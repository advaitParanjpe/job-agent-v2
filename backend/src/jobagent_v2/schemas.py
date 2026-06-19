"""Small schema helpers for the Phase 1 API contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ValidationError(ValueError):
    """Raised when a request payload does not match the Phase 1 contract."""


@dataclass(frozen=True)
class CapturePayload:
    url: str
    page_title: str
    visible_text: str
    source_site: str | None
    captured_at: str


def require_object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("request body must be a JSON object")
    return payload


def parse_capture_payload(payload: Any) -> CapturePayload:
    data = require_object(payload)
    url = _required_string(data, "url")
    page_title = _required_string(data, "page_title")
    visible_text = _required_string(data, "visible_text")
    captured_at = _required_string(data, "captured_at")
    source_site = data.get("source_site")
    if source_site is not None and not isinstance(source_site, str):
        raise ValidationError("source_site must be a string or null")
    return CapturePayload(
        url=url,
        page_title=page_title,
        visible_text=visible_text,
        source_site=source_site.strip() or None if isinstance(source_site, str) else None,
        captured_at=captured_at,
    )


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{key} is required")
    return value.strip()

