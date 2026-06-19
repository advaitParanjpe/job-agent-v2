from __future__ import annotations

import pytest

from jobagent_v2.schemas import ValidationError
from jobagent_v2.service import JobService


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


def test_invalid_request_rejection(service: JobService) -> None:
    with pytest.raises(ValidationError):
        service.create_job({"url": "not enough"})

