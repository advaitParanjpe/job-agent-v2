"""Local continuous worker runner for JobAgent queues."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from jobagent_v2.promotion import PromotionConfig
from jobagent_v2.regeneration_worker import ReviewRegenerationWorker
from jobagent_v2.storage import Repository
from jobagent_v2.util import utc_now_iso
from jobagent_v2.workers import Queue1Worker, Queue2Worker


WORKER_RUNNER_VERSION = "operational-worker-runner-v1"
WORKER_TYPES = {"q1", "q2", "regeneration"}


@dataclass(frozen=True)
class WorkerRunnerConfig:
    q1_poll_seconds: float = 5.0
    q2_poll_seconds: float = 5.0
    regeneration_poll_seconds: float = 5.0
    idle_backoff_max_seconds: float = 30.0
    health_heartbeat_seconds: float = 10.0
    max_consecutive_failures: int = 3

    @classmethod
    def from_env(cls) -> "WorkerRunnerConfig":
        return cls(
            q1_poll_seconds=_float_env("JOBAGENT_Q1_POLL_SECONDS", 5.0),
            q2_poll_seconds=_float_env("JOBAGENT_Q2_POLL_SECONDS", 5.0),
            regeneration_poll_seconds=_float_env(
                "JOBAGENT_REGENERATION_POLL_SECONDS", 5.0
            ),
            idle_backoff_max_seconds=_float_env("JOBAGENT_IDLE_BACKOFF_MAX_SECONDS", 30.0),
            health_heartbeat_seconds=_float_env("JOBAGENT_HEARTBEAT_SECONDS", 10.0),
            max_consecutive_failures=int(os.getenv("JOBAGENT_MAX_CONSECUTIVE_FAILURES", "3")),
        )

    def poll_seconds(self, worker_type: str) -> float:
        return {
            "q1": self.q1_poll_seconds,
            "q2": self.q2_poll_seconds,
            "regeneration": self.regeneration_poll_seconds,
        }[worker_type]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "q1_poll_seconds": self.q1_poll_seconds,
            "q2_poll_seconds": self.q2_poll_seconds,
            "regeneration_poll_seconds": self.regeneration_poll_seconds,
            "idle_backoff_max_seconds": self.idle_backoff_max_seconds,
            "health_heartbeat_seconds": self.health_heartbeat_seconds,
            "max_consecutive_failures": self.max_consecutive_failures,
            "version": WORKER_RUNNER_VERSION,
        }


class StopSignal:
    def __init__(self) -> None:
        self.stop_requested = False

    def request_stop(self, *_args: Any) -> None:
        self.stop_requested = True


class WorkerRunner:
    def __init__(
        self,
        *,
        repository: Repository,
        artifact_root: Path | str,
        worker_type: str,
        config: WorkerRunnerConfig | None = None,
        instance_id: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        stop_signal: StopSignal | None = None,
    ) -> None:
        if worker_type not in WORKER_TYPES:
            raise ValueError("unknown worker type")
        self.repository = repository
        self.artifact_root = Path(artifact_root)
        self.worker_type = worker_type
        self.config = config or WorkerRunnerConfig.from_env()
        self.instance_id = instance_id or f"{worker_type}-{uuid4()}"
        self.sleep = sleep
        self.stop_signal = stop_signal or StopSignal()
        self.poll_seconds = self.config.poll_seconds(worker_type)
        self.idle_sleep = self.poll_seconds
        self._registered = False

    def register(self) -> None:
        self.repository.register_worker_instance(
            worker_type=self.worker_type,
            instance_id=self.instance_id,
            process_id=os.getpid(),
            hostname=socket.gethostname().split(".")[0],
            polling_interval_seconds=self.poll_seconds,
            version=WORKER_RUNNER_VERSION,
        )
        self._registered = True
        self._log("worker_start", "Worker loop starting.", state="starting")

    def run_forever(self) -> None:
        self.register()
        try:
            while not self.stop_signal.stop_requested:
                processed = self.run_once()
                if self.stop_signal.stop_requested:
                    break
                if processed:
                    self.idle_sleep = self.poll_seconds
                    continue
                self.repository.update_worker_instance(
                    instance_id=self.instance_id,
                    state="backing_off",
                    event_type="worker_backoff",
                    message="Worker queue empty; backing off.",
                    metadata={"sleep_seconds": self.idle_sleep},
                )
                self.sleep(self.idle_sleep)
                self.idle_sleep = min(
                    self.config.idle_backoff_max_seconds,
                    max(self.poll_seconds, self.idle_sleep * 2),
                )
        finally:
            self.repository.stop_worker_instance(self.instance_id)
            self._log("worker_stop", "Worker loop stopped.", state="stopped")

    def run_once(self) -> bool:
        if not self._registered:
            self.register()
        if self.stop_signal.stop_requested:
            self.repository.update_worker_instance(
                instance_id=self.instance_id,
                state="stopping",
                event_type="worker_stopping",
                message="Worker stop requested before claiming new work.",
            )
            return False
        self.repository.update_worker_instance(instance_id=self.instance_id, state="idle")
        try:
            processed = self._process_one()
        except Exception as error:  # Defensive isolation for unexpected top-level errors.
            self.repository.update_worker_instance(
                instance_id=self.instance_id,
                state="unhealthy",
                failure_code="worker_unhandled_error",
                failure_reason=str(error),
                increment_failure=True,
                event_type="worker_failure",
                message="Worker iteration failed unexpectedly.",
            )
            self._log(
                "worker_failure",
                "Worker iteration failed unexpectedly.",
                state="unhealthy",
                safe_code="worker_unhandled_error",
            )
            return False
        if processed is None:
            self.repository.update_worker_instance(
                instance_id=self.instance_id,
                state="idle",
                event_type="worker_idle",
                message="Worker found no work.",
            )
            return False
        job_id = _processed_id(processed)
        self.repository.update_worker_instance(
            instance_id=self.instance_id,
            state="idle",
            completed_job_id=job_id,
            increment_processed=True,
            event_type="job_complete",
            message="Worker completed one unit of work.",
            metadata={"worker_type": self.worker_type},
        )
        self._log("job_complete", "Worker completed one unit of work.", job_id=job_id)
        return True

    def _process_one(self) -> dict[str, Any] | None:
        self.repository.update_worker_instance(
            instance_id=self.instance_id,
            state="processing",
            event_type="job_start",
            message="Worker is checking for one unit of work.",
        )
        if self.worker_type == "q1":
            return Queue1Worker(self.repository).process_next()
        if self.worker_type == "q2":
            return Queue2Worker(self.repository, self.artifact_root).process_next()
        worker = ReviewRegenerationWorker(self.repository, self.artifact_root)
        worker.recover_stale()
        return worker.process_next()

    def _log(
        self,
        event_type: str,
        message: str,
        *,
        state: str | None = None,
        job_id: str | None = None,
        safe_code: str | None = None,
    ) -> None:
        payload = {
            "event": event_type,
            "message": message,
            "worker_type": self.worker_type,
            "worker_instance_id": self.instance_id,
            "state": state,
            "job_id": job_id,
            "safe_code": safe_code,
            "timestamp": utc_now_iso(),
        }
        print(json.dumps({key: value for key, value in payload.items() if value is not None}))


def run_all(
    *,
    repository: Repository,
    artifact_root: Path | str,
    config: WorkerRunnerConfig | None = None,
    stop_signal: StopSignal | None = None,
) -> None:
    signal_state = stop_signal or StopSignal()
    runners = [
        WorkerRunner(
            repository=repository,
            artifact_root=artifact_root,
            worker_type=worker_type,
            config=config,
            stop_signal=signal_state,
        )
        for worker_type in ("q1", "q2", "regeneration")
    ]
    for runner in runners:
        runner.register()
    try:
        while not signal_state.stop_requested:
            did_work = False
            for runner in runners:
                if signal_state.stop_requested:
                    break
                did_work = runner.run_once() or did_work
            if not did_work:
                time.sleep(min(runner.poll_seconds for runner in runners))
    finally:
        for runner in runners:
            repository.stop_worker_instance(runner.instance_id)


def _processed_id(processed: dict[str, Any]) -> str | None:
    for key in ("regeneration_job_id", "job_id", "id", "task_id"):
        value = processed.get(key)
        if value:
            return str(value)
    return None


def _float_env(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local JobAgent worker loops.")
    parser.add_argument("--db-path", default="data/jobagent_v2.sqlite3")
    parser.add_argument("--artifact-root", default="data/artifacts")
    parser.add_argument("--worker", choices=sorted(WORKER_TYPES))
    parser.add_argument("--all", action="store_true", help="Run all worker types in one loop.")
    parser.add_argument("--once", action="store_true", help="Run one polling iteration.")
    args = parser.parse_args(argv)
    if not args.all and not args.worker:
        parser.error("choose --worker or --all")
    stop_signal = StopSignal()
    signal.signal(signal.SIGINT, stop_signal.request_stop)
    signal.signal(signal.SIGTERM, stop_signal.request_stop)
    repository = Repository(args.db_path)
    config = WorkerRunnerConfig.from_env()
    if args.all:
        run_all(
            repository=repository,
            artifact_root=args.artifact_root,
            config=config,
            stop_signal=stop_signal,
        )
        return 0
    runner = WorkerRunner(
        repository=repository,
        artifact_root=args.artifact_root,
        worker_type=args.worker,
        config=config,
        stop_signal=stop_signal,
    )
    if args.once:
        processed = runner.run_once()
        repository.stop_worker_instance(runner.instance_id)
        print(json.dumps({"processed": processed, "worker_type": args.worker}))
        return 0
    runner.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
