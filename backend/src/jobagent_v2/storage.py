"""SQLite persistence for Phase 1 jobs and events."""

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


SCHEMA_VERSION = 1


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
                    company TEXT,
                    title TEXT,
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
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

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
            title = payload.page_title or "Untitled job"
            connection.execute(
                """
                INSERT INTO jobs (
                    id, source_url, normalized_url, page_title, raw_visible_text,
                    source_site, company, title, role_family, overall_score,
                    recommendation, reason, intake_status, packet_status,
                    manual_priority, placeholder_artifact_path, archived_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    payload.url,
                    normalized_url,
                    payload.page_title,
                    payload.visible_text,
                    site,
                    title,
                    title,
                    None,
                    None,
                    None,
                    "Queued for dummy Phase 1 intake processing.",
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
        query += " ORDER BY manual_priority DESC, created_at ASC"
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

    def queue_packet(self, job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = self._get_job_row(connection, job_id)
            if row["packet_status"] in {"queued", "generating", "ready"}:
                raise DuplicateActivePacketError(job_id)
            from_status = row["packet_status"]
            validate_packet_transition(from_status, "queued")
            self._update_job(
                connection,
                job_id,
                {
                    "packet_status": "queued",
                    "reason": "Queued for dummy Phase 1 packet processing.",
                },
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="packet_queued",
                from_status=from_status,
                to_status="queued",
                message="Generate now queued dummy Q2 work.",
                metadata={},
            )
            updated = self._get_job_row(connection, job_id)
        return row_to_job(updated)

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
                    {"intake_status": "queued", "reason": "Retry queued for dummy Q1."},
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

    def next_job_with_packet_status(self, status: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE packet_status = ? AND archived_at IS NULL
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (status,),
            ).fetchone()
        return row_to_job(row) if row is not None else None

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
        "company": row["company"],
        "title": row["title"],
        "role_family": row["role_family"],
        "overall_score": row["overall_score"],
        "recommendation": row["recommendation"],
        "reason": row["reason"],
        "intake_status": row["intake_status"],
        "packet_status": row["packet_status"],
        "manual_priority": row["manual_priority"],
        "placeholder_artifact_path": row["placeholder_artifact_path"],
        "archived_at": row["archived_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
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
