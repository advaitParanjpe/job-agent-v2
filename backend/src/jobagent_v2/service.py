"""Application service layer for local API actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from uuid import uuid4

from jobagent_v2.promotion import PromotionConfig, PromotionScheduler, q2_eligibility
from jobagent_v2.config import RuntimeConfig
from jobagent_v2.project_blocks import load_project_block_registry
from jobagent_v2.regeneration_worker import ReviewRegenerationWorker
from jobagent_v2.schemas import (
    parse_capture_payload,
    parse_review_creation_payload,
    parse_review_resolution_payload,
)
from jobagent_v2.storage import DuplicateActivePacketError, Repository, summarize_job
from jobagent_v2.tailoring import load_tailoring_policy, select_tailoring_decision
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
        outcome = self.repository.capture_outcome(job, duplicate=duplicate)
        return {**summarize_job(job, duplicate=duplicate), **outcome}

    def list_jobs(self, *, include_archived: bool = False) -> dict[str, Any]:
        config = PromotionConfig.from_env()
        jobs = self.repository.list_jobs(include_archived=include_archived)
        for job in jobs:
            job["q2_eligibility"] = q2_eligibility(job, config)
            job["packet"] = self.repository.get_packet_for_job(str(job["id"]))
            job["tailoring_decision"] = self.repository.get_tailoring_decision(str(job["id"]))
            job["analysis_runs"] = self.repository.list_analysis_runs(
                str(job["id"]),
                owner_id=job["owner_id"],
            )
            self._attach_frontend_summary(job)
        return {"jobs": jobs}

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id)
        job["q2_eligibility"] = q2_eligibility(job, PromotionConfig.from_env())
        job["packet"] = self.repository.get_packet_for_job(job_id)
        job["tailoring_decision"] = self.repository.get_tailoring_decision(job_id)
        job["analysis_runs"] = self.repository.list_analysis_runs(job_id, owner_id=job["owner_id"])
        self._attach_frontend_summary(job)
        return {"job": job}

    def get_events(self, job_id: str) -> dict[str, Any]:
        return {"events": self.repository.list_events(job_id)}

    def get_score(self, job_id: str) -> dict[str, Any]:
        return {"score": self.repository.get_score(job_id)}

    def get_block_scores(self, job_id: str) -> dict[str, Any]:
        return {"block_scores": self.repository.list_block_scores(job_id)}

    def get_semantic_assessment(self, job_id: str) -> dict[str, Any]:
        return {"semantic_assessment": self.repository.get_semantic_assessment(job_id)}

    def list_analyses(self, job_id: str, *, owner_id: str = "local") -> dict[str, Any]:
        return {"analyses": self.repository.list_analysis_runs(job_id, owner_id=owner_id)}

    def restore(self, job_id: str, *, owner_id: str = "local") -> dict[str, Any]:
        job = self.repository.restore_job(job_id, owner_id=owner_id)
        self._attach_frontend_summary(job)
        return {
            "job": job,
            "outcome": "restored",
            "message": "Job restored.",
            "analysis_run": self.repository.get_active_analysis_run(job_id),
        }

    def rescore(self, job_id: str, *, owner_id: str = "local") -> dict[str, Any]:
        run, created = self.repository.start_analysis_run(
            job_id,
            owner_id=owner_id,
            trigger="manual_rescore",
        )
        if not created:
            job = self.repository.get_job(job_id)
            self._attach_frontend_summary(job)
            return {
                "job": job,
                "analysis_run": run,
                "created": False,
                "outcome": "existing_active",
                "message": "This job is already being analysed.",
            }
        job = Queue1Worker(self.repository).rescore(job_id)
        return {
            "job": job,
            "analysis_run": self.repository.list_analysis_runs(job_id, owner_id=owner_id)[0],
            "created": True,
            "outcome": "rescore_started",
            "message": "Re-score started.",
        }

    def restore_and_rescore(self, job_id: str, *, owner_id: str = "local") -> dict[str, Any]:
        run, created = self.repository.start_analysis_run(
            job_id,
            owner_id=owner_id,
            trigger="restore_and_rescore",
            restore=True,
        )
        if not created:
            job = self.repository.get_job(job_id)
            self._attach_frontend_summary(job)
            return {
                "job": job,
                "analysis_run": run,
                "created": False,
                "outcome": "existing_active",
                "message": "This job is already being analysed.",
            }
        job = Queue1Worker(self.repository).rescore(job_id)
        return {
            "job": job,
            "analysis_run": self.repository.list_analysis_runs(job_id, owner_id=owner_id)[0],
            "created": True,
            "outcome": "restored_and_rescore_started",
            "message": "Restored and queued.",
        }

    def reanalyze_project_selection(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id)
        base_family = str(job.get("selected_cv_family") or "")
        if not base_family:
            raise ValueError("job must be scored before project selection can be re-analysed")
        decision = select_tailoring_decision(
            packet_id=f"reanalyze-{uuid4()}",
            job=job,
            base_family=base_family,
            registry=load_project_block_registry(),
            policy=load_tailoring_policy(),
        )
        decision["analysis_mode"] = "reanalysis"
        decision["reason"] = (
            decision.get("reason")
            or "Project selection was re-analysed without overwriting existing packets."
        )
        packet = self.repository.get_packet_for_job(job_id)
        if packet:
            decision["packet_id"] = packet["packet_id"]
            self.repository.save_tailoring_decision(job_id, decision["packet_id"], decision)
        else:
            self.repository.record_project_reanalysis(job_id, decision)
        updated = self.repository.get_job(job_id)
        updated["packet"] = self.repository.get_packet_for_job(job_id)
        updated["tailoring_decision"] = self.repository.get_tailoring_decision(job_id)
        self._attach_frontend_summary(updated)
        tailoring_decision = updated["tailoring_decision"] or {"decision": decision}
        return {"job": updated, "tailoring_decision": tailoring_decision}

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
            "semantic_config": _semantic_config_summary(),
            "database": {
                "demo_cleanup": self.repository.demo_cleanup_preview(owner_id="local"),
            },
        }

    def queue_status(self) -> dict[str, Any]:
        now = utc_now_iso()
        return {"queues": self.repository.queue_summaries(now=now)}

    def run_promotion_once(self) -> dict[str, Any]:
        return PromotionScheduler(self.repository).run_once()

    def archive(self, job_id: str) -> dict[str, Any]:
        return {"job": self.repository.archive_job(job_id)}

    def delete_or_archive(self, job_id: str, *, owner_id: str = "local") -> dict[str, Any]:
        return {"job": self.repository.delete_or_archive_job(job_id, owner_id=owner_id)}

    def demo_cleanup_preview(self, *, owner_id: str = "local") -> dict[str, Any]:
        return {"preview": self.repository.demo_cleanup_preview(owner_id=owner_id)}

    def clear_demo_jobs(self, *, owner_id: str = "local") -> dict[str, Any]:
        return {"removed": self.repository.clear_demo_jobs(owner_id=owner_id)}

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

    def _attach_frontend_summary(self, job: dict[str, Any]) -> None:
        classification = job.get("family_classification") or {}
        semantic = (job.get("score_breakdown") or {}).get("hybrid") or {}
        packet = job.get("packet")
        stage = _workflow_stage(job)
        decision = str(classification.get("decision") or "")
        job["ui"] = {
            "workflow": {
                "stage": stage,
                "label": _workflow_label(stage),
                "timeline": _workflow_timeline(job),
                "next_action": _next_action(job),
            },
            "fit": {
                "score": job.get("overall_score"),
                "recommendation": job.get("recommendation"),
                "strengths": job.get("strengths") or [],
                "gaps": job.get("gaps") or [],
                "note": (
                    "Candidate fit estimates how suitable the role is for you. "
                    "It is separate from choosing which CV family to use."
                ),
            },
            "classification": {
                "selected_family": job.get("selected_cv_family"),
                "secondary_family": job.get("secondary_cv_family"),
                "decision": decision,
                "decision_label": _decision_label(decision, job),
                "requires_review": bool(job.get("family_classification_requires_review")),
                "family_scores": classification.get("family_scores") or {},
                "deterministic_scores": classification.get("deterministic_scores") or {},
                "semantic_scores": classification.get("semantic_scores"),
                "rule_evidence": classification.get("rule_evidence") or [],
                "semantic_evidence": classification.get("semantic_evidence") or [],
                "weights": _classification_weights(classification),
                "note": (
                    "CV-family classification identifies which type of resume best "
                    "matches the role. It is not your candidate-fit score."
                ),
            },
            "semantic": {
                "status": semantic.get("semantic_status") or _legacy_semantic_status(job),
                "attempted": bool(semantic.get("semantic_attempted")),
                "enabled": bool(semantic.get("semantic_enabled")),
                "fallback_used": bool(semantic.get("fallback_used")),
                "provider": semantic.get("provider"),
                "model": semantic.get("model") or job.get("llm_model"),
                "timestamp": semantic.get("completed_at") or job.get("updated_at"),
                "latency_ms": semantic.get("latency_ms"),
                "summary": ((semantic.get("semantic_assessment") or {}).get("grounded_reason")),
                "failure_code": semantic.get("failure_code"),
                "failure_summary": semantic.get("failure_summary") or job.get("llm_failure_reason"),
            },
            "packet": {
                "status": job.get("packet_status"),
                "status_label": _packet_label(job),
                "packet_id": packet.get("packet_id") if packet else None,
                "selected_cv_family": (
                    packet.get("selected_cv_family")
                    if packet
                    else job.get("selected_cv_family")
                ),
                "page_count": packet.get("page_count") if packet else None,
                "generation_kind": packet.get("generation_kind") if packet else None,
            },
        }


def _semantic_config_summary() -> dict[str, Any]:
    config = RuntimeConfig.from_env()
    return {
        "enabled": config.semantic_enabled,
        "provider": "openai",
        "model": config.semantic_model,
        "api_key_configured": config.semantic_api_key_present,
    }


def _workflow_stage(job: dict[str, Any]) -> str:
    intake = str(job.get("intake_status") or "")
    packet = str(job.get("packet_status") or "")
    if intake in {"queued", "extracting", "structuring", "scoring"}:
        return intake
    if intake in {"failed", "manual_review"}:
        return "failed"
    if packet in {"queued", "generating", "ready", "failed", "manual_review"}:
        return f"packet_{packet}"
    if bool(job.get("family_classification_requires_review")):
        return "requires_review"
    return "scored"


def _workflow_label(stage: str) -> str:
    return {
        "queued": "Waiting to be scored",
        "extracting": "Reading job description",
        "structuring": "Structuring job details",
        "scoring": "Scoring job",
        "scored": "Scored",
        "requires_review": "Needs review",
        "packet_queued": "Waiting for CV generation",
        "packet_generating": "Generating CV packet",
        "packet_ready": "Packet ready",
        "packet_failed": "Action needed",
        "packet_manual_review": "Needs review",
        "failed": "Action needed",
    }.get(stage, stage.replace("_", " ").title())


def _workflow_timeline(job: dict[str, Any]) -> list[dict[str, str]]:
    current = _workflow_stage(job)
    scored = job.get("overall_score") is not None
    classified = bool(job.get("selected_cv_family"))
    packet_ready = job.get("packet_status") == "ready"
    failed = current in {"failed", "packet_failed"}
    return [
        {"label": "Captured", "state": "complete"},
        {
            "label": "Scored",
            "state": _timeline_state(
                scored,
                current in {"queued", "extracting", "structuring", "scoring"},
                failed,
            ),
        },
        {
            "label": "Classified",
            "state": _timeline_state(classified, current == "scored", failed),
        },
        {
            "label": "CV generated",
            "state": _timeline_state(
                packet_ready,
                current in {"packet_queued", "packet_generating"},
                current == "packet_failed",
            ),
        },
        {"label": "Reviewed", "state": "current" if current == "requires_review" else "pending"},
    ]


def _timeline_state(done: bool, current: bool, failed: bool) -> str:
    if failed:
        return "failed"
    if done:
        return "complete"
    if current:
        return "current"
    return "pending"


def _next_action(job: dict[str, Any]) -> str:
    stage = _workflow_stage(job)
    if stage in {"queued", "extracting", "structuring", "scoring"}:
        return "Wait for scoring or run the scoring worker."
    if stage in {"failed", "packet_failed"}:
        return "Review the error, then retry."
    if stage == "requires_review" or bool(job.get("family_classification_requires_review")):
        return "Review the classification decision."
    if stage == "scored":
        return "Generate a CV packet."
    if stage == "packet_ready":
        return "Open the generated packet."
    return "View details."


def _decision_label(decision: str, job: dict[str, Any]) -> str:
    if decision == "clear_match":
        return "Clear match"
    if decision == "hybrid_match":
        primary = _family_label(job.get("selected_cv_family"))
        secondary = _family_label(job.get("secondary_cv_family"))
        if secondary != "-":
            return f"Mixed role: {primary} + {secondary}"
        return f"Mixed role: {primary}"
    if decision == "close_match":
        return "Close decision"
    if decision == "low_confidence":
        return "Low confidence"
    return decision.replace("_", " ").title() if decision else "Not classified"


def _family_label(value: Any) -> str:
    return {
        "digital_ic": "Digital IC / RTL",
        "verification": "Verification",
        "software": "Software",
        "ml": "Machine Learning",
    }.get(str(value or ""), "-")


def _classification_weights(classification: dict[str, Any]) -> dict[str, float]:
    if not classification.get("semantic_scores"):
        return {"deterministic": 1.0, "semantic": 0.0}
    return {"deterministic": 0.6, "semantic": 0.4}


def _legacy_semantic_status(job: dict[str, Any]) -> str:
    status = str(job.get("llm_call_status") or "")
    if status == "success":
        return "live_success"
    if status == "unavailable":
        reason = str(job.get("llm_failure_reason") or "").lower()
        if "disabled" in reason:
            return "disabled"
        if "key" in reason:
            return "not_configured"
        return "fallback_used"
    return "not_attempted"


def _packet_label(job: dict[str, Any]) -> str:
    return {
        "not_requested": "No CV packet yet",
        "queued": "Waiting for CV generation",
        "generating": "Generating CV packet",
        "ready": "Packet ready",
        "failed": "Packet failed",
        "manual_review": "Needs review",
    }.get(str(job.get("packet_status") or ""), str(job.get("packet_status") or "-"))


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
