from __future__ import annotations

from pathlib import Path

from jobagent_v2.hybrid_scoring import score_hybrid_job
from jobagent_v2.llm_client import LLMConfig, SemanticLLMClient
from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository


def _payload(
    url: str, *, provenance: str = "manual", owner_id: str = "local"
) -> dict[str, object]:
    return {
        "url": url,
        "page_title": "Verification Infrastructure Engineer",
        "visible_text": (
            "Responsibilities\nDevelop UVM regressions and Python dashboards."
            "\nQualifications\nUVM Python."
        ),
        "source_site": "example.com",
        "captured_at": "2026-06-30T12:00:00Z",
        "evidence": {"owner_id": owner_id, "source_provenance": provenance},
    }


def test_demo_cleanup_removes_only_explicit_demo_jobs(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "jobs.sqlite3")
    service = JobService(repo, tmp_path / "artifacts")
    demo = service.create_job(_payload("https://example.com/demo", provenance="demo"))["job"]
    manual = service.create_job(
        _payload("https://example.com/manual", provenance="manual")
    )["job"]
    extension = service.create_job(
        _payload("https://example.com/ext", provenance="extension")
    )["job"]

    preview = service.demo_cleanup_preview()["preview"]
    assert preview["job_count"] == 1

    removed = service.clear_demo_jobs()["removed"]
    remaining = service.list_jobs()["jobs"]

    assert removed["job_count"] == 1
    assert {job["job_id"] for job in remaining} == {manual["job_id"], extension["job_id"]}
    assert all(job["source_provenance"] != "demo" for job in remaining)
    assert repo.demo_cleanup_preview()["job_count"] == 0


def test_legacy_demo_seed_urls_are_marked_without_title_inference(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "jobs.sqlite3")
    service = JobService(repo, tmp_path / "artifacts")
    service.create_job({
        "url": "https://example.test/demo/verification",
        "page_title": "Design Verification Engineer",
        "visible_text": "Responsibilities\nBuild UVM regressions.",
        "source_site": "example.test",
        "captured_at": "2026-06-30T12:00:00Z",
        "evidence": {"owner_id": "local"},
    })
    service.create_job({
        "url": "https://example.com/not-demo",
        "page_title": "Design Verification Engineer",
        "visible_text": "Responsibilities\nBuild UVM regressions.",
        "source_site": "example.com",
        "captured_at": "2026-06-30T12:00:00Z",
        "evidence": {"owner_id": "local"},
    })

    repo = Repository(tmp_path / "jobs.sqlite3")
    jobs = repo.list_jobs()

    assert {job["source_provenance"] for job in jobs} == {"demo", "manual"}
    assert repo.demo_cleanup_preview()["job_count"] == 1


def test_delete_archives_real_jobs_but_hard_deletes_demo_jobs(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "jobs.sqlite3")
    service = JobService(repo, tmp_path / "artifacts")
    demo = service.create_job(
        _payload("https://example.com/delete-demo", provenance="demo")
    )["job"]
    manual = service.create_job(
        _payload("https://example.com/delete-manual", provenance="manual")
    )["job"]

    demo_result = service.delete_or_archive(str(demo["job_id"]))["job"]
    manual_result = service.delete_or_archive(str(manual["job_id"]))["job"]

    assert demo_result["deleted"] is True
    assert manual_result["archived"] is True
    assert service.list_jobs()["jobs"] == []
    archived = service.list_jobs(include_archived=True)["jobs"]
    assert [job["job_id"] for job in archived] == [manual["job_id"]]


def test_semantic_status_distinguishes_disabled_missing_timeout_and_invalid() -> None:
    disabled = score_hybrid_job(
        _job(),
        SemanticLLMClient(LLMConfig(False, None, "fake", 1, 0)),
    ).score_breakdown["hybrid"]
    assert disabled["semantic_status"] == "disabled"

    missing = score_hybrid_job(
        _job(),
        SemanticLLMClient(LLMConfig(True, None, "fake", 1, 0)),
    ).score_breakdown["hybrid"]
    assert missing["semantic_status"] == "not_configured"

    def timeout(*_args):
        raise TimeoutError("request timed out")

    timed_out = score_hybrid_job(
        _job(),
        SemanticLLMClient(LLMConfig(True, "key", "fake", 1, 0), timeout),
    ).score_breakdown["hybrid"]
    assert timed_out["semantic_status"] == "timed_out"

    invalid = score_hybrid_job(
        _job(),
        SemanticLLMClient(LLMConfig(True, "key", "fake", 1, 0), lambda *_: {"bad": True}),
    ).score_breakdown["hybrid"]
    assert invalid["semantic_status"] == "response_invalid"


def _job() -> dict[str, str]:
    return {
        "title": "Verification Engineer",
        "company": "Acme",
        "location": "Austin, TX",
        "jd_text": (
            "Responsibilities\nDevelop UVM regressions and scoreboards."
            "\nQualifications\nUVM Python."
        ),
    }
