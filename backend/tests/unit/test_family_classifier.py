from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jobagent_v2.family_classifier import (
    CLASSIFIER_VERSION,
    FAMILY_IDS,
    classify_job_family,
    load_classifier_config,
)


def job(title: str, text: str = "") -> dict[str, str]:
    return {"title": title, "company": "Fixture Co", "jd_text": text}


@pytest.mark.parametrize(
    ("title", "text", "family"),
    [
        ("RTL Design Engineer", "Implement RTL datapaths in SystemVerilog.", "digital_ic"),
        ("ASIC Design Engineer", "ASIC design, synthesis, timing closure, and PPA.", "digital_ic"),
        (
            "Design Verification Engineer",
            "Build UVM testbenches, scoreboards, coverage, and regression flows.",
            "verification",
        ),
        (
            "SoC Verification Engineer",
            "Own pre-silicon verification, SVA, test plans, and waveform debugging.",
            "verification",
        ),
        (
            "Backend Software Engineer",
            "Build backend APIs, databases, distributed systems, and cloud services.",
            "software",
        ),
        (
            "Full-Stack Engineer",
            "Develop frontend and backend APIs using TypeScript and SQL.",
            "software",
        ),
        (
            "Machine Learning Engineer",
            "Train and deploy PyTorch models for inference and evaluation.",
            "ml",
        ),
        (
            "Applied ML Engineer",
            "Own deep learning model training, quantization, and model evaluation.",
            "ml",
        ),
    ],
)
def test_clear_family_classifications(title: str, text: str, family: str) -> None:
    result = classify_job_family(job(title, text))

    assert result.selected_family == family
    assert result.decision == "clear_match"
    assert result.requires_review is False
    assert result.family_scores[family] >= 0.65
    assert_score_shape(result.to_dict())


def test_ml_accelerator_rtl_is_digital_ic_primary_with_ml_secondary() -> None:
    result = classify_job_family(job(
        "RTL Design Engineer, AI Accelerator",
        "Implement RTL for an AI accelerator, own microarchitecture and datapaths, "
        "and use Python for performance modelling.",
    ))

    assert result.selected_family == "digital_ic"
    assert result.family_scores["ml"] > 0
    assert result.decision in {"clear_match", "hybrid_match"}
    assert any(item["phrase"] == "microarchitecture" for item in result.rule_evidence)


def test_verification_infrastructure_python_role_is_verification_primary() -> None:
    result = classify_job_family(job(
        "Verification Infrastructure Engineer",
        "Build Python infrastructure for UVM regression triage, functional coverage, "
        "scoreboards, and waveform debugging.",
    ))

    assert result.selected_family == "verification"
    assert result.family_scores["software"] > 0
    assert result.family_scores["verification"] > result.family_scores["software"]


def test_ml_platform_backend_role_follows_responsibility_emphasis() -> None:
    result = classify_job_family(job(
        "ML Platform Backend Engineer",
        "Build backend APIs, databases, data pipelines, and cloud infrastructure for "
        "an AI product. Partner with model developers but do not train models.",
    ))

    assert result.selected_family == "software"
    assert result.family_scores["software"] > result.family_scores["ml"]


def test_fpga_verification_role_keeps_auditable_secondary_weight() -> None:
    result = classify_job_family(job(
        "FPGA Verification Engineer",
        "Verify RTL using UVM, SVA, protocol checkers, and FPGA prototyping flows.",
    ))

    assert result.selected_family == "verification"
    assert result.family_scores["digital_ic"] > 0
    assert result.rule_evidence


@pytest.mark.parametrize(
    ("title", "text", "family"),
    [
        (
            "UVM Regression Engineer",
            "Build Python infrastructure for UVM regression triage and coverage closure.",
            "verification",
        ),
        (
            "RTL Performance Modelling Engineer",
            "Implement RTL for an accelerator and use Python for performance modelling.",
            "digital_ic",
        ),
        (
            "C++ Inference Runtime Engineer",
            "Build the inference runtime, performance optimizations, testing, and "
            "production systems around deployed models.",
            "software",
        ),
        (
            "Backend APIs Engineer, AI Product",
            "Build backend APIs and data pipelines for an AI product using Python.",
            "software",
        ),
        (
            "PyTorch Model Training Engineer",
            "Train speech models with PyTorch, evaluate inference quality, and tune models.",
            "ml",
        ),
    ],
)
def test_responsibility_over_tool_policy(title: str, text: str, family: str) -> None:
    result = classify_job_family(job(title, text))

    assert result.selected_family == family
    assert result.family_scores[family] == max(result.family_scores.values())


def test_empty_description_is_low_confidence_review() -> None:
    result = classify_job_family(job("", ""))

    assert result.decision == "low_confidence"
    assert result.requires_review is True
    assert result.family_scores == {family: 0.25 for family in FAMILY_IDS}


def test_minimal_title_only_job_can_classify() -> None:
    result = classify_job_family(job("Backend Software Engineer"))

    assert result.selected_family == "software"
    assert result.decision == "clear_match"


def test_conflicting_title_and_responsibilities_requires_auditable_nonclear_decision() -> None:
    result = classify_job_family(job(
        "Machine Learning Engineer",
        "Own RTL implementation, microarchitecture, synthesis, and timing closure.",
    ))

    assert result.selected_family in {"digital_ic", "ml"}
    assert result.decision in {"hybrid_match", "close_match"}
    assert result.family_scores["digital_ic"] > 0
    assert result.family_scores["ml"] > 0


def test_unknown_out_of_scope_role_is_low_confidence() -> None:
    result = classify_job_family(job(
        "Product Manager",
        "Own roadmap planning, sales enablement, and stakeholder communications.",
    ))

    assert result.decision == "low_confidence"
    assert result.requires_review is True


def test_semantic_provider_unavailable_falls_back_to_deterministic() -> None:
    def unavailable(*_args: Any) -> dict[str, Any]:
        raise ValueError("fixture semantic provider unavailable")

    result = classify_job_family(
        job("RTL Engineer", "Implement RTL and SystemVerilog."),
        semantic_provider=unavailable,
    )

    assert result.selected_family == "digital_ic"
    assert result.semantic_scores is None
    assert result.semantic_evidence[0]["status"] == "unavailable"


def test_malformed_semantic_response_falls_back_to_deterministic() -> None:
    def malformed(*_args: Any) -> dict[str, Any]:
        return {"family_scores": {"digital_ic": 1.0}}

    result = classify_job_family(
        job("Machine Learning Engineer", "Train PyTorch models."),
        semantic_provider=malformed,
    )

    assert result.selected_family == "ml"
    assert result.semantic_scores is None
    assert result.semantic_evidence[0]["status"] == "unavailable"


def test_valid_semantic_response_combines_with_deterministic_scores() -> None:
    def semantic(*_args: Any) -> dict[str, Any]:
        return {
            "family_scores": {
                "digital_ic": 0.0,
                "verification": 0.0,
                "software": 0.2,
                "ml": 0.8,
            },
            "semantic_evidence": [
                {"family": "ml", "quote": "model training", "rationale": "fixture"}
            ],
        }

    result = classify_job_family(
        job("ML Platform Engineer", "Build model deployment and model evaluation tooling."),
        semantic_provider=semantic,
    )

    assert result.semantic_scores is not None
    assert result.semantic_evidence[0]["status"] == "success"
    assert result.family_scores["ml"] > result.deterministic_scores["ml"] * 0.6
    assert_score_shape(result.to_dict())


def test_normalized_scores_are_repeatable_and_sum_to_one() -> None:
    source = job("SoC Verification Engineer", "UVM SVA coverage regression scoreboard.")

    first = classify_job_family(source)
    second = classify_job_family(source)

    assert first.to_dict() == second.to_dict()
    assert abs(sum(first.family_scores.values()) - 1.0) < 0.00001


def test_configuration_versioning_is_stable() -> None:
    config = load_classifier_config()

    assert config["classifier_version"] == CLASSIFIER_VERSION
    assert config["config_version"] == "phase-b-family-classifier-config-v1"
    assert tuple(config["families"]) == FAMILY_IDS


def test_unknown_family_in_config_fails(tmp_path: Path) -> None:
    source = load_classifier_config()
    source["families"] = ["digital_ic", "verification", "software", "data_science"]
    path = tmp_path / "bad_classifier.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError, match="families"):
        load_classifier_config(path)


def assert_score_shape(payload: dict[str, Any]) -> None:
    assert set(payload["family_scores"]) == set(FAMILY_IDS)
    assert abs(sum(payload["family_scores"].values()) - 1.0) < 0.00001
    assert payload["selected_family"] in FAMILY_IDS
    assert payload["decision"] in {
        "clear_match", "hybrid_match", "close_match", "low_confidence",
    }
    assert isinstance(payload["rule_evidence"], list)
    assert isinstance(payload["semantic_evidence"], list)
    assert payload["classifier_version"] == CLASSIFIER_VERSION
