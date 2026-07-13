"""Document extraction backends.

The Celery backend never places an uploaded document or extracted text on the
broker/result backend in plaintext.  Both directions use a short-lived
AES-256-GCM envelope; only non-sensitive parsing metadata is visible.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pypdf import PdfReader


ENVELOPE_VERSION = 1
_SUFFIX_RE = re.compile(r"^\.[a-z0-9]{1,9}$")


class DocumentProcessingUnavailable(RuntimeError):
    """The configured document processor could not complete the request."""


class DocumentProcessor(Protocol):
    def extract_pages(
        self,
        content: bytes,
        *,
        media_type: str,
        filename: str,
        content_sha256: str,
    ) -> list[str]: ...


def load_envelope_key(value: str | None = None) -> bytes:
    """Load an explicitly configured 32-byte shared key.

    No key is generated implicitly: Celery mode must fail closed if API and
    worker were not intentionally configured with the same secret.
    """

    encoded = value if value is not None else os.getenv("OCDD_WORKER_ENVELOPE_KEY")
    if not encoded:
        raise RuntimeError(
            "OCDD_WORKER_ENVELOPE_KEY is required when OCDD_DOCUMENT_PROCESSOR=celery"
        )
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


def _safe_suffix(media_type: str, filename: str) -> str:
    if media_type == "application/pdf":
        return ".pdf"
    if media_type.startswith("text/"):
        candidate = Path(filename).suffix.lower()
        return candidate if _SUFFIX_RE.fullmatch(candidate) else ".txt"
    candidate = Path(filename).suffix.lower()
    return candidate if _SUFFIX_RE.fullmatch(candidate) else ""


class InlineDocumentProcessor:
    def extract_pages(
        self,
        content: bytes,
        *,
        media_type: str,
        filename: str,
        content_sha256: str,
    ) -> list[str]:
        del content_sha256
        if media_type == "application/pdf" or filename.lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
            if not any(page for page in pages):
                raise DocumentProcessingUnavailable(
                    "PDF has no extractable text; enable the Celery OCR worker or upload OCR text"
                )
            return pages
        if media_type.startswith("text/") or filename.lower().endswith((".txt", ".csv", ".json")):
            return [content.decode("utf-8", errors="replace")]
        return []


class CeleryDocumentProcessor:
    def __init__(
        self,
        *,
        broker_url: str,
        envelope_key: bytes,
        timeout_seconds: float = 45.0,
        celery_client: Any | None = None,
    ) -> None:
        if len(envelope_key) != 32:
            raise ValueError("worker envelope key must be exactly 32 bytes")
        if timeout_seconds <= 0:
            raise ValueError("worker timeout must be positive")
        if celery_client is None:
            try:
                from celery import Celery
            except ImportError as exc:  # pragma: no cover - container dependency guard
                raise RuntimeError("install celery to use OCDD_DOCUMENT_PROCESSOR=celery") from exc
            celery_client = Celery("ocdd_api_documents", broker=broker_url, backend=broker_url)
            celery_client.conf.update(
                task_serializer="json",
                result_serializer="json",
                accept_content=["json"],
                result_expires=300,
            )
        self.client = celery_client
        self.key = envelope_key
        self.timeout_seconds = timeout_seconds

    def extract_pages(
        self,
        content: bytes,
        *,
        media_type: str,
        filename: str,
        content_sha256: str,
    ) -> list[str]:
        if hashlib.sha256(content).hexdigest() != content_sha256:
            raise ValueError("document digest mismatch before worker dispatch")
        request_envelope = encrypt_envelope(
            self.key,
            content,
            purpose="artifact",
            metadata={
                "suffix": _safe_suffix(media_type, filename),
                "sha256": content_sha256,
            },
        )
        result_handle: Any | None = None
        try:
            result_handle = self.client.send_task(
                "ocdd.parse_encrypted_artifact",
                kwargs={"envelope": request_envelope},
                kwargsrepr="{'envelope': '[AES-256-GCM ciphertext]'}",
            )
            encrypted_result = result_handle.get(timeout=self.timeout_seconds)
            result_bytes = decrypt_envelope(
                self.key,
                encrypted_result,
                expected_purpose="result",
            )
            parsed = json.loads(result_bytes)
            if parsed.get("sha256") != content_sha256:
                raise ValueError("worker result digest mismatch")
            needs_ocr = parsed.get("needs_ocr")
            ocr_used = parsed.get("ocr_used")
            if not isinstance(needs_ocr, bool) or not isinstance(ocr_used, bool):
                raise ValueError("worker result is missing OCR status")
            pages = parsed.get("pages")
            if not isinstance(pages, list):
                raise ValueError("worker result is missing pages")
            normalized: list[str] = []
            for page in pages:
                if not isinstance(page, dict) or not isinstance(page.get("text"), str):
                    raise ValueError("worker returned an invalid page")
                normalized.append(page["text"])
            if needs_ocr or not any(page.strip() for page in normalized):
                raise DocumentProcessingUnavailable(
                    "document worker could not extract usable text; OCR is required or failed"
                )
            return normalized
        except DocumentProcessingUnavailable:
            if result_handle is not None:
                try:
                    result_handle.revoke(terminate=False)
                except Exception:
                    pass
            raise
        except (ValueError, json.JSONDecodeError) as exc:
            raise DocumentProcessingUnavailable("document worker returned an invalid result") from exc
        except Exception as exc:
            # Celery intentionally stays a lazy dependency. Broker connection
            # errors, timeouts and remote task failures all become an explicit
            # service-unavailable response instead of a silent empty parse.
            if result_handle is not None:
                try:
                    result_handle.revoke(terminate=False)
                except Exception:
                    pass
            raise DocumentProcessingUnavailable(
                "document worker is unavailable; the upload was not accepted"
            ) from exc


def create_document_processor(mode: str | None = None) -> DocumentProcessor:
    selected = (mode or os.getenv("OCDD_DOCUMENT_PROCESSOR", "inline")).strip().lower()
    if selected == "inline":
        return InlineDocumentProcessor()
    if selected != "celery":
        raise RuntimeError("OCDD_DOCUMENT_PROCESSOR must be 'inline' or 'celery'")
    return CeleryDocumentProcessor(
        broker_url=os.getenv("OCDD_REDIS_URL", "redis://localhost:6379/0"),
        envelope_key=load_envelope_key(),
        timeout_seconds=float(os.getenv("OCDD_DOCUMENT_PROCESSOR_TIMEOUT_SECONDS", "45")),
    )
