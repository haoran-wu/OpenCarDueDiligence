"""Comparable case ranking without a fake single reliability score."""

from __future__ import annotations

from ..inspection_catalog import canonicalize_inspection_item, inspection_risk_area
from ..listing_selection import latest_target_listing
from ..models import (
    CaseContext,
    ComparisonRisk,
    CompareResponse,
    ComparisonRow,
    Decision,
    FindingStatus,
    InspectionResult,
    MoneyRange,
    RiskArea,
)
from .risk import _inspection_completion, _title_verified


RISK_SCORE = {
    ComparisonRisk.INFO: 0,
    ComparisonRisk.LOW: 1,
    ComparisonRisk.MEDIUM: 2,
    ComparisonRisk.HIGH: 3,
    ComparisonRisk.CRITICAL: 4,
    # Unknown must never receive the same favorable ordering as an observed
    # INFO/LOW result.  It sorts after every evidence-backed risk value within
    # the same decision bucket so an empty case cannot win a shortlist.
    ComparisonRisk.UNKNOWN: 5,
}
DECISION_SCORE = {
    Decision.BUY_CANDIDATE: 0,
    Decision.NEGOTIATE: 1,
    Decision.INSPECT: 2,
    Decision.STOP: 3,
}


def _active_risk(case: CaseContext, areas: set[RiskArea]) -> ComparisonRisk | None:
    values = [
        finding.severity
        for finding in case.findings
        if finding.area in areas
        and finding.status in {FindingStatus.SUSPECTED, FindingStatus.CONFIRMED}
    ]
    if not values:
        return None
    severity = max(
        values,
        key=lambda value: RISK_SCORE[ComparisonRisk(value.value)],
    )
    return ComparisonRisk(severity.value)


def _inspection_risk(
    case: CaseContext,
    areas: set[RiskArea],
    *,
    include_custom: bool = False,
) -> ComparisonRisk | None:
    values = []
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
            area = inspection_risk_area(item.key)
            if area in areas or (include_custom and not canonical.recognized):
                values.append(item.severity_if_failed)
    if not values:
        return None
    severity = max(
        values,
        key=lambda value: RISK_SCORE[ComparisonRisk(value.value)],
    )
    return ComparisonRisk(severity.value)


def _max_observed_risk(*values: ComparisonRisk | None) -> ComparisonRisk | None:
    observed = [value for value in values if value is not None]
    if not observed:
        return None
    return max(observed, key=lambda value: RISK_SCORE[value])


def _mechanical_risk(case: CaseContext) -> ComparisonRisk:
    mechanical_areas = {
        RiskArea.ENGINE,
        RiskArea.TRANSMISSION,
        RiskArea.EMISSIONS,
        RiskArea.BRAKES,
        RiskArea.ELECTRICAL,
        RiskArea.SAFETY,
        RiskArea.STRUCTURE,
    }
    observed = _max_observed_risk(
        _active_risk(case, mechanical_areas),
        _inspection_risk(case, mechanical_areas, include_custom=True),
    )
    if observed is not None:
        return observed
    ppi_completion, _ = _inspection_completion(case, inspection_type="ppi")
    return ComparisonRisk.INFO if ppi_completion == 1 else ComparisonRisk.UNKNOWN


def _title_risk(case: CaseContext) -> ComparisonRisk:
    title_areas = {RiskArea.TITLE, RiskArea.IDENTITY, RiskArea.ODOMETER}
    observed = _max_observed_risk(
        _active_risk(case, title_areas),
        _inspection_risk(case, title_areas),
    )
    if observed is not None:
        return observed
    return ComparisonRisk.INFO if _title_verified(case) else ComparisonRisk.UNKNOWN


def _unresolved_planning_exposure(case: CaseContext) -> MoneyRange | None:
    # Only confirmed/suspected most-likely branches are aggregated. These are
    # planning exposure, not a promise that every repair will occur.
    scenarios = [
        scenario
        for finding in case.findings
        if finding.status in {FindingStatus.SUSPECTED, FindingStatus.CONFIRMED}
        for scenario in finding.repair_scenarios
        if scenario.probability_label == "most_likely"
    ]
    if not scenarios:
        return None
    return MoneyRange(
        low=sum(item.cost.low for item in scenarios),
        likely=sum(item.cost.likely for item in scenarios),
        high=sum(item.cost.high for item in scenarios),
    )


def compare_cases(cases: list[CaseContext]) -> CompareResponse:
    staged: list[tuple[tuple[float, ...], CaseContext, ComparisonRow]] = []
    for case in cases:
        target = latest_target_listing(case.listings, fallback_to_latest=True)
        asking = target.asking_price if target else None
        baseline = case.valuation.weighted_median if case.valuation else None
        attractiveness = (
            round((baseline - asking) / baseline * 100, 1)
            if baseline and asking is not None and baseline > 0
            else None
        )
        mechanical = _mechanical_risk(case)
        title = _title_risk(case)
        exposure = _unresolved_planning_exposure(case)
        reason = (
            f"{case.decision.value}; coverage {case.coverage_percent:.0f}%; "
            f"mechanical risk {mechanical.value}; title risk {title.value}"
        )
        row = ComparisonRow(
            case_id=case.id,
            rank=1,
            decision=case.decision,
            asking_price=asking,
            price_attractiveness=attractiveness,
            mechanical_risk=mechanical,
            title_risk=title,
            coverage_percent=case.coverage_percent,
            unresolved_planning_exposure=exposure,
            reason=reason,
        )
        key = (
            DECISION_SCORE[case.decision],
            RISK_SCORE[title],
            RISK_SCORE[mechanical],
            -(case.coverage_percent),
            -(attractiveness or -100),
            exposure.likely if exposure else 0,
        )
        staged.append((key, case, row))
    staged.sort(key=lambda item: item[0])
    for rank, (_, _, row) in enumerate(staged, start=1):
        row.rank = rank
    return CompareResponse(ranked=[row for _, _, row in staged])
