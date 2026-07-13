"""Traceable negotiation arithmetic and bilingual deterministic messages."""

from __future__ import annotations

from math import isclose

from ..listing_selection import latest_target_listing
from ..models import (
    AdjustmentCategory,
    CaseContext,
    EvidenceKind,
    FindingStatus,
    InspectionResult,
    Language,
    NegotiationAdjustment,
    NegotiationPhase,
    NegotiationRequest,
    NegotiationState,
    NegotiationTraceItem,
)


class NegotiationEvidenceError(ValueError):
    """The requested arithmetic is not supported by the case evidence ledger."""


def _supported_finding_ceiling(case: CaseContext, finding_id: str, evidence_ids: set[str]) -> float:
    """Return the largest non-worst documented scenario for one finding.

    A ``worst_reasonable`` diagnostic branch is deliberately not an automatic
    bargaining deduction.  It becomes priceable only when a PPI records a
    written estimate, which is represented by ``InspectionItem.estimated_cost``.
    """

    finding = next(item for item in case.findings if item.id == finding_id)
    ceilings = [
        scenario.cost.high
        for scenario in finding.repair_scenarios
        if scenario.probability_label in {"minimum", "most_likely"}
        and evidence_ids.intersection(scenario.evidence_ids)
    ]
    for session in case.inspections:
        if session.inspection_type != "ppi":
            continue
        for item in session.items:
            if item.result not in {InspectionResult.CONCERN, InspectionResult.FAIL}:
                continue
            if finding.code != f"INSPECTION_{item.key.upper()}":
                continue
            item_evidence = set(item.evidence_ids or [session.evidence_id])
            if item.estimated_cost and evidence_ids.intersection(item_evidence):
                ceilings.append(item.estimated_cost.high)
    return max(ceilings, default=0.0)


def normalize_case_negotiation(
    case: CaseContext,
    request: NegotiationRequest,
) -> NegotiationRequest:
    """Bind client-supplied negotiation inputs to the persisted case.

    The public request shape stays compatible, but the caller cannot mint a
    better coverage score, choose a different market baseline, or attach an
    arbitrary label/amount to unrelated evidence.
    """

    if request.phase == NegotiationPhase.INITIAL_CONTACT:
        # This phase only asks the seller for screening evidence.  Do not let
        # missing valuation data block it, and do not retain client-supplied
        # price adjustments in a message that makes no offer.
        return request.model_copy(
            update={
                "asking_price": None,
                "market_baseline": None,
                "all_in_budget": None,
                "evidence_coverage": case.coverage_percent,
                "adjustments": [],
                "buyer_mandatory_costs": 0,
                "seller_floor": None,
            }
        )

    valuation = case.valuation
    if valuation is None or valuation.weighted_median is None or valuation.sample_count < 5:
        raise NegotiationEvidenceError(
            "A usable case valuation with at least five admitted comparables is required"
        )
    baseline = round(valuation.weighted_median, 2)
    if request.market_baseline is None:
        raise NegotiationEvidenceError("marketBaseline is required for price-offer phases")
    if not isclose(request.market_baseline, baseline, rel_tol=0.0, abs_tol=0.01):
        raise NegotiationEvidenceError(
            f"marketBaseline must match the case valuation baseline ({baseline:.2f})"
        )
    target_listing = latest_target_listing(case.listings)
    if target_listing is None:
        raise NegotiationEvidenceError("A target listing is required before drafting an offer")
    asking_price = round(target_listing.asking_price, 2)
    if request.asking_price is None:
        raise NegotiationEvidenceError("askingPrice is required for price-offer phases")
    if not isclose(request.asking_price, asking_price, rel_tol=0.0, abs_tol=0.01):
        raise NegotiationEvidenceError(
            f"askingPrice must match the current target listing ({asking_price:.2f})"
        )
    if (
        request.evidence_coverage is not None
        and request.evidence_coverage > case.coverage_percent + 0.01
    ):
        raise NegotiationEvidenceError(
            "evidenceCoverage cannot exceed the case evidence coverage"
        )
    if request.all_in_budget is None:
        raise NegotiationEvidenceError("allInBudget is required for price-offer phases")

    evidence_by_id = {item.id: item for item in case.evidence}
    ppi_evidence_ids: set[str] = set()
    for session in case.inspections:
        if session.inspection_type != "ppi":
            continue
        ppi_evidence_ids.add(session.evidence_id)
        for item in session.items:
            ppi_evidence_ids.update(item.evidence_ids)
    history_evidence_ids = {
        evidence_id for event in case.history for evidence_id in event.evidence_ids
    }
    negotiation_evidence_kinds = {
        EvidenceKind.PPI,
        EvidenceKind.HISTORY_REPORT,
        EvidenceKind.STATE_INSPECTION,
        EvidenceKind.RECEIPT,
    }
    eligible_origin_ids = {
        evidence_id
        for evidence_id in ppi_evidence_ids | history_evidence_ids
        if evidence_id in evidence_by_id
        and evidence_by_id[evidence_id].kind in negotiation_evidence_kinds
    }
    eligible_findings = [
        finding
        for finding in case.findings
        if finding.status in {FindingStatus.SUSPECTED, FindingStatus.CONFIRMED}
        and set(finding.evidence_ids).intersection(eligible_origin_ids)
    ]

    normalized_adjustments: list[NegotiationAdjustment] = []
    used_finding_ids: set[str] = set()
    for adjustment in request.adjustments:
        evidence_ids = list(dict.fromkeys(adjustment.evidence_ids))
        unknown = [item for item in evidence_ids if item not in evidence_by_id]
        if unknown:
            raise NegotiationEvidenceError(
                "Unknown adjustment evidenceIds: " + ", ".join(unknown)
            )

        # Normal wear is never deducted.  Known references may remain in the
        # trace, but no supporting repair amount is required for an ignored row.
        if adjustment.normal_wear or adjustment.amount == 0:
            normalized_adjustments.append(
                adjustment.model_copy(update={"evidence_ids": evidence_ids})
            )
            continue
        if not evidence_ids:
            raise NegotiationEvidenceError(
                "Every applied negotiation adjustment requires evidenceIds"
            )

        requested_ids = set(evidence_ids)
        matched_findings = [
            finding
            for finding in eligible_findings
            if requested_ids.intersection(finding.evidence_ids)
        ]
        if adjustment.finding_id is not None:
            matched_findings = [
                finding
                for finding in matched_findings
                if finding.id == adjustment.finding_id
            ]
            if not matched_findings:
                raise NegotiationEvidenceError(
                    "findingId does not identify an eligible finding linked to the supplied evidenceIds"
                )
        elif len(matched_findings) > 1:
            label_matches = [
                finding
                for finding in matched_findings
                if finding.title.casefold() == adjustment.label.casefold()
            ]
            if len(label_matches) != 1:
                raise NegotiationEvidenceError(
                    "The evidenceIds link to multiple findings; provide findingId to select one"
                )
            matched_findings = label_matches
        linked_ids = {
            evidence_id
            for finding in matched_findings
            for evidence_id in finding.evidence_ids
            if evidence_id in requested_ids
        }
        unlinked = requested_ids - linked_ids
        if unlinked or not matched_findings:
            raise NegotiationEvidenceError(
                "Every adjustment evidenceId must link to a suspected or confirmed PPI/history finding"
            )

        duplicate_findings = used_finding_ids.intersection(
            finding.id for finding in matched_findings
        )
        if duplicate_findings:
            raise NegotiationEvidenceError(
                "The same documented finding cannot be deducted more than once"
            )

        supported_ceiling = sum(
            _supported_finding_ceiling(case, finding.id, requested_ids)
            for finding in matched_findings
        )
        if supported_ceiling <= 0:
            raise NegotiationEvidenceError(
                "The linked finding has no written estimate or supported repair-cost scenario"
            )
        if round(adjustment.amount, 2) > round(supported_ceiling, 2):
            raise NegotiationEvidenceError(
                f"Adjustment amount exceeds the documented ceiling ({supported_ceiling:.2f})"
            )

        used_finding_ids.update(finding.id for finding in matched_findings)
        canonical_label = " / ".join(
            dict.fromkeys(finding.title for finding in matched_findings)
        )
        normalized_adjustments.append(
            adjustment.model_copy(
                update={
                    "label": canonical_label,
                    "finding_id": matched_findings[0].id if len(matched_findings) == 1 else None,
                    "evidence_ids": sorted(requested_ids),
                }
            )
        )

    return request.model_copy(
        update={
            "market_baseline": baseline,
            "asking_price": asking_price,
            "evidence_coverage": case.coverage_percent,
            "adjustments": normalized_adjustments,
        }
    )


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _message(
    request: NegotiationRequest,
    *,
    language: Language,
    opening: float | None,
    ceiling: float | None,
    decision: str,
    applied_labels: list[str],
) -> str:
    if language == Language.ZH_CN:
        if request.phase == NegotiationPhase.INITIAL_CONTACT:
            return (
                "你好，我对这辆车有兴趣。方便先提供VIN，并确认原始title在你本人名下、没有未解除的lien吗？"
                "另外，是否有近期保养记录？目前有没有故障灯、漏油漏水、机械或电气问题？"
                "是否允许我安排独立购前检查？谢谢。"
            )
        if decision == "INSPECT_FIRST":
            return "目前关键信息不足，我需要先完成独立检查并核实title和维修记录，之后才能负责任地报价。"
        if decision == "WALK_AWAY":
            return (
                f"谢谢你的说明。根据目前可核实的车况和我的总预算，我的最高价格是{_money(ceiling or 0)}。"
                "如果以后这个价格可以考虑，欢迎联系我；否则也祝你顺利卖车。"
            )
        evidence = "、".join(applied_labels[:3]) or "当前可核实的检查结果"
        return (
            f"谢谢。我根据{evidence}以及同配置车辆的市场区间，愿意提出{_money(opening or 0)}的有条件报价。"
            "前提是原始title、VIN和卖家身份一致，并且独立检查没有发现新的重大问题。"
        )

    if request.phase == NegotiationPhase.INITIAL_CONTACT:
        return (
            "Hi, I’m interested in the car. Could you send the VIN and confirm that the original title is "
            "in your name with no unresolved lien? Do you have recent maintenance records? Are there any "
            "warning lights, leaks, mechanical or electrical issues I should know about? Are you comfortable "
            "with an independent pre-purchase inspection? Thank you."
        )
    if decision == "INSPECT_FIRST":
        return (
            "I still need to complete an independent inspection and verify the title and maintenance records "
            "before I can make a responsible final offer."
        )
    if decision == "WALK_AWAY":
        return (
            f"Thank you for the information. Based on the documented condition and my all-in budget, my ceiling "
            f"is {_money(ceiling or 0)}. If that becomes workable later, feel free to contact me; otherwise, I "
            "understand and wish you the best with the sale."
        )
    evidence = ", ".join(applied_labels[:3]) or "the documented inspection results"
    return (
        f"Thanks. Based on {evidence} and the market range for the same configuration, I can make a conditional "
        f"offer of {_money(opening or 0)}. This is subject to the original title, VIN, and seller identity matching "
        "and an independent inspection finding no additional major issues."
    )


def draft_negotiation(
    request: NegotiationRequest,
    *,
    case_id: str | None = None,
    default_language: Language = Language.EN,
) -> NegotiationState:
    language = request.language or default_language
    if request.phase == NegotiationPhase.INITIAL_CONTACT:
        return NegotiationState(
            case_id=case_id,
            phase=request.phase,
            target=None,
            opening=None,
            ceiling=None,
            evidence_reserve=0,
            decision="INSPECT_FIRST",
            trace=[
                NegotiationTraceItem(
                    label="Initial seller screening",
                    amount=0,
                    applied=False,
                    reason="No valuation, price offer, or evidence deduction is used in the initial-contact phase",
                )
            ],
            message=_message(
                request,
                language=language,
                opening=None,
                ceiling=None,
                decision="INSPECT_FIRST",
                applied_labels=[],
            ),
            language=language,
        )

    if (
        request.asking_price is None
        or request.market_baseline is None
        or request.all_in_budget is None
    ):
        raise NegotiationEvidenceError(
            "askingPrice, marketBaseline, and allInBudget are required for price-offer phases"
        )

    coverage = request.evidence_coverage if request.evidence_coverage is not None else 0
    if coverage >= 85:
        reserve_rate = 0.02
    elif coverage >= 65:
        reserve_rate = 0.05
    elif coverage >= 40:
        reserve_rate = 0.10
    else:
        reserve_rate = 0.10
    reserve = round(request.market_baseline * reserve_rate, 2)

    totals = {
        AdjustmentCategory.IMMEDIATE_REPAIR: 0.0,
        AdjustmentCategory.OVERDUE_MAINTENANCE: 0.0,
        AdjustmentCategory.ABNORMAL_RISK: 0.0,
    }
    trace: list[NegotiationTraceItem] = []
    seen: set[tuple[object, ...]] = set()
    applied_labels: list[str] = []
    for adjustment in request.adjustments:
        key = (
            adjustment.label.lower(),
            adjustment.category.value,
            round(adjustment.amount, 2),
            tuple(sorted(adjustment.evidence_ids)),
        )
        if adjustment.normal_wear:
            applied = False
            reason = "Normal age/mileage wear is already reflected in the market baseline"
        elif adjustment.amount == 0:
            applied = False
            reason = "Zero-dollar adjustment was not applied"
        elif key in seen:
            applied = False
            reason = "Exact duplicate adjustment was not counted twice"
        else:
            seen.add(key)
            applied = True
            reason = f"Applied as {adjustment.category.value}"
            totals[adjustment.category] += adjustment.amount
            applied_labels.append(adjustment.label)
        trace.append(
            NegotiationTraceItem(
                label=adjustment.label,
                amount=adjustment.amount,
                applied=applied,
                reason=reason,
                evidence_ids=adjustment.evidence_ids,
            )
        )

    trace.append(
        NegotiationTraceItem(
            label="Evidence coverage reserve",
            amount=reserve,
            applied=coverage >= 40,
            reason=f"{reserve_rate:.0%} of baseline at {coverage:.0f}% evidence coverage",
        )
    )

    if coverage < 40:
        message = _message(
            request,
            language=language,
            opening=None,
            ceiling=None,
            decision="INSPECT_FIRST",
            applied_labels=applied_labels,
        )
        return NegotiationState(
            case_id=case_id,
            phase=request.phase,
            target=None,
            opening=None,
            ceiling=None,
            evidence_reserve=reserve,
            decision="INSPECT_FIRST",
            trace=trace,
            message=message,
            language=language,
        )

    total_adjustments = sum(totals.values())
    target = max(0.0, request.market_baseline - total_adjustments - reserve)
    opening_discount = min(0.05 * request.market_baseline, 1000)
    opening_candidate = max(
        0.0,
        min(request.asking_price, target) - opening_discount,
    )
    affordability_ceiling = max(0.0, request.all_in_budget - request.buyer_mandatory_costs)
    ceiling = max(
        0.0,
        min(target + min(0.02 * request.market_baseline, 500), affordability_ceiling),
    )
    target, opening_candidate, ceiling = (
        round(target, 2),
        round(opening_candidate, 2),
        round(ceiling, 2),
    )
    feasible_offer_band = opening_candidate <= ceiling
    trace.append(
        NegotiationTraceItem(
            label="Buyer affordability ceiling",
            amount=ceiling,
            applied=feasible_offer_band,
            reason=(
                "The documented opening offer is within the all-in budget ceiling"
                if feasible_offer_band
                else "No offer is generated because the documented opening would exceed the all-in budget ceiling"
            ),
        )
    )

    if request.phase == NegotiationPhase.WALK_AWAY or (
        request.seller_floor is not None and request.seller_floor > ceiling
    ) or not feasible_offer_band:
        decision = "WALK_AWAY"
    elif request.seller_floor is not None and request.seller_floor == ceiling:
        decision = "WAIT"
    else:
        decision = "MAKE_OFFER"
    opening = None if decision == "WALK_AWAY" else opening_candidate
    message = _message(
        request,
        language=language,
        opening=opening,
        ceiling=ceiling,
        decision=decision,
        applied_labels=applied_labels,
    )
    return NegotiationState(
        case_id=case_id,
        phase=request.phase,
        target=target,
        opening=opening,
        ceiling=ceiling,
        evidence_reserve=reserve,
        decision=decision,  # type: ignore[arg-type]
        trace=trace,
        message=message,
        language=language,
    )
