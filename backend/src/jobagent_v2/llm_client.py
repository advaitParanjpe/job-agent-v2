"""Isolated structured semantic-assessment client with safe default disablement."""

from __future__ import annotations

import os
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


SEMANTIC_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "role_family_candidates", "primary_cv_family", "secondary_cv_family",
        "family_confidence", "must_have_requirements", "nice_to_have_requirements",
        "requirement_block_matches", "semantic_block_assessments", "semantic_seniority_fit",
        "domain_alignment", "superficial_keyword_matches", "strengths", "gaps",
        "ambiguities", "grounded_reason",
    ],
    "properties": {
        "role_family_candidates": {"type": "array", "items": {"type": "string"}},
        "primary_cv_family": {"type": "string"},
        "secondary_cv_family": {"type": ["string", "null"]},
        "family_confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "must_have_requirements": {"type": "array", "items": {"type": "string"}},
        "nice_to_have_requirements": {"type": "array", "items": {"type": "string"}},
        "requirement_block_matches": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "requirement_id", "requirement_text", "matched_block_ids",
                    "match_strength", "evidence_summary", "confidence",
                ],
                "properties": {
                    "requirement_id": {"type": "string"},
                    "requirement_text": {"type": "string"},
                    "matched_block_ids": {"type": "array", "items": {"type": "string"}},
                    "match_strength": {"type": "integer", "minimum": 0, "maximum": 4},
                    "evidence_summary": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        },
        "semantic_block_assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "block_id", "responsibility_match", "technical_relevance",
                    "evidence_strength", "domain_relevance", "seniority_relevance",
                    "superficial_keyword_risk", "reason",
                ],
                "properties": {
                    "block_id": {"type": "string"},
                    "responsibility_match": {"type": "integer", "minimum": 0, "maximum": 4},
                    "technical_relevance": {"type": "integer", "minimum": 0, "maximum": 4},
                    "evidence_strength": {"type": "integer", "minimum": 0, "maximum": 4},
                    "domain_relevance": {"type": "integer", "minimum": 0, "maximum": 4},
                    "seniority_relevance": {"type": "integer", "minimum": 0, "maximum": 4},
                    "superficial_keyword_risk": {"type": "integer", "minimum": 0, "maximum": 4},
                    "reason": {"type": "string"},
                },
            },
        },
        "semantic_seniority_fit": {"type": "integer", "minimum": 0, "maximum": 4},
        "domain_alignment": {"type": "integer", "minimum": 0, "maximum": 4},
        "superficial_keyword_matches": {"type": "array", "items": {"type": "string"}},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "grounded_reason": {"type": "string"},
    },
}


class LLMUnavailableError(RuntimeError):
    """Raised when an LLM assessment cannot be obtained."""


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    api_key: str | None
    model: str
    timeout_seconds: float
    retry_count: int

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            enabled=os.getenv("JOBAGENT_LLM_ENABLED", "false").lower() == "true",
            api_key=os.getenv("JOBAGENT_LLM_API_KEY"),
            model=os.getenv("JOBAGENT_LLM_MODEL", "gpt-4o-mini"),
            timeout_seconds=float(os.getenv("JOBAGENT_LLM_TIMEOUT_SECONDS", "10")),
            retry_count=int(os.getenv("JOBAGENT_LLM_RETRY_COUNT", "1")),
        )


class SemanticLLMClient:
    """Calls injected tests transports or the configured OpenAI structured transport."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        transport: Callable[[dict[str, Any], LLMConfig], dict[str, Any]] | None = None,
    ) -> None:
        self.config = config or LLMConfig.from_env()
        self.transport = transport

    def assess(self, prompt: dict[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            raise LLMUnavailableError("LLM semantic assessment is disabled")
        if not self.config.api_key:
            raise LLMUnavailableError("LLM API key is missing")
        transport = self.transport or openai_structured_transport
        last_error: Exception | None = None
        for _ in range(self.config.retry_count + 1):
            try:
                return transport(prompt, self.config)
            except (TimeoutError, ValueError, RuntimeError) as error:
                last_error = error
        raise LLMUnavailableError(f"LLM assessment failed: {last_error}")


def openai_structured_transport(
    prompt: dict[str, Any],
    config: LLMConfig,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Request strict JSON from the official OpenAI Responses SDK without logging secrets."""
    try:
        from openai import APIError, APITimeoutError, OpenAI
    except ImportError as error:
        raise RuntimeError("OpenAI SDK is not installed") from error
    try:
        factory = client_factory or OpenAI
        client = factory(
            api_key=config.api_key,
            timeout=config.timeout_seconds,
            max_retries=0,
        )
        response = client.responses.create(
            model=config.model,
            instructions=(
                "Return only schema-valid semantic evidence. Do not return a score, "
                "recommendation, section score, or promotion decision."
            ),
            input=json.dumps(prompt, sort_keys=True),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "jobagent_semantic_assessment",
                    "strict": True,
                    "schema": SEMANTIC_OUTPUT_SCHEMA,
                }
            },
            timeout=config.timeout_seconds,
        )
    except APITimeoutError as error:
        raise TimeoutError("OpenAI request timed out") from error
    except APIError as error:
        raise RuntimeError("OpenAI provider request failed") from error
    output_text = getattr(response, "output_text", "")
    if not isinstance(output_text, str) or not output_text.strip():
        raise ValueError("OpenAI response did not contain structured output")
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise ValueError("OpenAI response JSON was malformed") from error
    if not isinstance(payload, dict):
        raise ValueError("OpenAI response JSON must be an object")
    return payload
