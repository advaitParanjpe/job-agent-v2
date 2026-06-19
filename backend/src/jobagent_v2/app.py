"""Backend bootstrap surface for Phase 0B checks."""

from typing import Final, TypedDict


class AppMetadata(TypedDict):
    name: str
    phase: str
    implements_features: bool


APP_NAME: Final[str] = "jobagent-v2"
BOOTSTRAP_PHASE: Final[str] = "phase-0b"


def create_app_metadata() -> AppMetadata:
    """Return static metadata proving the backend package imports cleanly."""
    return {
        "name": APP_NAME,
        "phase": BOOTSTRAP_PHASE,
        "implements_features": False,
    }

