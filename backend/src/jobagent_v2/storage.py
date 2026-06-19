"""SQLite persistence for jobs and events."""

from __future__ import annotations

import json
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
from jobagent_v2.url_utils import normalize_url, source_site_from_url
from jobagent_v2.util import utc_now_iso


SCHEMA_VERSION = 5


class JobNotFoundError(LookupError):
    """Raised when a job ID does not exist."""


class DuplicateActivePacketError(RuntimeError):
    """Raised when a packet task is already active or ready."""


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
                    page_title TEXT NOT NULL,
                    raw_visible_text TEXT NOT NULL,
                    source_site TEXT,
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
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            self._ensure_columns(connection)

    def _ensure_columns(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA table_info(jobs)").fetchall()
        existing = {row["name"] for row in rows}
        columns = {
            "duplicate_key": "TEXT",
            "capture_evidence_json": "TEXT",
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
        }
        for name, ddl in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")

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
                    id, source_url, normalized_url, page_title, raw_visible_text,
                    source_site, capture_evidence_json, detected_site, duplicate_key,
                    company, title, role_family, overall_score,
                    recommendation, reason, intake_status, packet_status,
                    manual_priority, placeholder_artifact_path, archived_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    payload.url,
                    normalized_url,
                    payload.page_title,
                    payload.visible_text,
                    site,
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
                message="Raw job persisted and queued for dummy Q1.",
                metadata={
                    "normalized_url": normalized_url,
                    "captured_at": payload.captured_at,
                },
            )
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise JobNotFoundError(job_id)
            return row_to_job(row), False

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

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        self.get_job(job_id)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_events WHERE job_id = ? ORDER BY rowid ASC",
                (job_id,),
            ).fetchall()
        return [row_to_event(row) for row in rows]

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
                    "reason": "Queued for dummy Q2 processing.",
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
                message="Dummy Q2 worker claimed persistent task.",
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
                message="Dummy Q2 task started placeholder generation.",
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
                message="Dummy Q2 completed placeholder artifact.",
                metadata={
                    "task_id": task_id,
                    "artifact_path": artifact_path,
                    "dummy": True,
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
                    {"packet_status": "queued", "reason": "Retry queued for dummy Q2."},
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
            self._get_job_row(connection, job_id)
            connection.execute("DELETE FROM job_block_scores WHERE job_id = ?", (job_id,))
            for block in result.block_scores:
                connection.execute(
                    """INSERT INTO job_block_scores (
                    id, job_id, scoring_version, block_id, block_type, block_name,
                    technical_match, keyword_match, responsibility_match, evidence_strength,
                    seniority_fit, recency, impressiveness, domain_match, risk_of_overclaim,
                    aggregate_score, reason, matched_requirements_json, unmatched_requirements_json,
                    created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()), job_id, block["scoring_version"], block["block_id"],
                        block["block_type"], block["block_name"], block["technical_match"],
                        block["keyword_match"], block["responsibility_match"],
                        block["evidence_strength"], block["seniority_fit"], block["recency"],
                        block["impressiveness"], block["domain_match"], block["risk_of_overclaim"],
                        block["aggregate_score"], block["reason"],
                        json.dumps(block["matched_requirements"]),
                        json.dumps(block["unmatched_requirements"]), now,
                    ),
                )
            connection.execute("DELETE FROM job_scores WHERE job_id = ?", (job_id,))
            hybrid = result.score_breakdown.get("hybrid", {})
            connection.execute("DELETE FROM job_semantic_assessments WHERE job_id = ?", (job_id,))
            connection.execute(
                """INSERT INTO job_semantic_assessments (
                id, job_id, scoring_version, scoring_mode, llm_call_status,
                llm_failure_reason, model_name, prompt_version, semantic_schema_version,
                deterministic_family_json, llm_family_json, family_decision_json,
                semantic_assessment_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    job_id,
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
            connection.execute(
                """INSERT INTO job_scores (
                id, job_id, scoring_version, structured_jd_json, family_selection_json,
                section_scores_json, score_breakdown_json, strengths_json, gaps_json,
                hard_blockers_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), job_id, "phase3-deterministic-v1",
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

    def list_block_scores(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
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


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["id"],
        "source_url": row["source_url"],
        "normalized_url": row["normalized_url"],
        "page_title": row["page_title"],
        "raw_visible_text": row["raw_visible_text"],
        "source_site": row["source_site"],
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


def row_to_score(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"], "scoring_version": row["scoring_version"],
        "structured_jd": json.loads(row["structured_jd_json"]),
        "family_selection": json.loads(row["family_selection_json"]),
        "section_scores": json.loads(row["section_scores_json"]),
        "score_breakdown": json.loads(row["score_breakdown_json"]),
        "strengths": json.loads(row["strengths_json"]), "gaps": json.loads(row["gaps_json"]),
        "hard_blockers": json.loads(row["hard_blockers_json"]), "created_at": row["created_at"],
    }


def row_to_semantic_assessment(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"], "scoring_version": row["scoring_version"],
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


def ensure_no_unexpected_tables(repository: Repository, expected: Iterable[str]) -> None:
    with repository.connect() as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    names = {row["name"] for row in rows}
    unexpected = names.difference(expected)
    if unexpected:
        raise AssertionError(f"unexpected tables: {sorted(unexpected)}")
