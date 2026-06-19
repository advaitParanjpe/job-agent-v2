from __future__ import annotations

from pathlib import Path

from jobagent_v2.intake import run_intake


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "intake_pages"


def read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_jd_parser_extracts_useful_content_from_clean_fixture() -> None:
    result = run_intake(
        page_title="Senior RTL Engineer - Acme Silicon",
        visible_text=read_fixture("clean_company.txt"),
        source_site="acme.example",
        source_url="https://acme.example/jobs/1",
    )

    assert "SystemVerilog" in result.jd_text
    assert result.quality.band == "good"
    assert result.company.value == "Acme Silicon"
    assert result.title.value == "Senior RTL Engineer"
    assert result.location.value == "Austin, TX"


def test_jd_parser_does_not_over_truncate_noisy_fixture() -> None:
    result = run_intake(
        page_title="Systems Engineer - Workday Example",
        visible_text=read_fixture("workday_noisy.txt"),
        source_site="workday.example",
        source_url="https://workday.example/job/2",
    )

    assert "translate requirements" in result.jd_text
    assert "Privacy Policy" not in result.jd_text
    assert result.quality.clean_text_length > 350
    assert result.quality.band in {"good", "usable_with_warnings"}


def test_quality_diagnostics_classify_weak_input() -> None:
    result = run_intake(
        page_title="Engineer - Unknown",
        visible_text=(
            "Engineer\n"
            "About the role\n"
            "You will help with engineering tasks and collaborate with a small team."
        ),
        source_site=None,
        source_url="https://example.com/jobs/weak",
    )

    assert result.quality.band == "manual_review"
    assert "qualifications_section_missing" in result.warnings


def test_quality_diagnostics_classify_bad_input() -> None:
    result = run_intake(
        page_title="Unknown",
        visible_text=read_fixture("too_little.txt"),
        source_site=None,
        source_url="https://example.com/jobs/bad",
    )

    assert result.quality.band == "failed"
    assert result.failure_reason is not None


def test_company_title_location_extraction_variants() -> None:
    greenhouse = run_intake(
        page_title="Embedded Firmware Engineer - Greenhouse Demo Corp",
        visible_text=read_fixture("greenhouse_like.txt"),
        source_site="greenhouse.example",
        source_url="https://greenhouse.example/jobs/1",
    )
    lever = run_intake(
        page_title="Software Engineer, Infrastructure at Nova Compute",
        visible_text=read_fixture("lever_like.txt"),
        source_site="lever.example",
        source_url="https://lever.example/jobs/2",
    )

    assert greenhouse.company.value == "Greenhouse Demo Corp"
    assert greenhouse.title.value == "Embedded Firmware Engineer"
    assert greenhouse.location.value == "San Jose, CA"
    assert lever.company.value == "Nova Compute"
    assert lever.title.value == "Software Engineer, Infrastructure"
    assert lever.location.value == "London, UK"


def test_missing_company_or_location_is_marked_without_invention() -> None:
    missing_company = run_intake(
        page_title="Principal Verification Engineer",
        visible_text=read_fixture("missing_company.txt"),
        source_site=None,
        source_url="https://example.com/jobs/missing-company",
    )
    missing_location = run_intake(
        page_title="Backend Developer - Acme Systems",
        visible_text=read_fixture("missing_location.txt"),
        source_site="acme.example",
        source_url="https://example.com/jobs/missing-location",
    )

    assert missing_company.company.value is None
    assert "company_not_confident" in missing_company.warnings
    assert missing_location.location.value is None
    assert "location_not_found" in missing_location.warnings

