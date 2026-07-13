from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import CaseContext, CaseStatus, Evidence, EvidenceKind, SourceEnvelope
from app.state_machine import (
    InvalidCaseTransition,
    RejectionEvidenceRequired,
    UnknownTransitionEvidence,
    advance_case_status,
    transition_case,
)


def _create_case(client: TestClient, vehicle: dict[str, object] | None = None) -> str:
    response = client.post("/v1/cases", json={"vehicle": vehicle or {}})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _case_with_evidence() -> tuple[CaseContext, Evidence]:
    source = SourceEnvelope(source_type="test", content_sha256="a" * 64)
    evidence = Evidence(
        source_id=source.id, kind=EvidenceKind.OTHER, label="test evidence"
    )
    return CaseContext(sources=[source], evidence=[evidence]), evidence


def test_central_transition_validates_edges_and_rejection_evidence() -> None:
    case, evidence = _case_with_evidence()
    with pytest.raises(InvalidCaseTransition):
        transition_case(case, CaseStatus.PURCHASED, reason="illegal skip")
    with pytest.raises(RejectionEvidenceRequired):
        transition_case(case, CaseStatus.REJECTED, reason="unsupported rejection")
    with pytest.raises(UnknownTransitionEvidence):
        transition_case(
            case,
            CaseStatus.REJECTED,
            reason="unknown support",
            evidence_ids=["missing"],
        )

    event = transition_case(
        case,
        CaseStatus.REJECTED,
        reason="verified title conflict",
        evidence_ids=[evidence.id],
    )
    assert event is not None
    assert case.status == CaseStatus.REJECTED
    assert case.status_history[-1].evidence_ids == [evidence.id]


def test_advance_refuses_to_fabricate_intermediate_steps() -> None:
    case, evidence = _case_with_evidence()
    with pytest.raises(InvalidCaseTransition, match="cannot infer"):
        advance_case_status(
            case,
            CaseStatus.PPI_COMPLETE,
            reason="PPI business action",
            evidence_ids=[evidence.id],
        )
    assert case.status == CaseStatus.DISCOVERED
    assert case.status_history == []

    events = advance_case_status(
        case,
        CaseStatus.NEEDS_DATA,
        reason="listing captured",
        evidence_ids=[evidence.id],
    )
    assert [event.to_status for event in events] == [CaseStatus.NEEDS_DATA]


def test_listing_route_audits_discovered_to_needs_data(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    imported = client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={"listings": [{"title": "Target", "askingPrice": 5000, "isTarget": True}]},
    )
    assert imported.status_code == 201, imported.text
    case = client.get(f"/v1/cases/{case_id}").json()
    assert case["status"] == "NEEDS_DATA"
    assert [event["toStatus"] for event in case["statusHistory"]] == ["NEEDS_DATA"]
    assert case["statusHistory"][0]["evidenceIds"] == imported.json()["evidenceIds"]


def test_ppi_route_does_not_invent_view_or_self_inspection_stages(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={"listings": [{"title": "Target", "askingPrice": 5000, "isTarget": True}]},
    )
    ppi = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={
            "inspectionType": "ppi",
            "inspector": "Independent shop",
            "items": [
                {
                    "key": "lift_check",
                    "label": "Lift inspection",
                    "stage": "ppi",
                    "result": "PASS",
                }
            ],
        },
    )
    assert ppi.status_code == 201, ppi.text
    case = client.get(f"/v1/cases/{case_id}").json()
    assert case["status"] == "NEEDS_DATA"
    assert [event["toStatus"] for event in case["statusHistory"]] == ["NEEDS_DATA"]


def test_negotiation_route_does_not_invent_missing_lifecycle_stages(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    initial = client.post(
        f"/v1/cases/{case_id}/negotiation/draft",
        json={"phase": "initial_contact", "language": "zh-CN"},
    )
    assert initial.status_code == 200, initial.text
    assert initial.json()["target"] is None
    assert initial.json()["opening"] is None
    assert initial.json()["ceiling"] is None
    assert initial.json()["evidenceReserve"] == 0
    assert "VIN" in initial.json()["message"]
    assert "保养记录" in initial.json()["message"]
    assert "故障灯" in initial.json()["message"]
    assert "购前检查" in initial.json()["message"]

    response = client.post(
        f"/v1/cases/{case_id}/negotiation/draft",
        json={
            "phase": "conditional_offer",
            "askingPrice": 6000,
            "marketBaseline": 6500,
            "allInBudget": 7000,
            "evidenceCoverage": 80,
        },
    )
    # The request also lacks a case-derived valuation, so the negotiation
    # engine correctly refuses it. Most importantly, it cannot manufacture
    # lifecycle events while rejecting the request.
    assert response.status_code == 422, response.text
    case = client.get(f"/v1/cases/{case_id}").json()
    assert case["status"] == "DISCOVERED"
    assert case["statusHistory"] == []


def test_analyze_advances_and_rejects_only_with_blocking_evidence(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    imported = client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={
            "listings": [
                {
                    "title": "Conflicting VIN listing",
                    "askingPrice": 5000,
                    "vin": "2TESTCAR000000002",
                    "isTarget": True,
                }
            ]
        },
    )
    assert imported.status_code == 201, imported.text
    analyzed = client.post(f"/v1/cases/{case_id}/analyze", json={})
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["decision"] == "STOP"
    case = client.get(f"/v1/cases/{case_id}").json()
    assert case["status"] == "REJECTED"
    rejected = case["statusHistory"][-1]
    assert rejected["toStatus"] == "REJECTED"
    assert rejected["evidenceIds"] == imported.json()["evidenceIds"]


def test_manual_reject_persists_reason_and_known_evidence(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    imported = client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={"listings": [{"title": "Target", "askingPrice": 5000, "isTarget": True}]},
    ).json()
    evidence_id = imported["evidenceIds"][0]
    response = client.patch(
        f"/v1/cases/{case_id}/status",
        json={
            "status": "REJECTED",
            "reason": "Seller title name does not match verified ID",
            "evidenceIds": [evidence_id],
        },
    )
    assert response.status_code == 200, response.text
    event = response.json()["statusHistory"][-1]
    assert event["toStatus"] == "REJECTED"
    assert event["reason"] == "Seller title name does not match verified ID"
    assert event["evidenceIds"] == [evidence_id]
