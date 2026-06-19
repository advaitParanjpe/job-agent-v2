"""URL normalization and duplicate-key helpers."""

from __future__ import annotations

from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "trk",
    "trackingid",
}
REDIRECT_PARAMS = (
    "url",
    "u",
    "target",
    "redirect",
    "redirect_url",
    "destination",
    "dest",
    "link",
)
JOB_ID_QUERY_HINTS = {
    "gh_jid",
    "jobid",
    "job_id",
    "job",
    "jid",
    "jr",
    "reqid",
    "req_id",
    "requisitionid",
    "requisition_id",
    "postingid",
}


def normalize_url(raw_url: str) -> str:
    """Return a stable normalized URL for deterministic intake deduplication."""
    value = raw_url.strip()
    if not value:
        raise ValueError("url is required")
    value = unwrap_redirect_url(value)
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        raise ValueError("url must include scheme and host")
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("url scheme must be http or https")
    host = _normalize_netloc(parts.netloc)
    path = _normalize_path(parts.path)
    query = _normalize_query(parts.query)
    return urlunsplit((scheme, host, path, query, ""))


def duplicate_key_for_url(raw_url: str) -> str:
    return normalize_url(raw_url)


def source_site_from_url(raw_url: str) -> str:
    parts = urlsplit(normalize_url(raw_url))
    host = parts.netloc
    return host[4:] if host.startswith("www.") else host


def unwrap_redirect_url(raw_url: str) -> str:
    parts = urlsplit(raw_url.strip())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key in REDIRECT_PARAMS:
        candidate = query.get(key)
        if not candidate:
            continue
        decoded = unquote(candidate).strip()
        if decoded.startswith(("http://", "https://")):
            return decoded
    return raw_url.strip()


def _normalize_netloc(netloc: str) -> str:
    lowered = netloc.lower()
    if lowered.endswith(":443"):
        return lowered[:-4]
    return lowered


def _normalize_path(path: str) -> str:
    clean = path or "/"
    if clean != "/" and clean.endswith("/"):
        clean = clean.rstrip("/")
    return clean


def _normalize_query(query: str) -> str:
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_PARAMS:
            continue
        if lowered in {"ref", "source"} and not _looks_job_identifying(value):
            continue
        kept.append((key, value))
    return urlencode(sorted(kept), doseq=True)


def _looks_job_identifying(value: str) -> bool:
    lowered = value.lower()
    if any(hint in lowered for hint in JOB_ID_QUERY_HINTS):
        return True
    return any(char.isdigit() for char in value) and len(value) >= 4
