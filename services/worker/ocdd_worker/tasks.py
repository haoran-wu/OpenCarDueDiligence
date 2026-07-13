from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pypdf import PdfReader

from .celery_app import app


ENVELOPE_VERSION = 1
_SUFFIX_RE = re.compile(r"^\.[a-z0-9]{1,9}$")


def load_envelope_key(value: str | None = None) -> bytes:
    encoded = value if value is not None else os.getenv("OCDD_WORKER_ENVELOPE_KEY")
    if not encoded:
        raise RuntimeError("OCDD_WORKER_ENVELOPE_KEY is required by the document worker")
    encoded = encoded.removeprefix("base64:")
    try:
        key = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("OCDD_WORKER_ENVELOPE_KEY must be URL-safe base64") from exc
    if len(key) != 32:
        raise RuntimeError("OCDD_WORKER_ENVELOPE_KEY must decode to exactly 32 bytes")
    return key


def _metadata_bytes(metadata: dict[str, object]) -> bytes:
    return json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")


def encrypt_envelope(
    key: bytes,
    plaintext: bytes,
    *,
    purpose: str,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    public_metadata = {
        "version": ENVELOPE_VERSION,
        "purpose": purpose,
        **(metadata or {}),
    }
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _metadata_bytes(public_metadata))
    return {
        **public_metadata,
        "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
        "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    }


def decrypt_envelope(
    key: bytes,
    envelope: dict[str, object],
    *,
    expected_purpose: str,
) -> bytes:
    if envelope.get("version") != ENVELOPE_VERSION or envelope.get("purpose") != expected_purpose:
        raise ValueError("unsupported worker envelope")
    try:
        nonce = base64.b64decode(
            str(envelope["nonce"]).encode("ascii"), altchars=b"-_", validate=True
        )
        ciphertext = base64.b64decode(
            str(envelope["ciphertext"]).encode("ascii"), altchars=b"-_", validate=True
        )
    except (KeyError, binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("malformed worker envelope") from exc
    if len(nonce) != 12:
        raise ValueError("malformed worker nonce")
    metadata = {key: value for key, value in envelope.items() if key not in {"nonce", "ciphertext"}}
    return AESGCM(key).decrypt(nonce, ciphertext, _metadata_bytes(metadata))


def _run_ocr(image: Path, languages: str) -> str:
    """Run Tesseract while keeping extracted content out of worker logs."""

    try:
        completed = subprocess.run(
            ["tesseract", str(image), "stdout", "--dpi", "180", "-l", languages],
            check=True,
            capture_output=True,
            text=True,
            timeout=int(os.getenv("OCDD_OCR_PAGE_TIMEOUT_SECONDS", "60")),
        )
    except subprocess.CalledProcessError:
        # The bilingual language pack may not exist on a custom local install.
        return "" if languages == "eng" else _run_ocr(image, "eng")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip()


def ocr_pdf(path: Path) -> list[str]:
    """Render and OCR a scanned PDF when Poppler and Tesseract are available."""

    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        return []
    languages = os.getenv("OCDD_OCR_LANGUAGES", "eng+chi_sim")
    dpi = min(max(int(os.getenv("OCDD_OCR_DPI", "180")), 120), 300)
    with tempfile.TemporaryDirectory(prefix="ocdd-ocr-") as directory:
        prefix = Path(directory) / "page"
        try:
            subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), str(path), str(prefix)],
                check=True,
                capture_output=True,
                timeout=int(os.getenv("OCDD_OCR_DOCUMENT_TIMEOUT_SECONDS", "300")),
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []
        return [_run_ocr(image, languages) for image in sorted(Path(directory).glob("page-*.png"))]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_document(path: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        visible_chars = sum(len(page) for page in pages)
        needs_ocr = visible_chars < max(80, len(pages) * 20)
        ocr_used = False
        if needs_ocr and os.getenv("OCDD_OCR_ENABLED", "true").lower() in {"1", "true", "yes"}:
            ocr_pages = ocr_pdf(path)
            if ocr_pages and any(page.strip() for page in ocr_pages):
                pages = ocr_pages
                needs_ocr = False
                ocr_used = True
        return {
            "sha256": sha256_file(path),
            "media_type": "application/pdf",
            "pages": [{"page": index + 1, "text": text} for index, text in enumerate(pages)],
            "needs_ocr": needs_ocr,
            "ocr_used": ocr_used,
        }
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        languages = os.getenv("OCDD_OCR_LANGUAGES", "eng+chi_sim")
        text = (
            _run_ocr(path, languages)
            if os.getenv("OCDD_OCR_ENABLED", "true").lower() in {"1", "true", "yes"}
            else ""
        )
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }[suffix]
        return {
            "sha256": sha256_file(path),
            "media_type": media_type,
            "pages": [{"page": 1, "text": text}],
            "needs_ocr": not bool(text.strip()),
            "ocr_used": bool(text.strip()),
        }
    if suffix in {".txt", ".md", ".json", ".csv"}:
        return {
            "sha256": sha256_file(path),
            "media_type": "text/plain",
            "pages": [{"page": 1, "text": path.read_text(encoding="utf-8", errors="replace")}],
            "needs_ocr": False,
            "ocr_used": False,
        }
    return {
        "sha256": sha256_file(path),
        "media_type": "application/octet-stream",
        "pages": [],
        "needs_ocr": True,
        "ocr_used": False,
    }


def cleanup_expired_files(root: Path, ttl_seconds: int, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    removed: list[str] = []
    if not root.exists():
        return removed
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if now - path.stat().st_mtime >= ttl_seconds:
            path.unlink(missing_ok=True)
            removed.append(str(path.relative_to(root)))
    return removed


@app.task(name="ocdd.parse_encrypted_artifact")
def parse_encrypted_artifact(envelope: dict[str, object]) -> dict[str, object]:
    """Decrypt, parse and return only an encrypted result envelope.

    The broker sees ciphertext plus media type, suffix and digest. The original
    filename, uploaded bytes and extracted page text are never task arguments,
    return values or log messages in plaintext.
    """

    key = load_envelope_key()
    content = decrypt_envelope(key, envelope, expected_purpose="artifact")
    expected_digest = str(envelope.get("sha256", ""))
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise ValueError("artifact digest mismatch")
    suffix = str(envelope.get("suffix", ""))
    if suffix and not _SUFFIX_RE.fullmatch(suffix):
        raise ValueError("unsafe artifact suffix")

    temp_root = Path(os.getenv("OCDD_WORKER_TMP_DIR", "/tmp/ocdd-worker"))
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_root.chmod(0o700)
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="artifact-",
            suffix=suffix,
            dir=temp_root,
            delete=False,
        ) as handle:
            handle.write(content)
            path = Path(handle.name)
        path.chmod(0o600)
        parsed = extract_document(path)
        if parsed.get("sha256") != expected_digest:
            raise ValueError("parsed artifact digest mismatch")
        return encrypt_envelope(
            key,
            json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            purpose="result",
            metadata={"sha256": expected_digest},
        )
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


@app.task(name="ocdd.purge_transient_artifacts")
def purge_transient_artifacts() -> dict[str, int]:
    root = Path(os.getenv("OCDD_STORAGE_PATH", "./data/local/artifacts"))
    ttl = int(os.getenv("OCDD_ARTIFACT_TTL_SECONDS", "3600"))
    return {"removed": len(cleanup_expired_files(root, ttl))}
