from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import CaseContext, RetentionClass
from app.repository import CaseNotFoundError, SQLiteRepository


def test_sqlite_case_lease_is_exclusive_across_repository_instances(tmp_path) -> None:
    path = tmp_path / "shared.sqlite3"
    first = SQLiteRepository(path)
    second = SQLiteRepository(path)
    case = first.create_case(CaseContext())
    now = datetime.now(timezone.utc)

    assert first.acquire_case_lease(
        case.id,
        token="worker-one",
        expires_at=now + timedelta(minutes=5),
        now=now,
    )
    assert not second.acquire_case_lease(
        case.id,
        token="worker-two",
        expires_at=now + timedelta(minutes=5),
        now=now,
    )
    assert not second.release_case_lease(case.id, token="wrong-owner")
    assert first.release_case_lease(case.id, token="worker-one")
    assert second.acquire_case_lease(
        case.id,
        token="worker-two",
        expires_at=now + timedelta(minutes=5),
        now=now,
    )


def test_expired_lease_can_be_recovered_and_missing_case_is_distinct(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "lease.sqlite3")
    case = repository.create_case(CaseContext())
    start = datetime.now(timezone.utc)
    assert repository.acquire_case_lease(
        case.id,
        token="crashed-worker",
        expires_at=start + timedelta(seconds=1),
        now=start,
    )
    recovered_at = start + timedelta(seconds=2)
    assert repository.acquire_case_lease(
        case.id,
        token="replacement-worker",
        expires_at=recovered_at + timedelta(minutes=5),
        now=recovered_at,
    )
    with pytest.raises(CaseNotFoundError):
        repository.acquire_case_lease(
            "missing-case",
            token="worker",
            expires_at=recovered_at + timedelta(minutes=5),
            now=recovered_at,
        )


def test_expiry_purge_does_not_delete_a_case_with_an_active_lease(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "purge.sqlite3")
    now = datetime.now(timezone.utc)
    case = repository.create_case(
        CaseContext(
            retention_class=RetentionClass.ANONYMOUS,
            expires_at=now - timedelta(seconds=1),
        )
    )
    assert repository.acquire_case_lease(
        case.id,
        token="active-worker",
        expires_at=now + timedelta(minutes=5),
        now=now,
    )

    assert repository.purge_expired_cases(now) == 0
    assert repository.release_case_lease(case.id, token="active-worker")
    assert repository.purge_expired_cases(now) == 1


def test_repository_single_and_case_artifact_deletes(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "artifact-delete.sqlite3")
    case = repository.create_case(CaseContext())
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    for artifact_id in ("one", "two"):
        repository.store_artifact(
            artifact_id=artifact_id,
            case_id=case.id,
            filename=f"{artifact_id}.txt",
            media_type="text/plain",
            content=b"encrypted",
            content_sha256="a" * 64,
            expires_at=expiry,
        )

    assert repository.delete_artifact("one")
    assert not repository.delete_artifact("one")
    assert repository.delete_case_artifacts(case.id) == 1
    assert repository.artifact_count(case.id) == 0
