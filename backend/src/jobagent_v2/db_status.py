"""Inspect and initialize the local SQLite database schema."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from jobagent_v2.config import RuntimeConfig, load_local_env
from jobagent_v2.storage import Repository, SCHEMA_VERSION


def inspect_database(path: Path | str, *, initialize: bool = False) -> dict[str, Any]:
    db_path = Path(path)
    exists_before = db_path.exists()
    if initialize:
        Repository(db_path)
    elif not exists_before:
        return {
            "db_path": str(db_path),
            "exists": False,
            "supported_schema_version": SCHEMA_VERSION,
            "status": "missing",
        }
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        meta_exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone()
        if meta_exists is None:
            version = None
        else:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            version = int(row["value"]) if row else None
        tables = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
    status = "current" if version == SCHEMA_VERSION else "needs_migration"
    if version is not None and version > SCHEMA_VERSION:
        status = "unsupported_future_schema"
    return {
        "db_path": str(db_path),
        "exists": True,
        "schema_version": version,
        "supported_schema_version": SCHEMA_VERSION,
        "status": status,
        "tables": tables,
    }


def main(argv: list[str] | None = None) -> int:
    load_local_env()
    config = RuntimeConfig.from_env()
    parser = argparse.ArgumentParser(description="Inspect JobAgent SQLite schema status.")
    parser.add_argument("--db-path", default=str(config.db_path))
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args(argv)
    result = inspect_database(args.db_path, initialize=args.initialize)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == "unsupported_future_schema" else 0


if __name__ == "__main__":
    raise SystemExit(main())
