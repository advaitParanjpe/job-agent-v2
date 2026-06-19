"""Deterministic Phase 2 intake extraction and quality diagnostics."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal


QualityBand = Literal["good", "usable_with_warnings", "manual_review", "failed"]


SECTION_HEADERS = {
    "about the role",
    "the role",
    "what you'll do",
    "what you will do",
    "responsibilities",
    "key responsibilities",
    "requirements",
    "minimum qualifications",
    "basic qualifications",
    "preferred qualifications",
    "qualifications",
    "what we need to see",
    "experience",
    "skills",
}
RESPONSIBILITY_TERMS = (
    "responsibilities",
    "what you'll do",
    "what you will do",
    "you will",
    "role",
)
QUALIFICATION_TERMS = (
    "requirements",
    "qualifications",
    "minimum qualifications",
    "preferred qualifications",
    "experience",
    "skills",
)
BOILERPLATE_TERMS = (
    "cookie",
    "privacy policy",
    "terms of use",
    "sign in",
    "create job alert",
    "similar jobs",
    "recommended jobs",
    "share this job",
    "apply now",
    "equal opportunity employer",
    "accessibility",
)
FOOTER_HEADERS = (
    "similar jobs",
    "recommended jobs",
    "share this job",
    "job alerts",
    "privacy policy",
    "terms of use",
)
LOCATION_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z .'-]+,\s*(?:[A-Z]{2}|United States|UK|United Kingdom|Canada|India))\b"
)


@dataclass(frozen=True)
class FieldValue:
    value: str | None
    source: str
    confidence: str
    alternatives: list[dict[str, Any]] | None = None
    raw_value: str | None = None
    normalization: list[str] | None = None


@dataclass(frozen=True)
class JdQuality:
    band: QualityBand
    score: int
    raw_text_length: int
    clean_text_length: int
    has_responsibilities_section: bool
    has_qualifications_section: bool
    has_company_title_clues: bool
    boilerplate_ratio: float
    warnings: list[str]
    manual_review_recommended: bool
    failure_reason: str | None


@dataclass(frozen=True)
class IntakeResult:
    jd_text: str
    extraction_method: str
    quality: JdQuality
    company: FieldValue
    title: FieldValue
    location: FieldValue
    warnings: list[str]
    failure_reason: str | None
    manual_review_reason: str | None
    duplicate_fingerprint: str
    detected_site: str
    candidates: dict[str, list[dict[str, Any]]]


def run_intake(
    *,
    page_title: str,
    visible_text: str,
    source_site: str | None,
    source_url: str,
    evidence: dict[str, Any] | None = None,
) -> IntakeResult:
    evidence = evidence or {}
    raw = normalize_text(visible_text)
    detected_site = str(evidence.get("detected_site") or source_site or "generic")
    jd_source = select_jd_text(raw, evidence)
    lines = meaningful_lines(jd_source["text"])
    clean_lines = trim_to_job_like_content(lines)
    clean = "\n".join(clean_lines).strip()
    extraction_method = jd_source["source"]
    if clean_lines != lines and extraction_method == "visible_text":
        extraction_method = "visible_text_section_heuristic"
    candidate_map = collect_candidates(
        page_title=page_title,
        source_site=source_site,
        source_url=source_url,
        text=clean,
        evidence=evidence,
    )
    company = resolve_field("company", candidate_map["company"])
    title = resolve_field("title", candidate_map["title"])
    location = resolve_field("location", candidate_map["location"])
    quality_raw_text = raw if len(raw) >= len(jd_source["text"]) else jd_source["text"]
    quality = assess_quality(
        raw_text=quality_raw_text,
        clean_text=clean,
        has_company_title_clues=bool(company.value and title.value),
    )
    warnings = list(quality.warnings)
    if not company.value:
        warnings.append("company_not_confident")
    if not title.value:
        warnings.append("title_not_confident")
    if not location.value:
        warnings.append("location_not_found")
    failure_reason = quality.failure_reason
    manual_review_reason = None
    if quality.band == "manual_review":
        manual_review_reason = "JD extraction quality requires manual review."
    return IntakeResult(
        jd_text=clean,
        extraction_method=extraction_method,
        quality=quality,
        company=company,
        title=title,
        location=location,
        warnings=dedupe_preserve_order(warnings),
        failure_reason=failure_reason,
        manual_review_reason=manual_review_reason,
        duplicate_fingerprint=fingerprint_text(clean),
        detected_site=detected_site,
        candidates=candidate_map,
    )


def select_jd_text(raw_visible_text: str, evidence: dict[str, Any]) -> dict[str, str]:
    for posting in evidence.get("json_ld_job_postings", []):
        if isinstance(posting, dict):
            description = clean_html_text(str(posting.get("description") or ""))
            if len(description) >= 120:
                return {"text": description, "source": "json_ld_description"}
    for value in evidence.get("likely_description_elements", []):
        text = normalize_text(str(value))
        if len(text) >= 180:
            return {"text": text, "source": "dom_description_candidate"}
    return {"text": raw_visible_text, "source": "visible_text"}


def clean_html_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"</(?:p|li|div|h\d)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_text(
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def collect_candidates(
    *,
    page_title: str,
    source_site: str | None,
    source_url: str,
    text: str,
    evidence: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    candidates = {"company": [], "title": [], "location": []}
    for posting in evidence.get("json_ld_job_postings", []):
        if not isinstance(posting, dict):
            continue
        org = posting.get("hiringOrganization")
        company = org if isinstance(org, str) else (org or {}).get("name")
        add_candidate(candidates, "company", company, "json_ld_jobposting", "high")
        add_candidate(candidates, "title", posting.get("title"), "json_ld_jobposting", "high")
        add_candidate(
            candidates,
            "location",
            render_json_ld_location(posting.get("jobLocation")),
            "json_ld_jobposting",
            "high",
        )
    for value in evidence.get("likely_title_elements", []):
        add_candidate(candidates, "title", value, "dom_title_candidate", "high")
    for value in evidence.get("likely_company_elements", []):
        add_candidate(candidates, "company", value, "dom_company_candidate", "high")
    for value in evidence.get("likely_location_elements", []):
        add_candidate(
            candidates,
            "location",
            cleanup_location(str(value)),
            "dom_location_candidate",
            "high",
        )
    meta = evidence.get("meta") if isinstance(evidence.get("meta"), dict) else {}
    add_from_meta(candidates, meta)
    for heading in evidence.get("headings", []):
        text_heading = str(heading)
        if is_plausible_title(text_heading):
            add_candidate(candidates, "title", text_heading, "heading", "medium")
    legacy_company = extract_company(page_title=page_title, source_site=None, text=text)
    legacy_title = extract_title(page_title=page_title, text=text, company=None)
    legacy_location = extract_location(page_title=page_title, text=text)
    add_candidate(
        candidates,
        "company",
        legacy_company.value,
        legacy_company.source,
        legacy_company.confidence,
    )
    add_candidate(
        candidates,
        "title",
        legacy_title.value,
        legacy_title.source,
        legacy_title.confidence,
    )
    add_candidate(
        candidates,
        "location",
        legacy_location.value,
        legacy_location.source,
        legacy_location.confidence,
    )
    if source_site:
        add_candidate(candidates, "company", source_site, "source_site", "low")
    add_url_candidates(candidates, source_url)
    normalize_campaign_title_candidates(candidates["title"])
    return candidates


def add_candidate(
    candidates: dict[str, list[dict[str, Any]]],
    field: str,
    value: object,
    source: str,
    confidence: str,
) -> None:
    if value is None:
        return
    raw_value = normalize_candidate(str(value))
    if not raw_value:
        return
    clean, normalization = normalize_field_candidate(field, raw_value)
    if not clean:
        return
    if field == "title" and not is_plausible_title(clean):
        return
    if field == "company" and not is_plausible_company(clean):
        return
    item = {
        "raw_value": raw_value,
        "value": clean,
        "source": source,
        "confidence": confidence,
        "normalization": normalization,
    }
    if item not in candidates[field]:
        candidates[field].append(item)


def normalize_candidate(value: str) -> str:
    return re.sub(r"\s+", " ", clean_html_text(value)).strip(" |-–—")


def normalize_field_candidate(field: str, value: str) -> tuple[str | None, list[str]]:
    if field == "company":
        return normalize_company_candidate(value)
    if field == "location":
        clean = cleanup_location(value)
        return (clean, []) if clean else (None, [])
    return value, []


def resolve_field(field: str, candidates: list[dict[str, Any]]) -> FieldValue:
    if not candidates:
        return FieldValue(None, "not_found", "none", [])
    priority = {
        "json_ld_jobposting": 100,
        "dom_title_candidate": 90,
        "dom_company_candidate": 90,
        "dom_location_candidate": 90,
        "meta_tag": 75,
        "heading": 65,
        "page_title_pattern": 60,
        "visible_text_label": 60,
        "visible_text_pattern": 55,
        "visible_text_heading": 50,
        "url_pattern": 35,
        "source_site": 20,
    }
    ranked = sorted(
        candidates,
        key=lambda item: (
            priority.get(item["source"], 0),
            {"high": 3, "medium": 2, "low": 1, "none": 0}.get(item["confidence"], 0),
            len(item["value"]),
        ),
        reverse=True,
    )
    selected = ranked[0]
    alternatives = [item for item in ranked[1:8] if item["value"] != selected["value"]]
    return FieldValue(
        selected["value"],
        selected["source"],
        selected["confidence"],
        alternatives,
        str(selected.get("raw_value") or selected["value"]),
        list(selected.get("normalization") or []),
    )


CAMPAIGN_TITLE_SUFFIX = re.compile(
    r"\s*[-|:]\s*(?:new college grad|university graduate|graduate program|"
    r"early career|campus hiring)\b(?:\s*[-:]?\s*20\d{2})?\s*$",
    flags=re.I,
)


def normalize_campaign_title_candidates(candidates: list[dict[str, Any]]) -> None:
    for candidate in candidates:
        raw_value = str(candidate["raw_value"])
        normalized = CAMPAIGN_TITLE_SUFFIX.sub("", raw_value).strip()
        if normalized == raw_value or not normalized:
            continue
        supporting_sources = {
            str(other["source"])
            for other in candidates
            if str(other["source"]) != str(candidate["source"])
            and str(other["value"]).casefold() == normalized.casefold()
        }
        if len(supporting_sources) < 2:
            continue
        candidate["value"] = normalized
        candidate["normalization"] = [
            *list(candidate.get("normalization") or []),
            "campaign_suffix_removed",
        ]


COUNTRY_ONLY_VALUES = {
    "us",
    "usa",
    "u.s.",
    "u.s.a.",
    "united states",
    "united states of america",
    "uk",
    "united kingdom",
    "canada",
    "india",
}
ADDRESS_WORDS = re.compile(
    r"\b(?:street|st\.?|road|rd\.?|avenue|ave\.?|suite|building|postal|zip)\b",
    flags=re.I,
)


def normalize_company_candidate(value: str) -> tuple[str | None, list[str]]:
    clean = value.strip()
    normalization: list[str] = []
    without_address_number = re.sub(r"^\d{1,6}\s+", "", clean)
    if without_address_number != clean:
        clean = without_address_number
        normalization.append("leading_street_number_removed")
    country_match = re.search(
        r"\s+(?:USA|US|U\.S\.A?\.|United States(?: of America)?|"
        r"UK|United Kingdom|Canada|India)\s*$",
        clean,
        flags=re.I,
    )
    if country_match and clean[: country_match.start()].strip():
        clean = clean[: country_match.start()].strip(" ,-")
        normalization.append("country_suffix_removed")
    if re.search(r"\b\d{5}(?:-\d{4})?\b", clean) or ADDRESS_WORDS.search(clean):
        return None, normalization + ["address_like_candidate_rejected"]
    if clean.casefold() in COUNTRY_ONLY_VALUES or not is_plausible_company(clean):
        return None, normalization
    return clean, normalization


def render_json_ld_location(value: object) -> str | None:
    rendered = render_json_ld_locations(value)
    return " / ".join(rendered) or None


def render_json_ld_locations(value: object) -> list[str]:
    locations = value if isinstance(value, list) else [value]
    rendered: list[tuple[str, set[str]]] = []
    for location in locations:
        components = json_ld_location_components(location)
        if not components:
            continue
        clean_components = dedupe_location_components(components)
        if not clean_components:
            continue
        component_key = {item.lower() for item in clean_components}
        if any(component_key.issubset(existing) for _, existing in rendered):
            continue
        rendered.append((", ".join(clean_components), component_key))
    return [item[0] for item in rendered]


def json_ld_location_components(value: object) -> list[str]:
    if isinstance(value, str):
        return split_location_components(value)
    if isinstance(value, list):
        components: list[str] = []
        for item in value:
            components.extend(json_ld_location_components(item))
        return components
    if not isinstance(value, dict):
        return []
    address = value.get("address")
    if address is not None and address is not value:
        return json_ld_location_components(address)
    if any(
        key in value
        for key in ("addressLocality", "addressRegion", "addressCountry", "streetAddress")
    ):
        components: list[str] = []
        for key in ("addressLocality", "addressRegion", "addressCountry"):
            components.extend(json_ld_scalar_components(value.get(key)))
        return components
    return json_ld_scalar_components(value)


def json_ld_scalar_components(value: object) -> list[str]:
    if isinstance(value, str):
        return split_location_components(value)
    if isinstance(value, list):
        components: list[str] = []
        for item in value:
            components.extend(json_ld_scalar_components(item))
        return components
    if isinstance(value, dict):
        for key in ("name", "identifier", "code", "addressCountry"):
            if key in value:
                return json_ld_scalar_components(value[key])
    return []


def split_location_components(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def dedupe_location_components(components: list[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for component in components:
        normalized = re.sub(r"\s+", " ", component).strip(" .,-")
        if not normalized or "{" in normalized or "}" in normalized or "@type" in normalized:
            continue
        key = normalized.lower()
        if key not in seen:
            clean.append(normalized)
            seen.add(key)
    return clean


def add_from_meta(candidates: dict[str, list[dict[str, str]]], meta: dict[str, object]) -> None:
    title = str(meta.get("og:title") or meta.get("twitter:title") or "")
    site = str(meta.get("og:site_name") or meta.get("application-name") or "")
    if title:
        legacy_title = extract_title(page_title=title, text="", company=None)
        add_candidate(candidates, "title", legacy_title.value or title, "meta_tag", "medium")
    add_candidate(candidates, "company", site, "meta_tag", "medium")


def add_url_candidates(candidates: dict[str, list[dict[str, str]]], source_url: str) -> None:
    match = re.search(r"/companies/([^/]+)/jobs/", source_url)
    if match:
        add_candidate(candidates, "company", match.group(1).replace("-", " "), "url_pattern", "low")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def meaningful_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip(" \t•-*")
        if not line:
            continue
        lowered = line.lower()
        if len(line) < 3:
            continue
        if lowered in {"home", "jobs", "careers", "search", "menu"}:
            continue
        lines.append(line)
    return lines


def trim_to_job_like_content(lines: list[str]) -> list[str]:
    if not lines:
        return []
    start = 0
    for index, line in enumerate(lines[:40]):
        lowered = line.lower().strip(":")
        if lowered in SECTION_HEADERS or any(term in lowered for term in RESPONSIBILITY_TERMS):
            start = max(0, index - 3)
            break
    selected = lines[start:]
    end = len(selected)
    for index, line in enumerate(selected):
        lowered = line.lower().strip(":")
        if index > 8 and any(lowered.startswith(header) for header in FOOTER_HEADERS):
            end = index
            break
    return selected[:end]


def assess_quality(*, raw_text: str, clean_text: str, has_company_title_clues: bool) -> JdQuality:
    raw_len = len(raw_text)
    clean_len = len(clean_text)
    lowered = clean_text.lower()
    has_resp = any(term in lowered for term in RESPONSIBILITY_TERMS)
    has_qual = any(term in lowered for term in QUALIFICATION_TERMS)
    boilerplate_hits = sum(clean_text.lower().count(term) for term in BOILERPLATE_TERMS)
    line_count = max(1, len(clean_text.splitlines()))
    boilerplate_ratio = min(1.0, boilerplate_hits / line_count)
    score = 0
    warnings: list[str] = []
    failure_reason = None
    if clean_len >= 1200:
        score += 35
    elif clean_len >= 500:
        score += 25
    elif clean_len >= 220:
        score += 12
    else:
        warnings.append("clean_jd_too_short")
    if has_resp:
        score += 20
    else:
        warnings.append("responsibilities_section_missing")
    if has_qual:
        score += 20
    else:
        warnings.append("qualifications_section_missing")
    if has_company_title_clues:
        score += 15
    else:
        warnings.append("company_or_title_clues_missing")
    if boilerplate_ratio <= 0.1:
        score += 10
    elif boilerplate_ratio > 0.3:
        warnings.append("high_boilerplate_ratio")
        score -= 10
    score = max(0, min(100, score))
    if raw_len < 80 or clean_len < 80:
        band: QualityBand = "failed"
        failure_reason = "Captured text is too short to extract a job description."
    elif clean_len < 220 and not (has_resp or has_qual):
        band = "failed"
        failure_reason = "No usable responsibilities or qualifications found."
    elif score >= 75 and has_resp and has_qual:
        band = "good"
    elif score >= 55 and (has_resp or has_qual):
        band = "usable_with_warnings"
    else:
        band = "manual_review"
    return JdQuality(
        band=band,
        score=score,
        raw_text_length=raw_len,
        clean_text_length=clean_len,
        has_responsibilities_section=has_resp,
        has_qualifications_section=has_qual,
        has_company_title_clues=has_company_title_clues,
        boilerplate_ratio=round(boilerplate_ratio, 3),
        warnings=dedupe_preserve_order(warnings),
        manual_review_recommended=band == "manual_review",
        failure_reason=failure_reason,
    )


def extract_company(*, page_title: str, source_site: str | None, text: str) -> FieldValue:
    title = page_title.strip()
    for separator in (" | ", " - ", " – ", " — ", " at "):
        if separator in title:
            parts = [part.strip() for part in title.split(separator) if part.strip()]
            if len(parts) >= 2:
                candidate = parts[-1]
                if is_plausible_company(candidate):
                    return FieldValue(candidate, "page_title_pattern", "medium")
    for line in text.splitlines()[:12]:
        match = re.match(r"^(?:Company|Employer)\s*:\s*(.+)$", line, flags=re.I)
        if match and is_plausible_company(match.group(1)):
            return FieldValue(match.group(1).strip(), "visible_text_label", "high")
    if source_site:
        return FieldValue(source_site, "source_site", "low")
    return FieldValue(None, "not_found", "none")


def extract_title(*, page_title: str, text: str, company: str | None) -> FieldValue:
    clean_title = page_title.strip()
    if clean_title:
        for separator in (" | ", " - ", " – ", " — "):
            if separator in clean_title:
                first = clean_title.split(separator)[0].strip()
                if is_plausible_title(first):
                    return FieldValue(first, "page_title_pattern", "high")
        if " at " in clean_title:
            first = clean_title.split(" at ")[0].strip()
            if is_plausible_title(first):
                return FieldValue(first, "page_title_pattern", "high")
        if is_plausible_title(clean_title):
            return FieldValue(clean_title, "page_title", "medium")
    for line in text.splitlines()[:10]:
        match = re.match(r"^(?:Job Title|Title|Role)\s*:\s*(.+)$", line, flags=re.I)
        if match and is_plausible_title(match.group(1)):
            return FieldValue(match.group(1).strip(), "visible_text_label", "high")
        if company and company.lower() in line.lower():
            continue
        if is_plausible_title(line) and looks_like_heading(line):
            return FieldValue(line.strip(), "visible_text_heading", "medium")
    return FieldValue(None, "not_found", "none")


def extract_location(*, page_title: str, text: str) -> FieldValue:
    for line in text.splitlines()[:25]:
        match = re.match(r"^(?:Location|Office)\s*:\s*(.+)$", line, flags=re.I)
        if match:
            value = cleanup_location(match.group(1))
            if value:
                return FieldValue(value, "visible_text_label", "high")
    match = LOCATION_PATTERN.search(text)
    if match:
        return FieldValue(cleanup_location(match.group(1)), "visible_text_pattern", "medium")
    match = LOCATION_PATTERN.search(page_title)
    if match:
        return FieldValue(cleanup_location(match.group(1)), "page_title_pattern", "medium")
    if re.search(r"\b(remote|hybrid)\b", text, flags=re.I):
        return FieldValue("Remote/Hybrid", "visible_text_pattern", "low")
    return FieldValue(None, "not_found", "none")


def cleanup_location(value: str | None) -> str | None:
    if not value:
        return None
    clean = re.sub(r"^(?:locations?|office)\s*:\s*", "", value, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip(" .,-")
    if len(clean) > 90:
        clean = clean[:90].rsplit(" ", 1)[0]
    return clean or None


def is_plausible_company(value: str) -> bool:
    clean = value.strip()
    if not (2 <= len(clean) <= 80):
        return False
    return not any(word in clean.lower() for word in {"career", "job", "apply"})


def is_plausible_title(value: str) -> bool:
    clean = value.strip()
    if not (4 <= len(clean) <= 120):
        return False
    lowered = clean.lower()
    return any(
        term in lowered
        for term in (
            "engineer",
            "developer",
            "manager",
            "designer",
            "analyst",
            "scientist",
            "intern",
            "architect",
            "lead",
            "specialist",
        )
    )


def looks_like_heading(value: str) -> bool:
    clean = value.strip()
    if clean.endswith((".", "!", "?")):
        return False
    return len(clean.split()) <= 10


def fingerprint_text(text: str) -> str:
    normalized = re.sub(r"\W+", " ", text.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def intake_result_to_updates(result: IntakeResult) -> dict[str, object]:
    return {
        "jd_text": result.jd_text,
        "jd_quality_score": result.quality.score,
        "jd_quality_band": result.quality.band,
        "jd_quality_json": json.dumps(asdict(result.quality), sort_keys=True),
        "structured_jd_json": json.dumps(
            {
                "company": result.company.value,
                "title": result.title.value,
                "location": result.location.value,
                "responsibilities": [],
                "must_have_skills": [],
                "nice_to_have_skills": [],
                "raw_constraints": [],
                "phase": "phase_2_intake_only",
            },
            sort_keys=True,
        ),
        "company": result.company.value,
        "title": result.title.value,
        "location": result.location.value,
        "extraction_method": result.extraction_method,
        "extraction_warnings_json": json.dumps(result.warnings, sort_keys=True),
        "failure_reason": result.failure_reason,
        "manual_review_reason": result.manual_review_reason,
        "field_provenance_json": json.dumps(
            {
                "company": asdict(result.company),
                "title": asdict(result.title),
                "location": asdict(result.location),
            },
            sort_keys=True,
        ),
        "detected_site": result.detected_site,
        "extraction_candidates_json": json.dumps(result.candidates, sort_keys=True),
        "raw_text_length": result.quality.raw_text_length,
        "clean_text_length": result.quality.clean_text_length,
        "jd_text_fingerprint": result.duplicate_fingerprint,
    }


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
