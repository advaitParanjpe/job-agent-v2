"""SQLite persistence for jobs and events."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4

from jobagent_v2.schemas import CapturePayload
from jobagent_v2.statuses import (
    validate_intake_transition,
    validate_packet_transition,
)
from jobagent_v2.project_blocks import (
    ProjectBlockRegistryError,
    load_project_block_registry,
    validate_replacement_pair,
)
from jobagent_v2.url_utils import normalize_url, source_site_from_url
from jobagent_v2.util import utc_now_iso


SCHEMA_VERSION = 13
REGENERATION_MAX_ATTEMPTS = 3
REGENERATION_RETRYABLE_ERRORS = {
    "temporary_artifact_write_failure",
    "worker_interrupted",
}


class JobNotFoundError(LookupError):
    """Raised when a job ID does not exist."""


class DuplicateActivePacketError(RuntimeError):
    """Raised when a packet task is already active or ready."""


FAMILY_IDS = {"digital_ic", "verification", "software", "ml"}
REVIEWABLE_CLASSIFICATION_DECISIONS = {"close_match", "hybrid_match", "low_confidence"}
REVIEWABLE_TAILORING_STATUSES = {
    "review_required",
    "fallback_to_master",
    "tailoring_rejected",
}
REVIEW_ACTIONS = {
    "approve_classification",
    "override_family",
    "mark_out_of_scope",
    "defer",
    "approve_tailoring",
    "use_master_unchanged",
    "select_approved_replacement",
    "approve_order",
    "reject_tailoring",
}


class Repository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            existing_version = _existing_schema_version(connection)
            if existing_version is not None and existing_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema {existing_version} is newer than supported "
                    f"schema {SCHEMA_VERSION}"
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    normalized_url TEXT NOT NULL UNIQUE,
                    owner_id TEXT NOT NULL DEFAULT 'local',
                    page_title TEXT NOT NULL,
                    raw_visible_text TEXT NOT NULL,
                    source_site TEXT,
                    source_provenance TEXT NOT NULL DEFAULT 'manual',
                    capture_evidence_json TEXT,
                    detected_site TEXT,
                    extraction_candidates_json TEXT,
                    duplicate_key TEXT,
                    duplicate_warning TEXT,
                    jd_text TEXT,
                    jd_quality_score INTEGER,
                    jd_quality_band TEXT,
                    jd_quality_json TEXT,
                    structured_jd_json TEXT,
                    company TEXT,
                    title TEXT,
                    location TEXT,
                    extraction_method TEXT,
                    extraction_warnings_json TEXT,
                    failure_reason TEXT,
                    manual_review_reason TEXT,
                    field_provenance_json TEXT,
                    raw_text_length INTEGER,
                    clean_text_length INTEGER,
                    jd_text_fingerprint TEXT,
                    role_family TEXT,
                    overall_score INTEGER,
                    recommendation TEXT,
                    reason TEXT,
                    intake_status TEXT NOT NULL,
                    packet_status TEXT NOT NULL,
                    manual_priority INTEGER NOT NULL DEFAULT 0,
                    placeholder_artifact_path TEXT,
                    archived_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    message TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_block_scores (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    scoring_version TEXT NOT NULL,
                    block_id TEXT NOT NULL,
                    block_type TEXT NOT NULL,
                    block_name TEXT NOT NULL,
                    technical_match INTEGER NOT NULL,
                    keyword_match INTEGER NOT NULL,
                    responsibility_match INTEGER NOT NULL,
                    evidence_strength INTEGER NOT NULL,
                    seniority_fit INTEGER NOT NULL,
                    recency INTEGER NOT NULL,
                    impressiveness INTEGER NOT NULL,
                    domain_match INTEGER NOT NULL,
                    risk_of_overclaim INTEGER NOT NULL,
                    aggregate_score INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    matched_requirements_json TEXT NOT NULL,
                    unmatched_requirements_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_scores (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    analysis_run_id TEXT,
                    scoring_version TEXT NOT NULL,
                    structured_jd_json TEXT NOT NULL,
                    family_selection_json TEXT NOT NULL,
                    section_scores_json TEXT NOT NULL,
                    score_breakdown_json TEXT NOT NULL,
                    strengths_json TEXT NOT NULL,
                    gaps_json TEXT NOT NULL,
                    hard_blockers_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_semantic_assessments (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    analysis_run_id TEXT,
                    scoring_version TEXT NOT NULL,
                    scoring_mode TEXT NOT NULL,
                    llm_call_status TEXT NOT NULL,
                    llm_failure_reason TEXT,
                    model_name TEXT,
                    prompt_version TEXT,
                    semantic_schema_version TEXT,
                    deterministic_family_json TEXT NOT NULL,
                    llm_family_json TEXT,
                    family_decision_json TEXT,
                    semantic_assessment_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_family_classifications (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    analysis_run_id TEXT,
                    classifier_version TEXT NOT NULL,
                    config_version TEXT NOT NULL,
                    family_scores_json TEXT NOT NULL,
                    selected_family TEXT NOT NULL,
                    secondary_family TEXT,
                    confidence REAL NOT NULL,
                    decision TEXT NOT NULL,
                    requires_review INTEGER NOT NULL,
                    rule_evidence_json TEXT NOT NULL,
                    semantic_evidence_json TEXT NOT NULL,
                    deterministic_scores_json TEXT NOT NULL,
                    semantic_scores_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    source_content_version TEXT,
                    status TEXT NOT NULL,
                    candidate_fit_json TEXT,
                    family_classification_json TEXT,
                    semantic_requirements_json TEXT,
                    fused_requirements_json TEXT,
                    project_portfolio_json TEXT,
                    packet_id TEXT,
                    failure_code TEXT,
                    failure_reason TEXT,
                    policy_versions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_runs_one_active
                ON analysis_runs(job_id)
                WHERE status IN ('queued', 'running');
                CREATE INDEX IF NOT EXISTS idx_analysis_runs_job_created
                ON analysis_runs(job_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS q2_tasks (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    promotion_reason TEXT NOT NULL,
                    score_at_promotion INTEGER,
                    manual_override INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    failure_reason TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_q2_tasks_status_priority
                ON q2_tasks(status, priority DESC, created_at ASC);

                CREATE TABLE IF NOT EXISTS packets (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    q2_task_id TEXT NOT NULL REFERENCES q2_tasks(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    selected_cv_family TEXT,
                    artifact_directory TEXT,
                    pdf_path TEXT,
                    tex_path TEXT,
                    manifest_path TEXT,
                    selected_cv_path TEXT,
                    tailoring_decision_path TEXT,
                    page_count INTEGER,
                    failure_stage TEXT,
                    failure_reason TEXT,
                    generation_kind TEXT NOT NULL DEFAULT 'automated',
                    source_packet_id TEXT REFERENCES packets(id) ON DELETE SET NULL,
                    review_id TEXT REFERENCES review_items(id) ON DELETE SET NULL,
                    review_resolution_id TEXT REFERENCES review_resolutions(id) ON DELETE SET NULL,
                    idempotency_key TEXT,
                    generation_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_packets_job_created
                ON packets(job_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS job_tailoring_decisions (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    packet_id TEXT REFERENCES packets(id) ON DELETE CASCADE,
                    base_family TEXT NOT NULL,
                    classification_decision TEXT,
                    base_blocks_json TEXT NOT NULL,
                    final_blocks_json TEXT NOT NULL,
                    removed_block TEXT,
                    inserted_block TEXT,
                    scores_json TEXT NOT NULL,
                    replacement_gain REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    requires_review INTEGER NOT NULL,
                    tailoring_status TEXT NOT NULL,
                    fallback_reason TEXT,
                    policy_version TEXT NOT NULL,
                    registry_version TEXT NOT NULL,
                    classifier_version TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tailoring_job_created
                ON job_tailoring_decisions(job_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS review_items (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    packet_id TEXT REFERENCES packets(id) ON DELETE SET NULL,
                    review_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    classification_ref_id TEXT,
                    tailoring_ref_id TEXT,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_reviews_status_owner
                ON review_items(owner_id, status, created_at DESC);

                CREATE TABLE IF NOT EXISTS review_resolutions (
                    id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL REFERENCES review_items(id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    packet_id TEXT REFERENCES packets(id) ON DELETE SET NULL,
                    action TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    review_note TEXT,
                    original_family TEXT,
                    resolved_family TEXT,
                    original_blocks_json TEXT NOT NULL,
                    resolved_blocks_json TEXT NOT NULL,
                    resolution_json TEXT NOT NULL,
                    classifier_version TEXT,
                    registry_version TEXT,
                    policy_version TEXT,
                    regeneration_status TEXT NOT NULL,
                    regeneration_packet_id TEXT,
                    regeneration_job_id TEXT,
                    source_packet_id TEXT,
                    queued_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    failed_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    failure_code TEXT,
                    failure_reason TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_resolutions_review
                ON review_resolutions(review_id, created_at ASC);

                CREATE TABLE IF NOT EXISTS review_regeneration_jobs (
                    id TEXT PRIMARY KEY,
                    review_resolution_id TEXT NOT NULL UNIQUE
                        REFERENCES review_resolutions(id) ON DELETE CASCADE,
                    review_id TEXT NOT NULL REFERENCES review_items(id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    source_packet_id TEXT REFERENCES packets(id) ON DELETE SET NULL,
                    generated_packet_id TEXT REFERENCES packets(id) ON DELETE SET NULL,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    queued_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    failed_at TEXT,
                    failure_code TEXT,
                    failure_reason TEXT,
                    policy_version TEXT,
                    registry_version TEXT,
                    classifier_version TEXT,
                    packet_generator_version TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_regen_status
                ON review_regeneration_jobs(status, queued_at ASC);

                CREATE TABLE IF NOT EXISTS worker_instances (
                    instance_id TEXT PRIMARY KEY,
                    worker_type TEXT NOT NULL,
                    process_id INTEGER,
                    hostname TEXT,
                    state TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    last_heartbeat_at TEXT,
                    stopped_at TEXT,
                    current_job_id TEXT,
                    last_claimed_job_id TEXT,
                    last_completed_job_id TEXT,
                    last_success_at TEXT,
                    last_failure_at TEXT,
                    last_failure_code TEXT,
                    last_failure_reason TEXT,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    consecutive_failure_count INTEGER NOT NULL DEFAULT 0,
                    polling_interval_seconds REAL NOT NULL,
                    version TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_worker_instances_type
                ON worker_instances(worker_type, updated_at DESC);

                CREATE TABLE IF NOT EXISTS worker_events (
                    id TEXT PRIMARY KEY,
                    worker_type TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    state TEXT,
                    job_id TEXT,
                    safe_code TEXT,
                    message TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_worker_events_instance_created
                ON worker_events(instance_id, created_at DESC);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            self._ensure_columns(connection)
            self._mark_legacy_demo_seed_jobs(connection)
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_packets_regen_idempotency
                ON packets(idempotency_key)
                WHERE idempotency_key IS NOT NULL AND status = 'ready'"""
            )

    def _ensure_columns(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA table_info(jobs)").fetchall()
        existing = {row["name"] for row in rows}
        columns = {
            "owner_id": "TEXT NOT NULL DEFAULT 'local'",
            "duplicate_key": "TEXT",
            "capture_evidence_json": "TEXT",
            "source_provenance": "TEXT NOT NULL DEFAULT 'manual'",
            "detected_site": "TEXT",
            "extraction_candidates_json": "TEXT",
            "duplicate_warning": "TEXT",
            "jd_text": "TEXT",
            "jd_quality_score": "INTEGER",
            "jd_quality_band": "TEXT",
            "jd_quality_json": "TEXT",
            "structured_jd_json": "TEXT",
            "location": "TEXT",
            "extraction_method": "TEXT",
            "extraction_warnings_json": "TEXT",
            "failure_reason": "TEXT",
            "manual_review_reason": "TEXT",
            "field_provenance_json": "TEXT",
            "raw_text_length": "INTEGER",
            "clean_text_length": "INTEGER",
            "jd_text_fingerprint": "TEXT",
            "selected_cv_family": "TEXT",
            "secondary_cv_family": "TEXT",
            "cv_family_confidence": "TEXT",
            "cv_family_selection_json": "TEXT",
            "family_classification_json": "TEXT",
            "family_classifier_version": "TEXT",
            "family_classification_decision": "TEXT",
            "family_classification_requires_review": "INTEGER NOT NULL DEFAULT 0",
            "scoring_status": "TEXT",
            "scoring_version": "TEXT",
            "score_breakdown_json": "TEXT",
            "section_scores_json": "TEXT",
            "strengths_json": "TEXT",
            "gaps_json": "TEXT",
            "hard_blockers_json": "TEXT",
            "scoring_mode": "TEXT",
            "llm_call_status": "TEXT",
            "llm_failure_reason": "TEXT",
            "llm_model": "TEXT",
            "llm_prompt_version": "TEXT",
            "starred": "INTEGER NOT NULL DEFAULT 0",
            "priority_updated_at": "TEXT",
            "promotion_reason": "TEXT",
            "current_packet_id": "TEXT",
            "current_analysis_run_id": "TEXT",
        }
        for name, ddl in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")
        packet_rows = connection.execute("PRAGMA table_info(packets)").fetchall()
        packet_existing = {row["name"] for row in packet_rows}
        if "tailoring_decision_path" not in packet_existing:
            connection.execute("ALTER TABLE packets ADD COLUMN tailoring_decision_path TEXT")
        packet_columns = {
            "generation_kind": "TEXT NOT NULL DEFAULT 'automated'",
            "source_packet_id": "TEXT",
            "review_id": "TEXT",
            "review_resolution_id": "TEXT",
            "idempotency_key": "TEXT",
            "generation_reason": "TEXT",
        }
        for name, ddl in packet_columns.items():
            if name not in packet_existing:
                connection.execute(f"ALTER TABLE packets ADD COLUMN {name} {ddl}")
        for table in ("job_scores", "job_semantic_assessments", "job_family_classifications"):
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
            existing = {row["name"] for row in rows}
            if "analysis_run_id" not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN analysis_run_id TEXT")
        block_rows = connection.execute("PRAGMA table_info(job_block_scores)").fetchall()
        block_existing = {row["name"] for row in block_rows}
        if "analysis_run_id" not in block_existing:
            connection.execute("ALTER TABLE job_block_scores ADD COLUMN analysis_run_id TEXT")
        resolution_rows = connection.execute("PRAGMA table_info(review_resolutions)").fetchall()
        resolution_existing = {row["name"] for row in resolution_rows}
        resolution_columns = {
            "regeneration_job_id": "TEXT",
            "source_packet_id": "TEXT",
            "queued_at": "TEXT",
            "started_at": "TEXT",
            "completed_at": "TEXT",
            "failed_at": "TEXT",
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "failure_code": "TEXT",
        }
        for name, ddl in resolution_columns.items():
            if name not in resolution_existing:
                connection.execute(f"ALTER TABLE review_resolutions ADD COLUMN {name} {ddl}")
        regen_rows = connection.execute("PRAGMA table_info(review_regeneration_jobs)").fetchall()
        regen_existing = {row["name"] for row in regen_rows}
        regen_columns = {
            "generated_packet_id": "TEXT",
            "idempotency_key": "TEXT",
            "policy_version": "TEXT",
            "registry_version": "TEXT",
            "classifier_version": "TEXT",
            "packet_generator_version": "TEXT",
        }
        for name, ddl in regen_columns.items():
            if name not in regen_existing:
                connection.execute(f"ALTER TABLE review_regeneration_jobs ADD COLUMN {name} {ddl}")

    def _mark_legacy_demo_seed_jobs(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            UPDATE jobs
            SET source_provenance = 'demo'
            WHERE source_provenance = 'manual'
              AND source_url LIKE 'https://example.test/demo/%'
              AND source_site = 'example.test'
            """
        )

    def register_worker_instance(
        self,
        *,
        worker_type: str,
        instance_id: str,
        process_id: int | None,
        hostname: str | None,
        polling_interval_seconds: float,
        version: str,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO worker_instances (
                    instance_id, worker_type, process_id, hostname, state, started_at,
                    last_heartbeat_at, stopped_at, current_job_id, last_claimed_job_id,
                    last_completed_job_id, last_success_at, last_failure_at,
                    last_failure_code, last_failure_reason, processed_count,
                    failure_count, consecutive_failure_count, polling_interval_seconds,
                    version, updated_at
                )
                VALUES (?, ?, ?, ?, 'starting', ?, ?, NULL, NULL, NULL, NULL, NULL, NULL,
                    NULL, NULL, 0, 0, 0, ?, ?, ?)""",
                (
                    instance_id,
                    worker_type,
                    process_id,
                    hostname,
                    now,
                    now,
                    polling_interval_seconds,
                    version,
                    now,
                ),
            )
            self._insert_worker_event(
                connection,
                worker_type=worker_type,
                instance_id=instance_id,
                event_type="worker_start",
                state="starting",
                job_id=None,
                safe_code=None,
                message="Worker instance started.",
                metadata={},
            )
            row = connection.execute(
                "SELECT * FROM worker_instances WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
        return row_to_worker_instance(row)

    def update_worker_instance(
        self,
        *,
        instance_id: str,
        state: str,
        current_job_id: str | None = None,
        claimed_job_id: str | None = None,
        completed_job_id: str | None = None,
        failure_code: str | None = None,
        failure_reason: str | None = None,
        increment_processed: bool = False,
        increment_failure: bool = False,
        event_type: str | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        safe_reason = _safe_failure_reason(failure_reason or "") if failure_reason else None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM worker_instances WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
            if row is None:
                raise JobNotFoundError(instance_id)
            connection.execute(
                """UPDATE worker_instances SET state=?, last_heartbeat_at=?,
                    current_job_id=?, last_claimed_job_id=COALESCE(?, last_claimed_job_id),
                    last_completed_job_id=COALESCE(?, last_completed_job_id),
                    last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END,
                    last_failure_at=CASE WHEN ? THEN ? ELSE last_failure_at END,
                    last_failure_code=COALESCE(?, last_failure_code),
                    last_failure_reason=COALESCE(?, last_failure_reason),
                    processed_count=processed_count + ?,
                    failure_count=failure_count + ?,
                    consecutive_failure_count=CASE WHEN ? THEN 0
                        ELSE consecutive_failure_count + ? END,
                    updated_at=?
                WHERE instance_id=?""",
                (
                    state,
                    now,
                    current_job_id,
                    claimed_job_id,
                    completed_job_id,
                    int(increment_processed),
                    now,
                    int(increment_failure),
                    now,
                    failure_code,
                    safe_reason,
                    1 if increment_processed else 0,
                    1 if increment_failure else 0,
                    int(increment_processed),
                    1 if increment_failure else 0,
                    now,
                    instance_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM worker_instances WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
            if event_type:
                self._insert_worker_event(
                    connection,
                    worker_type=updated["worker_type"],
                    instance_id=instance_id,
                    event_type=event_type,
                    state=state,
                    job_id=current_job_id or claimed_job_id or completed_job_id,
                    safe_code=failure_code,
                    message=message or event_type,
                    metadata=metadata or {},
                )
        return row_to_worker_instance(updated)

    def stop_worker_instance(self, instance_id: str, *, state: str = "stopped") -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM worker_instances WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
            if row is None:
                return
            connection.execute(
                """UPDATE worker_instances SET state=?, current_job_id=NULL,
                stopped_at=?, last_heartbeat_at=?, updated_at=? WHERE instance_id=?""",
                (state, now, now, now, instance_id),
            )
            self._insert_worker_event(
                connection,
                worker_type=row["worker_type"],
                instance_id=instance_id,
                event_type="worker_stop",
                state=state,
                job_id=None,
                safe_code=None,
                message="Worker instance stopped.",
                metadata={},
            )

    def list_worker_instances(self, worker_type: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM worker_instances"
        params: tuple[Any, ...] = ()
        if worker_type:
            query += " WHERE worker_type = ?"
            params = (worker_type,)
        query += " ORDER BY updated_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [row_to_worker_instance(row) for row in rows]

    def list_worker_events(self, *, limit: int = 25) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM worker_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row_to_worker_event(row) for row in rows]

    def queue_summaries(self, *, now: str) -> dict[str, Any]:
        with self.connect() as connection:
            q1 = _queue_counts(
                connection,
                "jobs",
                "intake_status",
                queued="queued",
                processing=("extracting", "structuring", "scoring"),
                failed=("failed", "manual_review"),
                queued_at_column="created_at",
                stale_statuses=("extracting", "structuring", "scoring"),
                stale_column="updated_at",
                now=now,
            )
            q2 = _q2_queue_counts(connection, now=now)
            regeneration = _regeneration_queue_counts(connection, now=now)
        return {"q1": q1, "q2": q2, "regeneration": regeneration}

    def worker_operational_status(self, *, now: str) -> dict[str, Any]:
        return {
            "workers": self.list_worker_instances(),
            "queues": self.queue_summaries(now=now),
            "events": self.list_worker_events(limit=25),
        }

    def create_or_get_job(self, payload: CapturePayload) -> tuple[dict[str, Any], bool]:
        normalized_url = normalize_url(payload.url)
        site = payload.source_site or source_site_from_url(payload.url)
        now = utc_now_iso()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM jobs WHERE normalized_url = ?", (normalized_url,)
            ).fetchone()
            if existing is not None:
                self._insert_event(
                    connection,
                    job_id=existing["id"],
                    event_type="duplicate_detected",
                    from_status=existing["intake_status"],
                    to_status=existing["intake_status"],
                    message="Duplicate intake request returned existing job.",
                    metadata={"normalized_url": normalized_url},
                )
                return row_to_job(existing), True

            job_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO jobs (
                    id, source_url, normalized_url, owner_id, page_title, raw_visible_text,
                    source_site, source_provenance, capture_evidence_json,
                    detected_site, duplicate_key,
                    company, title, role_family, overall_score,
                    recommendation, reason, intake_status, packet_status,
                    manual_priority, placeholder_artifact_path, archived_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    payload.url,
                    normalized_url,
                    str(payload.evidence.get("owner_id") or "local"),
                    payload.page_title,
                    payload.visible_text,
                    site,
                    _source_provenance(payload.evidence),
                    json.dumps(payload.evidence, sort_keys=True),
                    str(payload.evidence.get("detected_site") or site or ""),
                    normalized_url,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "Queued for deterministic intake processing.",
                    "queued",
                    "not_requested",
                    0,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="job_created",
                from_status=None,
                to_status="queued",
                message="Raw job persisted and queued for Queue 1 intake/scoring.",
                metadata={
                    "normalized_url": normalized_url,
                    "captured_at": payload.captured_at,
                },
            )
            run_id = self._insert_analysis_run(
                connection,
                job_id=job_id,
                owner_id=str(payload.evidence.get("owner_id") or "local"),
                trigger="initial_capture",
                status="queued",
            )
            self._update_job(connection, job_id, {"current_analysis_run_id": run_id})
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise JobNotFoundError(job_id)
            return row_to_job(row), False

    def capture_outcome(self, job: dict[str, Any], *, duplicate: bool) -> dict[str, Any]:
        if not duplicate:
            return {
                "outcome": "created",
                "job_state": "active",
                "active_run": True,
                "analysis_run": self.get_active_analysis_run(str(job["id"])),
                "allowed_actions": ["open_existing"],
                "message": "Job added for analysis.",
            }
        active_run = self.get_active_analysis_run(str(job["id"]))
        intake_status = str(job.get("intake_status") or "")
        archived = bool(job.get("archived_at"))
        if archived:
            return {
                "outcome": "existing_archived",
                "job_state": "archived",
                "active_run": active_run is not None,
                "analysis_run": active_run,
                "allowed_actions": ["restore", "restore_and_rescore", "open_existing"],
                "message": "This job is in your archive.",
            }
        if active_run is not None or intake_status in {
            "queued",
            "extracting",
            "structuring",
            "scoring",
        }:
            return {
                "outcome": "existing_active",
                "job_state": "active",
                "active_run": True,
                "analysis_run": active_run,
                "allowed_actions": ["open_existing"],
                "message": "This job is already being analysed.",
            }
        if intake_status in {"failed", "manual_review"}:
            return {
                "outcome": "existing_failed",
                "job_state": "failed",
                "active_run": False,
                "analysis_run": None,
                "allowed_actions": ["rescore", "open_existing"],
                "message": "This job previously failed.",
            }
        return {
            "outcome": "existing_complete",
            "job_state": "complete",
            "active_run": False,
            "analysis_run": None,
            "allowed_actions": ["rescore", "archive", "open_existing"],
            "message": "This job already exists.",
        }

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return row_to_job(row)

    def list_jobs(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM jobs"
        params: tuple[Any, ...] = ()
        if not include_archived:
            query += " WHERE archived_at IS NULL"
        query += " ORDER BY manual_priority DESC, overall_score DESC, created_at ASC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [row_to_job(row) for row in rows]

    def demo_cleanup_preview(self, *, owner_id: str = "local") -> dict[str, Any]:
        with self.connect() as connection:
            job_rows = connection.execute(
                "SELECT id FROM jobs WHERE owner_id = ? AND source_provenance = 'demo'",
                (owner_id,),
            ).fetchall()
            job_ids = [str(row["id"]) for row in job_rows]
            if not job_ids:
                return {
                    "owner_id": owner_id,
                    "job_count": 0,
                    "review_count": 0,
                    "packet_count": 0,
                    "artifact_directories": [],
                }
            placeholders = ",".join("?" for _ in job_ids)
            review_count = connection.execute(
                f"SELECT count(*) AS count FROM review_items WHERE job_id IN ({placeholders})",
                tuple(job_ids),
            ).fetchone()["count"]
            packet_rows = connection.execute(
                f"SELECT artifact_directory FROM packets WHERE job_id IN ({placeholders})",
                tuple(job_ids),
            ).fetchall()
        artifact_dirs = sorted({
            str(row["artifact_directory"])
            for row in packet_rows
            if row["artifact_directory"]
        })
        return {
            "owner_id": owner_id,
            "job_count": len(job_ids),
            "review_count": int(review_count),
            "packet_count": len(packet_rows),
            "artifact_directories": artifact_dirs,
        }

    def clear_demo_jobs(self, *, owner_id: str = "local") -> dict[str, Any]:
        preview = self.demo_cleanup_preview(owner_id=owner_id)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE owner_id = ? AND source_provenance = 'demo'",
                (owner_id,),
            ).fetchall()
            for row in rows:
                connection.execute("DELETE FROM jobs WHERE id = ?", (row["id"],))
        return preview

    def delete_or_archive_job(self, job_id: str, *, owner_id: str = "local") -> dict[str, Any]:
        with self.connect() as connection:
            row = self._get_job_row(connection, job_id)
            if row["owner_id"] != owner_id:
                raise JobNotFoundError(job_id)
            if row["source_provenance"] in {"demo", "test"}:
                job = row_to_job(row)
                connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                return {**job, "deleted": True, "archived": False}
        archived = self.archive_job(job_id)
        return {**archived, "deleted": False, "archived": True}

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        self.get_job(job_id)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_events WHERE job_id = ? ORDER BY rowid ASC",
                (job_id,),
            ).fetchall()
        return [row_to_event(row) for row in rows]

    def record_project_reanalysis(self, job_id: str, decision: dict[str, Any]) -> None:
        with self.connect() as connection:
            job = self._get_job_row(connection, job_id)
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="project_selection_reanalyzed",
                from_status=job["packet_status"],
                to_status=job["packet_status"],
                message=(
                    "Requirement-aware project selection was re-analysed "
                    "without generating a packet."
                ),
                metadata={
                    "base_family": decision.get("base_family"),
                    "tailoring_status": decision.get("tailoring_status"),
                    "requires_review": bool(decision.get("requires_review")),
                    "shortlist": (decision.get("project_portfolio") or {}).get("shortlist", []),
                    "inserted_block": decision.get("inserted_block"),
                    "removed_block": decision.get("removed_block"),
                    "policy_version": decision.get("policy_version"),
                    "registry_version": decision.get("registry_version"),
                },
            )

    def transition_intake(
        self,
        job_id: str,
        to_status: str,
        *,
        event_type: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            row = self._get_job_row(connection, job_id)
            from_status = row["intake_status"]
            validate_intake_transition(from_status, to_status)
            self._update_job(
                connection,
                job_id,
                {"intake_status": to_status, **(updates or {})},
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                message=message,
                metadata=metadata or {},
            )
            updated = self._get_job_row(connection, job_id)
        return row_to_job(updated)

    def transition_packet(
        self,
        job_id: str,
        to_status: str,
        *,
        event_type: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            row = self._get_job_row(connection, job_id)
            from_status = row["packet_status"]
            validate_packet_transition(from_status, to_status)
            self._update_job(
                connection,
                job_id,
                {"packet_status": to_status, **(updates or {})},
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                message=message,
                metadata=metadata or {},
            )
            updated = self._get_job_row(connection, job_id)
        return row_to_job(updated)

    def set_priority(self, job_id: str, *, starred: bool, priority: int) -> dict[str, Any]:
        if priority not in {0, 1}:
            raise ValueError("priority must be 0 (normal) or 1 (high)")
        with self.connect() as connection:
            row = self._get_job_row(connection, job_id)
            self._update_job(
                connection,
                job_id,
                {
                    "starred": int(starred),
                    "manual_priority": priority,
                    "priority_updated_at": utc_now_iso(),
                },
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="manual_priority_updated",
                from_status=None,
                to_status=None,
                message="Manual queue priority updated.",
                metadata={"starred": starred, "manual_priority": priority},
            )
            updated = self._get_job_row(connection, job_id)
        return row_to_job(updated)

    def get_q2_task(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM q2_tasks WHERE job_id = ?", (job_id,)
            ).fetchone()
        return row_to_q2_task(row) if row else None

    def get_packet(self, packet_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM packets WHERE id = ?", (packet_id,)).fetchone()
        if row is None:
            raise JobNotFoundError(packet_id)
        return row_to_packet(row)

    def get_packet_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM packets WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        return row_to_packet(row) if row else None

    def get_latest_ready_packet_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM packets WHERE job_id = ? AND status = 'ready' "
                "ORDER BY completed_at DESC, created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        return row_to_packet(row) if row else None

    def create_packet_attempt(self, task_id: str, job_id: str) -> dict[str, Any]:
        now = utc_now_iso()
        packet_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO packets (id, job_id, q2_task_id, status, selected_cv_family,
                created_at, updated_at) VALUES (?, ?, ?, 'generating', ?, ?, ?)""",
                (packet_id, job_id, task_id,
                 self._get_job_row(connection, job_id)["selected_cv_family"], now, now),
            )
            self._update_job(connection, job_id, {"current_packet_id": packet_id})
            row = connection.execute(
                "SELECT * FROM packets WHERE id = ?", (packet_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("packet attempt did not persist")
        return row_to_packet(row)

    def create_review_packet_attempt(
        self,
        *,
        job_id: str,
        q2_task_id: str,
        source_packet_id: str,
        review_id: str,
        review_resolution_id: str,
        idempotency_key: str,
        selected_cv_family: str,
        generation_reason: str,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        packet_id = str(uuid4())
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM packets WHERE idempotency_key = ? AND status = 'ready'",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return row_to_packet(existing)
            connection.execute(
                """INSERT INTO packets (
                    id, job_id, q2_task_id, status, selected_cv_family,
                    generation_kind, source_packet_id, review_id, review_resolution_id,
                    idempotency_key, generation_reason, created_at, updated_at
                )
                VALUES (?, ?, ?, 'generating', ?, 'review_regeneration', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    packet_id,
                    job_id,
                    q2_task_id,
                    selected_cv_family,
                    source_packet_id,
                    review_id,
                    review_resolution_id,
                    idempotency_key,
                    generation_reason,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM packets WHERE id = ?", (packet_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("review packet attempt did not persist")
        return row_to_packet(row)

    def complete_packet_attempt(
        self, task_id: str, packet_id: str, *, artifact_directory: str,
        pdf_path: str, tex_path: str, selected_cv_path: str, manifest_path: str,
        page_count: int | None, tailoring_decision_path: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.connect() as connection:
            task = connection.execute(
                "SELECT * FROM q2_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if task is None or task["status"] != "running":
                raise ValueError("only running Q2 tasks can complete a packet")
            connection.execute(
                """UPDATE packets SET status='ready', artifact_directory=?, pdf_path=?,
                tex_path=?, selected_cv_path=?, manifest_path=?, tailoring_decision_path=?,
                page_count=?,
                updated_at=?, completed_at=? WHERE id=?""",
                (artifact_directory, pdf_path, tex_path, selected_cv_path, manifest_path,
                 tailoring_decision_path, page_count, now, now, packet_id),
            )
            connection.execute(
                """UPDATE q2_tasks SET status='ready', completed_at=?, lease_owner=NULL,
                lease_expires_at=NULL, updated_at=?, failure_reason=NULL WHERE id=?""",
                (now, now, task_id),
            )
            job = self._get_job_row(connection, task["job_id"])
            validate_packet_transition(job["packet_status"], "ready")
            self._update_job(
                connection, task["job_id"],
                {"packet_status": "ready", "placeholder_artifact_path": pdf_path},
            )
            self._insert_event(
                connection, job_id=task["job_id"], event_type="packet_ready",
                from_status="generating", to_status="ready",
                message="Phase 5 packet PDF generated.",
                metadata={"task_id": task_id, "packet_id": packet_id, "page_count": page_count},
            )
            row = connection.execute(
                "SELECT * FROM packets WHERE id = ?", (packet_id,)
            ).fetchone()
        return row_to_packet(row)

    def complete_review_packet_attempt(
        self,
        *,
        packet_id: str,
        artifact_directory: str,
        pdf_path: str,
        tex_path: str,
        selected_cv_path: str,
        manifest_path: str,
        page_count: int | None,
        tailoring_decision_path: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """UPDATE packets SET status='ready', artifact_directory=?, pdf_path=?,
                tex_path=?, selected_cv_path=?, manifest_path=?, tailoring_decision_path=?,
                page_count=?, updated_at=?, completed_at=? WHERE id=?""",
                (
                    artifact_directory,
                    pdf_path,
                    tex_path,
                    selected_cv_path,
                    manifest_path,
                    tailoring_decision_path,
                    page_count,
                    now,
                    now,
                    packet_id,
                ),
            )
            packet = connection.execute(
                "SELECT * FROM packets WHERE id = ?", (packet_id,)
            ).fetchone()
        return row_to_packet(packet)

    def save_tailoring_decision(
        self,
        job_id: str,
        packet_id: str,
        decision: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            job = self._get_job_row(connection, job_id)
            tailoring_id = str(uuid4())
            connection.execute(
                """INSERT INTO job_tailoring_decisions (
                id, job_id, packet_id, base_family, classification_decision,
                base_blocks_json, final_blocks_json, removed_block, inserted_block,
                scores_json, replacement_gain, evidence_json, requires_review,
                tailoring_status, fallback_reason, policy_version, registry_version,
                classifier_version, decision_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tailoring_id,
                    job_id,
                    packet_id,
                    decision["base_family"],
                    decision.get("classification_decision"),
                    json.dumps(decision.get("base_blocks", []), sort_keys=True),
                    json.dumps(decision.get("final_order", []), sort_keys=True),
                    decision.get("removed_block"),
                    decision.get("inserted_block"),
                    json.dumps({
                        "base_block_scores": decision.get("base_block_scores", []),
                        "candidate_blocks": decision.get("candidate_blocks", []),
                    }, sort_keys=True),
                    float(decision.get("replacement_gain") or 0.0),
                    json.dumps(decision.get("job_evidence", []), sort_keys=True),
                    int(bool(decision.get("requires_review"))),
                    decision["tailoring_status"],
                    decision.get("fallback_reason"),
                    decision["policy_version"],
                    decision["registry_version"],
                    decision["classifier_version"],
                    json.dumps(decision, sort_keys=True),
                    now,
                ),
            )
            if _tailoring_needs_review(decision):
                self._ensure_pending_review(
                    connection,
                    owner_id=job["owner_id"],
                    job_id=job_id,
                    packet_id=packet_id,
                    review_type="tailoring",
                    classification_ref_id=None,
                    tailoring_ref_id=tailoring_id,
                    reason=f"tailoring_status:{decision['tailoring_status']}",
                )

    def get_tailoring_decision(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_tailoring_decisions "
                "WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        return row_to_tailoring_decision(row) if row else None

    def list_reviews(
        self,
        *,
        owner_id: str = "local",
        status: str | None = None,
        review_type: str | None = None,
        family: str | None = None,
        job_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["r.owner_id = ?"]
        params: list[Any] = [owner_id]
        if status:
            clauses.append("r.status = ?")
            params.append(status)
        if review_type:
            clauses.append("r.review_type = ?")
            params.append(review_type)
        if job_id:
            clauses.append("r.job_id = ?")
            params.append(job_id)
        if family:
            clauses.append(
                "(c.selected_family = ? OR t.base_family = ? OR j.selected_cv_family = ?)"
            )
            params.extend([family, family, family])
        where = " AND ".join(clauses)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT r.*, j.title AS job_title, j.company AS job_company,
                       j.selected_cv_family AS job_selected_family,
                       c.selected_family AS classification_family,
                       c.decision AS classification_decision,
                       c.requires_review AS classification_requires_review,
                       t.tailoring_status AS tailoring_status,
                       t.requires_review AS tailoring_requires_review
                FROM review_items r
                JOIN jobs j ON j.id = r.job_id
                LEFT JOIN job_family_classifications c ON c.id = r.classification_ref_id
                LEFT JOIN job_tailoring_decisions t ON t.id = r.tailoring_ref_id
                WHERE {where}
                ORDER BY r.created_at DESC
                """,
                tuple(params),
            ).fetchall()
        return [row_to_review_summary(row) for row in rows]

    def get_review(self, review_id: str, *, owner_id: str = "local") -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM review_items WHERE id = ? AND owner_id = ?",
                (review_id, owner_id),
            ).fetchone()
            if row is None:
                raise JobNotFoundError(review_id)
            return self._review_detail(connection, row)

    def create_manual_review(
        self,
        job_id: str,
        *,
        owner_id: str = "local",
        review_type: str = "classification",
        reason: str = "manual_review_requested",
    ) -> dict[str, Any]:
        with self.connect() as connection:
            job = self._get_job_row(connection, job_id)
            if job["owner_id"] != owner_id:
                raise JobNotFoundError(job_id)
            classification_ref_id = None
            tailoring_ref_id = None
            packet_id = None
            if review_type == "classification":
                row = connection.execute(
                    "SELECT id FROM job_family_classifications WHERE job_id = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (job_id,),
                ).fetchone()
                classification_ref_id = str(row["id"]) if row else None
            elif review_type == "tailoring":
                row = connection.execute(
                    "SELECT id, packet_id FROM job_tailoring_decisions WHERE job_id = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (job_id,),
                ).fetchone()
                if row is not None:
                    tailoring_ref_id = str(row["id"])
                    packet_id = row["packet_id"]
            else:
                raise ValueError("unknown review type")
            review_id = self._ensure_pending_review(
                connection,
                owner_id=owner_id,
                job_id=job_id,
                packet_id=packet_id,
                review_type=review_type,
                classification_ref_id=classification_ref_id,
                tailoring_ref_id=tailoring_ref_id,
                reason=reason,
            )
            row = connection.execute(
                "SELECT * FROM review_items WHERE id = ?",
                (review_id,),
            ).fetchone()
            return self._review_detail(connection, row)

    def resolve_review(
        self,
        review_id: str,
        resolution: dict[str, Any],
        *,
        owner_id: str = "local",
    ) -> dict[str, Any]:
        action = str(resolution.get("action") or "")
        reviewer_id = str(resolution.get("reviewer_id") or "").strip()
        if action not in REVIEW_ACTIONS:
            raise ValueError("unknown review action")
        if not reviewer_id:
            raise ValueError("reviewer_id is required")
        note = resolution.get("review_note")
        if note is not None and not isinstance(note, str):
            raise ValueError("review_note must be a string")
        with self.connect() as connection:
            review = connection.execute(
                "SELECT * FROM review_items WHERE id = ? AND owner_id = ?",
                (review_id, owner_id),
            ).fetchone()
            if review is None:
                raise JobNotFoundError(review_id)
            detail = self._review_detail(connection, review)
            resolved = self._validate_review_resolution(detail, resolution)
            now = utc_now_iso()
            resolution_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO review_resolutions (
                    id, review_id, owner_id, job_id, packet_id, action, reviewer_id,
                    review_note, original_family, resolved_family, original_blocks_json,
                    resolved_blocks_json, resolution_json, classifier_version,
                    registry_version, policy_version, regeneration_status,
                    regeneration_packet_id, regeneration_job_id, source_packet_id,
                    queued_at, failure_reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution_id,
                    review_id,
                    owner_id,
                    detail["job_id"],
                    detail.get("packet_id"),
                    action,
                    reviewer_id,
                    note,
                    resolved["original_family"],
                    resolved["resolved_family"],
                    json.dumps(resolved["original_blocks"], sort_keys=True),
                    json.dumps(resolved["resolved_blocks"], sort_keys=True),
                    json.dumps(resolved, sort_keys=True),
                    resolved["classifier_version"],
                    resolved["registry_version"],
                    resolved["policy_version"],
                    resolved["regeneration_status"],
                    None,
                    None,
                    detail.get("packet_id"),
                    now if resolved["regeneration_status"] == "queued" else None,
                    resolved.get("failure_reason"),
                    now,
                ),
            )
            if resolved["regeneration_status"] == "queued":
                source_packet_id = detail.get("packet_id")
                if source_packet_id is None:
                    latest = connection.execute(
                        "SELECT id FROM packets WHERE job_id = ? AND status = 'ready' "
                        "ORDER BY completed_at DESC, created_at DESC LIMIT 1",
                        (detail["job_id"],),
                    ).fetchone()
                    source_packet_id = latest["id"] if latest else None
                key = _regeneration_idempotency_key(
                    resolution_id=resolution_id,
                    resolved_family=resolved["resolved_family"],
                    resolved_blocks=resolved["resolved_blocks"],
                    registry_version=resolved["registry_version"],
                    policy_version=resolved["policy_version"],
                )
                job_id = str(uuid4())
                connection.execute(
                    """INSERT INTO review_regeneration_jobs (
                        id, review_resolution_id, review_id, owner_id, job_id,
                        source_packet_id, idempotency_key, status, queued_at,
                        policy_version, registry_version, classifier_version,
                        packet_generator_version, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job_id,
                        resolution_id,
                        review_id,
                        owner_id,
                        detail["job_id"],
                        source_packet_id,
                        key,
                        now,
                        resolved["policy_version"],
                        resolved["registry_version"],
                        resolved["classifier_version"],
                        "phase-h-review-regeneration-v1",
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """UPDATE review_resolutions SET regeneration_job_id = ?,
                    source_packet_id = ?, queued_at = ? WHERE id = ?""",
                    (job_id, source_packet_id, now, resolution_id),
                )
            connection.execute(
                """
                UPDATE review_items
                SET status = ?, updated_at = ?, resolved_at = ?
                WHERE id = ?
                """,
                (resolved["review_status"], now, now, review_id),
            )
            self._insert_event(
                connection,
                job_id=detail["job_id"],
                event_type="review_resolved",
                from_status=detail["status"],
                to_status=resolved["review_status"],
                message=f"Review {action} recorded.",
                metadata={
                    "review_id": review_id,
                    "resolution_id": resolution_id,
                    "regeneration_status": resolved["regeneration_status"],
                },
            )
            updated = connection.execute(
                "SELECT * FROM review_items WHERE id = ?",
                (review_id,),
            ).fetchone()
            return self._review_detail(connection, updated)

    def export_review_feedback(self, *, owner_id: str = "local") -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT rr.*, ri.review_type, ri.reason, c.decision AS original_decision
                FROM review_resolutions rr
                JOIN review_items ri ON ri.id = rr.review_id
                LEFT JOIN job_family_classifications c ON c.id = ri.classification_ref_id
                WHERE rr.owner_id = ?
                ORDER BY rr.created_at ASC
                """,
                (owner_id,),
            ).fetchall()
        feedback = []
        for row in rows:
            resolution = json.loads(row["resolution_json"])
            feedback.append({
                "job_id": row["job_id"],
                "review_id": row["review_id"],
                "review_type": row["review_type"],
                "original_family": row["original_family"],
                "reviewed_family": row["resolved_family"],
                "original_decision": row["original_decision"],
                "review_action": row["action"],
                "original_blocks": json.loads(row["original_blocks_json"]),
                "reviewed_blocks": json.loads(row["resolved_blocks_json"]),
                "review_note": row["review_note"],
                "eligible_for_calibration": bool(resolution.get("eligible_for_calibration", True)),
            })
        return feedback

    def claim_next_regeneration_job(
        self,
        *,
        owner: str,
        lease_expires_at: str,
        max_attempts: int = REGENERATION_MAX_ATTEMPTS,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM review_regeneration_jobs
                WHERE status = 'queued' AND attempt_count < ?
                ORDER BY queued_at ASC LIMIT 1""",
                (max_attempts,),
            ).fetchone()
            if row is None:
                return None
            now = utc_now_iso()
            connection.execute(
                """UPDATE review_regeneration_jobs
                SET status='processing', lease_owner=?, lease_expires_at=?,
                    attempt_count=attempt_count + 1, started_at=COALESCE(started_at, ?),
                    updated_at=?
                WHERE id=? AND status='queued'""",
                (owner, lease_expires_at, now, now, row["id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM review_regeneration_jobs WHERE id = ?", (row["id"],)
            ).fetchone()
            if claimed is None or claimed["status"] != "processing":
                return None
            connection.execute(
                """UPDATE review_resolutions
                SET regeneration_status='processing', started_at=COALESCE(started_at, ?),
                    attempt_count=?
                WHERE id=?""",
                (now, claimed["attempt_count"], claimed["review_resolution_id"]),
            )
            self._insert_event(
                connection,
                job_id=claimed["job_id"],
                event_type="review_regeneration_claimed",
                from_status="queued",
                to_status="processing",
                message="Review packet regeneration job claimed.",
                metadata={
                    "regeneration_job_id": claimed["id"],
                    "resolution_id": claimed["review_resolution_id"],
                    "owner": owner,
                },
            )
        return row_to_regeneration_job(claimed)

    def get_regeneration_job(self, regeneration_job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM review_regeneration_jobs WHERE id = ?",
                (regeneration_job_id,),
            ).fetchone()
        if row is None:
            raise JobNotFoundError(regeneration_job_id)
        return row_to_regeneration_job(row)

    def get_review_resolution(self, resolution_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM review_resolutions WHERE id = ?", (resolution_id,)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(resolution_id)
        return row_to_review_resolution(row)

    def complete_regeneration_job(self, regeneration_job_id: str, packet_id: str) -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM review_regeneration_jobs WHERE id = ?",
                (regeneration_job_id,),
            ).fetchone()
            if row is None:
                raise JobNotFoundError(regeneration_job_id)
            connection.execute(
                """UPDATE review_regeneration_jobs
                SET status='complete', generated_packet_id=?, completed_at=?,
                    lease_owner=NULL, lease_expires_at=NULL, failure_code=NULL,
                    failure_reason=NULL, updated_at=?
                WHERE id=?""",
                (packet_id, now, now, regeneration_job_id),
            )
            connection.execute(
                """UPDATE review_resolutions
                SET regeneration_status='complete', regeneration_packet_id=?,
                    completed_at=?, failure_code=NULL, failure_reason=NULL,
                    attempt_count=?
                WHERE id=?""",
                (
                    packet_id,
                    now,
                    row["attempt_count"],
                    row["review_resolution_id"],
                ),
            )
            connection.execute(
                "UPDATE review_items SET status='approved', updated_at=? WHERE id=?",
                (now, row["review_id"]),
            )
            self._update_job(connection, row["job_id"], {"current_packet_id": packet_id})
            self._insert_event(
                connection,
                job_id=row["job_id"],
                event_type="review_regeneration_complete",
                from_status="processing",
                to_status="complete",
                message="Reviewed packet regeneration completed.",
                metadata={
                    "regeneration_job_id": regeneration_job_id,
                    "resolution_id": row["review_resolution_id"],
                    "packet_id": packet_id,
                    "source_packet_id": row["source_packet_id"],
                },
            )

    def fail_regeneration_job(
        self,
        regeneration_job_id: str,
        *,
        code: str,
        reason: str,
        retryable: bool = False,
        max_attempts: int = REGENERATION_MAX_ATTEMPTS,
    ) -> None:
        now = utc_now_iso()
        safe_reason = _safe_failure_reason(reason)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM review_regeneration_jobs WHERE id = ?",
                (regeneration_job_id,),
            ).fetchone()
            if row is None:
                raise JobNotFoundError(regeneration_job_id)
            should_retry = retryable and int(row["attempt_count"]) < max_attempts
            status = "queued" if should_retry else "failed"
            connection.execute(
                """UPDATE review_regeneration_jobs
                SET status=?, lease_owner=NULL, lease_expires_at=NULL,
                    failed_at=CASE WHEN ? = 'failed' THEN ? ELSE failed_at END,
                    failure_code=?, failure_reason=?, updated_at=?
                WHERE id=?""",
                (status, status, now, code, safe_reason, now, regeneration_job_id),
            )
            connection.execute(
                """UPDATE review_resolutions
                SET regeneration_status=?,
                    failed_at=CASE WHEN ? = 'failed' THEN ? ELSE failed_at END,
                    failure_code=?, failure_reason=?, attempt_count=?
                WHERE id=?""",
                (
                    status,
                    status,
                    now,
                    code,
                    safe_reason,
                    row["attempt_count"],
                    row["review_resolution_id"],
                ),
            )
            if status == "failed":
                connection.execute(
                    "UPDATE review_items SET status='regeneration_failed', updated_at=? WHERE id=?",
                    (now, row["review_id"]),
                )
            self._insert_event(
                connection,
                job_id=row["job_id"],
                event_type="review_regeneration_failed",
                from_status="processing",
                to_status=status,
                message="Reviewed packet regeneration failed.",
                metadata={
                    "regeneration_job_id": regeneration_job_id,
                    "resolution_id": row["review_resolution_id"],
                    "failure_code": code,
                    "retry_queued": should_retry,
                },
            )

    def recover_stale_regeneration_jobs(
        self,
        *,
        now: str,
        max_attempts: int = REGENERATION_MAX_ATTEMPTS,
    ) -> int:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM review_regeneration_jobs
                WHERE status = 'processing' AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < ?""",
                (now,),
            ).fetchall()
            for row in rows:
                retry = int(row["attempt_count"]) < max_attempts
                status = "queued" if retry else "failed"
                failed_at = None if retry else now
                connection.execute(
                    """UPDATE review_regeneration_jobs
                    SET status=?, lease_owner=NULL, lease_expires_at=NULL,
                        failed_at=COALESCE(?, failed_at), failure_code='worker_interrupted',
                        failure_reason='Worker lease expired before completion.',
                        updated_at=? WHERE id=?""",
                    (status, failed_at, now, row["id"]),
                )
                connection.execute(
                    """UPDATE review_resolutions
                    SET regeneration_status=?, failed_at=COALESCE(?, failed_at),
                        failure_code='worker_interrupted',
                        failure_reason='Worker lease expired before completion.',
                        attempt_count=? WHERE id=?""",
                    (status, failed_at, row["attempt_count"], row["review_resolution_id"]),
                )
                self._insert_event(
                    connection,
                    job_id=row["job_id"],
                    event_type="review_regeneration_stale_recovered",
                    from_status="processing",
                    to_status=status,
                    message="Expired review-regeneration lease was recovered.",
                    metadata={"regeneration_job_id": row["id"], "requeued": retry},
                )
        return len(rows)

    def fail_packet_attempt(
        self, task_id: str, packet_id: str, *, stage: str, reason: str
    ) -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            task = connection.execute(
                "SELECT * FROM q2_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if task is None:
                return
            connection.execute(
                "UPDATE packets SET status='failed', failure_stage=?, failure_reason=?, "
                "updated_at=? WHERE id=?",
                (stage, reason, now, packet_id),
            )
            connection.execute(
                """UPDATE q2_tasks SET status='failed', failure_reason=?, lease_owner=NULL,
                lease_expires_at=NULL, updated_at=? WHERE id=?""",
                (f"{stage}: {reason}", now, task_id),
            )
            self._update_job(
                connection, task["job_id"],
                {"packet_status": "failed", "failure_reason": reason,
                 "reason": "Packet generation failed."},
            )
            self._insert_event(
                connection, job_id=task["job_id"], event_type="packet_failed",
                from_status="generating", to_status="failed",
                message="Phase 5 packet generation failed.",
                metadata={"task_id": task_id, "packet_id": packet_id, "stage": stage,
                          "reason": reason},
            )

    def list_q2_tasks(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM q2_tasks ORDER BY priority DESC, created_at ASC"
            ).fetchall()
        return [row_to_q2_task(row) for row in rows]

    def q2_active_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT count(*) AS count FROM q2_tasks "
                "WHERE status IN ('queued', 'claimed', 'running')"
            ).fetchone()
        return int(row["count"])

    def automatic_promotions_today(self, day_prefix: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT count(*) AS count FROM q2_tasks "
                "WHERE manual_override = 0 AND created_at LIKE ?",
                (f"{day_prefix}%",),
            ).fetchone()
        return int(row["count"])

    def eligible_scored_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT j.* FROM jobs j
                LEFT JOIN q2_tasks t ON t.job_id = j.id
                WHERE j.intake_status = 'scored'
                  AND j.overall_score IS NOT NULL
                  AND j.archived_at IS NULL
                  AND t.id IS NULL
                ORDER BY j.manual_priority DESC, j.starred DESC,
                         j.overall_score DESC, j.created_at ASC
                """
            ).fetchall()
        return [row_to_job(row) for row in rows]

    def create_q2_task(
        self,
        job_id: str,
        *,
        promotion_reason: str,
        manual_override: bool,
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now_iso()
        with self.connect() as connection:
            job = self._get_job_row(connection, job_id)
            existing = connection.execute(
                "SELECT * FROM q2_tasks WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing is not None:
                return row_to_q2_task(existing), False
            if job["archived_at"] is not None:
                raise ValueError("archived jobs cannot be promoted")
            if job["intake_status"] != "scored" or job["overall_score"] is None:
                raise ValueError("only successfully scored jobs can be promoted")
            blockers = json.loads(job["hard_blockers_json"] or "[]")
            if blockers:
                raise ValueError(
                    "job has unrecoverable hard blockers and cannot be promoted"
                )
            if job["packet_status"] not in {"not_requested", "failed", "manual_review"}:
                raise DuplicateActivePacketError(job_id)
            validate_packet_transition(job["packet_status"], "queued")
            task_id = str(uuid4())
            connection.execute(
                """INSERT INTO q2_tasks (
                id, job_id, status, priority, promotion_reason, score_at_promotion,
                manual_override, attempt_count, created_at, updated_at)
                VALUES (?, ?, 'queued', ?, ?, ?, ?, 0, ?, ?)""",
                (
                    task_id,
                    job_id,
                    int(job["manual_priority"]),
                    promotion_reason,
                    job["overall_score"],
                    int(manual_override),
                    now,
                    now,
                ),
            )
            self._update_job(
                connection,
                job_id,
                {
                    "packet_status": "queued",
                    "promotion_reason": promotion_reason,
                    "reason": "Queued for Queue 2 packet generation.",
                },
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="q2_task_promoted",
                from_status=job["packet_status"],
                to_status="queued",
                message="Scored job promoted to persistent Q2 queue.",
                metadata={
                    "task_id": task_id,
                    "promotion_reason": promotion_reason,
                    "manual_override": manual_override,
                },
            )
            task = connection.execute(
                "SELECT * FROM q2_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if task is None:
            raise RuntimeError("Q2 task creation did not persist")
        return row_to_q2_task(task), True

    def claim_next_q2_task(
        self, *, owner: str, concurrency: int, lease_expires_at: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            active = connection.execute(
                "SELECT count(*) AS count FROM q2_tasks "
                "WHERE status IN ('claimed', 'running')"
            ).fetchone()
            if int(active["count"]) >= concurrency:
                return None
            row = connection.execute(
                "SELECT * FROM q2_tasks WHERE status = 'queued' "
                "ORDER BY priority DESC, created_at ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE q2_tasks SET status = 'claimed', lease_owner = ?,
                lease_expires_at = ?, attempt_count = attempt_count + 1, updated_at = ?
                WHERE id = ? AND status = 'queued'""",
                (owner, lease_expires_at, utc_now_iso(), row["id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM q2_tasks WHERE id = ?", (row["id"],)
            ).fetchone()
            self._insert_event(
                connection,
                job_id=row["job_id"],
                event_type="q2_task_claimed",
                from_status="queued",
                to_status="claimed",
                message="Queue 2 worker claimed persistent task.",
                metadata={"task_id": row["id"], "owner": owner},
            )
        return row_to_q2_task(claimed) if claimed else None

    def start_q2_task(self, task_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM q2_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown Q2 task: {task_id}")
            if row["status"] != "claimed":
                raise ValueError("only claimed Q2 tasks can start")
            connection.execute(
                "UPDATE q2_tasks SET status = 'running', started_at = ?, "
                "updated_at = ? WHERE id = ?",
                (utc_now_iso(), utc_now_iso(), task_id),
            )
            job = self._get_job_row(connection, row["job_id"])
            validate_packet_transition(job["packet_status"], "generating")
            self._update_job(connection, row["job_id"], {"packet_status": "generating"})
            self._insert_event(
                connection,
                job_id=row["job_id"],
                event_type="q2_task_running",
                from_status="claimed",
                to_status="running",
                message="Queue 2 task started packet generation.",
                metadata={"task_id": task_id},
            )
            updated = connection.execute(
                "SELECT * FROM q2_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return row_to_q2_task(updated)

    def complete_q2_task(self, task_id: str, artifact_path: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM q2_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None or row["status"] != "running":
                raise ValueError("only running Q2 tasks can complete")
            now = utc_now_iso()
            connection.execute(
                """UPDATE q2_tasks SET status = 'ready', completed_at = ?, lease_owner = NULL,
                lease_expires_at = NULL, updated_at = ? WHERE id = ?""",
                (now, now, task_id),
            )
            job = self._get_job_row(connection, row["job_id"])
            validate_packet_transition(job["packet_status"], "ready")
            self._update_job(
                connection,
                row["job_id"],
                {"packet_status": "ready", "placeholder_artifact_path": artifact_path},
            )
            self._insert_event(
                connection,
                job_id=row["job_id"],
                event_type="q2_task_ready",
                from_status="running",
                to_status="ready",
                message="Queue 2 completed legacy placeholder artifact.",
                metadata={
                    "task_id": task_id,
                    "artifact_path": artifact_path,
                    "legacy_placeholder": True,
                },
            )
            updated = connection.execute(
                "SELECT * FROM q2_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return row_to_q2_task(updated)

    def recover_stale_q2_tasks(self, *, now: str, retry_limit: int) -> int:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM q2_tasks WHERE status IN ('claimed', 'running') "
                "AND lease_expires_at IS NOT NULL AND lease_expires_at < ?",
                (now,),
            ).fetchall()
            for row in rows:
                retry = int(row["attempt_count"]) < retry_limit
                status = "queued" if retry else "failed"
                connection.execute(
                    """UPDATE q2_tasks SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                    failure_reason = ?, updated_at = ? WHERE id = ?""",
                    (status, "worker lease expired", now, row["id"]),
                )
                job = self._get_job_row(connection, row["job_id"])
                packet_status = "queued" if retry else "failed"
                self._update_job(connection, row["job_id"], {"packet_status": packet_status})
                self._insert_event(
                    connection,
                    job_id=row["job_id"],
                    event_type="q2_task_stale_recovered",
                    from_status=row["status"],
                    to_status=status,
                    message="Expired Q2 lease was recovered.",
                    metadata={"task_id": row["id"], "requeued": retry},
                )
        return len(rows)

    def archive_job(self, job_id: str) -> dict[str, Any]:
        now = utc_now_iso()
        with self.connect() as connection:
            row = self._get_job_row(connection, job_id)
            if row["archived_at"] is None:
                self._update_job(connection, job_id, {"archived_at": now})
                self._insert_event(
                    connection,
                    job_id=job_id,
                    event_type="job_archived",
                    from_status=None,
                    to_status=None,
                    message="Job archived and hidden from active dashboard results.",
                    metadata={},
                )
            updated = self._get_job_row(connection, job_id)
        return row_to_job(updated)

    def restore_job(self, job_id: str, *, owner_id: str = "local") -> dict[str, Any]:
        with self.connect() as connection:
            row = self._get_job_row(connection, job_id)
            if row["owner_id"] != owner_id:
                raise JobNotFoundError(job_id)
            if row["archived_at"] is not None:
                self._update_job(connection, job_id, {"archived_at": None})
                self._insert_event(
                    connection,
                    job_id=job_id,
                    event_type="job_restored",
                    from_status=None,
                    to_status=None,
                    message="Archived job restored to the active dashboard.",
                    metadata={},
                )
            updated = self._get_job_row(connection, job_id)
        return row_to_job(updated)

    def start_analysis_run(
        self,
        job_id: str,
        *,
        owner_id: str = "local",
        trigger: str,
        restore: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now_iso()
        with self.connect() as connection:
            row = self._get_job_row(connection, job_id)
            if row["owner_id"] != owner_id:
                raise JobNotFoundError(job_id)
            if restore and row["archived_at"] is not None:
                self._update_job(connection, job_id, {"archived_at": None})
                self._insert_event(
                    connection,
                    job_id=job_id,
                    event_type="job_restored",
                    from_status=None,
                    to_status=None,
                    message="Archived job restored to the active dashboard.",
                    metadata={"trigger": trigger},
                )
                row = self._get_job_row(connection, job_id)
            if row["archived_at"] is not None:
                raise ValueError("archived jobs must be restored before re-scoring")
            active = connection.execute(
                "SELECT * FROM analysis_runs WHERE job_id = ? "
                "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if active is not None:
                return row_to_analysis_run(active), False
            run_id = self._insert_analysis_run(
                connection,
                job_id=job_id,
                owner_id=owner_id,
                trigger=trigger,
                status="queued",
            )
            self._update_job(
                connection,
                job_id,
                {
                    "current_analysis_run_id": run_id,
                    "intake_status": "queued",
                    "reason": "Queued for re-analysis.",
                    "failure_reason": None,
                    "manual_review_reason": None,
                    "scoring_status": "queued",
                },
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="analysis_run_queued",
                from_status=row["intake_status"],
                to_status="queued",
                message="Analysis run queued.",
                metadata={"analysis_run_id": run_id, "trigger": trigger},
            )
            created = connection.execute(
                "SELECT * FROM analysis_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return row_to_analysis_run(created), True

    def get_active_analysis_run(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_runs WHERE job_id = ? "
                "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        return row_to_analysis_run(row) if row else None

    def mark_analysis_run_running(self, job_id: str) -> dict[str, Any] | None:
        now = utc_now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_runs WHERE job_id = ? AND status = 'queued' "
                "ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if row is None:
                job = self._get_job_row(connection, job_id)
                run_id = self._insert_analysis_run(
                    connection,
                    job_id=job_id,
                    owner_id=job["owner_id"],
                    trigger="legacy_queue",
                    status="running",
                    started_at=now,
                )
                self._update_job(connection, job_id, {"current_analysis_run_id": run_id})
                row = connection.execute(
                    "SELECT * FROM analysis_runs WHERE id = ?", (run_id,)
                ).fetchone()
            else:
                connection.execute(
                    "UPDATE analysis_runs SET status='running', "
                    "started_at=COALESCE(started_at, ?), updated_at=? WHERE id=?",
                    (now, now, row["id"]),
                )
                row = connection.execute(
                    "SELECT * FROM analysis_runs WHERE id = ?", (row["id"],)
                ).fetchone()
        return row_to_analysis_run(row) if row else None

    def complete_analysis_run(self, job_id: str, result: Any) -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_runs WHERE job_id = ? "
                "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if row is None:
                return
            hybrid = result.score_breakdown.get("hybrid", {})
            tailoring = self.get_tailoring_decision(job_id)
            connection.execute(
                """UPDATE analysis_runs SET status='complete', completed_at=?,
                updated_at=?, candidate_fit_json=?, family_classification_json=?,
                semantic_requirements_json=?, fused_requirements_json=?,
                project_portfolio_json=?, policy_versions_json=? WHERE id=?""",
                (
                    now,
                    now,
                    json.dumps({
                        "overall_score": result.overall_score,
                        "recommendation": result.recommendation,
                        "scoring_version": result.score_breakdown.get("formula_version"),
                    }, sort_keys=True),
                    json.dumps(
                        getattr(result, "family_classification", {}) or {},
                        sort_keys=True,
                    ),
                    json.dumps(hybrid.get("requirement_extraction") or {}, sort_keys=True),
                    json.dumps(hybrid.get("fused_requirements") or {}, sort_keys=True),
                    json.dumps(
                        (tailoring or {}).get("decision", {}).get("project_portfolio", {}),
                        sort_keys=True,
                    ),
                    json.dumps({
                        "scoring": result.score_breakdown.get("formula_version"),
                        "hybrid": result.score_breakdown.get("hybrid_formula_version"),
                    }, sort_keys=True),
                    row["id"],
                ),
            )

    def fail_analysis_run(self, job_id: str, *, code: str, reason: str) -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_runs WHERE job_id = ? "
                "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if row is None:
                return
            connection.execute(
                """UPDATE analysis_runs SET status='failed', failure_code=?,
                failure_reason=?, completed_at=?, updated_at=? WHERE id=?""",
                (code, _safe_failure_reason(reason), now, now, row["id"]),
            )

    def list_analysis_runs(self, job_id: str, *, owner_id: str = "local") -> list[dict[str, Any]]:
        with self.connect() as connection:
            job = self._get_job_row(connection, job_id)
            if job["owner_id"] != owner_id:
                raise JobNotFoundError(job_id)
            rows = connection.execute(
                "SELECT * FROM analysis_runs WHERE job_id = ? ORDER BY created_at DESC",
                (job_id,),
            ).fetchall()
        return [row_to_analysis_run(row) for row in rows]

    def retry_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = self._get_job_row(connection, job_id)
            if row["intake_status"] in {"failed", "manual_review"}:
                validate_intake_transition(row["intake_status"], "queued")
                self._update_job(
                    connection,
                    job_id,
                    {
                        "intake_status": "queued",
                        "reason": "Retry queued for intake processing.",
                        "failure_reason": None,
                        "manual_review_reason": None,
                        "extraction_warnings_json": "[]",
                    },
                )
                self._insert_event(
                    connection,
                    job_id=job_id,
                    event_type="retry_queued",
                    from_status=row["intake_status"],
                    to_status="queued",
                    message="Retry reset intake to queued.",
                    metadata={"queue": "q1"},
                )
            elif row["packet_status"] in {"failed", "manual_review"}:
                validate_packet_transition(row["packet_status"], "queued")
                self._update_job(
                    connection,
                    job_id,
                    {"packet_status": "queued", "reason": "Retry queued for packet generation.",
                     "failure_reason": None},
                )
                connection.execute(
                    "UPDATE q2_tasks SET status='queued', failure_reason=NULL, "
                    "updated_at=? WHERE job_id=?",
                    (utc_now_iso(), job_id),
                )
                self._insert_event(
                    connection,
                    job_id=job_id,
                    event_type="retry_queued",
                    from_status=row["packet_status"],
                    to_status="queued",
                    message="Retry reset packet generation to queued.",
                    metadata={"queue": "q2"},
                )
            else:
                raise ValueError("retry is only available for failed or manual_review states")
            updated = self._get_job_row(connection, job_id)
        return row_to_job(updated)

    def next_job_with_intake_status(self, status: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE intake_status = ? AND archived_at IS NULL
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (status,),
            ).fetchone()
        return row_to_job(row) if row is not None else None

    def save_scoring_result(self, job_id: str, result: Any) -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            job = self._get_job_row(connection, job_id)
            analysis_run_id = job["current_analysis_run_id"]
            for block in result.block_scores:
                connection.execute(
                    """INSERT INTO job_block_scores (
                    id, job_id, analysis_run_id, scoring_version, block_id, block_type, block_name,
                    technical_match, keyword_match, responsibility_match, evidence_strength,
                    seniority_fit, recency, impressiveness, domain_match, risk_of_overclaim,
                    aggregate_score, reason, matched_requirements_json, unmatched_requirements_json,
                    created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        job_id,
                        analysis_run_id,
                        block["scoring_version"],
                        block["block_id"],
                        block["block_type"], block["block_name"], block["technical_match"],
                        block["keyword_match"], block["responsibility_match"],
                        block["evidence_strength"], block["seniority_fit"], block["recency"],
                        block["impressiveness"], block["domain_match"], block["risk_of_overclaim"],
                        block["aggregate_score"], block["reason"],
                        json.dumps(block["matched_requirements"]),
                        json.dumps(block["unmatched_requirements"]), now,
                    ),
                )
            hybrid = result.score_breakdown.get("hybrid", {})
            connection.execute(
                """INSERT INTO job_semantic_assessments (
                id, job_id, analysis_run_id, scoring_version, scoring_mode, llm_call_status,
                llm_failure_reason, model_name, prompt_version, semantic_schema_version,
                deterministic_family_json, llm_family_json, family_decision_json,
                semantic_assessment_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    job_id,
                    analysis_run_id,
                    result.score_breakdown.get(
                        "hybrid_formula_version", "phase3-deterministic-v1"
                    ),
                    hybrid.get("scoring_mode", "deterministic_only"),
                    hybrid.get("llm_call_status", "not_called"),
                    hybrid.get("llm_failure_reason"),
                    hybrid.get("model"),
                    hybrid.get("prompt_version"),
                    hybrid.get("semantic_schema_version"),
                    json.dumps(hybrid.get("deterministic_family", result.selection)),
                    json.dumps(hybrid["llm_family"]) if hybrid.get("llm_family") else None,
                    json.dumps(hybrid["family_decision"])
                    if hybrid.get("family_decision")
                    else None,
                    json.dumps(hybrid["semantic_assessment"])
                    if hybrid.get("semantic_assessment")
                    else None,
                    now,
                ),
            )
            classification = getattr(result, "family_classification", {}) or {}
            if classification:
                classification_id = str(uuid4())
                connection.execute(
                    """INSERT INTO job_family_classifications (
                    id, job_id, analysis_run_id, classifier_version, config_version,
                    family_scores_json,
                    selected_family, secondary_family, confidence, decision, requires_review,
                    rule_evidence_json, semantic_evidence_json, deterministic_scores_json,
                    semantic_scores_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        classification_id,
                        job_id,
                        analysis_run_id,
                        classification["classifier_version"],
                        classification["config_version"],
                        json.dumps(classification["family_scores"], sort_keys=True),
                        classification["selected_family"],
                        classification.get("secondary_family"),
                        float(classification["confidence"]),
                        classification["decision"],
                        int(bool(classification["requires_review"])),
                        json.dumps(classification["rule_evidence"], sort_keys=True),
                        json.dumps(classification["semantic_evidence"], sort_keys=True),
                        json.dumps(
                            classification["deterministic_scores"], sort_keys=True
                        ),
                        json.dumps(classification["semantic_scores"], sort_keys=True)
                        if classification.get("semantic_scores") is not None
                        else None,
                        now,
                    ),
                )
                if _classification_needs_review(classification):
                    job = self._get_job_row(connection, job_id)
                    self._ensure_pending_review(
                        connection,
                        owner_id=job["owner_id"],
                        job_id=job_id,
                        packet_id=None,
                        review_type="classification",
                        classification_ref_id=classification_id,
                        tailoring_ref_id=None,
                        reason=f"classification_decision:{classification['decision']}",
                    )
            connection.execute(
                """INSERT INTO job_scores (
                id, job_id, analysis_run_id, scoring_version, structured_jd_json,
                family_selection_json,
                section_scores_json, score_breakdown_json, strengths_json, gaps_json,
                hard_blockers_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), job_id, analysis_run_id, "phase3-deterministic-v1",
                    json.dumps(result.structured_jd, sort_keys=True),
                    json.dumps(result.selection, sort_keys=True),
                    json.dumps(result.section_scores, sort_keys=True),
                    json.dumps(result.score_breakdown, sort_keys=True),
                    json.dumps(result.strengths), json.dumps(result.gaps),
                    json.dumps(result.hard_blockers), now,
                ),
            )
            self._update_job(connection, job_id, {
                "structured_jd_json": json.dumps(result.structured_jd, sort_keys=True),
                "role_family": result.role_family,
                "selected_cv_family": result.selection["primary_family"],
                "secondary_cv_family": result.selection["secondary_family"],
                "cv_family_confidence": result.selection["confidence"],
                "cv_family_selection_json": json.dumps(result.selection, sort_keys=True),
                "family_classification_json": json.dumps(classification, sort_keys=True)
                if classification
                else None,
                "family_classifier_version": classification.get("classifier_version")
                if classification
                else None,
                "family_classification_decision": classification.get("decision")
                if classification
                else None,
                "family_classification_requires_review": int(
                    bool(classification.get("requires_review"))
                )
                if classification
                else 0,
                "scoring_status": "complete",
                "scoring_version": "phase3-deterministic-v1",
                "scoring_mode": hybrid.get("scoring_mode", "deterministic_only"),
                "llm_call_status": hybrid.get("llm_call_status", "not_called"),
                "llm_failure_reason": hybrid.get("llm_failure_reason"),
                "llm_model": hybrid.get("model"),
                "llm_prompt_version": hybrid.get("prompt_version"),
                "score_breakdown_json": json.dumps(result.score_breakdown, sort_keys=True),
                "section_scores_json": json.dumps(result.section_scores, sort_keys=True),
                "strengths_json": json.dumps(result.strengths),
                "gaps_json": json.dumps(result.gaps),
                "hard_blockers_json": json.dumps(result.hard_blockers),
                "overall_score": result.overall_score,
                "recommendation": result.recommendation,
                "reason": result.reason,
            })

    def get_score(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_scores WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        score = row_to_score(row) if row else None
        if score is not None:
            score["semantic_assessment"] = self.get_semantic_assessment(job_id)
        return score

    def get_semantic_assessment(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_semantic_assessments "
                "WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        return row_to_semantic_assessment(row) if row else None

    def get_family_classification(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_family_classifications "
                "WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        return row_to_family_classification(row) if row else None

    def list_block_scores(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            latest = connection.execute(
                "SELECT analysis_run_id FROM job_scores WHERE job_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            run_id = latest["analysis_run_id"] if latest else None
            if run_id:
                rows = connection.execute(
                    "SELECT * FROM job_block_scores WHERE job_id = ? "
                    "AND analysis_run_id = ? ORDER BY aggregate_score DESC",
                    (job_id, run_id),
                ).fetchall()
                return [row_to_block_score(row) for row in rows]
            rows = connection.execute(
                "SELECT * FROM job_block_scores WHERE job_id = ? ORDER BY aggregate_score DESC",
                (job_id,),
            ).fetchall()
        return [row_to_block_score(row) for row in rows]

    def set_duplicate_warning(self, job_id: str, warning: str) -> dict[str, Any]:
        with self.connect() as connection:
            self._get_job_row(connection, job_id)
            self._update_job(connection, job_id, {"duplicate_warning": warning})
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="probable_duplicate_detected",
                from_status=None,
                to_status=None,
                message=warning,
                metadata={},
            )
            row = self._get_job_row(connection, job_id)
        return row_to_job(row)

    def find_probable_duplicate(
        self,
        *,
        job_id: str,
        company: str | None,
        title: str | None,
        jd_text_fingerprint: str | None,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            if jd_text_fingerprint:
                row = connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE id != ? AND jd_text_fingerprint = ?
                    LIMIT 1
                    """,
                    (job_id, jd_text_fingerprint),
                ).fetchone()
                if row is not None:
                    return row_to_job(row)
            if company and title:
                row = connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE id != ?
                    AND lower(company) = lower(?)
                    AND lower(title) = lower(?)
                    LIMIT 1
                    """,
                    (job_id, company, title),
                ).fetchone()
                if row is not None:
                    return row_to_job(row)
        return None

    def _get_job_row(self, connection: sqlite3.Connection, job_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return row

    def _update_job(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        updates: dict[str, Any],
    ) -> None:
        values = {**updates, "updated_at": utc_now_iso()}
        assignments = ", ".join(f"{key} = ?" for key in values)
        connection.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            (*values.values(), job_id),
        )

    def _insert_analysis_run(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        owner_id: str,
        trigger: str,
        status: str,
        started_at: str | None = None,
    ) -> str:
        now = utc_now_iso()
        run_id = str(uuid4())
        job = self._get_job_row(connection, job_id)
        connection.execute(
            """INSERT INTO analysis_runs (
                id, job_id, owner_id, trigger, source_content_version, status,
                policy_versions_json, created_at, started_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                job_id,
                owner_id,
                trigger,
                job["jd_text_fingerprint"] or job["normalized_url"],
                status,
                json.dumps({"analysis_run_schema": "analysis-run-v1"}, sort_keys=True),
                now,
                started_at,
                now,
            ),
        )
        return run_id

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        message: str,
        metadata: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO job_events (
                id, job_id, event_type, from_status, to_status, message,
                metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                job_id,
                event_type,
                from_status,
                to_status,
                message,
                json.dumps(metadata, sort_keys=True),
                utc_now_iso(),
            ),
        )

    def _ensure_pending_review(
        self,
        connection: sqlite3.Connection,
        *,
        owner_id: str,
        job_id: str,
        packet_id: str | None,
        review_type: str,
        classification_ref_id: str | None,
        tailoring_ref_id: str | None,
        reason: str,
    ) -> str:
        existing = connection.execute(
            """
            SELECT id FROM review_items
            WHERE owner_id = ? AND job_id = ? AND review_type = ? AND status = 'pending'
            LIMIT 1
            """,
            (owner_id, job_id, review_type),
        ).fetchone()
        if existing is not None:
            return str(existing["id"])
        now = utc_now_iso()
        review_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO review_items (
                id, owner_id, job_id, packet_id, review_type, status,
                classification_ref_id, tailoring_ref_id, reason,
                created_at, updated_at, resolved_at
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, NULL)
            """,
            (
                review_id,
                owner_id,
                job_id,
                packet_id,
                review_type,
                classification_ref_id,
                tailoring_ref_id,
                reason,
                now,
                now,
            ),
        )
        self._insert_event(
            connection,
            job_id=job_id,
            event_type="review_created",
            from_status=None,
            to_status="pending",
            message=f"Pending {review_type} review created.",
            metadata={"review_id": review_id, "reason": reason},
        )
        return review_id

    def _insert_worker_event(
        self,
        connection: sqlite3.Connection,
        *,
        worker_type: str,
        instance_id: str,
        event_type: str,
        state: str | None,
        job_id: str | None,
        safe_code: str | None,
        message: str,
        metadata: dict[str, Any],
    ) -> None:
        connection.execute(
            """INSERT INTO worker_events (
                id, worker_type, instance_id, event_type, state, job_id,
                safe_code, message, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                worker_type,
                instance_id,
                event_type,
                state,
                job_id,
                safe_code,
                message,
                json.dumps(metadata, sort_keys=True),
                utc_now_iso(),
            ),
        )

    def _review_detail(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        classification = None
        if row["classification_ref_id"]:
            c_row = connection.execute(
                "SELECT * FROM job_family_classifications WHERE id = ?",
                (row["classification_ref_id"],),
            ).fetchone()
            classification = row_to_family_classification(c_row) if c_row else None
        elif row["job_id"]:
            c_row = connection.execute(
                "SELECT * FROM job_family_classifications WHERE job_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (row["job_id"],),
            ).fetchone()
            classification = row_to_family_classification(c_row) if c_row else None
        tailoring = None
        if row["tailoring_ref_id"]:
            t_row = connection.execute(
                "SELECT * FROM job_tailoring_decisions WHERE id = ?",
                (row["tailoring_ref_id"],),
            ).fetchone()
            tailoring = row_to_tailoring_decision(t_row) if t_row else None
        elif row["job_id"]:
            t_row = connection.execute(
                "SELECT * FROM job_tailoring_decisions WHERE job_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (row["job_id"],),
            ).fetchone()
            tailoring = row_to_tailoring_decision(t_row) if t_row else None
        job = row_to_job(self._get_job_row(connection, row["job_id"]))
        resolutions = connection.execute(
            "SELECT * FROM review_resolutions WHERE review_id = ? ORDER BY created_at ASC",
            (row["id"],),
        ).fetchall()
        allowed_actions = _allowed_review_actions(str(row["review_type"]))
        metadata = _review_metadata(classification, tailoring)
        return {
            "review_id": row["id"],
            "job_id": row["job_id"],
            "packet_id": row["packet_id"],
            "review_type": row["review_type"],
            "status": row["status"],
            "reason": row["reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "resolved_at": row["resolved_at"],
            "job": {
                "job_id": job["job_id"],
                "company": job["company"],
                "title": job["title"],
                "selected_cv_family": job["selected_cv_family"],
            },
            "classification": classification,
            "tailoring": tailoring,
            "metadata": metadata,
            "allowed_actions": allowed_actions,
            "resolution": row_to_review_resolution(resolutions[-1]) if resolutions else None,
            "history": [row_to_review_resolution(item) for item in resolutions],
        }

    def _validate_review_resolution(
        self,
        detail: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        action = str(payload["action"])
        classification = detail.get("classification") or {}
        tailoring = detail.get("tailoring") or {}
        original_family = str(
            classification.get("selected_family")
            or tailoring.get("base_family")
            or detail["job"].get("selected_cv_family")
            or ""
        )
        resolved_family = str(payload.get("resolved_family") or original_family)
        if action == "override_family":
            resolved_family = _valid_family(payload.get("resolved_family"))
        elif action == "mark_out_of_scope":
            resolved_family = "out_of_scope"
        elif resolved_family not in FAMILY_IDS and resolved_family != "out_of_scope":
            raise ValueError("resolved family is unknown")

        original_blocks = list(
            tailoring.get("final_blocks") or tailoring.get("base_blocks") or []
        )
        if not original_blocks and original_family in FAMILY_IDS:
            registry = load_project_block_registry()
            original_blocks = list(registry["base_project_order"][original_family])
        resolved_blocks = list(original_blocks)
        regeneration_status = "not_required"
        failure_reason = None
        review_status = {
            "approve_classification": "approved",
            "approve_tailoring": "approved",
            "approve_order": "approved",
            "defer": "deferred",
            "mark_out_of_scope": "rejected",
            "reject_tailoring": "rejected",
            "use_master_unchanged": "overridden",
            "override_family": "overridden",
            "select_approved_replacement": "overridden",
        }[action]

        if action in {"override_family", "use_master_unchanged"} and resolved_family in FAMILY_IDS:
            registry = load_project_block_registry()
            resolved_blocks = list(registry["base_project_order"][resolved_family])
            regeneration_status = "queued"
        if action == "reject_tailoring":
            if original_family not in FAMILY_IDS:
                raise ValueError("cannot reject tailoring without a valid base family")
            registry = load_project_block_registry()
            resolved_family = original_family
            resolved_blocks = list(registry["base_project_order"][original_family])
            regeneration_status = "queued"
        if action == "select_approved_replacement":
            if resolved_family not in FAMILY_IDS:
                raise ValueError("resolved family is required for replacement selection")
            registry = load_project_block_registry()
            removed = str(payload.get("removed_block") or "").strip()
            inserted = str(payload.get("inserted_block") or "").strip()
            if not removed or not inserted:
                raise ValueError("removed_block and inserted_block are required")
            try:
                validate_replacement_pair(resolved_family, removed, inserted, registry)
            except ProjectBlockRegistryError as error:
                raise ValueError(str(error)) from error
            base_blocks = list(registry["base_project_order"][resolved_family])
            if removed not in base_blocks:
                raise ValueError("removed block is not in the resolved family master")
            resolved_blocks = [block for block in base_blocks if block != removed] + [inserted]
            if len(resolved_blocks) != len(set(resolved_blocks)):
                raise ValueError("resolved project blocks contain a duplicate")
            regeneration_status = "queued"
        if action in {"approve_tailoring", "approve_order"} and tailoring:
            resolved_blocks = list(tailoring.get("final_blocks") or [])
            if not resolved_blocks:
                raise ValueError("tailoring decision does not contain final blocks")
        if action == "approve_classification" and not classification:
            raise ValueError("classification decision is unavailable")

        return {
            "action": action,
            "original_family": original_family,
            "resolved_family": resolved_family,
            "original_blocks": original_blocks,
            "resolved_blocks": resolved_blocks,
            "review_status": review_status,
            "regeneration_status": regeneration_status,
            "failure_reason": failure_reason,
            "classifier_version": classification.get("classifier_version")
            or tailoring.get("classifier_version"),
            "registry_version": tailoring.get("registry_version"),
            "policy_version": tailoring.get("policy_version"),
            "eligible_for_calibration": action
            in {"approve_classification", "override_family", "mark_out_of_scope"},
        }


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["id"],
        "source_url": row["source_url"],
        "normalized_url": row["normalized_url"],
        "owner_id": row["owner_id"],
        "page_title": row["page_title"],
        "raw_visible_text": row["raw_visible_text"],
        "source_site": row["source_site"],
        "source_provenance": row["source_provenance"],
        "capture_evidence": json.loads(row["capture_evidence_json"])
        if row["capture_evidence_json"]
        else {},
        "detected_site": row["detected_site"],
        "extraction_candidates": json.loads(row["extraction_candidates_json"])
        if row["extraction_candidates_json"]
        else None,
        "duplicate_key": row["duplicate_key"],
        "duplicate_warning": row["duplicate_warning"],
        "jd_text": row["jd_text"],
        "jd_quality_score": row["jd_quality_score"],
        "jd_quality_band": row["jd_quality_band"],
        "jd_quality": json.loads(row["jd_quality_json"]) if row["jd_quality_json"] else None,
        "structured_jd": json.loads(row["structured_jd_json"])
        if row["structured_jd_json"]
        else None,
        "company": row["company"],
        "title": row["title"],
        "location": row["location"],
        "extraction_method": row["extraction_method"],
        "extraction_warnings": json.loads(row["extraction_warnings_json"])
        if row["extraction_warnings_json"]
        else [],
        "failure_reason": row["failure_reason"],
        "manual_review_reason": row["manual_review_reason"],
        "field_provenance": json.loads(row["field_provenance_json"])
        if row["field_provenance_json"]
        else None,
        "raw_text_length": row["raw_text_length"],
        "clean_text_length": row["clean_text_length"],
        "jd_text_fingerprint": row["jd_text_fingerprint"],
        "role_family": row["role_family"],
        "selected_cv_family": row["selected_cv_family"],
        "secondary_cv_family": row["secondary_cv_family"],
        "cv_family_confidence": row["cv_family_confidence"],
        "cv_family_selection": json.loads(row["cv_family_selection_json"])
        if row["cv_family_selection_json"]
        else None,
        "family_classification": json.loads(row["family_classification_json"])
        if row["family_classification_json"]
        else None,
        "family_classifier_version": row["family_classifier_version"],
        "family_classification_decision": row["family_classification_decision"],
        "family_classification_requires_review": bool(
            row["family_classification_requires_review"]
        ),
        "scoring_status": row["scoring_status"],
        "scoring_version": row["scoring_version"],
        "scoring_mode": row["scoring_mode"],
        "llm_call_status": row["llm_call_status"],
        "llm_failure_reason": row["llm_failure_reason"],
        "llm_model": row["llm_model"],
        "llm_prompt_version": row["llm_prompt_version"],
        "score_breakdown": json.loads(row["score_breakdown_json"])
        if row["score_breakdown_json"]
        else None,
        "section_scores": json.loads(row["section_scores_json"])
        if row["section_scores_json"]
        else None,
        "strengths": json.loads(row["strengths_json"]) if row["strengths_json"] else [],
        "gaps": json.loads(row["gaps_json"]) if row["gaps_json"] else [],
        "hard_blockers": json.loads(row["hard_blockers_json"])
        if row["hard_blockers_json"]
        else [],
        "overall_score": row["overall_score"],
        "recommendation": row["recommendation"],
        "reason": row["reason"],
        "intake_status": row["intake_status"],
        "packet_status": row["packet_status"],
        "manual_priority": row["manual_priority"],
        "starred": bool(row["starred"]),
        "priority_updated_at": row["priority_updated_at"],
        "promotion_reason": row["promotion_reason"],
        "current_packet_id": row["current_packet_id"],
        "current_analysis_run_id": row["current_analysis_run_id"],
        "placeholder_artifact_path": row["placeholder_artifact_path"],
        "archived_at": row["archived_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_q2_task(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["id"],
        "job_id": row["job_id"],
        "status": row["status"],
        "priority": row["priority"],
        "promotion_reason": row["promotion_reason"],
        "score_at_promotion": row["score_at_promotion"],
        "manual_override": bool(row["manual_override"]),
        "attempt_count": row["attempt_count"],
        "lease_owner": row["lease_owner"],
        "lease_expires_at": row["lease_expires_at"],
        "failure_reason": row["failure_reason"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
    }


def row_to_packet(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "packet_id": row["id"], "job_id": row["job_id"],
        "q2_task_id": row["q2_task_id"], "status": row["status"],
        "selected_cv_family": row["selected_cv_family"],
        "artifact_directory": row["artifact_directory"],
        "pdf_path": row["pdf_path"], "tex_path": row["tex_path"],
        "selected_cv_path": row["selected_cv_path"],
        "tailoring_decision_path": row["tailoring_decision_path"],
        "manifest_path": row["manifest_path"],
        "page_count": row["page_count"], "failure_stage": row["failure_stage"],
        "failure_reason": row["failure_reason"],
        "generation_kind": row["generation_kind"],
        "source_packet_id": row["source_packet_id"],
        "review_id": row["review_id"],
        "review_resolution_id": row["review_resolution_id"],
        "idempotency_key": row["idempotency_key"],
        "generation_reason": row["generation_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"], "completed_at": row["completed_at"],
    }


def row_to_analysis_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "analysis_run_id": row["id"],
        "job_id": row["job_id"],
        "owner_id": row["owner_id"],
        "trigger": row["trigger"],
        "source_content_version": row["source_content_version"],
        "status": row["status"],
        "candidate_fit": json.loads(row["candidate_fit_json"])
        if row["candidate_fit_json"]
        else None,
        "family_classification": json.loads(row["family_classification_json"])
        if row["family_classification_json"]
        else None,
        "semantic_requirements": json.loads(row["semantic_requirements_json"])
        if row["semantic_requirements_json"]
        else None,
        "fused_requirements": json.loads(row["fused_requirements_json"])
        if row["fused_requirements_json"]
        else None,
        "project_portfolio": json.loads(row["project_portfolio_json"])
        if row["project_portfolio_json"]
        else None,
        "packet_id": row["packet_id"],
        "failure_code": row["failure_code"],
        "failure_reason": row["failure_reason"],
        "policy_versions": json.loads(row["policy_versions_json"])
        if row["policy_versions_json"]
        else {},
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
    }


def row_to_score(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"], "analysis_run_id": row["analysis_run_id"],
        "scoring_version": row["scoring_version"],
        "structured_jd": json.loads(row["structured_jd_json"]),
        "family_selection": json.loads(row["family_selection_json"]),
        "section_scores": json.loads(row["section_scores_json"]),
        "score_breakdown": json.loads(row["score_breakdown_json"]),
        "strengths": json.loads(row["strengths_json"]), "gaps": json.loads(row["gaps_json"]),
        "hard_blockers": json.loads(row["hard_blockers_json"]), "created_at": row["created_at"],
    }


def row_to_semantic_assessment(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"], "analysis_run_id": row["analysis_run_id"],
        "scoring_version": row["scoring_version"],
        "scoring_mode": row["scoring_mode"], "llm_call_status": row["llm_call_status"],
        "llm_failure_reason": row["llm_failure_reason"], "model": row["model_name"],
        "prompt_version": row["prompt_version"],
        "semantic_schema_version": row["semantic_schema_version"],
        "deterministic_family": json.loads(row["deterministic_family_json"]),
        "llm_family": json.loads(row["llm_family_json"]) if row["llm_family_json"] else None,
        "family_decision": json.loads(row["family_decision_json"])
        if row["family_decision_json"]
        else None,
        "semantic_assessment": json.loads(row["semantic_assessment_json"])
        if row["semantic_assessment_json"]
        else None,
        "created_at": row["created_at"],
    }


def row_to_family_classification(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "analysis_run_id": row["analysis_run_id"],
        "classifier_version": row["classifier_version"],
        "config_version": row["config_version"],
        "family_scores": json.loads(row["family_scores_json"]),
        "selected_family": row["selected_family"],
        "secondary_family": row["secondary_family"],
        "confidence": row["confidence"],
        "decision": row["decision"],
        "requires_review": bool(row["requires_review"]),
        "rule_evidence": json.loads(row["rule_evidence_json"]),
        "semantic_evidence": json.loads(row["semantic_evidence_json"]),
        "deterministic_scores": json.loads(row["deterministic_scores_json"]),
        "semantic_scores": json.loads(row["semantic_scores_json"])
        if row["semantic_scores_json"]
        else None,
        "created_at": row["created_at"],
    }


def row_to_tailoring_decision(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "packet_id": row["packet_id"],
        "base_family": row["base_family"],
        "classification_decision": row["classification_decision"],
        "base_blocks": json.loads(row["base_blocks_json"]),
        "final_blocks": json.loads(row["final_blocks_json"]),
        "removed_block": row["removed_block"],
        "inserted_block": row["inserted_block"],
        "scores": json.loads(row["scores_json"]),
        "replacement_gain": row["replacement_gain"],
        "evidence": json.loads(row["evidence_json"]),
        "requires_review": bool(row["requires_review"]),
        "tailoring_status": row["tailoring_status"],
        "fallback_reason": row["fallback_reason"],
        "policy_version": row["policy_version"],
        "registry_version": row["registry_version"],
        "classifier_version": row["classifier_version"],
        "decision": json.loads(row["decision_json"]),
        "created_at": row["created_at"],
    }


def row_to_review_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "review_id": row["id"],
        "job_id": row["job_id"],
        "packet_id": row["packet_id"],
        "review_type": row["review_type"],
        "status": row["status"],
        "reason": row["reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "resolved_at": row["resolved_at"],
        "job": {
            "title": row["job_title"],
            "company": row["job_company"],
            "selected_cv_family": row["job_selected_family"],
        },
        "classification": {
            "selected_family": row["classification_family"],
            "decision": row["classification_decision"],
            "requires_review": bool(row["classification_requires_review"])
            if row["classification_decision"] is not None
            else None,
        },
        "tailoring": {
            "status": row["tailoring_status"],
            "requires_review": bool(row["tailoring_requires_review"])
            if row["tailoring_status"] is not None
            else None,
        },
    }


def row_to_review_resolution(row: sqlite3.Row) -> dict[str, Any]:
    resolution = json.loads(row["resolution_json"])
    retry_allowed = (
        row["regeneration_status"] == "failed"
        and (row["failure_code"] in REGENERATION_RETRYABLE_ERRORS)
        and int(row["attempt_count"] or 0) < REGENERATION_MAX_ATTEMPTS
    )
    return {
        "resolution_id": row["id"],
        "review_id": row["review_id"],
        "job_id": row["job_id"],
        "packet_id": row["packet_id"],
        "action": row["action"],
        "reviewer_id": row["reviewer_id"],
        "review_note": row["review_note"],
        "original_family": row["original_family"],
        "resolved_family": row["resolved_family"],
        "original_blocks": json.loads(row["original_blocks_json"]),
        "resolved_blocks": json.loads(row["resolved_blocks_json"]),
        "regeneration_status": row["regeneration_status"],
        "regeneration_packet_id": row["regeneration_packet_id"],
        "regeneration_job_id": row["regeneration_job_id"],
        "source_packet_id": row["source_packet_id"],
        "queued_at": row["queued_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "failed_at": row["failed_at"],
        "attempt_count": row["attempt_count"],
        "failure_code": row["failure_code"],
        "failure_reason": row["failure_reason"],
        "retry_allowed": retry_allowed,
        "created_at": row["created_at"],
        "details": resolution,
    }


def row_to_regeneration_job(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "regeneration_job_id": row["id"],
        "review_resolution_id": row["review_resolution_id"],
        "review_id": row["review_id"],
        "owner_id": row["owner_id"],
        "job_id": row["job_id"],
        "source_packet_id": row["source_packet_id"],
        "generated_packet_id": row["generated_packet_id"],
        "idempotency_key": row["idempotency_key"],
        "status": row["status"],
        "attempt_count": row["attempt_count"],
        "lease_owner": row["lease_owner"],
        "lease_expires_at": row["lease_expires_at"],
        "queued_at": row["queued_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "failed_at": row["failed_at"],
        "failure_code": row["failure_code"],
        "failure_reason": row["failure_reason"],
        "policy_version": row["policy_version"],
        "registry_version": row["registry_version"],
        "classifier_version": row["classifier_version"],
        "packet_generator_version": row["packet_generator_version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_worker_instance(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "instance_id": row["instance_id"],
        "worker_type": row["worker_type"],
        "process_id": row["process_id"],
        "hostname": row["hostname"],
        "state": row["state"],
        "started_at": row["started_at"],
        "last_heartbeat_at": row["last_heartbeat_at"],
        "stopped_at": row["stopped_at"],
        "current_job_id": row["current_job_id"],
        "last_claimed_job_id": row["last_claimed_job_id"],
        "last_completed_job_id": row["last_completed_job_id"],
        "last_success_at": row["last_success_at"],
        "last_failure_at": row["last_failure_at"],
        "last_failure_code": row["last_failure_code"],
        "last_failure_reason": row["last_failure_reason"],
        "processed_count": row["processed_count"],
        "failure_count": row["failure_count"],
        "consecutive_failure_count": row["consecutive_failure_count"],
        "polling_interval_seconds": row["polling_interval_seconds"],
        "version": row["version"],
        "updated_at": row["updated_at"],
    }


def row_to_worker_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "event_id": row["id"],
        "worker_type": row["worker_type"],
        "instance_id": row["instance_id"],
        "event_type": row["event_type"],
        "state": row["state"],
        "job_id": row["job_id"],
        "safe_code": row["safe_code"],
        "message": row["message"],
        "metadata": json.loads(row["metadata_json"]),
        "created_at": row["created_at"],
    }


def row_to_block_score(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"], "block_id": row["block_id"], "block_type": row["block_type"],
        "block_name": row["block_name"], "technical_match": row["technical_match"],
        "keyword_match": row["keyword_match"], "responsibility_match": row["responsibility_match"],
        "evidence_strength": row["evidence_strength"], "seniority_fit": row["seniority_fit"],
        "recency": row["recency"], "impressiveness": row["impressiveness"],
        "domain_match": row["domain_match"], "risk_of_overclaim": row["risk_of_overclaim"],
        "aggregate_score": row["aggregate_score"], "reason": row["reason"],
        "matched_requirements": json.loads(row["matched_requirements_json"]),
        "unmatched_requirements": json.loads(row["unmatched_requirements_json"]),
        "scoring_version": row["scoring_version"], "created_at": row["created_at"],
    }


def row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "event_type": row["event_type"],
        "from_status": row["from_status"],
        "to_status": row["to_status"],
        "message": row["message"],
        "metadata": json.loads(row["metadata_json"]),
        "created_at": row["created_at"],
    }


def summarize_job(job: dict[str, Any], *, duplicate: bool = False) -> dict[str, Any]:
    return {
        "job_id": job["id"],
        "intake_status": job["intake_status"],
        "packet_status": job["packet_status"],
        "duplicate": duplicate,
        "job": job,
    }


def _source_provenance(evidence: dict[str, Any]) -> str:
    value = str(evidence.get("source_provenance") or evidence.get("provenance") or "").strip()
    if value in {"manual", "extension", "demo", "imported", "test"}:
        return value
    source = str(evidence.get("source") or "").strip()
    if source in {"manual", "extension", "demo", "imported", "test"}:
        return source
    return "manual"


def ensure_no_unexpected_tables(repository: Repository, expected: Iterable[str]) -> None:
    with repository.connect() as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    names = {row["name"] for row in rows}
    unexpected = names.difference(expected)
    if unexpected:
        raise AssertionError(f"unexpected tables: {sorted(unexpected)}")


def _classification_needs_review(classification: dict[str, Any]) -> bool:
    return bool(classification.get("requires_review")) or str(
        classification.get("decision")
    ) in REVIEWABLE_CLASSIFICATION_DECISIONS


def _tailoring_needs_review(decision: dict[str, Any]) -> bool:
    return bool(decision.get("requires_review")) or str(
        decision.get("tailoring_status")
    ) in REVIEWABLE_TAILORING_STATUSES


def _valid_family(value: Any) -> str:
    family = str(value or "").strip()
    if family not in FAMILY_IDS:
        raise ValueError("resolved family is unknown")
    return family


def _regeneration_idempotency_key(
    *,
    resolution_id: str,
    resolved_family: str,
    resolved_blocks: list[str],
    registry_version: str | None,
    policy_version: str | None,
) -> str:
    payload = {
        "resolution_id": resolution_id,
        "resolved_family": resolved_family,
        "resolved_blocks": resolved_blocks,
        "registry_version": registry_version,
        "policy_version": policy_version,
        "packet_generator_version": "phase-h-review-regeneration-v1",
    }
    import hashlib

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe_failure_reason(reason: str) -> str:
    text = str(reason).replace("\n", " ").strip()
    text = re.sub(r"(/[^\s]+)+", "[path]", text)
    return text[:300] or "Review regeneration failed."


def _existing_schema_version(connection: sqlite3.Connection) -> int | None:
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_meta'"
    ).fetchone()
    if table is None:
        return None
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return None
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        raise RuntimeError("database schema version is invalid") from None


def _queue_counts(
    connection: sqlite3.Connection,
    table: str,
    status_column: str,
    *,
    queued: str,
    processing: tuple[str, ...],
    failed: tuple[str, ...],
    queued_at_column: str,
    stale_statuses: tuple[str, ...],
    stale_column: str,
    now: str,
) -> dict[str, Any]:
    processing_marks = ",".join("?" for _ in processing)
    failed_marks = ",".join("?" for _ in failed)
    stale_marks = ",".join("?" for _ in stale_statuses)
    queued_row = connection.execute(
        f"SELECT count(*) AS count, min({queued_at_column}) AS oldest FROM {table} "
        f"WHERE {status_column} = ?",
        (queued,),
    ).fetchone()
    processing_row = connection.execute(
        f"SELECT count(*) AS count FROM {table} WHERE {status_column} IN ({processing_marks})",
        processing,
    ).fetchone()
    failed_row = connection.execute(
        f"SELECT count(*) AS count FROM {table} WHERE {status_column} IN ({failed_marks})",
        failed,
    ).fetchone()
    stale_row = connection.execute(
        f"SELECT count(*) AS count FROM {table} WHERE {status_column} IN ({stale_marks}) "
        f"AND {stale_column} < datetime(?, '-15 minutes')",
        (*stale_statuses, now),
    ).fetchone()
    return {
        "queued_count": int(queued_row["count"]),
        "processing_count": int(processing_row["count"]),
        "failed_count": int(failed_row["count"]),
        "retryable_count": int(failed_row["count"]),
        "oldest_queued_at": queued_row["oldest"],
        "stale_processing_count": int(stale_row["count"]),
    }


def _q2_queue_counts(connection: sqlite3.Connection, *, now: str) -> dict[str, Any]:
    queued = connection.execute(
        "SELECT count(*) AS count, min(created_at) AS oldest FROM q2_tasks "
        "WHERE status = 'queued'"
    ).fetchone()
    processing = connection.execute(
        "SELECT count(*) AS count FROM q2_tasks WHERE status IN ('claimed', 'running')"
    ).fetchone()
    failed = connection.execute(
        "SELECT count(*) AS count FROM q2_tasks WHERE status = 'failed'"
    ).fetchone()
    stale = connection.execute(
        "SELECT count(*) AS count FROM q2_tasks WHERE status IN ('claimed', 'running') "
        "AND lease_expires_at IS NOT NULL AND lease_expires_at < ?",
        (now,),
    ).fetchone()
    exhausted = connection.execute(
        "SELECT count(*) AS count FROM q2_tasks WHERE status = 'failed' AND attempt_count >= 3"
    ).fetchone()
    return {
        "queued_count": int(queued["count"]),
        "processing_count": int(processing["count"]),
        "failed_count": int(failed["count"]),
        "retryable_count": max(0, int(failed["count"]) - int(exhausted["count"])),
        "oldest_queued_at": queued["oldest"],
        "stale_processing_count": int(stale["count"]),
        "max_attempt_exhausted_count": int(exhausted["count"]),
    }


def _regeneration_queue_counts(
    connection: sqlite3.Connection, *, now: str
) -> dict[str, Any]:
    queued = connection.execute(
        "SELECT count(*) AS count, min(queued_at) AS oldest FROM review_regeneration_jobs "
        "WHERE status = 'queued'"
    ).fetchone()
    processing = connection.execute(
        "SELECT count(*) AS count FROM review_regeneration_jobs WHERE status = 'processing'"
    ).fetchone()
    complete = connection.execute(
        "SELECT count(*) AS count FROM review_regeneration_jobs WHERE status = 'complete'"
    ).fetchone()
    failed = connection.execute(
        "SELECT count(*) AS count FROM review_regeneration_jobs WHERE status = 'failed'"
    ).fetchone()
    retryable = connection.execute(
        "SELECT count(*) AS count FROM review_regeneration_jobs WHERE status = 'failed' "
        "AND failure_code IN ('temporary_artifact_write_failure', 'worker_interrupted') "
        "AND attempt_count < ?",
        (REGENERATION_MAX_ATTEMPTS,),
    ).fetchone()
    stale = connection.execute(
        "SELECT count(*) AS count FROM review_regeneration_jobs WHERE status = 'processing' "
        "AND lease_expires_at IS NOT NULL AND lease_expires_at < ?",
        (now,),
    ).fetchone()
    exhausted = connection.execute(
        "SELECT count(*) AS count FROM review_regeneration_jobs WHERE status = 'failed' "
        "AND attempt_count >= ?",
        (REGENERATION_MAX_ATTEMPTS,),
    ).fetchone()
    return {
        "queued_count": int(queued["count"]),
        "processing_count": int(processing["count"]),
        "complete_count": int(complete["count"]),
        "failed_count": int(failed["count"]),
        "retryable_count": int(retryable["count"]),
        "oldest_queued_at": queued["oldest"],
        "stale_processing_count": int(stale["count"]),
        "max_attempt_exhausted_count": int(exhausted["count"]),
    }


def _allowed_review_actions(review_type: str) -> list[str]:
    if review_type == "classification":
        return ["approve_classification", "override_family", "mark_out_of_scope", "defer"]
    if review_type == "tailoring":
        return [
            "approve_tailoring",
            "use_master_unchanged",
            "select_approved_replacement",
            "approve_order",
            "reject_tailoring",
            "defer",
        ]
    return sorted(REVIEW_ACTIONS)


def _review_metadata(
    classification: dict[str, Any] | None,
    tailoring: dict[str, Any] | None,
) -> dict[str, Any]:
    registry = load_project_block_registry()
    blocks = {
        str(block["block_id"]): {
            "block_id": block["block_id"],
            "project_id": block["project_id"],
            "display_name": block["display_name"],
            "family": block["family"],
            "source_master": block["source_master"],
            "heading": block["heading"],
            "subtitle": block["subtitle"],
            "preview": " ".join(str(item) for item in block.get("bullets", [])[:2]),
        }
        for block in registry["blocks"]
    }
    replacement_options: list[dict[str, Any]] = []
    for base_family, family_rules in registry["compatibility"].items():
        for removed_block, rules in family_rules.items():
            for rule in rules:
                inserted_block = str(rule["insert_block_id"])
                replacement_options.append({
                    "base_family": base_family,
                    "removed_block": removed_block,
                    "inserted_block": inserted_block,
                    "removed_name": blocks.get(removed_block, {}).get(
                        "display_name", removed_block
                    ),
                    "inserted_name": blocks.get(inserted_block, {}).get(
                        "display_name", inserted_block
                    ),
                    "requires_review": bool(rule.get("requires_review")),
                    "reason": rule.get("reason"),
                })
    return {
        "families": {
            "digital_ic": "Digital IC / RTL",
            "verification": "Verification / SoC Verification",
            "software": "Software Engineering",
            "ml": "Machine Learning Engineering",
        },
        "base_project_order": registry["base_project_order"],
        "project_blocks": blocks,
        "replacement_options": replacement_options,
    }
