from __future__ import annotations

import json

import pytest

from jobagent_v2.scoring import (
    ScoringConfigurationError,
    load_cv_families,
    load_truth_bank,
    preview_truth_banks,
    validate_truth_bank,
)
from jobagent_v2.truth_banks import (
    REGISTERED_CONTENT_CLASS,
    STARTER_CONTENT_CLASS,
    TRUTH_BANK_SCHEMA_VERSION,
    TruthBankValidationError,
    list_truth_bank_previews,
    validate_truth_bank as validate_registered_truth_bank,
)


def registered_bank() -> dict[str, object]:
    return {
        "family_id": "hardware_rtl",
        "version": "2026.06",
        "schema_version": TRUTH_BANK_SCHEMA_VERSION,
        "content_class": REGISTERED_CONTENT_CLASS,
        "header": {
            "name": "Reviewed Profile",
            "contact": "reviewed-profile@example.test",
        },
        "education": ["Reviewed University, B.S. Electrical Engineering"],
        "skill_groups": [{"name": "RTL", "skills": ["rtl", "systemverilog"]}],
        "blocks": [
            {
                "id": "rtl_block",
                "type": "experience",
                "name": "Reviewed RTL Block",
                "canonical_text": "Reviewed canonical RTL implementation statement.",
                "bullets": ["Reviewed canonical RTL implementation statement."],
                "technologies": ["rtl", "systemverilog"],
                "domains": ["semiconductor"],
                "metrics": [],
                "provenance": "reviewed fixture source",
                "is_required": True,
            },
            {
                "id": "project_block",
                "type": "project",
                "name": "Reviewed Project Block",
                "canonical_text": "Reviewed canonical project statement.",
                "bullets": ["Reviewed canonical project statement."],
                "technologies": ["rtl"],
                "domains": ["semiconductor"],
                "metrics": [],
                "provenance": "reviewed fixture source",
                "is_optional": True,
            },
        ],
    }


def test_registered_truth_bank_schema_accepts_reviewed_fixture() -> None:
    validate_registered_truth_bank(registered_bank(), expected_family="hardware_rtl")


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda bank: bank.update({"family_id": ""}), "family_id"),
        (lambda bank: bank["blocks"].append({**bank["blocks"][0]}), "duplicate block ID"),
        (lambda bank: bank["blocks"][0].update({"type": "education"}), "unsupported block"),
        (lambda bank: bank["blocks"][0].pop("provenance"), "provenance"),
        (lambda bank: bank["blocks"][0].update({"canonical_text": ""}), "canonical_text"),
        (lambda bank: bank["blocks"][0].update({"bullets": []}), "canonical bullets"),
        (lambda bank: bank.update({"header": {}}), "name"),
        (lambda bank: bank.update({"education": []}), "education"),
    ],
)
def test_registered_truth_bank_rejects_critical_schema_errors(mutator, message) -> None:
    bank = registered_bank()
    mutator(bank)

    with pytest.raises(TruthBankValidationError, match=message):
        validate_registered_truth_bank(bank, expected_family="hardware_rtl")


def test_registered_truth_bank_rejects_placeholder_content() -> None:
    bank = registered_bank()
    bank["header"]["name"] = "Candidate"

    with pytest.raises(TruthBankValidationError, match="placeholder"):
        validate_registered_truth_bank(bank, expected_family="hardware_rtl")


def test_starter_fixture_requires_explicit_allowance() -> None:
    bank = registered_bank()
    bank["content_class"] = STARTER_CONTENT_CLASS
    bank["header"]["name"] = "Candidate"

    with pytest.raises(TruthBankValidationError, match="starter fixture"):
        validate_registered_truth_bank(bank, expected_family="hardware_rtl")

    validate_registered_truth_bank(bank, expected_family="hardware_rtl", allow_starter=True)


def test_existing_scoring_loader_allows_explicit_starter_fixture_data() -> None:
    family = next(item for item in load_cv_families() if item["id"] == "digital_ic")
    bank = load_truth_bank(family)

    assert bank["content_class"] == STARTER_CONTENT_CLASS
    validate_truth_bank(bank, expected_family="digital_ic")


def test_preview_reports_starter_fixtures_invalid_for_registration() -> None:
    previews = preview_truth_banks()

    assert {item["validation_status"] for item in previews} == {"invalid"}
    assert all("starter fixture" in item["validation_errors"][0] for item in previews)


def test_preview_can_include_starter_fixtures_for_dev_mode() -> None:
    previews = preview_truth_banks(allow_starter=True)

    assert {item["validation_status"] for item in previews} == {"valid"}
    assert all(item["content_class"] == STARTER_CONTENT_CLASS for item in previews)
    assert previews == sorted(previews, key=lambda item: item["family_id"])
    assert {
        "family_id",
        "display_name",
        "family_version",
        "truth_bank_path",
        "validation_status",
        "validation_errors",
        "truth_bank_version",
        "schema_version",
        "content_class",
        "blocks",
    }.issubset(previews[0])


def test_preview_lists_registered_fixture_from_temp_config(tmp_path) -> None:
    root = tmp_path / "truth_banks"
    root.mkdir()
    bank_path = root / "hardware.json"
    bank_path.write_text(json.dumps(registered_bank()), encoding="utf-8")
    families = [
        {
            "id": "hardware_rtl",
            "display_name": "Hardware RTL",
            "version": "1",
            "truth_bank_path": "hardware.json",
            "enabled": True,
        }
    ]

    previews = list_truth_bank_previews(families, root=root)

    assert previews == [
        {
            "family_id": "hardware_rtl",
            "display_name": "Hardware RTL",
            "family_version": "1",
            "truth_bank_path": str(bank_path),
            "validation_status": "valid",
            "validation_errors": [],
            "truth_bank_version": "2026.06",
            "schema_version": TRUTH_BANK_SCHEMA_VERSION,
            "content_class": REGISTERED_CONTENT_CLASS,
            "blocks": [
                {
                    "id": "rtl_block",
                    "type": "experience",
                    "name": "Reviewed RTL Block",
                    "required": True,
                },
                {
                    "id": "project_block",
                    "type": "project",
                    "name": "Reviewed Project Block",
                    "required": False,
                },
            ],
        }
    ]


def test_scoring_wrapper_preserves_configuration_error_type() -> None:
    bank = registered_bank()
    bank["schema_version"] = "old"

    with pytest.raises(ScoringConfigurationError, match="schema_version"):
        validate_truth_bank(bank, expected_family="hardware_rtl")
