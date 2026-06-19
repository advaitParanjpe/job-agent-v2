from __future__ import annotations

import pytest

from jobagent_v2.schemas import ValidationError
from jobagent_v2.service import JobService
from jobagent_v2.workers import DummyQ1Worker


def test_extension_payload_schema_and_post_jobs_success_response(
    service: JobService,
    capture_payload: dict[str, str],
) -> None:
    response = service.create_job(capture_payload)

    assert response["job_id"]
    assert response["intake_status"] == "queued"
    assert response["packet_status"] == "not_requested"
    assert response["duplicate"] is False
    assert response["job"]["source_url"] == capture_payload["url"]


def test_duplicate_post_is_idempotent(
    service: JobService,
    capture_payload: dict[str, str],
) -> None:
    first = service.create_job(capture_payload)
    second = service.create_job(capture_payload)
    jobs = service.list_jobs()["jobs"]

    assert second["job_id"] == first["job_id"]
    assert second["duplicate"] is True
    assert len(jobs) == 1


def test_job_list_and_generate_response_schema(
    service: JobService,
    capture_payload: dict[str, str],
) -> None:
    created = service.create_job(capture_payload)
    listed = service.list_jobs()
    generated = service.generate_now(str(created["job_id"]))

    assert set(listed["jobs"][0]).issuperset(
        {"job_id", "company", "title", "intake_status", "packet_status", "source_url"}
    )
    assert generated["job"]["packet_status"] == "queued"


def test_post_jobs_response_includes_phase2_intake_fields(
    service: JobService,
    capture_payload: dict[str, str],
) -> None:
    response = service.create_job(capture_payload)
    job = response["job"]

    assert set(job).issuperset(
        {
            "normalized_url",
            "duplicate_key",
            "duplicate_warning",
            "jd_text",
            "jd_quality_score",
            "jd_quality_band",
            "jd_quality",
            "structured_jd",
            "location",
            "extraction_method",
            "extraction_warnings",
            "failure_reason",
            "manual_review_reason",
            "field_provenance",
            "raw_text_length",
            "clean_text_length",
            "jd_text_fingerprint",
        }
    )


def test_list_and_detail_use_canonical_completed_intake_field_names(
    service: JobService,
    repository,
) -> None:
    created = service.create_job(
        {
            "url": "https://acme.example/jobs/completed-intake",
            "page_title": "Senior RTL Engineer - Acme Silicon",
            "visible_text": (
                "Senior RTL Engineer\nAustin, TX\nResponsibilities\n"
                "Design SystemVerilog RTL and collaborate with verification engineers.\n"
                "Qualifications\nBS in Electrical Engineering and SystemVerilog experience."
            ),
            "source_site": "acme.example",
            "captured_at": "2026-06-19T12:00:00Z",
        }
    )
    DummyQ1Worker(repository).process_next()

    listed = service.list_jobs()["jobs"][0]
    detailed = service.get_job(str(created["job_id"]))["job"]

    for job in (listed, detailed):
        assert job["company"] == "Acme Silicon"
        assert job["title"] == "Senior RTL Engineer"
        assert job["location"] == "Austin, TX"
        assert job["jd_quality_band"] == "usable_with_warnings"
        assert job["role_family"] == "RTL / ASIC Design"
        assert job["selected_cv_family"] == "hardware_rtl"


def test_invalid_request_rejection(service: JobService) -> None:
    with pytest.raises(ValidationError):
        service.create_job({"url": "not enough"})


def test_phase3_score_and_block_score_response_schemas(service: JobService, repository) -> None:
    created = service.create_job(
        {
            "url": "https://example.com/contracts/rtl", "page_title": "RTL Engineer - Acme",
            "visible_text": """Responsibilities
Design SystemVerilog RTL for ASIC products and review verification results.
Qualifications
Verilog, SystemVerilog, RTL, ASIC, and Python experience are required.
""",
            "source_site": "example.com", "captured_at": "2026-06-19T12:00:00Z",
        }
    )
    DummyQ1Worker(repository).process_next()
    job_id = str(created["job_id"])
    score = service.get_score(job_id)["score"]
    blocks = service.get_block_scores(job_id)["block_scores"]

    assert score is not None
    assert set(score).issuperset(
        {"structured_jd", "family_selection", "section_scores", "score_breakdown"}
    )
    assert blocks and {
        "aggregate_score", "matched_requirements", "risk_of_overclaim"
    }.issubset(blocks[0])
    assert service.rescore(job_id)["job"]["intake_status"] == "scored"
