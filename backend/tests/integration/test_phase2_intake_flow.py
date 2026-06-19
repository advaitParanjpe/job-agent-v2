from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository
from jobagent_v2.workers import DummyQ1Worker


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "intake_pages"
PAYLOAD_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "intake_payloads"


def payload(name: str, *, title: str, url: str) -> dict[str, str]:
    return {
        "url": url,
        "page_title": title,
        "visible_text": (FIXTURE_DIR / name).read_text(encoding="utf-8"),
        "source_site": "example.com",
        "captured_at": "2026-06-19T12:00:00Z",
    }


def evidence_payload(name: str) -> dict[str, object]:
    payload = json.loads((PAYLOAD_FIXTURE_DIR / name).read_text(encoding="utf-8"))
    payload["url"] = payload["source_url"]
    payload["captured_at"] = "2026-06-19T12:00:00Z"
    return payload


def test_real_intake_worker_good_fixture_reaches_intake_complete(
    service: JobService,
    repository: Repository,
) -> None:
    created = service.create_job(
        payload(
            "clean_company.txt",
            title="Senior RTL Engineer - Acme Silicon",
            url="https://acme.example/jobs/clean?utm_source=newsletter",
        )
    )

    processed = DummyQ1Worker(repository).process_next()
    events = service.get_events(str(created["job_id"]))["events"]

    assert processed is not None
    assert processed["intake_status"] == "scored"
    assert processed["jd_quality_band"] == "good"
    assert processed["company"] == "Acme Silicon"
    assert processed["title"] == "Senior RTL Engineer"
    assert processed["location"] == "Austin, TX"
    assert [event["event_type"] for event in events][-1] == "job_scored"


def test_real_failure_payloads_persist_normalized_intake_fields(
    service: JobService,
    repository: Repository,
) -> None:
    nvidia = service.create_job(evidence_payload("nvidia_workday.json"))
    queued = service.get_job(str(nvidia["job_id"]))["job"]
    assert queued["intake_status"] == "queued"
    assert queued["company"] is None

    DummyQ1Worker(repository).process_next()
    nvidia_job = service.get_job(str(nvidia["job_id"]))["job"]

    assert nvidia_job["company"] == "NVIDIA"
    assert nvidia_job["title"] == "ASIC Design Engineer"
    assert nvidia_job["location"] == "Santa Clara, CA, US"
    assert nvidia_job["field_provenance"]["company"]["raw_value"] == "2100 NVIDIA USA"
    assert "campaign_suffix_removed" in nvidia_job["field_provenance"]["title"]["normalization"]

    infineon = service.create_job(evidence_payload("infineon_structured_location.json"))
    DummyQ1Worker(repository).process_next()
    infineon_job = service.get_job(str(infineon["job_id"]))["job"]

    assert infineon_job["location"] == "San Jose, CA, US"
    assert not any(token in infineon_job["location"] for token in ("{", "}", "@type", "'"))


def test_weak_fixture_reaches_manual_review(
    service: JobService,
    repository: Repository,
) -> None:
    created = service.create_job(
        {
            "url": "https://example.com/jobs/weak",
            "page_title": "Engineer - Unknown",
            "visible_text": (
                "Engineer\n"
                "About the role\n"
                "You will help with engineering tasks and collaborate with a small team."
            ),
            "source_site": "example.com",
            "captured_at": "2026-06-19T12:00:00Z",
        }
    )

    processed = DummyQ1Worker(repository).process_next()

    assert processed is not None
    assert processed["intake_status"] == "manual_review"
    assert processed["manual_review_reason"]
    assert "qualifications_section_missing" in processed["extraction_warnings"]
    assert service.get_job(str(created["job_id"]))["job"]["intake_status"] == "manual_review"


def test_bad_fixture_reaches_failed(
    service: JobService,
    repository: Repository,
) -> None:
    created = service.create_job(
        payload(
            "too_little.txt",
            title="Unknown",
            url="https://example.com/jobs/bad",
        )
    )

    processed = DummyQ1Worker(repository).process_next()

    assert processed is not None
    assert processed["intake_status"] == "failed"
    assert processed["failure_reason"]
    assert service.get_job(str(created["job_id"]))["job"]["failure_reason"]


def test_duplicate_url_returns_existing_job_after_normalization(
    service: JobService,
) -> None:
    first = service.create_job(
        payload(
            "clean_company.txt",
            title="Senior RTL Engineer - Acme Silicon",
            url="https://acme.example/jobs/clean/?utm_source=x&gh_jid=1",
        )
    )
    second = service.create_job(
        payload(
            "clean_company.txt",
            title="Senior RTL Engineer - Acme Silicon",
            url="https://ACME.example/jobs/clean?gh_jid=1",
        )
    )

    assert second["duplicate"] is True
    assert second["job_id"] == first["job_id"]
    assert len(service.list_jobs()["jobs"]) == 1


def test_probable_duplicate_warning_is_persisted(
    service: JobService,
    repository: Repository,
) -> None:
    first = service.create_job(
        payload(
            "clean_company.txt",
            title="Senior RTL Engineer - Acme Silicon",
            url="https://acme.example/jobs/clean-1",
        )
    )
    DummyQ1Worker(repository).process_next()
    second = service.create_job(
        payload(
            "clean_company.txt",
            title="Senior RTL Engineer - Acme Silicon",
            url="https://acme.example/jobs/clean-2",
        )
    )
    processed = DummyQ1Worker(repository).process_next()

    assert first["job_id"] != second["job_id"]
    assert processed is not None
    assert processed["duplicate_warning"] is not None


def test_retry_requeues_failed_intake_without_duplicate(
    service: JobService,
    repository: Repository,
) -> None:
    created = service.create_job(
        payload("too_little.txt", title="Unknown", url="https://example.com/jobs/retry")
    )
    DummyQ1Worker(repository).process_next()

    retried = service.retry(str(created["job_id"]))["job"]

    assert retried["intake_status"] == "queued"
    assert retried["failure_reason"] is None
    assert len(service.list_jobs()["jobs"]) == 1


def test_restart_preserves_clean_jd_and_diagnostics(
    db_path: Path,
    artifact_root: Path,
) -> None:
    service = JobService(Repository(db_path), artifact_root)
    created = service.create_job(
        payload(
            "clean_company.txt",
            title="Senior RTL Engineer - Acme Silicon",
            url="https://acme.example/jobs/restart",
        )
    )
    DummyQ1Worker(Repository(db_path)).process_next()

    restarted = JobService(Repository(db_path), artifact_root)
    job = restarted.get_job(str(created["job_id"]))["job"]

    assert "SystemVerilog" in job["jd_text"]
    assert job["jd_quality_band"] == "good"
    assert job["field_provenance"]["title"]["source"] == "page_title_pattern"


def test_phase1_database_migrates_without_data_loss(
    db_path: Path,
    artifact_root: Path,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE jobs (
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
            CREATE TABLE job_events (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                message TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO schema_meta VALUES ('schema_version', '1');
            INSERT INTO jobs (
                id, source_url, normalized_url, page_title, raw_visible_text,
                source_site, company, title, role_family, overall_score,
                recommendation, reason, intake_status, packet_status,
                manual_priority, placeholder_artifact_path, archived_at,
                created_at, updated_at
            )
            VALUES (
                'old-job', 'https://example.com/old', 'https://example.com/old',
                'Old Engineer', 'Old captured text', 'example.com', 'Old Co',
                'Old Engineer', NULL, NULL, NULL, 'old reason', 'queued',
                'not_requested', 0, NULL, NULL, '2026-06-19T00:00:00Z',
                '2026-06-19T00:00:00Z'
            );
            """
        )

    service = JobService(Repository(db_path), artifact_root)
    job = service.get_job("old-job")["job"]

    assert job["job_id"] == "old-job"
    assert job["jd_quality_band"] is None
    assert job["extraction_warnings"] == []
