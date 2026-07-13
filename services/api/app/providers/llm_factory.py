"""Environment factory for the optional local Ollama language adapter."""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from .llm_common import GroundedLLMProvider, LLMProviderConfigurationError
from .ollama import DEFAULT_OLLAMA_BASE_URL, OllamaLLMProvider


def create_optional_local_llm_provider(
    provider: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> GroundedLLMProvider | None:
    """Build the explicitly selected free local adapter.

    No selection means no LLM call.  The deterministic application remains
    fully functional without Ollama or any model download.
    """

    env = os.environ if environ is None else environ
    selected = (provider if provider is not None else env.get("OCDD_LLM_PROVIDER", ""))
    selected = selected.strip().lower()
    if selected in {"", "none", "disabled"}:
        return None
    if selected == "ollama":
        return OllamaLLMProvider(
            model=env.get("OCDD_OLLAMA_MODEL", ""),
            base_url=env.get("OCDD_OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
            api_key=env.get("OLLAMA_API_KEY"),
            transport=transport,
        )
    raise LLMProviderConfigurationError(
        "local LLM provider must be 'ollama' or disabled"
    )
