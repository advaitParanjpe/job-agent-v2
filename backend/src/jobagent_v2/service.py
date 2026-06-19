"""Application service layer for Phase 1 API actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
        return {"jobs": self.repository.list_jobs(include_archived=include_archived)}

    def get_job(self, job_id: str) -> dict[str, Any]:
        return {"job": self.repository.get_job(job_id)}

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
            job = self.repository.queue_packet(job_id)
        except DuplicateActivePacketError:
            job = self.repository.get_job(job_id)
        return {"job": job}

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
