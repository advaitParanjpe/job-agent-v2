#!/usr/bin/env python3
"""Report local JobAgent dev stack status without printing secrets."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"


def main() -> int:
    sys.path.insert(0, str(BACKEND_SRC))
    from jobagent_v2.config import RuntimeConfig, load_local_env
    from jobagent_v2.local_runtime import status_report

    try:
        load_local_env()
        config = RuntimeConfig.from_env()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    report = status_report(config)
    print(f".env.local: {'present' if report['env_local_exists'] else 'missing'}")
    frontend_state = "running" if report["frontend_running"] else "stopped"
    print(f"Frontend: {report['frontend_url']} ({frontend_state})")
    print(f"API:      {report['api_url']} ({'running' if report['api_running'] else 'stopped'})")
    print(f"Workers:  {'running' if report['worker_runner_running'] else 'stopped'}")
    print(f"LLM semantic classification: {'enabled' if report['llm_enabled'] else 'disabled'}")
    print(f"LLM API key: {'configured' if report['llm_api_key_configured'] else 'missing'}")
    if report["worker_health"] is None:
        print("Worker health endpoint: unavailable")
    else:
        print("Worker health endpoint: reachable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
