from __future__ import annotations

import json
from pathlib import Path

from jobagent_v2.master_cvs import discover_master_cvs
from jobagent_v2.regeneration_worker import ReviewRegenerationWorker
from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository
from jobagent_v2.workers import DummyQ1Worker, DummyQ2Worker


def _make_ready_packet(
    service: JobService,
    repository: Repository,
    artifact_root: Path,
    capture_payload: dict[str, str],
) -> tuple[str, str]:
    payload = dict(capture_payload)
    payload["url"] = "https://example.com/regeneration-base"
    created = service.create_job(payload)
    DummyQ1Worker(repository).process_next()
    service.generate_now(str(created["job_id"]))
    DummyQ2Worker(repository, artifact_root).process_next()
    packet = service.get_packet_for_job(str(created["job_id"]))["packet"]
    return str(created["job_id"]), str(packet["packet_id"])


def test_regeneration_job_claiming_is_atomic(
    service: JobService,
    repository: Repository,
    artifact_root: Path,
    capture_payload: dict[str, str],
) -> None:
    job_id, _packet_id = _make_ready_packet(service, repository, artifact_root, capture_payload)
    review = service.create_review(
        job_id, {"review_type": "classification", "reason": "wrong_family_reported"}
    )["review"]
    resolved = service.resolve_review(
        review["review_id"],
        {"action": "override_family", "resolved_family": "software", "reviewer_id": "tester"},
    )["review"]

    first = repository.claim_next_regeneration_job(
        owner="worker-a", lease_expires_at="2099-01-01T00:00:00+00:00"
    )
    second = repository.claim_next_regeneration_job(
        owner="worker-b", lease_expires_at="2099-01-01T00:00:00+00:00"
    )

    assert first is not None
    assert first["review_resolution_id"] == resolved["resolution"]["resolution_id"]
    assert second is None


def test_regeneration_master_override_creates_linked_packet_once(
    service: JobService,
    repository: Repository,
    artifact_root: Path,
    capture_payload: dict[str, str],
) -> None:
    job_id, source_packet_id = _make_ready_packet(
        service, repository, artifact_root, capture_payload
    )
    review = service.create_review(
        job_id, {"review_type": "classification", "reason": "wrong_family_reported"}
    )["review"]
    service.resolve_review(
        review["review_id"],
        {"action": "override_family", "resolved_family": "software", "reviewer_id": "tester"},
    )

    worker = ReviewRegenerationWorker(repository, artifact_root)
    first = worker.process_next()
    second = worker.process_next()
    resolved = service.get_review(review["review_id"])["review"]
    packet = resolved["reviewed_packet"]
    master = {record.family_id: record for record in discover_master_cvs()}["software"]

    assert first is not None
    assert second is None
    assert packet["status"] == "ready"
    assert packet["generation_kind"] == "review_regeneration"
    assert packet["source_packet_id"] == source_packet_id
    assert Path(packet["tex_path"]).read_text(encoding="utf-8") == Path(
        master.tex_path
    ).read_text(encoding="utf-8")
    assert Path(packet["pdf_path"]).read_bytes() == Path(master.pdf_path).read_bytes()
    assert resolved["resolution"]["regeneration_status"] == "complete"
    assert resolved["original_packet"]["packet_id"] == source_packet_id


def test_regeneration_reuses_existing_success_for_same_resolution(
    service: JobService,
    repository: Repository,
    artifact_root: Path,
    capture_payload: dict[str, str],
) -> None:
    job_id, _source_packet_id = _make_ready_packet(
        service, repository, artifact_root, capture_payload
    )
    review = service.create_review(
        job_id, {"review_type": "classification", "reason": "wrong_family_reported"}
    )["review"]
    service.resolve_review(
        review["review_id"],
        {"action": "override_family", "resolved_family": "software", "reviewer_id": "tester"},
    )
    worker = ReviewRegenerationWorker(repository, artifact_root)
    worker.process_next()
    first_packet = service.get_review(review["review_id"])["review"]["reviewed_packet"]
    with repository.connect() as connection:
        connection.execute(
            "UPDATE review_regeneration_jobs SET status='queued', generated_packet_id=NULL"
        )
        connection.execute(
            "UPDATE review_resolutions SET regeneration_status='queued', "
            "regeneration_packet_id=NULL"
        )
    worker.process_next()
    second_packet = service.get_review(review["review_id"])["review"]["reviewed_packet"]

    assert second_packet["packet_id"] == first_packet["packet_id"]


def test_regeneration_approved_replacement_builds_tailored_packet(
    service: JobService,
    repository: Repository,
    artifact_root: Path,
    capture_payload: dict[str, str],
    monkeypatch,
) -> None:
    job_id, source_packet_id = _make_ready_packet(
        service, repository, artifact_root, capture_payload
    )
    review = service.create_review(
        job_id, {"review_type": "tailoring", "reason": "wrong_project_reported"}
    )["review"]
    service.resolve_review(
        review["review_id"],
        {
            "action": "select_approved_replacement",
            "resolved_family": "digital_ic",
            "removed_block": "sparrow_cluster_digital_ic_v1",
            "inserted_block": "sparrowml_ml_v1",
            "reviewer_id": "tester",
        },
    )

    def fake_compile(tex: str, output_dir: Path, timeout_seconds: int = 30):
        pdf = output_dir / "cv.pdf"
        pdf.write_bytes(b"%PDF reviewed")
        return pdf, "fake reviewed compile", 1

    monkeypatch.setattr("jobagent_v2.regeneration_worker.compile_pdf", fake_compile)
    worker = ReviewRegenerationWorker(repository, artifact_root)
    worker.process_next()
    resolved = service.get_review(review["review_id"])["review"]
    packet = resolved["reviewed_packet"]
    selected = json.loads(Path(packet["selected_cv_path"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(packet["manifest_path"]).read_text(encoding="utf-8"))

    assert packet["source_packet_id"] == source_packet_id
    assert Path(packet["pdf_path"]).read_bytes() == b"%PDF reviewed"
    assert selected["project_blocks"]["final_blocks"].count("sparrowml_ml_v1") == 1
    assert manifest["source_packet_id"] == source_packet_id
    assert manifest["review_resolution_id"] == resolved["resolution"]["resolution_id"]
