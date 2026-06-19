from __future__ import annotations

from jobagent_v2.url_utils import duplicate_key_for_url, normalize_url, unwrap_redirect_url


def test_url_normalization_is_idempotent() -> None:
    raw = "HTTPS://Example.COM/jobs/123/?utm_source=x&gh_jid=456#details"
    normalized = normalize_url(raw)

    assert normalize_url(normalized) == normalized


def test_tracking_parameters_removed_and_job_parameters_preserved() -> None:
    normalized = normalize_url(
        "https://boards.greenhouse.io/acme/jobs/123?utm_campaign=x&gh_jid=789&source=12345"
    )

    assert "utm_campaign" not in normalized
    assert "gh_jid=789" in normalized
    assert "source=12345" in normalized


def test_redirect_wrappers_are_handled_safely() -> None:
    wrapped = (
        "https://redirect.example/out?"
        "url=https%3A%2F%2Fjobs.example.com%2Frole%3Fjob_id%3D42&utm_source=x"
    )

    assert unwrap_redirect_url(wrapped).startswith("https://jobs.example.com/role")
    assert normalize_url(wrapped) == "https://jobs.example.com/role?job_id=42"


def test_duplicate_key_is_stable() -> None:
    first = duplicate_key_for_url("https://example.com/jobs/1/?b=2&a=1#x")
    second = duplicate_key_for_url("https://EXAMPLE.com/jobs/1?a=1&b=2")

    assert first == second
