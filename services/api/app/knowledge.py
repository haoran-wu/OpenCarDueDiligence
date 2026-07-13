"""Publication-gated vehicle knowledge resolution.

Family names are discovery metadata, not mechanical applicability keys.  A
buyer-facing claim is released only when one *published* applicability pack
matches every required field of :class:`VehicleSpec` exactly (apart from case
and insignificant whitespace).  Missing data, draft packs, overlapping packs,
and near matches all remain ``UNKNOWN`` and route the buyer to ``INSPECT``.
"""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, field_validator, model_validator

from .models import Decision, DomainModel, VehicleSpec


class PublicationStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    DRAFT = "DRAFT"
    RETIRED = "RETIRED"
    BLOCKED_PENDING_RESEARCH_AND_HUMAN_REVIEW = (
        "BLOCKED_PENDING_RESEARCH_AND_HUMAN_REVIEW"
    )


class BilingualText(DomainModel):
    en: str = Field(min_length=1, max_length=4000)
    zh: str = Field(min_length=1, max_length=4000)


class KnowledgeRepairScenario(DomainModel):
    level: Literal["minimum", "most_likely", "worst_reasonable"]
    description: BilingualText
    planning_cost_usd: tuple[float, float] | None = None
    cost_confidence: Literal["UNKNOWN", "LOW", "MEDIUM", "HIGH"] = "UNKNOWN"
    cost_basis: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_cost(self) -> "KnowledgeRepairScenario":
        if self.planning_cost_usd is not None:
            low, high = self.planning_cost_usd
            if low < 0 or high < low:
                raise ValueError("planning cost must satisfy 0 <= low <= high")
            if not self.cost_basis:
                raise ValueError("a planning cost requires a dated cost_basis")
        elif self.cost_confidence != "UNKNOWN":
            raise ValueError("cost_confidence must be UNKNOWN when no cost is published")
        return self


class KnowledgeClaim(DomainModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: BilingualText
    summary: BilingualText
    symptoms: list[BilingualText] = Field(min_length=1)
    associated_dtcs: list[str] = Field(default_factory=list)
    stranding_or_safety_risk: BilingualText
    basic_obd_visibility: BilingualText
    confirmation_tests: list[BilingualText] = Field(min_length=1)
    repair_scenarios: list[KnowledgeRepairScenario] = Field(min_length=3, max_length=3)
    evidence_grade: Literal["A", "B", "C"]
    source_ids: list[str] = Field(min_length=1)
    reviewed_at: date

    @field_validator("associated_dtcs")
    @classmethod
    def normalize_dtcs(cls, values: list[str]) -> list[str]:
        normalized = [value.upper() for value in values]
        if any(
            len(value) != 5
            or value[0] not in "PBCU"
            or any(character not in "0123456789ABCDEF" for character in value[1:])
            for value in normalized
        ):
            raise ValueError("associated DTCs must be five-character OBD code patterns")
        return normalized

    @model_validator(mode="after")
    def require_three_scenarios(self) -> "KnowledgeClaim":
        levels = {scenario.level for scenario in self.repair_scenarios}
        expected = {"minimum", "most_likely", "worst_reasonable"}
        if levels != expected:
            raise ValueError("repair_scenarios must contain each three-scenario level once")
        return self


class KnowledgeSource(DomainModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    url_or_document_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    license_or_use_basis: str = Field(min_length=1)
    retrieved_at: date
    supports_claim_ids: list[str] = Field(min_length=1)


class KnowledgeApplicability(DomainModel):
    """A deliberately closed, exact US applicability key."""

    market: Literal["US"] = "US"
    model_year_start: int = Field(ge=1981, le=2100)
    model_year_end: int = Field(ge=1981, le=2100)
    generations: list[str] = Field(min_length=1)
    platforms: list[str] = Field(min_length=1)
    engines: list[str] = Field(min_length=1)
    transmissions: list[str] = Field(min_length=1)
    drivetrains: list[str] = Field(min_length=1)
    production_date_start: date
    production_date_end: date

    @model_validator(mode="after")
    def closed_range_without_wildcards(self) -> "KnowledgeApplicability":
        if self.model_year_start > self.model_year_end:
            raise ValueError("model-year range is reversed")
        if self.production_date_start > self.production_date_end:
            raise ValueError("production-date range is reversed")
        for field_name in (
            "generations",
            "platforms",
            "engines",
            "transmissions",
            "drivetrains",
        ):
            values = getattr(self, field_name)
            if any(not value.strip() or value.strip() == "*" for value in values):
                raise ValueError(f"{field_name} cannot contain blanks or wildcards")
        return self


class KnowledgeApplicabilityPack(DomainModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    publication_status: PublicationStatus
    applicability: KnowledgeApplicability
    claims: list[KnowledgeClaim] = Field(default_factory=list)
    sources: list[KnowledgeSource] = Field(default_factory=list)
    reviewed_at: date | None = None
    reviewer: str | None = None

    @model_validator(mode="after")
    def published_pack_has_auditable_claims(self) -> "KnowledgeApplicabilityPack":
        if self.publication_status != PublicationStatus.PUBLISHED:
            return self
        if not self.reviewed_at or not self.reviewer:
            raise ValueError("published packs require reviewed_at and reviewer")
        if not self.claims or not self.sources:
            raise ValueError("published packs require claims and sources")
        claim_ids = [claim.id for claim in self.claims]
        source_ids = [source.id for source in self.sources]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim IDs must be unique within a pack")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source IDs must be unique within a pack")
        known_claims = set(claim_ids)
        known_sources = set(source_ids)
        for claim in self.claims:
            unknown_sources = set(claim.source_ids) - known_sources
            if unknown_sources:
                raise ValueError(f"claim {claim.id} references unknown sources")
        for source in self.sources:
            unknown_claims = set(source.supports_claim_ids) - known_claims
            if unknown_claims:
                raise ValueError(f"source {source.id} references unknown claims")
        return self


class KnowledgeFamily(DomainModel):
    id: str
    make: str
    model: str
    vehicle_classes: list[str] = Field(default_factory=list)
    # Legacy scaffold keys remain visible and empty until researched. Runtime
    # claims can only be published through the closed applicability_packs key.
    generation_packs: list[dict[str, object]] = Field(default_factory=list)
    powertrain_packs: list[dict[str, object]] = Field(default_factory=list)
    applicability_packs: list[KnowledgeApplicabilityPack] = Field(default_factory=list)
    publication_status: PublicationStatus


class KnowledgeManifest(DomainModel):
    schema_version: str
    manifest_version: str
    license: str
    status: str
    warning: str
    governance: dict[str, object]
    placeholder_template: dict[str, object]
    families: list[KnowledgeFamily]

    @model_validator(mode="after")
    def unique_family_and_pack_ids(self) -> "KnowledgeManifest":
        family_ids = [family.id for family in self.families]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("family IDs must be unique")
        pack_ids = [
            pack.id for family in self.families for pack in family.applicability_packs
        ]
        if len(pack_ids) != len(set(pack_ids)):
            raise ValueError("applicability-pack IDs must be globally unique")
        return self


class KnowledgeFamilySummary(DomainModel):
    id: str
    make: str
    model: str
    vehicle_classes: list[str]
    publication_status: PublicationStatus
    pack_count: int
    published_pack_count: int
    published_claim_count: int


class KnowledgeFamilyListResponse(DomainModel):
    manifest_version: str
    license: str
    manifest_sha256: str
    families: list[KnowledgeFamilySummary]


class KnowledgeResolution(DomainModel):
    knowledge_status: Literal["RESOLVED", "UNKNOWN"]
    decision: Decision = Decision.INSPECT
    manifest_version: str
    manifest_sha256: str
    candidate_family_ids: list[str] = Field(default_factory=list)
    matched_pack_ids: list[str] = Field(default_factory=list)
    claims: list[KnowledgeClaim] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)


def _data_root() -> Path:
    override = os.getenv("OCDD_DATA_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        return root if root.name == "data" else root / "data"
    return Path(__file__).resolve().parents[3] / "data"


def _manifest_path() -> Path:
    override = os.getenv("OCDD_KNOWLEDGE_MANIFEST")
    if override:
        return Path(override).expanduser().resolve()
    return _data_root() / "knowledge" / "model_family_manifests_v1.yaml"


def _normalize_exact(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.casefold().split())


def _token_match(value: str, allowed: list[str]) -> bool:
    normalized = _normalize_exact(value)
    return any(normalized == _normalize_exact(candidate) for candidate in allowed)


class KnowledgeRegistry:
    def __init__(self, manifest: KnowledgeManifest, manifest_sha256: str) -> None:
        self.manifest = manifest
        self.manifest_sha256 = manifest_sha256

    @classmethod
    def load(cls, path: Path | None = None) -> "KnowledgeRegistry":
        raw = (path or _manifest_path()).read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        return cls(
            KnowledgeManifest.model_validate(payload),
            hashlib.sha256(raw).hexdigest(),
        )

    def list_families(self) -> KnowledgeFamilyListResponse:
        return KnowledgeFamilyListResponse(
            manifest_version=self.manifest.manifest_version,
            license=self.manifest.license,
            manifest_sha256=self.manifest_sha256,
            families=[
                KnowledgeFamilySummary(
                    id=family.id,
                    make=family.make,
                    model=family.model,
                    vehicle_classes=family.vehicle_classes,
                    publication_status=family.publication_status,
                    pack_count=len(family.applicability_packs),
                    published_pack_count=sum(
                        pack.publication_status == PublicationStatus.PUBLISHED
                        for pack in family.applicability_packs
                    ),
                    published_claim_count=sum(
                        len(pack.claims)
                        for pack in family.applicability_packs
                        if pack.publication_status == PublicationStatus.PUBLISHED
                    ),
                )
                for family in self.manifest.families
            ],
        )

    def _unknown(
        self,
        *,
        families: list[KnowledgeFamily] | None = None,
        packs: list[KnowledgeApplicabilityPack] | None = None,
        missing_fields: list[str] | None = None,
        reasons: list[str] | None = None,
    ) -> KnowledgeResolution:
        return KnowledgeResolution(
            knowledge_status="UNKNOWN",
            decision=Decision.INSPECT,
            manifest_version=self.manifest.manifest_version,
            manifest_sha256=self.manifest_sha256,
            candidate_family_ids=[family.id for family in families or []],
            matched_pack_ids=[pack.id for pack in packs or []],
            claims=[],
            missing_fields=missing_fields or [],
            blocked_reasons=list(dict.fromkeys(reasons or [])),
        )

    def resolve(self, vehicle: VehicleSpec) -> KnowledgeResolution:
        required = {
            "make": vehicle.make,
            "model": vehicle.model,
            "year": vehicle.year,
            "generation": vehicle.generation,
            "platform": vehicle.platform,
            "engine": vehicle.engine,
            "transmission": vehicle.transmission,
            "drivetrain": vehicle.drivetrain,
            "productionDate": vehicle.production_date,
        }
        missing = [name for name, value in required.items() if value is None]
        if vehicle.make is None or vehicle.model is None:
            return self._unknown(
                missing_fields=missing,
                reasons=["vehicle_make_and_model_are_required_for_family_selection"],
            )

        families = [
            family
            for family in self.manifest.families
            if _normalize_exact(family.make) == _normalize_exact(vehicle.make)
            and _normalize_exact(family.model) == _normalize_exact(vehicle.model)
        ]
        if not families:
            return self._unknown(
                missing_fields=missing,
                reasons=["no_manifest_for_exact_make_and_model"],
            )

        reasons: list[str] = []
        published_families = [
            family
            for family in families
            if family.publication_status == PublicationStatus.PUBLISHED
        ]
        for family in families:
            if family.publication_status != PublicationStatus.PUBLISHED:
                reasons.append(
                    f"family:{family.id}:publication_status:{family.publication_status.value}"
                )
            if not family.applicability_packs:
                reasons.append(f"family:{family.id}:has_no_applicability_packs")

        if missing:
            reasons.append("all_exact_applicability_fields_are_required")
            return self._unknown(
                families=families,
                missing_fields=missing,
                reasons=reasons,
            )
        if not published_families:
            return self._unknown(families=families, reasons=reasons)

        matching_packs: list[KnowledgeApplicabilityPack] = []
        matching_unpublished: list[KnowledgeApplicabilityPack] = []
        for family in published_families:
            for pack in family.applicability_packs:
                applies = pack.applicability
                matches = bool(
                    applies.model_year_start <= vehicle.year <= applies.model_year_end
                    and applies.production_date_start
                    <= vehicle.production_date
                    <= applies.production_date_end
                    and _token_match(vehicle.generation, applies.generations)
                    and _token_match(vehicle.platform, applies.platforms)
                    and _token_match(vehicle.engine, applies.engines)
                    and _token_match(vehicle.transmission, applies.transmissions)
                    and _token_match(vehicle.drivetrain, applies.drivetrains)
                )
                if not matches:
                    continue
                if pack.publication_status == PublicationStatus.PUBLISHED:
                    matching_packs.append(pack)
                else:
                    matching_unpublished.append(pack)

        if len(matching_packs) != 1:
            if matching_unpublished:
                reasons.extend(
                    f"pack:{pack.id}:publication_status:{pack.publication_status.value}"
                    for pack in matching_unpublished
                )
            if len(matching_packs) > 1:
                reasons.append("multiple_published_packs_match; applicability_is_ambiguous")
            else:
                reasons.append("no_single_exact_published_applicability_pack_matches")
            return self._unknown(
                families=families,
                packs=[*matching_packs, *matching_unpublished],
                reasons=reasons,
            )

        pack = matching_packs[0]
        return KnowledgeResolution(
            knowledge_status="RESOLVED",
            decision=Decision.INSPECT,
            manifest_version=self.manifest.manifest_version,
            manifest_sha256=self.manifest_sha256,
            candidate_family_ids=[family.id for family in families],
            matched_pack_ids=[pack.id],
            claims=pack.claims,
            missing_fields=[],
            blocked_reasons=[],
        )


router = APIRouter(prefix="/v1/knowledge", tags=["publication-gated knowledge"])


def get_knowledge_registry(request: Request) -> KnowledgeRegistry:
    injected = getattr(request.app.state, "knowledge_registry", None)
    if injected is not None:
        return injected
    try:
        return KnowledgeRegistry.load()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="vehicle knowledge manifest is unavailable or failed schema validation",
        ) from exc


KnowledgeRegistryDependency = Annotated[KnowledgeRegistry, Depends(get_knowledge_registry)]


@router.get("/families", response_model=KnowledgeFamilyListResponse)
def list_knowledge_families(
    registry: KnowledgeRegistryDependency,
) -> KnowledgeFamilyListResponse:
    return registry.list_families()


@router.post("/resolve", response_model=KnowledgeResolution)
def resolve_vehicle_knowledge(
    vehicle: VehicleSpec,
    registry: KnowledgeRegistryDependency,
) -> KnowledgeResolution:
    return registry.resolve(vehicle)
