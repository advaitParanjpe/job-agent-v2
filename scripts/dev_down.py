#!/usr/bin/env python3
"""Stop processes launched by ./scripts/dev-up."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"


def main() -> int:
    sys.path.insert(0, str(BACKEND_SRC))
    from jobagent_v2.local_runtime import clean_state_if_stale, stop_tracked_processes

    stopped = stop_tracked_processes()
    stale_cleaned = clean_state_if_stale()
    if not stopped:
        print("No tracked JobAgent dev processes are running.")
        if stale_cleaned:
            print("Cleaned stale runtime state.")
        return 0
    for item in stopped:
        print(f"Stopped {item['name']} (PID {item['pid']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
