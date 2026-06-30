"""Offline evaluation and calibration for family classification and tailoring."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobagent_v2.family_classifier import (
    CLASSIFIER_VERSION,
    CONFIG_PATH,
    FAMILY_IDS,
    LLMFamilySemanticProvider,
    FamilyClassificationResult,
    combine_scores,
    decide,
    deterministic_family_scores,
    has_title_conflict,
    load_classifier_config,
    semantic_family_scores,
)
from jobagent_v2.project_blocks import load_project_block_registry, validate_replacement_pair
from jobagent_v2.scoring import structure_jd
from jobagent_v2.tailoring import (
    TAILORING_POLICY_PATH,
    load_tailoring_policy,
    select_tailoring_decision,
)
from jobagent_v2.util import utc_now_iso


DATASET_VERSION = "phase-e-labelled-jobs-v1"
REPORT_VERSION = "phase-e-calibration-report-v1"
DEFAULT_DATASET_PATH = Path(__file__).with_name("data") / "evaluation" / "labelled_jobs.json"
DEFAULT_REPORT_DIR = Path(__file__).resolve().parents[3] / "reports" / "calibration"
TAILORING_ACTIONS = {
    "master_unchanged",
    "one_swap",
    "review_required",
    "fallback_to_master",
    "any_no_auto",
}


class CalibrationError(ValueError):
    """Raised when calibration input or configuration is invalid."""


@dataclass(frozen=True)
class LabelledExample:
    example_id: str
    title: str
    description: str
    category: str
    split: str
    expected_primary_family: str | None
    acceptable_primary_families: list[str]
    acceptable_secondary_families: list[str]
    expected_decision: str | None
    requires_review: bool
    expected_tailoring_action: str
    acceptable_inserted_blocks: list[str]
    unacceptable_inserted_blocks: list[str]
    notes: str

    def to_job(self) -> dict[str, Any]:
        return {
            "id": self.example_id,
            "job_id": self.example_id,
            "title": self.title,
            "jd_text": self.description,
            "raw_visible_text": self.description,
        }


def load_labelled_dataset(path: Path | str = DEFAULT_DATASET_PATH) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_dataset(data)
    return data


def dataset_examples(data: dict[str, Any]) -> list[LabelledExample]:
    return [LabelledExample(**item) for item in data["examples"]]


def validate_dataset(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise CalibrationError("dataset must be a JSON object")
    if data.get("dataset_version") != DATASET_VERSION:
        raise CalibrationError("dataset_version is unsupported")
    examples = data.get("examples")
    if not isinstance(examples, list) or not examples:
        raise CalibrationError("dataset requires examples")
    registry = load_project_block_registry()
    block_ids = {str(block["block_id"]) for block in registry["blocks"]}
    seen: set[str] = set()
    for index, item in enumerate(examples):
        if not isinstance(item, dict):
            raise CalibrationError(f"example {index} must be an object")
        example_id = _required_string(item, "example_id", index)
        if example_id in seen:
            raise CalibrationError(f"duplicate example_id: {example_id}")
        seen.add(example_id)
        for key in ("title", "description", "category", "split", "notes"):
            _required_string(item, key, index)
        if item["split"] not in {"train", "holdout"}:
            raise CalibrationError(f"example {example_id} has invalid split")
        expected = item.get("expected_primary_family")
        if expected is not None and expected not in FAMILY_IDS:
            raise CalibrationError(f"example {example_id} has unknown expected family")
        primary = _string_list(item.get("acceptable_primary_families"), "primary", example_id)
        if expected is not None and expected not in primary:
            raise CalibrationError(f"example {example_id} must accept expected primary family")
        _validate_families(primary, example_id)
        secondary = _string_list(
            item.get("acceptable_secondary_families"), "secondary", example_id
        )
        _validate_families(secondary, example_id)
        decision = item.get("expected_decision")
        if decision is not None and decision not in {
            "clear_match", "hybrid_match", "close_match", "low_confidence",
        }:
            raise CalibrationError(f"example {example_id} has invalid expected decision")
        if not isinstance(item.get("requires_review"), bool):
            raise CalibrationError(f"example {example_id} requires_review must be boolean")
        action = item.get("expected_tailoring_action")
        if action not in TAILORING_ACTIONS:
            raise CalibrationError(f"example {example_id} has invalid tailoring action")
        for key in ("acceptable_inserted_blocks", "unacceptable_inserted_blocks"):
            values = _string_list(item.get(key), key, example_id)
            unknown = sorted(set(values) - block_ids)
            if unknown:
                raise CalibrationError(
                    f"example {example_id} references unknown block {unknown[0]}"
                )


def deterministic_split(example_id: str, holdout_percent: int = 20) -> str:
    digest = hashlib.sha256(example_id.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return "holdout" if bucket < holdout_percent else "train"


def evaluate(
    *,
    dataset_path: Path | str = DEFAULT_DATASET_PATH,
    classifier_config: dict[str, Any] | None = None,
    tailoring_policy: dict[str, Any] | None = None,
    semantic_mode: str = "deterministic",
) -> dict[str, Any]:
    dataset = load_labelled_dataset(dataset_path)
    examples = dataset_examples(dataset)
    classifier = classifier_config or load_classifier_config()
    policy = tailoring_policy or load_tailoring_policy()
    registry = load_project_block_registry()
    semantic_provider = _semantic_provider(semantic_mode)
    records = [
        evaluate_example(
            example,
            classifier_config=classifier,
            tailoring_policy=policy,
            registry=registry,
            semantic_provider=semantic_provider,
        )
        for example in examples
    ]
    return {
        "report_version": REPORT_VERSION,
        "dataset_version": dataset["dataset_version"],
        "dataset_id": dataset["dataset_id"],
        "dataset_summary": dataset_summary(examples),
        "semantic_mode": semantic_mode if semantic_provider is not None else "deterministic",
        "classifier_config": _config_summary(classifier),
        "tailoring_policy": _tailoring_summary(policy),
        "metrics": {
            "all": compute_metrics(records),
            "train": compute_metrics([item for item in records if item["split"] == "train"]),
            "holdout": compute_metrics(
                [item for item in records if item["split"] == "holdout"]
            ),
        },
        "records": records,
    }


def evaluate_example(
    example: LabelledExample,
    *,
    classifier_config: dict[str, Any],
    tailoring_policy: dict[str, Any],
    registry: dict[str, Any],
    semantic_provider: Any = None,
) -> dict[str, Any]:
    job = example.to_job()
    structured = structure_jd(job)
    classification = classify_with_config(
        job,
        structured_jd=structured,
        config=classifier_config,
        semantic_provider=semantic_provider,
    )
    job["selected_cv_family"] = classification.selected_family
    job["structured_jd"] = structured
    job["family_classification"] = classification.to_dict()
    tailoring = select_tailoring_decision(
        packet_id=f"eval-{example.example_id}",
        job=job,
        base_family=classification.selected_family,
        registry=registry,
        policy=tailoring_policy,
    )
    validate_tailoring_policy_compliance(tailoring, registry)
    selected_ok = classification.selected_family in example.acceptable_primary_families
    secondary_ok = (
        classification.secondary_family in example.acceptable_secondary_families
        if example.acceptable_secondary_families
        else True
    )
    actual_action = tailoring_action(tailoring)
    action_ok = tailoring_action_matches(example, tailoring)
    high_conf_wrong = (
        not selected_ok
        and not classification.requires_review
        and classification.decision == "clear_match"
    )
    return {
        "example_id": example.example_id,
        "split": example.split,
        "category": example.category,
        "expected_primary_family": example.expected_primary_family,
        "acceptable_primary_families": example.acceptable_primary_families,
        "actual_primary_family": classification.selected_family,
        "actual_secondary_family": classification.secondary_family,
        "classification_decision": classification.decision,
        "classification_requires_review": classification.requires_review,
        "expected_requires_review": example.requires_review,
        "classification_confidence": classification.confidence,
        "selected_ok": selected_ok,
        "secondary_ok": secondary_ok,
        "decision_ok": (
            example.expected_decision is None
            or classification.decision == example.expected_decision
        ),
        "review_ok": classification.requires_review == example.requires_review,
        "wrong_high_confidence_no_review": high_conf_wrong,
        "expected_tailoring_action": example.expected_tailoring_action,
        "actual_tailoring_action": actual_action,
        "tailoring_status": tailoring["tailoring_status"],
        "inserted_block": tailoring.get("inserted_block"),
        "removed_block": tailoring.get("removed_block"),
        "replacement_gain": tailoring.get("replacement_gain"),
        "tailoring_action_ok": action_ok,
        "tailoring_requires_review": tailoring.get("requires_review"),
        "invalid_substitution": False,
        "unnecessary_substitution": (
            actual_action == "one_swap"
            and example.expected_tailoring_action != "one_swap"
        ),
        "notes": example.notes,
    }


def classify_with_config(
    job: dict[str, Any],
    *,
    structured_jd: dict[str, Any],
    config: dict[str, Any],
    semantic_provider: Any = None,
) -> FamilyClassificationResult:
    deterministic, rule_evidence = deterministic_family_scores(job, structured_jd, config)
    semantic_scores, semantic_evidence = semantic_family_scores(
        job, structured_jd, deterministic, semantic_provider
    )
    combined = combine_scores(deterministic, semantic_scores, config)
    ranked = sorted(combined.items(), key=lambda item: (-item[1], item[0]))
    selected, confidence = ranked[0]
    secondary = ranked[1][0] if len(ranked) > 1 else None
    decision, requires_review = decide(combined, config)
    if decision == "clear_match" and has_title_conflict(rule_evidence, selected):
        decision = "hybrid_match"
        requires_review = False
    return FamilyClassificationResult(
        family_scores=combined,
        selected_family=selected,
        secondary_family=secondary,
        confidence=round(confidence, 4),
        decision=decision,
        requires_review=requires_review,
        rule_evidence=rule_evidence,
        semantic_evidence=semantic_evidence,
        classifier_version=str(config["classifier_version"]),
        config_version=str(config["config_version"]),
        deterministic_scores=deterministic,
        semantic_scores=semantic_scores,
    )


def compute_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}
    in_scope = [item for item in records if item["expected_primary_family"] is not None]
    family_metrics = classification_metrics(in_scope)
    tailoring = tailoring_metrics(records)
    decisions = decision_metrics(records)
    safety = {
        "wrong_high_confidence_no_review": sum(
            1 for item in records if item["wrong_high_confidence_no_review"]
        ),
        "wrong_high_confidence_rate": rate(
            sum(1 for item in records if item["wrong_high_confidence_no_review"]),
            len(records),
        ),
        "out_of_scope_review_rate": rate(
            sum(
                1 for item in records
                if item["expected_primary_family"] is None
                and item["classification_requires_review"]
            ),
            sum(1 for item in records if item["expected_primary_family"] is None),
        ),
    }
    return {
        "count": len(records),
        "family_classification": family_metrics,
        "decision_behavior": decisions,
        "tailoring_behavior": tailoring,
        "safety": safety,
    }


def classification_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    matrix = {
        expected: {actual: 0 for actual in FAMILY_IDS}
        for expected in FAMILY_IDS
    }
    for item in records:
        expected = item["expected_primary_family"]
        actual = item["actual_primary_family"]
        matrix[expected][actual] += 1
    per_family = {}
    for family in FAMILY_IDS:
        tp = matrix[family][family]
        fp = sum(matrix[other][family] for other in FAMILY_IDS if other != family)
        fn = sum(matrix[family][other] for other in FAMILY_IDS if other != family)
        precision = rate(tp, tp + fp)
        recall = rate(tp, tp + fn)
        per_family[family] = {
            "precision": precision,
            "recall": recall,
            "f1": f1(precision, recall),
        }
    return {
        "primary_accuracy": rate(sum(1 for item in records if item["selected_ok"]), len(records)),
        "macro_precision": average([item["precision"] for item in per_family.values()]),
        "macro_recall": average([item["recall"] for item in per_family.values()]),
        "macro_f1": average([item["f1"] for item in per_family.values()]),
        "per_family": per_family,
        "confusion_matrix": matrix,
        "top_two_recall": rate(
            sum(
                1 for item in records
                if item["selected_ok"]
                or item["actual_secondary_family"] in item["acceptable_primary_families"]
            ),
            len(records),
        ),
        "calibration_by_confidence_band": calibration_by_band(records),
    }


def decision_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    clear = [item for item in records if item["classification_decision"] == "clear_match"]
    hybrid = [item for item in records if item["classification_decision"] == "hybrid_match"]
    review_pred = [item for item in records if item["classification_requires_review"]]
    review_expected = [item for item in records if _expected_review(item)]
    close_expected = [
        item for item in records
        if item["expected_tailoring_action"] == "review_required"
        or item["expected_primary_family"] is None
    ]
    return {
        "clear_match_precision": rate(sum(1 for item in clear if item["selected_ok"]), len(clear)),
        "hybrid_match_precision": rate(
            sum(1 for item in hybrid if item["selected_ok"]), len(hybrid)
        ),
        "review_flag_precision": rate(
            sum(1 for item in review_pred if _expected_review(item)), len(review_pred)
        ),
        "review_flag_recall": rate(
            sum(1 for item in review_expected if item["classification_requires_review"]),
            len(review_expected),
        ),
        "close_match_review_recall": rate(
            sum(1 for item in close_expected if item["classification_requires_review"]),
            len(close_expected),
        ),
        "low_confidence_detection_rate": rate(
            sum(
                1 for item in records
                if item["classification_decision"] == "low_confidence"
                and item["expected_primary_family"] is None
            ),
            sum(1 for item in records if item["expected_primary_family"] is None),
        ),
    }


def tailoring_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    swaps = [item for item in records if item["actual_tailoring_action"] == "one_swap"]
    expected_swaps = [
        item for item in records if item["expected_tailoring_action"] == "one_swap"
    ]
    no_tailoring_expected = [
        item for item in records if item["expected_tailoring_action"] != "one_swap"
    ]
    return {
        "correct_no_tailoring_rate": rate(
            sum(
                1 for item in no_tailoring_expected
                if item["actual_tailoring_action"] != "one_swap"
            ),
            len(no_tailoring_expected),
        ),
        "correct_substitution_rate": rate(
            sum(1 for item in expected_swaps if item["tailoring_action_ok"]),
            len(expected_swaps),
        ),
        "unnecessary_substitution_rate": rate(
            sum(1 for item in records if item["unnecessary_substitution"]), len(records)
        ),
        "invalid_substitution_rate": rate(
            sum(1 for item in records if item["invalid_substitution"]), len(records)
        ),
        "expected_inserted_block_match_rate": rate(
            sum(1 for item in swaps if item["tailoring_action_ok"]), len(swaps)
        ),
        "fallback_rate": rate(
            sum(1 for item in records if item["tailoring_status"] == "fallback_to_master"),
            len(records),
        ),
        "one_page_validation_mode": "structural_bulk_no_pdf_compile",
    }


def calibration_by_band(records: list[dict[str, Any]]) -> dict[str, Any]:
    bands = {
        "high": lambda item: item["classification_decision"] == "clear_match",
        "medium": lambda item: item["classification_decision"] == "hybrid_match",
        "low": lambda item: item["classification_requires_review"],
    }
    result = {}
    for band, predicate in bands.items():
        values = [item for item in records if predicate(item)]
        result[band] = {
            "count": len(values),
            "accuracy": rate(sum(1 for item in values if item["selected_ok"]), len(values)),
        }
    return result


def search_parameters(
    dataset_path: Path | str = DEFAULT_DATASET_PATH,
    *,
    semantic_mode: str = "deterministic",
) -> dict[str, Any]:
    baseline_classifier = load_classifier_config()
    baseline_policy = load_tailoring_policy()
    baseline = evaluate(
        dataset_path=dataset_path,
        classifier_config=baseline_classifier,
        tailoring_policy=baseline_policy,
        semantic_mode=semantic_mode,
    )
    candidates = []
    for classifier, policy in candidate_configs(baseline_classifier, baseline_policy):
        report = evaluate(
            dataset_path=dataset_path,
            classifier_config=classifier,
            tailoring_policy=policy,
            semantic_mode=semantic_mode,
        )
        candidates.append({
            "objective": objective(report["metrics"]["train"]),
            "classifier_config": classifier,
            "tailoring_policy": policy,
            "report": report,
        })
    candidates.sort(key=lambda item: item["objective"], reverse=True)
    best = candidates[0] if candidates else None
    gates = acceptance_gates(
        baseline["metrics"]["holdout"],
        best["report"]["metrics"]["holdout"] if best else baseline["metrics"]["holdout"],
    )
    return {
        "baseline": baseline,
        "best_candidate": best,
        "acceptance_gates": gates,
        "promotion_decision": {
            "promote": bool(best and gates["passed"] and best["objective"] > objective(
                baseline["metrics"]["train"]
            )),
            "reason": "Candidate must improve train objective and pass holdout safety gates.",
        },
    }


def candidate_configs(
    classifier: dict[str, Any],
    tailoring_policy: dict[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    clear_scores = [0.65, 0.68]
    clear_margins = [0.25, 0.28]
    close_margins = [0.12, 0.15]
    low_scores = [0.40, 0.44]
    replacement_gains = [0.15, 0.25]
    result = []
    for clear_score in clear_scores:
        for clear_margin in clear_margins:
            for close_margin in close_margins:
                for low_score in low_scores:
                    for gain in replacement_gains:
                        candidate_classifier = copy.deepcopy(classifier)
                        thresholds = candidate_classifier["decision_thresholds"]
                        thresholds["clear_min_score"] = clear_score
                        thresholds["clear_min_margin"] = clear_margin
                        thresholds["close_max_margin"] = close_margin
                        thresholds["low_confidence_max_score"] = low_score
                        candidate_policy = copy.deepcopy(tailoring_policy)
                        candidate_policy["minimum_replacement_gain"] = gain
                        candidate_policy["clear_match_tailoring_gain"] = max(0.2, gain)
                        result.append((candidate_classifier, candidate_policy))
    return result


def objective(metrics: dict[str, Any]) -> tuple[float, float, float, float, float]:
    family = metrics.get("family_classification", {})
    decision = metrics.get("decision_behavior", {})
    tailoring = metrics.get("tailoring_behavior", {})
    safety = metrics.get("safety", {})
    return (
        -100.0 * float(safety.get("wrong_high_confidence_rate", 0.0)),
        -25.0 * float(tailoring.get("unnecessary_substitution_rate", 0.0)),
        10.0 * float(family.get("macro_f1", 0.0)),
        3.0 * float(decision.get("hybrid_match_precision", 0.0)),
        -1.0 * abs(float(decision.get("review_flag_recall", 0.0)) - 0.8),
    )


def acceptance_gates(
    baseline_holdout: dict[str, Any],
    candidate_holdout: dict[str, Any],
) -> dict[str, Any]:
    baseline_f1 = baseline_holdout["family_classification"]["macro_f1"]
    candidate_f1 = candidate_holdout["family_classification"]["macro_f1"]
    gates = {
        "macro_f1_no_regression": candidate_f1 >= baseline_f1,
        "wrong_high_confidence_rate_max_0": (
            candidate_holdout["safety"]["wrong_high_confidence_rate"] == 0.0
        ),
        "no_invalid_substitutions": (
            candidate_holdout["tailoring_behavior"]["invalid_substitution_rate"] == 0.0
        ),
        "unnecessary_substitution_rate_max_0_05": (
            candidate_holdout["tailoring_behavior"]["unnecessary_substitution_rate"] <= 0.05
        ),
        "out_of_scope_review_rate_min_0_80": (
            candidate_holdout["safety"]["out_of_scope_review_rate"] >= 0.8
        ),
    }
    return {
        "gates": gates,
        "passed": all(gates.values()),
        "baseline_macro_f1": baseline_f1,
        "candidate_macro_f1": candidate_f1,
    }


def write_reports(
    result: dict[str, Any],
    output_dir: Path | str = DEFAULT_REPORT_DIR,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "phase_e_calibration_report.json"
    md_path = output / "phase_e_calibration_report.md"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown_report(result), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def render_markdown_report(result: dict[str, Any]) -> str:
    baseline = result["baseline"]
    candidate = result.get("best_candidate")
    gates = result["acceptance_gates"]
    baseline_holdout = baseline["metrics"]["holdout"]
    candidate_holdout = (
        candidate["report"]["metrics"]["holdout"] if candidate else baseline_holdout
    )
    candidate_report = candidate["report"] if candidate else baseline
    lines = [
        "# Phase E Calibration Report",
        "",
        f"Generated: {utc_now_iso()}",
        f"Dataset: {baseline['dataset_id']} ({baseline['dataset_version']})",
        f"Semantic mode: {baseline['semantic_mode']}",
        "",
        "## Dataset",
        f"- Total examples: {baseline['dataset_summary']['total']}",
        f"- Train: {baseline['dataset_summary']['splits']['train']}",
        f"- Holdout: {baseline['dataset_summary']['splits']['holdout']}",
        f"- Categories: {json.dumps(baseline['dataset_summary']['categories'], sort_keys=True)}",
        "",
        "## Baseline Holdout Metrics",
        _metrics_summary(baseline_holdout),
        "",
        "## Baseline Configuration",
        _configuration_summary(
            baseline["classifier_config"], baseline["tailoring_policy"]
        ),
        "",
        "## Candidate Holdout Metrics",
        _metrics_summary(candidate_holdout),
        "",
        "## Candidate Configuration",
        _configuration_summary(
            candidate_report["classifier_config"],
            candidate_report["tailoring_policy"],
        ),
        "",
        "## Holdout Failure Cases",
        _failure_summary(candidate_report),
        "",
        "## Acceptance Gates",
        *[f"- {key}: {value}" for key, value in gates["gates"].items()],
        f"- Overall: {gates['passed']}",
        "",
        "## Promotion Decision",
        f"- Promote: {result['promotion_decision']['promote']}",
        f"- Reason: {result['promotion_decision']['reason']}",
        "",
        "## Limitations",
        "- Dataset examples are concise synthetic/paraphrased role patterns.",
        "- Bulk tailoring evaluation is structural and does not compile every PDF.",
        "- Live semantic evaluation was not run unless semantic_mode is live.",
    ]
    return "\n".join(lines) + "\n"


def _configuration_summary(
    classifier_config: dict[str, Any],
    tailoring_policy: dict[str, Any],
) -> str:
    return "\n".join([
        f"- Classifier config version: {classifier_config['config_version']}",
        f"- Decision thresholds: {json.dumps(classifier_config['decision_thresholds'])}",
        f"- Combination weights: {json.dumps(classifier_config['combination'])}",
        f"- Tailoring policy version: {tailoring_policy['policy_version']}",
        f"- Minimum replacement gain: {tailoring_policy['minimum_replacement_gain']}",
        f"- Clear-match replacement gain: {tailoring_policy['clear_match_tailoring_gain']}",
        f"- Dominant-family margin: {tailoring_policy['dominant_family_margin']}",
    ])


def _failure_summary(report: dict[str, Any]) -> str:
    holdout = [item for item in report["records"] if item["split"] == "holdout"]
    wrong_high = [
        item["example_id"] for item in holdout if item["wrong_high_confidence_no_review"]
    ]
    review = [
        item["example_id"] for item in holdout if item["classification_requires_review"]
    ][:10]
    tailoring_errors = [
        item["example_id"] for item in holdout
        if item["invalid_substitution"] or item["unnecessary_substitution"]
    ]
    missed_swaps = [
        item["example_id"] for item in holdout
        if item["expected_tailoring_action"] == "one_swap"
        and item["actual_tailoring_action"] != "one_swap"
    ]
    return "\n".join([
        f"- Wrong high-confidence no-review examples: {wrong_high or 'none'}",
        f"- Review-flagged examples: {review or 'none'}",
        f"- Tailoring safety errors: {tailoring_errors or 'none'}",
        f"- Expected swaps missed: {missed_swaps or 'none'}",
    ])


def dataset_summary(examples: list[LabelledExample]) -> dict[str, Any]:
    categories: dict[str, int] = {}
    splits = {"train": 0, "holdout": 0}
    for example in examples:
        categories[example.category] = categories.get(example.category, 0) + 1
        splits[example.split] += 1
    return {"total": len(examples), "categories": categories, "splits": splits}


def validate_tailoring_policy_compliance(
    decision: dict[str, Any],
    registry: dict[str, Any],
) -> None:
    removed = decision.get("removed_block")
    inserted = decision.get("inserted_block")
    if removed and inserted:
        validate_replacement_pair(decision["base_family"], removed, inserted, registry)


def tailoring_action(decision: dict[str, Any]) -> str:
    if decision.get("tailoring_status") == "fallback_to_master":
        return "fallback_to_master"
    if decision.get("inserted_block"):
        return "one_swap"
    if decision.get("tailoring_status") == "review_required":
        return "review_required"
    return "master_unchanged"


def tailoring_action_matches(example: LabelledExample, decision: dict[str, Any]) -> bool:
    action = tailoring_action(decision)
    expected = example.expected_tailoring_action
    if expected == "any_no_auto":
        return action != "one_swap"
    if expected != action:
        return False
    inserted = decision.get("inserted_block")
    if expected == "one_swap" and example.acceptable_inserted_blocks:
        return inserted in example.acceptable_inserted_blocks
    if inserted and inserted in example.unacceptable_inserted_blocks:
        return False
    return True


def rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def _metrics_summary(metrics: dict[str, Any]) -> str:
    family = metrics["family_classification"]
    safety = metrics["safety"]
    tailoring = metrics["tailoring_behavior"]
    return "\n".join([
        f"- Macro F1: {family['macro_f1']}",
        f"- Primary accuracy: {family['primary_accuracy']}",
        f"- Wrong high-confidence no-review rate: {safety['wrong_high_confidence_rate']}",
        f"- Out-of-scope review rate: {safety['out_of_scope_review_rate']}",
        f"- Unnecessary substitution rate: {tailoring['unnecessary_substitution_rate']}",
        f"- Invalid substitution rate: {tailoring['invalid_substitution_rate']}",
    ])


def _semantic_provider(mode: str) -> Any:
    if mode == "deterministic":
        return None
    if mode == "fake":
        return fake_semantic_provider
    if mode == "live":
        if not os.getenv("JOBAGENT_LLM_API_KEY"):
            return None
        return LLMFamilySemanticProvider()
    raise CalibrationError("semantic mode must be deterministic, fake, or live")


def fake_semantic_provider(
    job: dict[str, Any],
    structured_jd: dict[str, Any],
    deterministic: dict[str, float],
) -> dict[str, Any]:
    return {
        "family_scores": deterministic,
        "semantic_evidence": [{
            "source": "fake_semantic_provider",
            "title": job.get("title") or structured_jd.get("title"),
        }],
    }


def _config_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "classifier_version": config["classifier_version"],
        "config_version": config["config_version"],
        "section_weights": config["section_weights"],
        "combination": config["combination"],
        "decision_thresholds": config["decision_thresholds"],
    }


def _tailoring_summary(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_version": policy["policy_version"],
        "minimum_replacement_gain": policy["minimum_replacement_gain"],
        "clear_match_tailoring_gain": policy["clear_match_tailoring_gain"],
        "dominant_family_margin": policy["dominant_family_margin"],
        "score_weights": policy["score_weights"],
    }


def _required_string(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CalibrationError(f"example {index} requires non-empty {key}")
    return value


def _string_list(value: Any, name: str, example_id: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CalibrationError(f"example {example_id} {name} must be a string list")
    return value


def _validate_families(values: list[str], example_id: str) -> None:
    unknown = sorted(set(values) - set(FAMILY_IDS))
    if unknown:
        raise CalibrationError(f"example {example_id} references unknown family {unknown[0]}")


def _expected_review(item: dict[str, Any]) -> bool:
    return bool(item["expected_requires_review"] or item["expected_primary_family"] is None)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python3 -m jobagent_v2.calibration")
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    evaluate_parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR))
    evaluate_parser.add_argument(
        "--semantic-mode",
        choices=["deterministic", "fake", "live"],
        default="deterministic",
    )
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        result = search_parameters(args.dataset, semantic_mode=args.semantic_mode)
        paths = write_reports(result, args.output_dir)
        print(json.dumps({"reports": paths, "promotion": result["promotion_decision"]}))


if __name__ == "__main__":
    main()
