"""CLI entrypoint for running the local Phase 1 API server."""

from __future__ import annotations

import argparse
from pathlib import Path

from jobagent_v2.api import create_http_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run JobAgent V2 Phase 1 API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db-path", default="data/jobagent_v2.sqlite3")
    parser.add_argument("--artifact-root", default="data/artifacts")
    args = parser.parse_args()

    server = create_http_server(
        args.host,
        args.port,
        db_path=Path(args.db_path),
        artifact_root=Path(args.artifact_root),
    )
    print(f"JobAgent V2 API listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

