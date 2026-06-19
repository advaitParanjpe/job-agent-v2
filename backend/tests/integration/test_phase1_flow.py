from __future__ import annotations

from pathlib import Path

import pytest

from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository
from jobagent_v2.workers import DummyQ1Worker, DummyQ2Worker


def test_job_persists_and_survives_repository_restart(
    db_path: Path,
    artifact_root: Path,
    capture_payload: dict[str, str],
) -> None:
    first_service = JobService(Repository(db_path), artifact_root)
    created = first_service.create_job(capture_payload)

    restarted_service = JobService(Repository(db_path), artifact_root)
    fetched = restarted_service.get_job(str(created["job_id"]))

    assert fetched["job"]["job_id"] == created["job_id"]
    assert fetched["job"]["intake_status"] == "queued"


def test_event_history_is_persisted(
    service: JobService,
    repository: Repository,
    created_job: dict[str, object],
) -> None:
    DummyQ1Worker(repository).process_next()
    events = service.get_events(str(created_job["id"]))["events"]

    event_types = [event["event_type"] for event in events]
    assert event_types == ["job_created", "q1_extracting", "q1_scoring", "q1_scored"]


def test_dummy_q1_reaches_scored(
    service: JobService,
    repository: Repository,
    created_job: dict[str, object],
) -> None:
    DummyQ1Worker(repository).process_next()

    job = service.get_job(str(created_job["id"]))["job"]
    assert job["intake_status"] == "scored"
    assert job["packet_status"] == "not_requested"


def test_generate_now_and_dummy_q2_reaches_ready(
    service: JobService,
    repository: Repository,
    artifact_root: Path,
    created_job: dict[str, object],
) -> None:
    first = service.generate_now(str(created_job["id"]))["job"]
    second = service.generate_now(str(created_job["id"]))["job"]
    DummyQ2Worker(repository, artifact_root).process_next()

    job = service.get_job(str(created_job["id"]))["job"]
    events = service.get_events(str(created_job["id"]))["events"]

    assert first["packet_status"] == "queued"
    assert second["packet_status"] == "queued"
    assert job["packet_status"] == "ready"
    assert Path(str(job["placeholder_artifact_path"])).exists()
    assert [event["event_type"] for event in events].count("packet_queued") == 1


def test_duplicate_url_returns_existing_job(
    service: JobService,
    capture_payload: dict[str, str],
) -> None:
    first = service.create_job(capture_payload)
    duplicate_payload = {**capture_payload, "url": "https://example.com/jobs/123?a=1&b=2"}
    second = service.create_job(duplicate_payload)

    assert second["duplicate"] is True
    assert second["job_id"] == first["job_id"]
    assert len(service.list_jobs()["jobs"]) == 1


def test_archived_job_is_hidden_from_active_list(
    service: JobService,
    created_job: dict[str, object],
) -> None:
    service.archive(str(created_job["id"]))

    assert service.list_jobs()["jobs"] == []
    assert len(service.list_jobs(include_archived=True)["jobs"]) == 1


def test_worker_restart_does_not_duplicate_completed_work(
    db_path: Path,
    artifact_root: Path,
    capture_payload: dict[str, str],
) -> None:
    service = JobService(Repository(db_path), artifact_root)
    created = service.create_job(capture_payload)
    DummyQ1Worker(Repository(db_path)).process_next()
    service.generate_now(str(created["job_id"]))
    DummyQ2Worker(Repository(db_path), artifact_root).process_next()

    assert DummyQ1Worker(Repository(db_path)).process_next() is None
    assert DummyQ2Worker(Repository(db_path), artifact_root).process_next() is None


def test_retry_rejects_non_recoverable_state(
    service: JobService,
    created_job: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        service.retry(str(created_job["id"]))


def test_retry_resets_failed_intake_state(
    repository: Repository,
    service: JobService,
    created_job: dict[str, object],
) -> None:
    with repository.connect() as connection:
        connection.execute(
            "UPDATE jobs SET intake_status = ? WHERE id = ?",
            ("failed", created_job["id"]),
        )

    retried = service.retry(str(created_job["id"]))["job"]

    assert retried["intake_status"] == "queued"

