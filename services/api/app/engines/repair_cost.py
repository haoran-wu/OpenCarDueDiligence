"""Transparent regional repair-cost arithmetic."""

from __future__ import annotations

from ..models import (
    Confidence,
    MoneyRange,
    RepairCostComparisonRequest,
    RepairCostComparisonResult,
    RepairCostRequest,
    RepairCostResult,
    ShopType,
)


DEFAULT_RATES: dict[ShopType, MoneyRange] = {
    ShopType.DIY: MoneyRange(low=0, likely=0, high=0),
    ShopType.INDEPENDENT: MoneyRange(low=105, likely=150, high=210),
    ShopType.SPECIALIST: MoneyRange(low=135, likely=190, high=270),
    ShopType.DEALER: MoneyRange(low=190, likely=270, high=380),
}


def estimate_repair_cost(request: RepairCostRequest) -> RepairCostResult:
    supplied_rate = request.hourly_rate is not None
    base = request.hourly_rate or DEFAULT_RATES[request.shop_type]
    rate = MoneyRange(
        low=round(base.low * request.regional_multiplier, 2),
        likely=round(base.likely * request.regional_multiplier, 2),
        high=round(base.high * request.regional_multiplier, 2),
    )

    def component(diagnosis: float, parts: float, hours: float, hourly: float) -> float:
        labor = hours * hourly
        subtotal = diagnosis + parts + labor
        supplies = (parts + labor) * request.shop_supplies_rate
        tax = (parts + labor + supplies) * request.tax_rate
        return round(subtotal + supplies + tax, 2)

    total = MoneyRange(
        low=component(
            request.diagnostic_fee.low,
            request.parts.low,
            request.labor_hours.low,
            rate.low,
        ),
        likely=component(
            request.diagnostic_fee.likely,
            request.parts.likely,
            request.labor_hours.likely,
            rate.likely,
        ),
        high=component(
            request.diagnostic_fee.high,
            request.parts.high,
            request.labor_hours.high,
            rate.high,
        ),
    )
    assumptions = [
        f"ZIP3 {request.zip3}; multiplier {request.regional_multiplier:.2f}",
        f"Tax {request.tax_rate:.1%}; shop supplies {request.shop_supplies_rate:.1%}",
    ]
    if supplied_rate:
        assumptions.append("Hourly range supplied by user/provider")
        confidence = Confidence.MEDIUM
    else:
        assumptions.append("National default hourly range; obtain a local written quote")
        confidence = Confidence.LOW
    if request.shop_type == ShopType.DIY:
        assumptions.append("DIY labor is valued at $0 and does not include tools, towing, or lost time")
    return RepairCostResult(
        label=request.label,
        zip3=request.zip3,
        shop_type=request.shop_type,
        total=total,
        hourly_rate=rate,
        confidence=confidence,
        assumptions=assumptions,
    )


def compare_repair_costs(request: RepairCostComparisonRequest) -> RepairCostComparisonResult:
    estimates = [
        estimate_repair_cost(
            RepairCostRequest(
                label=request.label,
                zip3=request.zip3,
                shop_type=shop_type,
                diagnostic_fee=request.diagnostic_fee,
                parts=request.parts,
                labor_hours=request.labor_hours,
                hourly_rate=request.hourly_rates.get(shop_type),
                regional_multiplier=request.regional_multiplier,
                tax_rate=request.tax_rate,
                shop_supplies_rate=request.shop_supplies_rate,
            )
        )
        for shop_type in ShopType
    ]
    return RepairCostComparisonResult(
        label=request.label,
        zip3=request.zip3,
        estimates=estimates,
    )
