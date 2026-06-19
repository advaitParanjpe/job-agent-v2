from __future__ import annotations

import pytest

from jobagent_v2.scoring import (
    ScoringConfigurationError,
    load_cv_families,
    overall_score,
    score_job,
    select_cv_family,
    structure_jd,
    validate_truth_bank,
)


def job(title: str, text: str) -> dict[str, object]:
    return {
        "title": title,
        "company": "Acme",
        "location": "Austin, TX",
        "jd_text": text,
    }


def test_structured_jd_and_family_selection_for_rtl() -> None:
    structured = structure_jd(
        job(
            "RTL Design Engineer",
            "Responsibilities\nSystemVerilog RTL ASIC\nQualifications\nVerilog",
        )
    )
    selection = select_cv_family(structured, load_cv_families())

    assert structured["role_family_candidates"] == ["RTL / ASIC Design"]
    assert selection["primary_family"] == "hardware_rtl"
    assert selection["confidence"] in {"medium", "high"}


def test_ambiguous_family_selection_records_secondary_family() -> None:
    structured = structure_jd(job("GPU Firmware Engineer", "firmware gpu cuda c++"))
    selection = select_cv_family(structured, load_cv_families())

    assert selection["primary_family"] in {"cpu_gpu_architecture", "embedded_firmware"}
    assert selection["secondary_family"] in {"cpu_gpu_architecture", "embedded_firmware"}
    assert selection["secondary_family"] != selection["primary_family"]


def test_invalid_truth_bank_is_visible_failure() -> None:
    with pytest.raises(ScoringConfigurationError):
        validate_truth_bank(
            {"family_id": "software", "version": "1", "blocks": []},
            expected_family="software",
        )


def test_score_is_clamped_and_hard_blocker_overrides_apply() -> None:
    result = score_job(job(
        "RTL Engineer",
        "Responsibilities\nSystemVerilog RTL ASIC semiconductor.\nQualifications\n"
        "Verilog. US citizen security clearance required.",
    ))

    assert 0 <= result.overall_score <= 100
    assert result.recommendation in {"Consider", "Low priority"}
    assert result.hard_blockers == [
        "US citizenship requirement",
        "Security clearance requirement",
    ]
    assert all(0 <= block["aggregate_score"] <= 100 for block in result.block_scores)


def test_section_and_overall_aggregation_are_stable() -> None:
    source = job(
        "Backend Engineer",
        "Responsibilities\nPython backend SQL cloud.\nQualifications\nPython SQL",
    )
    first = score_job(source)
    second = score_job(source)

    assert first.overall_score == second.overall_score
    assert first.section_scores == second.section_scores
    assert first.score_breakdown["formula_version"] == "phase3-deterministic-v1"
