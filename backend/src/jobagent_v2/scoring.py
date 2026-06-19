"""Deterministic Phase 3 Queue 1 structuring and scoring."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCORING_VERSION = "phase3-deterministic-v1"
FAMILY_CONFIG_PATH = Path(__file__).with_name("data") / "cv_families.json"
TRUTH_BANK_ROOT = Path(__file__).with_name("data") / "truth_banks"
SKILL_TERMS = (
    "systemverilog", "verilog", "vhdl", "rtl", "asic", "fpga", "uvm", "python",
    "c++", "c", "linux", "embedded", "firmware", "cuda", "gpu", "cpu", "architecture",
    "backend", "distributed systems", "sql", "aws", "docker", "kubernetes",
)


class ScoringConfigurationError(ValueError):
    """Raised when a configured CV family or truth bank is invalid."""


@dataclass(frozen=True)
class ScoringResult:
    structured_jd: dict[str, Any]
    selection: dict[str, Any]
    block_scores: list[dict[str, Any]]
    section_scores: dict[str, Any]
    overall_score: int
    recommendation: str
    role_family: str
    reason: str
    strengths: list[str]
    gaps: list[str]
    hard_blockers: list[str]
    score_breakdown: dict[str, Any]


def load_cv_families(path: Path = FAMILY_CONFIG_PATH) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    families = data.get("families")
    if not isinstance(families, list) or not families:
        raise ScoringConfigurationError("CV family configuration must contain families")
    required = {"id", "display_name", "truth_bank_path", "enabled", "target_role_patterns"}
    for family in families:
        if not isinstance(family, dict) or not required.issubset(family):
            raise ScoringConfigurationError("CV family configuration is missing required fields")
    return families


def load_truth_bank(family: dict[str, Any], root: Path = TRUTH_BANK_ROOT) -> dict[str, Any]:
    path = root / str(family["truth_bank_path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_truth_bank(data, expected_family=str(family["id"]))
    return data


def validate_truth_bank(data: dict[str, Any], *, expected_family: str) -> None:
    if data.get("family_id") != expected_family or not data.get("version"):
        raise ScoringConfigurationError("truth bank family or version is invalid")
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ScoringConfigurationError("truth bank requires blocks")
    ids: set[str] = set()
    for block in blocks:
        required = {"id", "type", "name", "canonical_text", "technologies", "domains", "provenance"}
        if not isinstance(block, dict) or not required.issubset(block):
            raise ScoringConfigurationError("truth bank block is missing required fields")
        if block["id"] in ids or block["type"] not in {"experience", "project"}:
            raise ScoringConfigurationError("truth bank block ID or type is invalid")
        ids.add(str(block["id"]))


def structure_jd(job: dict[str, Any]) -> dict[str, Any]:
    text = str(job.get("jd_text") or "")
    lowered = text.lower()
    skills = [term for term in SKILL_TERMS if term in lowered]
    role_family = classify_role_family(str(job.get("title") or ""), lowered)
    must_have = _requirements_after(text, ("requirements", "qualifications", "what we need to see"))
    nice_to_have = _requirements_after(text, ("preferred", "nice to have", "bonus"))
    blockers = _hard_blockers(lowered)
    return {
        "company": job.get("company"),
        "title": job.get("title"),
        "location": job.get("location"),
        "employment_type": "full_time" if "full time" in lowered else None,
        "seniority": seniority_from_text(str(job.get("title") or "") + " " + text),
        "role_family_candidates": [role_family],
        "responsibilities": _sentences_after(
            text, ("responsibilities", "what you'll do", "you will")
        ),
        "must_have_requirements": must_have,
        "nice_to_have_requirements": nice_to_have,
        "skills": skills,
        "technologies": skills,
        "domains": [
            term for term in ("semiconductor", "automotive", "cloud", "ai") if term in lowered
        ],
        "education_requirements": ["degree"]
        if "degree" in lowered or "bs " in lowered
        else [],
        "work_authorization_constraints": blockers,
        "location_constraints": [job["location"]] if job.get("location") else [],
        "keywords": sorted(set(skills + [role_family.lower()])),
        "schema_version": "phase3-jd-v1",
    }


def classify_role_family(title: str, text: str) -> str:
    value = f"{title} {text}".lower()
    if any(term in value for term in ("rtl", "asic", "systemverilog", "verilog", "fpga")):
        return "RTL / ASIC Design"
    if any(term in value for term in ("gpu", "cpu", "accelerator", "microarchitecture")):
        return "CPU / GPU Architecture"
    if any(term in value for term in ("embedded", "firmware", "microcontroller")):
        return "Embedded Firmware"
    return "Software Engineering"


def select_cv_family(
    structured: dict[str, Any], families: list[dict[str, Any]]
) -> dict[str, Any]:
    evidence = " ".join(
        str(item)
        for item in (structured["title"], structured["skills"], structured["domains"])
    ).lower()
    ranked: list[tuple[int, dict[str, Any], list[str]]] = []
    for family in families:
        if not family["enabled"]:
            continue
        matches = [
            term for term in family["target_role_patterns"] if term.lower() in evidence
        ]
        ranked.append((len(matches), family, matches))
    ranked.sort(key=lambda item: (item[0], item[1]["id"]), reverse=True)
    if not ranked or ranked[0][0] == 0:
        raise ScoringConfigurationError("no enabled CV family has supporting evidence")
    score, primary, matches = ranked[0]
    secondary = (
        ranked[1][1]["id"] if len(ranked) > 1 and ranked[1][0] == score else None
    )
    confidence = (
        "high" if score >= 3 and not secondary else "medium" if score >= 2 else "low"
    )
    return {
        "primary_family": primary["id"],
        "secondary_family": secondary,
        "confidence": confidence,
        "reason": f"Matched role evidence: {', '.join(matches)}.",
        "evidence": matches,
        "selector_version": SCORING_VERSION,
        "manual_override": None,
    }


def score_job(
    job: dict[str, Any], *, families_path: Path = FAMILY_CONFIG_PATH
) -> ScoringResult:
    structured = structure_jd(job)
    families = load_cv_families(families_path)
    selection = select_cv_family(structured, families)
    family = next(item for item in families if item["id"] == selection["primary_family"])
    bank = load_truth_bank(family, families_path.parent / "truth_banks")
    blocks = [score_block(block, structured) for block in bank["blocks"]]
    sections = section_scores(blocks, structured)
    return overall_score(structured, selection, blocks, sections)


def score_block(block: dict[str, Any], structured: dict[str, Any]) -> dict[str, Any]:
    job_terms = set(structured["skills"] + structured["domains"] + structured["keywords"])
    block_terms = {
        str(item).lower() for item in block["technologies"] + block["domains"]
    }
    matched = sorted(job_terms.intersection(block_terms))
    coverage = round(100 * len(matched) / max(1, len(job_terms)))
    technical = min(100, 35 + coverage)
    domain = 90 if set(structured["domains"]).intersection(block["domains"]) else 55
    responsibility = 75 if matched else 35
    evidence = 90 if block.get("provenance") else 40
    seniority = 75 if structured["seniority"] != "senior" else 55
    recency = int(block.get("recency", 70))
    impressiveness = int(block.get("impressiveness", 70))
    risk = 10 if matched else 30
    aggregate = round(
        0.22 * technical
        + 0.18 * coverage
        + 0.16 * responsibility
        + 0.14 * domain
        + 0.1 * evidence
        + 0.08 * seniority
        + 0.06 * recency
        + 0.06 * impressiveness
        - 0.1 * risk
    )
    return {
        "block_id": block["id"],
        "block_type": block["type"],
        "block_name": block["name"],
        "technical_match": technical,
        "keyword_match": coverage,
        "responsibility_match": responsibility,
        "evidence_strength": evidence,
        "seniority_fit": seniority,
        "recency": recency,
        "impressiveness": impressiveness,
        "domain_match": domain,
        "risk_of_overclaim": risk,
        "aggregate_score": max(0, min(100, aggregate)),
        "matched_requirements": matched,
        "unmatched_requirements": sorted(job_terms - block_terms),
        "reason": f"Matched: {', '.join(matched) or 'no direct terms'}.",
        "scoring_version": SCORING_VERSION,
    }


def section_scores(blocks: list[dict[str, Any]], structured: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for section, block_type in (("experience", "experience"), ("projects", "project")):
        relevant = sorted(
            (item for item in blocks if item["block_type"] == block_type),
            key=lambda item: item["aggregate_score"],
            reverse=True,
        )[:3]
        values = [item["aggregate_score"] for item in relevant]
        score = (
            0
            if not values
            else round(0.5 * values[0] + 0.3 * sum(values) / len(values) + 0.2 * 75)
        )
        result[section] = {
            "score": min(100, score),
            "top_block_ids": [item["block_id"] for item in relevant],
        }
    result["recommended_section_order"] = (
        ["projects", "experience"] if result["projects"]["score"] > result["experience"]["score"]
        else ["experience", "projects"]
    )
    return result


def overall_score(
    structured: dict[str, Any],
    selection: dict[str, Any],
    blocks: list[dict[str, Any]],
    sections: dict[str, Any],
) -> ScoringResult:
    top = sorted((item["aggregate_score"] for item in blocks), reverse=True)[:3]
    top_average = sum(top) / max(1, len(top))
    must_have = 100 if structured["must_have_requirements"] else 70
    skills = min(100, 35 + 10 * len(structured["skills"]))
    domain = 85 if structured["domains"] else 60
    evidence = round(
        sum(item["evidence_strength"] for item in blocks) / max(1, len(blocks))
    )
    role_fit = {"high": 90, "medium": 75, "low": 60}[selection["confidence"]]
    blockers = structured["work_authorization_constraints"]
    blocker_penalty = 35 if blockers else 0
    score = round(
        0.25 * role_fit
        + 0.25 * must_have
        + 0.2 * top_average
        + 0.1 * skills
        + 0.1 * domain
        + 0.1 * evidence
        - blocker_penalty
    )
    score = max(0, min(100, score))
    recommendation = (
        "Strong apply"
        if score >= 85
        else "Apply" if score >= 75 else "Consider" if score >= 65 else "Low priority"
    )
    if blockers and recommendation in {"Strong apply", "Apply"}:
        recommendation = "Consider"
    strengths = [
        f"Strong {item['block_name']} evidence"
        for item in sorted(blocks, key=lambda item: item["aggregate_score"], reverse=True)[:2]
    ]
    gaps = [] if must_have == 100 else ["Requirements were not clearly structured from the JD."]
    if blockers:
        gaps.extend(blockers)
    reason = (
        f"{selection['primary_family']} matched {len(selection['evidence'])} role signals."
    )
    breakdown = {
        "role_family_fit": role_fit,
        "must_have_coverage": must_have,
        "top_block_average": round(top_average),
        "skills_match": skills,
        "domain_match": domain,
        "evidence_strength": evidence,
        "hard_blocker_penalty": blocker_penalty,
        "formula_version": SCORING_VERSION,
    }
    return ScoringResult(
        structured, selection, blocks, sections, score, recommendation,
        classify_role_family(str(structured["title"] or ""), " ".join(structured["keywords"])),
        reason, strengths, gaps, blockers, breakdown,
    )


def seniority_from_text(value: str) -> str:
    lowered = value.lower()
    if any(term in lowered for term in ("senior", "staff", "principal", "lead")):
        return "senior"
    if any(term in lowered for term in ("new grad", "graduate", "intern", "junior")):
        return "early_career"
    return "mid"


def _requirements_after(text: str, headers: tuple[str, ...]) -> list[str]:
    sentences = _sentences_after(text, headers)
    return [item for item in sentences if item][:6]


def _sentences_after(text: str, headers: tuple[str, ...]) -> list[str]:
    lines = [line.strip(" -*") for line in text.splitlines() if line.strip()]
    return [line for line in lines if any(header in line.lower() for header in headers)][:6]


def _hard_blockers(lowered: str) -> list[str]:
    blockers: list[str] = []
    if re.search(r"(?:u\.?s\.?|united states) citizen", lowered):
        blockers.append("US citizenship requirement")
    if "security clearance" in lowered or "active clearance" in lowered:
        blockers.append("Security clearance requirement")
    return blockers
