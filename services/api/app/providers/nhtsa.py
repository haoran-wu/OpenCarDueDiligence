"""Read-only clients for the official NHTSA vPIC and recalls APIs.

The provider deliberately keeps VIN decoding separate from model-level recall
signals.  NHTSA's public ``recallsByVehicle`` endpoint accepts model year, make,
and model -- not a VIN -- so its results cannot establish VIN applicability or
repair completion.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import httpx
from pydantic import Field

from ..models import DomainModel, FuelType, SourceEnvelope, VehicleSpec


VPIC_API_BASE = "https://vpic.nhtsa.dot.gov/api/vehicles"
RECALLS_API_BASE = "https://api.nhtsa.gov/recalls"
VPIC_DOCUMENTATION_URL = "https://vpic.nhtsa.dot.gov/api/Home/Index"
NHTSA_DATASETS_URL = "https://www.nhtsa.gov/nhtsa-datasets-and-apis"
NHTSA_VIN_RECALL_LOOKUP_URL = "https://www.nhtsa.gov/recalls"

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


class NhtsaProviderError(RuntimeError):
    """Base exception safe to translate to a generic API error."""


class NhtsaProviderTimeout(NhtsaProviderError):
    """The authoritative service did not answer within the configured timeout."""


class NhtsaProviderUnavailable(NhtsaProviderError):
    """The authoritative service returned an error or malformed response."""


class VinDecodeResponse(DomainModel):
    vin: str
    decode_valid: bool
    error_code: str | None = None
    error_text: str | None = None
    vehicle: VehicleSpec
    manufacturer: str | None = None
    vehicle_type: str | None = None
    plant_city: str | None = None
    plant_country: str | None = None
    decoded_fields: dict[str, str] = Field(default_factory=dict)
    source: SourceEnvelope
    documentation_url: str = VPIC_DOCUMENTATION_URL
    limitations: list[str] = Field(default_factory=list)


class VinDecodeQuery(DomainModel):
    """VIN decode input carried in a request body so access logs omit the VIN."""

    vin: str = Field(min_length=11, max_length=32)
    model_year: int | None = Field(default=None, ge=1981, le=2100)


class RecallSignalQuery(DomainModel):
    model_year: int = Field(ge=1981, le=2100)
    make: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=150)


class RecallSignal(DomainModel):
    nhtsa_campaign_number: str
    manufacturer: str | None = None
    component: str | None = None
    report_received_date: str | None = None
    summary: str | None = None
    consequence: str | None = None
    remedy: str | None = None
    notes: str | None = None
    park_it: bool | None = None
    park_outside: bool | None = None
    over_the_air_update: bool | None = None


class RecallSignalsResponse(DomainModel):
    query: RecallSignalQuery
    scope: str = "MODEL_YEAR_MAKE_MODEL_SIGNAL"
    count: int
    recalls: list[RecallSignal]
    vehicle_specific: bool = False
    vin_completion_verified: bool = False
    disclaimer: str
    source: SourceEnvelope
    documentation_url: str = NHTSA_DATASETS_URL
    official_vin_lookup_url: str = NHTSA_VIN_RECALL_LOOKUP_URL


def normalize_vin(vin: str) -> str:
    """Normalize and validate a complete North-American style VIN."""

    normalized = "".join(vin.upper().split())
    if not _VIN_RE.fullmatch(normalized):
        raise ValueError(
            "VIN must contain exactly 17 characters and cannot contain I, O, or Q"
        )
    return normalized


def _canonical_sha256(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(serialized).hexdigest()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_int(value: Any) -> int | None:
    try:
        normalized = _optional_text(value)
        return int(normalized) if normalized is not None else None
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = (_optional_text(value) or "").lower()
    if normalized in {"true", "yes", "y", "1"}:
        return True
    if normalized in {"false", "no", "n", "0"}:
        return False
    return None


def _join_nonempty(*values: Any) -> str | None:
    parts = [part for value in values if (part := _optional_text(value))]
    return " / ".join(parts) or None


def _fuel_type(value: Any) -> FuelType:
    normalized = (_optional_text(value) or "").lower()
    if "plug-in" in normalized or "plug in" in normalized:
        return FuelType.PLUG_IN_HYBRID
    if "hybrid" in normalized:
        return FuelType.HYBRID
    if "electric" in normalized:
        return FuelType.ELECTRIC
    if "diesel" in normalized:
        return FuelType.DIESEL
    if "gasoline" in normalized or "gas" == normalized:
        return FuelType.GASOLINE
    return FuelType.UNKNOWN


class NhtsaProvider:
    """Small synchronous official-data provider with injectable HTTP transport."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        self._transport = transport
        self._timeout = httpx.Timeout(timeout_seconds)

    def _get_json(
        self, url: str, *, params: dict[str, str | int]
    ) -> tuple[dict[str, Any], str, datetime]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "OpenCarDueDiligence/0.1 official-data-client",
        }
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=True,
                headers=headers,
            ) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                observed_at = datetime.now(timezone.utc)
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise NhtsaProviderTimeout("NHTSA request timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise NhtsaProviderUnavailable("NHTSA request failed") from exc
        if not isinstance(payload, dict):
            raise NhtsaProviderUnavailable("NHTSA returned an unexpected response")
        return payload, str(response.request.url), observed_at

    @staticmethod
    def _source(
        *,
        source_type: str,
        provider: str,
        source_url: str,
        payload: dict[str, Any],
        observed_at: datetime,
    ) -> SourceEnvelope:
        return SourceEnvelope(
            source_type=source_type,
            provider=provider,
            source_url=source_url,
            acquired_at=observed_at,
            observed_at=observed_at,
            license_name="NHTSA Open Data (U.S. Government)",
            redistribution="allowed",
            credential_storage="none",
            retention_policy="provider-response-not-persisted",
            content_sha256=_canonical_sha256(payload),
            last_updated_at=observed_at,
        )

    def decode_vin(
        self, vin: str, *, model_year: int | None = None
    ) -> VinDecodeResponse:
        normalized_vin = normalize_vin(vin)
        params: dict[str, str | int] = {"format": "json"}
        if model_year is not None:
            if not 1981 <= model_year <= 2100:
                raise ValueError("modelYear must be between 1981 and 2100")
            params["modelyear"] = model_year
        payload, source_url, observed_at = self._get_json(
            f"{VPIC_API_BASE}/DecodeVinValuesExtended/{normalized_vin}",
            params=params,
        )
        results = payload.get("Results")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise NhtsaProviderUnavailable("NHTSA vPIC returned no decodable result")
        result: dict[str, Any] = results[0]
        error_code = _optional_text(result.get("ErrorCode"))
        code_parts = [part.strip() for part in (error_code or "").split(",") if part.strip()]
        decode_valid = bool(code_parts) and all(part == "0" for part in code_parts)

        engine = _join_nonempty(
            result.get("EngineModel"),
            (
                f"{result['DisplacementL']}L"
                if _optional_text(result.get("DisplacementL"))
                else None
            ),
            (
                f"{result['EngineCylinders']} cylinders"
                if _optional_text(result.get("EngineCylinders"))
                else None
            ),
            result.get("EngineConfiguration"),
        )
        transmission = _join_nonempty(
            result.get("TransmissionStyle"),
            (
                f"{result['TransmissionSpeeds']} speeds"
                if _optional_text(result.get("TransmissionSpeeds"))
                else None
            ),
        )
        decoded_vin = _optional_text(result.get("VIN")) or normalized_vin
        vehicle = VehicleSpec(
            vin=decoded_vin,
            year=_optional_int(result.get("ModelYear")) or model_year,
            make=_optional_text(result.get("Make")),
            model=_optional_text(result.get("Model")),
            trim=(
                _optional_text(result.get("Trim"))
                or _optional_text(result.get("Series"))
            ),
            engine=engine,
            transmission=transmission,
            drivetrain=_optional_text(result.get("DriveType")),
            fuel_type=_fuel_type(result.get("FuelTypePrimary")),
            body_style=_optional_text(result.get("BodyClass")),
        )
        trace_fields = (
            "VIN",
            "ModelYear",
            "Make",
            "Model",
            "Trim",
            "Series",
            "Series2",
            "BodyClass",
            "VehicleType",
            "Manufacturer",
            "EngineModel",
            "DisplacementL",
            "EngineCylinders",
            "EngineConfiguration",
            "FuelTypePrimary",
            "TransmissionStyle",
            "TransmissionSpeeds",
            "DriveType",
            "PlantCity",
            "PlantCountry",
        )
        decoded_fields = {
            key: value
            for key in trace_fields
            if (value := _optional_text(result.get(key))) is not None
        }
        return VinDecodeResponse(
            vin=normalized_vin,
            decode_valid=decode_valid,
            error_code=error_code,
            error_text=_optional_text(result.get("ErrorText")),
            vehicle=vehicle,
            manufacturer=_optional_text(result.get("Manufacturer")),
            vehicle_type=_optional_text(result.get("VehicleType")),
            plant_city=_optional_text(result.get("PlantCity")),
            plant_country=_optional_text(result.get("PlantCountry")),
            decoded_fields=decoded_fields,
            source=self._source(
                source_type="official_vin_decode",
                provider="NHTSA vPIC",
                source_url=source_url,
                payload=payload,
                observed_at=observed_at,
            ),
            limitations=[
                "vPIC decodes manufacturer-submitted VIN attributes; blank fields remain unknown.",
                "A decode does not verify title, ownership, odometer accuracy, condition, or as-built options.",
                "This endpoint does not verify recall applicability or recall repair completion for the VIN.",
            ],
        )

    def recall_signals(self, query: RecallSignalQuery) -> RecallSignalsResponse:
        payload, source_url, observed_at = self._get_json(
            f"{RECALLS_API_BASE}/recallsByVehicle",
            params={
                "make": query.make,
                "model": query.model,
                "modelYear": query.model_year,
            },
        )
        raw_results = payload.get("results", payload.get("Results", []))
        if not isinstance(raw_results, list):
            raise NhtsaProviderUnavailable("NHTSA recalls returned malformed results")
        recalls: list[RecallSignal] = []
        for raw in raw_results:
            if not isinstance(raw, dict):
                continue
            campaign = _optional_text(raw.get("NHTSACampaignNumber"))
            if not campaign:
                continue
            recalls.append(
                RecallSignal(
                    nhtsa_campaign_number=campaign,
                    manufacturer=_optional_text(raw.get("Manufacturer")),
                    component=_optional_text(raw.get("Component")),
                    report_received_date=_optional_text(raw.get("ReportReceivedDate")),
                    summary=_optional_text(raw.get("Summary")),
                    consequence=_optional_text(raw.get("Consequence")),
                    remedy=_optional_text(raw.get("Remedy")),
                    notes=_optional_text(raw.get("Notes")),
                    park_it=_optional_bool(raw.get("parkIt")),
                    park_outside=_optional_bool(raw.get("parkOutSide")),
                    over_the_air_update=_optional_bool(raw.get("overTheAirUpdate")),
                )
            )
        return RecallSignalsResponse(
            query=query,
            count=len(recalls),
            recalls=recalls,
            disclaimer=(
                "These are model-year/make/model recall signals. A match does not prove that a "
                "specific VIN is included, that a recall remains open, or that a repair was "
                "completed. Verify the VIN with NHTSA's VIN recall lookup and the manufacturer."
            ),
            source=self._source(
                source_type="official_model_recall_signal",
                provider="NHTSA Recalls",
                source_url=source_url,
                payload=payload,
                observed_at=observed_at,
            ),
        )
