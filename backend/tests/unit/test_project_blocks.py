from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from jobagent_v2.master_cvs import MasterCVValidationError, validate_master_tex_compiles
from jobagent_v2.project_blocks import (
    FAMILY_IDS,
    PROJECT_BLOCK_POLICY_VERSION,
    PROJECT_BLOCK_SCHEMA_VERSION,
    ProjectBlockRegistryError,
    estimated_rendered_lines,
    extract_master_project_blocks,
    list_project_blocks,
    load_project_block_registry,
    project_block_content_hash,
    validate_project_block_registry,
    validate_replacement_pair,
    validate_tailoring_decision,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
MASTER_ROOT = REPO_ROOT / "master-cvs"


@pytest.fixture
def registry() -> dict[str, object]:
    return load_project_block_registry()


def clone_registry(registry: dict[str, object]) -> dict[str, object]:
    return copy.deepcopy(registry)


def test_all_canonical_master_blocks_register_successfully(registry: dict[str, object]) -> None:
    blocks = list_project_blocks()

    assert len(blocks) == 12
    assert [block.block_id for block in blocks[:3]] == [
        "tinynpu_digital_ic_v1",
        "sparrow_v_digital_ic_v1",
        "sparrow_cluster_digital_ic_v1",
    ]
    assert all(block.approved and block.immutable for block in blocks)
    assert {block.family for block in blocks} == set(FAMILY_IDS)
    assert registry["schema_version"] == PROJECT_BLOCK_SCHEMA_VERSION
    assert registry["policy_version"] == PROJECT_BLOCK_POLICY_VERSION


def test_every_master_project_has_registry_entry(registry: dict[str, object]) -> None:
    extracted = extract_master_project_blocks(MASTER_ROOT)
    registered = {
        (block["source_master"], block["heading"])
        for block in registry["blocks"]  # type: ignore[index]
    }

    assert len(extracted) == 12
    assert {(block.source_master, block.heading) for block in extracted} == registered


def test_exact_text_and_hash_agree_with_master_source(registry: dict[str, object]) -> None:
    extracted = {
        (block.source_master, block.heading): block
        for block in extract_master_project_blocks(MASTER_ROOT)
    }

    for block in registry["blocks"]:  # type: ignore[index]
        source = extracted[(block["source_master"], block["heading"])]
        assert block["subtitle"] == source.subtitle
        assert block["dates"] == source.dates
        assert block["bullets"] == source.bullets
        assert block["content_hash"] == project_block_content_hash(block)


def test_duplicate_block_id_rejected(registry: dict[str, object]) -> None:
    data = clone_registry(registry)
    data["blocks"][1]["block_id"] = data["blocks"][0]["block_id"]  # type: ignore[index]

    with pytest.raises(ProjectBlockRegistryError, match="duplicate project block ID"):
        validate_project_block_registry(data)


def test_duplicate_incompatible_content_rejected(registry: dict[str, object]) -> None:
    data = clone_registry(registry)
    first = data["blocks"][0]  # type: ignore[index]
    second = data["blocks"][1]  # type: ignore[index]
    for key in ("heading", "subtitle", "dates", "bullets", "source_master", "content_hash"):
        second[key] = first[key]

    with pytest.raises(ProjectBlockRegistryError, match="duplicate project block content"):
        validate_project_block_registry(data)


def test_unknown_family_rejected(registry: dict[str, object]) -> None:
    data = clone_registry(registry)
    data["blocks"][0]["family"] = "data_science"  # type: ignore[index]

    with pytest.raises(ProjectBlockRegistryError, match="unknown project block family"):
        validate_project_block_registry(data)


def test_missing_bullet_rejected(registry: dict[str, object]) -> None:
    data = clone_registry(registry)
    data["blocks"][0]["bullets"] = []  # type: ignore[index]

    with pytest.raises(ProjectBlockRegistryError, match="bullets"):
        validate_project_block_registry(data)


def test_unapproved_block_rejected(registry: dict[str, object]) -> None:
    data = clone_registry(registry)
    data["blocks"][0]["approved"] = False  # type: ignore[index]

    with pytest.raises(ProjectBlockRegistryError, match="not approved"):
        validate_project_block_registry(data)


def test_forbidden_section_content_rejected(registry: dict[str, object]) -> None:
    data = clone_registry(registry)
    data["blocks"][0]["bullets"][0] = r"\section*{Education}"  # type: ignore[index]

    with pytest.raises(ProjectBlockRegistryError, match="forbidden section"):
        validate_project_block_registry(data)


def test_dynamic_placeholder_rejected(registry: dict[str, object]) -> None:
    data = clone_registry(registry)
    data["blocks"][0]["bullets"][0] = "Built {{dynamic}} project block."  # type: ignore[index]

    with pytest.raises(ProjectBlockRegistryError, match="dynamic placeholder"):
        validate_project_block_registry(data)


def test_invalid_replacement_pair_rejected(registry: dict[str, object]) -> None:
    with pytest.raises(ProjectBlockRegistryError, match="not eligible"):
        validate_replacement_pair(
            "digital_ic",
            "sparrow_cluster_digital_ic_v1",
            "jobagent_software_v1",
            registry,
        )


def test_approved_replacement_pair_returns_policy_rule(registry: dict[str, object]) -> None:
    rule = validate_replacement_pair(
        "digital_ic",
        "sparrow_cluster_digital_ic_v1",
        "sparrowml_ml_v1",
        registry,
    )

    assert rule["requires_review"] is True


def test_more_than_one_substitution_rejected(registry: dict[str, object]) -> None:
    decision = {
        "base_family": "digital_ic",
        "base_blocks": registry["base_project_order"]["digital_ic"],  # type: ignore[index]
        "removed_block": "sparrow_cluster_digital_ic_v1",
        "inserted_block": "sparrowml_ml_v1",
        "final_order": ["tinynpu_digital_ic_v1", "sparrowml_ml_v1"],
        "reason": "fixture",
        "job_evidence": [],
        "requires_review": True,
        "policy_version": registry["policy_version"],
    }

    with pytest.raises(ProjectBlockRegistryError, match="removes too many blocks"):
        validate_tailoring_decision(decision, registry)


def test_base_family_project_order_validation(registry: dict[str, object]) -> None:
    data = clone_registry(registry)
    data["base_project_order"]["digital_ic"] = list(  # type: ignore[index]
        reversed(data["base_project_order"]["digital_ic"])  # type: ignore[index]
    )

    with pytest.raises(ProjectBlockRegistryError, match="base project order"):
        validate_project_block_registry(data)


def test_reordering_policy_validation(registry: dict[str, object]) -> None:
    data = clone_registry(registry)
    data["tailoring_policy"]["project_reordering_allowed"] = False  # type: ignore[index]
    decision = {
        "base_family": "ml",
        "base_blocks": data["base_project_order"]["ml"],  # type: ignore[index]
        "removed_block": None,
        "inserted_block": None,
        "final_order": list(reversed(data["base_project_order"]["ml"])),  # type: ignore[index]
        "reason": "fixture",
        "job_evidence": [],
        "requires_review": False,
        "policy_version": data["policy_version"],
    }

    with pytest.raises(ProjectBlockRegistryError, match="reordering is disabled"):
        validate_tailoring_decision(decision, data)


def test_oversized_block_rejected(registry: dict[str, object]) -> None:
    data = clone_registry(registry)
    data["blocks"][0]["render_budget"]["max_lines"] = 1  # type: ignore[index]

    with pytest.raises(ProjectBlockRegistryError, match="exceeds render budget"):
        validate_project_block_registry(data)


def test_deterministic_registry_loading() -> None:
    first = load_project_block_registry()
    second = load_project_block_registry()

    assert first == second


def test_schema_and_policy_versions_are_stable(registry: dict[str, object]) -> None:
    assert registry["schema_version"] == "project-block-registry-v1"
    assert registry["policy_version"] == "phase-c-project-tailoring-policy-v1"


def test_tex_compile_validation_skips_gracefully_when_toolchain_incomplete() -> None:
    if shutil.which("pdflatex") is None:
        pytest.skip("pdflatex is not installed")
    try:
        page_counts = validate_master_tex_compiles(MASTER_ROOT)
    except MasterCVValidationError as error:
        if "not found" in str(error) or "pdflatex failed" in str(error):
            pytest.skip(f"local LaTeX toolchain cannot compile approved masters: {error}")
        raise

    assert page_counts == {"digital_ic": 1, "verification": 1, "software": 1, "ml": 1}


def test_rendered_line_budget_is_not_source_line_count(registry: dict[str, object]) -> None:
    block = registry["blocks"][0]  # type: ignore[index]
    source_lines = len(json.dumps(block, indent=2).splitlines())
    rendered_lines = estimated_rendered_lines(
        block, registry["render_policy"]  # type: ignore[arg-type]
    )

    assert rendered_lines < source_lines
    assert rendered_lines <= block["render_budget"]["max_lines"]


def test_valid_tailoring_decision_shape(registry: dict[str, object]) -> None:
    decision = {
        "base_family": "digital_ic",
        "base_blocks": registry["base_project_order"]["digital_ic"],  # type: ignore[index]
        "removed_block": "sparrow_cluster_digital_ic_v1",
        "inserted_block": "sparrowml_ml_v1",
        "final_order": [
            "tinynpu_digital_ic_v1",
            "sparrow_v_digital_ic_v1",
            "sparrowml_ml_v1",
        ],
        "reason": "Fixture hybrid Digital IC/ML job evidence.",
        "job_evidence": [{"family": "ml", "phrase": "model deployment"}],
        "requires_review": True,
        "policy_version": registry["policy_version"],
    }

    validate_tailoring_decision(decision, registry)
