from __future__ import annotations

from fastapi.testclient import TestClient

from app.engines.repair_cost import compare_repair_costs, estimate_repair_cost
from app.models import MoneyRange, NumberRange, RepairCostComparisonRequest, RepairCostRequest


def test_repair_cost_formula_is_transparent_and_ordered() -> None:
    result = estimate_repair_cost(
        RepairCostRequest(
            label="Cooling system repair",
            zip3="112",
            shop_type="independent",
            diagnostic_fee=MoneyRange(low=100, likely=150, high=200),
            parts=MoneyRange(low=200, likely=400, high=800),
            labor_hours=NumberRange(low=2, likely=3, high=5),
            hourly_rate=MoneyRange(low=140, likely=170, high=210),
            tax_rate=0.08875,
            shop_supplies_rate=0.05,
        )
    )
    assert result.total.low < result.total.likely < result.total.high
    assert result.confidence == "MEDIUM"
    assert "diagnosis + parts" in result.formula


def test_repair_cost_comparison_returns_all_four_shop_types() -> None:
    result = compare_repair_costs(
        RepairCostComparisonRequest(
            label="Cooling-system diagnosis",
            zip3="112",
            diagnosticFee=MoneyRange(low=0, likely=150, high=250),
            parts=MoneyRange(low=20, likely=300, high=1200),
            laborHours=NumberRange(low=0.5, likely=2, high=6),
        )
    )
    assert [estimate.shop_type for estimate in result.estimates] == [
        "diy",
        "independent",
        "specialist",
        "dealer",
    ]
    assert result.estimates[0].total.likely < result.estimates[-1].total.likely
    assert all(estimate.confidence == "LOW" for estimate in result.estimates)


def test_repair_cost_comparison_api(client: TestClient) -> None:
    response = client.post(
        "/v1/repair-cost/compare",
        json={
            "label": "Cooling-system diagnosis",
            "zip3": "112",
            "parts": {"low": 20, "likely": 300, "high": 1200},
            "laborHours": {"low": 0.5, "likely": 2, "high": 6},
        },
    )
    assert response.status_code == 200, response.text
    assert [item["shopType"] for item in response.json()["estimates"]] == [
        "diy",
        "independent",
        "specialist",
        "dealer",
    ]
