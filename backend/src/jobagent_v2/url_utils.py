"""Phase 1 URL normalization and duplicate-key helpers."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_url(raw_url: str) -> str:
    """Return a basic normalized URL for Phase 1 URL-based deduplication."""
    value = raw_url.strip()
    if not value:
        raise ValueError("url is required")
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        raise ValueError("url must include scheme and host")
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("url scheme must be http or https")
    host = parts.netloc.lower()
    path = parts.path or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, host, path, query, ""))


def duplicate_key_for_url(raw_url: str) -> str:
    return normalize_url(raw_url)


def source_site_from_url(raw_url: str) -> str:
    parts = urlsplit(normalize_url(raw_url))
    host = parts.netloc
    return host[4:] if host.startswith("www.") else host

