"""Canonical truth-bank validation and registration helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


TRUTH_BANK_SCHEMA_VERSION = "phase6a-truth-bank-v1"
STARTER_CONTENT_CLASS = "starter_fixture"
REGISTERED_CONTENT_CLASS = "registered"
ALLOWED_CONTENT_CLASSES = {STARTER_CONTENT_CLASS, REGISTERED_CONTENT_CLASS}
ALLOWED_BLOCK_TYPES = {"experience", "project"}
PLACEHOLDER_PATTERNS = (
    re.compile(r"\bcandidate\b", re.IGNORECASE),
    re.compile(r"contact details maintained", re.IGNORECASE),
    re.compile(r"education details maintained", re.IGNORECASE),
    re.compile(r"\bplaceholder\b", re.IGNORECASE),
)


class TruthBankValidationError(ValueError):
    """Raised when a truth bank is missing required canonical-content guarantees."""


def load_truth_bank_json(
    path: Path | str,
    *,
    expected_family: str | None = None,
    allow_starter: bool = False,
) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_truth_bank(data, expected_family=expected_family, allow_starter=allow_starter)
    return data


def validate_truth_bank(
    data: dict[str, Any],
    *,
    expected_family: str | None = None,
    allow_starter: bool = False,
) -> None:
    if not isinstance(data, dict):
        raise TruthBankValidationError("truth bank must be a JSON object")
    family_id = _required_string(data, "family_id", "truth bank")
    if expected_family is not None and family_id != expected_family:
        raise TruthBankValidationError("truth bank family does not match CV family")
    _required_string(data, "version", "truth bank")
    schema_version = _required_string(data, "schema_version", "truth bank")
    if schema_version != TRUTH_BANK_SCHEMA_VERSION:
        raise TruthBankValidationError("truth bank schema_version is unsupported")
    content_class = _required_string(data, "content_class", "truth bank")
    if content_class not in ALLOWED_CONTENT_CLASSES:
        raise TruthBankValidationError("truth bank content_class is unsupported")
    if content_class == STARTER_CONTENT_CLASS and not allow_starter:
        raise TruthBankValidationError(
            "starter fixture truth banks cannot be registered as real data"
        )

    header = data.get("header")
    if not isinstance(header, dict):
        raise TruthBankValidationError("truth bank header is required")
    _required_string(header, "name", "truth bank header")
    _required_string(header, "contact", "truth bank header")
    education = data.get("education")
    if not isinstance(education, list) or not education:
        raise TruthBankValidationError("truth bank education content is required")
    _require_string_list(education, "education")

    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise TruthBankValidationError("truth bank requires blocks")
    ids: set[str] = set()
    for index, block in enumerate(blocks):
        _validate_block(block, ids, index)

    skill_groups = data.get("skill_groups", [])
    if not isinstance(skill_groups, list):
        raise TruthBankValidationError("truth bank skill_groups must be a list")
    for index, group in enumerate(skill_groups):
        if not isinstance(group, dict):
            raise TruthBankValidationError(f"skill group {index} must be an object")
        _required_string(group, "name", f"skill group {index}")
        skills = group.get("skills")
        if not isinstance(skills, list) or not skills:
            raise TruthBankValidationError(f"skill group {index} requires skills")
        _require_string_list(skills, f"skill group {index} skills")

    if content_class == REGISTERED_CONTENT_CLASS:
        _reject_placeholder_content(data)


def truth_bank_preview(
    family: dict[str, Any],
    *,
    root: Path | str,
    allow_starter: bool = False,
) -> dict[str, Any]:
    family_id = str(family.get("id") or "")
    path = Path(root) / str(family.get("truth_bank_path") or "")
    base = {
        "family_id": family_id,
        "display_name": str(family.get("display_name") or ""),
        "family_version": str(family.get("version") or ""),
        "truth_bank_path": str(path),
        "validation_status": "invalid",
        "validation_errors": [],
        "truth_bank_version": None,
        "schema_version": None,
        "content_class": None,
        "blocks": [],
    }
    try:
        data = load_truth_bank_json(path, expected_family=family_id, allow_starter=allow_starter)
    except (OSError, json.JSONDecodeError, TruthBankValidationError) as error:
        return {**base, "validation_errors": [str(error)]}
    blocks = [
        {
            "id": str(block["id"]),
            "type": str(block["type"]),
            "name": str(block["name"]),
            "required": bool(block.get("is_required")),
        }
        for block in data["blocks"]
    ]
    return {
        **base,
        "validation_status": "valid",
        "truth_bank_version": str(data["version"]),
        "schema_version": str(data["schema_version"]),
        "content_class": str(data["content_class"]),
        "blocks": blocks,
    }


def list_truth_bank_previews(
    families: list[dict[str, Any]],
    *,
    root: Path | str,
    allow_starter: bool = False,
) -> list[dict[str, Any]]:
    return [
        truth_bank_preview(family, root=root, allow_starter=allow_starter)
        for family in sorted(families, key=lambda item: str(item.get("id") or ""))
        if bool(family.get("enabled", True))
    ]


def _validate_block(block: Any, ids: set[str], index: int) -> None:
    if not isinstance(block, dict):
        raise TruthBankValidationError(f"block {index} must be an object")
    block_id = _required_string(block, "id", f"block {index}")
    if block_id in ids:
        raise TruthBankValidationError(f"duplicate block ID: {block_id}")
    ids.add(block_id)
    block_type = _required_string(block, "type", f"block {block_id}")
    if block_type not in ALLOWED_BLOCK_TYPES:
        raise TruthBankValidationError(f"unsupported block type for {block_id}: {block_type}")
    _required_string(block, "name", f"block {block_id}")
    _required_string(block, "canonical_text", f"block {block_id}")
    bullets = block.get("bullets")
    if not isinstance(bullets, list) or not bullets:
        raise TruthBankValidationError(f"block {block_id} requires canonical bullets")
    _require_string_list(bullets, f"block {block_id} bullets")
    _require_string_list(block.get("technologies"), f"block {block_id} technologies")
    _require_string_list(block.get("domains"), f"block {block_id} domains")
    _required_string(block, "provenance", f"block {block_id}")
    if not bool(block.get("is_required")) and not bool(block.get("is_optional")):
        raise TruthBankValidationError(
            f"block {block_id} must declare is_required or is_optional"
        )


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TruthBankValidationError(f"{context} requires non-empty {key}")
    return value.strip()


def _require_string_list(value: Any, context: str) -> None:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise TruthBankValidationError(f"{context} must be a non-empty string list")


def _reject_placeholder_content(data: dict[str, Any]) -> None:
    strings: list[str] = []
    header = data.get("header", {})
    strings.extend(str(value) for value in header.values())
    strings.extend(str(value) for value in data.get("education", []))
    for block in data.get("blocks", []):
        strings.append(str(block.get("canonical_text", "")))
        strings.extend(str(value) for value in block.get("bullets", []))
    for value in strings:
        if any(pattern.search(value) for pattern in PLACEHOLDER_PATTERNS):
            raise TruthBankValidationError("registered truth bank contains placeholder text")
