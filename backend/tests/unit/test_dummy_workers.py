from __future__ import annotations

from pathlib import Path

from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository
from jobagent_v2.workers import DummyQ1Worker, DummyQ2Worker


def test_dummy_q1_is_deterministic(
    repository: Repository,
    created_job: dict[str, object],
) -> None:
    worker = DummyQ1Worker(repository)

    processed = worker.process_next()
    second = worker.process_next()

    assert processed is not None
    assert processed["id"] == created_job["id"]
    assert processed["intake_status"] == "scored"
    assert processed["overall_score"] is None
    assert "Phase 1 dummy processing" in str(processed["reason"])
    assert second is None


def test_dummy_q2_is_idempotent(
    service: JobService,
    repository: Repository,
    artifact_root: Path,
    created_job: dict[str, object],
) -> None:
    service.generate_now(str(created_job["id"]))
    worker = DummyQ2Worker(repository, artifact_root)

    processed = worker.process_next()
    second = worker.process_next()

    assert processed is not None
    assert processed["packet_status"] == "ready"
    assert processed["placeholder_artifact_path"] is not None
    assert Path(str(processed["placeholder_artifact_path"])).exists()
    assert second is None

