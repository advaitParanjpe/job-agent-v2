from __future__ import annotations

import json

from jobagent_v2.service import JobService
from jobagent_v2.project_blocks import list_project_blocks, load_project_block_registry
from jobagent_v2.requirements import extract_requirements, score_project_portfolio
from jobagent_v2.tailoring import load_tailoring_policy, select_tailoring_decision


def _classification(family: str = "ml", decision: str = "clear_match") -> dict[str, object]:
    scores = {
        "digital_ic": 0.05,
        "verification": 0.02,
        "software": 0.13,
        "ml": 0.8,
    }
    if family == "digital_ic":
        scores = {"digital_ic": 0.78, "verification": 0.05, "software": 0.05, "ml": 0.12}
    return {
        "decision": decision,
        "requires_review": decision in {"close_match", "low_confidence"},
        "classifier_version": "phase-b-family-classifier-v1",
        "family_scores": scores,
        "selected_family": family,
        "secondary_family": "software" if family == "ml" else "ml",
        "confidence": scores[family],
        "rule_evidence": [],
    }


def qualcomm_like_job() -> dict[str, object]:
    return {
        "id": "qualcomm-cross-domain-fixture",
        "selected_cv_family": "ml",
        "title": "Machine Learning Engineer - College Graduate",
        "jd_text": (
            "Responsibilities: develop machine learning models and optimize inference "
            "for edge AI products. Preferred qualifications include knowledge of NPUs, "
            "machine-learning accelerators, quantized inference, and hardware-aware "
            "performance optimization. Use Python, C++, and PyTorch for deployment "
            "on constrained devices."
        ),
        "structured_jd": {
            "title": "Machine Learning Engineer - College Graduate",
            "responsibilities": [
                "Develop machine learning models and optimize inference for edge AI products"
            ],
            "must_have_requirements": [
                "Use Python, C++, and PyTorch for deployment on constrained devices"
            ],
            "nice_to_have_requirements": [
                "Knowledge of NPUs, machine-learning accelerators, quantized inference, "
                "and hardware-aware performance optimization"
            ],
            "skills": ["Python", "C++", "PyTorch"],
            "technologies": ["PyTorch", "C++"],
            "domains": ["edge AI", "machine learning"],
            "keywords": ["NPU", "machine-learning accelerators", "quantized inference"],
        },
        "family_classification": _classification("ml"),
    }


def generic_ml_job() -> dict[str, object]:
    return {
        "id": "generic-ml-fixture",
        "selected_cv_family": "ml",
        "title": "Machine Learning Engineer",
        "jd_text": (
            "Train PyTorch models, evaluate experiments, analyze datasets, and "
            "communicate results with product teams."
        ),
        "structured_jd": {
            "title": "Machine Learning Engineer",
            "responsibilities": ["Train PyTorch models and evaluate experiments"],
            "must_have_requirements": ["PyTorch and machine learning model training"],
            "nice_to_have_requirements": ["Communication and teamwork"],
            "skills": ["PyTorch", "Python"],
            "technologies": ["PyTorch"],
            "domains": ["machine learning"],
            "keywords": ["model training"],
        },
        "family_classification": _classification("ml"),
    }


def test_requirement_extraction_normalizes_npu_and_generic_specificity() -> None:
    analysis = extract_requirements(qualcomm_like_job())
    requirements = analysis["requirements"]

    npu = next(
        item for item in requirements
        if "npu" in item["normalized_capabilities"]
    )
    assert npu["required_or_preferred"] == "preferred"
    assert npu["specificity"] >= 0.9
    assert npu["importance"] >= 0.55
    assert npu["evidence_quote"].lower() in {"npu", "npus"}

    generic = extract_requirements(generic_ml_job())["requirements"]
    collaboration = next(
        item for item in generic
        if "general_collaboration" in item["normalized_capabilities"]
    )
    assert collaboration["specificity"] < 0.3
    assert collaboration["importance"] < npu["importance"]


def test_project_registry_has_bounded_portfolio_metadata() -> None:
    blocks = list_project_blocks()

    assert len(blocks) == 12
    assert all(block.home_family == block.family for block in blocks)
    assert all(block.capabilities for block in blocks)
    assert all(0.0 <= weight <= 1.0 for block in blocks for weight in block.capabilities.values())
    assert all(block.evidence_terms for block in blocks)
    tinynpu = next(block for block in blocks if block.block_id == "tinynpu_digital_ic_v1")
    assert tinynpu.home_family == "digital_ic"
    assert "ml" in tinynpu.eligible_families
    assert tinynpu.capabilities["npu"] == 1.0


def test_ml_base_family_considers_digital_ic_home_project_without_changing_base() -> None:
    job = qualcomm_like_job()
    registry = load_project_block_registry()
    analysis = extract_requirements(job)
    portfolio = score_project_portfolio(
        base_family="ml",
        registry=registry,
        requirement_analysis=analysis,
    )

    assert job["selected_cv_family"] == "ml"
    assert "tinynpu_digital_ic_v1" in portfolio["shortlist"]
    tinynpu = next(
        item for item in portfolio["candidate_scores"]
        if item["block_id"] == "tinynpu_digital_ic_v1"
    )
    assert tinynpu["home_family"] == "digital_ic"
    assert "high_specificity_requirement" == tinynpu["shortlist_reason"]
    assert {"npu", "ml_accelerator", "hardware_acceleration"} & set(
        tinynpu["distinctive_capabilities"]
    )


def test_qualcomm_regression_surfaces_tinynpu_for_review_when_auto_margin_fails() -> None:
    decision = select_tailoring_decision(
        packet_id="packet-qualcomm",
        job=qualcomm_like_job(),
        base_family="ml",
        registry=load_project_block_registry(),
        policy=load_tailoring_policy(),
    )

    assert decision["base_family"] == "ml"
    assert decision["tailoring_status"] == "review_required"
    assert decision["inserted_block"] is None
    assert decision["requires_review"] is True
    assert "tinynpu_digital_ic_v1" in decision["project_portfolio"]["shortlist"]
    tinynpu_candidate = next(
        item for item in decision["candidate_blocks"]
        if item["block_id"] == "tinynpu_digital_ic_v1"
    )
    assert tinynpu_candidate["shortlist_reason"] == "requirement_aware_shortlist"
    assert tinynpu_candidate["requires_review"] is True
    assert decision["replacement_gain"] < load_tailoring_policy()["minimum_replacement_gain"]


def test_generic_ml_role_does_not_shortlist_tinynpu() -> None:
    decision = select_tailoring_decision(
        packet_id="packet-generic-ml",
        job=generic_ml_job(),
        base_family="ml",
        registry=load_project_block_registry(),
        policy=load_tailoring_policy(),
    )

    assert "tinynpu_digital_ic_v1" not in decision["project_portfolio"]["shortlist"]
    assert decision["tailoring_status"] == "master_unchanged"
    assert decision["requires_review"] is False


def test_digital_ic_base_family_still_selects_ml_bridge_without_changing_base() -> None:
    job = {
        "id": "digital-ic-ml-bridge",
        "selected_cv_family": "digital_ic",
        "title": "RTL ML Accelerator Engineer",
        "jd_text": (
            "Design RTL accelerators for machine learning inference, PyTorch "
            "quantization, edge ML compiler runtime, and sparse vector execution."
        ),
        "structured_jd": {
            "title": "RTL ML Accelerator Engineer",
            "responsibilities": [
                "Design RTL accelerators for machine learning inference and sparse vector execution"
            ],
            "must_have_requirements": [
                "SystemVerilog Python C PyTorch quantization inference"
            ],
            "nice_to_have_requirements": [],
            "skills": ["SystemVerilog", "Python", "C", "PyTorch"],
            "technologies": ["SystemVerilog", "Python", "C", "PyTorch"],
            "domains": ["machine learning", "edge AI"],
            "keywords": ["rtl", "accelerator", "quantization", "compiler runtime"],
        },
        "family_classification": _classification("digital_ic", "hybrid_match"),
    }

    decision = select_tailoring_decision(
        packet_id="packet-dic",
        job=job,
        base_family="digital_ic",
        registry=load_project_block_registry(),
        policy=load_tailoring_policy(),
    )

    assert decision["base_family"] == "digital_ic"
    assert decision["inserted_block"] == "sparrowml_ml_v1"
    assert len(set(decision["final_order"]) - set(decision["base_blocks"])) == 1


def test_reanalysis_persists_decision_without_creating_packet(
    service: JobService,
    repository,
) -> None:
    created = service.create_job({
        "url": "https://example.com/jobs/qualcomm-sanitized",
        "page_title": "Machine Learning Engineer - College Graduate",
        "visible_text": qualcomm_like_job()["jd_text"],
        "source_site": "example.com",
        "captured_at": "2026-07-01T12:00:00Z",
    })
    job_id = str(created["job_id"])
    job = qualcomm_like_job()
    with repository.connect() as connection:
        repository._update_job(connection, job_id, {
            "intake_status": "scored",
            "overall_score": 86,
            "hard_blockers_json": "[]",
            "selected_cv_family": "ml",
            "secondary_cv_family": "software",
            "cv_family_confidence": "high",
            "scoring_version": "phase3-deterministic-v1",
            "structured_jd_json": json.dumps(job["structured_jd"], sort_keys=True),
            "family_classification_json": json.dumps(job["family_classification"], sort_keys=True),
            "family_classifier_version": "phase-b-family-classifier-v1",
            "family_classification_decision": "clear_match",
            "family_classification_requires_review": 0,
        })

    result = service.reanalyze_project_selection(job_id)

    assert result["job"]["packet"] is None
    decision = result["tailoring_decision"]["decision"]
    assert decision["analysis_mode"] == "reanalysis"
    assert decision["base_family"] == "ml"
    assert "tinynpu_digital_ic_v1" in decision["project_portfolio"]["shortlist"]
    assert repository.get_packet_for_job(job_id) is None
    events = repository.list_events(job_id)
    assert events[-1]["event_type"] == "project_selection_reanalyzed"
