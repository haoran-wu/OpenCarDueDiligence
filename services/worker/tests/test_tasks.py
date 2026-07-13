import os
import hashlib
import json
import base64
from pathlib import Path

from pypdf import PdfWriter

from ocdd_worker.tasks import (
    cleanup_expired_files,
    decrypt_envelope,
    encrypt_envelope,
    extract_document,
    parse_encrypted_artifact,
)


KEY = b"0123456789abcdef0123456789abcdef"
ENCODED_KEY = base64.urlsafe_b64encode(KEY).decode("ascii")


def test_extract_text_document(tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("VIN 123 and service history", encoding="utf-8")
    parsed = extract_document(source)
    assert parsed["needs_ocr"] is False
    assert parsed["pages"][0]["page"] == 1
    assert len(parsed["sha256"]) == 64
    assert parsed["ocr_used"] is False


def test_scanned_pdf_uses_ocr_when_available(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with source.open("wb") as handle:
        writer.write(handle)
    monkeypatch.setattr(
        "ocdd_worker.tasks.ocr_pdf",
        lambda _path: ["01/02/2026 120,000 miles serviced"],
    )

    parsed = extract_document(source)

    assert parsed["needs_ocr"] is False
    assert parsed["ocr_used"] is True
    assert parsed["pages"][0]["page"] == 1
    assert "120,000" in parsed["pages"][0]["text"]


def test_listing_screenshot_uses_ocr_without_image_claims(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "listing.png"
    source.write_bytes(b"not-a-real-image-fixture")
    monkeypatch.setattr(
        "ocdd_worker.tasks._run_ocr",
        lambda _path, _languages: "2014 MINI Cooper S $5,500 120,000 miles",
    )

    parsed = extract_document(source)

    assert parsed["media_type"] == "image/png"
    assert parsed["ocr_used"] is True
    assert parsed["needs_ocr"] is False
    assert parsed["pages"] == [
        {"page": 1, "text": "2014 MINI Cooper S $5,500 120,000 miles"}
    ]


def test_cleanup_only_expired_files(tmp_path: Path) -> None:
    old = tmp_path / "old.pdf"
    fresh = tmp_path / "fresh.pdf"
    old.write_bytes(b"old")
    fresh.write_bytes(b"fresh")
    now = max(old.stat().st_mtime, fresh.stat().st_mtime) + 100
    os.utime(old, (now - 100, now - 100))
    os.utime(fresh, (now - 10, now - 10))
    removed = cleanup_expired_files(tmp_path, ttl_seconds=50, now=now)
    assert removed == ["old.pdf"]
    assert not old.exists() and fresh.exists()


def test_encrypted_task_returns_pages_and_removes_opaque_tempfile(
    tmp_path: Path, monkeypatch
) -> None:
    secret = b"01/02/2026 120,000 miles serviced for Jane Sensitive"
    digest = hashlib.sha256(secret).hexdigest()
    request = encrypt_envelope(
        KEY,
        secret,
        purpose="artifact",
        metadata={"media_type": "text/plain", "suffix": ".txt", "sha256": digest},
    )
    monkeypatch.setenv("OCDD_WORKER_ENVELOPE_KEY", ENCODED_KEY)
    monkeypatch.setenv("OCDD_WORKER_TMP_DIR", str(tmp_path / "opaque"))
    observed_paths: list[Path] = []
    real_extract = extract_document

    def capture_path(path: Path) -> dict[str, object]:
        observed_paths.append(path)
        assert path.name.startswith("artifact-")
        assert "Jane" not in path.name
        return real_extract(path)

    monkeypatch.setattr("ocdd_worker.tasks.extract_document", capture_path)
    response = parse_encrypted_artifact.run(request)

    assert secret.decode("utf-8") not in json.dumps(request)
    assert secret.decode("utf-8") not in json.dumps(response)
    decoded = decrypt_envelope(KEY, response, expected_purpose="result")
    parsed = json.loads(decoded)
    assert parsed["sha256"] == digest
    assert parsed["pages"][0]["text"] == secret.decode("utf-8")
    assert len(observed_paths) == 1
    assert not observed_paths[0].exists()
