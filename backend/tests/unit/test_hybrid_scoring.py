from __future__ import annotations

import pytest

from jobagent_v2.hybrid_scoring import (
    SemanticValidationError,
    hybrid_family_decision,
    score_hybrid_job,
    validate_semantic_assessment,
)
from jobagent_v2.llm_client import LLMConfig, SemanticLLMClient


JOB = {
    "title": "RTL Engineer", "company": "Acme", "location": "Austin, TX",
    "jd_text": "Responsibilities\nDesign SystemVerilog RTL ASIC hardware.\nQualifications\n"
    "Verilog SystemVerilog RTL ASIC Python semiconductor.",
}


def response(prompt: dict[str, object], _: LLMConfig) -> dict[str, object]:
    block_ids = [item["block_id"] for item in prompt["blocks"]]  # type: ignore[index]
    return {
        "role_family_candidates": ["RTL / ASIC Design"], "primary_cv_family": "hardware_rtl",
        "secondary_cv_family": None, "family_confidence": "high", "must_have_requirements": [],
        "nice_to_have_requirements": [], "requirement_block_matches": [],
        "semantic_block_assessments": [
            {"block_id": block_id, "responsibility_match": 4, "technical_relevance": 4,
             "evidence_strength": 3, "domain_relevance": 4, "seniority_relevance": 3,
             "superficial_keyword_risk": 0, "reason": "Direct provided evidence."}
            for block_id in block_ids
        ],
        "semantic_seniority_fit": 3, "domain_alignment": 4, "superficial_keyword_matches": [],
        "strengths": ["RTL evidence"], "gaps": [], "ambiguities": [],
        "grounded_reason": "Provided blocks directly support RTL requirements.",
    }


def enabled_client(transport=response) -> SemanticLLMClient:
    return SemanticLLMClient(LLMConfig(True, "test-key", "fake-model", 1, 1), transport)


def test_hybrid_validated_assessment_drives_deterministic_score() -> None:
    result = score_hybrid_job(JOB, enabled_client())

    assert result.score_breakdown["hybrid"]["scoring_mode"] == "hybrid"
    assert result.recommendation in {"Strong apply", "Apply", "Consider", "Low priority"}
    assert all("hybrid_components" in block for block in result.block_scores)
    assert 0 <= result.overall_score <= 100


def test_missing_key_and_timeout_fall_back_without_losing_score() -> None:
    missing_key = SemanticLLMClient(LLMConfig(True, None, "fake", 1, 0))
    fallback = score_hybrid_job(JOB, missing_key)
    assert fallback.score_breakdown["hybrid"]["scoring_mode"] == "deterministic_fallback"

    def timeout(_: dict[str, object], __: LLMConfig) -> dict[str, object]:
        raise TimeoutError("timeout")

    timed_out = score_hybrid_job(JOB, enabled_client(timeout))
    assert timed_out.score_breakdown["hybrid"]["llm_call_status"] == "unavailable"


def test_malformed_semantic_response_is_rejected_and_falls_back() -> None:
    malformed = score_hybrid_job(JOB, enabled_client(lambda *_: {"bad": True}))
    assert malformed.score_breakdown["hybrid"]["scoring_mode"] == "deterministic_fallback"
    with pytest.raises(SemanticValidationError):
        validate_semantic_assessment({}, {"block"})


def test_family_disagreement_policy_keeps_deterministic_high_confidence() -> None:
    decision = hybrid_family_decision(
        {"primary_family": "hardware_rtl", "confidence": "high"},
        {"primary_cv_family": "software", "family_confidence": "high", "grounded_reason": "x"},
    )
    assert decision["selected"] == "hardware_rtl"
    assert decision["rule"] == "deterministic_high_confidence"
