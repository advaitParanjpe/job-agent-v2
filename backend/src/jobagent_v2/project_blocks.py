"""Approved whole-project block registry and bounded-tailoring policy."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jobagent_v2.master_cvs import EXPECTED_MASTER_FAMILIES, MASTER_CV_ROOT


PROJECT_BLOCK_SCHEMA_VERSION = "project-block-registry-v1"
PROJECT_BLOCK_POLICY_VERSION = "phase-c-project-tailoring-policy-v1"
PROJECT_BLOCK_REGISTRY_PATH = Path(__file__).with_name("data") / "project_block_registry.json"
FAMILY_IDS = tuple(EXPECTED_MASTER_FAMILIES)
FORBIDDEN_SECTION_TERMS = (
    r"\section*{Education}",
    r"\section*{Experience}",
    r"\section*{Skills}",
    r"\resumeEduHeading",
    r"\resumeExpHeading",
)
UNSUPPORTED_PLACEHOLDERS = ("{{", "}}", "<<", ">>", "@@")


class ProjectBlockRegistryError(ValueError):
    """Raised when approved project blocks or policy metadata are invalid."""


@dataclass(frozen=True)
class ProjectBlock:
    block_id: str
    project_id: str
    display_name: str
    family: str
    home_family: str
    eligible_families: list[str]
    approved: bool
    immutable: bool
    source_master: str
    heading: str
    subtitle: str
    dates: str
    bullets: list[str]
    tags: list[str]
    capabilities: dict[str, float]
    bridge_domains: list[list[str]]
    evidence_terms: list[str]
    portfolio_strength: float
    render_budget: dict[str, int]
    evidence_refs: list[dict[str, Any]]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtractedProjectBlock:
    source_master: str
    heading: str
    subtitle: str
    dates: str
    bullets: list[str]
    raw_tex: str


def load_project_block_registry(
    path: Path | str = PROJECT_BLOCK_REGISTRY_PATH,
    *,
    master_root: Path | str = MASTER_CV_ROOT,
) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_project_block_registry(data, master_root=master_root)
    return data


def list_project_blocks(
    path: Path | str = PROJECT_BLOCK_REGISTRY_PATH,
    *,
    master_root: Path | str = MASTER_CV_ROOT,
) -> list[ProjectBlock]:
    registry = load_project_block_registry(path, master_root=master_root)
    return [ProjectBlock(**block) for block in registry["blocks"]]


def validate_project_block_registry(
    data: dict[str, Any],
    *,
    master_root: Path | str = MASTER_CV_ROOT,
) -> None:
    if not isinstance(data, dict):
        raise ProjectBlockRegistryError("project-block registry must be a JSON object")
    if data.get("schema_version") != PROJECT_BLOCK_SCHEMA_VERSION:
        raise ProjectBlockRegistryError("project-block registry schema_version is unsupported")
    if data.get("policy_version") != PROJECT_BLOCK_POLICY_VERSION:
        raise ProjectBlockRegistryError("project-block policy_version is unsupported")
    if tuple(data.get("families") or ()) != FAMILY_IDS:
        raise ProjectBlockRegistryError("project-block registry families are unsupported")
    render_policy = _validate_render_policy(data.get("render_policy"))
    _validate_tailoring_policy(data.get("tailoring_policy"))
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ProjectBlockRegistryError("project-block registry requires blocks")

    extracted = extract_master_project_blocks(master_root)
    extracted_by_source = {
        (block.source_master, block.heading): block for block in extracted
    }
    ids: set[str] = set()
    content_hashes: dict[str, str] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for index, block in enumerate(blocks):
        _validate_block_shape(block, index)
        block_id = str(block["block_id"])
        if block_id in ids:
            raise ProjectBlockRegistryError(f"duplicate project block ID: {block_id}")
        ids.add(block_id)
        by_id[block_id] = block
        source_key = (str(block["source_master"]), str(block["heading"]))
        extracted_block = extracted_by_source.get(source_key)
        if extracted_block is None:
            raise ProjectBlockRegistryError(
                f"project block {block_id} does not match a canonical master project"
            )
        _validate_exact_master_match(block, extracted_block)
        content_hash = project_block_content_hash(block)
        if block["content_hash"] != content_hash:
            raise ProjectBlockRegistryError(f"content hash mismatch for {block_id}")
        previous = content_hashes.get(content_hash)
        if previous is not None and previous != block_id:
            raise ProjectBlockRegistryError(
                f"duplicate project block content under conflicting IDs: {previous}, {block_id}"
            )
        content_hashes[content_hash] = block_id
        lines = estimated_rendered_lines(block, render_policy)
        if lines > int(block["render_budget"]["max_lines"]):
            raise ProjectBlockRegistryError(
                f"project block {block_id} exceeds render budget: {lines} lines"
            )

    _validate_all_master_blocks_registered(extracted, blocks)
    _validate_base_order(data.get("base_project_order"), by_id, extracted)
    _validate_compatibility(data.get("compatibility"), by_id)


def extract_master_project_blocks(root: Path | str = MASTER_CV_ROOT) -> list[ExtractedProjectBlock]:
    root = Path(root)
    blocks: list[ExtractedProjectBlock] = []
    for family_id, config in EXPECTED_MASTER_FAMILIES.items():
        tex_path = root / f"{config['stem']}.tex"
        text = tex_path.read_text(encoding="utf-8")
        project_section = _project_section(text, family_id)
        cursor = 0
        while True:
            heading_index = project_section.find(r"\resumeProjectHeading", cursor)
            if heading_index == -1:
                break
            args, after_heading = _read_command_args(project_section, heading_index, 3)
            list_begin = project_section.find(r"\begin{resumeItemList}", after_heading)
            if list_begin == -1:
                raise ProjectBlockRegistryError(
                    f"project {args[0]} in {family_id} is missing resumeItemList"
                )
            list_end = project_section.find(r"\end{resumeItemList}", list_begin)
            if list_end == -1:
                raise ProjectBlockRegistryError(
                    f"project {args[0]} in {family_id} has unterminated resumeItemList"
                )
            raw_end = list_end + len(r"\end{resumeItemList}")
            raw_tex = project_section[heading_index:raw_end]
            bullets = _extract_resume_items(project_section[list_begin:raw_end])
            blocks.append(
                ExtractedProjectBlock(
                    source_master=family_id,
                    heading=args[0],
                    subtitle=args[1],
                    dates=args[2],
                    bullets=bullets,
                    raw_tex=raw_tex.strip(),
                )
            )
            cursor = raw_end
    return blocks


def validate_tailoring_decision(
    decision: dict[str, Any],
    registry: dict[str, Any],
) -> None:
    if not isinstance(decision, dict):
        raise ProjectBlockRegistryError("tailoring decision must be an object")
    policy = registry["tailoring_policy"]
    base_family = _required_string(decision, "base_family", "tailoring decision")
    if base_family not in FAMILY_IDS:
        raise ProjectBlockRegistryError("tailoring decision has unknown base_family")
    by_id = {str(block["block_id"]): block for block in registry["blocks"]}
    base_blocks = _required_string_list(decision.get("base_blocks"), "base_blocks")
    expected_order = registry["base_project_order"][base_family]
    if base_blocks != expected_order:
        raise ProjectBlockRegistryError("tailoring decision base_blocks do not match policy")
    final_order = _required_string_list(decision.get("final_order"), "final_order")
    if set(final_order) != set(base_blocks):
        removed = _required_string(decision, "removed_block", "tailoring decision")
        inserted = _required_string(decision, "inserted_block", "tailoring decision")
        if len(set(base_blocks) - set(final_order)) > 1:
            raise ProjectBlockRegistryError("tailoring decision removes too many blocks")
        if len(set(final_order) - set(base_blocks)) > 1:
            raise ProjectBlockRegistryError("tailoring decision inserts too many blocks")
        if int(policy["maximum_project_substitutions"]) < 1:
            raise ProjectBlockRegistryError("project substitutions are disabled by policy")
        validate_replacement_pair(base_family, removed, inserted, registry)
        if set(final_order) != (set(base_blocks) - {removed}) | {inserted}:
            raise ProjectBlockRegistryError("tailoring decision final_order is inconsistent")
    elif not bool(policy["project_reordering_allowed"]) and final_order != base_blocks:
        raise ProjectBlockRegistryError("project reordering is disabled by policy")
    for block_id in final_order:
        if block_id not in by_id:
            raise ProjectBlockRegistryError(
                f"tailoring decision references unknown block: {block_id}"
            )
    if not isinstance(decision.get("job_evidence", []), list):
        raise ProjectBlockRegistryError("tailoring decision job_evidence must be a list")
    _required_string(decision, "reason", "tailoring decision")
    if decision.get("policy_version") != registry["policy_version"]:
        raise ProjectBlockRegistryError("tailoring decision policy_version mismatch")


def validate_replacement_pair(
    base_family: str,
    removed_block_id: str,
    inserted_block_id: str,
    registry: dict[str, Any],
) -> dict[str, Any]:
    if base_family not in FAMILY_IDS:
        raise ProjectBlockRegistryError("unknown replacement base family")
    by_id = {str(block["block_id"]): block for block in registry["blocks"]}
    removed = by_id.get(removed_block_id)
    inserted = by_id.get(inserted_block_id)
    if removed is None or inserted is None:
        raise ProjectBlockRegistryError("replacement pair references unknown block")
    if removed["family"] != base_family:
        raise ProjectBlockRegistryError("removed block is not in the base family")
    if base_family not in inserted["eligible_families"]:
        raise ProjectBlockRegistryError("inserted block is not eligible for the base family")
    rules = registry.get("compatibility", {}).get(base_family, {}).get(removed_block_id, [])
    for rule in rules:
        if rule.get("insert_block_id") == inserted_block_id:
            return rule
    raise ProjectBlockRegistryError("replacement pair is not explicitly approved")


def project_block_content_hash(block: dict[str, Any]) -> str:
    payload = {
        "heading": block["heading"],
        "subtitle": block["subtitle"],
        "dates": block["dates"],
        "bullets": block["bullets"],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def estimated_rendered_lines(block: dict[str, Any], render_policy: dict[str, int]) -> int:
    chars_per_line = int(render_policy["chars_per_line"])
    heading_lines = int(render_policy["heading_lines"])
    total = heading_lines
    for bullet in block["bullets"]:
        total += max(1, math.ceil(len(_plain_latex(str(bullet))) / chars_per_line))
    return total


def _validate_block_shape(block: Any, index: int) -> None:
    if not isinstance(block, dict):
        raise ProjectBlockRegistryError(f"project block {index} must be an object")
    for key in (
        "block_id", "project_id", "display_name", "family", "source_master",
        "heading", "subtitle", "dates", "content_hash",
    ):
        _required_string(block, key, f"project block {index}")
    family = str(block["family"])
    if family not in FAMILY_IDS:
        raise ProjectBlockRegistryError(f"unknown project block family: {family}")
    home_family = str(block.get("home_family") or "")
    if home_family not in FAMILY_IDS:
        raise ProjectBlockRegistryError("project block home_family is unknown")
    if home_family != family:
        raise ProjectBlockRegistryError("project block home_family must match approved text family")
    if block["source_master"] not in FAMILY_IDS:
        raise ProjectBlockRegistryError("project block source_master is unknown")
    if block.get("approved") is not True:
        raise ProjectBlockRegistryError(f"project block {block['block_id']} is not approved")
    if block.get("immutable") is not True:
        raise ProjectBlockRegistryError(f"project block {block['block_id']} is not immutable")
    eligible = _required_string_list(block.get("eligible_families"), "eligible_families")
    unknown = sorted(set(eligible) - set(FAMILY_IDS))
    if unknown:
        raise ProjectBlockRegistryError(f"unknown eligible family: {unknown[0]}")
    if family not in eligible:
        raise ProjectBlockRegistryError("project block must be eligible for its own family")
    bullets = _required_string_list(block.get("bullets"), "project block bullets")
    tags = _required_string_list(block.get("tags"), "project block tags")
    if not tags:
        raise ProjectBlockRegistryError("project block tags are required")
    _validate_portfolio_metadata(block)
    evidence_refs = block.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        raise ProjectBlockRegistryError("project block evidence_refs must be a list")
    budget = block.get("render_budget")
    if not isinstance(budget, dict) or not isinstance(budget.get("max_lines"), int):
        raise ProjectBlockRegistryError("project block render_budget.max_lines is required")
    if int(budget["max_lines"]) <= 0:
        raise ProjectBlockRegistryError("project block render budget must be positive")
    combined = "\n".join(
        [str(block["heading"]), str(block["subtitle"]), str(block["dates"]), *bullets]
    )
    if any(term in combined for term in FORBIDDEN_SECTION_TERMS):
        raise ProjectBlockRegistryError("project block contains forbidden section content")
    if any(token in combined for token in UNSUPPORTED_PLACEHOLDERS):
        raise ProjectBlockRegistryError("project block contains unsupported dynamic placeholder")
    if "\\resumeProjectHeading" in combined or "\\begin{resumeItemList}" in combined:
        raise ProjectBlockRegistryError("project block contains malformed LaTeX fragment")


def _validate_exact_master_match(
    block: dict[str, Any],
    extracted: ExtractedProjectBlock,
) -> None:
    for key in ("heading", "subtitle", "dates"):
        if str(block[key]) != getattr(extracted, key):
            raise ProjectBlockRegistryError(
                f"project block {block['block_id']} {key} does not match source master"
            )
    if list(block["bullets"]) != extracted.bullets:
        raise ProjectBlockRegistryError(
            f"project block {block['block_id']} bullets do not match source master"
        )


def _validate_all_master_blocks_registered(
    extracted: list[ExtractedProjectBlock],
    blocks: list[dict[str, Any]],
) -> None:
    registered = {(str(block["source_master"]), str(block["heading"])) for block in blocks}
    for block in extracted:
        if (block.source_master, block.heading) not in registered:
            raise ProjectBlockRegistryError(
                f"canonical master project is unregistered: {block.source_master}/{block.heading}"
            )


def _validate_base_order(
    value: Any,
    by_id: dict[str, dict[str, Any]],
    extracted: list[ExtractedProjectBlock],
) -> None:
    if not isinstance(value, dict) or set(value) != set(FAMILY_IDS):
        raise ProjectBlockRegistryError("base_project_order must cover all families")
    for family in FAMILY_IDS:
        order = _required_string_list(value.get(family), f"{family} base_project_order")
        source_order = [block.heading for block in extracted if block.source_master == family]
        registry_order = []
        for block_id in order:
            block = by_id.get(block_id)
            if block is None:
                raise ProjectBlockRegistryError("base_project_order references unknown block")
            if block["family"] != family:
                raise ProjectBlockRegistryError("base_project_order mixes families")
            registry_order.append(str(block["heading"]))
        if registry_order != source_order:
            raise ProjectBlockRegistryError(f"{family} base project order does not match master")


def _validate_compatibility(value: Any, by_id: dict[str, dict[str, Any]]) -> None:
    if not isinstance(value, dict) or set(value) != set(FAMILY_IDS):
        raise ProjectBlockRegistryError("compatibility must cover all families")
    for family, rules_by_removed in value.items():
        if not isinstance(rules_by_removed, dict):
            raise ProjectBlockRegistryError("compatibility family entry must be an object")
        for removed_id, rules in rules_by_removed.items():
            removed = by_id.get(removed_id)
            if removed is None:
                raise ProjectBlockRegistryError("compatibility references unknown removed block")
            if removed["family"] != family:
                raise ProjectBlockRegistryError("compatibility removed block family mismatch")
            if not isinstance(rules, list) or not rules:
                raise ProjectBlockRegistryError("compatibility rules must be a non-empty list")
            for rule in rules:
                if not isinstance(rule, dict):
                    raise ProjectBlockRegistryError("compatibility rule must be an object")
                inserted_id = _required_string(rule, "insert_block_id", "compatibility rule")
                inserted = by_id.get(inserted_id)
                if inserted is None:
                    raise ProjectBlockRegistryError(
                        "compatibility references unknown inserted block"
                    )
                if family not in inserted["eligible_families"]:
                    raise ProjectBlockRegistryError(
                        "compatibility inserted block is not family-eligible"
                    )
                if not isinstance(rule.get("requires_review"), bool):
                    raise ProjectBlockRegistryError("compatibility requires_review must be boolean")
                _required_string(rule, "reason", "compatibility rule")


def _validate_portfolio_metadata(block: dict[str, Any]) -> None:
    capabilities = block.get("capabilities")
    if not isinstance(capabilities, dict) or not capabilities:
        raise ProjectBlockRegistryError("project block capabilities are required")
    for capability, weight in capabilities.items():
        if not isinstance(capability, str) or not capability:
            raise ProjectBlockRegistryError("project block capability names must be strings")
        if not isinstance(weight, (int, float)) or not 0.0 <= float(weight) <= 1.0:
            raise ProjectBlockRegistryError("project block capability weights must be bounded")
    bridge_domains = block.get("bridge_domains")
    if not isinstance(bridge_domains, list):
        raise ProjectBlockRegistryError("project block bridge_domains must be a list")
    for pair in bridge_domains:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(item, str) and item for item in pair)
        ):
            raise ProjectBlockRegistryError("project block bridge_domains entries are invalid")
    evidence_terms = _required_string_list(block.get("evidence_terms"), "evidence_terms")
    if not evidence_terms:
        raise ProjectBlockRegistryError("project block evidence_terms are required")
    strength = block.get("portfolio_strength")
    if not isinstance(strength, (int, float)) or not 0.0 <= float(strength) <= 1.0:
        raise ProjectBlockRegistryError("project block portfolio_strength must be bounded")


def _validate_tailoring_policy(value: Any) -> None:
    if not isinstance(value, dict):
        raise ProjectBlockRegistryError("tailoring_policy is required")
    expected_false = (
        "bullet_rewriting_allowed", "project_block_editing_allowed",
        "dynamic_skills_allowed", "education_editing_allowed", "experience_editing_allowed",
    )
    for key in expected_false:
        if value.get(key) is not False:
            raise ProjectBlockRegistryError(f"{key} must be false")
    if value.get("maximum_project_substitutions") != 1:
        raise ProjectBlockRegistryError("maximum_project_substitutions must be 1")
    if not isinstance(value.get("project_reordering_allowed"), bool):
        raise ProjectBlockRegistryError("project_reordering_allowed must be boolean")


def _validate_render_policy(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ProjectBlockRegistryError("render_policy is required")
    if value.get("type") != "conservative_text_wrap":
        raise ProjectBlockRegistryError("render_policy type is unsupported")
    chars = value.get("chars_per_line")
    heading = value.get("heading_lines")
    if not isinstance(chars, int) or chars <= 0:
        raise ProjectBlockRegistryError("render_policy chars_per_line must be positive")
    if not isinstance(heading, int) or heading <= 0:
        raise ProjectBlockRegistryError("render_policy heading_lines must be positive")
    return {"chars_per_line": chars, "heading_lines": heading}


def _project_section(text: str, family_id: str) -> str:
    start_match = re.search(r"\\section\*\{Projects\}", text)
    if start_match is None:
        raise ProjectBlockRegistryError(f"master {family_id} is missing Projects section")
    end_match = re.search(r"\\section\*\{Skills\}", text[start_match.end():])
    if end_match is None:
        raise ProjectBlockRegistryError(f"master {family_id} is missing Skills section")
    end = start_match.end() + end_match.start()
    return text[start_match.end():end]


def _read_command_args(text: str, command_index: int, count: int) -> tuple[list[str], int]:
    cursor = command_index + len(r"\resumeProjectHeading")
    args: list[str] = []
    for _ in range(count):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or text[cursor] != "{":
            raise ProjectBlockRegistryError("malformed resumeProjectHeading")
        value, cursor = _read_braced(text, cursor)
        args.append(value)
    return args, cursor


def _read_braced(text: str, open_index: int) -> tuple[str, int]:
    if text[open_index] != "{":
        raise ProjectBlockRegistryError("expected braced LaTeX argument")
    depth = 0
    cursor = open_index
    while cursor < len(text):
        char = text[cursor]
        escaped = cursor > 0 and text[cursor - 1] == "\\"
        if char == "{" and not escaped:
            depth += 1
        elif char == "}" and not escaped:
            depth -= 1
            if depth == 0:
                return text[open_index + 1:cursor], cursor + 1
        cursor += 1
    raise ProjectBlockRegistryError("unterminated braced LaTeX argument")


def _extract_resume_items(value: str) -> list[str]:
    bullets: list[str] = []
    cursor = 0
    command = r"\resumeItem"
    while True:
        index = value.find(command, cursor)
        if index == -1:
            break
        arg_start = index + len(command)
        while arg_start < len(value) and value[arg_start].isspace():
            arg_start += 1
        bullet, cursor = _read_braced(value, arg_start)
        bullets.append(bullet)
    if not bullets:
        raise ProjectBlockRegistryError("project block requires at least one bullet")
    return bullets


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProjectBlockRegistryError(f"{context} requires non-empty {key}")
    return value


def _required_string_list(value: Any, context: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ProjectBlockRegistryError(f"{context} must be a non-empty string list")
    return value


def _plain_latex(value: str) -> str:
    text = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", value)
    text = text.replace(r"\%", "%").replace(r"\&", "&")
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()
