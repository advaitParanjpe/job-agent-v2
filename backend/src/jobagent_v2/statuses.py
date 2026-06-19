"""Status values and validated transitions for the Phase 1 queue skeleton."""

from __future__ import annotations

from typing import Final, Literal


IntakeStatus = Literal[
    "raw_added",
    "queued",
    "extracting",
    "structuring",
    "scoring",
    "scored",
    "duplicate",
    "failed",
    "manual_review",
]
PacketStatus = Literal[
    "not_requested",
    "queued",
    "generating",
    "rewriting",
    "truth_checking",
    "rendering",
    "fitting",
    "ready",
    "failed",
    "manual_review",
    "skipped_low_score",
]


VALID_INTAKE_STATUSES: Final[set[str]] = {
    "raw_added",
    "queued",
    "extracting",
    "structuring",
    "scoring",
    "scored",
    "duplicate",
    "failed",
    "manual_review",
}
VALID_PACKET_STATUSES: Final[set[str]] = {
    "not_requested",
    "queued",
    "generating",
    "rewriting",
    "truth_checking",
    "rendering",
    "fitting",
    "ready",
    "failed",
    "manual_review",
    "skipped_low_score",
}

INTAKE_TRANSITIONS: Final[set[tuple[str, str]]] = {
    ("queued", "extracting"),
    ("extracting", "structuring"),
    ("extracting", "manual_review"),
    ("extracting", "failed"),
    ("structuring", "scored"),
    ("structuring", "scoring"),
    ("structuring", "manual_review"),
    ("structuring", "failed"),
    ("extracting", "scoring"),
    ("scoring", "scored"),
    ("scoring", "failed"),
    ("scored", "scoring"),
    ("failed", "queued"),
    ("manual_review", "queued"),
}
PACKET_TRANSITIONS: Final[set[tuple[str, str]]] = {
    ("not_requested", "queued"),
    ("queued", "generating"),
    ("generating", "ready"),
    ("failed", "queued"),
    ("manual_review", "queued"),
}


class InvalidTransitionError(ValueError):
    """Raised when a status transition is not allowed by the V2 status model."""


def validate_intake_transition(from_status: str, to_status: str) -> None:
    if from_status not in VALID_INTAKE_STATUSES:
        raise InvalidTransitionError(f"unknown intake status: {from_status}")
    if to_status not in VALID_INTAKE_STATUSES:
        raise InvalidTransitionError(f"unknown intake status: {to_status}")
    if (from_status, to_status) not in INTAKE_TRANSITIONS:
        raise InvalidTransitionError(
            f"invalid intake transition: {from_status} -> {to_status}"
        )


def validate_packet_transition(from_status: str, to_status: str) -> None:
    if from_status not in VALID_PACKET_STATUSES:
        raise InvalidTransitionError(f"unknown packet status: {from_status}")
    if to_status not in VALID_PACKET_STATUSES:
        raise InvalidTransitionError(f"unknown packet status: {to_status}")
    if (from_status, to_status) not in PACKET_TRANSITIONS:
        raise InvalidTransitionError(
            f"invalid packet transition: {from_status} -> {to_status}"
        )


def retry_available(intake_status: str, packet_status: str) -> bool:
    return intake_status in {"failed", "manual_review"} or packet_status in {
        "failed",
        "manual_review",
    }
