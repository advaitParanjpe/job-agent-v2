"""CLI entrypoint for running the local JobAgent V2 API server."""

from __future__ import annotations

import argparse
import os
import threading
from pathlib import Path

from jobagent_v2.api import create_http_server
from jobagent_v2.promotion import PromotionConfig


def start_promotion_loop(server) -> threading.Event | None:
    if os.getenv("JOBAGENT_PROMOTION_SCHEDULER_ENABLED", "true").lower() == "false":
        return None
    stop = threading.Event()
    interval = PromotionConfig.from_env().interval_seconds

    def run() -> None:
        while not stop.is_set():
            try:
                server.RequestHandlerClass.service.run_promotion_once()
            except Exception:
                pass
            stop.wait(interval)

    threading.Thread(target=run, name="jobagent-promotion", daemon=True).start()
    return stop


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local JobAgent V2 API server")
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
    stop = start_promotion_loop(server)
    try:
        server.serve_forever()
    finally:
        if stop is not None:
            stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
