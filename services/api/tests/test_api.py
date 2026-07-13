from __future__ import annotations

from fastapi.testclient import TestClient


def _create_case(client: TestClient, vehicle: dict[str, object]) -> str:
    response = client.post(
        "/v1/cases",
        json={"language": "zh-CN", "allInBudget": 7000, "vehicle": vehicle},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["language"] == "zh-CN"
    assert body["allInBudget"] == 7000
    return body["id"]


def test_case_listing_scan_inspection_analysis_and_report(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    target = {
        "title": "2014 MINI Cooper S",
        "askingPrice": 6000,
        "mileage": 120000,
        "sellerType": "private",
        "channel": "facebook_marketplace",
        "vin": resolved_vehicle["vin"],
        "year": 2014,
        "make": "MINI",
        "model": "Cooper S",
        "generation": "F56",
        "platform": "F56",
        "engine": "B48 2.0T",
        "transmission": "Aisin 6-speed automatic",
        "drivetrain": "FWD",
        "isTarget": True,
    }
    imported = client.post(
        f"/v1/cases/{case_id}/listings/import", json={"listings": [target]}
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["imported"] == 1

    # The bridge payload is accepted directly. Generic coverage does not imply
    # that ABS/SRS/body were scanned.
    scan = client.post(
        f"/v1/cases/{case_id}/obd/scans",
        json={
            "vin": resolved_vehicle["vin"],
            "adapter": "ELM327",
            "module_coverage": ["generic_powertrain_emissions"],
            "readiness": {"available": True, "mil_on": False, "raw": "410100"},
            "codes": [],
            "raw": {"03": "NO DATA"},
            "limitations": ["Generic scan only"],
        },
    )
    assert scan.status_code == 201, scan.text
    assert scan.json()["moduleCoverage"]["abs"] == "NOT_SCANNED"

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
                    "notes": "Pressure test found a coolant leak",
                    "severityIfFailed": "HIGH",
                    "estimatedCost": {"low": 500, "likely": 1100, "high": 2200},
                }
            ],
        },
    )
    assert ppi.status_code == 201, ppi.text

    analysis = client.post(f"/v1/cases/{case_id}/analyze", json={})
    assert analysis.status_code == 200, analysis.text
    body = analysis.json()
    assert body["decision"] == "INSPECT"
    assert any(item["code"] == "INSPECTION_COOLANT_LEAK" for item in body["findings"])
    assert any("ABS" in item for item in body["unknowns"])

    report = client.get(f"/v1/cases/{case_id}/report?language=zh-CN")
    assert report.status_code == 200
    assert "未知" in report.json()["disclaimer"]
    assert "机械状况正常" not in report.json()["summary"]
    pdf = client.get(f"/v1/cases/{case_id}/report?language=zh-CN&format=pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_listing_import_is_idempotent(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    payload = {
        "listings": [
            {
                "title": "Target",
                "asking_price": 5500,
                "seller_type": "private",
                "channel": "user_entry",
                "is_target": True,
            }
        ]
    }
    assert (
        client.post(f"/v1/cases/{case_id}/listings/import", json=payload).json()[
            "imported"
        ]
        == 1
    )
    assert (
        client.post(f"/v1/cases/{case_id}/listings/import", json=payload).json()[
            "imported"
        ]
        == 0
    )


def test_abs_only_scan_does_not_claim_no_powertrain_codes(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    scan = client.post(
        f"/v1/cases/{case_id}/obd/scans",
        json={
            "scannerName": "ABS-only test scanner",
            "moduleCoverage": {
                "powertrain": "NOT_SCANNED",
                "abs": "SCANNED",
                "srs": "NOT_SCANNED",
                "body": "NOT_SCANNED",
            },
            "dtcs": [],
            "limitations": ["Powertrain was not scanned"],
        },
    )
    assert scan.status_code == 201, scan.text

    case = client.get(f"/v1/cases/{case_id}")
    assert case.status_code == 200, case.text
    excerpt = next(
        item["excerpt"]
        for item in case.json()["evidence"]
        if item["kind"] == "obd_scan"
    )
    assert excerpt == "No generic powertrain DTC scan data"
    assert "DTC reported" not in excerpt


def test_target_refresh_updates_details_but_preserves_conflicting_canonical_vin(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    old = {
        "title": "Target before refresh",
        "askingPrice": 6000,
        "mileage": 120000,
        "isTarget": True,
        "capturedAt": "2026-07-12T12:00:00Z",
    }
    latest = {
        "title": "Target after refresh",
        "askingPrice": 5500,
        "mileage": 121500,
        "vin": "2TESTCAR000000002",
        "engine": "Corrected B48 2.0T",
        "transmission": "Corrected 6-speed manual",
        "bodyStyle": "hatchback",
        "isTarget": True,
        "capturedAt": "2026-07-13T12:00:00Z",
    }

    assert (
        client.post(
            f"/v1/cases/{case_id}/listings/import", json={"listings": [old]}
        ).json()["imported"]
        == 1
    )
    assert (
        client.post(
            f"/v1/cases/{case_id}/listings/import", json={"listings": [latest]}
        ).json()["imported"]
        == 1
    )

    case = client.get(f"/v1/cases/{case_id}").json()
    assert len(case["listings"]) == 2
    assert [item["askingPrice"] for item in case["listings"]] == [6000, 5500]
    assert all(item["isTarget"] for item in case["listings"])
    assert case["vehicle"]["odometerMiles"] == 121500
    # VIN is a durable identity claim. A different target VIN remains in the
    # listing evidence for conflict analysis rather than silently changing the
    # vehicle under review.
    assert case["vehicle"]["vin"] == resolved_vehicle["vin"]
    assert case["vehicle"]["engine"] == "Corrected B48 2.0T"
    assert case["vehicle"]["transmission"] == "Corrected 6-speed manual"
    assert case["vehicle"]["bodyStyle"] == "hatchback"
    # Omitted refreshed fields retain their earlier resolved value.
    assert case["vehicle"]["generation"] == "F56"

    analysis = client.post(f"/v1/cases/{case_id}/analyze", json={})
    assert analysis.status_code == 200, analysis.text
    finding = next(
        item for item in analysis.json()["findings"] if item["code"] == "VIN_MISMATCH"
    )
    assert analysis.json()["decision"] == "STOP"
    assert finding["evidenceIds"] == [case["listings"][1]["evidenceId"]]


def test_first_target_vin_fills_an_empty_case_vehicle(client: TestClient) -> None:
    case_id = _create_case(
        client,
        {
            "year": 2014,
            "make": "MINI",
            "model": "Cooper S",
        },
    )
    target_vin = "1TESTCAR000000001"
    imported = client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={
            "listings": [
                {
                    "title": "Target with VIN",
                    "askingPrice": 6000,
                    "vin": target_vin,
                    "isTarget": True,
                }
            ]
        },
    )
    assert imported.status_code == 201, imported.text

    case = client.get(f"/v1/cases/{case_id}").json()
    assert case["vehicle"]["vin"] == target_vin

    analysis = client.post(f"/v1/cases/{case_id}/analyze", json={})
    assert analysis.status_code == 200, analysis.text
    assert all(item["code"] != "VIN_MISMATCH" for item in analysis.json()["findings"])


def test_listing_contact_details_are_redacted_from_structured_case(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    response = client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={
            "listings": [
                {
                    "title": "Private vehicle",
                    "askingPrice": 5000,
                    "description": "Call 212-555-1212 or seller@example.com",
                }
            ]
        },
    )
    assert response.status_code == 201
    serialized = client.get(f"/v1/cases/{case_id}").text
    assert "212-555-1212" not in serialized
    assert "seller@example.com" not in serialized
    assert "REDACTED" in serialized


def test_transaction_context_is_never_an_openapi_query_parameter(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    """Sensitive transaction data belongs in a POST body, never in a URL."""

    operation = client.get("/openapi.json").json()["paths"][
        "/v1/cases/{case_id}/transaction-plan"
    ]["get"]
    parameters = operation.get("parameters", [])

    assert not any(parameter.get("name") == "context" for parameter in parameters)

    case_id = _create_case(client, resolved_vehicle)
    missing = client.get(f"/v1/cases/{case_id}/transaction-plan")
    assert missing.status_code == 409
    assert "POST it to this endpoint first" in missing.json()["detail"]


def test_cloud_title_content_is_transient_and_not_copied_to_case(
    cloud_client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    created = cloud_client.post(
        "/v1/cases",
        json={"language": "zh-CN", "allInBudget": 7000, "vehicle": resolved_vehicle},
    )
    assert created.status_code == 201
    case_id = created.json()["id"]
    access = {"X-OCDD-Case-Token": created.headers["X-OCDD-Case-Token"]}
    raw = "Owner: Jane Sensitive\nTitle Number ABC123456\n9999 Example Privacy Test Rd\n"
    response = cloud_client.post(
        f"/v1/cases/{case_id}/artifacts",
        json={
            "filename": "Jane Sensitive title.txt",
            "kind": "title",
            "mediaType": "text/plain",
            "text": raw,
        },
        headers=access,
    )
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["expiresAt"] is None
    assert cloud_client.app.state.artifact_store.get(receipt["artifactId"]) is None
    case_text = cloud_client.get(f"/v1/cases/{case_id}", headers=access).text
    assert "Jane Sensitive" not in case_text
    assert "ABC123456" not in case_text
    assert "9999 Example Privacy Test" not in case_text


def test_artifact_redacts_contact_data_in_structured_evidence(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    response = client.post(
        f"/v1/cases/{case_id}/artifacts",
        json={
            "filename": "message.txt",
            "kind": "seller_message",
            "text": "Email me at seller@example.com or 212-555-1212 at 10 Main Street",
        },
    )
    assert response.status_code == 201
    raw_blob = client.app.state.repository.get_artifact_bytes(
        response.json()["artifactId"]
    )
    assert raw_blob is not None
    assert b"seller@example.com" not in raw_blob
    assert client.app.state.artifact_store.get(
        response.json()["artifactId"]
    ).startswith(b"Email me")
    case = client.get(f"/v1/cases/{case_id}").json()
    excerpt = case["evidence"][0]["excerpt"]
    assert "seller@example.com" not in excerpt
    assert "212-555-1212" not in excerpt
    assert "REDACTED" in excerpt


def test_compare_requires_all_cases(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    response = client.post("/v1/compare", json={"caseIds": [case_id, "missing"]})
    assert response.status_code == 404
    assert response.json()["detail"]["missing_case_ids"] == ["missing"]


def test_state_machine_rejects_skips_and_requires_evidence_for_rejection(
    client: TestClient, resolved_vehicle: dict[str, object]
) -> None:
    case_id = _create_case(client, resolved_vehicle)
    skipped = client.patch(
        f"/v1/cases/{case_id}/status",
        json={"status": "PURCHASED", "reason": "skip everything"},
    )
    assert skipped.status_code == 409
    rejected = client.patch(
        f"/v1/cases/{case_id}/status",
        json={"status": "REJECTED", "reason": "seller refused title verification"},
    )
    assert rejected.status_code == 422
