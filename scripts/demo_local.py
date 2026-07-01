#!/usr/bin/env python3
"""Seed demo jobs into the configured isolated local database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
DEFAULT_DB = REPO_ROOT / "data" / "jobagent_v2.sqlite3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed demo jobs into .env.local database.")
    parser.add_argument("--allow-default-db", action="store_true")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(BACKEND_SRC))
    from jobagent_v2.config import RuntimeConfig, load_local_env
    from jobagent_v2.service import JobService
    from jobagent_v2.storage import Repository

    load_local_env()
    config = RuntimeConfig.from_env()
    resolved_db = (
        (REPO_ROOT / config.db_path).resolve()
        if not config.db_path.is_absolute()
        else config.db_path.resolve()
    )
    if resolved_db == DEFAULT_DB.resolve() and not args.allow_default_db:
        print(
            "Refusing to seed the default production-style database. "
            "Use data/local-test/jobagent.sqlite3 in .env.local or pass --allow-default-db.",
            file=sys.stderr,
        )
        return 1
    scripts_dir = REPO_ROOT / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from demo_seed import _payloads

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    service = JobService(Repository(config.db_path), config.artifact_dir)
    created = [service.create_job(payload)["job"] for payload in _payloads()]
    print(f"Created {len(created)} demo jobs in {config.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
