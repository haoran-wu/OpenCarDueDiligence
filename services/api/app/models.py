"""Shared domain models for the OpenCarDueDiligence API.

The models intentionally keep raw evidence separate from deterministic findings.
An unchecked item is represented as UNKNOWN; absence of a finding never means that
the vehicle was checked and passed.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class DomainModel(BaseModel):
    # Python and storage use snake_case. The public JSON API serializes camelCase
    # and accepts either spelling so local scripts remain ergonomic.
    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class Language(StrEnum):
    EN = "en"
    ZH_CN = "zh-CN"


class CaseStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    NEEDS_DATA = "NEEDS_DATA"
    REMOTE_SCREENED = "REMOTE_SCREENED"
    VIEW_SCHEDULED = "VIEW_SCHEDULED"
    SELF_INSPECTED = "SELF_INSPECTED"
    PPI_COMPLETE = "PPI_COMPLETE"
    NEGOTIATING = "NEGOTIATING"
    READY_TO_BUY = "READY_TO_BUY"
    PURCHASED = "PURCHASED"
    REGISTERED = "REGISTERED"
    REJECTED = "REJECTED"


class RetentionClass(StrEnum):
    """Lifecycle policy for a structured case.

    ``LOCAL`` and ``ACCOUNT`` cases do not receive an automatic expiry.
    ``ANONYMOUS`` is the cloud default and must always carry ``expires_at``.
    """

    LOCAL = "LOCAL"
    ANONYMOUS = "ANONYMOUS"
    ACCOUNT = "ACCOUNT"


class Decision(StrEnum):
    STOP = "STOP"
    INSPECT = "INSPECT"
    NEGOTIATE = "NEGOTIATE"
    BUY_CANDIDATE = "BUY_CANDIDATE"


class Confidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Severity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ComparisonRisk(StrEnum):
    """Risk value used by shortlist comparisons.

    ``Severity`` intentionally describes an observed finding and therefore has
    no UNKNOWN member.  A comparison axis also needs to represent that the
    relevant system was not verified; using INFO for that case would turn
    missing evidence into a false pass.
    """

    UNKNOWN = "UNKNOWN"
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    RESOLVED = "RESOLVED"


class InspectionResult(StrEnum):
    UNKNOWN = "UNKNOWN"
    PASS = "PASS"
    CONCERN = "CONCERN"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MatchStatus(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class SellerType(StrEnum):
    PRIVATE = "private"
    DEALER = "dealer"
    UNKNOWN = "unknown"


class ListingChannel(StrEnum):
    FACEBOOK_MARKETPLACE = "facebook_marketplace"
    CRAIGSLIST = "craigslist"
    CARS_COM = "cars_com"
    AUTOTRADER = "autotrader"
    DEALER = "dealer"
    CSV = "csv"
    USER_ENTRY = "user_entry"
    OTHER = "other"


class ReferenceKind(StrEnum):
    ASKING = "asking"
    SOLD = "sold"
    REFERENCE = "reference"


class EvidenceKind(StrEnum):
    LISTING = "listing"
    HISTORY_REPORT = "history_report"
    TITLE = "title"
    LIEN_RELEASE = "lien_release"
    RECEIPT = "receipt"
    STATE_INSPECTION = "state_inspection"
    SELLER_MESSAGE = "seller_message"
    PHOTO = "photo"
    OBD_SCAN = "obd_scan"
    SELF_INSPECTION = "self_inspection"
    PPI = "ppi"
    MARKET_COMPARABLE = "market_comparable"
    OFFICIAL_RULE = "official_rule"
    OTHER = "other"


class RiskArea(StrEnum):
    TITLE = "title"
    IDENTITY = "identity"
    HISTORY = "history"
    ODOMETER = "odometer"
    ENGINE = "engine"
    TRANSMISSION = "transmission"
    EMISSIONS = "emissions"
    BRAKES = "brakes"
    STRUCTURE = "structure"
    ELECTRICAL = "electrical"
    SAFETY = "safety"
    SELLER = "seller"
    DATA_QUALITY = "data_quality"
    OTHER = "other"


class DtcStatus(StrEnum):
    STORED = "stored"
    PENDING = "pending"
    PERMANENT = "permanent"


class ModuleCoverage(StrEnum):
    SCANNED = "SCANNED"
    NOT_SCANNED = "NOT_SCANNED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class ReadinessStatus(StrEnum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    UNKNOWN = "UNKNOWN"


class FuelType(StrEnum):
    GASOLINE = "gasoline"
    DIESEL = "diesel"
    HYBRID = "hybrid"
    PLUG_IN_HYBRID = "plug_in_hybrid"
    ELECTRIC = "electric"
    OTHER = "other"
    UNKNOWN = "unknown"


class VehicleSpec(DomainModel):
    vin: str | None = Field(default=None, min_length=11, max_length=17)
    year: int | None = Field(default=None, ge=1981, le=2100)
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    generation: str | None = None
    platform: str | None = None
    engine: str | None = None
    transmission: str | None = None
    drivetrain: str | None = None
    production_date: date | None = None
    fuel_type: FuelType = FuelType.UNKNOWN
    body_style: str | None = None
    odometer_miles: int | None = Field(default=None, ge=0, le=5_000_000)

    @field_validator("vin")
    @classmethod
    def normalize_vin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return "".join(value.upper().split())

    @property
    def powertrain_resolved(self) -> bool:
        return bool(
            self.year
            and self.make
            and self.model
            and self.generation
            and self.platform
            and self.engine
            and self.transmission
            and self.drivetrain
            and self.production_date
            and self.fuel_type != FuelType.UNKNOWN
        )


class SourceEnvelope(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_type: str
    provider: str = "user"
    source_url: str | None = None
    acquired_at: datetime = Field(default_factory=utc_now)
    observed_at: datetime = Field(default_factory=utc_now)
    effective_date: date | None = None
    license_name: str = "user-provided"
    redistribution: Literal["allowed", "restricted", "unknown"] = "restricted"
    credential_storage: str = "none"
    retention_policy: str = "case-controlled"
    content_sha256: str
    last_updated_at: datetime = Field(default_factory=utc_now)


class Evidence(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str
    kind: EvidenceKind
    label: str
    excerpt: str | None = Field(default=None, max_length=2000)
    page: int | None = Field(default=None, ge=1)
    observed_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_sensitive: bool = False
    redacted: bool = False


class HistoryEvent(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    event_date: date | None = None
    mileage: int | None = Field(default=None, ge=0)
    event_type: str
    description: str
    evidence_ids: list[str] = Field(default_factory=list)


class ListingInput(DomainModel):
    source_url: str | None = None
    title: str
    asking_price: float = Field(ge=0)
    currency: str = "USD"
    mileage: int | None = Field(default=None, ge=0)
    location: str | None = None
    listed_at: datetime | None = None
    seller_type: SellerType = SellerType.UNKNOWN
    channel: ListingChannel = ListingChannel.USER_ENTRY
    reference_kind: ReferenceKind = ReferenceKind.ASKING
    vin: str | None = None
    year: int | None = Field(default=None, ge=1981, le=2100)
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    generation: str | None = None
    platform: str | None = None
    engine: str | None = None
    transmission: str | None = None
    drivetrain: str | None = None
    production_date: date | None = None
    fuel_type: FuelType = FuelType.UNKNOWN
    body_style: str | None = None
    distance_miles: float | None = Field(default=None, ge=0)
    is_target: bool = False
    description: str | None = Field(default=None, max_length=10_000)
    captured_at: datetime = Field(default_factory=utc_now)

    @field_validator("vin")
    @classmethod
    def normalize_listing_vin(cls, value: str | None) -> str | None:
        return "".join(value.upper().split()) if value else None


class ListingSnapshot(ListingInput):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str
    evidence_id: str
    content_sha256: str


class ListingsImportRequest(DomainModel):
    listings: list[ListingInput] = Field(min_length=1, max_length=500)


class ListingsImportResponse(DomainModel):
    case_id: str
    imported: int
    listing_ids: list[str]
    evidence_ids: list[str]


class ListingPriceObservation(DomainModel):
    listing_id: str
    asking_price: float = Field(ge=0)
    captured_at: datetime
    evidence_id: str


class ListingWatchItem(DomainModel):
    key: str
    title: str
    source_url: str | None = None
    channel: ListingChannel
    observations: list[ListingPriceObservation] = Field(min_length=1)
    latest_price: float = Field(ge=0)
    absolute_change: float = 0
    percent_change: float | None = None


class ListingWatchlistResponse(DomainModel):
    case_id: str
    items: list[ListingWatchItem]


class MoneyRange(DomainModel):
    low: float = Field(ge=0)
    likely: float = Field(ge=0)
    high: float = Field(ge=0)
    currency: str = "USD"

    @model_validator(mode="after")
    def ordered(self) -> "MoneyRange":
        if not self.low <= self.likely <= self.high:
            raise ValueError("money range must satisfy low <= likely <= high")
        return self


class NumberRange(DomainModel):
    low: float = Field(ge=0)
    likely: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> "NumberRange":
        if not self.low <= self.likely <= self.high:
            raise ValueError("range must satisfy low <= likely <= high")
        return self


class ShopType(StrEnum):
    DIY = "diy"
    INDEPENDENT = "independent"
    SPECIALIST = "specialist"
    DEALER = "dealer"


class RepairCostRequest(DomainModel):
    label: str
    zip3: str = Field(pattern=r"^\d{3}$")
    shop_type: ShopType
    diagnostic_fee: MoneyRange = Field(default_factory=lambda: MoneyRange(low=0, likely=0, high=0))
    parts: MoneyRange
    labor_hours: NumberRange
    hourly_rate: MoneyRange | None = None
    regional_multiplier: float = Field(default=1.0, ge=0.5, le=3.0)
    tax_rate: float = Field(default=0.0, ge=0, le=0.2)
    shop_supplies_rate: float = Field(default=0.05, ge=0, le=0.2)


class RepairCostResult(DomainModel):
    label: str
    zip3: str
    shop_type: ShopType
    total: MoneyRange
    hourly_rate: MoneyRange
    confidence: Confidence
    assumptions: list[str]
    formula: str = "diagnosis + parts + labor_hours × hourly_rate + tax + shop_supplies"


class RepairCostComparisonRequest(DomainModel):
    label: str
    zip3: str = Field(pattern=r"^\d{3}$")
    diagnostic_fee: MoneyRange = Field(default_factory=lambda: MoneyRange(low=0, likely=0, high=0))
    parts: MoneyRange
    labor_hours: NumberRange
    hourly_rates: dict[ShopType, MoneyRange] = Field(default_factory=dict)
    regional_multiplier: float = Field(default=1.0, ge=0.5, le=3.0)
    tax_rate: float = Field(default=0.0, ge=0, le=0.2)
    shop_supplies_rate: float = Field(default=0.05, ge=0, le=0.2)


class RepairCostComparisonResult(DomainModel):
    label: str
    zip3: str
    estimates: list[RepairCostResult] = Field(min_length=4, max_length=4)
    source_note: str = (
        "Default rates are broad national assumptions unless a user/provider supplied a rate; "
        "obtain local written quotes before negotiating."
    )


class RepairScenario(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    label: str
    system: RiskArea
    probability_label: Literal["minimum", "most_likely", "worst_reasonable"]
    cost: MoneyRange
    confirmation_tests: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.LOW
    shop_type: Literal["diy", "independent", "specialist", "dealer", "mixed"] = "mixed"


class RiskFinding(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    code: str
    area: RiskArea
    title: str
    detail: str
    severity: Severity
    status: FindingStatus = FindingStatus.SUSPECTED
    evidence_ids: list[str] = Field(default_factory=list)
    next_checks: list[str] = Field(default_factory=list)
    repair_scenarios: list[RepairScenario] = Field(default_factory=list)
    decision_impact: Decision | None = None
    blocks_purchase: bool = False


class DtcEntry(DomainModel):
    code: str = Field(pattern=r"^[PBCU][0-9A-F]{4}$")
    status: DtcStatus
    description: str | None = None
    module: str = "powertrain"

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.upper()


class ReadinessMonitor(DomainModel):
    name: str
    status: ReadinessStatus


class DiagnosticScanInput(DomainModel):
    scanned_at: datetime = Field(default_factory=utc_now)
    scanner_name: str = "manual entry"
    vin: str | None = None
    mil_on: bool | None = None
    dtcs: list[DtcEntry] = Field(default_factory=list)
    readiness: list[ReadinessMonitor] = Field(default_factory=list)
    module_coverage: dict[str, ModuleCoverage] = Field(
        default_factory=lambda: {
            "powertrain": ModuleCoverage.SCANNED,
            "abs": ModuleCoverage.UNKNOWN,
            "srs": ModuleCoverage.UNKNOWN,
            "body": ModuleCoverage.UNKNOWN,
        }
    )
    freeze_frame: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    live_pids: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    raw: dict[str, str] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=5000)
    evidence_label: str = "OBD scan"

    @model_validator(mode="before")
    @classmethod
    def accept_bridge_payload(cls, value: Any) -> Any:
        """Normalize the read-only OBD bridge wire format.

        The bridge deliberately exposes only generic emissions coverage. It emits
        ``codes`` and a readiness summary object, while manual input uses richer
        ``dtcs`` and monitor rows.
        """
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "codes" in data and "dtcs" not in data:
            data["dtcs"] = data.pop("codes")
        if "adapter" in data and "scanner_name" not in data and "scannerName" not in data:
            data["scanner_name"] = data.pop("adapter") or "ELM327"
        coverage = data.get("module_coverage", data.get("moduleCoverage"))
        if isinstance(coverage, list):
            normalized = {
                "powertrain": ModuleCoverage.SCANNED,
                "abs": ModuleCoverage.NOT_SCANNED,
                "srs": ModuleCoverage.NOT_SCANNED,
                "body": ModuleCoverage.NOT_SCANNED,
            }
            data["module_coverage"] = normalized
            data.pop("moduleCoverage", None)
        readiness = data.get("readiness")
        if isinstance(readiness, dict):
            monitors: list[dict[str, str]] = []
            for name, status in readiness.items():
                if isinstance(status, str) and status.lower() in {
                    "ready",
                    "not_ready",
                    "unsupported",
                    "unknown",
                }:
                    mapped = {
                        "ready": ReadinessStatus.READY,
                        "not_ready": ReadinessStatus.NOT_READY,
                        "unsupported": ReadinessStatus.NOT_SUPPORTED,
                        "unknown": ReadinessStatus.UNKNOWN,
                    }[status.lower()]
                    monitors.append({"name": name, "status": mapped})
            # Raw bit masks cannot be safely expanded into named monitors. Keep
            # an UNKNOWN marker rather than treating the monitors as ready.
            if not monitors:
                monitors.append({"name": "generic_readiness", "status": ReadinessStatus.UNKNOWN})
            data["readiness"] = monitors
            if "mil_on" in readiness and "mil_on" not in data:
                data["mil_on"] = readiness["mil_on"]
        return data


class DiagnosticScan(DiagnosticScanInput):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str
    evidence_id: str


class InspectionItem(DomainModel):
    key: str
    label: str
    stage: Literal["pre_visit", "exterior", "interior", "road_test", "ppi"]
    result: InspectionResult = InspectionResult.UNKNOWN
    notes: str | None = Field(default=None, max_length=5000)
    severity_if_failed: Severity = Severity.MEDIUM
    evidence_ids: list[str] = Field(default_factory=list)
    estimated_cost: MoneyRange | None = None


class InspectionSessionInput(DomainModel):
    inspected_at: datetime = Field(default_factory=utc_now)
    inspection_type: Literal["self", "ppi"]
    inspector: str | None = None
    items: list[InspectionItem] = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=10_000)


class InspectionSession(InspectionSessionInput):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str
    evidence_id: str


class ValuationResult(DomainModel):
    reference_kind: Literal[
        "asking_price_range",
        "sold_price_range",
        "reference_value_range",
        "mixed_reference",
    ]
    channel: SellerType | Literal["mixed"]
    weighted_median: float | None = Field(default=None, ge=0)
    q25: float = Field(ge=0)
    q75: float = Field(ge=0)
    sample_count: int = Field(ge=0)
    radius_miles: int = Field(ge=0)
    max_age_days: int = Field(ge=0)
    confidence: Confidence
    low_sample_warning: bool
    comparable_listing_ids: list[str] = Field(default_factory=list)
    excluded_count: int = Field(default=0, ge=0)
    calculated_at: datetime = Field(default_factory=utc_now)


class ArtifactCreate(DomainModel):
    filename: str
    kind: EvidenceKind
    media_type: str = "text/plain"
    text: str | None = None
    content_base64: str | None = None
    label: str | None = None
    page: int | None = Field(default=None, ge=1)
    sensitive_fields: list[str] = Field(default_factory=list)
    identity_title_match: MatchStatus | None = None
    # These names exist only long enough for an exact, normalized server-side
    # comparison.  ``exclude=True`` keeps them out of model dumps, persistence,
    # worker payloads, and API responses.  The evidence ledger stores only the
    # resulting MATCH/MISMATCH status.
    title_owner_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        exclude=True,
        repr=False,
    )
    seller_legal_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        exclude=True,
        repr=False,
    )

    @model_validator(mode="after")
    def has_content(self) -> "ArtifactCreate":
        if (self.text is None) == (self.content_base64 is None):
            raise ValueError("provide exactly one of text or content_base64")
        if self.identity_title_match is not None and self.kind != EvidenceKind.TITLE:
            raise ValueError("identityTitleMatch is accepted only for title artifacts")
        supplied_names = (self.title_owner_name is not None, self.seller_legal_name is not None)
        if any(supplied_names) and self.kind != EvidenceKind.TITLE:
            raise ValueError("title identity names are accepted only for title artifacts")
        if supplied_names[0] != supplied_names[1]:
            raise ValueError("provide both titleOwnerName and sellerLegalName")
        return self


class ArtifactReceipt(DomainModel):
    artifact_id: str
    evidence_id: str
    content_sha256: str
    expires_at: datetime | None
    redactions: list[str]
    extracted_pages: int = 0


class OCDDImportRequest(DomainModel):
    content_base64: str
    passphrase: str = Field(min_length=8, max_length=1024)
    retention_class: RetentionClass | None = None


class OCDDImportResponse(DomainModel):
    case_id: str
    schema_version: str
    integrity_verified: bool
    attachments_imported: int = 0


class CaseCreate(DomainModel):
    language: Language = Language.EN
    buyer_goal: str | None = Field(default=None, max_length=2000)
    all_in_budget: float | None = Field(default=None, gt=0)
    vehicle: VehicleSpec = Field(default_factory=VehicleSpec)
    retention_class: RetentionClass | None = None


class CaseStatusEvent(DomainModel):
    from_status: CaseStatus | None = None
    to_status: CaseStatus
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    occurred_at: datetime = Field(default_factory=utc_now)


class CaseStatusUpdate(DomainModel):
    status: CaseStatus
    reason: str = Field(min_length=3, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list)


class CaseContext(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: CaseStatus = CaseStatus.DISCOVERED
    decision: Decision = Decision.INSPECT
    language: Language = Language.EN
    buyer_goal: str | None = None
    all_in_budget: float | None = None
    vehicle: VehicleSpec = Field(default_factory=VehicleSpec)
    sources: list[SourceEnvelope] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    history: list[HistoryEvent] = Field(default_factory=list)
    listings: list[ListingSnapshot] = Field(default_factory=list)
    scans: list[DiagnosticScan] = Field(default_factory=list)
    inspections: list[InspectionSession] = Field(default_factory=list)
    findings: list[RiskFinding] = Field(default_factory=list)
    valuation: ValuationResult | None = None
    transaction_context: dict[str, Any] | None = None
    transaction_plan: dict[str, Any] | None = None
    coverage_percent: float = Field(default=0, ge=0, le=100)
    unknowns: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    status_history: list[CaseStatusEvent] = Field(default_factory=list)
    retention_class: RetentionClass = RetentionClass.LOCAL
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_retention_window(self) -> "CaseContext":
        if self.retention_class == RetentionClass.ANONYMOUS:
            if self.expires_at is None:
                raise ValueError("ANONYMOUS cases require expires_at")
            if self.expires_at.tzinfo is None:
                raise ValueError("expires_at must include a timezone")
        elif self.expires_at is not None:
            raise ValueError(f"{self.retention_class.value} cases cannot expire automatically")
        return self


class AnalyzeRequest(DomainModel):
    comparables: list[ListingInput] = Field(default_factory=list, max_length=1000)
    buyer_all_in_budget: float | None = Field(default=None, gt=0)
    force: bool = False


class AnalysisResult(DomainModel):
    case_id: str
    decision: Decision
    coverage_percent: float = Field(ge=0, le=100)
    valuation: ValuationResult | None
    findings: list[RiskFinding]
    unknowns: list[str]
    next_actions: list[str]
    generated_at: datetime = Field(default_factory=utc_now)


class AdjustmentCategory(StrEnum):
    IMMEDIATE_REPAIR = "immediate_repair"
    OVERDUE_MAINTENANCE = "overdue_maintenance"
    ABNORMAL_RISK = "abnormal_risk"


class NegotiationPhase(StrEnum):
    INITIAL_CONTACT = "initial_contact"
    CONDITIONAL_OFFER = "conditional_offer"
    POST_PPI = "post_ppi"
    WALK_AWAY = "walk_away"


class NegotiationAdjustment(DomainModel):
    label: str
    category: AdjustmentCategory
    amount: float = Field(ge=0)
    normal_wear: bool = False
    finding_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class NegotiationRequest(DomainModel):
    phase: NegotiationPhase
    language: Language | None = None
    # Initial-contact drafts are screening questions, not price offers.  Their
    # request therefore does not need valuation or budget arithmetic.  The
    # negotiation engine still requires all three fields for offer phases.
    asking_price: float | None = Field(default=None, ge=0)
    market_baseline: float | None = Field(default=None, gt=0)
    all_in_budget: float | None = Field(default=None, gt=0)
    evidence_coverage: float | None = Field(default=None, ge=0, le=100)
    adjustments: list[NegotiationAdjustment] = Field(default_factory=list)
    buyer_mandatory_costs: float = Field(default=0, ge=0)
    seller_floor: float | None = Field(default=None, ge=0)


class NegotiationTraceItem(DomainModel):
    label: str
    amount: float
    applied: bool
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class NegotiationState(DomainModel):
    case_id: str | None = None
    phase: NegotiationPhase
    target: float | None = Field(default=None, ge=0)
    opening: float | None = Field(default=None, ge=0)
    ceiling: float | None = Field(default=None, ge=0)
    evidence_reserve: float = Field(ge=0)
    decision: Literal["INSPECT_FIRST", "MAKE_OFFER", "WALK_AWAY", "WAIT"]
    trace: list[NegotiationTraceItem]
    message: str
    language: Language


class TitleStatus(StrEnum):
    ORIGINAL = "ORIGINAL"
    MISSING = "MISSING"
    ALTERED = "ALTERED"
    ALREADY_ASSIGNED = "ALREADY_ASSIGNED"
    BRANDED = "BRANDED"
    UNKNOWN = "UNKNOWN"


class LienStatus(StrEnum):
    CLEAR = "CLEAR"
    RELEASE_ATTACHED = "RELEASE_ATTACHED"
    ACTIVE = "ACTIVE"
    UNKNOWN = "UNKNOWN"


class TransportOption(StrEnum):
    TOW = "tow"
    CARRIER = "carrier"
    VALID_TEMP_PERMIT = "valid_temp_permit"
    VALID_REGISTRATION_AND_PLATE = "valid_registration_and_plate"
    SELLER_PLATE = "seller_plate"
    BORROWED_PLATE = "borrowed_plate"
    DRIVE_UNREGISTERED = "drive_unregistered"
    UNDECIDED = "undecided"


class TransactionContext(DomainModel):
    purchase_date: date
    buyer_residence_state: str = Field(min_length=2, max_length=2)
    license_state: str = Field(min_length=2, max_length=2)
    garaging_state: str = Field(min_length=2, max_length=2)
    registration_state: str = Field(min_length=2, max_length=2)
    sale_state: str = Field(min_length=2, max_length=2)
    title_state: str = Field(min_length=2, max_length=2)
    seller_type: SellerType = SellerType.PRIVATE
    title_status: TitleStatus = TitleStatus.UNKNOWN
    lien_status: LienStatus = LienStatus.UNKNOWN
    identity_title_match: MatchStatus = MatchStatus.UNKNOWN
    vin_match: MatchStatus = MatchStatus.UNKNOWN
    seller_allows_ppi: bool | None = None
    seller_allows_bill_of_sale: bool | None = None
    seller_will_disclose_odometer: bool | None = None
    insurance_active_for_vin: bool = False
    transport_option: TransportOption = TransportOption.UNDECIDED
    vehicle: VehicleSpec
    current_inspection_status: InspectionResult = InspectionResult.UNKNOWN
    current_emissions_status: InspectionResult = InspectionResult.UNKNOWN

    @field_validator(
        "buyer_residence_state",
        "license_state",
        "garaging_state",
        "registration_state",
        "sale_state",
        "title_state",
    )
    @classmethod
    def uppercase_state(cls, value: str) -> str:
        return value.upper()


class TransactionGate(DomainModel):
    code: str
    label: str
    blocked: bool
    reason: str
    evidence_needed: str | None = None


class TransactionStep(DomainModel):
    order: int = Field(ge=1)
    category: Literal[
        "pre_payment",
        "signing",
        "transport",
        "insurance",
        "title_registration",
        "tax_fee",
        "inspection_emissions",
    ]
    title: str
    detail: str
    deadline: str | None = None
    official_url: str | None = None
    verified_as_of: date | None = None
    requires_confirmation: bool = False


class TransactionPlan(DomainModel):
    decision: Decision
    can_legally_drive_away: bool
    gates: list[TransactionGate]
    steps: list[TransactionStep]
    warnings: list[str] = Field(default_factory=list)
    rules_verified_as_of: date | None = None
    generated_at: datetime = Field(default_factory=utc_now)


class CompareRequest(DomainModel):
    case_ids: list[str] = Field(min_length=2, max_length=25)
    # Anonymous cloud cases are capability-protected. The mapping is optional
    # so local/offline clients retain their simpler request shape.
    access_tokens: dict[str, str] = Field(default_factory=dict)


class ComparisonRow(DomainModel):
    case_id: str
    rank: int = Field(ge=1)
    decision: Decision
    asking_price: float | None = None
    price_attractiveness: float | None = Field(default=None, ge=-100, le=100)
    mechanical_risk: ComparisonRisk
    title_risk: ComparisonRisk
    coverage_percent: float
    unresolved_planning_exposure: MoneyRange | None = Field(
        default=None,
        description=(
            "Comparison-only planning sum of the most-likely repair branches "
            "for unresolved findings; not a 12-month expected-cost forecast."
        ),
    )
    reason: str


class CompareResponse(DomainModel):
    ranked: list[ComparisonRow]
    generated_at: datetime = Field(default_factory=utc_now)


class ReportResponse(DomainModel):
    case_id: str
    language: Language
    decision: Decision
    summary: str
    valuation: ValuationResult | None
    findings: list[RiskFinding]
    evidence_index: list[Evidence]
    unknowns: list[str]
    next_actions: list[str]
    disclaimer: str
    generated_at: datetime = Field(default_factory=utc_now)
