from __future__ import annotations

from pathlib import Path

import pytest

from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository
from jobagent_v2.worker_runner import StopSignal, WorkerRunner, WorkerRunnerConfig


def _config() -> WorkerRunnerConfig:
    return WorkerRunnerConfig(
        q1_poll_seconds=0.1,
        q2_poll_seconds=0.1,
        regeneration_poll_seconds=0.1,
        idle_backoff_max_seconds=0.4,
        health_heartbeat_seconds=10.0,
    )


def test_empty_queue_reports_idle_and_backoff(
    repository: Repository,
    artifact_root: Path,
) -> None:
    sleeps: list[float] = []
    signal = StopSignal()
    runner = WorkerRunner(
        repository=repository,
        artifact_root=artifact_root,
        worker_type="q1",
        config=_config(),
        instance_id="q1-test",
        sleep=lambda seconds: (sleeps.append(seconds), signal.request_stop()),
        stop_signal=signal,
    )

    runner.run_forever()
    worker = repository.list_worker_instances("q1")[0]

    assert sleeps == [0.1]
    assert worker["state"] == "stopped"
    assert worker["processed_count"] == 0


def test_q1_runner_processes_work_once(
    service: JobService,
    repository: Repository,
    artifact_root: Path,
    capture_payload: dict[str, str],
) -> None:
    created = service.create_job(capture_payload)
    runner = WorkerRunner(
        repository=repository,
        artifact_root=artifact_root,
        worker_type="q1",
        config=_config(),
        instance_id="q1-work",
    )

    assert runner.run_once() is True
    assert runner.run_once() is False
    worker = repository.list_worker_instances("q1")[0]
    job = service.get_job(str(created["job_id"]))["job"]

    assert job["intake_status"] == "scored"
    assert worker["processed_count"] == 1
    assert worker["last_completed_job_id"] == created["job_id"]


def test_worker_failure_is_isolated(
    repository: Repository,
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_process(_self):
        raise RuntimeError("boom /tmp/private-path")

    monkeypatch.setattr("jobagent_v2.workers.Queue1Worker.process_next", fail_process)
    runner = WorkerRunner(
        repository=repository,
        artifact_root=artifact_root,
        worker_type="q1",
        config=_config(),
        instance_id="q1-fail",
    )

    assert runner.run_once() is False
    worker = repository.list_worker_instances("q1")[0]

    assert worker["state"] == "unhealthy"
    assert worker["failure_count"] == 1
    assert worker["last_failure_code"] == "worker_unhandled_error"
    assert "[path]" in worker["last_failure_reason"]


def test_worker_status_reports_queue_degraded_without_worker(
    service: JobService,
    capture_payload: dict[str, str],
) -> None:
    service.create_job(capture_payload)

    status = service.worker_status()

    assert status["queues"]["q1"]["queued_count"] == 1
    assert status["queue_health"]["q1"]["health"] == "degraded"
    assert "queued_work_without_healthy_worker" in status["queue_health"]["q1"]["warnings"]


def test_worker_status_reports_idle_worker(
    service: JobService,
    repository: Repository,
    artifact_root: Path,
) -> None:
    runner = WorkerRunner(
        repository=repository,
        artifact_root=artifact_root,
        worker_type="q1",
        config=_config(),
        instance_id="q1-idle",
    )
    runner.run_once()

    status = service.worker_status("q1")

    assert status["workers"][0]["health"] == "idle"
    assert status["queue_health"]["q1"]["health"] == "idle"


def test_unknown_worker_type_rejected(service: JobService) -> None:
    with pytest.raises(ValueError, match="unknown worker type"):
        service.worker_status("unknown")
