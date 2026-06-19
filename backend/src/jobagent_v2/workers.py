"""Deterministic workers for the local queue skeleton."""

from __future__ import annotations

import json
from pathlib import Path

from jobagent_v2.intake import intake_result_to_updates, run_intake
from jobagent_v2.storage import Repository
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
            event_type="intake_extracting",
            message="Intake started deterministic JD extraction.",
        )
        result = run_intake(
            page_title=str(job["page_title"]),
            visible_text=str(job["raw_visible_text"]),
            source_site=str(job["source_site"]) if job["source_site"] else None,
            source_url=str(job["source_url"]),
            evidence=job["capture_evidence"] if isinstance(job["capture_evidence"], dict) else {},
        )
        updates = intake_result_to_updates(result)
        self.repository.transition_intake(
            job_id,
            "structuring",
            event_type="intake_structuring",
            message="Intake extracted JD text and diagnostics.",
            updates=updates,
            metadata={
                "quality_band": result.quality.band,
                "warnings": result.warnings,
            },
        )
        if result.quality.band == "failed":
            return self.repository.transition_intake(
                job_id,
                "failed",
                event_type="intake_failed",
                message=result.failure_reason or "Intake failed.",
                metadata={"warnings": result.warnings},
                updates={
                    "reason": result.failure_reason or "Intake failed.",
                    "failure_reason": result.failure_reason,
                },
            )
        if result.quality.band == "manual_review":
            return self.repository.transition_intake(
                job_id,
                "manual_review",
                event_type="intake_manual_review",
                message=result.manual_review_reason or "Intake requires manual review.",
                metadata={"warnings": result.warnings},
                updates={
                    "reason": result.manual_review_reason or "Intake requires manual review.",
                    "manual_review_reason": result.manual_review_reason,
                },
            )
        final_job = self.repository.transition_intake(
            job_id,
            "scored",
            event_type="intake_complete",
            message="Deterministic intake completed.",
            updates={
                "reason": f"Intake complete with {result.quality.band} JD quality.",
            },
            metadata={"quality_band": result.quality.band, "warnings": result.warnings},
        )
        duplicate = self.repository.find_probable_duplicate(
            job_id=job_id,
            company=result.company.value,
            title=result.title.value,
            jd_text_fingerprint=result.duplicate_fingerprint,
        )
        if duplicate is not None:
            final_job = self.repository.set_duplicate_warning(
                job_id,
                f"Probable duplicate of job {duplicate['id']}.",
            )
        return final_job


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
