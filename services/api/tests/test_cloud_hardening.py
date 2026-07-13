from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.evidence as evidence_module
from app.cloud_security import CloudArtifactBodyLimitMiddleware
from app.main import create_app


HEADER = "X-OCDD-Case-Token"


class _NeverProcessor:
    def __init__(self) -> None:
        self.called = False

    def extract_pages(self, *args: object, **kwargs: object) -> list[str]:
        del args, kwargs
        self.called = True
        raise AssertionError("oversized or minimal cloud evidence must not reach a processor")


def _create(client: TestClient) -> tuple[str, dict[str, str]]:
    response = client.post("/v1/cases", json={"language": "en"})
    assert response.status_code == 201, response.text
    token = response.headers.get(HEADER)
    return response.json()["id"], ({HEADER: token} if token else {})


def test_oversized_base64_is_413_before_decode_dispatch_persistence_or_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    processor = _NeverProcessor()
    app = create_app(
        database_path=tmp_path / "oversized.sqlite3",
        deployment_mode="cloud",
        artifact_max_bytes=8,
        artifact_request_max_bytes=1024,
        cloud_case_create_limit_per_minute=10,
        cloud_artifact_upload_limit_per_minute=10,
        document_processor=processor,
    )
    caplog.set_level(logging.DEBUG)
    with TestClient(app) as client:
        case_id, access = _create(client)

        def _decoder_must_not_run(*args: object, **kwargs: object) -> bytes:
            del args, kwargs
            raise AssertionError("base64 decoder was called")

        monkeypatch.setattr(evidence_module.base64, "b64decode", _decoder_must_not_run)
        response = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "Jane-Sensitive-title.txt",
                "kind": "other",
                "contentBase64": base64.b64encode(b"123456789").decode("ascii"),
            },
            headers=access,
        )

    assert response.status_code == 413
    assert processor.called is False
    assert app.state.repository.artifact_count(case_id) == 0
    stored_case = app.state.repository.get_case(case_id)
    assert stored_case.sources == []
    assert stored_case.evidence == []
    assert "Jane-Sensitive" not in caplog.text
    assert "123456789" not in caplog.text


def test_stream_body_cap_rejects_missing_and_falsely_small_content_length() -> None:
    async def exercise(headers: list[tuple[bytes, bytes]]) -> tuple[bool, list[dict[str, Any]]]:
        called = False

        async def downstream(
            scope: dict[str, Any],
            receive: Any,
            send: Any,
        ) -> None:
            del scope, receive, send
            nonlocal called
            called = True

        middleware = CloudArtifactBodyLimitMiddleware(
            downstream,
            enabled=True,
            max_body_bytes=8,
        )
        chunks = [
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"67890", "more_body": False},
        ]
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return chunks.pop(0)

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/v1/cases/case-id/artifacts",
                "headers": headers,
            },
            receive,
            send,
        )
        return called, sent

    for headers in ([], [(b"content-length", b"1")]):
        called, sent = asyncio.run(exercise(headers))
        assert called is False
        assert sent[0]["type"] == "http.response.start"
        assert sent[0]["status"] == 413


def test_cloud_case_creation_limit_uses_direct_peer_not_forwarded_headers(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "case-limit.sqlite3",
        deployment_mode="cloud",
        cloud_case_create_limit_per_minute=1,
        cloud_artifact_upload_limit_per_minute=10,
    )
    with TestClient(app) as client:
        first = client.post(
            "/v1/cases",
            json={"language": "en"},
            headers={"X-Forwarded-For": "198.51.100.10"},
        )
        second = client.post(
            "/v1/cases",
            json={"language": "en"},
            headers={"X-Forwarded-For": "203.0.113.20"},
        )

    assert first.status_code == 201
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1
    assert len(app.state.repository.list_cases()) == 1


def test_cloud_artifact_upload_limit_fails_closed_before_second_persistence(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "artifact-limit.sqlite3",
        deployment_mode="cloud",
        cloud_case_create_limit_per_minute=10,
        cloud_artifact_upload_limit_per_minute=1,
    )
    with TestClient(app) as client:
        case_id, access = _create(client)
        first = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={"filename": "one.txt", "kind": "other", "text": "first"},
            headers={**access, "X-Forwarded-For": "198.51.100.10"},
        )
        second = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={"filename": "two.txt", "kind": "other", "text": "second"},
            headers={**access, "X-Forwarded-For": "203.0.113.20"},
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 429
    assert app.state.repository.artifact_count(case_id) == 1


def test_cloud_vin_decode_has_a_dedicated_peer_rate_limit(tmp_path: Path) -> None:
    app = create_app(
        database_path=tmp_path / "vin-decode-limit.sqlite3",
        deployment_mode="cloud",
        cloud_case_create_limit_per_minute=10,
        cloud_artifact_upload_limit_per_minute=10,
        cloud_vin_decode_limit_per_minute=1,
    )
    with TestClient(app) as client:
        first = client.post("/v1/vehicles/decode-vin", json={"vin": "invalid"})
        second = client.post("/v1/vehicles/decode-vin", json={"vin": "invalid"})

    assert first.status_code == 422
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1


def test_cloud_title_and_seller_chat_never_store_raw_body_name_or_label(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    processor = _NeverProcessor()
    app = create_app(
        database_path=tmp_path / "minimal-sensitive.sqlite3",
        deployment_mode="cloud",
        cloud_case_create_limit_per_minute=10,
        cloud_artifact_upload_limit_per_minute=10,
        document_processor=processor,
    )
    secrets = [
        "Jane Sensitive",
        "ABC123456",
        "9999 Example Privacy Test Rd",
        "Sam Private",
        "Janet Different",
        "I reset the codes before you arrive",
    ]
    caplog.set_level(logging.DEBUG)
    with TestClient(app) as client:
        case_id, access = _create(client)
        title = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "Jane Sensitive title.txt",
                "label": "Jane Sensitive original title",
                "kind": "title",
                "text": "Owner Jane Sensitive; Title Number ABC123456; 9999 Example Privacy Test Rd",
            },
            headers=access,
        )
        chat = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "chat-with-Sam-Private.txt",
                "label": "Chat with Sam Private",
                "kind": "seller_message",
                "text": "Sam Private said: I reset the codes before you arrive",
            },
            headers=access,
        )
        matched_title = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "second-sensitive-title.txt",
                "kind": "title",
                "text": "Another Human Name",
                "identityTitleMatch": "MATCH",
            },
            headers=access,
        )
        server_compared_title = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "server-compared-title.txt",
                "kind": "title",
                "text": "Sensitive title body",
                "titleOwnerName": "JANE-SENSITIVE",
                "sellerLegalName": "Jane Sensitive",
            },
            headers=access,
        )
        server_mismatch_title = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "server-mismatch-title.txt",
                "kind": "title",
                "text": "Another sensitive title body",
                "titleOwnerName": "Jane Sensitive",
                "sellerLegalName": "Janet Different",
            },
            headers=access,
        )
        raw_name_field = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "attempted-name-field.txt",
                "kind": "title",
                "text": "content",
                "titleOwnerName": "Jane Sensitive",
            },
            headers=access,
        )
        case_response = client.get(f"/v1/cases/{case_id}", headers=access)

    assert title.status_code == 201, title.text
    assert chat.status_code == 201, chat.text
    assert matched_title.status_code == 201, matched_title.text
    assert server_compared_title.status_code == 201, server_compared_title.text
    assert server_mismatch_title.status_code == 201, server_mismatch_title.text
    assert raw_name_field.status_code == 422
    assert title.json()["expiresAt"] is None
    assert chat.json()["expiresAt"] is None
    assert app.state.artifact_store.get(title.json()["artifactId"]) is None
    assert app.state.artifact_store.get(chat.json()["artifactId"]) is None
    assert app.state.repository.artifact_count(case_id) == 0
    assert processor.called is False

    serialized = case_response.text
    for secret in [*secrets, "Another Human Name", "Chat with Sam Private"]:
        assert secret not in serialized
        assert secret not in caplog.text
    evidence = case_response.json()["evidence"]
    assert evidence[0]["label"] == "Title verification artifact"
    assert evidence[0]["excerpt"] is None
    assert evidence[0]["metadata"]["identity_title_match"] == "UNKNOWN"
    assert evidence[1]["label"] == "Seller message artifact"
    assert evidence[1]["excerpt"] is None
    assert evidence[2]["metadata"]["identity_title_match"] == "MATCH"
    assert evidence[2]["metadata"]["identity_comparison_basis"] == "user_attested"
    assert evidence[3]["metadata"]["identity_title_match"] == "MATCH"
    assert evidence[3]["metadata"]["identity_comparison_basis"] == "server_exact_normalized"
    assert evidence[4]["metadata"]["identity_title_match"] == "MISMATCH"
    assert evidence[4]["metadata"]["identity_comparison_basis"] == "server_exact_normalized"


def test_cloud_ordinary_artifact_keeps_structured_fact_but_not_name_in_case_or_log(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(
        database_path=tmp_path / "ordinary-name.sqlite3",
        deployment_mode="cloud",
    )
    caplog.set_level(logging.DEBUG)
    with TestClient(app) as client:
        case_id, access = _create(client)
        response = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "Jane-Sensitive-receipt.txt",
                "label": "Jane Sensitive service invoice",
                "kind": "receipt",
                "text": "01/02/2025 120,000 miles Customer Jane Sensitive vehicle serviced",
            },
            headers=access,
        )
        case = client.get(f"/v1/cases/{case_id}", headers=access).json()

    assert response.status_code == 201, response.text
    assert case["evidence"][0]["excerpt"] is None
    assert case["evidence"][0]["label"] == "Uploaded receipt evidence"
    assert case["history"][0]["eventType"] == "service"
    assert "Jane Sensitive" not in str(case)
    assert "Jane Sensitive" not in caplog.text


def test_cloud_ocdd_import_cannot_bypass_free_text_deidentification(
    tmp_path: Path,
) -> None:
    local_app = create_app(
        database_path=tmp_path / "import-source.sqlite3",
        deployment_mode="local",
    )
    cloud_app = create_app(
        database_path=tmp_path / "import-destination.sqlite3",
        deployment_mode="cloud",
    )
    with TestClient(local_app) as local:
        created = local.post(
            "/v1/cases",
            json={"language": "en", "buyerGoal": "Meet Jane Sensitive at 9999 Example Privacy Test Rd"},
        )
        case_id = created.json()["id"]
        listing = local.post(
            f"/v1/cases/{case_id}/listings/import",
            json={
                "listings": [
                    {
                        "title": "Jane Sensitive personal car",
                        "askingPrice": 5000,
                        "location": "9999 Example Privacy Test Rd",
                        "description": "Sam Private said I reset the codes",
                    }
                ]
            },
        )
        assert listing.status_code == 201
        for kind, text in (
            ("title", "Owner Jane Sensitive Title Number ABC123456"),
            ("seller_message", "Sam Private said I reset the codes"),
        ):
            uploaded = local.post(
                f"/v1/cases/{case_id}/artifacts",
                json={
                    "filename": f"Jane-Sensitive-{kind}.txt",
                    "label": f"Jane Sensitive {kind}",
                    "kind": kind,
                    "text": text,
                },
            )
            assert uploaded.status_code == 201, uploaded.text
        package = local.get(
            f"/v1/cases/{case_id}/export",
            headers={"X-OCDD-Passphrase": "correct-horse"},
        )
        assert package.status_code == 200

    with TestClient(cloud_app) as cloud:
        imported = cloud.post(
            "/v1/cases/import",
            json={
                "contentBase64": base64.b64encode(package.content).decode("ascii"),
                "passphrase": "correct-horse",
            },
        )
        assert imported.status_code == 201, imported.text
        access = {HEADER: imported.headers[HEADER]}
        case_response = cloud.get(
            f"/v1/cases/{imported.json()['caseId']}",
            headers=access,
        )

    serialized = case_response.text
    for secret in (
        "Jane Sensitive",
        "Sam Private",
        "9999 Example Privacy Test",
        "ABC123456",
        "I reset the codes",
    ):
        assert secret not in serialized
    imported_case = case_response.json()
    assert imported_case["buyerGoal"] is None
    assert imported_case["listings"][0]["title"] == "Imported vehicle listing"
    title_evidence = next(
        item for item in imported_case["evidence"] if item["kind"] == "title"
    )
    assert title_evidence["excerpt"] is None
    assert title_evidence["metadata"]["identity_title_match"] == "UNKNOWN"


def test_local_seller_message_retains_useful_original_and_excerpt(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "local-useful.sqlite3",
        deployment_mode="local",
    )
    with TestClient(app) as client:
        case_id, _ = _create(client)
        response = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "seller-message.txt",
                "kind": "seller_message",
                "text": "Sam said the engine mount was replaced last month",
            },
        )
        case = client.get(f"/v1/cases/{case_id}").json()

    assert response.status_code == 201, response.text
    raw = app.state.artifact_store.get(response.json()["artifactId"])
    assert raw == b"Sam said the engine mount was replaced last month"
    assert case["evidence"][0]["excerpt"] == raw.decode("utf-8")


def test_cloud_limit_configuration_cannot_be_disabled(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="rate limits must be positive"):
        create_app(
            database_path=tmp_path / "invalid.sqlite3",
            deployment_mode="cloud",
            cloud_case_create_limit_per_minute=0,
        )

    with pytest.raises(ValueError, match="rate limits must be positive"):
        create_app(
            database_path=tmp_path / "invalid-vin-limit.sqlite3",
            deployment_mode="cloud",
            cloud_vin_decode_limit_per_minute=0,
        )
