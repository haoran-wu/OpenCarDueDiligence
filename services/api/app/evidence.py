"""Evidence ingestion, redaction, and lightweight document extraction."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .models import (
    ArtifactCreate,
    ArtifactReceipt,
    CaseContext,
    CaseStatus,
    Decision,
    Evidence,
    EvidenceKind,
    HistoryEvent,
    ListingInput,
    ListingSnapshot,
    MatchStatus,
    SourceEnvelope,
    utc_now,
)
from .artifact_store import TransientArtifactStore
from .document_processing import DocumentProcessor, InlineDocumentProcessor
from .ppi_trust import PPI_ARTIFACT_BINDING_BASIS


def _normalize_legal_name(value: str) -> str:
    """Normalize for a conservative exact identity comparison.

    This deliberately does not attempt fuzzy matching, transliteration, or
    nickname inference.  Those could turn two different people into a false
    MATCH.  Unicode letters and numbers are retained while punctuation and
    whitespace are collapsed.
    """

    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = "".join(
        character if unicodedata.category(character)[0] in {"L", "N"} else " "
        for character in normalized
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _title_identity_result(artifact: ArtifactCreate) -> tuple[MatchStatus, str]:
    if artifact.title_owner_name is not None and artifact.seller_legal_name is not None:
        owner = _normalize_legal_name(artifact.title_owner_name)
        seller = _normalize_legal_name(artifact.seller_legal_name)
        if not owner or not seller:
            raise ValueError("title identity names must contain letters or numbers")
        return (
            MatchStatus.MATCH if owner == seller else MatchStatus.MISMATCH,
            "server_exact_normalized",
        )
    if artifact.identity_title_match is not None:
        return artifact.identity_title_match, "user_attested"
    return MatchStatus.UNKNOWN, "not_checked"


def downgrade_imported_title_identity(case: CaseContext) -> CaseContext:
    """Remove title-identity trust that arrived inside a user-authored package.

    ``.ocdd`` encryption and hashes protect a package from accidental changes;
    they are not a server signature.  Imported metadata therefore cannot prove
    that ``server_exact_normalized`` was actually executed by this service.
    A fresh direct title upload/name comparison is required after every import.
    """

    downgraded = case.model_copy(deep=True)
    downgraded.evidence = [
        evidence.model_copy(
            update={
                "metadata": {
                    **evidence.metadata,
                    "identity_title_match": MatchStatus.UNKNOWN.value,
                    "identity_comparison_basis": "import_untrusted_requires_reverification",
                }
            }
        )
        if evidence.kind == EvidenceKind.TITLE
        else evidence
        for evidence in downgraded.evidence
    ]
    if downgraded.transaction_context:
        downgraded.transaction_context = {
            **downgraded.transaction_context,
            "identity_title_match": MatchStatus.UNKNOWN.value,
        }
    # A cached plan may have opened its identity gate from the now-downgraded
    # context. Rebuild it only after the caller submits fresh context.
    downgraded.transaction_plan = None
    if downgraded.decision == Decision.BUY_CANDIDATE:
        downgraded.decision = Decision.INSPECT
    reminder = "Re-verify seller identity against the original title after import"
    downgraded.next_actions = list(dict.fromkeys([reminder, *downgraded.next_actions]))
    return downgraded


def downgrade_imported_ppi_trust(case: CaseContext) -> CaseContext:
    """Require imported cases to re-upload the independent PPI report.

    An encrypted ``.ocdd`` package is integrity-checked but user-authored; its
    source provider and metadata are not a server signature.  Structured PPI
    checklist results remain useful as user attestations and risk signals, but
    they cannot retain artifact-bound coverage or a due-diligence status that
    depends on a verified PPI.
    """

    downgraded = case.model_copy(deep=True)
    downgraded.evidence = [
        evidence.model_copy(
            update={
                "metadata": {
                    **evidence.metadata,
                    "ppi_artifact_binding_basis": (
                        "import_untrusted_requires_reupload"
                    ),
                }
            }
        )
        if evidence.kind == EvidenceKind.PPI
        else evidence
        for evidence in downgraded.evidence
    ]
    ppi_source_ids = {
        session.source_id
        for session in downgraded.inspections
        if session.inspection_type == "ppi"
    }
    downgraded.sources = [
        source.model_copy(update={"provider": "user-attested-ppi"})
        if source.id in ppi_source_ids
        else source
        for source in downgraded.sources
    ]
    if downgraded.status in {
        CaseStatus.PPI_COMPLETE,
        CaseStatus.NEGOTIATING,
        CaseStatus.READY_TO_BUY,
    }:
        downgraded.status = CaseStatus.NEEDS_DATA
        # Imported status events are useful history, but after a trust
        # downgrade they cannot remain a server-audited lifecycle chain.
        downgraded.status_history = []
    if downgraded.decision not in {Decision.STOP, Decision.INSPECT}:
        downgraded.decision = Decision.INSPECT
    reminder = "Re-upload and link the independent PPI report after import"
    downgraded.next_actions = list(dict.fromkeys([reminder, *downgraded.next_actions]))
    return downgraded


PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
TITLE_NUMBER_RE = re.compile(
    r"\b(?:title|document|registration)\s*(?:number|no\.?|#)\s*[:#-]?\s*[A-Z0-9-]{5,}\b",
    re.IGNORECASE,
)
STREET_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z0-9.'-]+\s+){0,5}"
    r"(?:ST(?:REET)?|AVE(?:NUE)?|RD|ROAD|BLVD|DR(?:IVE)?|LN|LANE|CT|COURT|WAY)\b[^\n,]*",
    re.IGNORECASE,
)
DATED_HISTORY_ROW_RE = re.compile(
    r"^\s*(?P<date>(?:0?[1-9]|1[0-2])[/\-]"
    r"(?:0?[1-9]|[12]\d|3[01])[/\-](?:20\d{2}|19\d{2}))\b"
)
ROW_MILEAGE_RE = re.compile(
    r"^\s+(?P<mileage>(?:\d{1,3}(?:,\d{3})+|\d{1,7}))"
    r"(?P<unit>\s*(?:miles?|mi))?(?=\s|/|$)",
    re.IGNORECASE,
)
HISTORY_TABLE_HEADER_RE = re.compile(
    r"\bdate\s+mileage\s+source\s+comments\b", re.IGNORECASE
)
NON_ODOMETER_SUFFIX_RE = re.compile(
    r"^\s*(?:/\s*(?:yr|year)|per\s+year|a\s+year|coverage\b|"
    r"warranty\b|service\s+(?:performed|interval)\b|"
    r"maintenance\s+interval\b)",
    re.IGNORECASE,
)
OWNER_COUNT_RE = re.compile(r"\b(\d{1,2})\s+previous\s+owners?\b", re.IGNORECASE)
CLOUD_MINIMAL_ARTIFACT_KINDS = frozenset(
    {EvidenceKind.TITLE, EvidenceKind.SELLER_MESSAGE}
)


class ArtifactTooLarge(ValueError):
    """Raised before an oversized artifact is decoded or dispatched."""


def _contains_affirmative(
    text: str, positives: tuple[str, ...], negatives: tuple[str, ...]
) -> bool:
    lowered = " ".join(text.lower().split())
    return any(term in lowered for term in positives) and not any(
        term in lowered for term in negatives
    )


def _has_inspection_status(context: str, system: str, status: str) -> bool:
    """Match a status to its named inspection without crossing statements.

    PDF text extraction sometimes concatenates adjacent comments as
    ``Passed safety inspectionFailed emissions inspection``.  Split only where
    a complete inspection phrase is immediately followed by a new direct-form
    status statement, then evaluate direct and reverse wording one statement at
    a time.  This preserves ``safety inspection failed`` while preventing the
    word ``failed`` from a neighboring emissions statement from being assigned
    to safety.
    """

    separated = re.sub(
        r"(?i)(?<=inspection)[ \t]*(?=(?:failed|passed)[ \t]+"
        r"(?:state[ \t]+)?(?:safety|emissions?))",
        "\n",
        context,
    )
    statements = [
        " ".join(statement.lower().split())
        for statement in separated.splitlines()
        if statement.strip()
    ]
    direct = re.compile(
        rf"\b{status}\s+(?:state\s+)?{system}\s+inspection\b"
    )
    reverse = re.compile(
        rf"\b{system}\s+inspection\s+(?:status\s*:?\s*)?{status}\b"
    )
    return any(
        direct.search(statement) or reverse.search(statement)
        for statement in statements
    )


def _classify_history_context(context: str) -> list[str]:
    """Return only event types supported by affirmative wording.

    Vehicle-history reports repeat headings such as ``No accidents reported``
    and brand-name checklists.  Plain keyword matching turns those reassuring
    statements into false findings, so positive and negative phrases are kept
    explicit here.
    """

    lowered = " ".join(context.lower().split())
    event_types: list[str] = []
    if _has_inspection_status(context, "emissions?", "failed"):
        event_types.append("emissions_failed")
    if _has_inspection_status(context, "emissions?", "passed"):
        event_types.append("emissions_passed")
    if _has_inspection_status(context, "safety", "failed"):
        event_types.append("safety_failed")
    if _has_inspection_status(context, "safety", "passed"):
        event_types.append("safety_passed")

    if _contains_affirmative(
        lowered,
        (
            "accident reported",
            "accident or damage reported",
            "damage reported",
            "collision reported",
        ),
        ("no accident", "no damage", "no issues reported", "not reported"),
    ):
        event_types.append("accident_or_damage_reported")
    if _contains_affirmative(
        lowered,
        (
            "structural damage reported",
            "frame damage reported",
            "structural damage disclosed",
        ),
        ("no structural damage", "no issues reported", "not reported"),
    ):
        event_types.append("structural_damage_reported")
    if _contains_affirmative(
        lowered,
        (
            "flood damage reported",
            "water damage reported",
            "flood title",
            "flood branded",
        ),
        ("no flood", "no issues reported", "not reported"),
    ):
        event_types.append("flood_damage_reported")
    if _contains_affirmative(
        lowered,
        (
            "salvage title",
            "rebuilt title",
            "junk title",
            "lemon title",
            "flood title",
            "fire title",
            "hail title",
            "title branded salvage",
            "title branded rebuilt",
            "damage brand reported",
        ),
        (
            "no problem",
            "no issues reported",
            "none of these title problems",
            "not reported",
        ),
    ):
        event_types.append("title_brand_reported")
    if "new owner reported" in lowered or "first owner reported" in lowered:
        event_types.append("owner_change")
    elif "title issued or updated" in lowered:
        event_types.append("title_event")
    if any(
        term in lowered
        for term in (
            "vehicle serviced",
            "oil and filter changed",
            "replaced",
            "maintenance performed",
        )
    ):
        event_types.append("service")
    return list(dict.fromkeys(event_types))


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return sha256_bytes(payload)


def listing_sha256(item: ListingInput) -> str:
    payload = item.model_dump(mode="json", by_alias=False)
    # Capture time is provenance, not listing content. A refresh with the same
    # facts is idempotent; any actual price/mileage/description change hashes anew.
    payload.pop("captured_at", None)
    return canonical_json_sha256(payload)


def redact_sensitive_text(
    text: str, explicit_values: list[str] | None = None
) -> tuple[str, list[str]]:
    redactions: list[str] = []
    result = text
    for label, pattern in (
        ("email", EMAIL_RE),
        ("phone", PHONE_RE),
        ("title_or_registration_number", TITLE_NUMBER_RE),
        ("street_address", STREET_RE),
    ):
        result, count = pattern.subn(f"[REDACTED_{label.upper()}]", result)
        if count:
            redactions.append(label)
    for explicit in explicit_values or []:
        if explicit and explicit in result:
            result = result.replace(explicit, "[REDACTED_USER_FIELD]")
            redactions.append("user_specified")
    return result, list(dict.fromkeys(redactions))


def sanitize_case_for_cloud_import(case: CaseContext) -> CaseContext:
    """Remove free-text identity surfaces from an encrypted local case import.

    An `.ocdd` package is integrity-checked, but it is still user-controlled and
    may have been created under the more permissive local retention policy.
    Cloud import therefore cannot copy its free-text evidence ledger verbatim.
    Structured vehicle, scan, inspection, date, mileage and price fields remain
    available; attachment-like prose is omitted and can be re-uploaded under the
    cloud ingestion policy when appropriate.
    """

    sanitized = case.model_copy(deep=True)
    sanitized.buyer_goal = None
    sanitized.sources = [
        source.model_copy(
            update={
                "provider": "cloud-import",
                "source_url": None,
                "license_name": "user-provided; no redistribution",
                "redistribution": "restricted",
                "credential_storage": "none",
                "retention_policy": "de-identified structured import; free text omitted",
            }
        )
        for source in sanitized.sources
    ]

    clean_evidence: list[Evidence] = []
    for item in sanitized.evidence:
        metadata: dict[str, object] = {
            "note": "free-text evidence omitted during cloud import",
        }
        if item.kind == EvidenceKind.TITLE:
            raw_match = item.metadata.get("identity_title_match")
            try:
                match = (
                    MatchStatus(raw_match)
                    if raw_match is not None
                    else MatchStatus.UNKNOWN
                )
            except ValueError:
                match = MatchStatus.UNKNOWN
            metadata["identity_title_match"] = match.value
        clean_evidence.append(
            item.model_copy(
                update={
                    "label": (
                        "Title verification artifact"
                        if item.kind == EvidenceKind.TITLE
                        else (
                            "Seller message artifact"
                            if item.kind == EvidenceKind.SELLER_MESSAGE
                            else f"Imported {item.kind.value.replace('_', ' ')} evidence"
                        )
                    ),
                    "excerpt": None,
                    "metadata": metadata,
                    "is_sensitive": True,
                    "redacted": True,
                }
            )
        )
    sanitized.evidence = clean_evidence
    sanitized.history = [
        item.model_copy(
            update={
                "description": f"Imported {item.event_type} event; free text omitted"
            }
        )
        for item in sanitized.history
    ]
    sanitized.listings = [
        item.model_copy(
            update={
                "title": "Imported vehicle listing",
                "description": None,
                "location": None,
                "source_url": None,
            }
        )
        for item in sanitized.listings
    ]
    sanitized.scans = [
        scan.model_copy(
            update={
                "scanner_name": "cloud-import",
                "dtcs": [
                    dtc.model_copy(update={"description": None}) for dtc in scan.dtcs
                ],
                "freeze_frame": {},
                "live_pids": {},
                "raw": {},
                "limitations": [],
                "notes": None,
                "evidence_label": "Imported OBD scan",
            }
        )
        for scan in sanitized.scans
    ]
    sanitized.inspections = [
        inspection.model_copy(
            update={
                "inspector": None,
                "notes": None,
                "items": [
                    item.model_copy(update={"notes": None}) for item in inspection.items
                ],
            }
        )
        for inspection in sanitized.inspections
    ]
    # Findings, narrative transaction plans and action strings can contain LLM
    # or user-authored prose. They are cheap to regenerate from retained facts.
    sanitized.findings = []
    sanitized.valuation = None
    sanitized.transaction_context = None
    sanitized.transaction_plan = None
    sanitized.coverage_percent = 0
    sanitized.unknowns = ["Cloud import omitted local free-text evidence"]
    sanitized.next_actions = ["Review imported facts and run analysis again"]
    sanitized.status_history = [
        event.model_copy(update={"reason": "Imported status event; free text omitted"})
        for event in sanitized.status_history
    ]
    return CaseContext.model_validate(sanitized.model_dump(by_alias=False))


def _parse_date(value: str) -> datetime | None:
    for pattern in ("%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _dated_history_row(line: str) -> tuple[str, str] | None:
    """Return the leading date and remainder for an actual history row.

    Summary and warranty prose often contains dates, but CARFAX-style detailed
    history rows start with the event date.  Requiring that position prevents a
    warranty start date or a "last reported reading" sentence from becoming a
    fabricated service/odometer event.
    """

    match = DATED_HISTORY_ROW_RE.match(line)
    if not match:
        return None
    return match.group("date"), line[match.end() :]


def _row_mileage(remainder: str, *, mileage_column_present: bool) -> int | None:
    """Extract only an odometer value bound to a dated detailed-history row.

    A comma-formatted value or an explicit ``mi/miles`` suffix is strict enough
    without a header.  Bare numbers (including a new vehicle's ``1`` mile
    record) are accepted only when the page declares a Date/Mileage column.
    Per-year estimates, warranty limits, coverage text and service intervals
    are deliberately excluded.
    """

    match = ROW_MILEAGE_RE.match(remainder)
    if not match:
        return None
    raw = match.group("mileage")
    unit = (match.group("unit") or "").strip()
    suffix = remainder[match.end() :]
    if NON_ODOMETER_SUFFIX_RE.match(suffix):
        return None
    if not mileage_column_present and "," not in raw and not unit:
        return None
    return int(raw.replace(",", ""))


def extract_history_events(page_text: str, evidence_id: str) -> list[HistoryEvent]:
    """Extract conservative date/mileage events without inventing missing facts."""
    events: list[HistoryEvent] = []
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    mileage_column_present = bool(HISTORY_TABLE_HEADER_RE.search(" ".join(lines)))
    dated_rows = [
        (index, row)
        for index, line in enumerate(lines)
        if (row := _dated_history_row(line)) is not None
    ]
    for row_index, (index, (date_value, remainder)) in enumerate(dated_rows):
        next_index = (
            dated_rows[row_index + 1][0]
            if row_index + 1 < len(dated_rows)
            else len(lines)
        )
        # A record's comments normally occupy only a few extracted lines.  Stop
        # at the next dated row and cap the block so page footers/summaries
        # cannot be attached to the final record on a page.
        context_end = min(next_index, index + 8)
        context = "\n".join(lines[index:context_end])[:1000]
        mileage = _row_mileage(
            remainder, mileage_column_present=mileage_column_present
        )
        event_types = _classify_history_context(context) or ["history_event"]
        parsed = _parse_date(date_value)
        for event_type in event_types:
            events.append(
                HistoryEvent(
                    event_date=parsed.date() if parsed else None,
                    mileage=mileage,
                    event_type=event_type,
                    description=context,
                    evidence_ids=[evidence_id],
                )
            )

    # Preserve an undated ownership-summary fact when it is printed on the page.
    # This is provenance, not an assertion that every title transaction was a
    # real change of possession.
    owner_match = OWNER_COUNT_RE.search(page_text)
    if owner_match:
        events.append(
            HistoryEvent(
                event_type="ownership_summary",
                description=f"Report states an estimated owner count of {owner_match.group(1)}.",
                evidence_ids=[evidence_id],
            )
        )
    return events


def ingest_listing(case: CaseContext, item: ListingInput) -> ListingSnapshot:
    digest = listing_sha256(item)
    safe_description, redactions = redact_sensitive_text(item.description or "")
    safe_item = item.model_copy(update={"description": safe_description or None})
    source = SourceEnvelope(
        source_type="listing",
        provider=item.channel.value,
        source_url=item.source_url,
        redistribution="restricted",
        retention_policy="structured snapshot retained with case",
        content_sha256=digest,
        observed_at=item.captured_at,
    )
    evidence = Evidence(
        source_id=source.id,
        kind=EvidenceKind.LISTING if not item.is_target else EvidenceKind.LISTING,
        label=item.title,
        excerpt=(safe_description or item.title)[:2000],
        metadata={
            "asking_price": item.asking_price,
            "mileage": item.mileage,
            "seller_type": item.seller_type.value,
            "channel": item.channel.value,
            "reference_kind": item.reference_kind.value,
            "redactions": redactions,
        },
        is_sensitive=bool(redactions),
        redacted=bool(redactions),
    )
    snapshot = ListingSnapshot(
        **safe_item.model_dump(by_alias=False),
        source_id=source.id,
        evidence_id=evidence.id,
        content_sha256=digest,
    )
    case.sources.append(source)
    case.evidence.append(evidence)
    case.listings.append(snapshot)
    return snapshot


class ArtifactService:
    def __init__(
        self,
        artifact_store: TransientArtifactStore,
        *,
        deployment_mode: str = "local",
        cloud_ttl_seconds: int = 3600,
        cloud_delete_within_seconds: int | None = None,
        max_artifact_bytes: int = 25 * 1024 * 1024,
        document_processor: DocumentProcessor | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.deployment_mode = deployment_mode
        if cloud_ttl_seconds < 1:
            raise ValueError("cloud_ttl_seconds must be positive")
        if max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes must be positive")
        self.cloud_ttl_seconds = cloud_ttl_seconds
        self.cloud_delete_within_seconds = (
            cloud_delete_within_seconds or cloud_ttl_seconds
        )
        self.max_artifact_bytes = max_artifact_bytes
        self.document_processor = document_processor or InlineDocumentProcessor()

    def ingest(self, case: CaseContext, artifact: ArtifactCreate) -> ArtifactReceipt:
        if artifact.text is not None:
            if len(artifact.text) > self.max_artifact_bytes:
                raise ArtifactTooLarge("artifact exceeds the configured upload limit")
            content = artifact.text.encode("utf-8")
        else:
            encoded = artifact.content_base64 or ""
            padding = min(2, len(encoded) - len(encoded.rstrip("=")))
            decoded_length = max(0, (len(encoded) // 4) * 3 - padding)
            if decoded_length > self.max_artifact_bytes:
                raise ArtifactTooLarge("artifact exceeds the configured upload limit")
            try:
                content = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError("content_base64 is not valid base64") from exc
        if len(content) > self.max_artifact_bytes:
            raise ArtifactTooLarge("artifact exceeds the configured upload limit")

        digest = sha256_bytes(content)
        artifact_id = str(uuid4())
        now = utc_now()
        title_identity_match, title_identity_basis = (
            _title_identity_result(artifact)
            if artifact.kind == EvidenceKind.TITLE
            else (MatchStatus.UNKNOWN, "not_applicable")
        )
        cloud_minimal = (
            self.deployment_mode == "cloud"
            and artifact.kind in CLOUD_MINIMAL_ARTIFACT_KINDS
        )
        expires_at = (
            now + timedelta(seconds=self.cloud_ttl_seconds)
            if self.deployment_mode == "cloud" and not cloud_minimal
            else None
        )
        safe_extension = Path(artifact.filename).suffix[:10]
        stored_filename = (
            f"artifact-{artifact_id}{safe_extension}"
            if self.deployment_mode == "cloud"
            else Path(artifact.filename).name
        )
        source = SourceEnvelope(
            source_type=artifact.kind.value,
            provider="user-upload",
            license_name="user-provided; no redistribution",
            redistribution="restricted",
            retention_policy=(
                "raw discarded after in-memory hash; only de-identified verification retained"
                if cloud_minimal
                else (
                    "raw access expires before the independent deletion deadline "
                    f"of {self.cloud_delete_within_seconds} seconds; redacted facts retained"
                    if self.deployment_mode == "cloud"
                    else "raw retained locally until case deletion"
                )
            ),
            content_sha256=digest,
        )
        case.sources.append(source)

        # Cloud title and seller-message bodies are neither sent to a worker nor
        # copied into structured evidence. They are not written to transient
        # object storage either. A title contributes only an explicit equality
        # result, defaulting to UNKNOWN. Local mode keeps the complete evidence.
        pages = (
            []
            if cloud_minimal
            else self.document_processor.extract_pages(
                content,
                media_type=artifact.media_type,
                filename=artifact.filename,
                content_sha256=digest,
            )
        )
        all_redactions: list[str] = (
            ["cloud_raw_content_not_retained", "human_names_not_retained"]
            if cloud_minimal
            else []
        )
        first_evidence_id = ""
        if pages:
            for page_number, page_text in enumerate(pages, start=1):
                redacted, redactions = redact_sensitive_text(
                    page_text, artifact.sensitive_fields
                )
                all_redactions.extend(redactions)
                cloud_structured_only = self.deployment_mode == "cloud"
                if cloud_structured_only:
                    all_redactions.extend(
                        ["cloud_free_text_not_retained", "human_names_not_retained"]
                    )
                page_metadata: dict[str, object] = {
                    "artifact_id": artifact_id,
                    "content_sha256": digest,
                }
                if artifact.kind == EvidenceKind.PPI:
                    page_metadata.update(
                        {
                            "ppi_artifact_binding_basis": (PPI_ARTIFACT_BINDING_BASIS),
                            "extracted_text_chars": len(page_text.strip()),
                        }
                    )
                if artifact.kind == EvidenceKind.TITLE:
                    page_metadata["identity_title_match"] = title_identity_match.value
                    page_metadata["identity_comparison_basis"] = title_identity_basis
                if cloud_structured_only:
                    page_metadata["note"] = (
                        "cloud free text omitted; structured facts retained"
                    )
                evidence = Evidence(
                    source_id=source.id,
                    kind=artifact.kind,
                    label=(
                        f"Uploaded {artifact.kind.value.replace('_', ' ')} evidence"
                        if cloud_structured_only
                        else artifact.label
                        or artifact.kind.value.replace("_", " ").title()
                    ),
                    excerpt=None if cloud_structured_only else redacted[:2000] or None,
                    page=page_number,
                    is_sensitive=cloud_structured_only or bool(redactions),
                    redacted=cloud_structured_only or bool(redactions),
                    metadata=page_metadata,
                )
                case.evidence.append(evidence)
                first_evidence_id = first_evidence_id or evidence.id
                if artifact.kind in {
                    EvidenceKind.HISTORY_REPORT,
                    EvidenceKind.STATE_INSPECTION,
                    EvidenceKind.RECEIPT,
                }:
                    events = extract_history_events(redacted, evidence.id)
                    if cloud_structured_only:
                        events = [
                            event.model_copy(
                                update={
                                    "description": (
                                        f"{event.event_type} fact extracted from uploaded page "
                                        f"{page_number}; free text omitted"
                                    )
                                }
                            )
                            for event in events
                        ]
                    case.history.extend(events)
        else:
            safe_label = artifact.label or artifact.kind.value.replace("_", " ").title()
            metadata: dict[str, object] = {
                "artifact_id": artifact_id,
                "content_sha256": digest,
                "note": "binary artifact retained for inspection; no automated factual claim",
            }
            if artifact.kind == EvidenceKind.TITLE:
                metadata["identity_title_match"] = title_identity_match.value
                metadata["identity_comparison_basis"] = title_identity_basis
            if cloud_minimal:
                safe_label = (
                    "Title verification artifact"
                    if artifact.kind == EvidenceKind.TITLE
                    else "Seller message artifact"
                )
                metadata["note"] = (
                    "cloud raw content was not retained; only a de-identified verification result persists"
                )
            evidence = Evidence(
                source_id=source.id,
                kind=artifact.kind,
                label=safe_label,
                excerpt=None,
                page=artifact.page,
                is_sensitive=True,
                redacted=True,
                metadata=metadata,
            )
            case.evidence.append(evidence)
            first_evidence_id = evidence.id

        # Persist the original only after extraction and every structured
        # evidence object have been constructed successfully. The endpoint
        # then either saves the case or compensates this one object by ID.
        if not cloud_minimal:
            self.artifact_store.put(
                artifact_id=artifact_id,
                case_id=case.id,
                filename=stored_filename,
                media_type=artifact.media_type,
                content=content,
                content_sha256=digest,
                expires_at=expires_at,
            )
        case.updated_at = utc_now()
        return ArtifactReceipt(
            artifact_id=artifact_id,
            evidence_id=first_evidence_id,
            content_sha256=digest,
            expires_at=expires_at,
            redactions=list(dict.fromkeys(all_redactions)),
            extracted_pages=len(pages),
        )
