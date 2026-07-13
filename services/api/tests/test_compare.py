from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.engines.compare import compare_cases
from app.engines.risk import PPI_CRITICAL_KEYS
from app.models import (
    CaseContext,
    ComparisonRisk,
    Decision,
    Evidence,
    EvidenceKind,
    FindingStatus,
    InspectionItem,
    InspectionResult,
    InspectionSession,
    ListingSnapshot,
    LienStatus,
    MatchStatus,
    MoneyRange,
    RepairScenario,
    RiskArea,
    RiskFinding,
    SellerType,
    Severity,
    SourceEnvelope,
    TitleStatus,
    TransactionContext,
    TransportOption,
    VehicleSpec,
)
from app.ppi_trust import PPI_ARTIFACT_BINDING_BASIS


def _target_snapshot(
    listing_id: str, price: float, captured_at: datetime
) -> ListingSnapshot:
    return ListingSnapshot(
        id=listing_id,
        title=listing_id,
        asking_price=price,
        is_target=True,
        captured_at=captured_at,
        source_id=f"source-{listing_id}",
        evidence_id=f"evidence-{listing_id}",
        content_sha256="c" * 64,
    )


def test_empty_case_comparison_axes_are_explicitly_unknown() -> None:
    case = CaseContext(id="empty", decision=Decision.INSPECT)

    row = compare_cases([case]).ranked[0]

    assert row.mechanical_risk == ComparisonRisk.UNKNOWN
    assert row.title_risk == ComparisonRisk.UNKNOWN
    assert "mechanical risk UNKNOWN" in row.reason
    assert "title risk UNKNOWN" in row.reason


def test_compare_uses_latest_target_price_regardless_of_list_order() -> None:
    old = _target_snapshot(
        "target-old", 6000, datetime(2026, 7, 12, tzinfo=timezone.utc)
    )
    latest = _target_snapshot(
        "target-latest", 5500, datetime(2026, 7, 13, tzinfo=timezone.utc)
    )
    case = CaseContext(id="refreshed", listings=[latest, old])

    row = compare_cases([case]).ranked[0]

    assert row.asking_price == 5500
    assert len(case.listings) == 2
    assert all(item.is_target for item in case.listings)


def test_compare_api_serializes_empty_axes_as_unknown(client: TestClient) -> None:
    first = client.post("/v1/cases", json={}).json()["id"]
    second = client.post("/v1/cases", json={}).json()["id"]

    response = client.post("/v1/compare", json={"caseIds": [first, second]})

    assert response.status_code == 200, response.text
    assert all(
        row["mechanicalRisk"] == "UNKNOWN" and row["titleRisk"] == "UNKNOWN"
        for row in response.json()["ranked"]
    )


def test_unknown_axes_do_not_outrank_an_evidence_backed_case() -> None:
    unknown = CaseContext(
        id="unknown",
        decision=Decision.INSPECT,
        coverage_percent=90,
    )
    evidenced = CaseContext(
        id="evidenced",
        decision=Decision.INSPECT,
        coverage_percent=50,
        findings=[
            RiskFinding(
                code="MECHANICAL_OBSERVED",
                area=RiskArea.ENGINE,
                title="Observed engine finding",
                detail="Evidence-backed low-severity finding",
                severity=Severity.LOW,
            ),
            RiskFinding(
                code="TITLE_OBSERVED",
                area=RiskArea.TITLE,
                title="Observed title finding",
                detail="Evidence-backed low-severity finding",
                severity=Severity.LOW,
            ),
        ],
    )

    result = compare_cases([unknown, evidenced])

    assert [row.case_id for row in result.ranked] == ["evidenced", "unknown"]
    assert result.ranked[0].mechanical_risk == ComparisonRisk.LOW
    assert result.ranked[1].mechanical_risk == ComparisonRisk.UNKNOWN


def test_complete_ppi_and_verified_title_can_yield_info_not_unknown() -> None:
    ppi_source = SourceEnvelope(
        source_type="ppi",
        provider="user-upload",
        content_sha256="a" * 64,
    )
    ppi_evidence = Evidence(
        source_id=ppi_source.id,
        kind=EvidenceKind.PPI,
        label="Independent PPI",
        excerpt="Substantive independent inspection report text",
        page=1,
        metadata={
            "artifact_id": "ppi-artifact",
            "content_sha256": ppi_source.content_sha256,
            "ppi_artifact_binding_basis": PPI_ARTIFACT_BINDING_BASIS,
            "extracted_text_chars": 45,
        },
    )
    title_source = SourceEnvelope(source_type="title", content_sha256="b" * 64)
    title_evidence = Evidence(
        source_id=title_source.id,
        kind=EvidenceKind.TITLE,
        label="Original title verified",
        metadata={
            "artifact_id": "title-artifact",
            "content_sha256": title_source.content_sha256,
            "identity_title_match": MatchStatus.MATCH.value,
            "identity_comparison_basis": "server_exact_normalized",
        },
    )
    vehicle = VehicleSpec(
        vin="1TESTCAR000000001",
        year=2014,
        make="MINI",
        model="Cooper S",
        fuel_type="gasoline",
    )
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
    ppi = InspectionSession(
        inspection_type="ppi",
        inspector="Independent Shop",
        items=[
            InspectionItem(
                key=key,
                label=key,
                stage="ppi",
                result=InspectionResult.PASS,
                evidence_ids=[ppi_evidence.id],
            )
            for key in sorted(PPI_CRITICAL_KEYS)
        ],
        source_id=ppi_source.id,
        evidence_id=ppi_evidence.id,
    )
    case = CaseContext(
        id="verified",
        vehicle=vehicle,
        sources=[ppi_source, title_source],
        evidence=[ppi_evidence, title_evidence],
        inspections=[ppi],
        transaction_context=context.model_dump(mode="json", by_alias=False),
    )

    row = compare_cases([case]).ranked[0]

    assert row.mechanical_risk == ComparisonRisk.INFO
    assert row.title_risk == ComparisonRisk.INFO


def test_ppi_concern_is_not_hidden_when_case_has_not_been_reanalyzed() -> None:
    session = InspectionSession(
        inspection_type="ppi",
        inspector="Independent Shop",
        items=[
            InspectionItem(
                key="leaks",
                label="Coolant leak",
                stage="ppi",
                result=InspectionResult.CONCERN,
                severity_if_failed=Severity.HIGH,
            )
        ],
        source_id="ppi-source",
        evidence_id="ppi-evidence",
    )
    case = CaseContext(id="stale-analysis", inspections=[session])

    row = compare_cases([case]).ranked[0]

    assert row.mechanical_risk == ComparisonRisk.HIGH
    assert row.title_risk == ComparisonRisk.UNKNOWN


def test_stale_low_finding_cannot_mask_canonical_inspection_severity() -> None:
    session = InspectionSession(
        inspection_type="self",
        items=[
            InspectionItem(
                key="brakes",
                label="old client label",
                stage="pre_visit",
                result=InspectionResult.FAIL,
                severity_if_failed=Severity.LOW,
            )
        ],
        source_id="legacy-source",
        evidence_id="legacy-evidence",
    )
    stale_finding = RiskFinding(
        code="INSPECTION_BRAKES",
        area=RiskArea.BRAKES,
        title="old client label",
        detail="legacy cached analysis",
        severity=Severity.LOW,
    )
    case = CaseContext(
        id="legacy-cached-analysis",
        inspections=[session],
        findings=[stale_finding],
    )

    row = compare_cases([case]).ranked[0]

    assert row.mechanical_risk == ComparisonRisk.HIGH


def test_unresolved_repair_planning_exposure_excludes_non_active_findings() -> None:
    active = RiskFinding(
        code="ACTIVE_ENGINE_REPAIR",
        area=RiskArea.ENGINE,
        title="Active engine finding",
        detail="Still requires confirmation",
        severity=Severity.MEDIUM,
        status=FindingStatus.SUSPECTED,
        repair_scenarios=[
            RepairScenario(
                label="Active most-likely branch",
                system=RiskArea.ENGINE,
                probability_label="most_likely",
                cost=MoneyRange(low=100, likely=250, high=500),
                confirmation_tests=["Independent diagnosis"],
            )
        ],
    )
    resolved = RiskFinding(
        code="RESOLVED_TRANSMISSION_REPAIR",
        area=RiskArea.TRANSMISSION,
        title="Resolved transmission finding",
        detail="Repair is documented as complete",
        severity=Severity.HIGH,
        status=FindingStatus.RESOLVED,
        repair_scenarios=[
            RepairScenario(
                label="Historical most-likely branch",
                system=RiskArea.TRANSMISSION,
                probability_label="most_likely",
                cost=MoneyRange(low=2000, likely=4000, high=7000),
                confirmation_tests=["Review completed repair invoice"],
            )
        ],
    )
    confirmed = RiskFinding(
        code="CONFIRMED_BRAKE_REPAIR",
        area=RiskArea.BRAKES,
        title="Confirmed brake finding",
        detail="Repair is confirmed and still outstanding",
        severity=Severity.HIGH,
        status=FindingStatus.CONFIRMED,
        repair_scenarios=[
            RepairScenario(
                label="Confirmed most-likely branch",
                system=RiskArea.BRAKES,
                probability_label="most_likely",
                cost=MoneyRange(low=400, likely=500, high=600),
                confirmation_tests=["Review written repair estimate"],
            )
        ],
    )
    unknown = RiskFinding(
        code="UNKNOWN_REPAIR_STATE",
        area=RiskArea.ELECTRICAL,
        title="Unknown finding status",
        detail="The system has not established whether repair is needed",
        severity=Severity.HIGH,
        status=FindingStatus.UNKNOWN,
        repair_scenarios=[
            RepairScenario(
                label="Untrusted unknown branch",
                system=RiskArea.ELECTRICAL,
                probability_label="most_likely",
                cost=MoneyRange(low=3000, likely=5000, high=8000),
                confirmation_tests=["Establish whether a fault exists"],
            )
        ],
    )

    row = compare_cases(
        [
            CaseContext(
                id="active-and-resolved",
                findings=[active, resolved, confirmed, unknown],
            )
        ]
    ).ranked[0]
    resolved_only = compare_cases(
        [CaseContext(id="resolved-only", findings=[resolved])]
    ).ranked[0]

    assert row.unresolved_planning_exposure == MoneyRange(
        low=500, likely=750, high=1100
    )
    assert resolved_only.unresolved_planning_exposure is None
    serialized = row.model_dump(mode="json", by_alias=True)
    assert serialized["unresolvedPlanningExposure"] == {
        "low": 500.0,
        "likely": 750.0,
        "high": 1100.0,
        "currency": "USD",
    }
    assert "annualExposure" not in serialized


def test_canonical_identity_failure_is_ranked_on_title_axis() -> None:
    session = InspectionSession(
        inspection_type="self",
        items=[
            InspectionItem(
                key="vin_all_locations",
                label="nothing important",
                stage="interior",
                result=InspectionResult.FAIL,
                severity_if_failed=Severity.LOW,
            )
        ],
        source_id="legacy-source",
        evidence_id="legacy-evidence",
    )
    row = compare_cases([CaseContext(inspections=[session])]).ranked[0]

    assert row.title_risk == ComparisonRisk.CRITICAL
    assert row.mechanical_risk == ComparisonRisk.UNKNOWN
