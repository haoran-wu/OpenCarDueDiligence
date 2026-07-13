"""Audited case-lifecycle transitions.

This module is the only place that may mutate ``CaseContext.status``. A business
action may record only the next real edge. It must never manufacture intermediate
events such as VIEW_SCHEDULED or SELF_INSPECTED merely because later evidence was
uploaded.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import CaseContext, CaseStatus, CaseStatusEvent


FORWARD_STATUS_GRAPH: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.DISCOVERED: frozenset({CaseStatus.NEEDS_DATA, CaseStatus.REJECTED}),
    CaseStatus.NEEDS_DATA: frozenset({CaseStatus.REMOTE_SCREENED, CaseStatus.REJECTED}),
    CaseStatus.REMOTE_SCREENED: frozenset({CaseStatus.VIEW_SCHEDULED, CaseStatus.REJECTED}),
    CaseStatus.VIEW_SCHEDULED: frozenset({CaseStatus.SELF_INSPECTED, CaseStatus.REJECTED}),
    CaseStatus.SELF_INSPECTED: frozenset({CaseStatus.PPI_COMPLETE, CaseStatus.REJECTED}),
    CaseStatus.PPI_COMPLETE: frozenset({CaseStatus.NEGOTIATING, CaseStatus.REJECTED}),
    CaseStatus.NEGOTIATING: frozenset({CaseStatus.READY_TO_BUY, CaseStatus.REJECTED}),
    CaseStatus.READY_TO_BUY: frozenset({CaseStatus.PURCHASED, CaseStatus.REJECTED}),
    CaseStatus.PURCHASED: frozenset({CaseStatus.REGISTERED, CaseStatus.REJECTED}),
    # A late-discovered title or identity conflict must remain recordable even
    # after registration; REJECTED is still terminal.
    CaseStatus.REGISTERED: frozenset({CaseStatus.REJECTED}),
    CaseStatus.REJECTED: frozenset(),
}


class CaseTransitionError(ValueError):
    """Base class for lifecycle validation errors."""


class InvalidCaseTransition(CaseTransitionError):
    """Raised when the requested edge/path is not in the canonical graph."""


class UnknownTransitionEvidence(CaseTransitionError):
    """Raised when an audit event references evidence outside the case."""

    def __init__(self, evidence_ids: list[str]) -> None:
        self.evidence_ids = evidence_ids
        super().__init__(f"unknown evidence IDs: {', '.join(evidence_ids)}")


class RejectionEvidenceRequired(CaseTransitionError):
    """Raised when REJECTED would be recorded without concrete evidence."""


def _validated_evidence_ids(case: CaseContext, evidence_ids: Iterable[str]) -> list[str]:
    normalized = list(dict.fromkeys(item for item in evidence_ids if item))
    known = {item.id for item in case.evidence}
    unknown = [item for item in normalized if item not in known]
    if unknown:
        raise UnknownTransitionEvidence(unknown)
    return normalized


def transition_case(
    case: CaseContext,
    to_status: CaseStatus,
    *,
    reason: str,
    evidence_ids: Iterable[str] = (),
) -> CaseStatusEvent | None:
    """Apply one legal graph edge and append its immutable audit event.

    Asking for the current status is idempotent and does not create a duplicate
    audit event.  A rejection always requires at least one evidence ID that is
    already present in the case evidence ledger.
    """

    if to_status == case.status:
        return None
    if to_status not in FORWARD_STATUS_GRAPH[case.status]:
        raise InvalidCaseTransition(
            f"invalid case status transition: {case.status.value} -> {to_status.value}"
        )
    normalized_evidence = _validated_evidence_ids(case, evidence_ids)
    if to_status == CaseStatus.REJECTED and not normalized_evidence:
        raise RejectionEvidenceRequired("REJECTED requires at least one evidence ID")

    previous = case.status
    event = CaseStatusEvent(
        from_status=previous,
        to_status=to_status,
        reason=reason,
        evidence_ids=normalized_evidence,
    )
    case.status = to_status
    case.status_history.append(event)
    return event


def advance_case_status(
    case: CaseContext,
    to_status: CaseStatus,
    *,
    reason: str,
    evidence_ids: Iterable[str] = (),
    no_op_if_unreachable: bool = False,
) -> list[CaseStatusEvent]:
    """Record one real next-stage transition, never synthetic intermediate stages.

    ``no_op_if_unreachable`` is intended for deterministic re-analysis: a new
    analysis must never move a lifecycle backwards or resurrect a rejected
    case. It also lets evidence upload succeed while the lifecycle remains at
    its honest earlier stage. Interactive status changes should keep the
    default and surface a conflict instead.
    """

    if case.status == to_status:
        return []
    if to_status not in FORWARD_STATUS_GRAPH[case.status]:
        if no_op_if_unreachable:
            return []
        raise InvalidCaseTransition(
            "case lifecycle cannot infer missing intermediate stages: "
            f"{case.status.value} -> {to_status.value}"
        )
    event = transition_case(
        case,
        to_status,
        reason=reason,
        evidence_ids=evidence_ids,
    )
    return [event] if event is not None else []


__all__ = [
    "FORWARD_STATUS_GRAPH",
    "CaseTransitionError",
    "InvalidCaseTransition",
    "UnknownTransitionEvidence",
    "RejectionEvidenceRequired",
    "advance_case_status",
    "transition_case",
]
