from __future__ import annotations

from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository
from jobagent_v2.workers import DummyQ1Worker


def scoring_payload(url: str, title: str, text: str) -> dict[str, str]:
    return {"url": url, "page_title": title, "visible_text": text, "source_site": "example.com",
            "captured_at": "2026-06-19T12:00:00Z"}


RTL_TEXT = """RTL Design Engineer
Location: Austin, TX
Responsibilities
Design SystemVerilog RTL for ASIC semiconductor products and collaborate with verification.
Qualifications
Experience with Verilog, SystemVerilog, RTL, ASIC flows, and Python.
"""


def test_q1_persists_score_diagnostics_and_restart(
    service: JobService, repository: Repository
) -> None:
    created = service.create_job(
        scoring_payload("https://example.com/rtl", "RTL Design Engineer - Acme", RTL_TEXT)
    )
    processed = DummyQ1Worker(repository).process_next()

    assert processed is not None and processed["intake_status"] == "scored"
    assert processed["overall_score"] is not None
    assert processed["selected_cv_family"] == "digital_ic"
    assert service.get_score(str(created["job_id"]))["score"] is not None
    assert len(service.get_block_scores(str(created["job_id"]))["block_scores"]) == 2
    assert service.get_job(str(created["job_id"]))["job"]["strengths"]
    classification = repository.get_family_classification(str(created["job_id"]))
    assert classification is not None
    assert classification["selected_family"] == "digital_ic"
    assert classification["family_scores"]["digital_ic"] > classification["family_scores"]["ml"]
    assert processed["family_classification"]["classifier_version"]
    stored = service.get_job(str(created["job_id"]))["job"]
    assert processed["overall_score"] == stored["overall_score"]


def test_dashboard_list_sorts_by_score_and_rescore_replaces_blocks(
    service: JobService, repository: Repository
) -> None:
    lower = service.create_job(scoring_payload(
        "https://example.com/software", "Backend Engineer - Acme",
        """Backend Engineer
Responsibilities
Build backend Python services, maintain SQL data models, review production incidents,
improve API reliability, and collaborate with product and infrastructure teams.
Qualifications
Python and SQL experience, knowledge of distributed systems, Linux, Docker, and clear
technical communication are required for this software engineering role.
""",
    ))
    higher = service.create_job(
        scoring_payload("https://example.com/rtl-high", "RTL Engineer - Acme", RTL_TEXT)
    )
    DummyQ1Worker(repository).process_next()
    DummyQ1Worker(repository).process_next()

    listed = service.list_jobs()["jobs"]
    assert listed[0]["overall_score"] >= listed[1]["overall_score"]
    rescored = service.rescore(str(higher["job_id"]))["job"]
    assert rescored["intake_status"] == "scored"
    assert len(service.get_block_scores(str(higher["job_id"]))["block_scores"]) == 2
    assert service.get_job(str(lower["job_id"]))["job"]["scoring_status"] == "complete"


def test_low_confidence_family_review_flag_persists(
    service: JobService, repository: Repository
) -> None:
    created = service.create_job(scoring_payload(
        "https://example.com/product-manager",
        "Product Manager - Acme",
        """Product Manager
Location: Remote
Responsibilities
Own roadmap planning, stakeholder communication, sales enablement, and launch planning.
Qualifications
Experience with business strategy, pricing, and executive presentations.
""",
    ))

    processed = DummyQ1Worker(repository).process_next()

    assert processed is not None and processed["intake_status"] == "scored"
    assert processed["family_classification"]["decision"] == "low_confidence"
    assert processed["family_classification_requires_review"] is True
    classification = repository.get_family_classification(str(created["job_id"]))
    assert classification is not None
    assert classification["requires_review"] is True
    assert classification["decision"] == "low_confidence"
    assert processed["overall_score"] is not None
