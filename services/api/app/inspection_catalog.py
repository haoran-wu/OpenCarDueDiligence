"""Canonical first-party inspection checklist and trust-boundary helpers.

The public ``InspectionItem`` shape deliberately accepts labels, stages, and a
severity so old ``.ocdd`` packages remain readable.  None of those client
fields are authoritative.  This module reloads the first-party checklist by
``key`` at ingestion and again whenever stored cases are analyzed or compared.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from .models import (
    FuelType,
    InspectionItem,
    InspectionResult,
    InspectionSessionInput,
    RiskArea,
    Severity,
    VehicleSpec,
)


ChecklistStage = Literal["pre_visit", "exterior", "interior", "road_test", "ppi"]


def _checklist_path() -> Path:
    override = os.getenv("OCDD_DATA_ROOT")
    if override:
        return Path(override) / "checklists" / "five_stage_inspection_v1.yaml"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "checklists" / "five_stage_inspection_v1.yaml"
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "inspection checklist not found; set OCDD_DATA_ROOT to the packaged data directory"
    )


_CHECKLIST_PATH = _checklist_path()
_STAGE_MAP: dict[str, ChecklistStage] = {
    "pre_visit": "pre_visit",
    "exterior_structure": "exterior",
    "interior_electrical": "interior",
    "cold_start_road_test": "road_test",
    "lift_ppi": "ppi",
}

# These are narrow identity/title gates, not a general claim that every safety
# concern should automatically reject a vehicle.  A confirmed FAIL on one of
# them is fail-closed; brakes, rust, warning lamps, and other critical checks
# remain HIGH/INSPECT until the evidence is independently resolved.
FAIL_CLOSED_KEYS = frozenset(
    {
        "vin_received",
        "title_photo_redacted",
        "seller_identity_match_plan",
        "vin_all_locations",
    }
)

_SAFE_CUSTOM_KEY_RE = re.compile(r"[^a-zA-Z0-9_.:-]+")


class InspectionCatalogError(ValueError):
    """A submitted inspection contradicts canonical checklist requirements."""


@dataclass(frozen=True, slots=True)
class InspectionCatalogItem:
    key: str
    label_en: str
    label_zh: str
    stage: ChecklistStage
    source_stage: str
    weight: int
    critical: bool
    applicability: str | None

    @property
    def severity_if_failed(self) -> Severity:
        if self.key in FAIL_CLOSED_KEYS:
            return Severity.CRITICAL
        return Severity.HIGH if self.critical else Severity.MEDIUM

    @property
    def requires_ppi(self) -> bool:
        return self.stage == "ppi"


@dataclass(frozen=True, slots=True)
class CanonicalInspectionItem:
    item: InspectionItem
    catalog_item: InspectionCatalogItem | None

    @property
    def recognized(self) -> bool:
        return self.catalog_item is not None


@lru_cache(maxsize=1)
def inspection_catalog() -> dict[str, InspectionCatalogItem]:
    """Load and validate the checked-in checklist as the server authority."""

    raw = json.loads(_CHECKLIST_PATH.read_text(encoding="utf-8"))
    catalog: dict[str, InspectionCatalogItem] = {}
    for stage in raw.get("stages", []):
        source_stage = str(stage["id"])
        try:
            canonical_stage = _STAGE_MAP[source_stage]
        except KeyError as exc:  # fail startup/tests instead of silently trusting drift
            raise RuntimeError(
                f"unknown inspection checklist stage: {source_stage}"
            ) from exc
        for raw_item in stage.get("items", []):
            key = str(raw_item["id"])
            if key in catalog:
                raise RuntimeError(f"duplicate inspection checklist key: {key}")
            catalog[key] = InspectionCatalogItem(
                key=key,
                label_en=str(raw_item["label_en"]),
                label_zh=str(raw_item["label_zh"]),
                stage=canonical_stage,
                source_stage=source_stage,
                weight=int(raw_item["weight"]),
                critical=bool(raw_item["critical"]),
                applicability=(
                    str(raw_item["applicability"])
                    if raw_item.get("applicability") is not None
                    else None
                ),
            )
    if not catalog:
        raise RuntimeError("inspection checklist contains no items")
    return catalog


def _is_manual(vehicle: VehicleSpec) -> bool | None:
    transmission = (vehicle.transmission or "").strip().lower()
    if not transmission:
        return None
    if "automatic" in transmission or "cvt" in transmission:
        return False
    return "manual" in transmission or bool(
        re.search(r"\b[4567]-speed\b", transmission)
    )


def catalog_item_applicable(
    item: InspectionCatalogItem,
    vehicle: VehicleSpec,
) -> bool | None:
    """Return True/False when applicability is knowable, otherwise None."""

    if item.applicability == "manual_only":
        return _is_manual(vehicle)
    if item.applicability == "hybrid_or_EV":
        if vehicle.fuel_type == FuelType.UNKNOWN:
            return None
        return vehicle.fuel_type in {
            FuelType.HYBRID,
            FuelType.PLUG_IN_HYBRID,
            FuelType.ELECTRIC,
        }
    # ``if_equipped`` and ``technician_indicated`` need an observation that is
    # not represented in VehicleSpec; the submitted NOT_APPLICABLE value is
    # retained, but the server never invents applicability.
    return True


def required_inspection_keys(
    vehicle: VehicleSpec,
    inspection_type: Literal["self", "ppi"],
) -> set[str]:
    """Return applicable canonical critical keys used by evidence coverage."""

    required: set[str] = set()
    for key, item in inspection_catalog().items():
        belongs = (
            item.requires_ppi if inspection_type == "ppi" else not item.requires_ppi
        )
        if not belongs or not item.critical:
            continue
        applicable = catalog_item_applicable(item, vehicle)
        # Unknown applicability is still an unknown check, not permission to
        # remove the item from the denominator.  Only an explicitly resolved
        # False (for example gasoline or a known automatic) may exclude it.
        if applicable is not False:
            required.add(key)
    return required


def _custom_label(key: str) -> str:
    safe_key = _SAFE_CUSTOM_KEY_RE.sub("_", key).strip("_.:-")[:80]
    return f"Custom inspection item: {safe_key or 'unnamed'}"


def canonicalize_inspection_item(
    item: InspectionItem,
    *,
    vehicle: VehicleSpec,
    inspection_type: Literal["self", "ppi"],
    strict_session: bool = False,
) -> CanonicalInspectionItem:
    """Ignore untrusted presentation/risk fields and normalize by item key.

    ``strict_session`` is enabled at API ingestion.  It rejects a professional
    lift/PPI checklist item presented as a self-inspection.  Stored legacy
    cases remain parseable; analysis still recalculates their severity and does
    not award invalid coverage.
    """

    catalog_item = inspection_catalog().get(item.key)
    if catalog_item is None:
        severity = (
            Severity.HIGH if item.result == InspectionResult.FAIL else Severity.MEDIUM
        )
        normalized = item.model_copy(
            update={
                "label": _custom_label(item.key),
                "stage": "ppi" if inspection_type == "ppi" else "pre_visit",
                "severity_if_failed": severity,
            }
        )
        return CanonicalInspectionItem(item=normalized, catalog_item=None)

    if strict_session and catalog_item.requires_ppi and inspection_type != "ppi":
        raise InspectionCatalogError(
            f"inspection item '{item.key}' requires inspectionType=ppi"
        )

    result = item.result
    if catalog_item_applicable(catalog_item, vehicle) is False:
        result = InspectionResult.NOT_APPLICABLE
    normalized = item.model_copy(
        update={
            "label": catalog_item.label_en,
            "stage": catalog_item.stage,
            "result": result,
            "severity_if_failed": catalog_item.severity_if_failed,
        }
    )
    return CanonicalInspectionItem(item=normalized, catalog_item=catalog_item)


def normalize_inspection_session(
    payload: InspectionSessionInput,
    *,
    vehicle: VehicleSpec,
) -> InspectionSessionInput:
    """Canonicalize an API submission and enforce PPI authorship claims."""

    normalized_items = [
        canonicalize_inspection_item(
            item,
            vehicle=vehicle,
            inspection_type=payload.inspection_type,
            strict_session=True,
        )
        for item in payload.items
    ]
    if payload.inspection_type == "ppi" and not (payload.inspector or "").strip():
        raise InspectionCatalogError(
            "PPI inspection sessions require a non-empty inspector"
        )
    return payload.model_copy(
        update={"items": [item.item for item in normalized_items]}
    )


def inspection_risk_area(key: str) -> RiskArea:
    """Map first-party keys to broad risk areas without trusting a client label."""

    if key in {"title_photo_redacted"}:
        return RiskArea.TITLE
    if key in {"vin_received", "seller_identity_match_plan", "vin_all_locations"}:
        return RiskArea.IDENTITY
    if key in {"brakes", "brake_measurements"}:
        return RiskArea.BRAKES
    if key in {"transmission", "clutch"}:
        return RiskArea.TRANSMISSION
    if key in {
        "overspray_welds",
        "rust",
        "flood_signs",
        "structural_underbody",
    }:
        return RiskArea.STRUCTURE
    if key in {
        "warning_lamp_self_test",
        "module_coverage",
        "restraints",
        "steering_suspension",
        "steering_suspension_lift",
        "full_module_scan",
    }:
        return RiskArea.SAFETY
    if key in {
        "start_quality",
        "fluids_temperature",
        "leaks",
        "cooling_pressure",
        "compression_leakdown",
    }:
        return RiskArea.ENGINE
    if key in {"exhaust_emissions", "post_drive_scan"}:
        return RiskArea.EMISSIONS
    return RiskArea.OTHER


def checklist_public_payload() -> dict[str, object]:
    """Return a read-only, UI-safe representation of the canonical checklist."""

    raw = json.loads(_CHECKLIST_PATH.read_text(encoding="utf-8"))
    stages: list[dict[str, object]] = []
    by_key = inspection_catalog()
    for raw_stage in raw["stages"]:
        items = []
        for raw_item in raw_stage["items"]:
            canonical = by_key[raw_item["id"]]
            items.append(
                {
                    "key": canonical.key,
                    "labelEn": canonical.label_en,
                    "labelZh": canonical.label_zh,
                    "stage": canonical.stage,
                    "weight": canonical.weight,
                    "critical": canonical.critical,
                    "severityIfFailed": canonical.severity_if_failed.value,
                    "applicability": canonical.applicability,
                    "requiresPpi": canonical.requires_ppi,
                }
            )
        stages.append(
            {
                "id": _STAGE_MAP[raw_stage["id"]],
                "sourceId": raw_stage["id"],
                "order": raw_stage["order"],
                "titleEn": raw_stage["title_en"],
                "titleZh": raw_stage["title_zh"],
                "items": items,
            }
        )
    return {
        "schemaVersion": raw["schema_version"],
        "checklistVersion": raw["checklist_version"],
        "license": raw["license"],
        "defaultResult": raw["default_result"],
        "allowedResults": raw["allowed_results"],
        "unknownPolicy": raw["unknown_policy"],
        "stages": stages,
    }
