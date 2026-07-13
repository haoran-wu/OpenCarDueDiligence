"""Optional Anthropic Messages API adapter for grounded prose rendering only."""

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


ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicLLMProvider(GroundedLLMProvider):
    """Language-only adapter; it cannot write back to a case or decision model."""

    metadata = PluginMetadata(
        name="anthropic-llm-explainer",
        version="1.0.0",
        license_name="Anthropic Commercial Terms",
        license_url="https://www.anthropic.com/legal/commercial-terms",
        credential_storage=(
            "ANTHROPIC_API_KEY is accepted in memory only and is never persisted or logged"
        ),
        retention_policy=(
            "adapter retains no prompts or responses; service-side retention follows the "
            "customer's Anthropic account and contract"
        ),
        redistribution=(
            "generated narrative only; no Anthropic model weights or training data redistributed"
        ),
        data_sources=["user-authorized deterministic case facts", "Anthropic Messages API"],
    )

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 30.0,
        max_tokens: int = 800,
    ) -> None:
        super().__init__()
        if not api_key.strip():
            raise LLMProviderConfigurationError("Anthropic API key is required")
        if not model.strip():
            raise LLMProviderConfigurationError("Anthropic model is required")
        if not 64 <= max_tokens <= 4096:
            raise LLMProviderConfigurationError(
                "Anthropic max_tokens must be between 64 and 4096"
            )
        if timeout_seconds <= 0:
            raise LLMProviderConfigurationError("timeout must be positive")
        self._api_key = api_key
        self._model = model
        self._transport = transport
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_tokens = max_tokens

    async def _generate(self, prompt: str) -> str:
        headers = {
            "Accept": "application/json",
            "anthropic-version": ANTHROPIC_API_VERSION,
            "x-api-key": self._api_key,
            "User-Agent": "OpenCarDueDiligence/0.1 language-renderer",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
                headers=headers,
            ) as client:
                response = await client.post(ANTHROPIC_MESSAGES_URL, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise LLMProviderUnavailable("Anthropic explanation request timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderUnavailable("Anthropic explanation request failed") from exc

        if not isinstance(body, dict):
            raise LLMProviderUnavailable("Anthropic returned an unexpected response")
        if body.get("stop_reason") == "max_tokens":
            raise LLMProviderUnavailable("Anthropic explanation was truncated")
        content = body.get("content")
        if not isinstance(content, list):
            raise LLMProviderUnavailable("Anthropic response did not contain text")
        text_blocks = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        rendered = "\n".join(part.strip() for part in text_blocks if part.strip())
        if not rendered:
            raise LLMProviderUnavailable("Anthropic response did not contain text")
        return rendered
