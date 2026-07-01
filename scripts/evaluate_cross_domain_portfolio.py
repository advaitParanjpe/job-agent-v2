#!/usr/bin/env python3
"""Offline invariant evaluation for requirement-aware project selection."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from jobagent_v2.project_blocks import load_project_block_registry  # noqa: E402
from jobagent_v2.requirements import extract_requirements, score_project_portfolio  # noqa: E402
from jobagent_v2.tailoring import load_tailoring_policy, select_tailoring_decision  # noqa: E402


DATASET = (
    BACKEND_SRC
    / "jobagent_v2"
    / "data"
    / "evaluation"
    / "cross_domain_project_selection.json"
)


def main() -> int:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    registry = load_project_block_registry()
    policy = load_tailoring_policy()
    records = []
    failures = []
    for example in data["examples"]:
        job = _job(example)
        analysis = extract_requirements(job)
        portfolio = score_project_portfolio(
            base_family=example["base_family"],
            registry=registry,
            requirement_analysis=analysis,
        )
        decision = select_tailoring_decision(
            packet_id=f"eval-{example['example_id']}",
            job=job,
            base_family=example["base_family"],
            registry=registry,
            policy=policy,
        )
        shortlist = set(portfolio["shortlist"])
        expected = set(example.get("expected_shortlist", []))
        unexpected = set(example.get("unexpected_shortlist", []))
        record = {
            "example_id": example["example_id"],
            "base_family": example["base_family"],
            "tailoring_status": decision["tailoring_status"],
            "shortlist": sorted(shortlist),
            "expected_recall": sorted(expected & shortlist),
            "unexpected_hits": sorted(unexpected & shortlist),
        }
        records.append(record)
        if not expected <= shortlist:
            failures.append(f"{example['example_id']}: missing {sorted(expected - shortlist)}")
        if unexpected & shortlist:
            failures.append(
                f"{example['example_id']}: unexpected {sorted(unexpected & shortlist)}"
            )
        if decision["tailoring_status"] not in set(example["expected_statuses"]):
            failures.append(
                f"{example['example_id']}: status {decision['tailoring_status']} not expected"
            )
    metrics = {
        "dataset_version": data["dataset_version"],
        "examples": len(records),
        "shortlist_recall": round(
            sum(1 for record in records if record["expected_recall"]) / len(records), 4
        ),
        "unexpected_shortlist_rate": round(
            sum(1 for record in records if record["unexpected_hits"]) / len(records), 4
        ),
        "failures": failures,
        "records": records,
    }
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 1 if failures else 0


def _job(example: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": example["example_id"],
        "selected_cv_family": example["base_family"],
        "title": example["title"],
        "jd_text": example["description"],
        "structured_jd": {
            "title": example["title"],
            "responsibilities": [example["description"]],
            "must_have_requirements": [example["description"]],
            "nice_to_have_requirements": [],
            "skills": [],
            "technologies": [],
            "domains": [],
            "keywords": [],
        },
        "family_classification": {
            "decision": "clear_match",
            "requires_review": False,
            "classifier_version": "phase-b-family-classifier-v1",
            "family_scores": {
                "digital_ic": 0.8 if example["base_family"] == "digital_ic" else 0.05,
                "verification": 0.8 if example["base_family"] == "verification" else 0.05,
                "software": 0.8 if example["base_family"] == "software" else 0.05,
                "ml": 0.8 if example["base_family"] == "ml" else 0.05,
            },
            "selected_family": example["base_family"],
            "secondary_family": None,
            "confidence": 0.8,
            "rule_evidence": [],
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
