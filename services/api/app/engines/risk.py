"""Evidence-backed risk and OBD interpretation.

This module never maps a DTC directly to a part replacement. A code produces a
diagnostic branch with confirmation tests and minimum/likely/worst-reasonable
cost scenarios.
"""

from __future__ import annotations

from collections import defaultdict

from ..inspection_catalog import (
    FAIL_CLOSED_KEYS,
    canonicalize_inspection_item,
    inspection_catalog,
    inspection_risk_area,
    required_inspection_keys,
)
from ..models import (
    AnalysisResult,
    CaseContext,
    CaseStatus,
    Confidence,
    Decision,
    DiagnosticScan,
    DtcEntry,
    DtcStatus,
    EvidenceKind,
    FindingStatus,
    InspectionResult,
    LienStatus,
    MatchStatus,
    ModuleCoverage,
    MoneyRange,
    ReadinessStatus,
    RepairScenario,
    RiskArea,
    RiskFinding,
    Severity,
    TitleStatus,
    TransactionContext,
    TransactionPlan,
    utc_now,
)
from ..ppi_trust import trusted_ppi_artifact_evidence_ids
from ..state_machine import advance_case_status
from .history import findings_from_history


# Backwards-compatible exports for tests/plugins.  The YAML catalog is the only
# maintained source; these sets are derived rather than duplicated.
SELF_CRITICAL_KEYS = frozenset(
    key
    for key, item in inspection_catalog().items()
    if item.critical and not item.requires_ppi and item.applicability != "manual_only"
)
PPI_CRITICAL_KEYS = frozenset(
    key
    for key, item in inspection_catalog().items()
    if item.critical and item.requires_ppi and item.applicability != "hybrid_or_EV"
)
COMPLETED_INSPECTION_RESULTS = frozenset(
    {InspectionResult.PASS, InspectionResult.CONCERN, InspectionResult.FAIL}
)
TRUSTED_TITLE_IDENTITY_BASES = frozenset({"server_exact_normalized"})


_INSPECTION_GATE_CHECKS = {
    "vin_received": (
        "Obtain the full VIN and compare it character by character with the listing, "
        "history records, and physical vehicle before traveling or paying"
    ),
    "title_photo_redacted": (
        "Request a redacted original title photo showing the VIN, issuing state, title "
        "status, assignment, and lien area; inspect the original before payment"
    ),
    "seller_identity_match_plan": (
        "Confirm the seller will show photo ID and match the name to the current original "
        "title in person; resolve any lien or authority mismatch before payment"
    ),
    "vin_all_locations": (
        "Match the dashboard, door-label, original-title, history-report, and diagnostic-scan "
        "VINs character by character before proceeding"
    ),
    "ppi_permission": (
        "Obtain explicit permission for an independent PPI and road test before traveling "
        "or making an offer"
    ),
}


def _inspection_next_checks(item_key: str, inspection_type: str) -> list[str]:
    """Return a next step appropriate to the observed check.

    Identity/title/PPI-access gates cannot be converted into a price concession.
    A self-inspection concern also is not yet a written professional finding.
    """

    gate_check = _INSPECTION_GATE_CHECKS.get(item_key)
    if gate_check:
        return [gate_check]
    if inspection_type == "ppi":
        return ["Resolve or price this item using the written PPI finding"]
    return [
        "Verify this concern during an independent PPI and obtain a written diagnosis "
        "before negotiating"
    ]


def _substantive_evidence_ids(case: CaseContext, kind: EvidenceKind) -> set[str]:
    """Return evidence IDs that carry an extracted fact, not just a label.

    A page/excerpt or a de-identified title match result is substantive. Generic
    binary-placeholder notes intentionally are not.
    """

    result: set[str] = set()
    history_ids = {
        evidence_id for event in case.history for evidence_id in event.evidence_ids
    }
    for evidence in case.evidence:
        if evidence.kind != kind:
            continue
        has_text = bool(evidence.excerpt and evidence.excerpt.strip())
        has_history_fact = evidence.id in history_ids
        has_title_result = kind == EvidenceKind.TITLE and evidence.metadata.get(
            "identity_title_match"
        ) in {MatchStatus.MATCH.value, MatchStatus.MISMATCH.value}
        if has_text or has_history_fact or has_title_result:
            result.add(evidence.id)
    return result


def _inspection_completion(
    case: CaseContext,
    *,
    inspection_type: str,
) -> tuple[float, set[str]]:
    required = required_inspection_keys(case.vehicle, inspection_type)  # type: ignore[arg-type]

    sessions = [
        session
        for session in case.inspections
        if session.inspection_type == inspection_type
        and (inspection_type != "ppi" or bool((session.inspector or "").strip()))
    ]
    trusted_ppi_ids = (
        trusted_ppi_artifact_evidence_ids(case) if inspection_type == "ppi" else set()
    )
    completed: set[str] = set()
    for session in sessions:
        for raw_item in session.items:
            canonical = canonicalize_inspection_item(
                raw_item,
                vehicle=case.vehicle,
                inspection_type=session.inspection_type,
            )
            item = canonical.item
            if (
                canonical.recognized
                and item.key in required
                and item.result in COMPLETED_INSPECTION_RESULTS
                and (
                    inspection_type != "ppi"
                    or bool(set(item.evidence_ids).intersection(trusted_ppi_ids))
                )
            ):
                completed.add(item.key)
    return (len(completed) / len(required) if required else 0.0), completed


def _transaction_context(case: CaseContext) -> TransactionContext | None:
    if not case.transaction_context:
        return None
    try:
        return TransactionContext.model_validate(case.transaction_context)
    except ValueError:
        return None


def _trusted_title_identity_evidence(
    case: CaseContext,
    status: MatchStatus,
) -> list[str]:
    """Return title evidence IDs structurally bound to an ingested source.

    A caller-supplied enum or a free-standing metadata dictionary is not a
    server verification.  The evidence must carry the artifact ID and digest
    created during ingestion, reference an existing source with the same
    digest, and name an approved comparison basis.
    """

    sources = {source.id: source for source in case.sources}
    trusted: list[str] = []
    for evidence in case.evidence:
        if evidence.kind != EvidenceKind.TITLE:
            continue
        source = sources.get(evidence.source_id)
        metadata_digest = evidence.metadata.get("content_sha256")
        artifact_id = evidence.metadata.get("artifact_id")
        basis = evidence.metadata.get("identity_comparison_basis")
        raw_match = evidence.metadata.get("identity_title_match")
        try:
            match = MatchStatus(raw_match)
        except (TypeError, ValueError):
            continue
        if (
            match == status
            and isinstance(basis, str)
            and basis in TRUSTED_TITLE_IDENTITY_BASES
            and source is not None
            and isinstance(metadata_digest, str)
            and metadata_digest == source.content_sha256
            and isinstance(artifact_id, str)
            and bool(artifact_id.strip())
        ):
            trusted.append(evidence.id)
    return trusted


def _title_verified(case: CaseContext) -> bool:
    context = _transaction_context(case)
    trusted_matches = _trusted_title_identity_evidence(case, MatchStatus.MATCH)
    trusted_mismatches = _trusted_title_identity_evidence(case, MatchStatus.MISMATCH)
    return bool(
        context
        and trusted_matches
        and not trusted_mismatches
        and context.title_status == TitleStatus.ORIGINAL
        and context.lien_status in {LienStatus.CLEAR, LienStatus.RELEASE_ATTACHED}
        and context.identity_title_match == MatchStatus.MATCH
        and context.vin_match == MatchStatus.MATCH
    )


def _transaction_ready(case: CaseContext) -> bool:
    if not case.transaction_plan:
        return False
    try:
        plan = TransactionPlan.model_validate(case.transaction_plan)
    except ValueError:
        return False
    return plan.decision == Decision.BUY_CANDIDATE and not any(
        gate.blocked for gate in plan.gates
    )


def _scenario(
    *,
    label: str,
    system: RiskArea,
    probability_label: str,
    low: float,
    likely: float,
    high: float,
    tests: list[str],
    evidence_id: str,
) -> RepairScenario:
    return RepairScenario(
        label=label,
        system=system,
        probability_label=probability_label,  # type: ignore[arg-type]
        cost=MoneyRange(low=low, likely=likely, high=high),
        confirmation_tests=tests,
        evidence_ids=[evidence_id],
        confidence=Confidence.LOW,
    )


def _dtc_finding(code: DtcEntry, scan: DiagnosticScan) -> RiskFinding:
    severity = (
        Severity.HIGH
        if code.status in {DtcStatus.STORED, DtcStatus.PERMANENT}
        else Severity.MEDIUM
    )
    common = dict(
        evidence_ids=[scan.evidence_id],
        status=FindingStatus.SUSPECTED,
        decision_impact=Decision.INSPECT,
        blocks_purchase=False,
    )
    if code.code.startswith("P030"):
        tests = [
            "Review freeze-frame and misfire counters after a true cold start",
            "Swap-test ignition components only if appropriate, then retest",
            "Perform compression/leak-down and injector tests if the misfire remains",
        ]
        scenarios = [
            _scenario(
                label="Ignition/connection diagnosis and minor repair",
                system=RiskArea.ENGINE,
                probability_label="minimum",
                low=150,
                likely=350,
                high=650,
                tests=tests,
                evidence_id=scan.evidence_id,
            ),
            _scenario(
                label="Fuel, air, or valve-control repair",
                system=RiskArea.ENGINE,
                probability_label="most_likely",
                low=350,
                likely=950,
                high=1800,
                tests=tests,
                evidence_id=scan.evidence_id,
            ),
            _scenario(
                label="Internal engine repair after failed compression/leak-down test",
                system=RiskArea.ENGINE,
                probability_label="worst_reasonable",
                low=2200,
                likely=4500,
                high=8000,
                tests=tests,
                evidence_id=scan.evidence_id,
            ),
        ]
        return RiskFinding(
            code=f"DTC_{code.code}_{code.status.value}",
            area=RiskArea.ENGINE,
            title=f"{code.code} misfire diagnostic branch",
            detail=(
                "The ECU detected a misfire. This does not identify a failed coil or any other single part; "
                "ignition, fueling, air leaks, valve control, and compression remain possible."
            ),
            severity=severity,
            next_checks=tests,
            repair_scenarios=scenarios,
            **common,
        )
    if code.code == "P0420":
        tests = [
            "Check for exhaust leaks and other engine codes before catalyst testing",
            "Graph upstream/downstream oxygen-sensor behavior at operating temperature",
            "Verify fuel trims and catalyst efficiency with a qualified technician",
        ]
        return RiskFinding(
            code=f"DTC_{code.code}_{code.status.value}",
            area=RiskArea.EMISSIONS,
            title="Catalyst-efficiency diagnostic branch",
            detail=(
                "P0420 reports catalyst-system efficiency below threshold; it does not by itself prove that "
                "the catalytic converter must be replaced. Exhaust leaks, sensors, fueling, or prior misfires matter."
            ),
            severity=severity,
            next_checks=tests,
            repair_scenarios=[
                _scenario(
                    label="Leak/sensor diagnosis",
                    system=RiskArea.EMISSIONS,
                    probability_label="minimum",
                    low=180,
                    likely=450,
                    high=900,
                    tests=tests,
                    evidence_id=scan.evidence_id,
                ),
                _scenario(
                    label="Confirmed emissions repair",
                    system=RiskArea.EMISSIONS,
                    probability_label="most_likely",
                    low=500,
                    likely=1400,
                    high=2600,
                    tests=tests,
                    evidence_id=scan.evidence_id,
                ),
                _scenario(
                    label="OEM catalyst plus contributing repair",
                    system=RiskArea.EMISSIONS,
                    probability_label="worst_reasonable",
                    low=1800,
                    likely=3200,
                    high=5000,
                    tests=tests,
                    evidence_id=scan.evidence_id,
                ),
            ],
            **common,
        )
    if code.code == "P0700":
        tests = [
            "Scan the transmission control module with a manufacturer-capable tool",
            "Check fluid condition/leaks and road-test shift quality",
            "Do not price a transmission replacement until the underlying TCM code is known",
        ]
        return RiskFinding(
            code=f"DTC_{code.code}_{code.status.value}",
            area=RiskArea.TRANSMISSION,
            title="Transmission controller requested the warning lamp",
            detail="P0700 is a request from the transmission controller, not a component diagnosis.",
            severity=Severity.HIGH,
            next_checks=tests,
            repair_scenarios=[
                _scenario(
                    label="Module scan and minor electrical/fluid repair",
                    system=RiskArea.TRANSMISSION,
                    probability_label="minimum",
                    low=180,
                    likely=500,
                    high=1000,
                    tests=tests,
                    evidence_id=scan.evidence_id,
                ),
                _scenario(
                    label="Valve body, solenoid, or control repair",
                    system=RiskArea.TRANSMISSION,
                    probability_label="most_likely",
                    low=900,
                    likely=2200,
                    high=4000,
                    tests=tests,
                    evidence_id=scan.evidence_id,
                ),
                _scenario(
                    label="Confirmed internal transmission repair",
                    system=RiskArea.TRANSMISSION,
                    probability_label="worst_reasonable",
                    low=3500,
                    likely=6000,
                    high=9500,
                    tests=tests,
                    evidence_id=scan.evidence_id,
                ),
            ],
            **common,
        )
    if code.code == "P0299":
        tests = [
            "Smoke/pressure-test the charge-air system",
            "Command and inspect wastegate/boost control operation",
            "Inspect turbo oil supply and shaft condition before quoting a turbo",
        ]
        return RiskFinding(
            code=f"DTC_{code.code}_{code.status.value}",
            area=RiskArea.ENGINE,
            title="Underboost diagnostic branch",
            detail="Underboost can come from leaks, controls, sensors, or turbocharger wear; the code alone does not select a repair.",
            severity=severity,
            next_checks=tests,
            repair_scenarios=[
                _scenario(
                    label="Hose/leak/control repair",
                    system=RiskArea.ENGINE,
                    probability_label="minimum",
                    low=180,
                    likely=500,
                    high=1000,
                    tests=tests,
                    evidence_id=scan.evidence_id,
                ),
                _scenario(
                    label="Wastegate or boost-control repair",
                    system=RiskArea.ENGINE,
                    probability_label="most_likely",
                    low=600,
                    likely=1500,
                    high=2800,
                    tests=tests,
                    evidence_id=scan.evidence_id,
                ),
                _scenario(
                    label="Confirmed turbocharger replacement",
                    system=RiskArea.ENGINE,
                    probability_label="worst_reasonable",
                    low=2200,
                    likely=3800,
                    high=6000,
                    tests=tests,
                    evidence_id=scan.evidence_id,
                ),
            ],
            **common,
        )
    tests = [
        "Read the manufacturer service information for this exact powertrain",
        "Review freeze-frame/live data and reproduce the symptom",
        "Obtain a written diagnosis before assigning a replacement part",
    ]
    return RiskFinding(
        code=f"DTC_{code.code}_{code.status.value}",
        area=RiskArea.ENGINE if code.code.startswith("P") else RiskArea.ELECTRICAL,
        title=f"{code.code} requires diagnosis",
        detail=code.description
        or "A diagnostic code is evidence of a monitored condition, not proof of a failed part.",
        severity=severity,
        next_checks=tests,
        repair_scenarios=[
            _scenario(
                label="Diagnostic/minor repair",
                system=RiskArea.OTHER,
                probability_label="minimum",
                low=150,
                likely=350,
                high=750,
                tests=tests,
                evidence_id=scan.evidence_id,
            ),
            _scenario(
                label="System-specific repair",
                system=RiskArea.OTHER,
                probability_label="most_likely",
                low=400,
                likely=1000,
                high=2500,
                tests=tests,
                evidence_id=scan.evidence_id,
            ),
            _scenario(
                label="Worst reasonable system repair",
                system=RiskArea.OTHER,
                probability_label="worst_reasonable",
                low=1500,
                likely=3500,
                high=7000,
                tests=tests,
                evidence_id=scan.evidence_id,
            ),
        ],
        **common,
    )


def calculate_coverage(case: CaseContext) -> tuple[float, list[str]]:
    points = 0.0
    unknowns: list[str] = []

    basic_identity = bool(
        case.vehicle.vin
        and case.vehicle.year
        and case.vehicle.make
        and case.vehicle.model
    )
    if basic_identity:
        points += 5
        corroborating_vins = [
            item.vin for item in case.listings if item.vin == case.vehicle.vin
        ] + [scan.vin for scan in case.scans if scan.vin == case.vehicle.vin]
        if len(corroborating_vins) >= 2:
            points += 5
        else:
            unknowns.append(
                "VIN/basic identity is entered but not corroborated by both listing and physical scan evidence"
            )
    else:
        unknowns.append("VIN and basic vehicle identity have not all been verified")

    if case.vehicle.powertrain_resolved:
        points += 10
    else:
        unknowns.append(
            "Exact generation/platform/engine/transmission/drivetrain/production date is not fully resolved"
        )
    evidence_ids = {item.id for item in case.evidence}
    if any(
        listing.evidence_id in evidence_ids
        and bool(listing.content_sha256)
        and listing.is_target
        for listing in case.listings
    ):
        points += 5
    else:
        unknowns.append("No evidence-backed target listing snapshot is saved")

    if _substantive_evidence_ids(case, EvidenceKind.HISTORY_REPORT):
        points += 10
    else:
        unknowns.append(
            "No extracted, evidence-backed vehicle history report facts are recorded"
        )

    if _title_verified(case):
        points += 15
    else:
        unknowns.append(
            "Original title, owner identity, VIN, and lien status are not verified"
        )

    if case.scans:
        latest = case.scans[-1]
        substantive_scan = bool(
            latest.dtcs
            or latest.readiness
            or latest.freeze_frame
            or latest.live_pids
            or latest.mil_on is not None
            or latest.vin
        )
        if (
            substantive_scan
            and latest.module_coverage.get("powertrain", ModuleCoverage.UNKNOWN)
            == ModuleCoverage.SCANNED
        ):
            points += 10
        else:
            unknowns.append(
                "No substantive generic powertrain scan with explicit module coverage is recorded"
            )
        supported = [
            monitor
            for monitor in latest.readiness
            if monitor.status in {ReadinessStatus.READY, ReadinessStatus.NOT_READY}
        ]
        if supported and all(m.status == ReadinessStatus.READY for m in supported):
            points += 5
        else:
            unknowns.append("Emissions readiness is incomplete or could not be decoded")
        _, ppi_completed = _inspection_completion(case, inspection_type="ppi")
        full_module_ppi = "full_module_scan" in ppi_completed
        for module in ("abs", "srs", "body"):
            if (
                latest.module_coverage.get(module, ModuleCoverage.UNKNOWN)
                != ModuleCoverage.SCANNED
                and not full_module_ppi
            ):
                unknowns.append(
                    f"{module.upper()} module was not verified by the available scanner"
                )
    else:
        unknowns.extend(
            ["No OBD scan is recorded", "ABS/SRS/body module status is unknown"]
        )

    self_completion, _ = _inspection_completion(case, inspection_type="self")
    points += 10 * self_completion
    if self_completion < 1:
        completed_percent = round(self_completion * 100)
        unknowns.append(
            f"Five-stage buyer inspection critical checks are only {completed_percent}% complete"
        )

    ppi_completion, _ = _inspection_completion(case, inspection_type="ppi")
    points += 20 * ppi_completion
    if ppi_completion < 1:
        completed_percent = round(ppi_completion * 100)
        unknowns.append(
            "Independent PPI requires an identified inspector, a substantive uploaded PPI report, "
            "and report-linked evidence IDs on all applicable critical checks; "
            f"current completion is {completed_percent}%"
        )

    if _substantive_evidence_ids(case, EvidenceKind.RECEIPT):
        points += 5
    else:
        unknowns.append(
            "Recent maintenance/repair receipts have no extracted, verifiable content"
        )
    return min(100.0, round(points, 2)), list(dict.fromkeys(unknowns))


def analyze_case(case: CaseContext) -> AnalysisResult:
    findings: list[RiskFinding] = findings_from_history(case)

    trusted_title_mismatches = _trusted_title_identity_evidence(
        case, MatchStatus.MISMATCH
    )
    if trusted_title_mismatches:
        context = _transaction_context(case)
        context_conflict = bool(
            context and context.identity_title_match == MatchStatus.MATCH
        )
        findings.append(
            RiskFinding(
                code="TITLE_IDENTITY_TRUSTED_MISMATCH",
                area=RiskArea.TITLE,
                title="Server-verified seller/title identity mismatch",
                detail=(
                    "The stored transaction context reports MATCH, but trusted title evidence reports MISMATCH. "
                    "The evidence controls; stop until ownership or signing authority is independently resolved."
                    if context_conflict
                    else "Trusted title evidence reports that the seller identity does not match the titled owner. "
                    "Stop until ownership or documented signing authority is independently resolved."
                ),
                severity=Severity.CRITICAL,
                status=FindingStatus.CONFIRMED,
                evidence_ids=trusted_title_mismatches,
                next_checks=[
                    "Recheck government ID against the original title or obtain documented signing authority"
                ],
                decision_impact=Decision.STOP,
                blocks_purchase=True,
            )
        )

    vins: dict[str, list[str]] = defaultdict(list)
    if case.vehicle.vin:
        vins[case.vehicle.vin].append("vehicle record")
    for item in case.listings:
        if item.vin:
            vins[item.vin].append(item.evidence_id)
    for scan in case.scans:
        if scan.vin:
            vins[scan.vin].append(scan.evidence_id)
    if len(vins) > 1:
        evidence_ids = [
            reference
            for refs in vins.values()
            for reference in refs
            if reference != "vehicle record"
        ]
        findings.append(
            RiskFinding(
                code="VIN_MISMATCH",
                area=RiskArea.TITLE,
                title="VIN mismatch across evidence",
                detail="The VIN differs between the case, listing, or scan. Stop until the physical VIN, title, and records match.",
                severity=Severity.CRITICAL,
                status=FindingStatus.CONFIRMED,
                evidence_ids=evidence_ids,
                next_checks=[
                    "Compare dashboard, door-jamb, title, and report VINs character by character"
                ],
                decision_impact=Decision.STOP,
                blocks_purchase=True,
            )
        )

    for scan in case.scans:
        findings.extend(_dtc_finding(code, scan) for code in scan.dtcs)
        not_ready = [
            monitor
            for monitor in scan.readiness
            if monitor.status == ReadinessStatus.NOT_READY
        ]
        if not_ready:
            findings.append(
                RiskFinding(
                    code=f"READINESS_NOT_READY_{scan.id}",
                    area=RiskArea.DATA_QUALITY,
                    title="Readiness monitors are not complete",
                    detail=(
                        "Incomplete monitors can follow a weak/disconnected battery, recent code clearing, or normal repairs. "
                        "They are not proof that the seller cleared codes."
                    ),
                    severity=Severity.MEDIUM if len(not_ready) >= 2 else Severity.LOW,
                    status=FindingStatus.SUSPECTED,
                    evidence_ids=[scan.evidence_id],
                    next_checks=[
                        "Complete the manufacturer drive cycle without clearing codes, then rescan"
                    ],
                    decision_impact=Decision.INSPECT,
                )
            )

    dated_mileage = sorted(
        (
            (event.event_date, event.mileage, event)
            for event in case.history
            if event.event_date and event.mileage is not None
        ),
        key=lambda item: (item[0], item[1]),
    )
    for previous, current in zip(dated_mileage, dated_mileage[1:]):
        if current[1] + 100 < previous[1]:
            findings.append(
                RiskFinding(
                    code="ODOMETER_SEQUENCE_CONFLICT",
                    area=RiskArea.ODOMETER,
                    title="Mileage decreases in the history timeline",
                    detail=f"Mileage falls from {previous[1]:,} to {current[1]:,}; verify source records and title disclosure.",
                    severity=Severity.HIGH,
                    status=FindingStatus.SUSPECTED,
                    evidence_ids=list(
                        dict.fromkeys(
                            previous[2].evidence_ids + current[2].evidence_ids
                        )
                    ),
                    next_checks=[
                        "Obtain original inspection/title records and compare the dashboard odometer"
                    ],
                    decision_impact=Decision.STOP,
                    blocks_purchase=True,
                )
            )

    for session in case.inspections:
        for raw_item in session.items:
            canonical = canonicalize_inspection_item(
                raw_item,
                vehicle=case.vehicle,
                inspection_type=session.inspection_type,
            )
            item = canonical.item
            if item.result not in {InspectionResult.CONCERN, InspectionResult.FAIL}:
                continue
            finding_status = (
                FindingStatus.CONFIRMED
                if item.result == InspectionResult.FAIL
                else FindingStatus.SUSPECTED
            )
            risk_area = inspection_risk_area(item.key)
            blocks_purchase = (
                item.result == InspectionResult.FAIL and item.key in FAIL_CLOSED_KEYS
            )
            inspect_required = (
                item.result == InspectionResult.CONCERN
                and item.key in FAIL_CLOSED_KEYS
            ) or (
                item.result == InspectionResult.FAIL
                and (
                    not canonical.recognized
                    or item.severity_if_failed
                    in {Severity.HIGH, Severity.CRITICAL}
                )
            )
            scenarios = []
            if item.estimated_cost:
                scenarios.append(
                    RepairScenario(
                        label=item.label,
                        system=risk_area,
                        probability_label="most_likely",
                        cost=item.estimated_cost,
                        confirmation_tests=["Obtain a written itemized repair quote"],
                        evidence_ids=item.evidence_ids or [session.evidence_id],
                        confidence=Confidence.MEDIUM,
                    )
                )
            findings.append(
                RiskFinding(
                    code=f"INSPECTION_{item.key.upper()}",
                    area=risk_area,
                    title=item.label,
                    detail=item.notes or f"Inspection result: {item.result.value}",
                    severity=item.severity_if_failed,
                    status=finding_status,
                    evidence_ids=item.evidence_ids or [session.evidence_id],
                    next_checks=_inspection_next_checks(
                        item.key,
                        session.inspection_type,
                    ),
                    repair_scenarios=scenarios,
                    decision_impact=(
                        Decision.STOP
                        if blocks_purchase
                        else Decision.INSPECT
                        if inspect_required
                        else Decision.NEGOTIATE
                    ),
                    blocks_purchase=blocks_purchase,
                )
            )

    coverage, unknowns = calculate_coverage(case)
    ppi_completion, _ = _inspection_completion(case, inspection_type="ppi")
    has_complete_ppi = ppi_completion == 1
    title_verified = _title_verified(case)
    transaction_ready = _transaction_ready(case)
    transaction_decision: Decision | None = None
    if case.transaction_plan:
        try:
            transaction_decision = TransactionPlan.model_validate(
                case.transaction_plan
            ).decision
        except ValueError:
            transaction_decision = None
    unresolved = [
        finding for finding in findings if finding.status != FindingStatus.RESOLVED
    ]
    if (
        any(finding.blocks_purchase for finding in unresolved)
        or transaction_decision == Decision.STOP
    ):
        decision = Decision.STOP
    elif coverage < 40 or not has_complete_ppi:
        decision = Decision.INSPECT
    elif any(f.severity in {Severity.HIGH, Severity.CRITICAL} for f in unresolved):
        decision = Decision.INSPECT
    elif coverage >= 85 and title_verified and transaction_ready:
        decision = Decision.BUY_CANDIDATE
    else:
        decision = Decision.NEGOTIATE

    if decision == Decision.STOP:
        next_actions = [
            "Stop the transaction until every blocking finding is independently resolved"
        ]
        target_status = CaseStatus.REJECTED
    elif not has_complete_ppi:
        next_actions = [
            "Arrange an independent pre-purchase inspection and keep the engine cold for arrival"
        ]
        target_status = (
            CaseStatus.REMOTE_SCREENED if case.listings else CaseStatus.NEEDS_DATA
        )
    elif decision == Decision.INSPECT:
        next_actions = [
            "Resolve high-severity PPI/diagnostic findings and obtain written repair quotes before negotiating"
        ]
        target_status = CaseStatus.PPI_COMPLETE
    elif decision == Decision.NEGOTIATE:
        next_actions = [
            "Convert confirmed PPI findings into written repair quotes before making a conditional offer"
        ]
        target_status = CaseStatus.NEGOTIATING
    else:
        next_actions = [
            "Verify title/identity/lien and complete the state transaction plan before payment"
        ]
        target_status = CaseStatus.READY_TO_BUY

    case.findings = findings
    case.coverage_percent = coverage
    case.unknowns = unknowns
    case.next_actions = next_actions
    case.decision = decision
    transition_evidence = list(
        dict.fromkeys(
            evidence_id
            for finding in findings
            if target_status != CaseStatus.REJECTED or finding.blocks_purchase
            for evidence_id in finding.evidence_ids
        )
    )
    # A STOP decision without ledger evidence remains a decision/next action,
    # but cannot silently turn into the terminal REJECTED lifecycle state.
    if target_status != CaseStatus.REJECTED or transition_evidence:
        advance_case_status(
            case,
            target_status,
            reason=f"Deterministic analysis decision: {decision.value}",
            evidence_ids=transition_evidence,
            no_op_if_unreachable=True,
        )
    case.updated_at = utc_now()
    return AnalysisResult(
        case_id=case.id,
        decision=decision,
        coverage_percent=coverage,
        valuation=case.valuation,
        findings=findings,
        unknowns=unknowns,
        next_actions=next_actions,
    )
