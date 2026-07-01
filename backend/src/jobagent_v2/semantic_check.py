"""Explicit semantic diagnostic that never touches the jobs database."""

from __future__ import annotations

import argparse
import sys
from time import perf_counter
from typing import Any

from jobagent_v2.config import RuntimeConfig, load_local_env
from jobagent_v2.hybrid_scoring import score_hybrid_job
from jobagent_v2.llm_client import LLMConfig, SemanticLLMClient


SYNTHETIC_JOB = {
    "company": "Synthetic",
    "title": "Verification Infrastructure Engineer",
    "location": "Remote",
    "jd_text": (
        "Responsibilities\n"
        "Develop UVM regressions, scoreboards, waveform triage tools, "
        "and pre-silicon validation flows.\n"
        "Build Python infrastructure for regression dashboards and debug automation.\n"
        "Qualifications\n"
        "SystemVerilog, UVM, functional coverage, Python, and CI experience.\n"
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one explicit semantic classification diagnostic."
    )
    parser.add_argument(
        "--no-network", action="store_true", help="Use deterministic fake transport."
    )
    args = parser.parse_args(argv)
    load_local_env()
    runtime = RuntimeConfig.from_env()
    if args.no_network:
        client = SemanticLLMClient(
            LLMConfig(True, "fake-key", runtime.semantic_model, 1, 0),
            _fake_transport,
        )
    else:
        if not runtime.semantic_enabled:
            print(
                "Semantic check failed: JOBAGENT_LLM_ENABLED=false. "
                "Enable it in .env.local to run live."
            )
            return 1
        if not runtime.semantic_api_key_present:
            print(
                "Semantic check failed: JOBAGENT_LLM_API_KEY is missing. "
                "The key was not printed."
            )
            return 1
        print("This command sends one small provider request and may incur provider cost.")
        client = SemanticLLMClient()
    start = perf_counter()
    result = score_hybrid_job(SYNTHETIC_JOB, client)
    elapsed = round((perf_counter() - start) * 1000)
    hybrid = result.score_breakdown.get("hybrid", {})
    status = hybrid.get("semantic_status")
    assessment = hybrid.get("semantic_assessment") or {}
    evidence_count = len(assessment.get("requirement_block_matches") or []) + len(
        assessment.get("semantic_block_assessments") or []
    )
    print(f"status: {status}")
    print(f"model: {hybrid.get('model')}")
    print(f"latency_ms: {hybrid.get('latency_ms') or elapsed}")
    print(f"selected_family: {result.selection.get('primary_family')}")
    print(f"semantic_evidence_count: {evidence_count}")
    if status != "live_success":
        print(f"failure: {hybrid.get('failure_code') or hybrid.get('llm_call_status')}")
        return 1
    return 0


def _fake_transport(prompt: dict[str, Any], _: LLMConfig) -> dict[str, Any]:
    blocks = prompt.get("blocks") or []
    return {
        "role_family_candidates": ["verification", "software"],
        "primary_cv_family": "verification",
        "secondary_cv_family": "software",
        "family_confidence": "high",
        "must_have_requirements": ["UVM", "Python"],
        "nice_to_have_requirements": [],
        "requirement_block_matches": [
            {
                "requirement_id": "req-1",
                "requirement_text": "UVM regressions",
                "matched_block_ids": [item["block_id"] for item in blocks[:1]],
                "match_strength": 4,
                "evidence_summary": "UVM regressions are the core role evidence.",
                "confidence": "high",
            }
        ],
        "semantic_block_assessments": [
            {
                "block_id": item["block_id"],
                "responsibility_match": 4,
                "technical_relevance": 4,
                "evidence_strength": 4,
                "domain_relevance": 4,
                "seniority_relevance": 3,
                "superficial_keyword_risk": 0,
                "reason": "The supplied job text emphasizes UVM and verification flows.",
            }
            for item in blocks
        ],
        "semantic_seniority_fit": 3,
        "domain_alignment": 4,
        "superficial_keyword_matches": ["Python"],
        "strengths": ["UVM regressions", "scoreboards", "waveform triage"],
        "gaps": [],
        "ambiguities": ["Python is supporting infrastructure, not the primary family."],
        "grounded_reason": (
            "Primarily Verification because the role centers on UVM regressions, "
            "scoreboards, waveform triage, and pre-silicon validation. Software "
            "is secondary because Python infrastructure supports the verification workflow."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
