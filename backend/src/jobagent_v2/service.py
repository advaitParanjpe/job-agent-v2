"""Application service layer for Phase 1 API actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jobagent_v2.promotion import PromotionConfig, PromotionScheduler, q2_eligibility
from jobagent_v2.schemas import parse_capture_payload
from jobagent_v2.storage import DuplicateActivePacketError, Repository, summarize_job
from jobagent_v2.workers import DummyQ1Worker, DummyQ2Worker


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
        return {"jobs": jobs}

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id)
        job["q2_eligibility"] = q2_eligibility(job, PromotionConfig.from_env())
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
        return {"job": DummyQ1Worker(self.repository).rescore(job_id)}

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

    def list_q2_tasks(self) -> dict[str, Any]:
        config = PromotionConfig.from_env()
        return {
            "tasks": self.repository.list_q2_tasks(),
            "active_tasks": self.repository.q2_active_count(),
            "capacity": config.q2_capacity,
            "worker_concurrency": config.q2_worker_concurrency,
        }

    def run_promotion_once(self) -> dict[str, Any]:
        return PromotionScheduler(self.repository).run_once()

    def archive(self, job_id: str) -> dict[str, Any]:
        return {"job": self.repository.archive_job(job_id)}

    def retry(self, job_id: str) -> dict[str, Any]:
        return {"job": self.repository.retry_job(job_id)}

    def run_q1_once(self) -> dict[str, Any]:
        job = DummyQ1Worker(self.repository).process_next()
        return {"processed": job is not None, "job": job}

    def run_q2_once(self) -> dict[str, Any]:
        job = DummyQ2Worker(self.repository, self.artifact_root).process_next()
        return {"processed": job is not None, "job": job}
