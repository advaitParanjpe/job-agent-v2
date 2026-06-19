"""Deterministic dummy workers for the Phase 1 queue skeleton."""

from __future__ import annotations

import json
from pathlib import Path

from jobagent_v2.storage import Repository
from jobagent_v2.url_utils import source_site_from_url
from jobagent_v2.util import utc_now_iso


class DummyQ1Worker:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def process_next(self) -> dict[str, object] | None:
        job = self.repository.next_job_with_intake_status("queued")
        if job is None:
            return None
        job_id = str(job["id"])
        self.repository.transition_intake(
            job_id,
            "extracting",
            event_type="q1_extracting",
            message="Dummy Q1 started placeholder extraction.",
        )
        self.repository.transition_intake(
            job_id,
            "scoring",
            event_type="q1_scoring",
            message="Dummy Q1 started placeholder scoring.",
        )
        title = str(job["page_title"] or "Untitled job")
        site = str(job["source_site"] or source_site_from_url(str(job["source_url"])))
        return self.repository.transition_intake(
            job_id,
            "scored",
            event_type="q1_scored",
            message="Dummy Q1 completed with deterministic placeholder output.",
            updates={
                "company": title,
                "title": title,
                "reason": f"Phase 1 dummy processing completed for {site}.",
            },
            metadata={"dummy": True},
        )


class DummyQ2Worker:
    def __init__(self, repository: Repository, artifact_root: Path | str) -> None:
        self.repository = repository
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def process_next(self) -> dict[str, object] | None:
        job = self.repository.next_job_with_packet_status("queued")
        if job is None:
            return None
        job_id = str(job["id"])
        self.repository.transition_packet(
            job_id,
            "generating",
            event_type="q2_generating",
            message="Dummy Q2 started placeholder artifact generation.",
        )
        artifact_path = self._write_placeholder_artifact(job)
        return self.repository.transition_packet(
            job_id,
            "ready",
            event_type="q2_ready",
            message="Dummy Q2 completed placeholder artifact.",
            updates={
                "placeholder_artifact_path": str(artifact_path),
                "reason": "Phase 1 dummy packet artifact is ready.",
            },
            metadata={"artifact_path": str(artifact_path), "dummy": True},
        )

    def _write_placeholder_artifact(self, job: dict[str, object]) -> Path:
        job_id = str(job["id"])
        safe_job_id = "".join(char for char in job_id if char.isalnum() or char == "-")
        path = self.artifact_root / f"{safe_job_id}.json"
        payload = {
            "job_id": job_id,
            "source_url": job["source_url"],
            "created_at": utc_now_iso(),
            "kind": "phase_1_placeholder_packet",
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

