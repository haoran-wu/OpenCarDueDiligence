"""Optional Ollama adapter for local grounded prose rendering only."""

from __future__ import annotations

from typing import Any

import httpx

from ..plugins import PluginMetadata
from .llm_common import (
    GroundedLLMProvider,
    LLMProviderConfigurationError,
    LLMProviderUnavailable,
    SYSTEM_PROMPT,
)


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def _validated_base_url(value: str, *, has_api_key: bool) -> str:
    try:
        url = httpx.URL(value.strip())
    except (TypeError, ValueError) as exc:
        raise LLMProviderConfigurationError("Ollama base URL is invalid") from exc
    if url.scheme not in {"http", "https"} or not url.host:
        raise LLMProviderConfigurationError("Ollama base URL must use HTTP or HTTPS")
    if url.query or url.fragment or url.path not in {"", "/"}:
        raise LLMProviderConfigurationError(
            "Ollama base URL must not include a path, query, or fragment"
        )
    loopback = url.host in {"localhost", "127.0.0.1", "::1"}
    if has_api_key and url.scheme != "https" and not loopback:
        raise LLMProviderConfigurationError(
            "Ollama credentials require HTTPS for non-loopback servers"
        )
    return str(url).rstrip("/")


class OllamaLLMProvider(GroundedLLMProvider):
    """Language-only local/server adapter with no case mutation capability."""

    metadata = PluginMetadata(
        name="ollama-llm-explainer",
        version="1.0.0",
        license_name="Ollama API; selected model license varies",
        license_url="https://docs.ollama.com/api/introduction",
        access_cost="free",
        credential_storage=(
            "local API needs no credential; optional bearer token is accepted in memory "
            "only and is never persisted or logged"
        ),
        retention_policy=(
            "adapter retains no prompts or responses; server-side retention is controlled "
            "by the configured Ollama runtime"
        ),
        redistribution=(
            "generated narrative follows the selected model license; no model weights "
            "redistributed by this adapter"
        ),
        data_sources=["user-authorized deterministic case facts", "configured Ollama model"],
    )

    def __init__(
        self,
        *,
        model: str,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__()
        if not model.strip():
            raise LLMProviderConfigurationError("Ollama model is required")
        if timeout_seconds <= 0:
            raise LLMProviderConfigurationError("timeout must be positive")
        self._model = model
        self._api_key = api_key.strip() if api_key and api_key.strip() else None
        self._base_url = _validated_base_url(
            base_url,
            has_api_key=self._api_key is not None,
        )
        self._transport = transport
        self._timeout = httpx.Timeout(timeout_seconds)

    async def _generate(self, prompt: str) -> str:
        headers = {
            "Accept": "application/json",
            "User-Agent": "OpenCarDueDiligence/0.1 language-renderer",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
                headers=headers,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/api/generate",
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise LLMProviderUnavailable("Ollama explanation request timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderUnavailable("Ollama explanation request failed") from exc

        if not isinstance(body, dict) or body.get("done") is not True:
            raise LLMProviderUnavailable("Ollama returned an incomplete response")
        rendered = body.get("response")
        if not isinstance(rendered, str) or not rendered.strip():
            raise LLMProviderUnavailable("Ollama response did not contain text")
        return rendered
