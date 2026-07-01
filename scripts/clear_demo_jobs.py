#!/usr/bin/env python3
"""Safely remove jobs explicitly marked as demo from the configured local DB."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
DEFAULT_DB = REPO_ROOT / "data" / "jobagent_v2.sqlite3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove explicit demo jobs only.")
    parser.add_argument("--yes", action="store_true", help="Do not prompt for confirmation.")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Leave generated demo packet artifacts on disk.",
    )
    parser.add_argument("--allow-default-db", action="store_true")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(BACKEND_SRC))
    from jobagent_v2.config import RuntimeConfig, load_local_env
    from jobagent_v2.storage import Repository

    load_local_env()
    config = RuntimeConfig.from_env()
    db_path = (
        (REPO_ROOT / config.db_path).resolve()
        if not config.db_path.is_absolute()
        else config.db_path.resolve()
    )
    if db_path == DEFAULT_DB.resolve() and not args.allow_default_db:
        print(
            "Refusing default production-style database without --allow-default-db.",
            file=sys.stderr,
        )
        return 1
    repo = Repository(db_path)
    preview = repo.demo_cleanup_preview(owner_id=config.owner_id)
    print(
        f"Demo cleanup preview: {preview['job_count']} jobs, "
        f"{preview['review_count']} reviews, {preview['packet_count']} packets."
    )
    if preview["job_count"] == 0:
        return 0
    if not args.yes:
        answer = input(
            "Remove only explicitly marked demo jobs? "
            "Type 'remove demo jobs' to continue: "
        )
        if answer != "remove demo jobs":
            print("Cancelled.")
            return 1
    removed = repo.clear_demo_jobs(owner_id=config.owner_id)
    if not args.keep_artifacts:
        for raw in removed["artifact_directories"]:
            path = Path(raw)
            try:
                resolved = path.resolve()
            except OSError:
                continue
            artifact_root = config.artifact_dir.resolve()
            if artifact_root in resolved.parents and resolved.exists():
                shutil.rmtree(resolved)
    print(f"Removed {removed['job_count']} demo jobs. Real jobs were preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
