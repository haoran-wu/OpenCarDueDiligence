from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from app.engines.transaction import build_transaction_plan
from app.models import (
    Decision,
    InspectionResult,
    LienStatus,
    MatchStatus,
    SellerType,
    TitleStatus,
    TransactionContext,
    TransportOption,
    VehicleSpec,
)


DATA_ROOT = Path(__file__).resolve().parents[3] / "data"


def _nj_buyer_ny_title(**overrides: object) -> TransactionContext:
    values: dict[str, object] = {
        "purchase_date": date(2026, 7, 12),
        "buyer_residence_state": "NJ",
        "license_state": "NJ",
        "garaging_state": "NJ",
        "registration_state": "NJ",
        "sale_state": "NY",
        "title_state": "NY",
        "seller_type": SellerType.PRIVATE,
        "title_status": TitleStatus.ORIGINAL,
        "lien_status": LienStatus.CLEAR,
        "identity_title_match": MatchStatus.MATCH,
        "vin_match": MatchStatus.MATCH,
        "seller_allows_ppi": True,
        "seller_allows_bill_of_sale": True,
        "seller_will_disclose_odometer": True,
        "insurance_active_for_vin": True,
        "transport_option": TransportOption.VALID_TEMP_PERMIT,
        "vehicle": VehicleSpec(
            vin="1TESTCAR000000001",
            year=2014,
            make="MINI",
            model="Cooper S",
            generation="F56",
            platform="F56",
            engine="B48 2.0T",
            transmission="Aisin 6-speed automatic",
            drivetrain="FWD",
            odometer_miles=120_010,
        ),
        "current_inspection_status": InspectionResult.PASS,
        "current_emissions_status": InspectionResult.PASS,
    }
    values.update(overrides)
    return TransactionContext.model_validate(values)


def test_nj_buyer_with_ny_title_gets_origin_transport_and_nj_registration(monkeypatch) -> None:
    monkeypatch.setenv("OCDD_RULES_AS_OF", "2026-07-12")
    plan = build_transaction_plan(_nj_buyer_ny_title())

    assert plan.decision == Decision.INSPECT
    assert plan.can_legally_drive_away is False
    assert plan.rules_verified_as_of == date(2026, 7, 12)
    assert not [gate for gate in plan.gates if gate.blocked]

    combined = " ".join(f"{step.title} {step.detail}" for step in plan.steps)
    assert "in-transit" in combined
    assert "OS/SS-UTA" in combined
    assert "6.625%" in combined
    official_hosts = {
        urlsplit(step.official_url).hostname
        for step in plan.steps
        if step.official_url
    }
    assert official_hosts == {"dmv.ny.gov", "www.nj.gov"}
    lookalike_host = urlsplit("https://www.nj.gov.attacker.example/mvc").hostname
    assert lookalike_host != "www.nj.gov"
    assert any("await maintainer human signoff" in warning for warning in plan.warnings)
    assert all(step.requires_confirmation for step in plan.steps if step.verified_as_of)
    assert [step.order for step in plan.steps] == sorted(step.order for step in plan.steps)


def test_insurance_and_bill_of_sale_do_not_make_seller_plate_legal(monkeypatch) -> None:
    monkeypatch.setenv("OCDD_RULES_AS_OF", "2026-07-12")
    context = _nj_buyer_ny_title(transport_option=TransportOption.SELLER_PLATE)

    plan = build_transaction_plan(context)

    assert plan.decision == Decision.STOP
    assert plan.can_legally_drive_away is False
    transport_gate = next(gate for gate in plan.gates if gate.code == "legal_transport")
    assert transport_gate.blocked is True
    assert "seller" in transport_gate.reason.lower()


def test_title_owner_identity_mismatch_is_hard_stop(monkeypatch) -> None:
    monkeypatch.setenv("OCDD_RULES_AS_OF", "2026-07-12")
    context = _nj_buyer_ny_title(identity_title_match=MatchStatus.MISMATCH)

    plan = build_transaction_plan(context)

    assert plan.decision == Decision.STOP
    assert plan.can_legally_drive_away is False
    gate = next(gate for gate in plan.gates if gate.code == "seller_title_identity")
    assert gate.blocked is True
    assert "does not match" in gate.reason


def test_stale_rules_downgrade_to_confirmation_required(monkeypatch) -> None:
    monkeypatch.setenv("OCDD_RULES_AS_OF", "2027-01-01")

    plan = build_transaction_plan(_nj_buyer_ny_title())

    assert plan.decision == Decision.INSPECT
    assert plan.can_legally_drive_away is False
    assert any("older than 90 days" in warning for warning in plan.warnings)
    assert any(step.requires_confirmation for step in plan.steps)
    assert all(step.requires_confirmation for step in plan.steps if step.verified_as_of)


def test_mapping_input_uses_same_pydantic_contract(monkeypatch) -> None:
    monkeypatch.setenv("OCDD_RULES_AS_OF", "2026-07-12")
    camel_case_payload = _nj_buyer_ny_title().model_dump(by_alias=True, mode="json")

    plan = build_transaction_plan(camel_case_payload)

    assert plan.decision == Decision.INSPECT
    assert plan.model_dump(by_alias=True)["canLegallyDriveAway"] is False


def test_unknown_title_never_becomes_buy_candidate(monkeypatch) -> None:
    monkeypatch.setenv("OCDD_RULES_AS_OF", "2026-07-12")

    plan = build_transaction_plan(_nj_buyer_ny_title(title_status=TitleStatus.UNKNOWN))

    assert plan.decision == Decision.INSPECT
    assert plan.can_legally_drive_away is False
    assert next(gate for gate in plan.gates if gate.code == "title_document").blocked


def test_rule_and_safety_data_contracts_are_complete() -> None:
    for state in ("NJ", "NY", "CT"):
        path = next((DATA_ROOT / "rules" / "states").glob(f"{state}-*.yaml"))
        bundle = json.loads(path.read_text(encoding="utf-8"))
        assert bundle["jurisdiction"] == state
        assert bundle["rules_effective_as_of"]
        assert bundle["verified_at"]
        assert bundle["provenance"]["human_reviewed"] is False
        assert bundle["provenance"]["review_status"].endswith("HUMAN_SIGNOFF_PENDING")
        assert bundle["refresh_after_days"] == 90
        assert bundle["forms"] and bundle["fees"] and bundle["seller_tasks"] and bundle["buyer_tasks"]
        assert all(source["url"].startswith("https://") for source in bundle["sources"])
        assert all(source["verified_at"] for source in bundle["sources"])

    checklist = json.loads((DATA_ROOT / "checklists" / "five_stage_inspection_v1.yaml").read_text(encoding="utf-8"))
    assert checklist["default_result"] == "UNKNOWN"
    assert [stage["order"] for stage in checklist["stages"]] == [1, 2, 3, 4, 5]
    assert all(stage["items"] for stage in checklist["stages"])

    manifests = json.loads((DATA_ROOT / "knowledge" / "model_family_manifests_v1.yaml").read_text(encoding="utf-8"))
    assert len(manifests["families"]) == 20
    assert len({family["id"] for family in manifests["families"]}) == 20
    assert all(family["publication_status"] == "DRAFT" for family in manifests["families"])
    assert all(len(family["applicability_packs"]) == 1 for family in manifests["families"])
    assert all(
        pack["publication_status"] == "DRAFT"
        and pack["reviewer"] is None
        and pack["reviewed_at"] is None
        for family in manifests["families"]
        for pack in family["applicability_packs"]
    )


def test_generic_dtc_trees_never_turn_code_into_component_verdict() -> None:
    payload = json.loads((DATA_ROOT / "diagnostics" / "generic_dtc_trees_v1.yaml").read_text(encoding="utf-8"))
    trees = {tree["id"]: tree for tree in payload["trees"]}

    assert set(trees) == {"P0301", "P0420", "P0171", "P0299", "P07xx"}
    assert all(tree["direct_replacement_forbidden"] for tree in trees.values())
    assert all(len(tree["scenarios"]) == 3 for tree in trees.values())
    assert "compression/leak-down or relative-compression test when indicated" in trees["P0301"]["confirmation_tests"]
    assert "check companion and pending codes first" in trees["P0420"]["confirmation_tests"]
