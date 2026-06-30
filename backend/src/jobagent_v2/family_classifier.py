"""Auditable four-family job classification for canonical master-CV selection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from jobagent_v2.llm_client import LLMUnavailableError, SemanticLLMClient


FAMILY_IDS = ("digital_ic", "verification", "software", "ml")
CLASSIFIER_VERSION = "phase-b-family-classifier-v1"
CONFIG_PATH = Path(__file__).with_name("data") / "family_classifier.json"
SEMANTIC_PROMPT_VERSION = "phase-b-family-semantic-v1"


class FamilyClassifierConfigurationError(ValueError):
    """Raised when the family-classifier configuration is invalid."""


class SemanticProvider(Protocol):
    def __call__(
        self,
        job: dict[str, Any],
        structured_jd: dict[str, Any],
        deterministic: dict[str, float],
    ) -> dict[str, Any]:
        """Return semantic family scores and evidence."""


@dataclass(frozen=True)
class FamilyClassificationResult:
    family_scores: dict[str, float]
    selected_family: str
    secondary_family: str | None
    confidence: float
    decision: str
    requires_review: bool
    rule_evidence: list[dict[str, Any]]
    semantic_evidence: list[dict[str, Any]]
    classifier_version: str
    config_version: str
    deterministic_scores: dict[str, float]
    semantic_scores: dict[str, float] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_scores": self.family_scores,
            "selected_family": self.selected_family,
            "secondary_family": self.secondary_family,
            "confidence": self.confidence,
            "decision": self.decision,
            "requires_review": self.requires_review,
            "rule_evidence": self.rule_evidence,
            "semantic_evidence": self.semantic_evidence,
            "classifier_version": self.classifier_version,
            "config_version": self.config_version,
            "deterministic_scores": self.deterministic_scores,
            "semantic_scores": self.semantic_scores,
        }


class LLMFamilySemanticProvider:
    """Optional semantic provider using the existing disabled-by-default LLM client."""

    def __init__(self, client: SemanticLLMClient | None = None) -> None:
        self.client = client or SemanticLLMClient()

    def __call__(
        self,
        job: dict[str, Any],
        structured_jd: dict[str, Any],
        deterministic: dict[str, float],
    ) -> dict[str, Any]:
        prompt = {
            "prompt_version": SEMANTIC_PROMPT_VERSION,
            "instructions": (
                "Classify the job across exactly digital_ic, verification, software, "
                "and ml. Use only the supplied job description. Return normalized "
                "scores and extracted evidence; do not judge candidate fit."
            ),
            "families": list(FAMILY_IDS),
            "job": {
                "title": job.get("title") or structured_jd.get("title"),
                "jd_text": job.get("jd_text"),
            },
            "structured_jd": structured_jd,
            "deterministic_scores": deterministic,
        }
        return self.client.assess(prompt)


def load_classifier_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("classifier_version") != CLASSIFIER_VERSION:
        raise FamilyClassifierConfigurationError("classifier version mismatch")
    families = tuple(data.get("families") or ())
    if families != FAMILY_IDS:
        raise FamilyClassifierConfigurationError("classifier families must match canonical IDs")
    if not isinstance(data.get("signals"), dict):
        raise FamilyClassifierConfigurationError("classifier signals are missing")
    if set(data["signals"]) != set(FAMILY_IDS):
        raise FamilyClassifierConfigurationError("classifier signals must cover all families")
    return data


def classify_job_family(
    job: dict[str, Any],
    *,
    structured_jd: dict[str, Any] | None = None,
    config_path: Path = CONFIG_PATH,
    semantic_provider: SemanticProvider | None = None,
) -> FamilyClassificationResult:
    config = load_classifier_config(config_path)
    structured = structured_jd or {}
    deterministic, rule_evidence = deterministic_family_scores(job, structured, config)
    semantic_scores, semantic_evidence = semantic_family_scores(
        job, structured, deterministic, semantic_provider
    )
    combined = combine_scores(deterministic, semantic_scores, config)
    ranked = sorted(combined.items(), key=lambda item: (-item[1], item[0]))
    selected, confidence = ranked[0]
    secondary = ranked[1][0] if len(ranked) > 1 else None
    decision, requires_review = decide(combined, config)
    if decision == "clear_match" and has_title_conflict(rule_evidence, selected):
        decision = "hybrid_match"
        requires_review = False
    return FamilyClassificationResult(
        family_scores=combined,
        selected_family=selected,
        secondary_family=secondary,
        confidence=round(confidence, 4),
        decision=decision,
        requires_review=requires_review,
        rule_evidence=rule_evidence,
        semantic_evidence=semantic_evidence,
        classifier_version=str(config["classifier_version"]),
        config_version=str(config["config_version"]),
        deterministic_scores=deterministic,
        semantic_scores=semantic_scores,
    )


def selection_from_classification(result: FamilyClassificationResult) -> dict[str, Any]:
    confidence_label = (
        "high" if result.decision == "clear_match"
        else "medium" if result.decision == "hybrid_match"
        else "low"
    )
    evidence = [
        item["phrase"] for item in result.rule_evidence
        if item.get("family") == result.selected_family and item.get("weight", 0) > 0
    ]
    reason = (
        f"{result.selected_family} selected by {result.decision} "
        f"with score {result.confidence:.2f}."
    )
    secondary_score = (
        result.family_scores.get(result.secondary_family, 0.0)
        if result.secondary_family
        else 0.0
    )
    secondary_family = result.secondary_family if secondary_score >= 0.15 else None
    return {
        "primary_family": result.selected_family,
        "secondary_family": secondary_family,
        "confidence": confidence_label,
        "confidence_score": result.confidence,
        "decision": result.decision,
        "requires_review": result.requires_review,
        "reason": reason,
        "evidence": evidence,
        "selector_version": result.classifier_version,
        "classifier": result.to_dict(),
        "manual_override": None,
    }


def deterministic_family_scores(
    job: dict[str, Any],
    structured: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    sections = section_texts(job, structured)
    section_weights = config["section_weights"]
    raw = {family: 0.0 for family in FAMILY_IDS}
    evidence: list[dict[str, Any]] = []
    for family in FAMILY_IDS:
        signals = config["signals"][family]
        for section, text in sections.items():
            base_weight = float(section_weights.get(section, 1.0))
            for phrase in signals.get(section, []):
                if phrase_matches(text, phrase):
                    weight = base_weight * phrase_strength(str(phrase))
                    raw[family] += weight
                    evidence.append(evidence_record(family, section, phrase, weight, text))
        for phrase in signals.get("negative", []):
            matched_sections = [
                section for section, text in sections.items()
                if phrase_matches(text, phrase)
            ]
            if matched_sections:
                weight = -1.5 * phrase_strength(str(phrase))
                raw[family] = max(0.0, raw[family] + weight)
                evidence.append(
                    {
                        "source": "deterministic",
                        "family": family,
                        "section": ",".join(matched_sections),
                        "phrase": phrase,
                        "weight": round(weight, 4),
                        "polarity": "negative",
                    }
                )
    return normalize(raw), evidence


def semantic_family_scores(
    job: dict[str, Any],
    structured: dict[str, Any],
    deterministic: dict[str, float],
    provider: SemanticProvider | None,
) -> tuple[dict[str, float] | None, list[dict[str, Any]]]:
    if provider is None:
        return None, [{
            "source": "semantic",
            "status": "unavailable",
            "reason": "semantic_provider_not_configured",
        }]
    try:
        payload = provider(job, structured, deterministic)
        scores = validate_semantic_scores(payload)
    except (LLMUnavailableError, ValueError, TypeError, KeyError) as error:
        return None, [{
            "source": "semantic",
            "status": "unavailable",
            "reason": str(error),
        }]
    evidence = payload.get("semantic_evidence", payload.get("evidence", []))
    if not isinstance(evidence, list):
        evidence = []
    return scores, [
        {"source": "semantic", "status": "success", "evidence": evidence}
    ]


def validate_semantic_scores(payload: dict[str, Any]) -> dict[str, float]:
    if not isinstance(payload, dict):
        raise ValueError("semantic family response must be an object")
    scores = payload.get("family_scores")
    if not isinstance(scores, dict) or set(scores) != set(FAMILY_IDS):
        raise ValueError("semantic family response must score all canonical families")
    values: dict[str, float] = {}
    for family in FAMILY_IDS:
        value = scores[family]
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError("semantic family score must be a non-negative number")
        values[family] = float(value)
    return normalize(values)


def combine_scores(
    deterministic: dict[str, float],
    semantic: dict[str, float] | None,
    config: dict[str, Any],
) -> dict[str, float]:
    if semantic is None:
        return normalize(deterministic)
    weights = config["combination"]
    deterministic_weight = float(weights["deterministic_weight"])
    semantic_weight = float(weights["semantic_weight"])
    combined = {
        family: deterministic_weight * deterministic[family] + semantic_weight * semantic[family]
        for family in FAMILY_IDS
    }
    return normalize(combined)


def decide(scores: dict[str, float], config: dict[str, Any]) -> tuple[str, bool]:
    thresholds = config["decision_thresholds"]
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    top = ranked[0][1]
    second = ranked[1][1]
    margin = top - second
    if top <= float(thresholds["low_confidence_max_score"]):
        return "low_confidence", True
    if (
        top >= float(thresholds["clear_min_score"])
        and margin >= float(thresholds["clear_min_margin"])
    ):
        return "clear_match", False
    if margin <= float(thresholds["close_max_margin"]):
        return "close_match", True
    return "hybrid_match", False


def has_title_conflict(evidence: list[dict[str, Any]], selected_family: str) -> bool:
    title_families = {
        str(item.get("family"))
        for item in evidence
        if item.get("section") == "title" and item.get("polarity") == "positive"
    }
    return bool(title_families - {selected_family})


def section_texts(job: dict[str, Any], structured: dict[str, Any]) -> dict[str, str]:
    title = " ".join(
        str(value or "") for value in (job.get("title"), structured.get("title"))
    )
    jd_text = str(job.get("jd_text") or job.get("raw_visible_text") or "")
    responsibilities = "\n".join(str(value) for value in structured.get("responsibilities", []))
    qualifications = "\n".join(
        str(value)
        for value in (
            list(structured.get("must_have_requirements", []))
            + list(structured.get("nice_to_have_requirements", []))
        )
    )
    tools = " ".join(
        str(value)
        for value in (
            list(structured.get("skills", []))
            + list(structured.get("technologies", []))
            + list(structured.get("keywords", []))
        )
    )
    domains = " ".join(str(value) for value in structured.get("domains", []))
    return {
        "title": title,
        "responsibility": f"{responsibilities}\n{jd_text}",
        "qualification": f"{qualifications}\n{jd_text}",
        "domain": f"{domains}\n{jd_text}",
        "tool": f"{tools}\n{jd_text}",
    }


def phrase_matches(text: str, phrase: str) -> bool:
    normalized = normalize_text(text)
    target = normalize_text(str(phrase))
    if not target:
        return False
    pattern = r"(?<![a-z0-9+/#])" + re.escape(target) + r"(?![a-z0-9+/#])"
    return re.search(pattern, normalized) is not None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("full-stack", "full stack")).strip()


def phrase_strength(phrase: str) -> float:
    return 1.0 + min(0.8, 0.08 * max(0, len(phrase.split()) - 1))


def evidence_record(
    family: str, section: str, phrase: str, weight: float, text: str
) -> dict[str, Any]:
    return {
        "source": "deterministic",
        "family": family,
        "section": section,
        "phrase": phrase,
        "weight": round(weight, 4),
        "polarity": "positive",
        "matched_excerpt": excerpt_for_phrase(text, phrase),
    }


def excerpt_for_phrase(text: str, phrase: str) -> str:
    normalized = normalize_text(text)
    target = normalize_text(str(phrase))
    index = normalized.find(target)
    if index < 0:
        return ""
    start = max(0, index - 45)
    end = min(len(normalized), index + len(target) + 45)
    return normalized[start:end].strip()


def normalize(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(values.get(family, 0.0))) for family in FAMILY_IDS)
    if total <= 0:
        return {family: 0.25 for family in FAMILY_IDS}
    rounded = {
        family: round(max(0.0, float(values.get(family, 0.0))) / total, 6)
        for family in FAMILY_IDS
    }
    drift = round(1.0 - sum(rounded.values()), 6)
    top = max(rounded, key=rounded.get)
    rounded[top] = round(rounded[top] + drift, 6)
    return rounded
