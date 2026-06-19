from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jobagent_v2.llm_client import (
    LLMConfig,
    LLMUnavailableError,
    SemanticLLMClient,
    openai_structured_transport,
)


def valid_payload() -> dict[str, object]:
    return {"ok": True}


class FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class FakeClient:
    def __init__(self, responses: FakeResponses, **kwargs: object) -> None:
        self.responses = responses
        self.kwargs = kwargs


def test_openai_request_uses_strict_json_schema_and_parses_output() -> None:
    responses = FakeResponses(json.dumps(valid_payload()))
    created: list[FakeClient] = []

    def factory(**kwargs: object) -> FakeClient:
        client = FakeClient(responses, **kwargs)
        created.append(client)
        return client

    result = openai_structured_transport(
        {"prompt_version": "test"},
        LLMConfig(True, "secret", "gpt-4o-mini", 3, 2),
        client_factory=factory,
    )

    assert result == valid_payload()
    assert created[0].kwargs["api_key"] == "secret"
    assert created[0].kwargs["max_retries"] == 0
    request = responses.calls[0]
    assert request["model"] == "gpt-4o-mini"
    assert request["text"]["format"]["type"] == "json_schema"  # type: ignore[index]
    assert request["text"]["format"]["strict"] is True  # type: ignore[index]


def test_openai_transport_rejects_malformed_response() -> None:
    responses = FakeResponses("not-json")

    with pytest.raises(ValueError, match="malformed"):
        openai_structured_transport(
            {},
            LLMConfig(True, "secret", "model", 1, 0),
            client_factory=lambda **kwargs: FakeClient(responses, **kwargs),
        )


def test_provider_error_timeout_and_retry_exhaustion_are_sanitized() -> None:
    calls = 0

    def provider_error(_: dict[str, object], __: LLMConfig) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider rejected request")

    client = SemanticLLMClient(LLMConfig(True, "key", "model", 1, 2), provider_error)
    with pytest.raises(LLMUnavailableError, match="LLM assessment failed"):
        client.assess({})
    assert calls == 3

    def timeout(_: dict[str, object], __: LLMConfig) -> dict[str, object]:
        raise TimeoutError("network timeout")

    with pytest.raises(LLMUnavailableError, match="LLM assessment failed"):
        SemanticLLMClient(LLMConfig(True, "key", "model", 1, 0), timeout).assess({})


def test_missing_key_prevents_provider_call() -> None:
    with pytest.raises(LLMUnavailableError, match="API key is missing"):
        SemanticLLMClient(LLMConfig(True, None, "model", 1, 0)).assess({})
