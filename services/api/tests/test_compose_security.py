from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_reference_compose_api_and_web_ports_are_loopback_only() -> None:
    for filename in ("docker-compose.yml", "docker-compose.cloud.yml"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert '"127.0.0.1:${OCDD_API_PORT:-8000}:8000"' in text
        assert '"127.0.0.1:${OCDD_WEB_PORT:-3000}:3000"' in text
