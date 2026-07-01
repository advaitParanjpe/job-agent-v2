"""Bounded one-block project tailoring for approved master CV packets."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobagent_v2.family_classifier import CLASSIFIER_VERSION, FAMILY_IDS
from jobagent_v2.master_cvs import MasterCVValidationError, pdf_page_count
from jobagent_v2.packets import PacketGenerationError, compile_pdf
from jobagent_v2.project_blocks import (
    PROJECT_BLOCK_REGISTRY_PATH,
    ProjectBlockRegistryError,
    extract_master_project_blocks,
    load_project_block_registry,
    validate_tailoring_decision,
)
from jobagent_v2.requirements import (
    counterfactual_gain,
    extract_requirements,
    score_project_portfolio,
)


TAILORING_POLICY_PATH = Path(__file__).with_name("data") / "tailoring_policy.json"
TAILORING_POLICY_VERSION = "phase-d-one-block-tailoring-v1"
TAILORING_AUDIT_VERSION = "phase-d-tailoring-audit-v1"
TAILORING_STATUSES = {
    "master_unchanged",
    "tailored",
    "review_required",
    "fallback_to_master",
    "tailoring_rejected",
}


@dataclass(frozen=True)
class TailoringResult:
    decision: dict[str, Any]
    tex_path: Path | None
    pdf_path: Path | None
    page_count: int | None
    compile_log: str
    used_tailored_output: bool


class TailoringError(ValueError):
    """Raised when a tailoring decision or artifact violates policy."""


def load_tailoring_policy(path: Path | str = TAILORING_POLICY_PATH) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("policy_version") != TAILORING_POLICY_VERSION:
        raise TailoringError("tailoring policy version mismatch")
    weights = data.get("score_weights")
    if not isinstance(weights, dict) or set(weights) != {
        "responsibility", "domain", "technology", "project", "family_evidence",
    }:
        raise TailoringError("tailoring score weights are invalid")
    total = sum(float(value) for value in weights.values())
    if abs(total - 1.0) > 0.001:
        raise TailoringError("tailoring score weights must sum to 1.0")
    for key in (
        "minimum_replacement_gain", "clear_match_tailoring_gain",
        "dominant_family_margin",
    ):
        if not isinstance(data.get(key), (int, float)):
            raise TailoringError(f"tailoring policy {key} must be numeric")
    return data


def evaluate_tailoring(
    *,
    packet_id: str,
    job: dict[str, Any],
    output_dir: Path,
    master_tex_path: Path | str,
    master_pdf_path: Path | str,
    registry_path: Path | str = PROJECT_BLOCK_REGISTRY_PATH,
    policy_path: Path | str = TAILORING_POLICY_PATH,
) -> TailoringResult:
    registry = load_project_block_registry(registry_path)
    policy = load_tailoring_policy(policy_path)
    base_family = str(job.get("selected_cv_family") or "")
    classification = job.get("family_classification") or {}
    if base_family not in FAMILY_IDS:
        decision = _base_decision(packet_id, job, base_family, registry, policy)
        decision.update({
            "tailoring_status": "fallback_to_master",
            "fallback_reason": "unknown_base_family",
            "reason": "Selected family is not supported for tailoring.",
        })
        return _master_result(decision)
    decision = select_tailoring_decision(
        packet_id=packet_id,
        job=job,
        base_family=base_family,
        registry=registry,
        policy=policy,
    )
    if decision["tailoring_status"] != "tailored":
        return _master_result(decision)
    candidate_dir: Path | None = None
    try:
        tex = render_tailored_tex(
            Path(master_tex_path).read_text(encoding="utf-8"),
            decision["final_order"],
            registry,
        )
        validate_tailored_tex(
            tex,
            master_tex_path=master_tex_path,
            decision=decision,
            registry=registry,
        )
        candidate_dir = output_dir / "tailored-candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate_tex = candidate_dir / "cv.tex"
        candidate_tex.write_text(tex, encoding="utf-8")
        candidate_pdf, compile_log, page_count = compile_pdf(tex, candidate_dir)
        page_count = page_count if page_count is not None else pdf_page_count(candidate_pdf)
        if page_count != 1:
            raise TailoringError(f"tailored PDF must be exactly one page; got {page_count}")
        tex_path = output_dir / "cv.tex"
        pdf_path = output_dir / "cv.pdf"
        tex_path.write_text(tex, encoding="utf-8")
        shutil.copy2(candidate_pdf, pdf_path)
        shutil.rmtree(candidate_dir, ignore_errors=True)
        decision["tailoring_status"] = "tailored"
        decision["fallback_reason"] = None
        return TailoringResult(decision, tex_path, pdf_path, page_count, compile_log, True)
    except (
        OSError,
        PacketGenerationError,
        ProjectBlockRegistryError,
        TailoringError,
        MasterCVValidationError,
    ) as error:
        if candidate_dir is not None:
            shutil.rmtree(candidate_dir, ignore_errors=True)
        decision["tailoring_status"] = "fallback_to_master"
        decision["fallback_reason"] = str(error)
        decision["reason"] = f"Tailored candidate rejected; copied approved master. {error}"
        return _master_result(decision)


def select_tailoring_decision(
    *,
    packet_id: str,
    job: dict[str, Any],
    base_family: str,
    registry: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    decision = _base_decision(packet_id, job, base_family, registry, policy)
    classification = job.get("family_classification") or {}
    class_decision = str(classification.get("decision") or "low_confidence")
    base_blocks = list(registry["base_project_order"][base_family])
    block_scores = score_project_blocks(job, registry, policy)
    requirement_analysis = extract_requirements(job)
    portfolio_scores = score_project_portfolio(
        base_family=base_family,
        registry=registry,
        requirement_analysis=requirement_analysis,
    )
    decision["requirement_analysis"] = requirement_analysis
    decision["project_portfolio"] = portfolio_scores
    decision["base_block_scores"] = [
        _score_payload(block_id, block_scores[block_id]) for block_id in base_blocks
    ]
    candidates = compatible_candidates(base_family, registry, portfolio_scores)
    decision["candidate_blocks"] = [
        {
            **_score_payload(item["inserted"], block_scores[item["inserted"]]),
            "compatible": True,
            "removed_block": item["removed"],
            "requires_review": item["requires_review"],
            "compatibility_reason": item["reason"],
            "shortlist_reason": item.get("shortlist_reason"),
        }
        for item in candidates
    ]
    if class_decision == "low_confidence":
        decision.update({
            "tailoring_status": "review_required",
            "requires_review": True,
            "reason": "Low-confidence family classification; approved master used unchanged.",
        })
        return decision
    best = best_substitution(
        base_blocks, candidates, block_scores, registry, policy, portfolio_scores
    )
    if best is None:
        review_candidate = _reviewable_requirement_candidate(candidates)
        status = (
            "review_required"
            if class_decision == "close_match" or review_candidate is not None
            else "master_unchanged"
        )
        decision.update({
            "tailoring_status": status,
            "requires_review": (
                class_decision == "close_match"
                or review_candidate is not None
                or bool(decision["requires_review"])
            ),
            "reason": (
                "A high-specificity requirement has a reviewable approved project option."
                if review_candidate is not None
                else "No compatible replacement exceeded the configured relevance gain."
            ),
        })
        return decision
    gain_threshold = float(policy["minimum_replacement_gain"])
    if class_decision == "clear_match":
        scores = classification.get("family_scores") or {}
        ranked = sorted(
            (float(scores.get(family, 0.0)), family) for family in FAMILY_IDS
        )
        margin = ranked[-1][0] - ranked[-2][0]
        gain_threshold = max(gain_threshold, float(policy["clear_match_tailoring_gain"]))
        if margin < float(policy["dominant_family_margin"]):
            decision.update({
                "tailoring_status": "master_unchanged",
                "reason": "Clear match was not dominant enough for automatic tailoring.",
            })
            return decision
    if best["gain"] < gain_threshold:
        review_candidate = _reviewable_requirement_candidate(candidates)
        status = (
            "review_required"
            if class_decision == "close_match" or review_candidate is not None
            else "master_unchanged"
        )
        decision.update({
            "tailoring_status": status,
            "requires_review": (
                class_decision == "close_match"
                or review_candidate is not None
                or bool(decision["requires_review"])
            ),
            "replacement_gain": round(best["gain"], 4),
            "reason": (
                "A high-specificity requirement has a reviewable approved project option, "
                "but automatic substitution did not clear the gain threshold."
                if review_candidate is not None
                else "Best compatible replacement was below the configured gain threshold."
            ),
        })
        return decision
    final = [block for block in base_blocks if block != best["removed"]] + [best["inserted"]]
    if bool(policy.get("allow_reordering", True)):
        final = ordered_blocks(final, block_scores, registry)
    decision.update({
        "removed_block": best["removed"],
        "inserted_block": best["inserted"],
        "final_order": final,
        "replacement_gain": round(best["gain"], 4),
        "counterfactual": counterfactual_gain(
            candidate_block_id=best["inserted"],
            removed_block_id=best["removed"],
            portfolio_scores=portfolio_scores,
        ),
        "requires_review": (
            class_decision == "close_match"
            or bool(best["requires_review"])
            or bool(decision["requires_review"])
        ),
        "tailoring_status": "tailored",
        "reason": best["reason"],
    })
    registry_decision = {
        **decision,
        "policy_version": registry["policy_version"],
    }
    validate_tailoring_decision(registry_decision, registry)
    return decision


def score_project_blocks(
    job: dict[str, Any],
    registry: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    structured = job.get("structured_jd") or {}
    classification = job.get("family_classification") or {}
    evidence_phrases = [
        str(item.get("phrase"))
        for item in classification.get("rule_evidence", [])
        if item.get("polarity") == "positive" and item.get("phrase")
    ]
    sections = {
        "responsibility": " ".join([
            str(job.get("title") or ""),
            *[str(value) for value in structured.get("responsibilities", [])],
            str(job.get("jd_text") or job.get("raw_visible_text") or ""),
        ]),
        "domain": " ".join([
            *[str(value) for value in structured.get("domains", [])],
            str(job.get("jd_text") or job.get("raw_visible_text") or ""),
        ]),
        "technology": " ".join([
            *[str(value) for value in structured.get("skills", [])],
            *[str(value) for value in structured.get("technologies", [])],
            *[str(value) for value in structured.get("keywords", [])],
            str(job.get("jd_text") or job.get("raw_visible_text") or ""),
        ]),
        "family_evidence": " ".join(evidence_phrases),
    }
    weights = {key: float(value) for key, value in policy["score_weights"].items()}
    scores: dict[str, dict[str, Any]] = {}
    for block in registry["blocks"]:
        block_terms = {
            "responsibility": _block_text(block),
            "domain": " ".join(str(value) for value in block.get("tags", [])),
            "technology": " ".join([
                str(block.get("subtitle") or ""),
                *[str(value) for value in block.get("tags", [])],
                _block_text(block),
            ]),
            "project": " ".join([
                str(block.get("display_name") or ""),
                str(block.get("heading") or ""),
                str(block.get("project_id") or ""),
            ]),
            "family_evidence": " ".join(str(value) for value in block.get("tags", [])),
        }
        components = {
            "responsibility": phrase_overlap(
                sections["responsibility"], block_terms["responsibility"]
            ),
            "domain": phrase_overlap(sections["domain"], block_terms["domain"]),
            "technology": phrase_overlap(sections["technology"], block_terms["technology"]),
            "project": phrase_overlap(
                " ".join([sections["responsibility"], sections["technology"]]),
                block_terms["project"],
            ),
            "family_evidence": phrase_overlap(
                sections["family_evidence"], block_terms["family_evidence"]
            ),
        }
        total = sum(weights[key] * components[key] for key in weights)
        scores[str(block["block_id"])] = {
            "score": round(total, 4),
            "components": {key: round(value, 4) for key, value in components.items()},
            "evidence": score_evidence(block, sections),
        }
    return scores


def compatible_candidates(
    base_family: str,
    registry: dict[str, Any],
    portfolio_scores: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    rules = registry.get("compatibility", {}).get(base_family, {})
    shortlist = set((portfolio_scores or {}).get("shortlist") or [])
    for removed, entries in rules.items():
        for entry in entries:
            inserted = str(entry["insert_block_id"])
            result.append({
                "removed": str(removed),
                "inserted": inserted,
                "requires_review": bool(entry["requires_review"]),
                "reason": str(entry["reason"]),
                "shortlist_reason": (
                    "requirement_aware_shortlist" if inserted in shortlist else None
                ),
            })
    return result


def best_substitution(
    base_blocks: list[str],
    candidates: list[dict[str, Any]],
    block_scores: dict[str, dict[str, Any]],
    registry: dict[str, Any],
    policy: dict[str, Any],
    portfolio_scores: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    by_id = {str(block["block_id"]): block for block in registry["blocks"]}
    portfolio_by_id = {
        item["block_id"]: item
        for item in (portfolio_scores or {}).get("candidate_scores", [])
    }
    options = []
    for candidate in candidates:
        removed = candidate["removed"]
        inserted = candidate["inserted"]
        if removed not in base_blocks or inserted in base_blocks:
            continue
        inserted_project = by_id[inserted]["project_id"]
        if not bool(policy.get("allow_duplicate_projects", False)):
            final_ids = [block for block in base_blocks if block != removed]
            if inserted_project in {by_id[block]["project_id"] for block in final_ids}:
                continue
        old_gain = float(block_scores[inserted]["score"]) - float(block_scores[removed]["score"])
        portfolio_gain = (
            float(portfolio_by_id[inserted]["score"]) - float(portfolio_by_id[removed]["score"])
            if inserted in portfolio_by_id and removed in portfolio_by_id else old_gain
        )
        gain = max(old_gain, portfolio_gain)
        options.append({
            **candidate,
            "gain": gain,
            "legacy_gain": round(old_gain, 4),
            "portfolio_gain": round(portfolio_gain, 4),
            "reason": (
                f"{inserted} improves approved project requirement coverage over {removed} "
                f"by {gain:.2f}."
            ),
        })
    if not options:
        return None
    options.sort(key=lambda item: (-item["gain"], item["removed"], item["inserted"]))
    return options[0]


def ordered_blocks(
    block_ids: list[str],
    block_scores: dict[str, dict[str, Any]],
    registry: dict[str, Any],
) -> list[str]:
    stable_order = {
        block_id: index
        for order in registry["base_project_order"].values()
        for index, block_id in enumerate(order)
    }
    return sorted(
        block_ids,
        key=lambda block_id: (
            -float(block_scores[block_id]["score"]),
            stable_order.get(block_id, 999),
            block_id,
        ),
    )


def _reviewable_requirement_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate.get("shortlist_reason") and candidate.get("requires_review"):
            return candidate
    return None


def render_tailored_tex(master_tex: str, final_order: list[str], registry: dict[str, Any]) -> str:
    start = re.search(r"\\section\*\{Projects\}", master_tex)
    end = re.search(r"\\section\*\{Skills\}", master_tex)
    if start is None or end is None or start.end() >= end.start():
        raise TailoringError("master TeX does not have a replaceable Projects section")
    raw_by_id = raw_tex_by_block_id(registry)
    fragments = []
    for block_id in final_order:
        fragment = raw_by_id.get(block_id)
        if fragment is None:
            raise TailoringError(f"unknown project block in final order: {block_id}")
        fragments.append(fragment)
    projects = "\\section*{Projects}\n" + "\n".join(fragments) + "\n\\vspace{-0.5em}\n\n"
    return master_tex[:start.start()] + projects + master_tex[end.start():]


def validate_tailored_tex(
    tex: str,
    *,
    master_tex_path: Path | str,
    decision: dict[str, Any],
    registry: dict[str, Any],
) -> None:
    if any(token in tex for token in ("<<", ">>", "@@")):
        raise TailoringError("tailored TeX contains a dynamic placeholder")
    master = Path(master_tex_path).read_text(encoding="utf-8")
    before_master, after_master = _immutable_parts(master)
    before_tex, after_tex = _immutable_parts(tex)
    if before_master != before_tex or after_master != after_tex:
        raise TailoringError("tailored TeX changed immutable non-project content")
    raw_by_id = raw_tex_by_block_id(registry)
    section = _project_section(tex)
    for block_id in decision["final_order"]:
        fragment = raw_by_id[block_id]
        if fragment not in section:
            raise TailoringError(f"approved project fragment missing from tailored TeX: {block_id}")
    found = len(re.findall(r"\\resumeProjectHeading", section))
    if found != len(decision["final_order"]):
        raise TailoringError("tailored TeX has unexpected project slot count")


def raw_tex_by_block_id(registry: dict[str, Any]) -> dict[str, str]:
    extracted = {
        (block.source_master, block.heading): block.raw_tex
        for block in extract_master_project_blocks()
    }
    result = {}
    for block in registry["blocks"]:
        key = (str(block["source_master"]), str(block["heading"]))
        if key not in extracted:
            raise TailoringError(f"registered block source is missing: {block['block_id']}")
        result[str(block["block_id"])] = extracted[key]
    return result


def phrase_overlap(job_text: str, block_text: str) -> float:
    job_terms = meaningful_terms(job_text)
    block_terms = meaningful_terms(block_text)
    if not job_terms or not block_terms:
        return 0.0
    matched = job_terms & block_terms
    return min(1.0, len(matched) / max(3, min(len(block_terms), 12)))


def score_evidence(block: dict[str, Any], sections: dict[str, str]) -> list[dict[str, str]]:
    evidence = []
    terms = meaningful_terms(_block_text(block) + " " + " ".join(block.get("tags", [])))
    for section, text in sections.items():
        matched = sorted(meaningful_terms(text) & terms)[:8]
        if matched:
            evidence.append({"section": section, "matched_terms": ", ".join(matched)})
    return evidence


def meaningful_terms(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9+/#.-]*", value.casefold())
    stop = {
        "and", "or", "the", "with", "for", "to", "of", "in", "on", "a", "an", "by",
        "using", "built", "designed", "implemented", "developed", "you", "will",
        "role", "work", "team", "experience", "requirements", "responsibilities",
    }
    return {word for word in words if len(word) >= 3 and word not in stop}


def _base_decision(
    packet_id: str,
    job: dict[str, Any],
    base_family: str,
    registry: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    classification = job.get("family_classification") or {}
    base_blocks = list(registry.get("base_project_order", {}).get(base_family, []))
    return {
        "audit_version": TAILORING_AUDIT_VERSION,
        "job_id": str(job.get("id") or job.get("job_id") or ""),
        "packet_id": packet_id,
        "base_family": base_family,
        "classification_decision": classification.get("decision"),
        "base_blocks": base_blocks,
        "candidate_blocks": [],
        "removed_block": None,
        "inserted_block": None,
        "final_order": base_blocks,
        "replacement_gain": 0.0,
        "reason": "Approved master used unchanged.",
        "job_evidence": _job_evidence(job),
        "requires_review": bool(classification.get("requires_review")),
        "tailoring_status": "master_unchanged",
        "fallback_reason": None,
        "policy_version": str(policy["policy_version"]),
        "registry_version": str(registry["schema_version"]),
        "project_registry_policy_version": str(registry["policy_version"]),
        "classifier_version": str(
            classification.get("classifier_version") or CLASSIFIER_VERSION
        ),
    }


def _master_result(decision: dict[str, Any]) -> TailoringResult:
    return TailoringResult(decision, None, None, None, "approved master fallback", False)


def _score_payload(block_id: str, score: dict[str, Any]) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "score": score["score"],
        "components": score["components"],
        "evidence": score["evidence"],
    }


def _block_text(block: dict[str, Any]) -> str:
    return " ".join([
        str(block.get("heading") or ""),
        str(block.get("subtitle") or ""),
        *[str(value) for value in block.get("bullets", [])],
    ])


def _job_evidence(job: dict[str, Any]) -> list[dict[str, Any]]:
    structured = job.get("structured_jd") or {}
    evidence = []
    for key in ("responsibilities", "must_have_requirements", "nice_to_have_requirements"):
        values = structured.get(key)
        if isinstance(values, list):
            evidence.extend({"source": key, "text": str(value)} for value in values[:5])
    for item in (job.get("family_classification") or {}).get("rule_evidence", [])[:12]:
        evidence.append({
            "source": "family_classifier",
            "family": item.get("family"),
            "section": item.get("section"),
            "phrase": item.get("phrase"),
        })
    return evidence


def _immutable_parts(tex: str) -> tuple[str, str]:
    start = re.search(r"\\section\*\{Projects\}", tex)
    end = re.search(r"\\section\*\{Skills\}", tex)
    if start is None or end is None or start.end() >= end.start():
        raise TailoringError("TeX does not have Projects followed by Skills")
    return tex[:start.start()], tex[end.start():]


def _project_section(tex: str) -> str:
    start = re.search(r"\\section\*\{Projects\}", tex)
    end = re.search(r"\\section\*\{Skills\}", tex)
    if start is None or end is None or start.end() >= end.start():
        raise TailoringError("TeX does not have Projects followed by Skills")
    return tex[start.start():end.start()]
