from __future__ import annotations

from pathlib import Path

from jobagent_v2.requirements import (
    extract_requirements,
    fuse_requirements,
    validate_semantic_requirement_response,
)
from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository
from jobagent_v2.workers import Queue1Worker


def _payload(url: str, *, owner_id: str = "local") -> dict[str, object]:
    return {
        "url": url,
        "page_title": "Machine Learning Runtime Engineer",
        "visible_text": (
            "Responsibilities deploy efficient inference on constrained devices. "
            "Optimize models for heterogeneous compute targets. Partner with "
            "accelerator architecture teams. Requirements Python PyTorch inference."
        ),
        "source_site": "example.com",
        "captured_at": "2026-07-01T12:00:00Z",
        "evidence": {"owner_id": owner_id, "source_provenance": "manual"},
    }


def test_archived_duplicate_returns_structured_archive_outcome(tmp_path: Path) -> None:
    service = JobService(Repository(tmp_path / "jobs.sqlite3"), tmp_path / "artifacts")
    created = service.create_job(_payload("https://example.com/jobs/123?utm_source=x"))
    job_id = str(created["job_id"])
    service.delete_or_archive(job_id)

    duplicate = service.create_job(_payload("https://example.com/jobs/123"))

    assert duplicate["duplicate"] is True
    assert duplicate["outcome"] == "existing_archived"
    assert duplicate["job_state"] == "archived"
    assert duplicate["active_run"] is True
    assert "restore_and_rescore" in duplicate["allowed_actions"]
    assert duplicate["message"] == "This job is in your archive."


def test_completed_duplicate_is_not_reported_as_queued(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "jobs.sqlite3")
    service = JobService(repo, tmp_path / "artifacts")
    created = service.create_job(_payload("https://example.com/jobs/complete"))
    job_id = str(created["job_id"])
    Queue1Worker(repo).process_next()

    duplicate = service.create_job(_payload("https://example.com/jobs/complete"))

    assert duplicate["outcome"] == "existing_complete"
    assert duplicate["active_run"] is False
    assert duplicate["message"] == "This job already exists."


def test_restore_preserves_analysis_runs_and_does_not_enqueue(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "jobs.sqlite3")
    service = JobService(repo, tmp_path / "artifacts")
    created = service.create_job(_payload("https://example.com/jobs/restore"))
    job_id = str(created["job_id"])
    Queue1Worker(repo).process_next()
    before = service.list_analyses(job_id)["analyses"]
    service.delete_or_archive(job_id)

    restored = service.restore(job_id)

    assert restored["job"]["archived_at"] is None
    assert service.list_analyses(job_id)["analyses"] == before
    assert repo.get_active_analysis_run(job_id) is None


def test_restore_and_rescore_reuses_active_run(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "jobs.sqlite3")
    service = JobService(repo, tmp_path / "artifacts")
    created = service.create_job(_payload("https://example.com/jobs/restore-rescore"))
    job_id = str(created["job_id"])
    Queue1Worker(repo).process_next()
    service.delete_or_archive(job_id)

    first = repo.start_analysis_run(
        job_id, owner_id="local", trigger="restore_and_rescore", restore=True
    )
    second = service.restore_and_rescore(job_id)

    assert first[1] is True
    assert second["created"] is False
    assert second["analysis_run"]["analysis_run_id"] == first[0]["analysis_run_id"]


def test_rescore_preserves_previous_analysis_rows(tmp_path: Path) -> None:
    service = JobService(Repository(tmp_path / "jobs.sqlite3"), tmp_path / "artifacts")
    created = service.create_job(_payload("https://example.com/jobs/history"))
    job_id = str(created["job_id"])

    Queue1Worker(service.repository).process_next()
    service.rescore(job_id)
    analyses = service.list_analyses(job_id)["analyses"]

    assert len([run for run in analyses if run["status"] == "complete"]) == 2
    assert {run["trigger"] for run in analyses} >= {"manual_rescore"}


def test_semantic_requirement_validation_rejects_ungrounded_and_unknown_caps() -> None:
    job_text = "Deploy efficient inference on constrained devices."
    accepted, rejected = validate_semantic_requirement_response(
        {
            "requirements": [
                {
                    "requirement_text": "On-device inference",
                    "normalized_capabilities": ["on_device_inference", "edge_ai"],
                    "importance": 0.8,
                    "specificity": 0.75,
                    "required_or_preferred": "responsibility",
                    "evidence_quote": "Deploy efficient inference on constrained devices",
                    "concise_reason": "Grounded.",
                },
                {
                    "requirement_text": "RTL design",
                    "normalized_capabilities": ["made_up_capability"],
                    "importance": 0.8,
                    "specificity": 0.75,
                    "evidence_quote": "Deploy efficient inference on constrained devices",
                },
                {
                    "requirement_text": "NPU",
                    "normalized_capabilities": ["npu"],
                    "importance": 0.8,
                    "specificity": 0.75,
                    "evidence_quote": "NPU",
                },
            ]
        },
        job_text=job_text,
    )

    assert len(accepted) == 1
    assert {item["reason"] for item in rejected} == {"invalid_capability", "ungrounded_evidence"}


def test_semantic_fusion_discounts_semantic_only_and_boosts_agreement() -> None:
    deterministic = [
        {
            "requirement_id": "req_001",
            "text": "On-device inference execution",
            "normalized_capabilities": ["on_device_inference"],
            "importance": 0.7,
            "specificity": 0.8,
            "differentiation_value": 0.7,
            "required_or_preferred": "required",
            "evidence_quote": "on-device inference",
        }
    ]
    semantic = [
        {
            "requirement_id": "sem_001",
            "text": "Deploy on device",
            "normalized_capabilities": ["on_device_inference"],
            "importance": 0.82,
            "specificity": 0.78,
            "confidence": 0.6,
            "required_or_preferred": "responsibility",
            "evidence_quote": "on-device inference",
            "sources": ["semantic"],
            "semantic_only": True,
            "differentiation_value": 0.6,
        }
    ]

    fused = fuse_requirements(deterministic, semantic)

    assert fused[0]["sources"] == ["deterministic", "semantic"]
    assert fused[0]["semantic_only"] is False
    assert fused[0]["confidence"] > 0.82


def test_subjective_language_fake_semantic_adds_grounded_capabilities() -> None:
    def fake_provider(_prompt):
        return {
            "requirements": [
                {
                    "requirement_text": "Hardware-aware model deployment",
                    "normalized_capabilities": [
                        "hardware_acceleration",
                        "performance_optimization",
                    ],
                    "importance": 0.77,
                    "specificity": 0.7,
                    "required_or_preferred": "responsibility",
                    "evidence_quote": "Optimize models for heterogeneous compute targets",
                    "concise_reason": "Grounded heterogeneous compute requirement.",
                }
            ]
        }

    analysis = extract_requirements(
        {
            "title": "ML Runtime Engineer",
            "jd_text": "Optimize models for heterogeneous compute targets.",
            "structured_jd": {
                "responsibilities": ["Optimize models for heterogeneous compute targets"]
            },
        },
        semantic_provider=fake_provider,
        semantic_enabled=True,
    )

    assert analysis["semantic_status"] == "live_success"
    assert "hardware_acceleration" in analysis["role_dimensions"]
