"""Local development process and environment helpers."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from jobagent_v2.config import LOCAL_ENV_FILENAME, REPO_ROOT, RuntimeConfig
from jobagent_v2.util import utc_now_iso


RUNTIME_DIR = REPO_ROOT / ".runtime"
STATE_PATH = RUNTIME_DIR / "dev-up.json"
SERVICE_MARKERS = {
    "api": ("jobagent_v2.server",),
    "workers": ("jobagent_v2.worker_runner",),
    "frontend": ("http.server",),
}


@dataclass(frozen=True)
class PortOwner:
    host: str
    port: int
    pid: int | None
    command: str | None

    def describe(self) -> str:
        if self.pid and self.command:
            return f"{self.host}:{self.port} is already in use by PID {self.pid}: {self.command}"
        if self.pid:
            return f"{self.host}:{self.port} is already in use by PID {self.pid}"
        return f"{self.host}:{self.port} is already in use"


def require_local_env() -> None:
    path = REPO_ROOT / LOCAL_ENV_FILENAME
    if not path.exists():
        raise RuntimeError(
            f"{LOCAL_ENV_FILENAME} was not found at {path}. Run ./scripts/setup-local, "
            "then edit .env.local and set JOBAGENT_LLM_API_KEY."
        )


def assert_startup_config(config: RuntimeConfig) -> None:
    errors = config.validate_llm_startup()
    if errors:
        raise RuntimeError("\n".join(errors))


def print_safe_config_summary(config: RuntimeConfig) -> None:
    for line in config.llm_summary_lines():
        print(line)


def assert_ports_available(config: RuntimeConfig) -> None:
    conflicts = [
        owner
        for owner in (
            port_owner(config.api_host, config.api_port),
            port_owner(config.frontend_host, config.frontend_port),
        )
        if owner is not None
    ]
    if not conflicts:
        return
    lines = ["Configured port conflict detected; startup was not attempted."]
    for owner in conflicts:
        lines.append(owner.describe())
        lines.append(f"Inspect it with: lsof -nP -iTCP:{owner.port} -sTCP:LISTEN")
    if _state_has_live_processes():
        lines.append("If this is a previous job-agent-v2 stack, run: ./scripts/dev-down")
    lines.append("No unrelated process was killed.")
    raise RuntimeError("\n".join(lines))


def port_owner(host: str, port: int) -> PortOwner | None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        if sock.connect_ex((host, port)) != 0:
            return None
    pid, command = _lsof_owner(port)
    return PortOwner(host=host, port=port, pid=pid, command=command)


def write_state(processes: list[dict[str, Any]]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "repo_root": str(REPO_ROOT),
        "started_at": utc_now_iso(),
        "processes": processes,
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def read_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "repo_root": str(REPO_ROOT), "processes": []}
    return payload if isinstance(payload, dict) else None


def clean_state_if_stale() -> bool:
    state = read_state()
    if not state:
        return False
    processes = state.get("processes", [])
    if not isinstance(processes, list):
        STATE_PATH.unlink(missing_ok=True)
        return True
    if not any(_process_exists(entry.get("pid")) for entry in processes if isinstance(entry, dict)):
        STATE_PATH.unlink(missing_ok=True)
        return True
    return False


def stop_tracked_processes(*, timeout_seconds: float = 5.0) -> list[dict[str, Any]]:
    state = read_state()
    if not state:
        return []
    stopped: list[dict[str, Any]] = []
    live_entries = [
        entry
        for entry in state.get("processes", [])
        if isinstance(entry, dict) and _is_tracked_process(entry)
    ]
    for entry in live_entries:
        _terminate_entry(entry, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline and any(
        _is_tracked_process(entry) for entry in live_entries
    ):
        time.sleep(0.1)
    for entry in live_entries:
        if _is_tracked_process(entry):
            _terminate_entry(entry, signal.SIGKILL)
        stopped.append({"name": entry.get("name"), "pid": entry.get("pid")})
    STATE_PATH.unlink(missing_ok=True)
    return stopped


def status_report(config: RuntimeConfig, *, timeout_seconds: float = 1.0) -> dict[str, Any]:
    clean_state_if_stale()
    state = read_state()
    tracked = {
        entry.get("name"): _is_tracked_process(entry)
        for entry in (state or {}).get("processes", [])
        if isinstance(entry, dict)
    }
    api_reachable, worker_health = _worker_health(config, timeout_seconds=timeout_seconds)
    return {
        "env_local_exists": (REPO_ROOT / LOCAL_ENV_FILENAME).exists(),
        "frontend_url": f"http://{config.frontend_host}:{config.frontend_port}",
        "api_url": f"http://{config.api_host}:{config.api_port}",
        "llm_enabled": config.semantic_enabled,
        "llm_api_key_configured": config.semantic_api_key_present,
        "api_running": bool(tracked.get("api")) or api_reachable,
        "frontend_running": bool(tracked.get("frontend"))
        or port_owner(config.frontend_host, config.frontend_port) is not None,
        "worker_runner_running": bool(tracked.get("workers")),
        "worker_health": worker_health,
    }


def process_command(pid: int) -> str | None:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            text=True,
            capture_output=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    command = result.stdout.strip()
    return command or None


def _process_exists(pid: object) -> bool:
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _state_has_live_processes() -> bool:
    state = read_state()
    return bool(
        state
        and any(
            isinstance(entry, dict) and _is_tracked_process(entry)
            for entry in state.get("processes", [])
        )
    )


def _is_tracked_process(entry: dict[str, Any]) -> bool:
    pid = entry.get("pid")
    name = entry.get("name")
    if not isinstance(pid, int) or not isinstance(name, str):
        return False
    command = process_command(pid)
    if not command:
        return False
    expected = SERVICE_MARKERS.get(name, ())
    return all(marker in command for marker in expected)


def _terminate_entry(entry: dict[str, Any], sig: signal.Signals) -> None:
    pid = entry.get("pid")
    if not isinstance(pid, int) or not _is_tracked_process(entry):
        return
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return
    except OSError:
        try:
            os.kill(pid, sig)
        except OSError:
            return


def _lsof_owner(port: int) -> tuple[int | None, str | None]:
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp", "-Fc"],
            check=False,
            text=True,
            capture_output=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    pid: int | None = None
    command: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            try:
                pid = int(line[1:])
            except ValueError:
                pid = None
        elif line.startswith("c"):
            command = line[1:]
        if pid is not None and command:
            return pid, command
    return pid, command


def _worker_health(
    config: RuntimeConfig, *, timeout_seconds: float
) -> tuple[bool, dict[str, Any] | None]:
    url = f"http://{config.api_host}:{config.api_port}/api/workers/status"
    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return True, payload if isinstance(payload, dict) else None
    except (OSError, URLError, json.JSONDecodeError, TimeoutError):
        return False, None
