from __future__ import annotations

import json
from pathlib import Path

from jobagent_v2.service import JobService
from jobagent_v2.workers import DummyQ1Worker, DummyQ2Worker


def test_q2_generates_truthful_packet_and_is_idempotent(
    service: JobService, repository, artifact_root: Path, created_job
) -> None:
    scored = DummyQ1Worker(repository).process_next()
    assert scored is not None and scored["intake_status"] == "scored"
    service.generate_now(str(created_job["id"]))

    result = DummyQ2Worker(repository, artifact_root).process_next()
    assert result is not None and result["packet_status"] == "ready"
    packet = service.get_packet_for_job(str(created_job["id"]))["packet"]
    assert packet is not None and packet["status"] == "ready"
    assert Path(packet["pdf_path"]).read_bytes().startswith(b"%PDF")
    manifest = json.loads(Path(packet["manifest_path"]).read_text(encoding="utf-8"))
    selected = json.loads(Path(packet["selected_cv_path"]).read_text(encoding="utf-8"))
    assert manifest["section_order"] == selected["section_order"]
    assert manifest["truth_bank_version"] == selected["truth_bank_version"]
    assert all(item["selected"] for item in manifest["selected_blocks"])
    assert DummyQ2Worker(repository, artifact_root).process_next() is None


def test_missing_persisted_scoring_input_fails_visibly(
    service: JobService, repository, artifact_root: Path
) -> None:
    created = service.create_job({
        "url": "https://example.com/jobs/missing-packet-input",
        "page_title": "RTL Engineer",
        "visible_text": "Responsibilities\nRTL\nQualifications\nVerilog",
        "source_site": "example.com", "captured_at": "2026-06-20T12:00:00Z",
    })
    job_id = str(created["job_id"])
    with repository.connect() as connection:
        repository._update_job(connection, job_id, {"intake_status": "scored", "overall_score": 90,
                                                     "hard_blockers_json": "[]"})
    service.generate_now(job_id)
    result = DummyQ2Worker(repository, artifact_root).process_next()
    assert result is not None and result["packet_status"] == "failed"
    packet = service.get_packet_for_job(job_id)["packet"]
    assert packet is not None and packet["failure_stage"] == "validate_inputs"
