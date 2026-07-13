from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.export import OCDDPackageError, export_case, import_case
from app.models import CaseContext, Evidence, EvidenceKind, SourceEnvelope
from app.repository import SQLiteRepository


def test_encrypted_ocdd_roundtrip_and_wrong_password() -> None:
    source = SourceEnvelope(source_type="test", content_sha256="a" * 64)
    evidence = Evidence(source_id=source.id, kind=EvidenceKind.OTHER, label="fact", excerpt="redacted fact")
    case = CaseContext(sources=[source], evidence=[evidence])
    package = export_case(case, "correct horse battery staple")
    assert package.startswith(b"OCDD1")
    assert b"redacted fact" not in package
    restored, manifest = import_case(package, "correct horse battery staple")
    assert restored == case
    assert manifest["attachments_included"] is False
    assert manifest["schema_version"] == "1.0"
    with pytest.raises(OCDDPackageError, match="invalid passphrase"):
        import_case(package, "wrong password")


def test_repository_ttl_physically_deletes_raw_artifact(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "ttl.sqlite3")
    case = repository.create_case(CaseContext())
    repository.store_artifact(
        artifact_id="expired",
        case_id=case.id,
        filename="hidden.bin",
        media_type="application/octet-stream",
        content=b"private bytes",
        content_sha256="b" * 64,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert repository.purge_expired_artifacts() == 1
    assert repository.get_artifact_bytes("expired") is None
