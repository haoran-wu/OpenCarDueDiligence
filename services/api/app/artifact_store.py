"""Injectable raw artifact stores with TTL and encryption at rest."""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .repository import CaseRepository


class S3ArtifactBatchError(RuntimeError):
    """Sanitized aggregate error for a multi-object S3 operation.

    Object keys, metadata, provider messages, and case identifiers are
    deliberately excluded so callers can safely report the exception class or
    message without leaking transient-artifact locators.
    """

    def __init__(self, operation: str, failure_count: int) -> None:
        self.operation = operation
        self.failure_count = failure_count
        super().__init__(f"{operation} failed for {failure_count} object(s)")


class TransientArtifactStore(Protocol):
    def put(
        self,
        *,
        artifact_id: str,
        case_id: str,
        filename: str,
        media_type: str,
        content: bytes,
        content_sha256: str,
        expires_at: datetime | None,
    ) -> None: ...

    def get(self, artifact_id: str) -> bytes | None: ...
    def delete(self, artifact_id: str) -> bool: ...
    def delete_case(self, case_id: str) -> int: ...
    def purge_expired(self, now: datetime | None = None) -> int: ...
    def count(self, case_id: str | None = None) -> int: ...


def _load_or_create_key(key_file: Path | None = None) -> bytes:
    encoded = os.getenv("OCDD_ARTIFACT_KEY")
    if encoded:
        try:
            key = base64.urlsafe_b64decode(encoded)
        except ValueError as exc:
            raise ValueError("OCDD_ARTIFACT_KEY is not URL-safe base64") from exc
        if len(key) != 32:
            raise ValueError("OCDD_ARTIFACT_KEY must decode to exactly 32 bytes")
        return key
    if key_file is None:
        return AESGCM.generate_key(bit_length=256)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        key = key_file.read_bytes()
        if len(key) != 32:
            raise ValueError(f"invalid artifact key file: {key_file}")
        return key
    key = AESGCM.generate_key(bit_length=256)
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    return key


class EncryptedRepositoryArtifactStore:
    """AES-GCM envelope over a repository's local/fallback blob table."""

    def __init__(self, repository: CaseRepository, *, key_file: Path | None = None) -> None:
        self.repository = repository
        self.key_file = key_file
        self._key: bytes | None = None

    @property
    def key(self) -> bytes:
        if self._key is None:
            self._key = _load_or_create_key(self.key_file)
        return self._key

    def put(
        self,
        *,
        artifact_id: str,
        case_id: str,
        filename: str,
        media_type: str,
        content: bytes,
        content_sha256: str,
        expires_at: datetime | None,
    ) -> None:
        nonce = os.urandom(12)
        associated = f"{artifact_id}:{case_id}:{content_sha256}".encode()
        ciphertext = AESGCM(self.key).encrypt(nonce, content, associated)
        envelope = associated + b"\0" + nonce + ciphertext
        self.repository.store_artifact(
            artifact_id=artifact_id,
            case_id=case_id,
            filename=filename,
            media_type=media_type,
            content=envelope,
            content_sha256=content_sha256,
            expires_at=expires_at,
        )

    def get(self, artifact_id: str) -> bytes | None:
        envelope = self.repository.get_artifact_bytes(artifact_id)
        if envelope is None:
            return None
        associated, payload = envelope.split(b"\0", 1)
        nonce, ciphertext = payload[:12], payload[12:]
        return AESGCM(self.key).decrypt(nonce, ciphertext, associated)

    def delete(self, artifact_id: str) -> bool:
        return self.repository.delete_artifact(artifact_id)

    def delete_case(self, case_id: str) -> int:
        return self.repository.delete_case_artifacts(case_id)

    def purge_expired(self, now: datetime | None = None) -> int:
        return self.repository.purge_expired_artifacts(now)

    def count(self, case_id: str | None = None) -> int:
        return self.repository.artifact_count(case_id)


class S3ArtifactStore:
    """S3-compatible transient store for cloud originals.

    Objects carry an expiry timestamp. Standard S3 lifecycle expiration has
    day-level granularity, so the cloud reference runs ``purge_expired`` in a
    separate short-interval sidecar. Reads fail closed when expiry metadata is
    missing or malformed, and case deletion scans the dedicated transient
    prefix for the matching opaque case hash.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "ocdd-transient",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        client: object | None = None,
    ) -> None:
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise RuntimeError("install the 'cloud' extra to use S3ArtifactStore") from exc
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=region_name,
                config=Config(
                    connect_timeout=int(os.getenv("OCDD_S3_CONNECT_TIMEOUT_SECONDS", "5")),
                    read_timeout=int(os.getenv("OCDD_S3_READ_TIMEOUT_SECONDS", "10")),
                    retries={
                        "max_attempts": int(os.getenv("OCDD_S3_MAX_ATTEMPTS", "3")),
                        "mode": "standard",
                    },
                ),
            )
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, artifact_id: str) -> str:
        return f"{self.prefix}/{artifact_id}"

    @staticmethod
    def _expiry_from_metadata(metadata: dict[str, str] | None) -> datetime | None:
        value = (metadata or {}).get("expires-at")
        if not value or value == "none":
            return None
        try:
            expiry = datetime.fromisoformat(value)
        except ValueError:
            return None
        if expiry.tzinfo is None:
            return None
        return expiry.astimezone(timezone.utc)

    def _iter_keys(self):  # type: ignore[no-untyped-def]
        paginator = self.client.get_paginator("list_objects_v2")  # type: ignore[attr-defined]
        for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{self.prefix}/"):
            for item in page.get("Contents", []):
                key = item.get("Key")
                if isinstance(key, str):
                    yield key

    def put(
        self,
        *,
        artifact_id: str,
        case_id: str,
        filename: str,
        media_type: str,
        content: bytes,
        content_sha256: str,
        expires_at: datetime | None,
    ) -> None:
        if expires_at is None or expires_at.tzinfo is None:
            raise ValueError("S3 transient originals require a timezone-aware expires_at")
        expires_at = expires_at.astimezone(timezone.utc)
        metadata = {
            "case-id-hash": hashlib.sha256(case_id.encode()).hexdigest(),
            "sha256": content_sha256,
            "expires-at": expires_at.isoformat(),
        }
        kwargs = {
            "Bucket": self.bucket,
            "Key": self._key(artifact_id),
            "Body": content,
            "ContentType": media_type,
            "Metadata": metadata,
            # HTTP Expires is advisory and does not delete the object. The
            # independent purger uses the recorded metadata above as authority.
            "Expires": expires_at,
            "ServerSideEncryption": os.getenv("OCDD_S3_SSE", "AES256"),
        }
        kms_key = os.getenv("OCDD_S3_KMS_KEY_ID") or os.getenv("OCDD_KMS_KEY_ID")
        if kms_key:
            kwargs["ServerSideEncryption"] = "aws:kms"
            kwargs["SSEKMSKeyId"] = kms_key
        self.client.put_object(**kwargs)  # type: ignore[attr-defined]

    def get(self, artifact_id: str) -> bytes | None:
        key = self._key(artifact_id)
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)  # type: ignore[attr-defined]
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                return None
            raise
        expires_at = self._expiry_from_metadata(head.get("Metadata"))
        # The prefix is dedicated to transient originals. Missing or invalid
        # expiry metadata must never turn an upload into an indefinite object.
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            self.client.delete_object(Bucket=self.bucket, Key=key)  # type: ignore[attr-defined]
            return None
        response = self.client.get_object(Bucket=self.bucket, Key=key)  # type: ignore[attr-defined]
        return response["Body"].read()

    def delete(self, artifact_id: str) -> bool:
        # S3 DELETE is intentionally idempotent. A successful response means
        # the key is absent afterward even when it did not exist beforehand.
        self.client.delete_object(  # type: ignore[attr-defined]
            Bucket=self.bucket,
            Key=self._key(artifact_id),
        )
        return True

    def purge_expired(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        deleted = 0
        if now.tzinfo is None:
            raise ValueError("purge time must include a timezone")
        now = now.astimezone(timezone.utc)
        try:
            keys = list(self._iter_keys())
        except Exception:
            raise S3ArtifactBatchError("purge_expired", 1) from None
        failures = 0
        for key in keys:
            try:
                head = self.client.head_object(Bucket=self.bucket, Key=key)  # type: ignore[attr-defined]
                expires_at = self._expiry_from_metadata(head.get("Metadata"))
                if expires_at is None or expires_at <= now:
                    self.client.delete_object(Bucket=self.bucket, Key=key)  # type: ignore[attr-defined]
                    deleted += 1
            except Exception:
                # Continue so one corrupt/unavailable object cannot prevent
                # other expired originals from being physically deleted. Do
                # not log the provider exception, key, or object metadata.
                failures += 1
        if failures:
            raise S3ArtifactBatchError("purge_expired", failures) from None
        return deleted

    def delete_case(self, case_id: str) -> int:
        """Physically delete originals belonging to ``case_id`` immediately.

        S3 has no metadata-search API, so this scans only the dedicated
        transient prefix and compares a SHA-256 case capability label. The raw
        case ID never appears in an object key or metadata.
        """

        expected = hashlib.sha256(case_id.encode()).hexdigest()
        deleted = 0
        try:
            keys = list(self._iter_keys())
        except Exception:
            raise S3ArtifactBatchError("delete_case", 1) from None
        failures = 0
        for key in keys:
            try:
                head = self.client.head_object(Bucket=self.bucket, Key=key)  # type: ignore[attr-defined]
                if head.get("Metadata", {}).get("case-id-hash") != expected:
                    continue
                self.client.delete_object(Bucket=self.bucket, Key=key)  # type: ignore[attr-defined]
                deleted += 1
            except Exception:
                # A failed object remains for retry, but later objects are
                # still processed. The aggregate error below is intentionally
                # free of keys, metadata, provider text, and the case ID.
                failures += 1
        if failures:
            raise S3ArtifactBatchError("delete_case", failures) from None
        return deleted

    def count(self, case_id: str | None = None) -> int:
        # Case IDs are intentionally hashed in object metadata and are not used
        # for listing. This operation is diagnostic only.
        count = 0
        expected = hashlib.sha256(case_id.encode()).hexdigest() if case_id else None
        for key in self._iter_keys():
            if expected:
                head = self.client.head_object(Bucket=self.bucket, Key=key)  # type: ignore[attr-defined]
                if head.get("Metadata", {}).get("case-id-hash") != expected:
                    continue
            count += 1
        return count
