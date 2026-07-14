from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_reference_compose_api_and_web_ports_are_loopback_only() -> None:
    for filename in ("docker-compose.yml", "docker-compose.cloud.yml"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert '"127.0.0.1:${OCDD_API_PORT:-8000}:8000"' in text
        assert '"127.0.0.1:${OCDD_WEB_PORT:-3000}:3000"' in text


def test_reference_document_brokers_are_deliberately_non_persistent() -> None:
    for filename in ("docker-compose.yml", "docker-compose.cloud.yml"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert '["valkey-server", "--save", "", "--appendonly", "no"]' in text
        assert "redis-data:/data" not in text
        assert "redis-data:" not in text


def test_reference_workers_use_volatile_temp_storage_and_matching_cleanup_root() -> None:
    for filename in ("docker-compose.yml", "docker-compose.cloud.yml"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert "OCDD_WORKER_TMP_DIR: /tmp/ocdd-worker" in text
        assert "OCDD_STORAGE_PATH: /tmp/ocdd-worker" in text
        assert "/tmp:size=256m,mode=1777" in text
        assert "- --beat" in text


def test_readme_describes_local_retention_until_case_or_volume_deletion() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "one-hour transient-artifact TTL" not in text
    assert "remain there until the case or Docker volume" in text
    assert "forensic wipe of SQLite" in text
