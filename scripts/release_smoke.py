#!/usr/bin/env python3
"""Deterministic release smoke flow using isolated local data."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"


def main() -> int:
    sys.path.insert(0, str(BACKEND_SRC))
    summary = run_smoke()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def run_smoke() -> dict[str, object]:
    from jobagent_v2.db_status import inspect_database
    from jobagent_v2.service import JobService
    from jobagent_v2.storage import Repository

    with tempfile.TemporaryDirectory(prefix="jobagent-release-smoke-") as raw:
        root = Path(raw)
        db_path = root / "jobagent.sqlite3"
        artifact_root = root / "artifacts"
        repository = Repository(db_path)
        service = JobService(repository, artifact_root)
        db_status = inspect_database(db_path)

        created = service.create_job(_digital_ic_payload())["job"]
        q1_job = service.run_q1_once()["job"]
        assert q1_job is not None, "Queue 1 did not process the smoke job"
        assert q1_job["family_classification"]["selected_family"] == "digital_ic"

        service.generate_now(str(created["job_id"]))
        q2_job = service.run_q2_once()["job"]
        assert q2_job is not None and q2_job["packet_status"] == "ready"
        original_packet = service.get_packet_for_job(str(created["job_id"]))["packet"]
        assert original_packet is not None and original_packet["status"] == "ready"
        assert Path(original_packet["pdf_path"]).read_bytes().startswith(b"%PDF")

        review = service.create_review(
            str(created["job_id"]),
            {"review_type": "classification", "reason": "release_smoke_override"},
        )["review"]
        resolved = service.resolve_review(
            str(review["review_id"]),
            {
                "action": "override_family",
                "resolved_family": "software",
                "reviewer_id": "release-smoke",
            },
        )["review"]
        assert resolved["resolution"]["regeneration_status"] == "queued"

        regen_result = service.run_regeneration_once()
        assert regen_result["processed"] is True
        reviewed = service.get_review(str(review["review_id"]))["review"]
        assert reviewed["resolution"]["regeneration_status"] == "complete"
        reviewed_packet = reviewed["reviewed_packet"]
        assert reviewed_packet is not None and reviewed_packet["status"] == "ready"
        assert reviewed_packet["id"] != original_packet["id"]
        assert reviewed["original_packet"]["id"] == original_packet["id"]
        assert Path(original_packet["pdf_path"]).is_file()
        assert Path(reviewed_packet["pdf_path"]).is_file()

        worker_status = service.worker_status()
        queues = service.queue_status()["queues"]
        return {
            "status": "pass",
            "schema": db_status["schema_version"],
            "job_id": created["job_id"],
            "original_packet_id": original_packet["id"],
            "reviewed_packet_id": reviewed_packet["id"],
            "review_resolution_status": reviewed["resolution"]["regeneration_status"],
            "worker_queue_keys": sorted(worker_status["queues"]),
            "queue_summary_keys": sorted(queues),
        }


def _digital_ic_payload() -> dict[str, object]:
    return {
        "url": "https://example.test/release-smoke/digital-ic",
        "page_title": "Release Smoke RTL Engineer",
        "visible_text": (
            "Release Smoke RTL Engineer\n"
            "Responsibilities\n"
            "Design synthesizable SystemVerilog RTL, review microarchitecture specs, "
            "debug simulation failures, and collaborate with verification engineers.\n"
            "Qualifications\n"
            "Digital logic, computer architecture, Verilog, SystemVerilog, Python, "
            "synthesis, timing closure, and FPGA prototyping experience."
        ),
        "source_site": "example.test",
        "captured_at": "2026-06-30T12:00:00Z",
        "evidence": {"owner_id": "local"},
    }


if __name__ == "__main__":
    raise SystemExit(main())
