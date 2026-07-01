#!/usr/bin/env python3
"""Start the local API, worker runner, and frontend static server."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
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
    from jobagent_v2.config import RuntimeConfig, load_local_env
    from jobagent_v2.local_runtime import (
        assert_ports_available,
        assert_startup_config,
        clean_state_if_stale,
        print_safe_config_summary,
        require_local_env,
        write_state,
    )
    from jobagent_v2.preflight import run_preflight

    try:
        require_local_env()
        local_env = load_local_env()
        config = RuntimeConfig.from_env()
        print_safe_config_summary(config)
        assert_startup_config(config)
        clean_state_if_stale()
        assert_ports_available(config)
        if not args.skip_preflight:
            result = run_preflight(config=config, strict_latex=False, check_ports=False)
            _print_preflight(result)
            if not result["ok"]:
                return 1
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1

    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(BACKEND_SRC) if not existing_path else f"{BACKEND_SRC}{os.pathsep}{existing_path}"
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    python = _python_executable()

    commands = [
        (
            "api",
            [
                python,
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
                python,
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
                python,
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
    processes: list[tuple[str, subprocess.Popen[str], list[str]]] = []
    readers: list[threading.Thread] = []
    print("Starting JobAgent local release stack")
    if local_env.exists:
        print(f"Config:   loaded {local_env.path}")
    print(f"API:      http://{config.api_host}:{config.api_port}")
    print(f"Frontend: http://{config.frontend_host}:{config.frontend_port}")
    print("Workers:  q1, q2, regeneration")
    try:
        for name, command in commands:
            process = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            processes.append((name, process, command))
            readers.append(_prefix_output(name, process))
            time.sleep(0.4)
            if process.poll() is not None:
                print(
                    f"{name} exited during startup with code {process.returncode}",
                    file=sys.stderr,
                )
                return 1
        write_state([
            {
                "name": name,
                "pid": process.pid,
                "command": command,
                "cwd": str(REPO_ROOT),
            }
            for name, process, command in processes
        ])
        if args.open:
            webbrowser.open(f"http://{config.frontend_host}:{config.frontend_port}")
        while True:
            for name, process, _command in processes:
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
        for reader in readers:
            reader.join(timeout=1)


def _print_preflight(result: dict[str, object]) -> None:
    print(f"Preflight v{result['release_version']}")
    for item in result["checks"]:  # type: ignore[index]
        print(f"{item['status'].upper():4} {item['name']}: {item['message']}")


def _python_executable() -> str:
    candidate = REPO_ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def _prefix_output(name: str, process: subprocess.Popen[str]) -> threading.Thread:
    def run() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            print(f"[{name}] {line}", end="")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _terminate(processes: list[tuple[str, subprocess.Popen[str], list[str]]]) -> None:
    for _name, process, _command in processes:
        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except OSError:
                process.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + 5
    for _name, process, _command in processes:
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
    for _name, process, _command in processes:
        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except OSError:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
