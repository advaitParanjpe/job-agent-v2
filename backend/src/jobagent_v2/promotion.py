"""Persistent Phase 4 promotion policy and deterministic scheduler."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from jobagent_v2.storage import Repository
from jobagent_v2.util import utc_now_iso


@dataclass(frozen=True)
class PromotionConfig:
    interval_seconds: int = 60
    q2_capacity: int = 8
    q2_worker_concurrency: int = 1
    auto_promote_threshold: int = 82
    manual_review_threshold: int = 70
    auto_packet_budget: int = 10
    lease_seconds: int = 300
    retry_limit: int = 3

    @classmethod
    def from_env(cls) -> "PromotionConfig":
        return cls(
            interval_seconds=_positive_env("JOBAGENT_PROMOTION_INTERVAL_SECONDS", 60),
            q2_capacity=_positive_env("JOBAGENT_Q2_CAPACITY", 8),
            q2_worker_concurrency=_positive_env("JOBAGENT_Q2_WORKER_CONCURRENCY", 1),
            auto_promote_threshold=_bounded_env("JOBAGENT_AUTO_PROMOTE_THRESHOLD", 82),
            manual_review_threshold=_bounded_env("JOBAGENT_MANUAL_REVIEW_THRESHOLD", 70),
            auto_packet_budget=_positive_env("JOBAGENT_AUTO_PACKET_BUDGET", 10),
        )


class PromotionScheduler:
    def __init__(self, repository: Repository, config: PromotionConfig | None = None) -> None:
        self.repository = repository
        self.config = config or PromotionConfig.from_env()

    def run_once(self) -> dict[str, Any]:
        now = utc_now_iso()
        recovered = self.repository.recover_stale_q2_tasks(
            now=now, retry_limit=self.config.retry_limit
        )
        active = self.repository.q2_active_count()
        available = max(0, self.config.q2_capacity - active)
        day = datetime.now(timezone.utc).date().isoformat()
        budget_used = self.repository.automatic_promotions_today(day)
        promoted: list[dict[str, Any]] = []
        for job in self.repository.eligible_scored_jobs():
            if len(promoted) >= available or budget_used >= self.config.auto_packet_budget:
                break
            if job["hard_blockers"]:
                continue
            priority = bool(job["starred"]) or int(job["manual_priority"]) > 0
            score = int(job["overall_score"])
            if not priority and score < self.config.auto_promote_threshold:
                continue
            reason = "manual_priority" if priority else "score_threshold"
            task, created = self.repository.create_q2_task(
                str(job["id"]), promotion_reason=reason, manual_override=False
            )
            if created:
                promoted.append(task)
                budget_used += 1
        return {
            "promoted": promoted,
            "recovered_stale_tasks": recovered,
            "active_tasks": self.repository.q2_active_count(),
            "capacity": self.config.q2_capacity,
            "automatic_budget_used": budget_used,
            "automatic_budget": self.config.auto_packet_budget,
        }


def q2_eligibility(job: dict[str, Any], config: PromotionConfig) -> str:
    if job["archived_at"] is not None:
        return "archived"
    if job["hard_blockers"]:
        return "blocked"
    if job["packet_status"] in {"queued", "generating", "ready"}:
        return "in_q2"
    if job["intake_status"] != "scored" or job["overall_score"] is None:
        return "not_scored"
    if bool(job["starred"]) or int(job["manual_priority"]) > 0:
        return "eligible_manual_priority"
    score = int(job["overall_score"])
    if score >= config.auto_promote_threshold:
        return "eligible"
    if score >= config.manual_review_threshold:
        return "manual_review_range"
    return "below_threshold"


def _positive_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


def _bounded_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not 0 <= value <= 100:
        raise ValueError(f"{name} must be between 0 and 100")
    return value
