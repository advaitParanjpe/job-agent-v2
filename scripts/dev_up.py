#!/usr/bin/env python3
"""Start the local API, worker runner, and frontend static server."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the local JobAgent release stack.")
    parser.add_argument("--open", action="store_true", help="Open the frontend in a browser.")
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(BACKEND_SRC))
    from jobagent_v2.config import RuntimeConfig
    from jobagent_v2.preflight import run_preflight

    config = RuntimeConfig.from_env()
    if not args.skip_preflight:
        result = run_preflight(config=config, strict_latex=False, check_ports=True)
        _print_preflight(result)
        if not result["ok"]:
            return 1
    else:
        _assert_port_available(config.api_host, config.api_port, "API")
        _assert_port_available(config.frontend_host, config.frontend_port, "frontend")

    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(BACKEND_SRC) if not existing_path else f"{BACKEND_SRC}{os.pathsep}{existing_path}"
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)

    commands = [
        (
            "api",
            [
                sys.executable,
                "-m",
                "jobagent_v2.server",
                "--host",
                config.api_host,
                "--port",
                str(config.api_port),
                "--db-path",
                str(config.db_path),
                "--artifact-root",
                str(config.artifact_dir),
            ],
        ),
        (
            "workers",
            [
                sys.executable,
                "-m",
                "jobagent_v2.worker_runner",
                "--all",
                "--db-path",
                str(config.db_path),
                "--artifact-root",
                str(config.artifact_dir),
            ],
        ),
        (
            "frontend",
            [
                sys.executable,
                "-m",
                "http.server",
                str(config.frontend_port),
                "--bind",
                config.frontend_host,
                "--directory",
                str(REPO_ROOT / "frontend" / "src"),
            ],
        ),
    ]
    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    print("Starting JobAgent local release stack")
    print(f"API:      http://{config.api_host}:{config.api_port}")
    print(f"Frontend: http://{config.frontend_host}:{config.frontend_port}")
    print("Workers:  q1, q2, regeneration")
    try:
        for name, command in commands:
            process = subprocess.Popen(command, cwd=REPO_ROOT, env=env)
            processes.append((name, process))
            time.sleep(0.4)
            if process.poll() is not None:
                print(
                    f"{name} exited during startup with code {process.returncode}",
                    file=sys.stderr,
                )
                return 1
        if args.open:
            webbrowser.open(f"http://{config.frontend_host}:{config.frontend_port}")
        while True:
            for name, process in processes:
                code = process.poll()
                if code is not None:
                    print(f"{name} exited with code {code}; stopping stack", file=sys.stderr)
                    return code or 1
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Stopping JobAgent local release stack")
        return 0
    finally:
        _terminate(processes)


def _print_preflight(result: dict[str, object]) -> None:
    print(f"Preflight v{result['release_version']}")
    for item in result["checks"]:  # type: ignore[index]
        print(f"{item['status'].upper():4} {item['name']}: {item['message']}")


def _assert_port_available(host: str, port: int, label: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        if sock.connect_ex((host, port)) == 0:
            raise SystemExit(f"{label} port {host}:{port} is already in use")


def _terminate(processes: list[tuple[str, subprocess.Popen[bytes]]]) -> None:
    for _name, process in processes:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + 5
    for _name, process in processes:
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
    for _name, process in processes:
        if process.poll() is None:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
