"""Requirement extraction and cross-family project portfolio scoring."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable


REQUIREMENT_ANALYSIS_VERSION = "requirement-analysis-v1"
SEMANTIC_REQUIREMENT_SCHEMA_VERSION = "semantic-requirements-v1"
FUSED_REQUIREMENT_VERSION = "requirement-fusion-v1"
PORTFOLIO_POLICY_VERSION = "portfolio-selection-v1"

SECTION_WEIGHTS = {
    "title": 0.95,
    "responsibilities": 0.9,
    "must_have_requirements": 1.0,
    "nice_to_have_requirements": 0.72,
    "skills": 0.68,
    "technologies": 0.65,
    "domains": 0.62,
    "keywords": 0.55,
    "jd_text": 0.58,
}

CAPABILITY_ALIASES: dict[str, dict[str, Any]] = {
    "npu": {
        "capabilities": ["npu", "ml_accelerator", "hardware_acceleration"],
        "specificity": 0.98,
        "differentiation": 0.95,
        "aliases": ["npu", "npus", "neural processing unit", "neural processing units"],
    },
    "ml_accelerator": {
        "capabilities": ["ml_accelerator", "hardware_acceleration", "edge_ai"],
        "specificity": 0.94,
        "differentiation": 0.9,
        "aliases": [
            "ml accelerator", "machine learning accelerator", "ai accelerator",
            "accelerator architecture", "hardware accelerator",
        ],
    },
    "quantization": {
        "capabilities": ["quantization", "model_optimization", "edge_ai"],
        "specificity": 0.88,
        "differentiation": 0.78,
        "aliases": ["quantization", "quantized", "int8", "int4", "model compression"],
    },
    "edge_ai": {
        "capabilities": ["edge_ai", "on_device_inference", "deployment"],
        "specificity": 0.84,
        "differentiation": 0.76,
        "aliases": ["edge ai", "edge ml", "on-device ai", "on device ai"],
    },
    "on_device_inference": {
        "capabilities": ["on_device_inference", "deployment", "performance_optimization"],
        "specificity": 0.82,
        "differentiation": 0.72,
        "aliases": ["on-device inference", "on device inference", "embedded inference"],
    },
    "hardware_aware_optimization": {
        "capabilities": [
            "hardware_acceleration", "hardware_aware_optimization",
            "performance_optimization",
        ],
        "specificity": 0.82,
        "differentiation": 0.76,
        "aliases": [
            "hardware-aware", "hardware aware", "hardware core optimization",
            "performance optimization", "low latency", "throughput optimization",
        ],
    },
    "machine_learning": {
        "capabilities": ["machine_learning", "model_training"],
        "specificity": 0.62,
        "differentiation": 0.48,
        "aliases": ["machine learning", "deep learning", "model training", "train models"],
    },
    "pytorch": {
        "capabilities": ["pytorch", "machine_learning"],
        "specificity": 0.7,
        "differentiation": 0.48,
        "aliases": ["pytorch", "torch"],
    },
    "compiler_runtime": {
        "capabilities": ["compiler_runtime", "software_engineering"],
        "specificity": 0.82,
        "differentiation": 0.7,
        "aliases": ["compiler", "runtime", "code generation", "kernel optimization"],
    },
    "rtl": {
        "capabilities": ["rtl", "digital_design", "computer_architecture"],
        "specificity": 0.9,
        "differentiation": 0.82,
        "aliases": ["rtl", "systemverilog", "microarchitecture", "datapath"],
    },
    "verification": {
        "capabilities": ["verification", "uvm"],
        "specificity": 0.86,
        "differentiation": 0.74,
        "aliases": ["uvm", "scoreboard", "functional coverage", "regression triage"],
    },
    "python": {
        "capabilities": ["python", "software_engineering"],
        "specificity": 0.42,
        "differentiation": 0.3,
        "aliases": ["python"],
    },
    "cpp": {
        "capabilities": ["cpp", "software_engineering"],
        "specificity": 0.48,
        "differentiation": 0.34,
        "aliases": ["c++", "cpp"],
    },
}

GENERIC_ALIASES = {
    "communication", "teamwork", "collaboration", "problem solving", "problem-solving",
}

APPROVED_CAPABILITIES = sorted({
    "general_collaboration",
    *(cap for spec in CAPABILITY_ALIASES.values() for cap in spec["capabilities"]),
    "embedded_systems",
    "digital_ic",
    "software_engineering",
    "edge_ai",
    "hardware_acceleration",
    "compiler_runtime",
    "on_device_inference",
    "performance_optimization",
})


@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    text: str
    normalized_capabilities: list[str]
    source_section: str
    explicitness: float
    importance: float
    specificity: float
    differentiation_value: float
    required_or_preferred: str
    evidence_quote: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "text": self.text,
            "normalized_capabilities": self.normalized_capabilities,
            "source_section": self.source_section,
            "explicitness": self.explicitness,
            "importance": self.importance,
            "specificity": self.specificity,
            "differentiation_value": self.differentiation_value,
            "required_or_preferred": self.required_or_preferred,
            "evidence_quote": self.evidence_quote,
        }


def extract_requirements(
    job: dict[str, Any],
    *,
    semantic_provider: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    semantic_enabled: bool | None = None,
) -> dict[str, Any]:
    structured = job.get("structured_jd") or {}
    candidates = _section_candidates(job, structured)
    found: dict[tuple[str, str], Requirement] = {}
    counter = 1
    for section, text in candidates:
        for key, spec in CAPABILITY_ALIASES.items():
            quote = _first_alias_match(text, spec["aliases"])
            if quote is None:
                continue
            caps = list(dict.fromkeys(str(cap) for cap in spec["capabilities"]))
            specificity = float(spec["specificity"])
            differentiation = float(spec["differentiation"])
            explicitness = 1.0 if len(quote.split()) > 1 or quote.isupper() else 0.86
            required = _required_or_preferred(section, text)
            section_weight = SECTION_WEIGHTS.get(section, 0.55)
            importance = min(
                1.0,
                section_weight * explicitness * specificity * differentiation
                * (1.08 if required == "required" else 1.0),
            )
            requirement = Requirement(
                requirement_id=f"req_{counter:03d}",
                text=_requirement_text(key, quote),
                normalized_capabilities=caps,
                source_section=section,
                explicitness=round(explicitness, 3),
                importance=round(importance, 3),
                specificity=round(specificity, 3),
                differentiation_value=round(differentiation, 3),
                required_or_preferred=required,
                evidence_quote=quote,
            )
            dedupe_key = (key, section)
            current = found.get(dedupe_key)
            if current is None:
                found[dedupe_key] = requirement
                counter += 1
            elif requirement.importance > current.importance:
                found[dedupe_key] = requirement
        for generic in GENERIC_ALIASES:
            quote = _first_alias_match(text, [generic])
            if quote is None:
                continue
            found.setdefault(
                ("generic", section),
                Requirement(
                    requirement_id=f"req_{counter:03d}",
                    text=f"General workplace requirement: {quote}",
                    normalized_capabilities=["general_collaboration"],
                    source_section=section,
                    explicitness=0.75,
                    importance=round(SECTION_WEIGHTS.get(section, 0.55) * 0.18, 3),
                    specificity=0.18,
                    differentiation_value=0.12,
                    required_or_preferred=_required_or_preferred(section, text),
                    evidence_quote=quote,
                ),
            )
    deterministic = sorted(found.values(), key=lambda item: (-item.importance, item.requirement_id))
    semantic = extract_semantic_requirements(
        job,
        deterministic_requirements=[item.to_dict() for item in deterministic],
        provider=semantic_provider,
        enabled=semantic_enabled,
    )
    fused = fuse_requirements(
        [item.to_dict() for item in deterministic],
        semantic.get("accepted_requirements", []),
    )
    requirements = [_requirement_compat(item) for item in fused]
    role_dimensions = _role_dimensions_from_dicts(requirements)
    return {
        "analysis_version": REQUIREMENT_ANALYSIS_VERSION,
        "fusion_version": FUSED_REQUIREMENT_VERSION,
        "semantic_status": semantic["status"],
        "semantic_metadata": semantic["metadata"],
        "deterministic_requirements": [item.to_dict() for item in deterministic],
        "semantic_requirements": semantic,
        "requirements": requirements,
        "role_dimensions": role_dimensions,
    }


def extract_semantic_requirements(
    job: dict[str, Any],
    *,
    deterministic_requirements: list[dict[str, Any]],
    provider: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    enabled = (
        os.getenv("JOBAGENT_SEMANTIC_REQUIREMENTS_ENABLED", "false").lower() == "true"
        if enabled is None
        else enabled
    )
    metadata = {
        "enabled": bool(enabled),
        "attempted": False,
        "provider": "openai",
        "model": os.getenv("JOBAGENT_LLM_MODEL", "gpt-4o-mini"),
        "latency_ms": None,
        "semantic_requirement_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "failure_code": None,
        "fallback_used": True,
        "configuration_version": SEMANTIC_REQUIREMENT_SCHEMA_VERSION,
    }
    if not enabled:
        return _semantic_payload("disabled", metadata, [], [])
    if provider is None:
        metadata["failure_code"] = "not_configured"
        return _semantic_payload("not_configured", metadata, [], [])
    prompt = {
        "schema_version": SEMANTIC_REQUIREMENT_SCHEMA_VERSION,
        "job": {
            "title": job.get("title"),
            "jd_text": job.get("jd_text") or job.get("raw_visible_text"),
            "structured_jd": job.get("structured_jd") or {},
        },
        "approved_capabilities": APPROVED_CAPABILITIES,
        "deterministic_requirements": deterministic_requirements,
    }
    start = perf_counter()
    metadata["attempted"] = True
    try:
        raw = provider(prompt)
        accepted, rejected = validate_semantic_requirement_response(
            raw,
            job_text=str(job.get("jd_text") or job.get("raw_visible_text") or ""),
        )
    except TimeoutError:
        metadata["failure_code"] = "timed_out"
        return _semantic_payload("timed_out", metadata, [], [])
    except (ValueError, TypeError) as error:
        metadata["failure_code"] = "response_invalid"
        metadata["failure_summary"] = str(error)[:160]
        return _semantic_payload("response_invalid", metadata, [], [])
    metadata["latency_ms"] = round((perf_counter() - start) * 1000)
    metadata["semantic_requirement_count"] = len(raw.get("requirements") or [])
    metadata["accepted_count"] = len(accepted)
    metadata["rejected_count"] = len(rejected)
    metadata["fallback_used"] = len(accepted) == 0
    status = "live_success" if accepted else "grounding_rejected"
    return _semantic_payload(status, metadata, accepted, rejected)


def validate_semantic_requirement_response(
    data: dict[str, Any],
    *,
    job_text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(data, dict) or not isinstance(data.get("requirements"), list):
        raise ValueError("semantic requirement response is missing requirements")
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    normalized_text = _normalize_grounding_text(job_text)
    for index, item in enumerate(data.get("requirements") or []):
        reason = _semantic_rejection_reason(item, normalized_text)
        if reason:
            rejected.append({"index": index, "reason": reason})
            continue
        caps = [str(cap) for cap in item["normalized_capabilities"]]
        accepted.append({
            "requirement_id": f"sem_{index + 1:03d}",
            "text": str(item["requirement_text"]).strip(),
            "normalized_capabilities": sorted(dict.fromkeys(caps)),
            "importance": round(float(item["importance"]), 3),
            "specificity": round(float(item["specificity"]), 3),
            "confidence": round(
                min(float(item["importance"]), float(item["specificity"])) * 0.78,
                3,
            ),
            "required_or_preferred": str(item.get("required_or_preferred") or "responsibility"),
            "evidence_quote": str(item["evidence_quote"]).strip(),
            "concise_reason": str(item.get("concise_reason") or "").strip(),
            "sources": ["semantic"],
            "semantic_only": True,
            "differentiation_value": round(float(item["specificity"]) * 0.75, 3),
        })
    return accepted, rejected


def fuse_requirements(
    deterministic: list[dict[str, Any]],
    semantic: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fused: list[dict[str, Any]] = []
    for item in deterministic:
        fused.append({
            **item,
            "confidence": round(min(1.0, float(item.get("importance") or 0.0) + 0.12), 3),
            "sources": ["deterministic"],
            "evidence_quotes": [item.get("evidence_quote")] if item.get("evidence_quote") else [],
            "semantic_only": False,
        })
    for sem in semantic:
        if float(sem.get("importance") or 0.0) < 0.62 or float(sem.get("specificity") or 0.0) < 0.6:
            continue
        match = _matching_requirement(fused, sem)
        if match is not None:
            match["sources"] = sorted(set(match.get("sources", [])) | {"semantic"})
            match["confidence"] = round(min(1.0, float(match.get("confidence") or 0) + 0.08), 3)
            quote = sem.get("evidence_quote")
            if quote and quote not in match.setdefault("evidence_quotes", []):
                match["evidence_quotes"].append(quote)
            match["semantic_only"] = False
            continue
        fused.append(sem)
    fused.sort(key=lambda item: (-float(item.get("importance") or 0.0), item["requirement_id"]))
    return fused


def score_project_portfolio(
    *,
    base_family: str,
    registry: dict[str, Any],
    requirement_analysis: dict[str, Any],
) -> dict[str, Any]:
    requirements = requirement_analysis.get("requirements") or []
    blocks = registry.get("blocks") or []
    scores = []
    for block in blocks:
        if base_family not in block.get("eligible_families", []):
            continue
        score = score_project(block, requirements, base_family, requirement_analysis)
        scores.append(score)
    scores.sort(key=lambda item: (-item["score"], item["block_id"]))
    shortlist = [
        item["block_id"] for item in scores
        if item["shortlist_reason"] or float(item["score"]) >= 0.2
    ]
    return {
        "policy_version": PORTFOLIO_POLICY_VERSION,
        "requirement_analysis_version": requirement_analysis.get("analysis_version"),
        "base_family": base_family,
        "candidate_scores": scores,
        "shortlist": shortlist,
    }


def score_project(
    block: dict[str, Any],
    requirements: list[dict[str, Any]],
    base_family: str,
    requirement_analysis: dict[str, Any],
) -> dict[str, Any]:
    capabilities = {
        str(key): float(value)
        for key, value in (block.get("capabilities") or {}).items()
    }
    matches = []
    coverage_total = 0.0
    specificity_total = 0.0
    differentiation_total = 0.0
    distinctive = []
    for requirement in requirements:
        overlap = [
            cap for cap in requirement.get("normalized_capabilities", [])
            if cap in capabilities
        ]
        if not overlap:
            continue
        strength = max(capabilities[cap] for cap in overlap)
        importance = float(requirement.get("importance") or 0.0)
        specificity = float(requirement.get("specificity") or 0.0)
        differentiation = float(requirement.get("differentiation_value") or 0.0)
        coverage = strength * importance
        coverage_total += coverage
        specificity_total += strength * specificity * importance
        differentiation_total += strength * differentiation * importance
        if specificity >= 0.82 and importance >= 0.55:
            distinctive.extend(overlap)
        matches.append({
            "requirement_id": requirement["requirement_id"],
            "capabilities": overlap,
            "coverage": round(min(1.0, coverage), 4),
            "reason": _match_reason(block, requirement, overlap),
            "project_evidence": block.get("evidence_terms", [])[:4],
            "evidence_quote": requirement.get("evidence_quote"),
        })
    coverage_component = _saturate(coverage_total)
    specificity_component = _saturate(specificity_total)
    differentiation_component = _saturate(differentiation_total)
    bridge_bonus = _bridge_bonus(block, requirement_analysis)
    evidence_quality = min(1.0, len(block.get("evidence_terms", [])) / 4)
    base_affinity = 1.0 if block.get("home_family", block.get("family")) == base_family else 0.45
    mismatch_penalty = 0.0 if base_family in block.get("eligible_families", []) else 0.5
    score = (
        0.35 * coverage_component
        + 0.20 * specificity_component
        + 0.10 * differentiation_component
        + 0.10 * bridge_bonus
        + 0.05 * evidence_quality
        + 0.05 * base_affinity
        - 0.15 * mismatch_penalty
    )
    shortlist_reason = None
    if distinctive and matches:
        shortlist_reason = "high_specificity_requirement"
    return {
        "block_id": block["block_id"],
        "project_id": block["project_id"],
        "display_name": block["display_name"],
        "home_family": block.get("home_family", block.get("family")),
        "score": round(max(0.0, min(1.0, score)), 4),
        "requirement_coverage": round(coverage_component, 4),
        "specificity_coverage": round(specificity_component, 4),
        "differentiation_value": round(differentiation_component, 4),
        "bridge_bonus": round(bridge_bonus, 4),
        "base_family_affinity": round(base_affinity, 4),
        "matches": matches,
        "shortlist_reason": shortlist_reason,
        "distinctive_capabilities": sorted(set(distinctive)),
    }


def counterfactual_gain(
    *,
    candidate_block_id: str,
    removed_block_id: str,
    portfolio_scores: dict[str, Any],
) -> dict[str, Any]:
    by_id = {item["block_id"]: item for item in portfolio_scores.get("candidate_scores", [])}
    candidate = by_id.get(candidate_block_id)
    removed = by_id.get(removed_block_id)
    if candidate is None:
        return {}
    removed_score = float(removed.get("score", 0.0)) if removed else 0.0
    candidate_score = float(candidate.get("score", 0.0))
    gained = sorted({
        cap for match in candidate.get("matches", []) for cap in match.get("capabilities", [])
    })
    lost = sorted({
        cap for match in (removed or {}).get("matches", []) for cap in match.get("capabilities", [])
    })
    return {
        "candidate_project": candidate_block_id,
        "replaced_project": removed_block_id,
        "coverage_gain": round(candidate_score - removed_score, 4),
        "distinctive_requirements_added": gained,
        "coverage_lost": lost,
        "net_gain": round(candidate_score - removed_score, 4),
    }


def _section_candidates(job: dict[str, Any], structured: dict[str, Any]) -> list[tuple[str, str]]:
    result = [("title", str(job.get("title") or structured.get("title") or ""))]
    for key in (
        "responsibilities", "must_have_requirements", "nice_to_have_requirements",
        "skills", "technologies", "domains", "keywords",
    ):
        values = structured.get(key)
        if isinstance(values, list):
            result.extend((key, str(value)) for value in values)
    result.append(("jd_text", str(job.get("jd_text") or job.get("raw_visible_text") or "")))
    return [(section, text) for section, text in result if text.strip()]


def _first_alias_match(text: str, aliases: list[str]) -> str | None:
    normalized = " ".join(text.split())
    for alias in sorted(aliases, key=len, reverse=True):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])"
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return normalized[match.start():match.end()]
    return None


def _required_or_preferred(section: str, text: str) -> str:
    lowered = text.casefold()
    if section == "nice_to_have_requirements" or any(
        token in lowered for token in ("preferred", "nice to have", "plus")
    ):
        return "preferred"
    return "required"


def _requirement_text(key: str, quote: str) -> str:
    labels = {
        "npu": "Knowledge of NPUs or machine-learning accelerators",
        "ml_accelerator": "Machine-learning accelerator or hardware acceleration work",
        "quantization": "Quantized model or inference optimization",
        "edge_ai": "Edge or on-device AI deployment",
        "on_device_inference": "On-device inference execution",
        "hardware_aware_optimization": "Hardware-aware performance optimization",
        "machine_learning": "Machine-learning model development",
        "pytorch": "PyTorch model work",
        "compiler_runtime": "Compiler/runtime implementation",
        "rtl": "RTL or computer-architecture implementation",
        "verification": "Verification methodology",
        "python": "Python implementation",
        "cpp": "C++ implementation",
    }
    return labels.get(key, quote)


def _role_dimensions(requirements: list[Requirement]) -> dict[str, float]:
    dims: dict[str, float] = {}
    for requirement in requirements:
        for cap in requirement.normalized_capabilities:
            current = dims.get(cap, 0.0)
            dims[cap] = min(1.0, current + requirement.importance)
    return {key: round(value, 3) for key, value in sorted(dims.items())}


def _role_dimensions_from_dicts(requirements: list[dict[str, Any]]) -> dict[str, float]:
    dims: dict[str, float] = {}
    for requirement in requirements:
        for cap in requirement.get("normalized_capabilities", []):
            current = dims.get(str(cap), 0.0)
            dims[str(cap)] = min(1.0, current + float(requirement.get("importance") or 0.0))
    return {key: round(value, 3) for key, value in sorted(dims.items())}


def _requirement_compat(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence_quotes") or []
    quote = item.get("evidence_quote") or (evidence[0] if evidence else "")
    return {
        **item,
        "evidence_quote": quote,
        "normalized_capabilities": list(item.get("normalized_capabilities") or []),
        "differentiation_value": item.get(
            "differentiation_value",
            round(float(item.get("specificity") or 0.0) * 0.75, 3),
        ),
    }


def _semantic_payload(
    status: str,
    metadata: dict[str, Any],
    accepted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = {
        **metadata,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "fallback_used": status != "live_success",
    }
    return {
        "schema_version": SEMANTIC_REQUIREMENT_SCHEMA_VERSION,
        "status": status,
        "metadata": metadata,
        "accepted_requirements": accepted,
        "rejected_requirements": rejected,
    }


def _semantic_rejection_reason(item: Any, normalized_job_text: str) -> str | None:
    if not isinstance(item, dict):
        return "not_object"
    quote = str(item.get("evidence_quote") or "").strip()
    if not quote or _normalize_grounding_text(quote) not in normalized_job_text:
        return "ungrounded_evidence"
    if _is_negated_context(quote, normalized_job_text):
        return "negated_evidence"
    caps = item.get("normalized_capabilities")
    if not isinstance(caps, list) or not caps:
        return "missing_capabilities"
    unknown = [str(cap) for cap in caps if str(cap) not in APPROVED_CAPABILITIES]
    if unknown:
        return "invalid_capability"
    for key in ("importance", "specificity"):
        value = item.get(key)
        if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            return f"invalid_{key}"
    text = str(item.get("requirement_text") or "").strip()
    if not text:
        return "missing_requirement_text"
    lowered = quote.casefold()
    if "accelerate innovation" in lowered or "fast-paced" in lowered:
        return "generic_marketing"
    if lowered == "hardware" and any(
        token in normalized_job_text
        for token in ("laptop hardware", "hardware inventory", "it equipment")
    ):
        return "generic_it_hardware"
    return None


def _normalize_grounding_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _is_negated_context(quote: str, normalized_job_text: str) -> bool:
    quote_norm = _normalize_grounding_text(quote)
    index = normalized_job_text.find(quote_norm)
    if index < 0:
        return False
    prefix = normalized_job_text[max(0, index - 48):index]
    return any(
        token in prefix
        for token in ("not ", "no ", "without ", "excluded ", "not responsible")
    )


def _matching_requirement(
    requirements: list[dict[str, Any]],
    semantic: dict[str, Any],
) -> dict[str, Any] | None:
    sem_caps = set(semantic.get("normalized_capabilities") or [])
    sem_quote = _normalize_grounding_text(str(semantic.get("evidence_quote") or ""))
    for item in requirements:
        caps = set(item.get("normalized_capabilities") or [])
        quotes = [
            _normalize_grounding_text(str(quote))
            for quote in item.get("evidence_quotes", [])
        ]
        if sem_caps & caps and (sem_quote in quotes or caps == sem_caps):
            return item
    return None


def _saturate(value: float) -> float:
    return min(1.0, value / (1.0 + value))


def _bridge_bonus(block: dict[str, Any], requirement_analysis: dict[str, Any]) -> float:
    dims = requirement_analysis.get("role_dimensions") or {}
    if not isinstance(dims, dict):
        return 0.0
    bonus = 0.0
    for pair in block.get("bridge_domains", []):
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        left, right = str(pair[0]), str(pair[1])
        bonus = max(bonus, min(float(dims.get(left, 0.0)), float(dims.get(right, 0.0))))
    strength = float(block.get("portfolio_strength", 0.75))
    return min(0.35, bonus * strength)


def _match_reason(block: dict[str, Any], requirement: dict[str, Any], overlap: list[str]) -> str:
    evidence = ", ".join(str(term) for term in block.get("evidence_terms", [])[:2])
    caps = ", ".join(overlap)
    return (
        f"{block.get('display_name')} covers {caps}"
        + (f" through {evidence}." if evidence else ".")
    )
