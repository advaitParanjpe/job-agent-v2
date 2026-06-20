from __future__ import annotations

from jobagent_v2.promotion import PromotionConfig, PromotionScheduler
from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository
from jobagent_v2.workers import DummyQ2Worker
from jobagent_v2.workers import DummyQ1Worker


def _scored_job(service: JobService, repository: Repository, score: int) -> dict[str, object]:
    created = service.create_job(
        {
            "url": f"https://example.com/jobs/{score}-{len(service.list_jobs()['jobs'])}",
            "page_title": "RTL Engineer - Acme",
            "visible_text": "Responsibilities\nRTL SystemVerilog ASIC design.\n"
            "Qualifications\nVerilog SystemVerilog Python.",
            "source_site": "example.com",
            "captured_at": "2026-06-20T12:00:00Z",
        }
    )
    job_id = str(created["job_id"])
    with repository.connect() as connection:
        repository._update_job(
            connection,
            job_id,
            {
                "intake_status": "scored",
                "overall_score": score,
                "hard_blockers_json": "[]",
            },
        )
    return service.get_job(job_id)["job"]


def test_scheduler_orders_priority_and_respects_capacity(
    service: JobService, repository: Repository
) -> None:
    normal_high = _scored_job(service, repository, 95)
    normal_low = _scored_job(service, repository, 60)
    starred_low = _scored_job(service, repository, 50)
    service.set_star(str(starred_low["id"]), True)
    config = PromotionConfig(q2_capacity=2, auto_packet_budget=10)

    result = PromotionScheduler(repository, config).run_once()

    assert [task["job_id"] for task in result["promoted"]] == [
        str(starred_low["id"]),
        str(normal_high["id"]),
    ]
    assert repository.get_q2_task(str(normal_low["id"])) is None
    assert PromotionScheduler(repository, config).run_once()["promoted"] == []


def test_generate_now_is_idempotent_and_bypasses_threshold(
    service: JobService, repository: Repository
) -> None:
    job = _scored_job(service, repository, 40)

    first = service.generate_now(str(job["id"]))
    second = service.generate_now(str(job["id"]))

    assert first["created"] is True
    assert second["created"] is False
    assert first["task"]["task_id"] == second["task"]["task_id"]
    assert first["task"]["manual_override"] is True


def test_hard_blocker_prevents_manual_and_automatic_promotion(
    service: JobService, repository: Repository
) -> None:
    job = _scored_job(service, repository, 96)
    with repository.connect() as connection:
        repository._update_job(
            connection, str(job["id"]), {"hard_blockers_json": '["clearance_required"]'}
        )

    assert PromotionScheduler(repository).run_once()["promoted"] == []
    try:
        service.generate_now(str(job["id"]))
    except ValueError as error:
        assert "hard blockers" in str(error)
    else:
        raise AssertionError("manual promotion should reject a hard blocker")


def test_q2_task_survives_restart_and_dummy_worker_completes(
    db_path, artifact_root, service: JobService, repository: Repository
) -> None:
    created = service.create_job(
        {
            "url": "https://example.com/jobs/real-q2",
            "page_title": "RTL Engineer - Acme",
            "visible_text": "Responsibilities\nDesign SystemVerilog RTL ASIC blocks.\n"
            "Qualifications\nVerilog SystemVerilog Python RTL ASIC.",
            "source_site": "example.com",
            "captured_at": "2026-06-20T12:00:00Z",
        }
    )
    job = DummyQ1Worker(repository).process_next()
    assert job is not None and job["id"] == created["job_id"]
    PromotionScheduler(repository, PromotionConfig(q2_capacity=1)).run_once()

    restarted = Repository(db_path)
    task = restarted.get_q2_task(str(job["id"]))
    assert task is not None and task["status"] == "queued"
    processed = DummyQ2Worker(restarted, artifact_root).process_next()
    assert processed is not None and processed["packet_status"] == "ready"


def test_stale_task_is_requeued_or_failed_by_retry_limit(
    service: JobService, repository: Repository
) -> None:
    job = _scored_job(service, repository, 90)
    service.generate_now(str(job["id"]))
    task = repository.claim_next_q2_task(
        owner="test", concurrency=1, lease_expires_at="2000-01-01T00:00:00+00:00"
    )
    assert task is not None

    recovered = repository.recover_stale_q2_tasks(
        now="2001-01-01T00:00:00+00:00", retry_limit=3
    )
    assert recovered == 1
    assert repository.get_q2_task(str(job["id"]))["status"] == "queued"
