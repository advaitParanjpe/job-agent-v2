#!/usr/bin/env python3
"""Explicit, one-job live semantic smoke test; never called by scripts/check.py."""

from __future__ import annotations

import argparse

from jobagent_v2.config import load_local_env
from jobagent_v2.hybrid_scoring import score_hybrid_job
from jobagent_v2.llm_client import LLMConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one explicit live semantic scoring call")
    parser.add_argument("--live", action="store_true", help="Allow a provider request")
    args = parser.parse_args()
    load_local_env()
    config = LLMConfig.from_env()
    if not args.live:
        raise SystemExit("Pass --live to allow a provider request.")
    if not config.enabled or not config.api_key:
        raise SystemExit("Set JOBAGENT_LLM_ENABLED=true and JOBAGENT_LLM_API_KEY in .env.local.")
    result = score_hybrid_job({
        "title": "RTL Engineer", "company": "Smoke Test", "location": "Austin, TX",
        "jd_text": "Responsibilities\nDesign SystemVerilog RTL for ASIC products.\n"
        "Qualifications\nVerilog, SystemVerilog, RTL, ASIC, and Python experience.",
    })
    diagnostics = result.score_breakdown["hybrid"]
    print(f"scoring_mode={diagnostics['scoring_mode']}")
    print(f"llm_call_status={diagnostics['llm_call_status']}")
    print(f"model={diagnostics['model']}")
    print(f"prompt_version={diagnostics['prompt_version']}")
    print(f"overall_score={result.overall_score}")


if __name__ == "__main__":
    main()
