from __future__ import annotations

import json
from pathlib import Path

from jobagent_v2.intake import run_intake


GOOD_DESCRIPTION = """
About the role
You will build reliable infrastructure for high-throughput systems.
Responsibilities
You will design services, write tests, debug production issues, and improve
observability for engineers using local tools.
Qualifications
Requirements include Python, SQL, HTTP APIs, distributed systems experience, and
strong written communication.
"""
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "intake_payloads"


def load_payload(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_json_ld_jobposting_evidence_wins() -> None:
    result = run_intake(
        page_title="Careers",
        visible_text="JavaScript shell",
        source_site="greenhouse",
        source_url="https://job-boards.greenhouse.io/acme/jobs/1",
        evidence={
            "detected_site": "greenhouse",
            "json_ld_job_postings": [
                {
                    "@type": "JobPosting",
                    "title": "GPU Performance Engineer",
                    "hiringOrganization": {"name": "Acme AI"},
                    "jobLocation": {
                        "address": {
                            "addressLocality": "San Francisco",
                            "addressRegion": "CA",
                            "addressCountry": "US",
                        }
                    },
                    "description": GOOD_DESCRIPTION,
                }
            ],
        },
    )

    assert result.title.value == "GPU Performance Engineer"
    assert result.title.source == "json_ld_jobposting"
    assert result.company.value == "Acme AI"
    assert result.location.value == "San Francisco, CA, US"
    assert result.extraction_method == "json_ld_description"
    assert result.quality.band in {"good", "usable_with_warnings"}


def test_meta_and_heading_candidates_are_used_when_json_ld_absent() -> None:
    result = run_intake(
        page_title="Jobs",
        visible_text=GOOD_DESCRIPTION,
        source_site="company.example",
        source_url="https://company.example/careers/software-engineer",
        evidence={
            "detected_site": "generic",
            "meta": {
                "og:title": "Backend Engineer - Example Systems",
                "og:site_name": "Example Systems",
            },
            "headings": ["Backend Engineer"],
        },
    )

    assert result.company.value == "Example Systems"
    assert result.company.source == "meta_tag"
    assert result.title.value == "Backend Engineer"


def test_ats_dom_candidates_override_generic_page_title() -> None:
    result = run_intake(
        page_title="Open Roles | Careers",
        visible_text=GOOD_DESCRIPTION,
        source_site="myworkdayjobs.com",
        source_url="https://example.myworkdayjobs.com/site/job/123",
        evidence={
            "detected_site": "workday",
            "likely_title_elements": ["Systems Integration Engineer"],
            "likely_company_elements": ["Example Robotics"],
            "likely_location_elements": ["Location: Boston, MA"],
            "likely_description_elements": [GOOD_DESCRIPTION],
        },
    )

    assert result.title.value == "Systems Integration Engineer"
    assert result.title.source == "dom_title_candidate"
    assert result.company.value == "Example Robotics"
    assert result.location.value == "Boston, MA"


def test_conflicting_evidence_keeps_alternatives() -> None:
    result = run_intake(
        page_title="Wrong Title - Wrong Co",
        visible_text=GOOD_DESCRIPTION,
        source_site="lever",
        source_url="https://jobs.lever.co/acme/abc",
        evidence={
            "detected_site": "lever",
            "json_ld_job_postings": [
                {
                    "@type": "JobPosting",
                    "title": "Compiler Engineer",
                    "hiringOrganization": "Acme Compilers",
                    "jobLocation": "Austin, TX",
                    "description": GOOD_DESCRIPTION,
                }
            ],
            "likely_title_elements": ["Wrong Engineer"],
        },
    )

    assert result.title.value == "Compiler Engineer"
    assert result.title.alternatives is not None
    assert any(item["value"] == "Wrong Engineer" for item in result.title.alternatives)


def test_missing_fields_stay_unknown_with_warnings() -> None:
    result = run_intake(
        page_title="Careers",
        visible_text=GOOD_DESCRIPTION,
        source_site=None,
        source_url="https://example.com/careers",
        evidence={},
    )

    assert result.company.value is None
    assert result.title.value is None
    assert "company_not_confident" in result.warnings
    assert "title_not_confident" in result.warnings


def test_jd_fallback_does_not_over_truncate_long_visible_text() -> None:
    tail = "\n".join(
        f"Responsibility detail line {index} with engineering work." for index in range(40)
    )
    visible = f"Navigation\nJobs\n{GOOD_DESCRIPTION}\n{tail}\nPrivacy Policy"

    result = run_intake(
        page_title="Backend Engineer - Example Systems",
        visible_text=visible,
        source_site="example.com",
        source_url="https://example.com/jobs/1",
        evidence={},
    )

    assert "Responsibility detail line 39" in result.jd_text
    assert "Privacy Policy" not in result.jd_text


def test_nvidia_company_and_campaign_title_are_normalized_with_provenance() -> None:
    payload = load_payload("nvidia_workday.json")
    result = run_intake(**payload)

    assert result.company.value == "NVIDIA"
    assert result.company.raw_value == "2100 NVIDIA USA"
    assert result.company.normalization == [
        "leading_street_number_removed",
        "country_suffix_removed",
    ]
    assert result.title.value == "ASIC Design Engineer"
    assert result.title.raw_value == "ASIC Design Engineer - New College Grad 2026"
    assert "campaign_suffix_removed" in (result.title.normalization or [])
    assert all(not item["value"].startswith("2100 ") for item in result.candidates["company"])


def test_infineon_structured_locations_do_not_stringify_json_objects() -> None:
    payload = load_payload("infineon_structured_location.json")
    result = run_intake(**payload)

    assert result.location.value == "San Jose, CA, US"
    assert result.location.value.count("US") == 1
    assert not any(token in result.location.value for token in ("{", "}", "@type", "'"))
    assert result.location.source == "json_ld_jobposting"
