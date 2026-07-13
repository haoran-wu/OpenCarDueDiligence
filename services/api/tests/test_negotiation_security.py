from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.testclient import TestClient


def _create_case(client: TestClient, vehicle: dict[str, object]) -> str:
    response = client.post(
        "/v1/cases",
        json={"language": "en", "allInBudget": 8000, "vehicle": vehicle},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _listing(
    vehicle: dict[str, object],
    *,
    title: str,
    price: float,
    target: bool,
    index: int = 0,
) -> dict[str, Any]:
    return {
        "title": title,
        "askingPrice": price,
        "mileage": 120_000 + index * 500,
        "sellerType": "private",
        "channel": "user_entry",
        "year": vehicle["year"],
        "make": vehicle["make"],
        "model": vehicle["model"],
        "trim": vehicle["trim"],
        "generation": vehicle["generation"],
        "platform": vehicle["platform"],
        "engine": vehicle["engine"],
        "transmission": vehicle["transmission"],
        "drivetrain": vehicle["drivetrain"],
        "productionDate": vehicle["productionDate"],
        "fuelType": vehicle["fuelType"],
        "distanceMiles": 10 + index,
        "listedAt": (
            datetime.now(timezone.utc) - timedelta(days=10 + index)
        ).isoformat(),
        "isTarget": target,
    }


def _setup_priced_case(
    client: TestClient, vehicle: dict[str, object]
) -> tuple[str, float, str, str, str]:
    case_id = _create_case(client, vehicle)
    imported = client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={
            "listings": [
                _listing(vehicle, title="Target", price=6000, target=True),
            ]
        },
    )
    assert imported.status_code == 201, imported.text
    listing_evidence_id = imported.json()["evidenceIds"][0]

    ppi_artifact = client.post(
        f"/v1/cases/{case_id}/artifacts",
        json={
            "filename": "independent-ppi.txt",
            "kind": "ppi",
            "mediaType": "text/plain",
            "text": (
                "Independent pre-purchase inspection report: pressure test "
                "confirmed an active coolant leak and included a written estimate."
            ),
        },
    )
    assert ppi_artifact.status_code == 201, ppi_artifact.text
    ppi_evidence_id = ppi_artifact.json()["evidenceId"]
    ppi = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={
            "inspectionType": "ppi",
            "inspector": "Independent shop",
            "items": [
                {
                    "key": "coolant_leak",
                    "label": "Cooling-system leak",
                    "stage": "ppi",
                    "result": "FAIL",
                    "notes": "Pressure test found an active leak",
                    "severityIfFailed": "HIGH",
                    "estimatedCost": {"low": 500, "likely": 1100, "high": 2200},
                    "evidenceIds": [ppi_evidence_id],
                }
            ],
        },
    )
    assert ppi.status_code == 201, ppi.text

    comparables = [
        _listing(
            vehicle,
            title=f"Comparable {index}",
            price=6200 + index * 100,
            target=False,
            index=index,
        )
        for index in range(5)
    ]
    analyzed = client.post(
        f"/v1/cases/{case_id}/analyze", json={"comparables": comparables}
    )
    assert analyzed.status_code == 200, analyzed.text

    repository = client.app.state.repository
    case = repository.get_case(case_id)
    assert case.valuation is not None and case.valuation.weighted_median is not None
    finding = next(
        item for item in case.findings if item.code == "INSPECTION_COOLANT_LEAK"
    )
    # Pin the ledger coverage so these tests isolate request forgery from the
    # broader checklist coverage algorithm.
    case.coverage_percent = 80
    repository.save_case(case)
    return (
        case_id,
        case.valuation.weighted_median,
        ppi_evidence_id,
        listing_evidence_id,
        finding.id,
    )


def _payload(
    *, baseline: float, evidence_id: str, finding_id: str, amount: float = 500
) -> dict[str, Any]:
    return {
        "phase": "post_ppi",
        "language": "en",
        "askingPrice": 6000,
        "marketBaseline": baseline,
        "allInBudget": 8000,
        "evidenceCoverage": 40,
        "adjustments": [
            {
                "label": "Invented transmission replacement",
                "category": "immediate_repair",
                "amount": amount,
                "findingId": finding_id,
                "evidenceIds": [evidence_id],
            }
        ],
        "buyerMandatoryCosts": 500,
    }


def test_endpoint_uses_case_coverage_and_canonical_finding_label(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id, baseline, evidence_id, _, finding_id = _setup_priced_case(
        client, resolved_vehicle
    )
    response = client.post(
        f"/v1/cases/{case_id}/negotiation/draft",
        json=_payload(
            baseline=baseline, evidence_id=evidence_id, finding_id=finding_id
        ),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidenceReserve"] == round(baseline * 0.05, 2)
    assert "Custom inspection item: coolant_leak" in body["message"]
    assert "Invented transmission" not in body["message"]


def test_endpoint_rejects_coverage_above_case_ledger(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id, baseline, evidence_id, _, finding_id = _setup_priced_case(
        client, resolved_vehicle
    )
    payload = _payload(
        baseline=baseline, evidence_id=evidence_id, finding_id=finding_id
    )
    payload["evidenceCoverage"] = 100
    response = client.post(f"/v1/cases/{case_id}/negotiation/draft", json=payload)
    assert response.status_code == 422
    assert "cannot exceed" in response.json()["detail"]


def test_endpoint_rejects_caller_selected_market_baseline(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id, _, evidence_id, _, finding_id = _setup_priced_case(
        client, resolved_vehicle
    )
    response = client.post(
        f"/v1/cases/{case_id}/negotiation/draft",
        json=_payload(baseline=99_999, evidence_id=evidence_id, finding_id=finding_id),
    )
    assert response.status_code == 422
    assert "case valuation baseline" in response.json()["detail"]


def test_endpoint_rejects_caller_selected_asking_price(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id, baseline, evidence_id, _, finding_id = _setup_priced_case(
        client, resolved_vehicle
    )
    payload = _payload(
        baseline=baseline, evidence_id=evidence_id, finding_id=finding_id
    )
    payload["askingPrice"] = 1
    response = client.post(f"/v1/cases/{case_id}/negotiation/draft", json=payload)
    assert response.status_code == 422
    assert "current target listing" in response.json()["detail"]


def test_endpoint_binds_offer_to_latest_target_refresh(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id, baseline, evidence_id, _, finding_id = _setup_priced_case(
        client, resolved_vehicle
    )
    refreshed = _listing(
        resolved_vehicle,
        title="Target refreshed",
        price=5750,
        target=True,
    )
    refreshed["capturedAt"] = "2026-07-14T00:00:00Z"
    imported = client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={"listings": [refreshed]},
    )
    assert imported.status_code == 201, imported.text

    stale = _payload(baseline=baseline, evidence_id=evidence_id, finding_id=finding_id)
    assert (
        client.post(f"/v1/cases/{case_id}/negotiation/draft", json=stale).status_code
        == 422
    )

    current = {**stale, "askingPrice": 5750}
    response = client.post(f"/v1/cases/{case_id}/negotiation/draft", json=current)
    assert response.status_code == 200, response.text


def test_endpoint_requires_usable_case_valuation(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    response = client.post(
        f"/v1/cases/{case_id}/negotiation/draft",
        json={
            "phase": "conditional_offer",
            "askingPrice": 6000,
            "marketBaseline": 6500,
            "allInBudget": 8000,
            "adjustments": [],
        },
    )
    assert response.status_code == 422
    assert "usable case valuation" in response.json()["detail"]


def test_endpoint_rejects_missing_unknown_and_unlinked_evidence(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id, baseline, ppi_id, listing_id, finding_id = _setup_priced_case(
        client, resolved_vehicle
    )
    path = f"/v1/cases/{case_id}/negotiation/draft"

    missing = _payload(baseline=baseline, evidence_id=ppi_id, finding_id=finding_id)
    missing["adjustments"][0]["evidenceIds"] = []
    assert client.post(path, json=missing).status_code == 422

    unknown = _payload(
        baseline=baseline, evidence_id="not-in-this-case", finding_id=finding_id
    )
    assert client.post(path, json=unknown).status_code == 422

    unrelated = _payload(
        baseline=baseline, evidence_id=listing_id, finding_id=finding_id
    )
    assert client.post(path, json=unrelated).status_code == 422


def test_endpoint_caps_adjustment_and_rejects_double_deduction(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id, baseline, evidence_id, _, finding_id = _setup_priced_case(
        client, resolved_vehicle
    )
    path = f"/v1/cases/{case_id}/negotiation/draft"

    excessive = _payload(
        baseline=baseline,
        evidence_id=evidence_id,
        finding_id=finding_id,
        amount=2200.01,
    )
    assert client.post(path, json=excessive).status_code == 422

    duplicate = _payload(
        baseline=baseline, evidence_id=evidence_id, finding_id=finding_id
    )
    duplicate["adjustments"].append(
        {
            "label": "Same leak under another name",
            "category": "abnormal_risk",
            "amount": 400,
            "findingId": finding_id,
            "evidenceIds": [evidence_id],
        }
    )
    response = client.post(path, json=duplicate)
    assert response.status_code == 422
    assert "cannot be deducted more than once" in response.json()["detail"]
