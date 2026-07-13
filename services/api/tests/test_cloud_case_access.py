from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.case_access import hash_case_token


HEADER = "X-OCDD-Case-Token"


def _create_cloud_case(client: TestClient) -> tuple[str, str]:
    response = client.post("/v1/cases", json={"language": "en"})
    assert response.status_code == 201, response.text
    token = response.headers[HEADER]
    assert token
    assert token not in response.text
    return response.json()["id"], token


def test_cloud_case_capability_is_one_time_hashed_and_not_enumerable(
    cloud_client: TestClient,
) -> None:
    case_id, token = _create_cloud_case(cloud_client)
    repository = cloud_client.app.state.repository

    assert repository.get_case_access_token_hash(case_id) == hash_case_token(token)
    assert repository.get_case_access_token_hash(case_id) != token
    assert token not in repository.get_case(case_id).model_dump_json()
    listed = cloud_client.get("/v1/cases")
    assert listed.status_code == 403
    assert case_id not in listed.text


def test_cloud_missing_and_wrong_tokens_cannot_read_change_or_delete(
    cloud_client: TestClient,
) -> None:
    case_id, token = _create_cloud_case(cloud_client)
    missing_id = "00000000-0000-0000-0000-000000000000"
    wrong = {HEADER: "wrong-token"}

    denied = [
        cloud_client.get(f"/v1/cases/{case_id}"),
        cloud_client.get(f"/v1/cases/{case_id}", headers=wrong),
        cloud_client.patch(
            f"/v1/cases/{case_id}/status",
            json={"status": "NEEDS_DATA", "reason": "unauthorized"},
            headers=wrong,
        ),
        cloud_client.delete(f"/v1/cases/{case_id}", headers=wrong),
        cloud_client.get(f"/v1/cases/{missing_id}", headers={HEADER: token}),
    ]
    assert {(item.status_code, item.text) for item in denied} == {
        (404, '{"detail":"case not found"}')
    }

    allowed = cloud_client.get(f"/v1/cases/{case_id}", headers={HEADER: token})
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "DISCOVERED"


def test_cloud_correct_token_supports_full_mutation_and_delete_flow(
    cloud_client: TestClient,
) -> None:
    case_id, token = _create_cloud_case(cloud_client)
    access = {HEADER: token}

    imported = cloud_client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={
            "listings": [
                {
                    "title": "User-owned listing snapshot",
                    "askingPrice": 5000,
                    "isTarget": True,
                }
            ]
        },
        headers=access,
    )
    assert imported.status_code == 201, imported.text
    assert cloud_client.get(f"/v1/cases/{case_id}", headers=access).json()["status"] == "NEEDS_DATA"

    deleted = cloud_client.delete(f"/v1/cases/{case_id}", headers=access)
    assert deleted.status_code == 204
    assert cloud_client.get(f"/v1/cases/{case_id}", headers=access).status_code == 404


def test_cloud_compare_requires_a_valid_capability_for_every_case(
    cloud_client: TestClient,
) -> None:
    first_id, first_token = _create_cloud_case(cloud_client)
    second_id, second_token = _create_cloud_case(cloud_client)
    base = {"caseIds": [first_id, second_id]}

    assert cloud_client.post("/v1/compare", json=base).status_code == 404
    wrong = {
        **base,
        "accessTokens": {first_id: first_token, second_id: "wrong"},
    }
    assert cloud_client.post("/v1/compare", json=wrong).status_code == 404
    valid = {
        **base,
        "accessTokens": {first_id: first_token, second_id: second_token},
    }
    response = cloud_client.post("/v1/compare", json=valid)
    assert response.status_code == 200, response.text
    assert {item["caseId"] for item in response.json()["ranked"]} == {first_id, second_id}


def test_cloud_import_issues_a_fresh_capability(
    client: TestClient,
    cloud_client: TestClient,
) -> None:
    local = client.post("/v1/cases", json={"language": "en"}).json()
    exported = client.get(
        f"/v1/cases/{local['id']}/export",
        headers={"X-OCDD-Passphrase": "correct-horse"},
    )
    assert exported.status_code == 200

    imported = cloud_client.post(
        "/v1/cases/import",
        json={
            "contentBase64": base64.b64encode(exported.content).decode("ascii"),
            "passphrase": "correct-horse",
        },
    )
    assert imported.status_code == 201, imported.text
    token = imported.headers[HEADER]
    case_id = imported.json()["caseId"]
    assert token and token not in imported.text
    assert cloud_client.get(f"/v1/cases/{case_id}", headers={HEADER: token}).status_code == 200


def test_expired_cloud_case_returns_same_not_found_with_previous_token(
    cloud_client: TestClient,
) -> None:
    case_id, token = _create_cloud_case(cloud_client)
    repository = cloud_client.app.state.repository
    case = repository.get_case(case_id)
    case.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    repository.save_case(case)

    response = cloud_client.get(f"/v1/cases/{case_id}", headers={HEADER: token})
    assert response.status_code == 404
    assert response.json() == {"detail": "case not found"}
    assert repository.get_case_access_token_hash(case_id) is None


def test_cloud_cors_allows_and_exposes_case_capability_header(
    cloud_client: TestClient,
) -> None:
    response = cloud_client.post(
        "/v1/cases",
        json={"language": "en"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 201
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert HEADER.lower() in response.headers["access-control-expose-headers"].lower()

    # The outer CORS middleware must answer the custom-header preflight before
    # the inner case-capability check sees the token-less OPTIONS request.
    case_id = response.json()["id"]
    preflight = cloud_client.options(
        f"/v1/cases/{case_id}",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": HEADER,
        },
    )
    assert preflight.status_code == 200
    assert HEADER.lower() in preflight.headers["access-control-allow-headers"].lower()
