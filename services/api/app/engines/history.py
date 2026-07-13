"""Conservative findings derived from user-provided history evidence."""

from __future__ import annotations

from ..listing_selection import latest_target_listing
from ..models import (
    CaseContext,
    Decision,
    FindingStatus,
    RiskArea,
    RiskFinding,
    Severity,
)


def _evidence(events: list) -> list[str]:
    return list(dict.fromkeys(evidence_id for event in events for evidence_id in event.evidence_ids))


def findings_from_history(case: CaseContext) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    by_type: dict[str, list] = {}
    for event in case.history:
        by_type.setdefault(event.event_type, []).append(event)

    brands = by_type.get("title_brand_reported", [])
    if brands:
        findings.append(
            RiskFinding(
                code="HISTORY_TITLE_BRAND",
                area=RiskArea.TITLE,
                title="History evidence reports a branded title",
                detail="An affirmative salvage/rebuilt/junk/lemon title statement was extracted. Verify the original title and issuing DMV before continuing.",
                severity=Severity.CRITICAL,
                status=FindingStatus.CONFIRMED,
                evidence_ids=_evidence(brands),
                next_checks=["Inspect the original title and obtain a current NMVTIS/DMV title record"],
                decision_impact=Decision.STOP,
                blocks_purchase=True,
            )
        )

    for event_type, code, title, area, severity in (
        ("structural_damage_reported", "HISTORY_STRUCTURAL_DAMAGE", "Structural damage is reported in the history", RiskArea.STRUCTURE, Severity.HIGH),
        ("flood_damage_reported", "HISTORY_FLOOD_DAMAGE", "Flood or water damage is reported in the history", RiskArea.STRUCTURE, Severity.CRITICAL),
        ("accident_or_damage_reported", "HISTORY_ACCIDENT_DAMAGE", "Accident or damage is reported in the history", RiskArea.HISTORY, Severity.MEDIUM),
    ):
        events = by_type.get(event_type, [])
        if events:
            findings.append(
                RiskFinding(
                    code=code,
                    area=area,
                    title=title,
                    detail="The report contains affirmative damage wording. CARFAX/history data alone does not establish the quality of repairs or present structural safety.",
                    severity=severity,
                    status=FindingStatus.CONFIRMED,
                    evidence_ids=_evidence(events),
                    next_checks=["Require an independent body/structure inspection and repair documentation"],
                    decision_impact=Decision.INSPECT,
                )
            )

    emissions_failures = by_type.get("emissions_failed", [])
    if len(emissions_failures) >= 2:
        findings.append(
            RiskFinding(
                code="HISTORY_REPEATED_EMISSIONS_FAILURES",
                area=RiskArea.EMISSIONS,
                title="Multiple emissions failures appear in the history",
                detail="Repeated failures can have unrelated causes, including incomplete readiness. Obtain the actual inspection results; do not infer a failed part from the history alone.",
                severity=Severity.MEDIUM,
                status=FindingStatus.SUSPECTED,
                evidence_ids=_evidence(emissions_failures),
                next_checks=["Request both inspection receipts, scan all emissions DTC states, and verify readiness after a normal drive cycle"],
                decision_impact=Decision.INSPECT,
            )
        )

    safety_failures = by_type.get("safety_failed", [])
    if safety_failures:
        findings.append(
            RiskFinding(
                code="HISTORY_SAFETY_FAILURE",
                area=RiskArea.SAFETY,
                title="A safety inspection failure appears in the history",
                detail="The history does not identify whether the failed item was minor or safety-critical. Verify the failure sheet and completed repair.",
                severity=Severity.HIGH,
                status=FindingStatus.SUSPECTED,
                evidence_ids=_evidence(safety_failures),
                next_checks=["Obtain the failed inspection sheet, repair invoice, and current PPI confirmation"],
                decision_impact=Decision.INSPECT,
            )
        )

    services = sorted(
        (event for event in by_type.get("service", []) if event.event_date),
        key=lambda event: event.event_date,
    )
    large_gaps: list[tuple] = []
    for previous, current in zip(services, services[1:]):
        days = (current.event_date - previous.event_date).days
        mileage_delta = (
            current.mileage - previous.mileage
            if current.mileage is not None and previous.mileage is not None
            else None
        )
        if days > 730 or (mileage_delta is not None and mileage_delta > 30_000):
            large_gaps.append((previous, current, days, mileage_delta))
    if large_gaps:
        events = [event for gap in large_gaps for event in gap[:2]]
        findings.append(
            RiskFinding(
                code="HISTORY_SERVICE_RECORD_GAP",
                area=RiskArea.DATA_QUALITY,
                title="The supplied report has a long service-record gap",
                detail="This is a gap in reported records, not proof that maintenance was skipped. Ask for receipts and judge condition through the PPI.",
                severity=Severity.LOW,
                status=FindingStatus.SUSPECTED,
                evidence_ids=_evidence(events),
                next_checks=["Request maintenance receipts covering the gap and verify fluid/service condition during PPI"],
                decision_impact=Decision.INSPECT,
            )
        )

    target_listing = latest_target_listing(case.listings)
    listing_text = (
        f"{target_listing.title} {target_listing.description or ''}".lower()
        if target_listing
        else ""
    )
    conflicts: list[str] = []
    conflict_evidence: list[str] = []
    if brands and "clean title" in listing_text:
        conflicts.append("the listing says clean title while the history reports a title brand")
        conflict_evidence.extend(_evidence(brands))
    accidents = by_type.get("accident_or_damage_reported", [])
    if accidents and any(term in listing_text for term in ("no accident", "never accident", "no damage")):
        conflicts.append("the listing denies accident/damage while the history affirmatively reports it")
        conflict_evidence.extend(_evidence(accidents))
    if conflicts:
        if target_listing:
            conflict_evidence.append(target_listing.evidence_id)
        findings.append(
            RiskFinding(
                code="LISTING_HISTORY_CONFLICT",
                area=RiskArea.SELLER,
                title="Listing claims conflict with supplied history evidence",
                detail="; ".join(conflicts).capitalize() + ". Resolve the documentary conflict before relying on the listing.",
                severity=Severity.CRITICAL if brands else Severity.HIGH,
                status=FindingStatus.CONFIRMED,
                evidence_ids=list(dict.fromkeys(conflict_evidence)),
                next_checks=["Compare the original title, report page, physical VIN, and seller's written explanation"],
                decision_impact=Decision.STOP,
                blocks_purchase=True,
            )
        )

    return findings
