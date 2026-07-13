from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from httpx import Response


def _create(client: TestClient, **extra: object) -> Response:
    response = client.post("/v1/cases", json={"language": "en", **extra})
    assert response.status_code == 201, response.text
    return response


def test_cloud_anonymous_case_expires_and_cascades_local_artifacts(
    cloud_client: TestClient,
) -> None:
    created_response = _create(cloud_client)
    created = created_response.json()
    access = {"X-OCDD-Case-Token": created_response.headers["X-OCDD-Case-Token"]}
    assert created["retentionClass"] == "ANONYMOUS"
    assert created["expiresAt"] is not None
    created_at = datetime.fromisoformat(str(created["createdAt"]))
    expires_at = datetime.fromisoformat(str(created["expiresAt"]))
    assert timedelta(days=6, hours=23) < expires_at - created_at <= timedelta(days=7)

    case_id = str(created["id"])
    artifact = cloud_client.post(
        f"/v1/cases/{case_id}/artifacts",
        json={
            "filename": "private.txt",
            "kind": "other",
            "mediaType": "text/plain",
            "text": "private original",
        },
        headers=access,
    )
    assert artifact.status_code == 201, artifact.text
    repository = cloud_client.app.state.repository
    assert repository.artifact_count(case_id) == 1

    case = repository.get_case(case_id)
    case.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    repository.save_case(case)

    health = cloud_client.get("/health")
    assert health.status_code == 200
    assert health.json()["expiredCasesPurged"] == 1
    assert cloud_client.get(f"/v1/cases/{case_id}", headers=access).status_code == 404
    assert repository.artifact_count(case_id) == 0


def test_cloud_account_retention_is_explicit_and_does_not_expire(
    account_cloud_client: TestClient,
) -> None:
    created_response = _create(account_cloud_client, retentionClass="ACCOUNT")
    created = created_response.json()
    access = {"X-OCDD-Case-Token": created_response.headers["X-OCDD-Case-Token"]}
    assert created["retentionClass"] == "ACCOUNT"
    assert created["expiresAt"] is None

    repository = account_cloud_client.app.state.repository
    assert repository.purge_expired_cases(datetime.now(timezone.utc) + timedelta(days=3650)) == 0
    assert account_cloud_client.get(f"/v1/cases/{created['id']}", headers=access).status_code == 200


def test_public_cloud_cannot_claim_account_retention_without_auth_layer(
    cloud_client: TestClient,
) -> None:
    response = cloud_client.post(
        "/v1/cases",
        json={"language": "en", "retentionClass": "ACCOUNT"},
    )
    assert response.status_code == 403


def test_local_case_defaults_to_non_expiring_local_retention(client: TestClient) -> None:
    created = _create(client).json()
    assert created["retentionClass"] == "LOCAL"
    assert created["expiresAt"] is None

    repository = client.app.state.repository
    assert repository.purge_expired_cases(datetime.now(timezone.utc) + timedelta(days=3650)) == 0
    assert client.get(f"/v1/cases/{created['id']}").status_code == 200


def test_cloud_cannot_request_local_retention(cloud_client: TestClient) -> None:
    response = cloud_client.post(
        "/v1/cases",
        json={"language": "en", "retentionClass": "LOCAL"},
    )
    assert response.status_code == 422
