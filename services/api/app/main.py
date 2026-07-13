"""FastAPI application for the OpenCarDueDiligence deterministic core."""

from __future__ import annotations

import base64
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

from .artifact_store import EncryptedRepositoryArtifactStore, S3ArtifactStore
from .case_access import CASE_TOKEN_HEADER, issue_case_token, verify_case_token
from .case_lease import CaseLeaseBusy, exclusive_case_lease
from .cloud_security import (
    ARTIFACT_UPLOAD_PATH_RE,
    CloudArtifactBodyLimitMiddleware,
    InMemoryRateLimiter,
)
from .engines.compare import compare_cases
from .engines.negotiation import (
    NegotiationEvidenceError,
    draft_negotiation,
    normalize_case_negotiation,
)
from .engines.repair_cost import compare_repair_costs, estimate_repair_cost
from .engines.report import build_report, render_report_pdf
from .engines.risk import _inspection_completion, analyze_case, calculate_coverage
from .engines.valuation import calculate_valuation
from .engines.watchlist import build_watchlist
from .evidence import (
    ArtifactService,
    ArtifactTooLarge,
    canonical_json_sha256,
    downgrade_imported_ppi_trust,
    downgrade_imported_title_identity,
    ingest_listing,
    listing_sha256,
    sanitize_case_for_cloud_import,
)
from .document_processing import (
    DocumentProcessingUnavailable,
    DocumentProcessor,
    create_document_processor,
)
from .export import OCDDPackageError, export_case, import_case
from .inspection_catalog import (
    InspectionCatalogError,
    checklist_public_payload,
    normalize_inspection_session,
)
from .knowledge import router as knowledge_router
from .listing_selection import latest_target_listing
from .models import (
    AnalyzeRequest,
    AnalysisResult,
    ArtifactCreate,
    ArtifactReceipt,
    CaseContext,
    CaseCreate,
    CaseStatus,
    CaseStatusUpdate,
    CompareRequest,
    CompareResponse,
    DiagnosticScan,
    DiagnosticScanInput,
    Evidence,
    EvidenceKind,
    InspectionResult,
    InspectionSession,
    InspectionSessionInput,
    Language,
    ListingInput,
    ListingsImportRequest,
    ListingsImportResponse,
    ListingWatchlistResponse,
    ModuleCoverage,
    NegotiationRequest,
    NegotiationState,
    OCDDImportRequest,
    OCDDImportResponse,
    ReportResponse,
    RepairCostComparisonRequest,
    RepairCostComparisonResult,
    RepairCostRequest,
    RepairCostResult,
    RetentionClass,
    SourceEnvelope,
    TransactionContext,
    TransactionPlan,
    utc_now,
)
from .ppi_trust import trusted_ppi_artifact_evidence_ids
from .repository import (
    CaseNotFoundError,
    CaseRepository,
    PostgresRepository,
    SQLiteRepository,
)
from .routes.vehicles import router as vehicle_router
from .state_machine import (
    InvalidCaseTransition,
    RejectionEvidenceRequired,
    UnknownTransitionEvidence,
    advance_case_status,
    transition_case,
)


logger = logging.getLogger(__name__)


def _repo(request: Request) -> CaseRepository:
    return request.app.state.repository


def _case_or_404(repository: CaseRepository, case_id: str) -> CaseContext:
    try:
        return repository.get_case(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="case not found") from exc


def _save(repository: CaseRepository, case: CaseContext) -> CaseContext:
    case.updated_at = utc_now()
    repository.save_case(case)
    return case


def _raise_transition_http(exc: ValueError) -> None:
    if isinstance(exc, InvalidCaseTransition):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, UnknownTransitionEvidence):
        raise HTTPException(
            status_code=422,
            detail={"unknown_evidence_ids": exc.evidence_ids},
        ) from exc
    if isinstance(exc, RejectionEvidenceRequired):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


def _update_vehicle_from_target(case: CaseContext) -> None:
    target = latest_target_listing(case.listings)
    if target is None:
        return
    fields = (
        "year",
        "make",
        "model",
        "trim",
        "generation",
        "platform",
        "engine",
        "transmission",
        "drivetrain",
        "production_date",
        "body_style",
    )
    updates = case.vehicle.model_dump(by_alias=False)
    # VIN is a durable vehicle-identity claim, not a mutable listing detail.
    # A target can supply a missing canonical VIN, but a different later VIN
    # must remain visible beside the case VIN so analyze_case can fail closed
    # with a traceable VIN_MISMATCH finding instead of silently changing the
    # vehicle being evaluated.
    if target.vin and not case.vehicle.vin:
        updates["vin"] = target.vin
    for field in fields:
        # The latest explicit target snapshot defines the vehicle being
        # evaluated. Overlay mutable facts it actually supplies so a corrected
        # powertrain cannot leave stale case details behind; preserve the prior
        # value only when the refreshed listing omits that field.
        if getattr(target, field, None):
            updates[field] = getattr(target, field)
    if target.fuel_type.value != "unknown":
        updates["fuel_type"] = target.fuel_type
    # Mileage is an observation that can legitimately change on a refreshed
    # target listing.  A newer snapshot therefore supersedes the older listing
    # value while the old snapshot remains in the evidence ledger.
    if target.mileage is not None:
        updates["odometer_miles"] = target.mileage
    case.vehicle = case.vehicle.__class__.model_validate(updates)


_CLOUD_STRUCTURED_KEY_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_CLOUD_PID_KEY_RE = re.compile(r"^[A-Za-z0-9_.%+/-]{1,48}$")


def _cloud_listing(item: ListingInput) -> ListingInput:
    vehicle_label = " ".join(
        str(value).strip()
        for value in (item.year, item.make, item.model, item.trim)
        if value is not None and str(value).strip()
    )
    return item.model_copy(
        update={
            "title": vehicle_label or "Vehicle listing",
            "description": None,
            "location": None,
            "source_url": None,
        }
    )


def _cloud_scan(payload: DiagnosticScanInput) -> DiagnosticScanInput:
    def numeric_map(values: dict[str, object]) -> dict[str, object]:
        return {
            key: value
            for key, value in values.items()
            if _CLOUD_PID_KEY_RE.fullmatch(key)
            and (value is None or isinstance(value, (int, float, bool)))
        }

    data = payload.model_dump(by_alias=False)
    data.update(
        {
            "scanner_name": "cloud scanner",
            "dtcs": [
                {
                    "code": item.code,
                    "status": item.status,
                    "description": None,
                    "module": "powertrain",
                }
                for item in payload.dtcs
            ],
            "freeze_frame": numeric_map(payload.freeze_frame),
            "live_pids": numeric_map(payload.live_pids),
            "raw": {},
            "limitations": [],
            "notes": None,
            "evidence_label": "OBD scan",
        }
    )
    return DiagnosticScanInput.model_validate(data)


def _cloud_inspection(payload: InspectionSessionInput) -> InspectionSessionInput:
    items: list[dict[str, object]] = []
    for index, item in enumerate(payload.items, start=1):
        key = (
            item.key
            if _CLOUD_STRUCTURED_KEY_RE.fullmatch(item.key)
            else f"custom_check_{index}"
        )
        items.append(
            {
                **item.model_dump(by_alias=False),
                "key": key,
                "label": key.replace("_", " ").title(),
                "notes": None,
            }
        )
    return InspectionSessionInput.model_validate(
        {
            **payload.model_dump(by_alias=False),
            # Retain only the assertion that an inspector was identified; the
            # anonymous cloud case never stores the raw person or shop name.
            "inspector": (
                "inspector name supplied (redacted)" if payload.inspector else None
            ),
            "notes": None,
            "items": items,
        }
    )


def _build_transaction(context: TransactionContext) -> TransactionPlan:
    try:
        from .engines.transaction import build_transaction_plan
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="state transaction rules are not installed in this build",
        ) from exc
    return build_transaction_plan(context)


def _retention_window(
    requested: RetentionClass | None,
    *,
    deployment_mode: str,
    anonymous_ttl_days: int,
    account_retention_enabled: bool,
) -> tuple[RetentionClass, datetime | None]:
    """Resolve a request into an explicit, auditable lifecycle policy."""

    retention_class = requested or (
        RetentionClass.ANONYMOUS if deployment_mode == "cloud" else RetentionClass.LOCAL
    )
    if deployment_mode == "cloud" and retention_class == RetentionClass.LOCAL:
        raise HTTPException(
            status_code=422,
            detail="LOCAL retention is only available in a local deployment",
        )
    if (
        deployment_mode == "cloud"
        and retention_class == RetentionClass.ACCOUNT
        and not account_retention_enabled
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "ACCOUNT retention requires a deployment-provided authentication layer; "
                "the public reference API defaults to anonymous seven-day retention"
            ),
        )
    if retention_class == RetentionClass.ANONYMOUS:
        return retention_class, utc_now() + timedelta(days=anonymous_ttl_days)
    # ACCOUNT is never inferred: it reaches this branch only when explicitly
    # supplied by the caller. Neither ACCOUNT nor LOCAL auto-expires.
    return retention_class, None


def create_app(
    *,
    database_path: str | Path | None = None,
    database_url: str | None = None,
    deployment_mode: str | None = None,
    anonymous_case_ttl_days: int | None = None,
    account_retention_enabled: bool | None = None,
    artifact_max_bytes: int | None = None,
    artifact_request_max_bytes: int | None = None,
    cloud_case_create_limit_per_minute: int | None = None,
    cloud_artifact_upload_limit_per_minute: int | None = None,
    cloud_vin_decode_limit_per_minute: int | None = None,
    case_lease_ttl_seconds: float | None = None,
    case_lease_wait_seconds: float | None = None,
    allow_cloud_artifact_fallback: bool | None = None,
    document_processor: DocumentProcessor | None = None,
) -> FastAPI:
    database_path_was_explicit = database_path is not None
    database_url = database_url or (
        None if database_path is not None else os.getenv("OCDD_DATABASE_URL")
    )
    if database_url and database_url.startswith("sqlite:///"):
        database_path = database_url.removeprefix("sqlite:///")
        database_url = None
    elif database_url and not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://")
    ):
        raise ValueError(
            "OCDD_DATABASE_URL must use sqlite:/// or postgresql(+psycopg)://"
        )
    database_path = database_path or os.getenv("OCDD_DATABASE_PATH", "./ocdd.sqlite3")
    deployment_mode = (
        deployment_mode
        or os.getenv("OCDD_DEPLOYMENT_MODE")
        or os.getenv("OCDD_ENV", "local")
    ).lower()
    if deployment_mode not in {"local", "cloud"}:
        raise ValueError("deployment_mode must be 'local' or 'cloud'")
    if anonymous_case_ttl_days is None:
        anonymous_case_ttl_days = int(os.getenv("OCDD_ANONYMOUS_CASE_TTL_DAYS", "7"))
    if anonymous_case_ttl_days < 1:
        raise ValueError("OCDD_ANONYMOUS_CASE_TTL_DAYS must be at least 1")
    if account_retention_enabled is None:
        account_retention_enabled = os.getenv(
            "OCDD_ACCOUNT_RETENTION_ENABLED", "false"
        ).lower() in {"1", "true", "yes"}
    if artifact_max_bytes is None:
        artifact_max_bytes = int(
            os.getenv(
                "OCDD_ARTIFACT_MAX_BYTES",
                str(
                    10 * 1024 * 1024 if deployment_mode == "cloud" else 25 * 1024 * 1024
                ),
            )
        )
    if artifact_request_max_bytes is None:
        encoded_ceiling = 4 * ((artifact_max_bytes + 2) // 3)
        artifact_request_max_bytes = int(
            os.getenv(
                "OCDD_ARTIFACT_REQUEST_MAX_BYTES",
                str(encoded_ceiling + 64 * 1024),
            )
        )
    if cloud_case_create_limit_per_minute is None:
        cloud_case_create_limit_per_minute = int(
            os.getenv("OCDD_CLOUD_CASE_CREATE_PER_MINUTE", "30")
        )
    if cloud_artifact_upload_limit_per_minute is None:
        cloud_artifact_upload_limit_per_minute = int(
            os.getenv("OCDD_CLOUD_ARTIFACT_UPLOAD_PER_MINUTE", "20")
        )
    if cloud_vin_decode_limit_per_minute is None:
        cloud_vin_decode_limit_per_minute = int(
            os.getenv("OCDD_CLOUD_VIN_DECODE_PER_MINUTE", "30")
        )
    if case_lease_ttl_seconds is None:
        case_lease_ttl_seconds = float(os.getenv("OCDD_CASE_LEASE_TTL_SECONDS", "300"))
    if case_lease_wait_seconds is None:
        case_lease_wait_seconds = float(os.getenv("OCDD_CASE_LEASE_WAIT_SECONDS", "5"))
    if artifact_max_bytes < 1 or artifact_request_max_bytes < 1:
        raise ValueError("artifact byte limits must be positive")
    if artifact_request_max_bytes <= artifact_max_bytes:
        raise ValueError(
            "artifact request limit must be larger than the decoded artifact limit"
        )
    if (
        cloud_case_create_limit_per_minute < 1
        or cloud_artifact_upload_limit_per_minute < 1
        or cloud_vin_decode_limit_per_minute < 1
    ):
        raise ValueError("cloud per-minute rate limits must be positive")
    if case_lease_ttl_seconds <= 0 or case_lease_wait_seconds < 0:
        raise ValueError(
            "case lease TTL must be positive and wait must be non-negative"
        )
    repository: CaseRepository = (
        PostgresRepository(database_url)
        if database_url
        else SQLiteRepository(database_path)
    )
    s3_bucket = os.getenv("OCDD_S3_BUCKET")
    if allow_cloud_artifact_fallback is None:
        # Explicit temporary SQLite paths are used by isolated tests. An
        # environment-configured cloud process must never silently fall back to
        # API-health-triggered database blob deletion.
        allow_cloud_artifact_fallback = (
            database_path_was_explicit and database_url is None
        )
    if (
        deployment_mode == "cloud"
        and not s3_bucket
        and not allow_cloud_artifact_fallback
    ):
        raise ValueError(
            "cloud deployment requires OCDD_S3_BUCKET and the independent artifact purger"
        )
    if deployment_mode == "cloud" and s3_bucket:
        artifact_store = S3ArtifactStore(
            bucket=s3_bucket,
            prefix=os.getenv("OCDD_S3_PREFIX", "ocdd-transient"),
            endpoint_url=os.getenv("OCDD_S3_ENDPOINT_URL")
            or os.getenv("OCDD_S3_ENDPOINT"),
            region_name=os.getenv("OCDD_S3_REGION"),
        )
    else:
        configured_key_path = os.getenv("OCDD_ARTIFACT_KEY_FILE")
        key_path = (
            Path(configured_key_path)
            if configured_key_path
            else Path(str(database_path) + ".artifacts.key")
        )
        artifact_store = EncryptedRepositoryArtifactStore(repository, key_file=key_path)

    api = FastAPI(
        title="OpenCarDueDiligence API",
        version="0.1.0-alpha.3",
        description=(
            "Evidence-backed US used-car due diligence. Deterministic rules calculate findings; "
            "LLMs, when configured, may explain but never override gates."
        ),
    )
    api.state.repository = repository
    api.state.artifact_store = artifact_store
    api.state.cloud_artifact_fallback = bool(
        deployment_mode == "cloud" and not s3_bucket
    )
    ttl_seconds = int(os.getenv("OCDD_ARTIFACT_TTL_SECONDS", "3600"))
    purge_interval_seconds = int(
        os.getenv("OCDD_ARTIFACT_PURGE_INTERVAL_SECONDS", "60")
    )
    safety_margin_seconds = int(
        os.getenv(
            "OCDD_ARTIFACT_EXPIRY_SAFETY_MARGIN_SECONDS",
            str(max(300, purge_interval_seconds * 2)),
        )
    )
    if ttl_seconds < 60:
        raise ValueError("OCDD_ARTIFACT_TTL_SECONDS must be at least 60")
    if purge_interval_seconds < 1:
        raise ValueError("OCDD_ARTIFACT_PURGE_INTERVAL_SECONDS must be positive")
    if safety_margin_seconds < purge_interval_seconds:
        raise ValueError(
            "OCDD_ARTIFACT_EXPIRY_SAFETY_MARGIN_SECONDS must be at least the purge interval"
        )
    if deployment_mode == "cloud" and safety_margin_seconds >= ttl_seconds:
        raise ValueError("artifact expiry safety margin must be shorter than the TTL")
    access_ttl_seconds = (
        ttl_seconds - safety_margin_seconds
        if deployment_mode == "cloud"
        else ttl_seconds
    )
    api.state.artifact_service = ArtifactService(
        artifact_store,
        deployment_mode=deployment_mode,
        cloud_ttl_seconds=access_ttl_seconds,
        cloud_delete_within_seconds=ttl_seconds,
        max_artifact_bytes=artifact_max_bytes,
        document_processor=document_processor or create_document_processor(),
    )
    api.state.deployment_mode = deployment_mode
    api.state.anonymous_case_ttl_days = anonymous_case_ttl_days
    api.state.account_retention_enabled = account_retention_enabled
    api.state.artifact_max_bytes = artifact_max_bytes
    api.state.artifact_request_max_bytes = artifact_request_max_bytes
    api.state.cloud_case_create_limit_per_minute = cloud_case_create_limit_per_minute
    api.state.cloud_artifact_upload_limit_per_minute = (
        cloud_artifact_upload_limit_per_minute
    )
    api.state.cloud_vin_decode_limit_per_minute = cloud_vin_decode_limit_per_minute
    api.state.case_lease_ttl_seconds = case_lease_ttl_seconds
    api.state.case_lease_wait_seconds = case_lease_wait_seconds
    api.state.rate_limiter = InMemoryRateLimiter()
    api.include_router(vehicle_router)
    api.include_router(knowledge_router)

    # Install the body counter before the access middleware is declared.
    # Starlette wraps later-added middleware outside earlier middleware, so the
    # resulting order is CORS -> auth/rate -> bounded body replay -> routes.
    # Invalid capabilities and rate-limited peers are rejected before their
    # request body is buffered.
    api.add_middleware(
        CloudArtifactBodyLimitMiddleware,
        enabled=deployment_mode == "cloud",
        max_body_bytes=artifact_request_max_bytes,
    )

    @api.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response
        if request.app.state.deployment_mode == "cloud":
            path = request.url.path.rstrip("/") or "/"
            rate_scope: str | None = None
            rate_limit = 0
            if request.method == "POST" and path in {"/v1/cases", "/v1/cases/import"}:
                rate_scope = "case_creation"
                rate_limit = request.app.state.cloud_case_create_limit_per_minute
            elif request.method == "POST" and ARTIFACT_UPLOAD_PATH_RE.fullmatch(path):
                rate_scope = "artifact_upload"
                rate_limit = request.app.state.cloud_artifact_upload_limit_per_minute
            elif request.method == "POST" and path == "/v1/vehicles/decode-vin":
                rate_scope = "vin_decode"
                rate_limit = request.app.state.cloud_vin_decode_limit_per_minute

            rate_response: Response | None = None
            if rate_scope is not None:
                # Only the actual ASGI peer participates in the key. Forwarded,
                # Real-IP and similar headers are deliberately ignored because
                # this app cannot authenticate the proxy that supplied them.
                peer = request.client.host if request.client else "<unknown-peer>"
                decision = request.app.state.rate_limiter.check(
                    scope=rate_scope,
                    peer=peer,
                    limit=rate_limit,
                )
                if not decision.allowed:
                    rate_response = JSONResponse(
                        status_code=429,
                        content={"detail": "cloud request rate limit exceeded"},
                        headers={"Retry-After": str(decision.retry_after_seconds)},
                    )

            if rate_response is not None:
                response = rate_response
            elif request.method == "GET" and path == "/v1/cases":
                response = JSONResponse(
                    status_code=403,
                    content={
                        "detail": "case enumeration is disabled in cloud deployments"
                    },
                )
            else:
                case_id: str | None = None
                prefix = "/v1/cases/"
                if path.startswith(prefix) and path != "/v1/cases/import":
                    case_id = path[len(prefix) :].split("/", 1)[0] or None
                if case_id and not verify_case_token(
                    request.app.state.repository,
                    case_id,
                    request.headers.get(CASE_TOKEN_HEADER),
                ):
                    # Missing cases and invalid capabilities are deliberately
                    # indistinguishable, preventing an ID-existence oracle.
                    response = JSONResponse(
                        status_code=404,
                        content={"detail": "case not found"},
                    )
                else:
                    response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    # Register CORS after the access middleware so even a denied browser
    # request receives a readable CORS response. The capability is exposed to
    # JavaScript only as the one-time case-creation response header.
    configured_origins = [
        item.strip()
        for item in (
            os.getenv("OCDD_CORS_ORIGINS") or os.getenv("OCDD_ALLOWED_ORIGINS", "")
        ).split(",")
        if item.strip() and item.strip() != "chrome-extension://*"
    ]
    api.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            *configured_origins,
        ],
        allow_origin_regex=r"chrome-extension://[a-p]{32}",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-OCDD-Passphrase",
            CASE_TOKEN_HEADER,
        ],
        expose_headers=[CASE_TOKEN_HEADER],
    )

    @api.get("/health")
    def health(request: Request) -> dict[str, object]:
        expired_cases = _repo(request).purge_expired_cases()
        # Local fallback blobs can be cleaned cheaply here. Cloud S3 cleanup is
        # deliberately owned by the independent artifact-purger service, not
        # API traffic or health checks.
        purged = (
            0
            if isinstance(request.app.state.artifact_store, S3ArtifactStore)
            else request.app.state.artifact_store.purge_expired()
        )
        return {
            "status": "ok",
            "version": api.version,
            "deploymentMode": request.app.state.deployment_mode,
            "expiredCasesPurged": expired_cases,
            "expiredArtifactsPurged": purged,
            "deterministicCore": True,
            "artifactStore": (
                "repository-test-fallback"
                if request.app.state.cloud_artifact_fallback
                else "s3"
                if isinstance(request.app.state.artifact_store, S3ArtifactStore)
                else "local-encrypted"
            ),
        }

    @api.get("/v1/inspection-checklist")
    def get_inspection_checklist() -> dict[str, object]:
        """Expose the exact read-only catalog enforced by the API."""

        return checklist_public_payload()

    @api.post(
        "/v1/cases", response_model=CaseContext, status_code=status.HTTP_201_CREATED
    )
    def create_case(
        payload: CaseCreate, request: Request, response: Response
    ) -> CaseContext:
        retention_class, expires_at = _retention_window(
            payload.retention_class,
            deployment_mode=request.app.state.deployment_mode,
            anonymous_ttl_days=request.app.state.anonymous_case_ttl_days,
            account_retention_enabled=request.app.state.account_retention_enabled,
        )
        case = CaseContext(
            language=payload.language,
            buyer_goal=(
                None
                if request.app.state.deployment_mode == "cloud"
                else payload.buyer_goal
            ),
            all_in_budget=payload.all_in_budget,
            vehicle=payload.vehicle,
            retention_class=retention_class,
            expires_at=expires_at,
        )
        repository = _repo(request)
        created = repository.create_case(case)
        if request.app.state.deployment_mode == "cloud":
            response.headers[CASE_TOKEN_HEADER] = issue_case_token(
                repository, created.id
            )
        return created

    # Static route is intentionally declared before /v1/cases/{case_id}.
    @api.post(
        "/v1/cases/import",
        response_model=OCDDImportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def import_ocdd(
        payload: OCDDImportRequest,
        request: Request,
        response: Response,
    ) -> OCDDImportResponse:
        try:
            encoded = payload.content_base64
            padding = min(2, len(encoded) - len(encoded.rstrip("=")))
            decoded_length = max(0, (len(encoded) // 4) * 3 - padding)
            if decoded_length > request.app.state.artifact_max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="encrypted case package exceeds the configured import limit",
                )
            package = base64.b64decode(payload.content_base64, validate=True)
            if len(package) > request.app.state.artifact_max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="encrypted case package exceeds the configured import limit",
                )
            case, manifest = import_case(package, payload.passphrase)
            case = downgrade_imported_title_identity(case)
            case = downgrade_imported_ppi_trust(case)
            if request.app.state.deployment_mode == "cloud":
                case = sanitize_case_for_cloud_import(case)
            retention_class, expires_at = _retention_window(
                payload.retention_class,
                deployment_mode=request.app.state.deployment_mode,
                anonymous_ttl_days=request.app.state.anonymous_case_ttl_days,
                account_retention_enabled=request.app.state.account_retention_enabled,
            )
            case = CaseContext.model_validate(
                {
                    **case.model_dump(by_alias=False),
                    "retention_class": retention_class,
                    "expires_at": expires_at,
                }
            )
            case.coverage_percent, coverage_unknowns = calculate_coverage(case)
            case.unknowns = list(dict.fromkeys([*case.unknowns, *coverage_unknowns]))
            repository = _repo(request)
            repository.create_case(case)
            if request.app.state.deployment_mode == "cloud":
                response.headers[CASE_TOKEN_HEADER] = issue_case_token(
                    repository, case.id
                )
        except (sqlite3.IntegrityError, SQLAlchemyIntegrityError) as exc:
            raise HTTPException(status_code=409, detail="case already exists") from exc
        except (ValueError, OCDDPackageError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return OCDDImportResponse(
            case_id=case.id,
            schema_version=str(manifest["schema_version"]),
            integrity_verified=True,
            attachments_imported=0,
        )

    @api.get("/v1/cases", response_model=list[CaseContext])
    def list_cases(request: Request) -> list[CaseContext]:
        # Cloud requests are rejected by middleware before this handler. Keep
        # the check here as defense in depth if middleware ordering changes.
        if request.app.state.deployment_mode == "cloud":
            raise HTTPException(
                status_code=403,
                detail="case enumeration is disabled in cloud deployments",
            )
        return _repo(request).list_cases()

    @api.get("/v1/cases/{case_id}", response_model=CaseContext)
    def get_case(case_id: str, request: Request) -> CaseContext:
        return _case_or_404(_repo(request), case_id)

    @api.patch("/v1/cases/{case_id}/status", response_model=CaseContext)
    def update_case_status(
        case_id: str, payload: CaseStatusUpdate, request: Request
    ) -> CaseContext:
        repository = _repo(request)
        case = _case_or_404(repository, case_id)
        if payload.status in {
            CaseStatus.PPI_COMPLETE,
            CaseStatus.NEGOTIATING,
            CaseStatus.READY_TO_BUY,
        }:
            ppi_completion, _ = _inspection_completion(case, inspection_type="ppi")
            if ppi_completion < 1:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"{payload.status.value} requires a complete PPI whose "
                        "critical checklist results are linked to a substantive "
                        "uploaded PPI report"
                    ),
                )
        try:
            transition_case(
                case,
                payload.status,
                reason=(
                    f"User-confirmed transition to {payload.status.value}; cloud free-text reason omitted"
                    if request.app.state.deployment_mode == "cloud"
                    else payload.reason
                ),
                evidence_ids=payload.evidence_ids,
            )
        except (
            InvalidCaseTransition,
            UnknownTransitionEvidence,
            RejectionEvidenceRequired,
        ) as exc:
            _raise_transition_http(exc)
        return _save(repository, case)

    @api.delete("/v1/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_case(case_id: str, request: Request) -> Response:
        repository = _repo(request)
        try:
            with exclusive_case_lease(
                repository,
                case_id,
                ttl_seconds=request.app.state.case_lease_ttl_seconds,
                wait_seconds=request.app.state.case_lease_wait_seconds,
            ):
                _case_or_404(repository, case_id)
                try:
                    # Delete originals while holding the same database lease
                    # used by upload. No uploader can write after this scan and
                    # before the structured capability is deleted.
                    request.app.state.artifact_store.delete_case(case_id)
                except Exception as exc:
                    logger.error(
                        "case-original deletion failed (%s); structured case retained for retry",
                        type(exc).__name__,
                    )
                    raise HTTPException(
                        status_code=503,
                        detail="transient originals could not be deleted; retry case deletion",
                    ) from exc
                if not repository.delete_case(case_id):
                    raise HTTPException(status_code=404, detail="case not found")
        except CaseLeaseBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="case not found") from exc
        return Response(status_code=204)

    @api.post(
        "/v1/cases/{case_id}/listings/import",
        response_model=ListingsImportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def import_listings(
        case_id: str, payload: ListingsImportRequest, request: Request
    ) -> ListingsImportResponse:
        repository = _repo(request)
        case = _case_or_404(repository, case_id)
        ids, evidence_ids = [], []
        existing_hashes = {item.content_sha256 for item in case.listings}
        for submitted_item in payload.listings:
            item = (
                _cloud_listing(submitted_item)
                if request.app.state.deployment_mode == "cloud"
                else submitted_item
            )
            digest = listing_sha256(item)
            if digest in existing_hashes:
                continue
            snapshot = ingest_listing(case, item)
            existing_hashes.add(snapshot.content_sha256)
            ids.append(snapshot.id)
            evidence_ids.append(snapshot.evidence_id)
        _update_vehicle_from_target(case)
        if case.listings and case.status == CaseStatus.DISCOVERED:
            advance_case_status(
                case,
                CaseStatus.NEEDS_DATA,
                reason="A listing snapshot was added; additional due-diligence evidence is required",
                evidence_ids=evidence_ids,
            )
        _save(repository, case)
        return ListingsImportResponse(
            case_id=case_id,
            imported=len(ids),
            listing_ids=ids,
            evidence_ids=evidence_ids,
        )

    @api.get(
        "/v1/cases/{case_id}/listings/history",
        response_model=ListingWatchlistResponse,
    )
    def listing_history(case_id: str, request: Request) -> ListingWatchlistResponse:
        return build_watchlist(_case_or_404(_repo(request), case_id))

    @api.post(
        "/v1/cases/{case_id}/artifacts",
        response_model=ArtifactReceipt,
        status_code=status.HTTP_201_CREATED,
    )
    def upload_artifact(
        case_id: str, payload: ArtifactCreate, request: Request
    ) -> ArtifactReceipt:
        repository = _repo(request)
        try:
            with exclusive_case_lease(
                repository,
                case_id,
                ttl_seconds=request.app.state.case_lease_ttl_seconds,
                wait_seconds=request.app.state.case_lease_wait_seconds,
            ):
                case = _case_or_404(repository, case_id)
                receipt = request.app.state.artifact_service.ingest(case, payload)
                try:
                    _save(repository, case)
                except Exception as exc:
                    try:
                        request.app.state.artifact_store.delete(receipt.artifact_id)
                    except Exception as cleanup_exc:
                        logger.critical(
                            "artifact compensation delete failed (%s) after case save failure",
                            type(cleanup_exc).__name__,
                        )
                        raise HTTPException(
                            status_code=503,
                            detail="artifact metadata could not be saved and cleanup must be retried",
                        ) from cleanup_exc
                    logger.error(
                        "artifact upload rolled back after case save failure (%s)",
                        type(exc).__name__,
                    )
                    raise HTTPException(
                        status_code=503,
                        detail="artifact metadata could not be saved; upload was rolled back",
                    ) from exc
        except CaseLeaseBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="case not found") from exc
        except ArtifactTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except DocumentProcessingUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return receipt

    @api.post(
        "/v1/cases/{case_id}/obd/scans",
        response_model=DiagnosticScan,
        status_code=status.HTTP_201_CREATED,
    )
    def add_obd_scan(
        case_id: str, payload: DiagnosticScanInput, request: Request
    ) -> DiagnosticScan:
        repository = _repo(request)
        case = _case_or_404(repository, case_id)
        if request.app.state.deployment_mode == "cloud":
            payload = _cloud_scan(payload)
        digest = canonical_json_sha256(payload.model_dump(mode="json", by_alias=False))
        source = SourceEnvelope(
            source_type="obd_scan",
            provider=payload.scanner_name,
            license_name="user-generated diagnostic data",
            redistribution="allowed",
            retention_policy="structured scan retained with case",
            content_sha256=digest,
            observed_at=payload.scanned_at,
        )
        if payload.dtcs:
            codes = ", ".join(item.code for item in payload.dtcs)
        elif payload.module_coverage.get("powertrain") == ModuleCoverage.SCANNED:
            codes = "No generic powertrain DTC reported in this scan"
        else:
            codes = "No generic powertrain DTC scan data"
        evidence = Evidence(
            source_id=source.id,
            kind=EvidenceKind.OBD_SCAN,
            label=payload.evidence_label,
            excerpt=codes,
            metadata={
                "mil_on": payload.mil_on,
                "module_coverage": {
                    k: v.value for k, v in payload.module_coverage.items()
                },
                "limitations": payload.limitations,
            },
        )
        scan = DiagnosticScan(
            **payload.model_dump(by_alias=False),
            source_id=source.id,
            evidence_id=evidence.id,
        )
        case.sources.append(source)
        case.evidence.append(evidence)
        case.scans.append(scan)
        _save(repository, case)
        return scan

    @api.post(
        "/v1/cases/{case_id}/inspections",
        response_model=InspectionSession,
        status_code=status.HTTP_201_CREATED,
    )
    def add_inspection(
        case_id: str, payload: InspectionSessionInput, request: Request
    ) -> InspectionSession:
        repository = _repo(request)
        case = _case_or_404(repository, case_id)
        if request.app.state.deployment_mode == "cloud":
            payload = _cloud_inspection(payload)
        try:
            payload = normalize_inspection_session(payload, vehicle=case.vehicle)
        except InspectionCatalogError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        submitted_evidence_ids = {
            evidence_id
            for item in payload.items
            for evidence_id in item.evidence_ids
            if evidence_id
        }
        known_evidence_ids = {item.id for item in case.evidence}
        unknown_evidence_ids = sorted(submitted_evidence_ids - known_evidence_ids)
        if unknown_evidence_ids:
            raise HTTPException(
                status_code=422,
                detail={"unknown_evidence_ids": unknown_evidence_ids},
            )
        trusted_ppi_ids = trusted_ppi_artifact_evidence_ids(case)
        recorded_ppi_items = [
            item
            for item in payload.items
            if item.result
            in {
                InspectionResult.PASS,
                InspectionResult.CONCERN,
                InspectionResult.FAIL,
            }
        ]
        ppi_artifact_bound = (
            payload.inspection_type == "ppi"
            and bool(recorded_ppi_items)
            and all(
                bool(set(item.evidence_ids).intersection(trusted_ppi_ids))
                for item in recorded_ppi_items
            )
        )
        linked_trusted_ppi_ids = sorted(
            submitted_evidence_ids.intersection(trusted_ppi_ids)
        )
        digest = canonical_json_sha256(payload.model_dump(mode="json", by_alias=False))
        source = SourceEnvelope(
            source_type=payload.inspection_type,
            provider=(
                "evidence-bound-ppi"
                if ppi_artifact_bound
                else "user-attested-ppi"
                if payload.inspection_type == "ppi"
                else "buyer"
            ),
            license_name="user-generated inspection data",
            redistribution="allowed",
            retention_policy="structured inspection retained with case",
            content_sha256=digest,
            observed_at=payload.inspected_at,
        )
        evidence = Evidence(
            source_id=source.id,
            kind=(
                EvidenceKind.PPI if ppi_artifact_bound else EvidenceKind.SELF_INSPECTION
            ),
            label=(
                "PPI checklist linked to uploaded report"
                if ppi_artifact_bound
                else "User-attested PPI checklist (report not linked)"
                if payload.inspection_type == "ppi"
                else "Buyer inspection"
            ),
            excerpt=f"{len(payload.items)} checklist items recorded",
            metadata={
                "inspection_type": payload.inspection_type,
                "verification_level": (
                    "artifact_bound" if ppi_artifact_bound else "user_attested"
                ),
                "linked_ppi_evidence_ids": linked_trusted_ppi_ids,
            },
        )
        session = InspectionSession(
            **payload.model_dump(by_alias=False),
            source_id=source.id,
            evidence_id=evidence.id,
        )
        case.sources.append(source)
        case.evidence.append(evidence)
        case.inspections.append(session)
        if payload.inspection_type == "self":
            advance_case_status(
                case,
                CaseStatus.SELF_INSPECTED,
                reason="A buyer self-inspection was recorded",
                evidence_ids=[evidence.id],
                no_op_if_unreachable=True,
            )
        else:
            ppi_completion, _ = _inspection_completion(case, inspection_type="ppi")
            if ppi_completion == 1:
                all_linked_ppi_ids = sorted(
                    {
                        evidence_id
                        for inspection in case.inspections
                        if inspection.inspection_type == "ppi"
                        for item in inspection.items
                        for evidence_id in item.evidence_ids
                        if evidence_id in trusted_ppi_ids
                    }
                )
                advance_case_status(
                    case,
                    CaseStatus.PPI_COMPLETE,
                    reason=(
                        "All applicable critical PPI checks were linked to a "
                        "substantive uploaded independent inspection report"
                    ),
                    evidence_ids=[*all_linked_ppi_ids, evidence.id],
                    no_op_if_unreachable=True,
                )
        _save(repository, case)
        return session

    @api.post("/v1/cases/{case_id}/analyze", response_model=AnalysisResult)
    def analyze(
        case_id: str, payload: AnalyzeRequest, request: Request
    ) -> AnalysisResult:
        repository = _repo(request)
        case = _case_or_404(repository, case_id)
        if payload.buyer_all_in_budget is not None:
            case.all_in_budget = payload.buyer_all_in_budget
        existing_hashes = {item.content_sha256 for item in case.listings}
        for comparable in payload.comparables:
            comparable.is_target = False
            digest = listing_sha256(comparable)
            if digest not in existing_hashes:
                snapshot = ingest_listing(case, comparable)
                existing_hashes.add(snapshot.content_sha256)
        case.valuation = calculate_valuation(case, case.listings)
        result = analyze_case(case)
        _save(repository, case)
        return result

    @api.get("/v1/cases/{case_id}/report", response_model=ReportResponse)
    def report(
        case_id: str,
        request: Request,
        language: Language | None = Query(default=None),
        format: str = Query(default="json", pattern="^(json|pdf)$"),
    ) -> object:
        case = _case_or_404(_repo(request), case_id)
        rendered = build_report(case, language)
        if format == "pdf":
            return Response(
                content=render_report_pdf(rendered),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="{case_id}-report.pdf"'
                },
            )
        return rendered

    @api.post("/v1/cases/{case_id}/negotiation/draft", response_model=NegotiationState)
    def negotiation(
        case_id: str, payload: NegotiationRequest, request: Request
    ) -> NegotiationState:
        repository = _repo(request)
        case = _case_or_404(repository, case_id)
        try:
            normalized = normalize_case_negotiation(case, payload)
        except NegotiationEvidenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = draft_negotiation(
            normalized, case_id=case_id, default_language=case.language
        )
        if result.decision in {"MAKE_OFFER", "WAIT"}:
            adjustment_evidence = list(
                dict.fromkeys(
                    evidence_id
                    for adjustment in normalized.adjustments
                    for evidence_id in adjustment.evidence_ids
                )
            )
            try:
                advance_case_status(
                    case,
                    CaseStatus.NEGOTIATING,
                    reason=f"Negotiation draft generated for {payload.phase.value}",
                    evidence_ids=adjustment_evidence,
                    no_op_if_unreachable=True,
                )
            except UnknownTransitionEvidence as exc:
                _raise_transition_http(exc)
            _save(repository, case)
        return result

    @api.post("/v1/cases/{case_id}/transaction-plan", response_model=TransactionPlan)
    def save_transaction_context(
        case_id: str, payload: TransactionContext, request: Request
    ) -> TransactionPlan:
        repository = _repo(request)
        case = _case_or_404(repository, case_id)
        plan = _build_transaction(payload)
        # Persist only match/mismatch enums, not any identity strings (none are
        # accepted by TransactionContext).
        case.transaction_context = payload.model_dump(mode="json", by_alias=False)
        case.transaction_plan = plan.model_dump(mode="json", by_alias=False)
        _save(repository, case)
        return plan

    @api.get("/v1/cases/{case_id}/transaction-plan", response_model=TransactionPlan)
    def transaction_plan(
        case_id: str,
        request: Request,
    ) -> TransactionPlan:
        repository = _repo(request)
        case = _case_or_404(repository, case_id)
        if case.transaction_plan:
            return TransactionPlan.model_validate(case.transaction_plan)
        if case.transaction_context:
            return _build_transaction(
                TransactionContext.model_validate(case.transaction_context)
            )
        raise HTTPException(
            status_code=409,
            detail="transaction context is required; POST it to this endpoint first",
        )

    @api.post("/v1/compare", response_model=CompareResponse)
    def compare(payload: CompareRequest, request: Request) -> CompareResponse:
        repository = _repo(request)
        if request.app.state.deployment_mode == "cloud" and not all(
            verify_case_token(repository, case_id, payload.access_tokens.get(case_id))
            for case_id in payload.case_ids
        ):
            # Do not disclose which requested ID exists or which token failed.
            raise HTTPException(
                status_code=404, detail="one or more cases were not found"
            )
        cases = repository.list_cases(payload.case_ids)
        found = {case.id for case in cases}
        missing = [case_id for case_id in payload.case_ids if case_id not in found]
        if missing:
            if request.app.state.deployment_mode == "cloud":
                raise HTTPException(
                    status_code=404, detail="one or more cases were not found"
                )
            raise HTTPException(status_code=404, detail={"missing_case_ids": missing})
        return compare_cases(cases)

    @api.post("/v1/repair-cost/estimate", response_model=RepairCostResult)
    def repair_cost(payload: RepairCostRequest) -> RepairCostResult:
        return estimate_repair_cost(payload)

    @api.post("/v1/repair-cost/compare", response_model=RepairCostComparisonResult)
    def repair_cost_comparison(
        payload: RepairCostComparisonRequest,
    ) -> RepairCostComparisonResult:
        return compare_repair_costs(payload)

    @api.get("/v1/cases/{case_id}/export")
    def export_ocdd(
        case_id: str,
        request: Request,
        passphrase: Annotated[str | None, Header(alias="X-OCDD-Passphrase")] = None,
    ) -> Response:
        if not passphrase or len(passphrase) < 8:
            raise HTTPException(
                status_code=422,
                detail="X-OCDD-Passphrase must contain at least 8 characters",
            )
        case = _case_or_404(_repo(request), case_id)
        package = export_case(case, passphrase)
        return Response(
            content=package,
            media_type="application/vnd.opencarduediligence.case",
            headers={"Content-Disposition": f'attachment; filename="{case_id}.ocdd"'},
        )

    return api


app = create_app()
