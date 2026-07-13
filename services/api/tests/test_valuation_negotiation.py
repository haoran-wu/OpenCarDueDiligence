from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.engines.negotiation import draft_negotiation
from app.engines.valuation import calculate_valuation
from app.models import (
    CaseContext,
    Language,
    ListingInput,
    ListingSnapshot,
    NegotiationAdjustment,
    NegotiationPhase,
    NegotiationRequest,
    SellerType,
    VehicleSpec,
)


def _case() -> CaseContext:
    target_input = ListingInput(
        title="Target",
        asking_price=6000,
        mileage=120000,
        seller_type=SellerType.PRIVATE,
        year=2014,
        make="MINI",
        model="Cooper S",
        trim="S",
        generation="F56",
        platform="F56",
        engine="B48",
        transmission="auto",
        drivetrain="FWD",
        production_date=date(2014, 8, 15),
        fuel_type="gasoline",
        body_style="hatchback",
        is_target=True,
    )
    target = ListingSnapshot(
        **target_input.model_dump(),
        source_id="s",
        evidence_id="e",
        content_sha256="a" * 64,
    )
    return CaseContext(
        vehicle=VehicleSpec(
            year=2014,
            make="MINI",
            model="Cooper S",
            trim="S",
            generation="F56",
            platform="F56",
            engine="B48",
            transmission="auto",
            drivetrain="FWD",
            production_date=date(2014, 8, 2),
            fuel_type="gasoline",
            body_style="hatchback",
            odometer_miles=120000,
        ),
        listings=[target],
    )


def _comparable(
    price: float, index: int, seller: SellerType = SellerType.PRIVATE
) -> ListingInput:
    return ListingInput(
        title=f"Comparable {index}",
        asking_price=price,
        mileage=115000 + index * 1000,
        seller_type=seller,
        year=2014,
        make="MINI",
        model="Cooper S",
        trim="S",
        generation="F56",
        platform="F56",
        engine="B48",
        transmission="auto",
        drivetrain="FWD",
        production_date=date(2014, 8, 20),
        fuel_type="gasoline",
        body_style="hatchback",
        distance_miles=20 + index,
        listed_at=datetime.now(timezone.utc) - timedelta(days=10 + index),
    )


def test_valuation_low_sample_has_no_fake_point_estimate() -> None:
    result = calculate_valuation(
        _case(), [_comparable(5000 + index * 100, index) for index in range(4)]
    )
    assert result is not None
    assert result.sample_count == 4
    assert result.weighted_median is None
    assert result.low_sample_warning is True
    assert result.reference_kind == "asking_price_range"


def test_valuation_separates_private_and_dealer_and_expands_confidence() -> None:
    comparables = [_comparable(5200 + i * 100, i) for i in range(8)]
    comparables += [_comparable(9000, 20, SellerType.DEALER)]
    result = calculate_valuation(_case(), comparables)
    assert result is not None
    assert result.sample_count == 8
    assert result.confidence == "HIGH"
    assert result.weighted_median is not None and result.weighted_median < 6000


def test_valuation_excludes_comparables_with_unknown_required_configuration() -> None:
    complete = [_comparable(5200 + i * 100, i) for i in range(5)]
    missing_engine = _comparable(999, 90).model_copy(update={"engine": None})
    missing_mileage = _comparable(999, 91).model_copy(update={"mileage": None})
    missing_distance = _comparable(999, 92).model_copy(update={"distance_miles": None})
    missing_listed_date = _comparable(999, 93).model_copy(update={"listed_at": None})

    result = calculate_valuation(
        _case(),
        complete
        + [missing_engine, missing_mileage, missing_distance, missing_listed_date],
    )

    assert result is not None
    assert result.sample_count == 5
    assert result.q25 > 999
    assert result.excluded_count == 4


def test_valuation_fails_closed_without_target_mileage() -> None:
    case = _case()
    case.vehicle.odometer_miles = None
    case.listings[0] = case.listings[0].model_copy(update={"mileage": None})

    assert calculate_valuation(
        case, [_comparable(5200 + index * 100, index) for index in range(5)]
    ) is None


def test_valuation_fails_closed_when_target_vehicle_identity_is_unresolved() -> None:
    case = _case()
    case.vehicle = VehicleSpec()
    case.listings[0] = case.listings[0].model_copy(
        update={
            "year": None,
            "make": None,
            "model": None,
            "trim": None,
            "generation": None,
            "platform": None,
            "engine": None,
            "transmission": None,
            "drivetrain": None,
            "production_date": None,
            "fuel_type": "unknown",
            "body_style": None,
        }
    )
    unrelated = [
        _comparable(3500, 1).model_copy(update={"make": "Honda", "model": "Civic"}),
        _comparable(4500, 2).model_copy(update={"make": "Toyota", "model": "Corolla"}),
    ]

    assert calculate_valuation(case, unrelated) is None


def test_valuation_separates_reference_population_and_exact_configuration() -> None:
    complete = [_comparable(5200 + i * 100, i) for i in range(5)]
    incompatible = [
        _comparable(999, 70).model_copy(update={"trim": "JCW"}),
        _comparable(999, 71).model_copy(update={"platform": "R56"}),
        _comparable(999, 72).model_copy(update={"fuel_type": "electric"}),
        _comparable(999, 73).model_copy(update={"production_date": date(2014, 9, 1)}),
        _comparable(999, 74).model_copy(update={"reference_kind": "sold"}),
    ]

    result = calculate_valuation(_case(), complete + incompatible)

    assert result is not None
    assert result.sample_count == 5
    assert result.reference_kind == "asking_price_range"
    assert result.excluded_count == len(incompatible)
    assert result.q25 > 999


def test_valuation_uses_latest_target_mileage_not_stale_vehicle_odometer() -> None:
    case = _case()
    old = case.listings[0].model_copy(
        update={
            "id": "target-old",
            "captured_at": datetime(2026, 7, 12, tzinfo=timezone.utc),
            "mileage": 120000,
        }
    )
    latest = case.listings[0].model_copy(
        update={
            "id": "target-latest",
            "captured_at": datetime(2026, 7, 13, tzinfo=timezone.utc),
            "mileage": 195000,
        }
    )
    case.listings = [latest, old]
    comparables = [
        _comparable(5200 + index * 100, index).model_copy(
            update={"mileage": 195000 + index * 500}
        )
        for index in range(5)
    ]

    result = calculate_valuation(case, comparables)

    assert result is not None
    assert result.sample_count == 5
    assert result.weighted_median is not None


def test_negotiation_is_traceable_and_does_not_double_count_normal_wear() -> None:
    request = NegotiationRequest(
        phase=NegotiationPhase.POST_PPI,
        language=Language.EN,
        asking_price=6000,
        market_baseline=6500,
        all_in_budget=7000,
        evidence_coverage=80,
        buyer_mandatory_costs=500,
        adjustments=[
            NegotiationAdjustment(
                label="Confirmed coolant leak",
                category="immediate_repair",
                amount=800,
                evidence_ids=["ppi-1"],
            ),
            NegotiationAdjustment(
                label="Age-normal brake wear",
                category="immediate_repair",
                amount=500,
                normal_wear=True,
                evidence_ids=["ppi-2"],
            ),
        ],
    )
    result = draft_negotiation(request)
    # target = 6500 - 800 - 5% reserve(325), then a 325 opening discount
    assert result.target == 5375
    assert result.opening == 5050
    assert result.ceiling == 5505
    ignored = next(
        item for item in result.trace if item.label == "Age-normal brake wear"
    )
    assert ignored.applied is False
    assert "conditional" in result.message


def test_initial_contact_needs_no_valuation_or_budget_arithmetic() -> None:
    result = draft_negotiation(
        NegotiationRequest(
            phase=NegotiationPhase.INITIAL_CONTACT,
            language=Language.EN,
        )
    )

    assert result.decision == "INSPECT_FIRST"
    assert result.target is None
    assert result.opening is None
    assert result.ceiling is None
    assert result.evidence_reserve == 0
    assert "VIN" in result.message
    assert "title" in result.message
    assert "maintenance" in result.message
    assert "warning lights" in result.message
    assert "pre-purchase inspection" in result.message
    assert len(result.trace) == 1
    assert "No valuation" in result.trace[0].reason


def test_low_coverage_refuses_to_invent_ceiling() -> None:
    result = draft_negotiation(
        NegotiationRequest(
            phase="conditional_offer",
            language="zh-CN",
            asking_price=6000,
            market_baseline=6500,
            all_in_budget=7000,
            evidence_coverage=39,
        )
    )
    assert result.decision == "INSPECT_FIRST"
    assert result.opening is None
    assert result.ceiling is None
    assert "检查" in result.message


def test_budget_below_opening_walks_away_without_impossible_offer() -> None:
    result = draft_negotiation(
        NegotiationRequest(
            phase="conditional_offer",
            language="en",
            asking_price=8_000,
            market_baseline=8_000,
            all_in_budget=3_000,
            buyer_mandatory_costs=500,
            evidence_coverage=90,
        )
    )

    assert result.target == 7_840
    assert result.ceiling == 2_500
    assert result.opening is None
    assert result.decision == "WALK_AWAY"
    assert "$7,440" not in result.message
    assert "$2,500" in result.message
    assert any(
        item.label == "Buyer affordability ceiling" and not item.applied
        for item in result.trace
    )
