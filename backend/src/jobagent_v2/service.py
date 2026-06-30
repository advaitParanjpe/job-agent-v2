"""Application service layer for local API actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from jobagent_v2.promotion import PromotionConfig, PromotionScheduler, q2_eligibility
from jobagent_v2.regeneration_worker import ReviewRegenerationWorker
from jobagent_v2.schemas import (
    parse_capture_payload,
    parse_review_creation_payload,
    parse_review_resolution_payload,
)
from jobagent_v2.storage import DuplicateActivePacketError, Repository, summarize_job
from jobagent_v2.util import utc_now_iso
from jobagent_v2.workers import Queue1Worker, Queue2Worker
from jobagent_v2.worker_runner import WorkerRunnerConfig


class JobService:
    def __init__(self, repository: Repository, artifact_root: Path | str) -> None:
        self.repository = repository
        self.artifact_root = Path(artifact_root)

    def create_job(self, payload: Any) -> dict[str, Any]:
        parsed = parse_capture_payload(payload)
        job, duplicate = self.repository.create_or_get_job(parsed)
        return summarize_job(job, duplicate=duplicate)

    def list_jobs(self, *, include_archived: bool = False) -> dict[str, Any]:
        config = PromotionConfig.from_env()
        jobs = self.repository.list_jobs(include_archived=include_archived)
        for job in jobs:
            job["q2_eligibility"] = q2_eligibility(job, config)
            job["packet"] = self.repository.get_packet_for_job(str(job["id"]))
        return {"jobs": jobs}

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id)
        job["q2_eligibility"] = q2_eligibility(job, PromotionConfig.from_env())
        job["packet"] = self.repository.get_packet_for_job(job_id)
        return {"job": job}

    def get_events(self, job_id: str) -> dict[str, Any]:
        return {"events": self.repository.list_events(job_id)}

    def get_score(self, job_id: str) -> dict[str, Any]:
        return {"score": self.repository.get_score(job_id)}

    def get_block_scores(self, job_id: str) -> dict[str, Any]:
        return {"block_scores": self.repository.list_block_scores(job_id)}

    def get_semantic_assessment(self, job_id: str) -> dict[str, Any]:
        return {"semantic_assessment": self.repository.get_semantic_assessment(job_id)}

    def rescore(self, job_id: str) -> dict[str, Any]:
        return {"job": Queue1Worker(self.repository).rescore(job_id)}

    def generate_now(self, job_id: str) -> dict[str, Any]:
        try:
            task, created = self.repository.create_q2_task(
                job_id,
                promotion_reason="manual_generate",
                manual_override=True,
            )
        except DuplicateActivePacketError:
            task = self.repository.get_q2_task(job_id)
            created = False
        return {"job": self.repository.get_job(job_id), "task": task, "created": created}

    def set_star(self, job_id: str, starred: bool) -> dict[str, Any]:
        priority = 1 if starred else 0
        return {"job": self.repository.set_priority(job_id, starred=starred, priority=priority)}

    def set_priority(self, job_id: str, payload: Any) -> dict[str, Any]:
        value = payload.get("priority") if isinstance(payload, dict) else None
        if value not in {"normal", "high"}:
            raise ValueError("priority must be 'normal' or 'high'")
        job = self.repository.get_job(job_id)
        return {
            "job": self.repository.set_priority(
                job_id,
                starred=bool(job["starred"]),
                priority=1 if value == "high" else 0,
            )
        }

    def get_q2_task(self, job_id: str) -> dict[str, Any]:
        return {"task": self.repository.get_q2_task(job_id)}

    def get_packet_for_job(self, job_id: str) -> dict[str, Any]:
        return {"packet": self.repository.get_packet_for_job(job_id)}

    def get_packet(self, packet_id: str) -> dict[str, Any]:
        return {"packet": self.repository.get_packet(packet_id)}

    def list_reviews(
        self,
        *,
        owner_id: str = "local",
        status: str | None = "pending",
        review_type: str | None = None,
        family: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "reviews": self.repository.list_reviews(
                owner_id=owner_id,
                status=status,
                review_type=review_type,
                family=family,
                job_id=job_id,
            )
        }

    def get_review(self, review_id: str, *, owner_id: str = "local") -> dict[str, Any]:
        review = self.repository.get_review(review_id, owner_id=owner_id)
        self._attach_review_packets(review)
        return {"review": review}

    def create_review(
        self,
        job_id: str,
        payload: Any,
        *,
        owner_id: str = "local",
    ) -> dict[str, Any]:
        request = parse_review_creation_payload(payload)
        return {
            "review": self.repository.create_manual_review(
                job_id,
                owner_id=owner_id,
                review_type=request["review_type"],
                reason=request["reason"],
            )
        }

    def resolve_review(
        self,
        review_id: str,
        payload: Any,
        *,
        owner_id: str = "local",
    ) -> dict[str, Any]:
        resolution = parse_review_resolution_payload(payload)
        review = self.repository.resolve_review(
                review_id,
                resolution,
                owner_id=owner_id,
            )
        self._attach_review_packets(review)
        return {"review": review}

    def export_review_feedback(self, *, owner_id: str = "local") -> dict[str, Any]:
        return {"feedback": self.repository.export_review_feedback(owner_id=owner_id)}

    def packet_artifact(
        self,
        packet_id: str,
        field: str,
        *,
        owner_id: str = "local",
    ) -> Path:
        packet = self.repository.get_packet(packet_id)
        job = self.repository.get_job(str(packet["job_id"]))
        if job["owner_id"] != owner_id:
            raise FileNotFoundError("packet artifact is unavailable")
        raw = packet.get(field)
        if not raw:
            raise FileNotFoundError("packet artifact is unavailable")
        root = (self.artifact_root / "packets").resolve()
        path = Path(str(raw)).resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError("packet artifact is unavailable")
        return path

    def list_q2_tasks(self) -> dict[str, Any]:
        config = PromotionConfig.from_env()
        return {
            "tasks": self.repository.list_q2_tasks(),
            "active_tasks": self.repository.q2_active_count(),
            "capacity": config.q2_capacity,
            "worker_concurrency": config.q2_worker_concurrency,
        }

    def worker_status(self, worker_type: str | None = None) -> dict[str, Any]:
        if worker_type and worker_type not in {"q1", "q2", "regeneration"}:
            raise ValueError("unknown worker type")
        config = WorkerRunnerConfig.from_env()
        now = utc_now_iso()
        snapshot = self.repository.worker_operational_status(now=now)
        workers = [
            _worker_health(item, now=now, config=config)
            for item in snapshot["workers"]
            if worker_type is None or item["worker_type"] == worker_type
        ]
        queues = snapshot["queues"]
        queue_health = {
            key: _queue_health(key, queues[key], workers, config=config, now=now)
            for key in queues
            if worker_type is None or key == worker_type
        }
        return {
            "workers": workers,
            "queues": {key: queues[key] for key in queue_health},
            "queue_health": queue_health,
            "events": snapshot["events"],
            "config": config.safe_dict(),
        }

    def queue_status(self) -> dict[str, Any]:
        now = utc_now_iso()
        return {"queues": self.repository.queue_summaries(now=now)}

    def run_promotion_once(self) -> dict[str, Any]:
        return PromotionScheduler(self.repository).run_once()

    def archive(self, job_id: str) -> dict[str, Any]:
        return {"job": self.repository.archive_job(job_id)}

    def retry(self, job_id: str) -> dict[str, Any]:
        return {"job": self.repository.retry_job(job_id)}

    def run_q1_once(self) -> dict[str, Any]:
        job = Queue1Worker(self.repository).process_next()
        return {"processed": job is not None, "job": job}

    def run_q2_once(self) -> dict[str, Any]:
        job = Queue2Worker(self.repository, self.artifact_root).process_next()
        return {"processed": job is not None, "job": job}

    def run_regeneration_once(self) -> dict[str, Any]:
        worker = ReviewRegenerationWorker(self.repository, self.artifact_root)
        worker.recover_stale()
        job = worker.process_next()
        return {"processed": job is not None, "regeneration_job": job}

    def _attach_review_packets(self, review: dict[str, Any]) -> None:
        resolution = review.get("resolution") or {}
        source_packet_id = resolution.get("source_packet_id") or review.get("packet_id")
        regeneration_packet_id = resolution.get("regeneration_packet_id")
        review["original_packet"] = (
            self.repository.get_packet(str(source_packet_id)) if source_packet_id else None
        )
        review["reviewed_packet"] = (
            self.repository.get_packet(str(regeneration_packet_id))
            if regeneration_packet_id else None
        )
        review["current_preferred_packet"] = review["reviewed_packet"] or review["original_packet"]


def _worker_health(
    worker: dict[str, Any],
    *,
    now: str,
    config: WorkerRunnerConfig,
) -> dict[str, Any]:
    heartbeat_age = _age_seconds(worker.get("last_heartbeat_at"), now)
    threshold = config.health_heartbeat_seconds * 3
    state = str(worker["state"])
    if state in {"stopped", "stopping"}:
        health = "offline"
    elif heartbeat_age is None or heartbeat_age > threshold:
        health = "offline"
    elif int(worker.get("consecutive_failure_count") or 0) >= config.max_consecutive_failures:
        health = "degraded"
    elif state == "idle":
        health = "idle"
    elif state in {"processing", "starting", "backing_off"}:
        health = "healthy"
    elif state == "unhealthy":
        health = "degraded"
    else:
        health = "healthy"
    return {**worker, "health": health, "heartbeat_age_seconds": heartbeat_age}


def _queue_health(
    worker_type: str,
    queue: dict[str, Any],
    workers: list[dict[str, Any]],
    *,
    config: WorkerRunnerConfig,
    now: str,
) -> dict[str, Any]:
    healthy_workers = [
        item for item in workers
        if item["worker_type"] == worker_type and item["health"] in {"healthy", "idle"}
    ]
    queued = int(queue.get("queued_count") or 0)
    stale = int(queue.get("stale_processing_count") or 0)
    failures = int(queue.get("failed_count") or 0)
    exhausted = int(queue.get("max_attempt_exhausted_count") or 0)
    oldest_age = _age_seconds(queue.get("oldest_queued_at"), now)
    warnings = []
    if queued and not healthy_workers:
        warnings.append("queued_work_without_healthy_worker")
    if stale:
        warnings.append("stale_processing_work")
    if exhausted:
        warnings.append("max_attempts_exhausted")
    if oldest_age is not None and oldest_age > config.idle_backoff_max_seconds * 4:
        warnings.append("oldest_queued_item_waiting")
    if failures:
        warnings.append("failed_work_present")
    if warnings:
        health = "degraded"
    elif queued or int(queue.get("processing_count") or 0):
        health = "healthy"
    elif healthy_workers:
        health = "idle"
    else:
        health = "offline"
    return {
        "worker_type": worker_type,
        "health": health,
        "warnings": warnings,
        "healthy_worker_count": len(healthy_workers),
        "oldest_queued_age_seconds": oldest_age,
    }


def _age_seconds(value: str | None, now: str) -> float | None:
    if not value:
        return None
    try:
        then = datetime.fromisoformat(value.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (current - then).total_seconds())
