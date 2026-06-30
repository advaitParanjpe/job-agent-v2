from __future__ import annotations

import pytest

from jobagent_v2.api import API_DOCUMENTATION
from jobagent_v2.project_blocks import load_project_block_registry
from jobagent_v2.service import JobService
from jobagent_v2.storage import JobNotFoundError, Repository
from jobagent_v2.workers import DummyQ1Worker


def _payload(url: str, title: str, text: str, *, owner_id: str = "local") -> dict[str, object]:
    return {
        "url": url,
        "page_title": title,
        "visible_text": text,
        "source_site": "example.com",
        "captured_at": "2026-06-30T12:00:00Z",
        "evidence": {"owner_id": owner_id},
    }


def _low_confidence_text() -> str:
    return """Product Manager
Responsibilities
Own roadmap planning, stakeholder communication, launch planning, and sales enablement.
Qualifications
Experience with pricing, executive presentations, and market research.
"""


def _tailoring_decision(status: str = "review_required") -> dict[str, object]:
    registry = load_project_block_registry()
    base = list(registry["base_project_order"]["digital_ic"])
    return {
        "base_family": "digital_ic",
        "classification_decision": "close_match",
        "base_blocks": base,
        "final_order": base,
        "removed_block": None,
        "inserted_block": None,
        "base_block_scores": [],
        "candidate_blocks": [],
        "replacement_gain": 0.0,
        "job_evidence": [],
        "requires_review": True,
        "tailoring_status": status,
        "fallback_reason": None,
        "policy_version": "phase-d-one-block-tailoring-v1",
        "registry_version": registry["schema_version"],
        "classifier_version": "phase-b-family-classifier-v1",
        "reason": "Test review-required tailoring decision.",
    }


def test_low_confidence_classification_creates_pending_review(
    service: JobService,
    repository: Repository,
) -> None:
    created = service.create_job(
        _payload(
            "https://example.com/review-low-confidence",
            "Product Manager",
            _low_confidence_text(),
        )
    )
    processed = DummyQ1Worker(repository).process_next()

    assert processed is not None
    assert processed["family_classification"]["decision"] == "low_confidence"
    reviews = service.list_reviews()["reviews"]
    assert len(reviews) == 1
    assert reviews[0]["job_id"] == created["job_id"]
    assert reviews[0]["review_type"] == "classification"
    assert reviews[0]["status"] == "pending"


def test_duplicate_pending_review_is_not_created(
    service: JobService,
    repository: Repository,
) -> None:
    service.create_job(
        _payload("https://example.com/review-duplicate", "Product Manager", _low_confidence_text())
    )
    DummyQ1Worker(repository).process_next()
    job = service.list_jobs()["jobs"][0]
    DummyQ1Worker(repository).rescore(str(job["job_id"]))

    reviews = service.list_reviews()["reviews"]
    assert len(reviews) == 1
    assert reviews[0]["status"] == "pending"


def test_clear_unchanged_master_does_not_create_default_review(
    service: JobService,
    repository: Repository,
    capture_payload: dict[str, str],
) -> None:
    payload = dict(capture_payload)
    payload["url"] = "https://example.com/review-clear-rtl"
    service.create_job(payload)
    processed = DummyQ1Worker(repository).process_next()

    assert processed is not None
    assert processed["family_classification"]["decision"] == "clear_match"
    assert service.list_reviews()["reviews"] == []


def test_clear_classification_can_be_manually_reviewed(
    service: JobService,
    repository: Repository,
    capture_payload: dict[str, str],
) -> None:
    payload = dict(capture_payload)
    payload["url"] = "https://example.com/review-clear-manual"
    created = service.create_job(payload)
    processed = DummyQ1Worker(repository).process_next()

    assert processed is not None
    assert processed["family_classification"]["decision"] == "clear_match"
    review = service.create_review(
        str(created["job_id"]),
        {"review_type": "classification", "reason": "wrong_family_reported"},
    )["review"]

    assert review["status"] == "pending"
    assert review["reason"] == "wrong_family_reported"
    assert review["classification"]["decision"] == "clear_match"


def test_review_owner_is_enforced(
    service: JobService,
    repository: Repository,
) -> None:
    service.create_job(
        _payload(
            "https://example.com/review-owner",
            "Product Manager",
            _low_confidence_text(),
            owner_id="alice",
        )
    )
    DummyQ1Worker(repository).process_next()
    alice_reviews = service.list_reviews(owner_id="alice")["reviews"]

    assert len(alice_reviews) == 1
    assert service.list_reviews(owner_id="bob")["reviews"] == []
    with pytest.raises(JobNotFoundError):
        service.get_review(alice_reviews[0]["review_id"], owner_id="bob")


def test_override_family_resolution_preserves_original_decision_and_exports_feedback(
    service: JobService,
    repository: Repository,
) -> None:
    service.create_job(
        _payload("https://example.com/review-override", "Product Manager", _low_confidence_text())
    )
    DummyQ1Worker(repository).process_next()
    review = service.list_reviews()["reviews"][0]
    original = repository.get_family_classification(str(review["job_id"]))

    resolved = service.resolve_review(
        review["review_id"],
        {
            "action": "override_family",
            "resolved_family": "software",
            "reviewer_id": "tester",
            "review_note": "Software platform role after review.",
        },
    )["review"]
    feedback = service.export_review_feedback()["feedback"]

    assert resolved["status"] == "overridden"
    assert resolved["resolution"]["regeneration_status"] == "queued"
    assert repository.get_family_classification(str(review["job_id"])) == original
    assert feedback[0]["review_action"] == "override_family"
    assert feedback[0]["reviewed_family"] == "software"
    assert feedback[0]["eligible_for_calibration"] is True


def test_unknown_family_resolution_is_rejected(
    service: JobService,
    repository: Repository,
) -> None:
    service.create_job(
        _payload("https://example.com/review-bad-family", "Product Manager", _low_confidence_text())
    )
    DummyQ1Worker(repository).process_next()
    review = service.list_reviews()["reviews"][0]

    with pytest.raises(ValueError, match="resolved family is unknown"):
        service.resolve_review(
            review["review_id"],
            {
                "action": "override_family",
                "resolved_family": "analog_ic",
                "reviewer_id": "tester",
            },
        )


def test_tailoring_review_rejects_incompatible_replacement(
    service: JobService,
    repository: Repository,
) -> None:
    created = service.create_job(
        _payload(
            "https://example.com/review-tailoring",
            "RTL ML Accelerator",
            _low_confidence_text(),
        )
    )
    repository.save_tailoring_decision(str(created["job_id"]), None, _tailoring_decision())
    review = service.list_reviews(review_type="tailoring")["reviews"][0]

    with pytest.raises(ValueError, match="not eligible|not explicitly approved"):
        service.resolve_review(
            review["review_id"],
            {
                "action": "select_approved_replacement",
                "resolved_family": "digital_ic",
                "removed_block": "tinynpu_digital_ic_v1",
                "inserted_block": "jobagent_software_v1",
                "reviewer_id": "tester",
            },
        )


def test_tailoring_review_accepts_compatible_replacement(
    service: JobService,
    repository: Repository,
) -> None:
    created = service.create_job(
        _payload(
            "https://example.com/review-tailoring-valid",
            "RTL ML Accelerator",
            _low_confidence_text(),
        )
    )
    repository.save_tailoring_decision(str(created["job_id"]), None, _tailoring_decision())
    review = service.list_reviews(review_type="tailoring")["reviews"][0]

    resolved = service.resolve_review(
        review["review_id"],
        {
            "action": "select_approved_replacement",
            "resolved_family": "digital_ic",
            "removed_block": "sparrow_cluster_digital_ic_v1",
            "inserted_block": "sparrowml_ml_v1",
            "reviewer_id": "tester",
        },
    )["review"]

    assert resolved["status"] == "overridden"
    assert resolved["resolution"]["regeneration_status"] == "queued"
    assert resolved["resolution"]["resolved_blocks"].count("sparrowml_ml_v1") == 1


def test_review_detail_includes_registered_block_metadata(
    service: JobService,
    repository: Repository,
) -> None:
    created = service.create_job(
        _payload(
            "https://example.com/review-tailoring-metadata",
            "RTL ML Accelerator",
            _low_confidence_text(),
        )
    )
    repository.save_tailoring_decision(str(created["job_id"]), None, _tailoring_decision())
    summary = service.list_reviews(review_type="tailoring")["reviews"][0]

    review = service.get_review(summary["review_id"])["review"]
    metadata = review["metadata"]

    assert metadata["families"]["digital_ic"] == "Digital IC / RTL"
    assert metadata["project_blocks"]["sparrowml_ml_v1"]["display_name"] == "SparrowML"
    assert metadata["project_blocks"]["sparrowml_ml_v1"]["preview"]
    assert {
        "base_family": "digital_ic",
        "removed_block": "sparrow_cluster_digital_ic_v1",
        "inserted_block": "sparrowml_ml_v1",
        "removed_name": "Sparrow-Cluster",
        "inserted_name": "SparrowML",
        "requires_review": True,
        "reason": (
            "Approved ML-family SparrowML block may be considered for hybrid "
            "Digital IC/ML roles."
        ),
    } in metadata["replacement_options"]
    assert {
        "base_family": "verification",
        "removed_block": "agentic_rtl_security_verification_v1",
        "inserted_block": "sparrow_v_verification_v1",
        "removed_name": "Agentic RTL Security",
        "inserted_name": "Sparrow-V Verification",
        "requires_review": False,
        "reason": (
            "Approved verification-family Sparrow-V block can substitute for another "
            "verification project block."
        ),
    } in metadata["replacement_options"]
    assert metadata["replacement_options"]


def test_review_api_docs_include_endpoints() -> None:
    assert "GET /api/reviews" in API_DOCUMENTATION
    assert "POST /api/reviews/{review_id}/resolve" in API_DOCUMENTATION
    assert "POST /api/jobs/{job_id}/reviews" in API_DOCUMENTATION
