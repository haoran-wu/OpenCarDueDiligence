from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from app.plugins import LLMProvider, validate_plugin_metadata
from app.providers.llm_common import (
    LLMOutputRejected,
    LLMProviderConfigurationError,
    LLMProviderUnavailable,
)
from app.providers.llm_factory import create_optional_local_llm_provider
from app.providers.ollama import OllamaLLMProvider


def _run(provider: LLMProvider, facts: dict[str, object], language: str = "en") -> str:
    return asyncio.run(provider.explain(facts, language))


def _ollama_transport(response_text: str) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"done": True, "done_reason": "stop", "response": response_text},
        )
    )


def test_ollama_renders_only_grounded_facts_without_mutating_input() -> None:
    facts: dict[str, object] = {
        "decision": "NEGOTIATE",
        "opening": 5200,
        "absCoverage": "UNKNOWN",
    }
    original = deepcopy(facts)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://127.0.0.1:11434/api/generate"
        payload = json.loads(request.read())
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0
        assert "<deterministic_facts>" in payload["prompt"]
        assert "NEGOTIATE" in payload["prompt"]
        assert "5200" in payload["prompt"]
        assert "UNKNOWN" in payload["prompt"]
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "response": (
                    "The deterministic decision is NEGOTIATE and the opening "
                    "is $5,200. ABS coverage is UNKNOWN."
                ),
            },
        )

    provider = OllamaLLMProvider(
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    rendered = _run(provider, facts)

    assert rendered.endswith("ABS coverage is UNKNOWN.")
    assert facts == original
    assert isinstance(provider, LLMProvider)
    validate_plugin_metadata(provider.metadata)
    assert provider.metadata.access_cost == "free"
    assert "in memory only" in provider.metadata.credential_storage
    assert "retains no prompts" in provider.metadata.retention_policy


@pytest.mark.parametrize(
    ("facts", "generated", "message"),
    [
        (
            {"decision": "NEGOTIATE", "opening": 5200},
            "The opening is $5,300.",
            "numeric value",
        ),
        (
            {"decision": "INSPECT", "opening": 5200},
            "This is a BUY_CANDIDATE at $5,200.",
            "protected decision",
        ),
        (
            {"decision": "INSPECT", "ownerCount": 2},
            "There are three owners.",
            "spelled an unsupported number",
        ),
        (
            {"decision": "INSPECT", "ownerCount": 2},
            "共有三任车主。",
            "spelled an unsupported number",
        ),
    ],
)
def test_ollama_rejects_prose_that_changes_facts(
    facts: dict[str, object], generated: str, message: str
) -> None:
    provider = OllamaLLMProvider(
        model="test-model",
        transport=_ollama_transport(generated),
    )

    with pytest.raises(LLMOutputRejected, match=message):
        _run(provider, facts)


def test_ollama_fails_closed_for_missing_model_and_http_errors() -> None:
    with pytest.raises(LLMProviderConfigurationError, match="model"):
        OllamaLLMProvider(model="")

    secret = "must-not-appear"
    provider = OllamaLLMProvider(
        model="test-model",
        base_url="https://ollama.example",
        api_key=secret,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"error": "denied"})
        ),
    )
    with pytest.raises(LLMProviderUnavailable) as captured:
        _run(provider, {"decision": "INSPECT"})
    assert secret not in str(captured.value)


def test_decision_validation_does_not_confuse_inspect_first_with_inspect() -> None:
    provider = OllamaLLMProvider(
        model="test-model",
        transport=_ollama_transport("Decision: INSPECT."),
    )
    with pytest.raises(LLMOutputRejected, match="protected decision"):
        _run(provider, {"decision": "INSPECT_FIRST"})


def test_ollama_uses_non_streaming_api_and_validates_grounded_chinese() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://127.0.0.1:11434/api/generate"
        assert "Authorization" not in request.headers
        payload = json.loads(request.read())
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0
        assert "Simplified Chinese" in payload["prompt"]
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "response": "确定性决策为 INSPECT；记录的报价为 $5,200。",
            },
        )

    provider = OllamaLLMProvider(
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    rendered = _run(
        provider,
        {"decision": "INSPECT", "documentedOffer": 5200},
        "zh-CN",
    )

    assert rendered == "确定性决策为 INSPECT；记录的报价为 $5,200。"
    assert isinstance(provider, LLMProvider)
    validate_plugin_metadata(provider.metadata)
    assert "model license varies" in provider.metadata.license_name


def test_ollama_cloud_bearer_requires_https_and_is_sent_only_when_configured() -> None:
    with pytest.raises(LLMProviderConfigurationError, match="require HTTPS"):
        OllamaLLMProvider(
            model="test-model",
            base_url="http://example.com",
            api_key="secret",
        )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://ollama.example/api/generate"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json={"done": True, "response": "Status is UNKNOWN."})

    provider = OllamaLLMProvider(
        model="test-model",
        base_url="https://ollama.example",
        api_key="secret",
        transport=httpx.MockTransport(handler),
    )
    assert _run(provider, {"status": "UNKNOWN"}) == "Status is UNKNOWN."


def test_ollama_rejects_incomplete_response_and_invalid_language() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"done": False, "response": "partial"})

    provider = OllamaLLMProvider(
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMProviderConfigurationError, match="language"):
        _run(provider, {"decision": "INSPECT"}, "fr")
    assert called is False

    with pytest.raises(LLMProviderUnavailable, match="incomplete"):
        _run(provider, {"decision": "INSPECT"})


def test_environment_factory_is_disabled_by_default_and_local_only() -> None:
    assert create_optional_local_llm_provider(environ={}) is None
    assert create_optional_local_llm_provider(
        environ={"OCDD_LLM_PROVIDER": "disabled"}
    ) is None

    with pytest.raises(LLMProviderConfigurationError, match="model"):
        create_optional_local_llm_provider(
            environ={"OCDD_LLM_PROVIDER": "ollama"}
        )
    with pytest.raises(LLMProviderConfigurationError, match="must be"):
        create_optional_local_llm_provider(provider="anthropic", environ={})
    with pytest.raises(LLMProviderConfigurationError, match="must be"):
        create_optional_local_llm_provider(provider="unsupported", environ={})
