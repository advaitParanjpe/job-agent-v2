from __future__ import annotations

import pytest

from jobagent_v2.statuses import (
    InvalidTransitionError,
    retry_available,
    validate_intake_transition,
    validate_packet_transition,
)
from jobagent_v2.url_utils import duplicate_key_for_url, normalize_url, source_site_from_url


def test_valid_state_transitions() -> None:
    validate_intake_transition("queued", "extracting")
    validate_intake_transition("extracting", "scoring")
    validate_intake_transition("scoring", "scored")
    validate_packet_transition("not_requested", "queued")
    validate_packet_transition("queued", "generating")
    validate_packet_transition("generating", "ready")


def test_invalid_state_transition_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_intake_transition("queued", "scored")
    with pytest.raises(InvalidTransitionError):
        validate_packet_transition("not_requested", "ready")


def test_url_normalization_used_for_duplicate_keys() -> None:
    url = "HTTPS://Example.COM/jobs/123?b=2&a=1#details"

    assert normalize_url(url) == "https://example.com/jobs/123?a=1&b=2"
    assert duplicate_key_for_url(url) == "https://example.com/jobs/123?a=1&b=2"
    assert source_site_from_url("https://www.example.com/jobs") == "example.com"


def test_retry_eligibility() -> None:
    assert retry_available("failed", "not_requested")
    assert retry_available("scored", "failed")
    assert not retry_available("queued", "not_requested")

