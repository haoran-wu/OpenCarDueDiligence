from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.engines.compare import compare_cases
from app.engines.risk import PPI_CRITICAL_KEYS, _inspection_completion, analyze_case
from app.export import export_case
from app.inspection_catalog import required_inspection_keys
from app.models import (
    CaseContext,
    CaseStatus,
    ComparisonRisk,
    Decision,
    Evidence,
    EvidenceKind,
    InspectionItem,
    InspectionResult,
    InspectionSession,
    Severity,
    SourceEnvelope,
    VehicleSpec,
)
from app.ppi_trust import (
    PPI_ARTIFACT_BINDING_BASIS,
    trusted_ppi_artifact_evidence_ids,
)


def _create_case(client: TestClient, vehicle: dict[str, object]) -> str:
    response = client.post("/v1/cases", json={"vehicle": vehicle})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _trusted_ppi_artifact() -> tuple[SourceEnvelope, Evidence]:
    source = SourceEnvelope(
        source_type="ppi",
        provider="user-upload",
        content_sha256="d" * 64,
    )
    evidence = Evidence(
        source_id=source.id,
        kind=EvidenceKind.PPI,
        label="Uploaded independent PPI report",
        excerpt="Substantive independent inspection report text",
        page=1,
        metadata={
            "artifact_id": "ppi-artifact",
            "content_sha256": source.content_sha256,
            "ppi_artifact_binding_basis": PPI_ARTIFACT_BINDING_BASIS,
            "extracted_text_chars": 45,
        },
    )
    return source, evidence


def _advance_to_self_inspected(client: TestClient, case_id: str) -> None:
    listing = client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={"listings": [{"title": "Target", "askingPrice": 5000, "isTarget": True}]},
    )
    assert listing.status_code == 201, listing.text
    for status in ("REMOTE_SCREENED", "VIEW_SCHEDULED"):
        response = client.patch(
            f"/v1/cases/{case_id}/status",
            json={"status": status, "reason": "Test lifecycle setup"},
        )
        assert response.status_code == 200, response.text
    inspected = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={
            "inspectionType": "self",
            "items": [
                {
                    "key": "vin_received",
                    "label": "VIN received",
                    "stage": "pre_visit",
                    "result": "PASS",
                }
            ],
        },
    )
    assert inspected.status_code == 201, inspected.text
    assert client.get(f"/v1/cases/{case_id}").json()["status"] == "SELF_INSPECTED"


def test_client_cannot_downgrade_canonical_brake_rust_or_warning_lamp_failures(
    client: TestClient,
    resolved_vehicle: dict[str, object],
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    response = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={
            "inspectionType": "self",
            "items": [
                {
                    "key": "brakes",
                    "label": "cosmetic only",
                    "stage": "pre_visit",
                    "result": "FAIL",
                    "severityIfFailed": "LOW",
                },
                {
                    "key": "rust",
                    "label": "tiny spot",
                    "stage": "interior",
                    "result": "FAIL",
                    "severityIfFailed": "MEDIUM",
                },
                {
                    "key": "warning_lamp_self_test",
                    "label": "ignore this",
                    "stage": "exterior",
                    "result": "FAIL",
                    "severityIfFailed": "LOW",
                },
            ],
        },
    )

    assert response.status_code == 201, response.text
    by_key = {item["key"]: item for item in response.json()["items"]}
    assert by_key["brakes"]["stage"] == "road_test"
    assert by_key["rust"]["stage"] == "exterior"
    assert by_key["warning_lamp_self_test"]["stage"] == "interior"
    assert {item["severityIfFailed"] for item in by_key.values()} == {"HIGH"}
    assert by_key["brakes"]["label"].startswith("Test straight")
    assert by_key["rust"]["label"].startswith("Inspect subframes")

    analysis = client.post(f"/v1/cases/{case_id}/analyze", json={})
    assert analysis.status_code == 200, analysis.text
    findings = {
        item["code"]: item
        for item in analysis.json()["findings"]
        if item["code"].startswith("INSPECTION_")
    }
    for code in (
        "INSPECTION_BRAKES",
        "INSPECTION_RUST",
        "INSPECTION_WARNING_LAMP_SELF_TEST",
    ):
        assert findings[code]["severity"] == "HIGH"
        assert findings[code]["decisionImpact"] == "INSPECT"
    assert analysis.json()["decision"] == "INSPECT"


def test_unknown_custom_key_never_increases_inspection_coverage() -> None:
    vehicle = VehicleSpec(transmission="6-speed automatic", fuel_type="gasoline")
    custom = InspectionSession(
        inspection_type="self",
        items=[
            InspectionItem(
                key="totally_custom_pass",
                label="Everything is perfect",
                stage="road_test",
                result=InspectionResult.PASS,
                severity_if_failed=Severity.LOW,
            )
        ],
        source_id="custom-source",
        evidence_id="custom-evidence",
    )
    case = CaseContext(vehicle=vehicle, inspections=[custom])

    completion, completed = _inspection_completion(case, inspection_type="self")

    assert completion == 0
    assert completed == set()


def test_unknown_powertrain_applicability_remains_required_for_coverage() -> None:
    vehicle = VehicleSpec()
    source, evidence = _trusted_ppi_artifact()
    ppi = InspectionSession(
        inspection_type="ppi",
        inspector="Independent shop",
        items=[
            InspectionItem(
                key=key,
                label="client label",
                stage="ppi",
                result=InspectionResult.PASS,
                evidence_ids=[evidence.id],
            )
            for key in sorted(PPI_CRITICAL_KEYS)
        ],
        source_id=source.id,
        evidence_id=evidence.id,
    )
    case = CaseContext(
        vehicle=vehicle,
        sources=[source],
        evidence=[evidence],
        inspections=[ppi],
    )

    completion, completed = _inspection_completion(case, inspection_type="ppi")

    assert completion < 1
    assert completed == set(PPI_CRITICAL_KEYS)
    assert "hybrid_ev_battery" not in completed

    ppi.items.append(
        InspectionItem(
            key="hybrid_ev_battery",
            label="client label",
            stage="ppi",
            result=InspectionResult.PASS,
            evidence_ids=[evidence.id],
        )
    )
    completion, completed = _inspection_completion(case, inspection_type="ppi")
    assert completion == 1
    assert "hybrid_ev_battery" in completed


def test_unknown_transmission_keeps_manual_check_unknown_in_coverage() -> None:
    unknown_keys = required_inspection_keys(VehicleSpec(), "self")
    automatic_keys = required_inspection_keys(
        VehicleSpec(transmission="6-speed automatic"),
        "self",
    )

    assert "clutch" in unknown_keys
    assert "clutch" not in automatic_keys


def test_unknown_custom_failure_is_recomputed_high_and_requires_inspection() -> None:
    session = InspectionSession(
        inspection_type="ppi",
        inspector="Legacy shop",
        items=[
            InspectionItem(
                key="legacy_custom_failure",
                label="harmless",
                stage="ppi",
                result=InspectionResult.FAIL,
                severity_if_failed=Severity.LOW,
            )
        ],
        source_id="legacy-source",
        evidence_id="",
    )
    case = CaseContext(inspections=[session])

    result = analyze_case(case)
    finding = next(
        item
        for item in result.findings
        if item.code == "INSPECTION_LEGACY_CUSTOM_FAILURE"
    )
    comparison = compare_cases([case]).ranked[0]

    assert finding.severity == Severity.HIGH
    assert finding.decision_impact.value == "INSPECT"
    assert comparison.mechanical_risk == ComparisonRisk.HIGH


def test_missing_title_photo_remains_a_document_gate_not_a_price_item() -> None:
    session = InspectionSession(
        inspection_type="self",
        items=[
            InspectionItem(
                key="title_photo_redacted",
                label="client label",
                stage="pre_visit",
                result=InspectionResult.CONCERN,
            )
        ],
        source_id="self-source",
        evidence_id="",
    )
    result = analyze_case(CaseContext(inspections=[session]))
    finding = next(
        item
        for item in result.findings
        if item.code == "INSPECTION_TITLE_PHOTO_REDACTED"
    )

    assert finding.decision_impact == Decision.INSPECT
    assert finding.blocks_purchase is False
    assert "original title photo" in finding.next_checks[0]
    assert "inspect the original before payment" in finding.next_checks[0]
    assert "price" not in finding.next_checks[0].lower()
    assert "written PPI finding" not in finding.next_checks[0]


def test_canonical_ppi_item_requires_ppi_session_and_named_inspector(
    client: TestClient,
    resolved_vehicle: dict[str, object],
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    item = {
        "key": "structural_underbody",
        "label": "Structure",
        "stage": "pre_visit",
        "result": "PASS",
        "severityIfFailed": "LOW",
    }

    no_inspector = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={"inspectionType": "ppi", "items": [item]},
    )
    custom_no_inspector = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={
            "inspectionType": "ppi",
            "items": [
                {
                    "key": "custom_shop_note",
                    "label": "Custom shop note",
                    "stage": "ppi",
                    "result": "PASS",
                }
            ],
        },
    )
    wrong_session = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={"inspectionType": "self", "items": [item]},
    )

    assert no_inspector.status_code == 422
    assert "inspector" in no_inspector.text
    assert custom_no_inspector.status_code == 422
    assert "inspector" in custom_no_inspector.text
    assert wrong_session.status_code == 422
    assert "inspectionType=ppi" in wrong_session.text


def test_ppi_coverage_and_status_require_preexisting_report_links(
    client: TestClient,
    resolved_vehicle: dict[str, object],
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    _advance_to_self_inspected(client, case_id)
    vehicle = VehicleSpec.model_validate(resolved_vehicle)
    required = sorted(required_inspection_keys(vehicle, "ppi"))
    unbound_items = [
        {
            "key": key,
            "label": key,
            "stage": "ppi",
            "result": "PASS",
        }
        for key in required
    ]

    unbound = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={
            "inspectionType": "ppi",
            "inspector": "Arbitrary typed shop name",
            "items": unbound_items,
        },
    )
    assert unbound.status_code == 201, unbound.text
    stored = client.get(f"/v1/cases/{case_id}").json()
    assert stored["status"] == "SELF_INSPECTED"
    unbound_session = stored["inspections"][-1]
    unbound_source = next(
        item for item in stored["sources"] if item["id"] == unbound_session["sourceId"]
    )
    unbound_evidence = next(
        item
        for item in stored["evidence"]
        if item["id"] == unbound_session["evidenceId"]
    )
    assert unbound_source["provider"] == "user-attested-ppi"
    assert unbound_evidence["kind"] == "self_inspection"
    manual_upgrade = client.patch(
        f"/v1/cases/{case_id}/status",
        json={"status": "PPI_COMPLETE", "reason": "Typed shop name only"},
    )
    assert manual_upgrade.status_code == 422
    analysis = client.post(f"/v1/cases/{case_id}/analyze", json={})
    assert analysis.status_code == 200, analysis.text
    assert any(
        "substantive uploaded PPI report" in item
        for item in analysis.json()["unknowns"]
    )

    upload = client.post(
        f"/v1/cases/{case_id}/artifacts",
        json={
            "filename": "independent-ppi.txt",
            "kind": "ppi",
            "mediaType": "text/plain",
            "text": (
                "Independent pre-purchase inspection report with lift, brakes, "
                "leaks, modules, suspension, and emissions results."
            ),
        },
    )
    assert upload.status_code == 201, upload.text
    report_evidence_id = upload.json()["evidenceId"]
    bound = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={
            "inspectionType": "ppi",
            "inspector": "Independent shop",
            "items": [
                {**item, "evidenceIds": [report_evidence_id]} for item in unbound_items
            ],
        },
    )
    assert bound.status_code == 201, bound.text
    stored = client.get(f"/v1/cases/{case_id}").json()
    assert stored["status"] == "PPI_COMPLETE"
    bound_session = stored["inspections"][-1]
    bound_source = next(
        item for item in stored["sources"] if item["id"] == bound_session["sourceId"]
    )
    assert bound_source["provider"] == "evidence-bound-ppi"
    case = client.app.state.repository.get_case(case_id)
    completion, completed = _inspection_completion(case, inspection_type="ppi")
    assert completion == 1
    assert completed == set(required)


def test_crafted_ocdd_cannot_import_forged_ppi_artifact_trust(
    client: TestClient,
    resolved_vehicle: dict[str, object],
) -> None:
    vehicle = VehicleSpec.model_validate(resolved_vehicle)
    artifact_source, artifact_evidence = _trusted_ppi_artifact()
    session_source = SourceEnvelope(
        source_type="ppi",
        provider="evidence-bound-ppi",
        content_sha256="e" * 64,
    )
    session_evidence = Evidence(
        source_id=session_source.id,
        kind=EvidenceKind.PPI,
        label="PPI checklist linked to uploaded report",
        excerpt="All critical checks recorded",
    )
    session = InspectionSession(
        inspection_type="ppi",
        inspector="Claimed independent shop",
        items=[
            InspectionItem(
                key=key,
                label=key,
                stage="ppi",
                result=InspectionResult.PASS,
                evidence_ids=[artifact_evidence.id],
            )
            for key in sorted(required_inspection_keys(vehicle, "ppi"))
        ],
        source_id=session_source.id,
        evidence_id=session_evidence.id,
    )
    crafted = CaseContext(
        vehicle=vehicle,
        status=CaseStatus.PPI_COMPLETE,
        decision=Decision.BUY_CANDIDATE,
        coverage_percent=100,
        sources=[artifact_source, session_source],
        evidence=[artifact_evidence, session_evidence],
        inspections=[session],
    )
    package = export_case(crafted, "correct horse battery staple")

    imported = client.post(
        "/v1/cases/import",
        json={
            "contentBase64": base64.b64encode(package).decode("ascii"),
            "passphrase": "correct horse battery staple",
        },
    )

    assert imported.status_code == 201, imported.text
    stored = client.app.state.repository.get_case(imported.json()["caseId"])
    assert trusted_ppi_artifact_evidence_ids(stored) == set()
    assert _inspection_completion(stored, inspection_type="ppi")[0] == 0
    assert stored.status == CaseStatus.NEEDS_DATA
    assert stored.decision == Decision.INSPECT
    assert (
        stored.evidence[0].metadata["ppi_artifact_binding_basis"]
        == "import_untrusted_requires_reupload"
    )


def test_inapplicable_manual_and_hybrid_checks_are_forced_not_applicable(
    client: TestClient,
    resolved_vehicle: dict[str, object],
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    self_response = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={
            "inspectionType": "self",
            "items": [
                {
                    "key": "clutch",
                    "label": "Failed clutch",
                    "stage": "road_test",
                    "result": "FAIL",
                    "severityIfFailed": "CRITICAL",
                }
            ],
        },
    )
    ppi_response = client.post(
        f"/v1/cases/{case_id}/inspections",
        json={
            "inspectionType": "ppi",
            "inspector": "Independent shop",
            "items": [
                {
                    "key": "hybrid_ev_battery",
                    "label": "Failed battery",
                    "stage": "ppi",
                    "result": "FAIL",
                    "severityIfFailed": "CRITICAL",
                }
            ],
        },
    )

    assert self_response.status_code == 201, self_response.text
    assert ppi_response.status_code == 201, ppi_response.text
    assert self_response.json()["items"][0]["result"] == "NOT_APPLICABLE"
    assert ppi_response.json()["items"][0]["result"] == "NOT_APPLICABLE"


def test_checklist_endpoint_exposes_canonical_severity(client: TestClient) -> None:
    response = client.get("/v1/inspection-checklist")

    assert response.status_code == 200
    items = {
        item["key"]: item
        for stage in response.json()["stages"]
        for item in stage["items"]
    }
    assert items["brakes"]["severityIfFailed"] == "HIGH"
    assert items["title_photo_redacted"]["severityIfFailed"] == "CRITICAL"
    assert items["structural_underbody"]["requiresPpi"] is True


def test_cloud_ppi_preserves_inspector_assertion_without_storing_raw_name(
    cloud_client: TestClient,
    resolved_vehicle: dict[str, object],
) -> None:
    created = cloud_client.post("/v1/cases", json={"vehicle": resolved_vehicle})
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    token = created.headers["X-OCDD-Case-Token"]
    headers = {"X-OCDD-Case-Token": token}

    response = cloud_client.post(
        f"/v1/cases/{case_id}/inspections",
        headers=headers,
        json={
            "inspectionType": "ppi",
            "inspector": "Dr. Sensitive Full Name at Example Garage",
            "items": [
                {
                    "key": "structural_underbody",
                    "label": "untrusted",
                    "stage": "pre_visit",
                    "result": "PASS",
                    "severityIfFailed": "LOW",
                }
            ],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["inspector"] == "inspector name supplied (redacted)"
    stored = cloud_client.get(f"/v1/cases/{case_id}", headers=headers).json()
    serialized = str(stored)
    assert "Sensitive Full Name" not in serialized
    assert stored["inspections"][0]["inspector"] == "inspector name supplied (redacted)"
    source_id = stored["inspections"][0]["sourceId"]
    source = next(item for item in stored["sources"] if item["id"] == source_id)
    evidence_id = stored["inspections"][0]["evidenceId"]
    evidence = next(item for item in stored["evidence"] if item["id"] == evidence_id)
    assert source["provider"] == "user-attested-ppi"
    assert evidence["kind"] == "self_inspection"
    assert evidence["metadata"]["verification_level"] == "user_attested"
