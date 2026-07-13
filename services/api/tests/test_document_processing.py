from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.document_processing import (
    CeleryDocumentProcessor,
    DocumentProcessingUnavailable,
    InlineDocumentProcessor,
    create_document_processor,
    decrypt_envelope,
    encrypt_envelope,
)
from app.main import create_app
from pypdf import PdfWriter


KEY = b"0123456789abcdef0123456789abcdef"


class _Result:
    def __init__(self, value: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.revoked = False

    def get(self, timeout: float) -> dict[str, object]:
        assert timeout > 0
        if self.error:
            raise self.error
        assert self.value is not None
        return self.value

    def revoke(self, terminate: bool = False) -> None:
        assert terminate is False
        self.revoked = True


class _EchoWorkerClient:
    def __init__(self) -> None:
        self.dispatched: dict[str, Any] | None = None

    def send_task(self, name: str, **options: Any) -> _Result:
        assert name == "ocdd.parse_encrypted_artifact"
        self.dispatched = options
        envelope = options["kwargs"]["envelope"]
        content = decrypt_envelope(KEY, envelope, expected_purpose="artifact")
        parsed = {
            "sha256": envelope["sha256"],
            "pages": [{"page": 1, "text": content.decode("utf-8")}],
            "needs_ocr": False,
            "ocr_used": False,
        }
        encrypted = encrypt_envelope(
            KEY,
            json.dumps(parsed).encode("utf-8"),
            purpose="result",
            metadata={"sha256": envelope["sha256"]},
        )
        return _Result(encrypted)


class _OfflineClient:
    def __init__(self) -> None:
        self.result = _Result(error=TimeoutError("no worker"))

    def send_task(self, name: str, **options: Any) -> _Result:
        del name, options
        return self.result


class _NeedsOcrWorkerClient:
    def __init__(self) -> None:
        self.result: _Result | None = None

    def send_task(self, name: str, **options: Any) -> _Result:
        assert name == "ocdd.parse_encrypted_artifact"
        envelope = options["kwargs"]["envelope"]
        parsed = {
            "sha256": envelope["sha256"],
            "pages": [{"page": 1, "text": ""}],
            "needs_ocr": True,
            "ocr_used": False,
        }
        encrypted = encrypt_envelope(
            KEY,
            json.dumps(parsed).encode("utf-8"),
            purpose="result",
            metadata={"sha256": envelope["sha256"]},
        )
        self.result = _Result(encrypted)
        return self.result


def _new_case(client: TestClient) -> str:
    response = client.post(
        "/v1/cases",
        json={"language": "en", "vehicle": {"year": 2014, "make": "MINI", "model": "Cooper S"}},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_celery_queue_and_result_never_contain_plaintext_or_original_filename() -> None:
    secret = b"Owner Jane Sensitive, title ABC123 and service history"
    client = _EchoWorkerClient()
    processor = CeleryDocumentProcessor(
        broker_url="redis://unused",
        envelope_key=KEY,
        celery_client=client,
        timeout_seconds=1,
    )

    pages = processor.extract_pages(
        secret,
        media_type="text/plain",
        filename="Jane Sensitive CARFAX.txt",
        content_sha256=hashlib.sha256(secret).hexdigest(),
    )

    assert pages == [secret.decode("utf-8")]
    serialized_dispatch = json.dumps(client.dispatched)
    assert secret.decode("utf-8") not in serialized_dispatch
    assert "Jane Sensitive CARFAX" not in serialized_dispatch
    assert "AES-256-GCM ciphertext" in serialized_dispatch


def test_worker_outage_is_503_and_does_not_persist_raw_artifact(tmp_path: Path) -> None:
    offline = _OfflineClient()
    processor = CeleryDocumentProcessor(
        broker_url="redis://unused",
        envelope_key=KEY,
        celery_client=offline,
        timeout_seconds=0.1,
    )
    app = create_app(
        database_path=tmp_path / "offline.sqlite3",
        deployment_mode="local",
        document_processor=processor,
    )
    with TestClient(app) as client:
        case_id = _new_case(client)
        response = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "private.txt",
                "kind": "history_report",
                "mediaType": "text/plain",
                "text": "private owner text",
            },
        )

    assert response.status_code == 503
    assert "not accepted" in response.json()["detail"]
    assert offline.result.revoked is True
    assert app.state.repository.artifact_count(case_id) == 0


def test_worker_ocr_failure_is_503_and_does_not_create_false_extracted_pages(
    tmp_path: Path,
) -> None:
    worker = _NeedsOcrWorkerClient()
    processor = CeleryDocumentProcessor(
        broker_url="redis://unused",
        envelope_key=KEY,
        celery_client=worker,
        timeout_seconds=1,
    )
    app = create_app(
        database_path=tmp_path / "ocr-failed.sqlite3",
        deployment_mode="local",
        document_processor=processor,
    )
    with TestClient(app) as client:
        case_id = _new_case(client)
        response = client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "scanned-report.pdf",
                "kind": "history_report",
                "mediaType": "application/pdf",
                "contentBase64": "JVBERi0xLjQ=",
            },
        )

    assert response.status_code == 503
    assert "OCR is required or failed" in response.json()["detail"]
    assert worker.result is not None and worker.result.revoked is True
    assert app.state.repository.artifact_count(case_id) == 0
    stored_case = app.state.repository.get_case(case_id)
    assert stored_case.sources == []
    assert stored_case.evidence == []


def test_inline_processor_rejects_scanned_pdf_instead_of_reporting_empty_pages() -> None:
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(buffer)
    content = buffer.getvalue()

    with pytest.raises(DocumentProcessingUnavailable, match="no extractable text"):
        InlineDocumentProcessor().extract_pages(
            content,
            media_type="application/pdf",
            filename="scan.pdf",
            content_sha256=hashlib.sha256(content).hexdigest(),
        )


def test_celery_mode_without_shared_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCDD_DOCUMENT_PROCESSOR", "celery")
    monkeypatch.delenv("OCDD_WORKER_ENVELOPE_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OCDD_WORKER_ENVELOPE_KEY is required"):
        create_document_processor()


def test_upload_logs_never_include_filename_owner_or_chat_text(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    case_id = _new_case(client)
    secret = "Jane Sensitive title ABC123456; chat: meet me at 9999 Example Privacy Test Rd"

    response = client.post(
        f"/v1/cases/{case_id}/artifacts",
        json={
            "filename": "Jane-Sensitive-CARFAX.txt",
            "kind": "history_report",
            "mediaType": "text/plain",
            "text": secret,
        },
    )

    assert response.status_code == 201
    assert "Jane-Sensitive-CARFAX" not in caplog.text
    assert "Jane Sensitive" not in caplog.text
    assert "ABC123456" not in caplog.text
    assert "9999 Example Privacy Test" not in caplog.text
