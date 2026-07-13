#!/usr/bin/env python3
"""Fail release checks if an official paid path is reintroduced.

This is intentionally a narrow policy guard, not a license scanner.  It keeps
the official quickstart free of commercial-license files, hosted paid-model
credentials, and the non-open Redis server image while allowing documentation
to describe external transaction costs honestly.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def main() -> int:
    failures: list[str] = []

    forbidden_paths = (
        "COMMERCIAL-LICENSE.md",
        "services/api/app/providers/anthropic.py",
        "services/api/app/providers/openai.py",
    )
    for relative in forbidden_paths:
        if (ROOT / relative).exists():
            failures.append(f"official paid/provider path exists: {relative}")

    readme = _read("README.md")
    for token in ("dual licensed", "separate commercial license"):
        if token in readme.lower():
            failures.append(f"legacy commercial-license wording appears in README: {token}")
    if "FREE_SOFTWARE.md" not in readme:
        failures.append("README must link the free-software commitment")

    provider_dir = ROOT / "services/api/app/providers"
    allowed_provider_modules = {
        "__init__.py",
        "llm_common.py",
        "llm_factory.py",
        "nhtsa.py",
        "ollama.py",
    }
    unexpected_provider_modules = sorted(
        path.name
        for path in provider_dir.glob("*.py")
        if path.name not in allowed_provider_modules
    )
    if unexpected_provider_modules:
        failures.append(
            "provider module is not in the reviewed free-provider allowlist: "
            + ", ".join(unexpected_provider_modules)
        )

    env_example = _read(".env.example")
    for token in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OCDD_ANTHROPIC_MODEL",
        "STRIPE_SECRET_KEY",
    ):
        if token in env_example:
            failures.append(f"paid-service credential appears in .env.example: {token}")
    allowed_key_names = {"OLLAMA_API_KEY"}
    declared_key_names = {
        match.group(1)
        for match in re.finditer(r"(?m)^([A-Z][A-Z0-9_]*(?:API_KEY|SECRET_KEY))=", env_example)
    }
    for key_name in sorted(declared_key_names - allowed_key_names):
        failures.append(f"unreviewed API/secret credential appears in .env.example: {key_name}")

    compose = _read("docker-compose.yml") + _read("docker-compose.cloud.yml")
    if "image: valkey/valkey:" not in compose:
        failures.append("official Compose stack must use the open-source Valkey image")
    if "image: redis:" in compose:
        failures.append("official Compose stack must not use the Redis server image")

    python_policy = _read("services/api/app/plugins.py")
    if 'Literal["free", "user-supplied-artifact"]' not in python_policy:
        failures.append("Python plugin metadata must restrict official access-cost modes")
    sdk_policy = _read("packages/plugin-sdk/src/index.ts")
    if 'accessCost: "free" | "user-supplied-artifact"' not in sdk_policy:
        failures.append("TypeScript plugin SDK must expose the official access-cost modes")

    license_expectations = {
        "package.json": '"license": "AGPL-3.0-or-later"',
        "apps/web/package.json": '"license": "AGPL-3.0-or-later"',
        "apps/extension/package.json": '"license": "AGPL-3.0-or-later"',
        "packages/contracts/package.json": '"license": "AGPL-3.0-or-later"',
        "packages/plugin-sdk/package.json": '"license": "Apache-2.0"',
        "services/api/pyproject.toml": 'license = "AGPL-3.0-or-later"',
        "services/worker/pyproject.toml": 'license = "AGPL-3.0-or-later"',
        "services/obd-bridge/pyproject.toml": 'license = "AGPL-3.0-or-later"',
    }
    for relative, token in license_expectations.items():
        if token not in _read(relative):
            failures.append(f"expected license metadata missing from {relative}")

    version_expectations = (
        ("package.json", '"version": "0.1.0-alpha.3"'),
        ("apps/web/package.json", '"version": "0.1.0-alpha.3"'),
        ("apps/extension/package.json", '"version": "0.1.0-alpha.3"'),
        ("package-lock.json", '"version": "0.1.0-alpha.3"'),
        ("CHANGELOG.md", "## 0.1.0-alpha.3 - 2026-07-13"),
        ("services/api/app/main.py", 'version="0.1.0-alpha.3"'),
        ("apps/extension/public/manifest.json", '"version_name": "0.1.0-alpha.3"'),
        ("apps/extension/public/manifest.json", '"version": "0.1.0.3"'),
        ("packages/contracts/package.json", '"version": "0.1.0-alpha.3"'),
        ("packages/plugin-sdk/package.json", '"version": "0.1.0-alpha.3"'),
        ("services/api/pyproject.toml", 'version = "0.1.0a3"'),
        ("services/worker/pyproject.toml", 'version = "0.1.0a3"'),
        ("services/obd-bridge/pyproject.toml", 'version = "0.1.0a3"'),
        ("services/obd-bridge/obd_bridge/__init__.py", '__version__ = "0.1.0-alpha.3"'),
        ("services/obd-bridge/obd_bridge/service.py", 'version="0.1.0-alpha.3"'),
        ("CITATION.cff", "version: 0.1.0-alpha.3"),
    )
    for relative, token in version_expectations:
        if token not in _read(relative):
            failures.append(f"release version metadata is inconsistent in {relative}")

    if failures:
        print("Free-distribution policy check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Free-distribution policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
