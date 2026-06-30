#!/usr/bin/env python3
"""Seed deterministic demo jobs into a non-production local database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
DEFAULT_DEMO_DB = REPO_ROOT / "data" / "demo_jobagent_v2.sqlite3"
DEFAULT_DEMO_ARTIFACTS = REPO_ROOT / "data" / "demo_artifacts"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed deterministic JobAgent demo jobs.")
    parser.add_argument("--db-path", default=str(DEFAULT_DEMO_DB))
    parser.add_argument("--artifact-root", default=str(DEFAULT_DEMO_ARTIFACTS))
    args = parser.parse_args(argv)
    sys.path.insert(0, str(BACKEND_SRC))
    from jobagent_v2.service import JobService
    from jobagent_v2.storage import Repository

    service = JobService(Repository(args.db_path), args.artifact_root)
    created = [service.create_job(payload)["job"] for payload in _payloads()]
    print(json.dumps({"created_jobs": len(created), "db_path": args.db_path}, indent=2))
    return 0


def _payloads() -> list[dict[str, object]]:
    captured_at = "2026-06-30T12:00:00Z"
    examples = [
        (
            "digital-ic",
            "Digital IC RTL Engineer",
            "Design synthesizable SystemVerilog RTL, microarchitecture, synthesis, timing.",
        ),
        (
            "verification",
            "Design Verification Engineer",
            "Build UVM testbenches, assertions, constrained random tests, and coverage.",
        ),
        (
            "software",
            "Backend Software Engineer",
            "Develop Python services, APIs, SQL data models, tests, and observability.",
        ),
        (
            "ml",
            "Machine Learning Engineer",
            "Train PyTorch models, evaluate datasets, deploy inference, and improve metrics.",
        ),
        (
            "hybrid-digital-ml",
            "RTL ML Accelerator Engineer",
            "Implement RTL accelerators for quantized machine learning inference workloads.",
        ),
        (
            "close-verification-software",
            "Simulation Infrastructure Engineer",
            "Maintain Python simulation tooling, CI regressions, UVM flows, and debug dashboards.",
        ),
        (
            "out-of-scope",
            "Sales Operations Manager",
            "Own pricing operations, launch planning, stakeholder updates, and sales enablement.",
        ),
    ]
    return [
        {
            "url": f"https://example.test/demo/{slug}",
            "page_title": title,
            "visible_text": f"{title}\nResponsibilities\n{text}\nQualifications\n{text}",
            "source_site": "example.test",
            "captured_at": captured_at,
            "evidence": {"owner_id": "local"},
        }
        for slug, title, text in examples
    ]


if __name__ == "__main__":
    raise SystemExit(main())
