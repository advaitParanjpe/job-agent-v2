from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from jobagent_v2 import calibration
from jobagent_v2.calibration import CalibrationError
from jobagent_v2.family_classifier import load_classifier_config
from jobagent_v2.tailoring import load_tailoring_policy


def _example(example_id: str, family: str | None, *, split: str = "train") -> dict[str, object]:
    if family == "digital_ic":
        title = "RTL Design Engineer"
        description = (
            "Responsibilities Implement SystemVerilog RTL, microarchitecture, "
            "synthesis, and timing-aware datapaths."
        )
        decision = "clear_match"
        action = "master_unchanged"
        primary = ["digital_ic"]
        review = False
    elif family == "verification":
        title = "UVM Verification Engineer"
        description = (
            "Responsibilities Build UVM testbenches, scoreboards, coverage, "
            "assertions, and regression triage automation."
        )
        decision = "clear_match"
        action = "master_unchanged"
        primary = ["verification"]
        review = False
    elif family == "software":
        title = "Backend Software Engineer"
        description = (
            "Responsibilities Build backend APIs, SQL storage, queue workers, "
            "service reliability, and distributed systems."
        )
        decision = "clear_match"
        action = "master_unchanged"
        primary = ["software"]
        review = False
    elif family == "ml":
        title = "Machine Learning Engineer"
        description = (
            "Responsibilities Train PyTorch models, evaluate inference quality, "
            "quantization, model evaluation, and deployment workflows."
        )
        decision = "clear_match"
        action = "master_unchanged"
        primary = ["ml"]
        review = False
    else:
        title = "Analog Layout Engineer"
        description = (
            "Responsibilities Create transistor-level custom analog layouts, "
            "device matching, parasitic extraction, DRC, and LVS."
        )
        decision = "low_confidence"
        action = "any_no_auto"
        primary = []
        review = True
    return {
        "example_id": example_id,
        "title": title,
        "description": description,
        "category": family or "out_of_scope",
        "split": split,
        "expected_primary_family": family,
        "acceptable_primary_families": primary,
        "acceptable_secondary_families": [],
        "expected_decision": decision,
        "requires_review": review,
        "expected_tailoring_action": action,
        "acceptable_inserted_blocks": [],
        "unacceptable_inserted_blocks": [],
        "notes": "unit test fixture",
    }


def _dataset(tmp_path: Path, examples: list[dict[str, object]]) -> Path:
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps({
            "dataset_version": calibration.DATASET_VERSION,
            "dataset_id": "unit-test-dataset",
            "examples": examples,
        }),
        encoding="utf-8",
    )
    return path


def test_default_dataset_schema_and_coverage() -> None:
    data = calibration.load_labelled_dataset()
    summary = calibration.dataset_summary(calibration.dataset_examples(data))

    assert summary["total"] == 90
    assert summary["categories"] == {
        "digital_ic": 15,
        "verification": 15,
        "software": 15,
        "ml": 15,
        "hybrid": 20,
        "out_of_scope": 10,
    }
    assert summary["splits"]["holdout"] > 0


def test_dataset_validation_rejects_duplicate_unknown_family_and_bad_block(tmp_path) -> None:
    duplicate = [_example("same", "digital_ic"), _example("same", "software")]
    with pytest.raises(CalibrationError, match="duplicate example_id"):
        calibration.load_labelled_dataset(_dataset(tmp_path, duplicate))

    unknown = [_example("bad-family", "digital_ic")]
    unknown[0]["expected_primary_family"] = "analog"
    unknown[0]["acceptable_primary_families"] = ["analog"]
    with pytest.raises(CalibrationError, match="unknown expected family"):
        calibration.load_labelled_dataset(_dataset(tmp_path, unknown))

    bad_block = [_example("bad-block", "digital_ic")]
    bad_block[0]["acceptable_inserted_blocks"] = ["missing_block"]
    with pytest.raises(CalibrationError, match="unknown block"):
        calibration.load_labelled_dataset(_dataset(tmp_path, bad_block))


def test_deterministic_split_is_repeatable() -> None:
    first = calibration.deterministic_split("stable-example")
    assert first == calibration.deterministic_split("stable-example")
    assert first in {"train", "holdout"}


def test_evaluation_is_repeatable_and_writes_no_production_db(tmp_path) -> None:
    path = _dataset(tmp_path, [
        _example("dic", "digital_ic", split="train"),
        _example("ver", "verification", split="holdout"),
        _example("sw", "software", split="train"),
        _example("ml", "ml", split="holdout"),
    ])
    db_path = Path("data/jobagent_v2.sqlite3")
    before = db_path.stat().st_mtime_ns if db_path.exists() else None

    first = calibration.evaluate(dataset_path=path)
    second = calibration.evaluate(dataset_path=path)

    assert first["metrics"] == second["metrics"]
    after = db_path.stat().st_mtime_ns if db_path.exists() else None
    assert after == before


def test_confusion_matrix_and_metric_math() -> None:
    records = [
        {
            "expected_primary_family": "digital_ic",
            "actual_primary_family": "digital_ic",
            "actual_secondary_family": None,
            "acceptable_primary_families": ["digital_ic"],
            "selected_ok": True,
            "classification_decision": "clear_match",
            "classification_requires_review": False,
        },
        {
            "expected_primary_family": "software",
            "actual_primary_family": "ml",
            "actual_secondary_family": "software",
            "acceptable_primary_families": ["software"],
            "selected_ok": False,
            "classification_decision": "hybrid_match",
            "classification_requires_review": False,
        },
    ]

    metrics = calibration.classification_metrics(records)

    assert metrics["confusion_matrix"]["digital_ic"]["digital_ic"] == 1
    assert metrics["confusion_matrix"]["software"]["ml"] == 1
    assert metrics["primary_accuracy"] == 0.5
    assert metrics["top_two_recall"] == 1.0


def test_parameter_search_is_deterministic_and_gates_block_safety_regression(
    tmp_path, monkeypatch
) -> None:
    path = _dataset(tmp_path, [
        _example("dic", "digital_ic", split="train"),
        _example("ver", "verification", split="holdout"),
        _example("out", None, split="holdout"),
    ])
    classifier = load_classifier_config()
    policy = load_tailoring_policy()

    def tiny_candidates(base_classifier, base_policy):
        candidate_classifier = copy.deepcopy(base_classifier)
        candidate_policy = copy.deepcopy(base_policy)
        candidate_classifier["decision_thresholds"]["low_confidence_max_score"] = 0.36
        return [(candidate_classifier, candidate_policy)]

    monkeypatch.setattr(calibration, "candidate_configs", tiny_candidates)
    first = calibration.search_parameters(path)
    second = calibration.search_parameters(path)

    assert first["promotion_decision"] == second["promotion_decision"]
    assert first["acceptance_gates"] == second["acceptance_gates"]
    assert first["promotion_decision"]["promote"] is False
    assert first["best_candidate"]["classifier_config"]["classifier_version"] == (
        classifier["classifier_version"]
    )
    assert first["best_candidate"]["tailoring_policy"]["policy_version"] == (
        policy["policy_version"]
    )


def test_report_generation_and_fake_semantic_provider(tmp_path, monkeypatch) -> None:
    path = _dataset(tmp_path, [
        _example("dic", "digital_ic", split="train"),
        _example("ml", "ml", split="holdout"),
    ])

    def tiny_candidates(base_classifier, base_policy):
        return [(copy.deepcopy(base_classifier), copy.deepcopy(base_policy))]

    monkeypatch.setattr(calibration, "candidate_configs", tiny_candidates)
    result = calibration.search_parameters(path, semantic_mode="fake")
    paths = calibration.write_reports(result, tmp_path / "reports")

    assert result["baseline"]["semantic_mode"] == "fake"
    assert Path(paths["json"]).is_file()
    assert Path(paths["markdown"]).read_text(encoding="utf-8").startswith(
        "# Phase E Calibration Report"
    )


def test_live_semantic_without_credentials_falls_back_offline(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("JOBAGENT_LLM_API_KEY", raising=False)
    path = _dataset(tmp_path, [_example("dic", "digital_ic", split="train")])

    report = calibration.evaluate(dataset_path=path, semantic_mode="live")

    assert report["semantic_mode"] == "deterministic"
