"""Validated semantic evidence plus deterministic Phase 3 score aggregation."""

from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Any

from jobagent_v2.llm_client import LLMUnavailableError, SemanticLLMClient
from jobagent_v2.scoring import SCORING_VERSION, ScoringResult, score_job


SEMANTIC_SCHEMA_VERSION = "phase3b-semantic-v1"
PROMPT_VERSION = "phase3b-semantic-assessment-v1"


class SemanticValidationError(ValueError):
    """Raised for malformed or unsupported semantic output."""


def build_prompt(job: dict[str, Any], deterministic: ScoringResult) -> dict[str, Any]:
    return {
        "prompt_version": PROMPT_VERSION,
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "instructions": "Use only supplied JD and truth-bank evidence. Do not score or recommend.",
        "job": {"title": job.get("title"), "jd_text": job.get("jd_text")},
        "structured_jd": deterministic.structured_jd,
        "families": deterministic.selection,
        "blocks": [
            {
                "block_id": item["block_id"],
                "block_name": item["block_name"],
                "reason": item["reason"],
            }
            for item in deterministic.block_scores
        ],
    }


def validate_semantic_assessment(
    data: dict[str, Any], block_ids: set[str]
) -> dict[str, Any]:
    required = {
        "role_family_candidates", "primary_cv_family", "secondary_cv_family",
        "family_confidence", "must_have_requirements", "nice_to_have_requirements",
        "requirement_block_matches", "semantic_block_assessments",
        "semantic_seniority_fit", "domain_alignment", "superficial_keyword_matches",
        "strengths", "gaps", "ambiguities", "grounded_reason",
    }
    if not isinstance(data, dict) or not required.issubset(data):
        raise SemanticValidationError("semantic assessment is missing required fields")
    if data["family_confidence"] not in {"low", "medium", "high"}:
        raise SemanticValidationError("semantic family confidence is invalid")
    assessments = data["semantic_block_assessments"]
    if not isinstance(assessments, list) or {
        item.get("block_id") for item in assessments
    } != block_ids:
        raise SemanticValidationError("semantic assessment must cover every truth-bank block")
    for item in assessments:
        for key in (
            "responsibility_match", "technical_relevance", "evidence_strength",
            "domain_relevance", "seniority_relevance", "superficial_keyword_risk",
        ):
            if not isinstance(item.get(key), int) or not 0 <= item[key] <= 4:
                raise SemanticValidationError(f"semantic bounded scale is invalid: {key}")
        if not isinstance(item.get("reason"), str):
            raise SemanticValidationError("semantic block reason is invalid")
    return data


def hybrid_family_decision(
    deterministic: dict[str, Any], semantic: dict[str, Any]
) -> dict[str, Any]:
    candidate = semantic["primary_cv_family"]
    if candidate == deterministic["primary_family"]:
        return {
            "selected": candidate,
            "rule": "agreement",
            "confidence": deterministic["confidence"],
        }
    if deterministic["confidence"] == "high":
        return {
            "selected": deterministic["primary_family"],
            "rule": "deterministic_high_confidence",
            "confidence": "high",
        }
    if semantic["family_confidence"] == "high" and semantic["grounded_reason"]:
        return {
            "selected": candidate,
            "rule": "grounded_semantic_override",
            "confidence": "high",
        }
    return {
        "selected": deterministic["primary_family"],
        "rule": "deterministic_tiebreak",
        "confidence": "low",
    }


def score_hybrid_job(
    job: dict[str, Any], client: SemanticLLMClient | None = None
) -> ScoringResult:
    deterministic = score_job(job)
    client = client or SemanticLLMClient()
    mode = (
        "deterministic_only" if not client.config.enabled else "deterministic_fallback"
    )
    diagnostics: dict[str, Any] = {
        "scoring_mode": mode,
        "semantic_status": "disabled" if not client.config.enabled else "not_configured"
        if not client.config.api_key else "not_attempted",
        "semantic_attempted": False,
        "semantic_enabled": bool(client.config.enabled),
        "fallback_used": not client.config.enabled or not client.config.api_key,
        "llm_call_status": "not_called",
        "llm_failure_reason": None,
        "failure_code": None,
        "failure_summary": None,
        "provider": "openai",
        "model": client.config.model,
        "started_at": None,
        "completed_at": None,
        "latency_ms": None,
        "prompt_version": PROMPT_VERSION,
        "semantic_schema_version": SEMANTIC_SCHEMA_VERSION,
        "semantic_assessment": None,
        "deterministic_family": deterministic.selection,
        "llm_family": None,
        "family_decision": None,
    }
    try:
        from jobagent_v2.util import utc_now_iso

        diagnostics["started_at"] = utc_now_iso()
        diagnostics["semantic_attempted"] = bool(client.config.enabled and client.config.api_key)
        start = perf_counter()
        assessment = validate_semantic_assessment(
            client.assess(build_prompt(job, deterministic)),
            {item["block_id"] for item in deterministic.block_scores},
        )
        diagnostics["completed_at"] = utc_now_iso()
        diagnostics["latency_ms"] = round((perf_counter() - start) * 1000)
    except (LLMUnavailableError, SemanticValidationError) as error:
        message = str(error)
        status = _semantic_failure_status(message, client)
        diagnostics.update({
            "semantic_status": status,
            "fallback_used": True,
            "llm_call_status": "unavailable",
            "llm_failure_reason": message,
            "failure_code": status,
            "failure_summary": _safe_summary(message),
        })
        return with_hybrid_diagnostics(deterministic, diagnostics)
    decision = hybrid_family_decision(deterministic.selection, assessment)
    semantic_by_block = {
        item["block_id"]: item for item in assessment["semantic_block_assessments"]
    }
    blocks: list[dict[str, Any]] = []
    for block in deterministic.block_scores:
        semantic = semantic_by_block[block["block_id"]]
        semantic_subtotal = round(
            100 * (
                semantic["responsibility_match"] + semantic["technical_relevance"]
                + semantic["evidence_strength"] + semantic["domain_relevance"]
                + semantic["seniority_relevance"]
            ) / 20
        )
        superficial_penalty = round(10 * semantic["superficial_keyword_risk"] / 4)
        aggregate = round(
            0.55 * block["aggregate_score"] + 0.35 * semantic_subtotal - superficial_penalty
        )
        blocks.append(
            {
                **block,
                "aggregate_score": max(0, min(100, aggregate)),
                "hybrid_components": {
                    "deterministic_subtotal": block["aggregate_score"],
                    "semantic_subtotal": semantic_subtotal,
                    "superficial_keyword_penalty": superficial_penalty,
                },
                "semantic_assessment": semantic,
            }
        )
    semantic_average = sum(item["aggregate_score"] for item in blocks) / len(blocks)
    score = max(
        0, min(100, round(0.75 * deterministic.overall_score + 0.25 * semantic_average))
    )
    recommendation = recommendation_for(score, deterministic.hard_blockers)
    diagnostics.update(
        {
            "scoring_mode": "hybrid",
            "semantic_status": "live_success",
            "fallback_used": False,
            "llm_call_status": "success",
            "semantic_assessment": assessment,
            "llm_family": {
                "primary": assessment["primary_cv_family"],
                "secondary": assessment["secondary_cv_family"],
                "confidence": assessment["family_confidence"],
            },
            "family_decision": decision,
        }
    )
    selection = {
        **deterministic.selection,
        "primary_family": decision["selected"],
        "confidence": decision["confidence"],
        "hybrid_decision": decision,
    }
    breakdown = {
        **deterministic.score_breakdown,
        "semantic_block_average": round(semantic_average),
        "hybrid_formula_version": "phase3b-hybrid-v1",
    }
    result = replace(
        deterministic,
        selection=selection,
        block_scores=blocks,
        overall_score=score,
        recommendation=recommendation,
        score_breakdown=breakdown,
    )
    return with_hybrid_diagnostics(result, diagnostics)


def recommendation_for(score: int, blockers: list[str]) -> str:
    recommendation = (
        "Strong apply"
        if score >= 85
        else "Apply" if score >= 75 else "Consider" if score >= 65 else "Low priority"
    )
    return (
        "Consider"
        if blockers and recommendation in {"Strong apply", "Apply"}
        else recommendation
    )


def with_hybrid_diagnostics(result: ScoringResult, diagnostics: dict[str, Any]) -> ScoringResult:
    return replace(result, score_breakdown={**result.score_breakdown, "hybrid": diagnostics})


def _semantic_failure_status(message: str, client: SemanticLLMClient) -> str:
    lowered = message.lower()
    if not client.config.enabled:
        return "disabled"
    if not client.config.api_key or "key is missing" in lowered:
        return "not_configured"
    if "timed out" in lowered or "timeout" in lowered:
        return "timed_out"
    if "missing required fields" in lowered or "invalid" in lowered or "malformed" in lowered:
        return "response_invalid"
    if "failed" in lowered or "provider request" in lowered:
        return "request_failed"
    return "fallback_used"


def _safe_summary(message: str) -> str:
    text = " ".join(message.split())
    return text[:240]
