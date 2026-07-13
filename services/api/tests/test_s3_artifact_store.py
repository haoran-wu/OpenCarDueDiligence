from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from threading import Event, Thread
from time import sleep

import pytest
from fastapi.testclient import TestClient

from app.artifact_store import S3ArtifactBatchError, S3ArtifactStore


class _Paginator:
    def __init__(self, client: "FakeS3") -> None:
        self.client = client

    def paginate(self, *, Bucket: str, Prefix: str):  # noqa: N803
        del Bucket
        yield {
            "Contents": [
                {"Key": key}
                for key in sorted(self.client.objects)
                if key.startswith(Prefix)
            ]
        }


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}

    def put_object(self, **kwargs: object) -> None:
        self.objects[str(kwargs["Key"])] = dict(kwargs)

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        value = self.objects[Key]
        return {
            "Body": BytesIO(value["Body"]),
            "Metadata": value["Metadata"],
        }

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        del Bucket
        self.objects.pop(Key, None)

    def head_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        return {"Metadata": self.objects[Key]["Metadata"]}

    def get_paginator(self, name: str) -> _Paginator:
        assert name == "list_objects_v2"
        return _Paginator(self)


class DeleteFailingS3(FakeS3):
    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        del Bucket, Key
        raise RuntimeError("simulated object-store outage")


class BlockingPutS3(FakeS3):
    def __init__(self) -> None:
        super().__init__()
        self.put_started = Event()
        self.allow_put_to_return = Event()

    def put_object(self, **kwargs: object) -> None:
        super().put_object(**kwargs)
        self.put_started.set()
        if not self.allow_put_to_return.wait(timeout=5):
            raise TimeoutError("test did not release blocked S3 upload")


class SelectiveFailingS3(FakeS3):
    def __init__(self) -> None:
        super().__init__()
        self.head_failures: set[str] = set()
        self.delete_failures: set[str] = set()
        self.head_attempts: list[str] = []
        self.delete_attempts: list[str] = []

    def head_object(self, *, Bucket: str, Key: str):  # noqa: N803
        self.head_attempts.append(Key)
        if Key in self.head_failures:
            raise RuntimeError(f"provider exposed sensitive key={Key} metadata={self.objects[Key]['Metadata']}")
        return super().head_object(Bucket=Bucket, Key=Key)

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        self.delete_attempts.append(Key)
        if Key in self.delete_failures:
            raise RuntimeError(f"provider exposed sensitive key={Key} metadata={self.objects[Key]['Metadata']}")
        super().delete_object(Bucket=Bucket, Key=Key)


def _put(
    store: S3ArtifactStore,
    *,
    expires_at: datetime,
    artifact_id: str = "a1",
    case_id: str = "private-case-id",
) -> None:
    store.put(
        artifact_id=artifact_id,
        case_id=case_id,
        filename="owner-name.pdf",
        media_type="application/pdf",
        content=b"private original",
        content_sha256="a" * 64,
        expires_at=expires_at,
    )


def test_s3_artifact_metadata_uses_hashed_case_id_and_no_filename(monkeypatch) -> None:
    monkeypatch.setenv("OCDD_S3_SSE", "AES256")
    client = FakeS3()
    store = S3ArtifactStore(bucket="test", client=client)
    _put(store, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))

    stored = client.objects["ocdd-transient/a1"]
    assert "private-case-id" not in str(stored["Metadata"])
    assert "owner-name" not in str(stored)
    assert stored["ServerSideEncryption"] == "AES256"
    assert stored["Expires"] == stored["Expires"].astimezone(timezone.utc)


def test_s3_expired_original_is_physically_deleted_by_ttl_purge() -> None:
    client = FakeS3()
    store = S3ArtifactStore(bucket="test", client=client)
    now = datetime.now(timezone.utc)
    _put(store, artifact_id="expired", expires_at=now - timedelta(seconds=1))
    _put(store, artifact_id="active", expires_at=now + timedelta(hours=1))

    assert store.purge_expired(now) == 1
    assert "ocdd-transient/expired" not in client.objects
    assert "ocdd-transient/active" in client.objects


def test_s3_purge_continues_after_object_errors_and_raises_sanitized_aggregate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = SelectiveFailingS3()
    store = S3ArtifactStore(bucket="test", client=client)
    now = datetime.now(timezone.utc)
    for artifact_id in ("a-head-fail", "b-success", "c-delete-fail", "d-after-fail"):
        _put(store, artifact_id=artifact_id, expires_at=now - timedelta(seconds=1))
    client.head_failures.add("ocdd-transient/a-head-fail")
    client.delete_failures.add("ocdd-transient/c-delete-fail")

    with pytest.raises(S3ArtifactBatchError) as exc_info:
        store.purge_expired(now)

    assert exc_info.value.operation == "purge_expired"
    assert exc_info.value.failure_count == 2
    assert set(client.objects) == {
        "ocdd-transient/a-head-fail",
        "ocdd-transient/c-delete-fail",
    }
    assert "ocdd-transient/d-after-fail" in client.delete_attempts
    disclosed = f"{exc_info.value} {' '.join(record.getMessage() for record in caplog.records)}"
    assert "a-head-fail" not in disclosed
    assert "c-delete-fail" not in disclosed
    assert "Metadata" not in disclosed
    assert "private-case-id" not in disclosed


def test_s3_get_enforces_ttl_even_before_scheduled_purge() -> None:
    client = FakeS3()
    store = S3ArtifactStore(bucket="test", client=client)
    _put(store, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))

    assert store.get("a1") is None
    assert client.objects == {}


def test_s3_missing_expiry_fails_closed_and_is_deleted() -> None:
    client = FakeS3()
    store = S3ArtifactStore(bucket="test", client=client)
    _put(store, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    client.objects["ocdd-transient/a1"]["Metadata"].pop("expires-at")

    assert store.get("a1") is None
    assert client.objects == {}


def test_s3_rejects_an_original_without_timezone_aware_expiry() -> None:
    client = FakeS3()
    store = S3ArtifactStore(bucket="test", client=client)
    with pytest.raises(ValueError, match="timezone-aware"):
        store.put(
            artifact_id="a1",
            case_id="case",
            filename="private.pdf",
            media_type="application/pdf",
            content=b"private",
            content_sha256="a" * 64,
            expires_at=None,
        )
    assert client.objects == {}


def test_s3_case_delete_removes_only_matching_physical_originals() -> None:
    client = FakeS3()
    store = S3ArtifactStore(bucket="test", client=client)
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    _put(store, artifact_id="case-a-1", case_id="case-a", expires_at=expiry)
    _put(store, artifact_id="case-a-2", case_id="case-a", expires_at=expiry)
    _put(store, artifact_id="case-b-1", case_id="case-b", expires_at=expiry)

    assert store.delete_case("case-a") == 2
    assert set(client.objects) == {"ocdd-transient/case-b-1"}


def test_s3_single_object_delete_is_idempotent() -> None:
    client = FakeS3()
    store = S3ArtifactStore(bucket="test", client=client)
    _put(
        store,
        artifact_id="single",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    assert store.delete("single")
    assert "ocdd-transient/single" not in client.objects
    assert store.delete("single")


def test_s3_case_delete_continues_after_object_errors_and_fails_safely(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = SelectiveFailingS3()
    store = S3ArtifactStore(bucket="test", client=client)
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    for artifact_id in ("a-head-fail", "b-success", "c-delete-fail", "d-after-fail"):
        _put(store, artifact_id=artifact_id, case_id="case-a", expires_at=expiry)
    _put(store, artifact_id="e-other-case", case_id="case-b", expires_at=expiry)
    client.head_failures.add("ocdd-transient/a-head-fail")
    client.delete_failures.add("ocdd-transient/c-delete-fail")

    with pytest.raises(S3ArtifactBatchError) as exc_info:
        store.delete_case("case-a")

    assert exc_info.value.operation == "delete_case"
    assert exc_info.value.failure_count == 2
    assert set(client.objects) == {
        "ocdd-transient/a-head-fail",
        "ocdd-transient/c-delete-fail",
        "ocdd-transient/e-other-case",
    }
    assert "ocdd-transient/d-after-fail" in client.delete_attempts
    assert "ocdd-transient/e-other-case" in client.head_attempts
    disclosed = f"{exc_info.value} {' '.join(record.getMessage() for record in caplog.records)}"
    assert "a-head-fail" not in disclosed
    assert "c-delete-fail" not in disclosed
    assert "Metadata" not in disclosed
    assert "case-a" not in disclosed


def test_api_case_delete_physically_removes_s3_originals(cloud_client: TestClient) -> None:
    s3 = FakeS3()
    store = S3ArtifactStore(bucket="test", client=s3)
    cloud_client.app.state.artifact_store = store
    cloud_client.app.state.artifact_service.artifact_store = store

    created = cloud_client.post("/v1/cases", json={"language": "en"})
    assert created.status_code == 201
    case_id = created.json()["id"]
    access = {"X-OCDD-Case-Token": created.headers["X-OCDD-Case-Token"]}
    uploaded = cloud_client.post(
        f"/v1/cases/{case_id}/artifacts",
        json={
            "filename": "owner-name.txt",
            "kind": "other",
            "mediaType": "text/plain",
            "text": "private original",
        },
        headers=access,
    )
    assert uploaded.status_code == 201, uploaded.text
    assert store.count(case_id) == 1

    deleted = cloud_client.delete(f"/v1/cases/{case_id}", headers=access)
    assert deleted.status_code == 204
    assert s3.objects == {}


def test_api_keeps_case_capability_when_s3_case_delete_fails(
    cloud_client: TestClient,
) -> None:
    s3 = DeleteFailingS3()
    store = S3ArtifactStore(bucket="test", client=s3)
    cloud_client.app.state.artifact_store = store
    cloud_client.app.state.artifact_service.artifact_store = store

    created = cloud_client.post("/v1/cases", json={"language": "en"})
    case_id = created.json()["id"]
    access = {"X-OCDD-Case-Token": created.headers["X-OCDD-Case-Token"]}
    uploaded = cloud_client.post(
        f"/v1/cases/{case_id}/artifacts",
        json={
            "filename": "private.txt",
            "kind": "other",
            "mediaType": "text/plain",
            "text": "private original",
        },
        headers=access,
    )
    assert uploaded.status_code == 201

    failed = cloud_client.delete(f"/v1/cases/{case_id}", headers=access)
    assert failed.status_code == 503
    assert failed.json()["detail"] == (
        "transient originals could not be deleted; retry case deletion"
    )
    assert cloud_client.get(f"/v1/cases/{case_id}", headers=access).status_code == 200


def test_concurrent_upload_finishes_before_delete_and_leaves_no_s3_object(
    cloud_client: TestClient,
) -> None:
    s3 = BlockingPutS3()
    store = S3ArtifactStore(bucket="test", client=s3)
    cloud_client.app.state.artifact_store = store
    cloud_client.app.state.artifact_service.artifact_store = store
    cloud_client.app.state.case_lease_wait_seconds = 3

    created = cloud_client.post("/v1/cases", json={"language": "en"})
    case_id = created.json()["id"]
    access = {"X-OCDD-Case-Token": created.headers["X-OCDD-Case-Token"]}
    responses: dict[str, object] = {}

    def upload() -> None:
        responses["upload"] = cloud_client.post(
            f"/v1/cases/{case_id}/artifacts",
            json={
                "filename": "private.txt",
                "kind": "other",
                "mediaType": "text/plain",
                "text": "private original",
            },
            headers=access,
        )

    def delete() -> None:
        responses["delete"] = cloud_client.delete(
            f"/v1/cases/{case_id}", headers=access
        )

    upload_thread = Thread(target=upload)
    upload_thread.start()
    assert s3.put_started.wait(timeout=2)
    delete_thread = Thread(target=delete)
    delete_thread.start()
    sleep(0.1)
    assert delete_thread.is_alive(), "delete should wait for the upload's database lease"
    s3.allow_put_to_return.set()
    upload_thread.join(timeout=5)
    delete_thread.join(timeout=5)

    assert not upload_thread.is_alive()
    assert not delete_thread.is_alive()
    assert responses["upload"].status_code == 201  # type: ignore[union-attr]
    assert responses["delete"].status_code == 204  # type: ignore[union-attr]
    assert s3.objects == {}


def test_upload_compensates_s3_object_when_case_save_fails(
    cloud_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = FakeS3()
    store = S3ArtifactStore(bucket="test", client=s3)
    cloud_client.app.state.artifact_store = store
    cloud_client.app.state.artifact_service.artifact_store = store
    created = cloud_client.post("/v1/cases", json={"language": "en"})
    case_id = created.json()["id"]
    access = {"X-OCDD-Case-Token": created.headers["X-OCDD-Case-Token"]}

    def fail_save(_case: object) -> None:
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(cloud_client.app.state.repository, "save_case", fail_save)
    response = cloud_client.post(
        f"/v1/cases/{case_id}/artifacts",
        json={
            "filename": "private.txt",
            "kind": "other",
            "mediaType": "text/plain",
            "text": "private original",
        },
        headers=access,
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "artifact metadata could not be saved; upload was rolled back"
    )
    assert s3.objects == {}
