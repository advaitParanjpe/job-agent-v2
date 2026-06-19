"""Deterministic workers for the local queue skeleton."""

from __future__ import annotations

import json
from pathlib import Path

from jobagent_v2.intake import intake_result_to_updates, run_intake
from jobagent_v2.hybrid_scoring import score_hybrid_job
from jobagent_v2.scoring import ScoringConfigurationError
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
        self.repository.transition_intake(
            job_id,
            "scoring",
            event_type="scoring_started",
            message="Intake complete; deterministic Queue 1 scoring started.",
            metadata={"quality_band": result.quality.band, "warnings": result.warnings},
        )
        return self._score_job(job_id)

    def rescore(self, job_id: str) -> dict[str, object]:
        self.repository.transition_intake(
            job_id, "scoring", event_type="rescore_started", message="Manual rescore started."
        )
        return self._score_job(job_id)

    def _score_job(self, job_id: str) -> dict[str, object]:
        job = self.repository.get_job(job_id)
        try:
            result = score_hybrid_job(job)
            self.repository.save_scoring_result(job_id, result)
        except (ScoringConfigurationError, OSError, ValueError) as error:
            return self.repository.transition_intake(
                job_id,
                "failed",
                event_type="scoring_failed",
                message=str(error),
                updates={
                    "failure_reason": str(error),
                    "reason": "Queue 1 scoring failed.",
                    "scoring_status": "failed",
                },
                metadata={"stage": "job_scoring"},
            )
        final_job = self.repository.transition_intake(
            job_id,
            "scored",
            event_type="job_scored",
            message="Deterministic Queue 1 scoring completed.",
            updates={"scoring_status": "complete"},
            metadata={"scoring_version": result.score_breakdown["formula_version"]},
        )
        duplicate = self.repository.find_probable_duplicate(
            job_id=job_id,
            company=str(job.get("company") or ""), title=str(job.get("title") or ""),
            jd_text_fingerprint=str(job.get("jd_text_fingerprint") or ""),
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
