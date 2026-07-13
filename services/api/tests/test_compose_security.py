from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_reference_compose_api_and_web_ports_are_loopback_only() -> None:
    for filename in ("docker-compose.yml", "docker-compose.cloud.yml"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert '"127.0.0.1:${OCDD_API_PORT:-8000}:8000"' in text
        assert '"127.0.0.1:${OCDD_WEB_PORT:-3000}:3000"' in text


def test_cloud_document_broker_is_deliberately_non_persistent() -> None:
    text = (ROOT / "docker-compose.cloud.yml").read_text(encoding="utf-8")
    assert '["valkey-server", "--save", "", "--appendonly", "no"]' in text
    assert "redis-data:/data" not in text
    assert "redis-data:" not in text


def test_readme_describes_local_retention_until_case_or_volume_deletion() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "one-hour transient-artifact TTL" not in text
    assert "remain there until the case or Docker volume" in text
