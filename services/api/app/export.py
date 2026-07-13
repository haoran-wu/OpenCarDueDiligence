"""Encrypted, integrity-checked .ocdd case package export/import."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .models import CaseContext


MAGIC = b"OCDD1"
ASSOCIATED_DATA = b"OpenCarDueDiligence.case.v1"
SCHEMA_VERSION = "1.0"
MAX_PACKAGE_FILES = 3
MAX_ENTRY_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 12 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


class OCDDPackageError(ValueError):
    pass


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 8:
        raise OCDDPackageError("passphrase must contain at least 8 characters")
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(passphrase.encode("utf-8"))


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def export_case(case: CaseContext, passphrase: str) -> bytes:
    case_bytes = case.model_dump_json(by_alias=False, indent=2).encode("utf-8")
    evidence_bytes = json.dumps(
        [item.model_dump(mode="json", by_alias=False) for item in case.evidence],
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case.id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "attachments_included": False,
        "encryption": "AES-256-GCM",
        "kdf": "scrypt-n16384-r8-p1",
        "files": {
            "case.json": _sha(case_bytes),
            "evidence/evidence.json": _sha(evidence_bytes),
        },
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        bundle.writestr("case.json", case_bytes)
        bundle.writestr("evidence/evidence.json", evidence_bytes)
    salt, nonce = os.urandom(16), os.urandom(12)
    cipher = AESGCM(_derive_key(passphrase, salt)).encrypt(nonce, archive.getvalue(), ASSOCIATED_DATA)
    return MAGIC + salt + nonce + cipher


def import_case(package: bytes, passphrase: str) -> tuple[CaseContext, dict[str, object]]:
    if len(package) < len(MAGIC) + 16 + 12 + 16 or not package.startswith(MAGIC):
        raise OCDDPackageError("not a supported encrypted .ocdd package")
    offset = len(MAGIC)
    salt = package[offset : offset + 16]
    nonce = package[offset + 16 : offset + 28]
    ciphertext = package[offset + 28 :]
    try:
        archive_bytes = AESGCM(_derive_key(passphrase, salt)).decrypt(
            nonce, ciphertext, ASSOCIATED_DATA
        )
    except Exception as exc:  # cryptography intentionally hides auth failure detail
        raise OCDDPackageError("invalid passphrase or package integrity failure") from exc

    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as bundle:
            required = {"manifest.json", "case.json", "evidence/evidence.json"}
            infos = bundle.infolist()
            names = {item.filename for item in infos}
            if len(infos) != MAX_PACKAGE_FILES or names != required:
                raise OCDDPackageError("package must contain exactly the v1 manifest and case files")
            total_uncompressed = 0
            for info in infos:
                if info.is_dir() or info.file_size > MAX_ENTRY_UNCOMPRESSED_BYTES:
                    raise OCDDPackageError("package entry exceeds the v1 extraction limit")
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
                    raise OCDDPackageError("package exceeds the v1 total extraction limit")
                if info.file_size and (
                    info.compress_size == 0
                    or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
                ):
                    raise OCDDPackageError("package compression ratio is unsafe")
            manifest = json.loads(bundle.read("manifest.json"))
            if manifest.get("schema_version") != SCHEMA_VERSION:
                raise OCDDPackageError("unsupported .ocdd schema version")
            for name, expected in manifest.get("files", {}).items():
                if name not in names or _sha(bundle.read(name)) != expected:
                    raise OCDDPackageError(f"integrity check failed for {name}")
            case = CaseContext.model_validate_json(bundle.read("case.json"))
            evidence = json.loads(bundle.read("evidence/evidence.json"))
            if evidence != [item.model_dump(mode="json", by_alias=False) for item in case.evidence]:
                raise OCDDPackageError("evidence ledger does not match case.json")
    except zipfile.BadZipFile as exc:
        raise OCDDPackageError("decrypted content is not a valid .ocdd archive") from exc
    return case, manifest
