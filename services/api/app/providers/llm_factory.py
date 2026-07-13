"""Environment factory for the two optional non-OpenAI language adapters."""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from .anthropic import AnthropicLLMProvider
from .llm_common import GroundedLLMProvider, LLMProviderConfigurationError
from .ollama import DEFAULT_OLLAMA_BASE_URL, OllamaLLMProvider


def create_optional_non_openai_llm_provider(
    provider: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> GroundedLLMProvider | None:
    """Build an explicitly selected adapter; no selection means no LLM call."""

    env = os.environ if environ is None else environ
    selected = (provider if provider is not None else env.get("OCDD_LLM_PROVIDER", ""))
    selected = selected.strip().lower()
    if selected in {"", "none", "disabled"}:
        return None
    if selected == "anthropic":
        return AnthropicLLMProvider(
            api_key=env.get("ANTHROPIC_API_KEY", ""),
            model=env.get("OCDD_ANTHROPIC_MODEL", ""),
            transport=transport,
        )
    if selected == "ollama":
        return OllamaLLMProvider(
            model=env.get("OCDD_OLLAMA_MODEL", ""),
            base_url=env.get("OCDD_OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
            api_key=env.get("OLLAMA_API_KEY"),
            transport=transport,
        )
    raise LLMProviderConfigurationError(
        "non-OpenAI LLM provider must be 'anthropic', 'ollama', or disabled"
    )
