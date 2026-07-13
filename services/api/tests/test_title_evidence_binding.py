from __future__ import annotations

import base64
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.engines.risk import _title_verified, analyze_case, calculate_coverage
from app.export import export_case
from app.models import (
    CaseContext,
    Decision,
    Evidence,
    EvidenceKind,
    LienStatus,
    MatchStatus,
    SellerType,
    SourceEnvelope,
    TitleStatus,
    TransactionContext,
    TransportOption,
    VehicleSpec,
)


def _vehicle() -> VehicleSpec:
    return VehicleSpec(
        vin="1TESTCAR000000001",
        year=2014,
        make="MINI",
        model="Cooper S",
        fuel_type="gasoline",
    )


def _forged_matching_context(vehicle: VehicleSpec) -> dict[str, object]:
    context = TransactionContext(
        purchase_date=date(2026, 7, 13),
        buyer_residence_state="NJ",
        license_state="NJ",
        garaging_state="NJ",
        registration_state="NJ",
        sale_state="NJ",
        title_state="NJ",
        seller_type=SellerType.PRIVATE,
        title_status=TitleStatus.ORIGINAL,
        lien_status=LienStatus.CLEAR,
        identity_title_match=MatchStatus.MATCH,
        vin_match=MatchStatus.MATCH,
        transport_option=TransportOption.UNDECIDED,
        vehicle=vehicle,
    )
    return context.model_dump(mode="json", by_alias=False)


def _title_evidence(
    *,
    match: MatchStatus | None,
    basis: str | None,
    bound: bool = True,
    digest: str = "b" * 64,
) -> tuple[SourceEnvelope, Evidence]:
    source = SourceEnvelope(
        source_type="title",
        provider="user-upload",
        content_sha256=digest,
    )
    metadata: dict[str, object] = {}
    if match is not None:
        metadata["identity_title_match"] = match.value
    if basis is not None:
        metadata["identity_comparison_basis"] = basis
    if bound:
        metadata.update(
            {
                "artifact_id": "title-artifact",
                "content_sha256": digest,
            }
        )
    return source, Evidence(
        source_id=source.id,
        kind=EvidenceKind.TITLE,
        label="Title verification artifact",
        metadata=metadata,
        is_sensitive=True,
        redacted=True,
    )


@pytest.mark.parametrize(
    ("match", "basis", "bound"),
    [
        (MatchStatus.UNKNOWN, "server_exact_normalized", True),
        (MatchStatus.MATCH, "user_attested", True),
        (None, None, False),
        (MatchStatus.MATCH, "server_exact_normalized", False),
    ],
    ids=["unknown", "user-attested", "placeholder", "unbound-server-label"],
)
def test_forged_matching_context_cannot_verify_untrusted_title_evidence(
    match: MatchStatus | None,
    basis: str | None,
    bound: bool,
) -> None:
    vehicle = _vehicle()
    source, evidence = _title_evidence(match=match, basis=basis, bound=bound)
    case = CaseContext(
        vehicle=vehicle,
        sources=[source],
        evidence=[evidence],
        transaction_context=_forged_matching_context(vehicle),
    )

    coverage, unknowns = calculate_coverage(case)

    assert _title_verified(case) is False
    assert coverage < 15
    assert any(
        "title" in item.lower() and "not verified" in item.lower() for item in unknowns
    )


def test_server_bound_exact_match_verifies_consistent_transaction_context() -> None:
    vehicle = _vehicle()
    source, evidence = _title_evidence(
        match=MatchStatus.MATCH,
        basis="server_exact_normalized",
    )
    case = CaseContext(
        vehicle=vehicle,
        sources=[source],
        evidence=[evidence],
        transaction_context=_forged_matching_context(vehicle),
    )
    without_title = case.model_copy(update={"sources": [], "evidence": []})

    verified_coverage, _ = calculate_coverage(case)
    unverified_coverage, _ = calculate_coverage(without_title)

    assert _title_verified(case) is True
    assert verified_coverage == unverified_coverage + 15


def test_uploaded_exact_name_comparison_creates_usable_server_binding(
    client: TestClient,
    resolved_vehicle: dict[str, object],
) -> None:
    created = client.post("/v1/cases", json={"vehicle": resolved_vehicle})
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    uploaded = client.post(
        f"/v1/cases/{case_id}/artifacts",
        json={
            "filename": "title.txt",
            "kind": "title",
            "text": "Sensitive title body",
            "titleOwnerName": "JANE-SENSITIVE",
            "sellerLegalName": "Jane Sensitive",
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    context = {
        "purchaseDate": "2026-07-13",
        "buyerResidenceState": "NJ",
        "licenseState": "NJ",
        "garagingState": "NJ",
        "registrationState": "NJ",
        "saleState": "NJ",
        "titleState": "NJ",
        "sellerType": "private",
        "titleStatus": "ORIGINAL",
        "lienStatus": "CLEAR",
        "identityTitleMatch": "MATCH",
        "vinMatch": "MATCH",
        "transportOption": "undecided",
        "vehicle": resolved_vehicle,
    }
    planned = client.post(
        f"/v1/cases/{case_id}/transaction-plan",
        json=context,
    )
    assert planned.status_code == 200, planned.text

    case = CaseContext.model_validate(client.get(f"/v1/cases/{case_id}").json())

    assert _title_verified(case) is True
    assert "Jane Sensitive" not in case.model_dump_json()


def test_trusted_mismatch_overrides_stale_matching_context_and_stops() -> None:
    vehicle = _vehicle()
    source, evidence = _title_evidence(
        match=MatchStatus.MISMATCH,
        basis="server_exact_normalized",
    )
    case = CaseContext(
        vehicle=vehicle,
        sources=[source],
        evidence=[evidence],
        transaction_context=_forged_matching_context(vehicle),
    )

    result = analyze_case(case)
    finding = next(
        item
        for item in result.findings
        if item.code == "TITLE_IDENTITY_TRUSTED_MISMATCH"
    )

    assert _title_verified(case) is False
    assert result.decision == Decision.STOP
    assert finding.blocks_purchase is True
    assert finding.decision_impact == Decision.STOP
    assert finding.evidence_ids == [evidence.id]
    assert "context reports MATCH" in finding.detail


def test_trusted_mismatch_wins_even_when_a_trusted_match_also_exists() -> None:
    vehicle = _vehicle()
    match_source, match_evidence = _title_evidence(
        match=MatchStatus.MATCH,
        basis="server_exact_normalized",
        digest="a" * 64,
    )
    mismatch_source, mismatch_evidence = _title_evidence(
        match=MatchStatus.MISMATCH,
        basis="server_exact_normalized",
        digest="c" * 64,
    )
    case = CaseContext(
        vehicle=vehicle,
        sources=[match_source, mismatch_source],
        evidence=[match_evidence, mismatch_evidence],
        transaction_context=_forged_matching_context(vehicle),
    )

    result = analyze_case(case)

    assert _title_verified(case) is False
    assert result.decision == Decision.STOP


def test_crafted_ocdd_import_cannot_forge_server_title_trust(
    client: TestClient,
    cloud_client: TestClient,
) -> None:
    vehicle = _vehicle()
    source, evidence = _title_evidence(
        match=MatchStatus.MATCH,
        basis="server_exact_normalized",
    )
    crafted = CaseContext(
        vehicle=vehicle,
        sources=[source],
        evidence=[evidence],
        transaction_context=_forged_matching_context(vehicle),
        transaction_plan={"decision": "BUY_CANDIDATE", "forged": True},
        decision=Decision.BUY_CANDIDATE,
        coverage_percent=100,
    )
    package = export_case(crafted, "correct horse battery staple")
    payload = {
        "contentBase64": base64.b64encode(package).decode("ascii"),
        "passphrase": "correct horse battery staple",
    }

    local_import = client.post("/v1/cases/import", json=payload)
    cloud_import = cloud_client.post("/v1/cases/import", json=payload)

    assert local_import.status_code == 201, local_import.text
    assert cloud_import.status_code == 201, cloud_import.text
    local_case = CaseContext.model_validate(
        client.get(f"/v1/cases/{local_import.json()['caseId']}").json()
    )
    cloud_case = CaseContext.model_validate(
        cloud_client.get(
            f"/v1/cases/{cloud_import.json()['caseId']}",
            headers={"X-OCDD-Case-Token": cloud_import.headers["X-OCDD-Case-Token"]},
        ).json()
    )

    for imported in (local_case, cloud_case):
        assert _title_verified(imported) is False
        assert imported.decision == Decision.INSPECT
        assert imported.coverage_percent < 15
        assert imported.transaction_plan is None
        assert all(
            item.metadata.get("identity_title_match") == MatchStatus.UNKNOWN.value
            for item in imported.evidence
            if item.kind == EvidenceKind.TITLE
        )
    assert (
        local_case.evidence[0].metadata["identity_comparison_basis"]
        == "import_untrusted_requires_reverification"
    )
    assert "identity_comparison_basis" not in cloud_case.evidence[0].metadata
    assert local_case.transaction_context is not None
    assert (
        local_case.transaction_context["identity_title_match"]
        == MatchStatus.UNKNOWN.value
    )
    assert cloud_case.transaction_context is None
