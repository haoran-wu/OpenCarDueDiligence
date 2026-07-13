"""Deterministic comparable filtering and asking/sold price summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from math import exp

from ..listing_selection import latest_target_listing
from ..models import (
    CaseContext,
    Confidence,
    FuelType,
    ListingInput,
    ListingSnapshot,
    ReferenceKind,
    SellerType,
    ValuationResult,
)


def _norm(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _matches_vehicle(
    case: CaseContext, item: ListingInput, target: ListingSnapshot | None
) -> bool:
    vehicle = case.vehicle
    expected_make = vehicle.make or (target.make if target else None)
    expected_model = vehicle.model or (target.model if target else None)
    # A missing field is not a match.  v1 promises same-configuration
    # comparables, so unknown make/model/powertrain facts must be excluded rather
    # than silently treated as compatible.
    if expected_make and (not item.make or _norm(expected_make) != _norm(item.make)):
        return False
    if expected_model and (
        not item.model or _norm(expected_model) != _norm(item.model)
    ):
        return False
    for expected, actual in (
        (vehicle.trim or (target.trim if target else None), item.trim),
        (
            vehicle.generation or (target.generation if target else None),
            item.generation,
        ),
        (vehicle.platform or (target.platform if target else None), item.platform),
        (vehicle.engine or (target.engine if target else None), item.engine),
        (
            vehicle.transmission or (target.transmission if target else None),
            item.transmission,
        ),
        (
            vehicle.drivetrain or (target.drivetrain if target else None),
            item.drivetrain,
        ),
        (
            vehicle.body_style or (target.body_style if target else None),
            item.body_style,
        ),
    ):
        if expected and (not actual or _norm(expected) != _norm(actual)):
            return False
    expected_fuel = (
        vehicle.fuel_type
        if vehicle.fuel_type != FuelType.UNKNOWN
        else target.fuel_type
        if target
        else FuelType.UNKNOWN
    )
    if expected_fuel != FuelType.UNKNOWN and item.fuel_type != expected_fuel:
        return False
    expected_production_date = vehicle.production_date or (
        target.production_date if target else None
    )
    if expected_production_date and (
        item.production_date is None
        or (item.production_date.year, item.production_date.month)
        != (expected_production_date.year, expected_production_date.month)
    ):
        return False
    target_year = vehicle.year or (target.year if target else None)
    if target_year:
        if item.year is None or abs(target_year - item.year) > 2:
            return False
    target_mileage = (
        target.mileage
        if target is not None and target.mileage is not None
        else vehicle.odometer_miles
    )
    # The requested +/-30,000-mile comparable boundary cannot be evaluated
    # without a target odometer.  Missing target or comparable mileage is an
    # exclusion, never a zero-delta assumption.
    if target_mileage is None or item.mileage is None:
        return False
    if abs(target_mileage - item.mileage) > 30_000:
        return False
    return True


def _age_days(item: ListingInput, now: datetime) -> int | None:
    # captured_at proves when the user saved a snapshot, not when an asking or
    # sold price was on the market.  Unknown listing age cannot satisfy a
    # 180/365-day comparable window.
    timestamp = item.listed_at
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return max(0, (now - timestamp).days)


def _inside_market_window(
    item: ListingInput, *, now: datetime, radius: int, age_limit: int
) -> bool:
    age = _age_days(item, now)
    return bool(
        item.distance_miles is not None
        and item.distance_miles <= radius
        and age is not None
        and age <= age_limit
    )


def _weighted_median(values: list[tuple[float, float]]) -> float:
    ordered = sorted(values)
    total = sum(weight for _, weight in ordered)
    cursor = 0.0
    for value, weight in ordered:
        cursor += weight
        if cursor >= total / 2:
            return value
    return ordered[-1][0]


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    portion = position - lower
    return ordered[lower] * (1 - portion) + ordered[upper] * portion


def calculate_valuation(
    case: CaseContext,
    candidates: list[ListingInput | ListingSnapshot],
    *,
    now: datetime | None = None,
) -> ValuationResult | None:
    now = now or datetime.now(timezone.utc)
    target = latest_target_listing(case.listings, fallback_to_latest=True)
    target_seller_type = target.seller_type if target else SellerType.UNKNOWN

    # Vehicle identity is the admission boundary, not merely a display hint.
    # Without a resolved year/make/model/generation/platform/powertrain and
    # production date, unrelated cars can otherwise look like valid samples
    # because every unknown target field would be skipped by the matcher.
    if not case.vehicle.powertrain_resolved:
        return None

    # One result represents one seller-type/reference population.  If the
    # seller type is unknown, returning no valuation is safer than mixing
    # dealer and private-party prices into a misleading midpoint.
    if target is None or target_seller_type == SellerType.UNKNOWN:
        return None

    target_mileage = (
        target.mileage
        if target.mileage is not None
        else case.vehicle.odometer_miles
    )
    if target_mileage is None:
        return None

    eligible = [
        item
        for item in candidates
        if not item.is_target and _matches_vehicle(case, item, target)
    ]
    eligible = [
        item
        for item in eligible
        if item.seller_type == target_seller_type
        and item.reference_kind == target.reference_kind
    ]

    radius, age_limit = 150, 180
    filtered = [
        item
        for item in eligible
        if _inside_market_window(
            item, now=now, radius=radius, age_limit=age_limit
        )
    ]
    if len(filtered) < 8:
        radius, age_limit = 300, 365
        filtered = [
            item
            for item in eligible
            if _inside_market_window(
                item, now=now, radius=radius, age_limit=age_limit
            )
        ]
    if not filtered:
        return None

    weighted: list[tuple[float, float]] = []
    for item in filtered:
        distance = item.distance_miles or 0
        age = _age_days(item, now)
        assert age is not None  # guaranteed by _inside_market_window
        assert item.mileage is not None  # guaranteed by _matches_vehicle
        mileage_delta = abs(item.mileage - target_mileage)
        # Smooth non-zero weights; closer, newer, mileage-similar listings carry more weight.
        weight = max(
            0.05, exp(-distance / 250) * exp(-age / 365) * exp(-mileage_delta / 50_000)
        )
        weighted.append((float(item.asking_price), weight))
    prices = [price for price, _ in weighted]
    if target.reference_kind == ReferenceKind.ASKING:
        kind = "asking_price_range"
    elif target.reference_kind == ReferenceKind.SOLD:
        kind = "sold_price_range"
    else:
        kind = "reference_value_range"

    sample_count = len(filtered)
    if sample_count >= 8:
        confidence = Confidence.HIGH
    elif sample_count >= 5:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    return ValuationResult(
        reference_kind=kind,
        channel=target_seller_type,
        weighted_median=_weighted_median(weighted) if sample_count >= 5 else None,
        q25=round(_quantile(prices, 0.25), 2),
        q75=round(_quantile(prices, 0.75), 2),
        sample_count=sample_count,
        radius_miles=radius,
        max_age_days=age_limit,
        confidence=confidence,
        low_sample_warning=sample_count < 5,
        comparable_listing_ids=[
            getattr(item, "id", "") for item in filtered if getattr(item, "id", None)
        ],
        excluded_count=max(0, len(candidates) - len(filtered)),
    )
