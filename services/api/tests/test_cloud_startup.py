from __future__ import annotations

from pathlib import Path

import pytest

from app.main import create_app


def _clear_cloud_storage_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OCDD_DATABASE_URL",
        "OCDD_DATABASE_PATH",
        "OCDD_S3_BUCKET",
        "OCDD_S3_ENDPOINT_URL",
        "OCDD_S3_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_environment_configured_cloud_fails_closed_without_s3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_storage_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(
        ValueError,
        match="cloud deployment requires OCDD_S3_BUCKET",
    ):
        create_app(deployment_mode="cloud")


def test_explicit_test_database_can_use_cloud_repository_fallback(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "isolated-cloud-test.sqlite3",
        deployment_mode="cloud",
    )

    assert app.state.cloud_artifact_fallback is True


def test_explicit_cloud_database_can_disable_test_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_storage_environment(monkeypatch)

    with pytest.raises(
        ValueError,
        match="cloud deployment requires OCDD_S3_BUCKET",
    ):
        create_app(
            database_path=tmp_path / "must-not-fallback.sqlite3",
            deployment_mode="cloud",
            allow_cloud_artifact_fallback=False,
        )
