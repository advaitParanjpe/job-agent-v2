"""Backend package metadata used by repository checks."""

from typing import Final, TypedDict


class AppMetadata(TypedDict):
    name: str
    phase: str
    implements_features: bool


APP_NAME: Final[str] = "jobagent-v2"
BOOTSTRAP_PHASE: Final[str] = "release-v0.1.0"


def create_app_metadata() -> AppMetadata:
    """Return static metadata proving the backend package imports cleanly."""
    return {
        "name": APP_NAME,
        "phase": BOOTSTRAP_PHASE,
        "implements_features": True,
    }
