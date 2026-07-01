from __future__ import annotations

import sqlite3
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobagent_v2.config import RuntimeConfig, load_local_env
from jobagent_v2.db_status import inspect_database
from jobagent_v2.local_runtime import (
    PortOwner,
    assert_ports_available,
    clean_state_if_stale,
    status_report,
    stop_tracked_processes,
)
from jobagent_v2.llm_client import LLMConfig
from jobagent_v2.preflight import run_preflight
from jobagent_v2.storage import SCHEMA_VERSION, Repository


def test_runtime_config_redacts_secret_and_rejects_bad_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JOBAGENT_LLM_API_KEY", "secret-value")
    assert RuntimeConfig.from_env().safe_dict()["semantic_api_key"] == "<redacted>"
    monkeypatch.setenv("JOBAGENT_API_PORT", "70000")
    with pytest.raises(ValueError, match="valid TCP port"):
        RuntimeConfig.from_env()


def test_secret_files_are_ignored_and_template_has_no_real_secret() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")

    assert ".env.local" in gitignore.splitlines()
    assert ".runtime/" in gitignore.splitlines()
    assert "JOBAGENT_LLM_API_KEY=" in env_example
    assert "sk-" not in env_example
    assert "replace-with-local-key" not in env_example
    assert "data/local-test/jobagent.sqlite3" in env_example


def test_local_env_file_loads_without_overriding_shell_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join([
            "# local-only settings",
            "JOBAGENT_LLM_ENABLED=true",
            "JOBAGENT_LLM_API_KEY='from-file'",
            'JOBAGENT_LLM_MODEL="gpt-test-model"',
            "JOBAGENT_API_PORT=9999 # local override",
            "export JOBAGENT_OWNER_ID=owner-from-file",
        ]),
        encoding="utf-8",
    )
    for key in (
        "JOBAGENT_LLM_ENABLED",
        "JOBAGENT_LLM_API_KEY",
        "JOBAGENT_LLM_MODEL",
        "JOBAGENT_API_PORT",
        "JOBAGENT_OWNER_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("JOBAGENT_API_PORT", "8766")

    result = load_local_env(env_path)

    assert result.exists is True
    assert "JOBAGENT_LLM_API_KEY" in result.loaded_keys
    assert result.skipped_keys == ("JOBAGENT_API_PORT",)
    runtime = RuntimeConfig.from_env()
    llm = LLMConfig.from_env()
    assert runtime.api_port == 8766
    assert runtime.owner_id == "owner-from-file"
    assert llm.enabled is True
    assert llm.api_key == "from-file"
    assert llm.model == "gpt-test-model"


def test_local_env_file_rejects_invalid_lines(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text("JOBAGENT_LLM_ENABLED\n", encoding="utf-8")

    with pytest.raises(ValueError, match="expected KEY=value"):
        load_local_env(env_path)


def test_llm_startup_validation_blocks_missing_or_placeholder_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JOBAGENT_LLM_ENABLED", "true")
    monkeypatch.delenv("JOBAGENT_LLM_API_KEY", raising=False)
    assert "JOBAGENT_LLM_API_KEY is missing" in RuntimeConfig.from_env().validate_llm_startup()[0]

    monkeypatch.setenv("JOBAGENT_LLM_API_KEY", "changeme")
    assert "obvious placeholder" in RuntimeConfig.from_env().validate_llm_startup()[0]

    monkeypatch.setenv("JOBAGENT_LLM_ENABLED", "false")
    monkeypatch.delenv("JOBAGENT_LLM_API_KEY", raising=False)
    assert RuntimeConfig.from_env().validate_llm_startup() == []


def test_preflight_valid_setup_uses_isolated_database(tmp_path: Path) -> None:
    config = RuntimeConfig(
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        db_path=tmp_path / "data" / "jobagent.sqlite3",
        api_port=0,
        frontend_port=0,
    )
    result = run_preflight(config=config, check_ports=False)

    assert result["ok"] is True
    assert (tmp_path / "data" / "jobagent.sqlite3").is_file()
    assert {item["name"] for item in result["checks"]} >= {
        "master_cvs",
        "project_block_registry",
        "database",
        "frontend_files",
        "llm_config",
    }


def test_preflight_reports_latex_as_optional_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("jobagent_v2.preflight.shutil.which", lambda _name: None)
    config = RuntimeConfig(
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        db_path=tmp_path / "data" / "jobagent.sqlite3",
    )

    result = run_preflight(config=config, check_ports=False)

    latex = [item for item in result["checks"] if item["name"] == "latex"][0]
    assert result["ok"] is True
    assert latex["status"] == "warn"


def test_preflight_detects_occupied_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "jobagent_v2.preflight.port_owner",
        lambda host, port: PortOwner(host, port, 1234, "python") if port == 8765 else None,
    )
    config = RuntimeConfig(
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        db_path=tmp_path / "data" / "jobagent.sqlite3",
        api_port=8765,
        frontend_port=5173,
    )

    result = run_preflight(config=config, check_ports=True)

    assert result["ok"] is False
    assert any(item["name"] == "api_port" and item["status"] == "fail" for item in result["checks"])


def test_occupied_port_message_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    config = RuntimeConfig(api_port=8765, frontend_port=5173)
    owners = {
        8765: PortOwner("127.0.0.1", 8765, 1234, "python -m jobagent_v2.server"),
        5173: None,
    }
    monkeypatch.setattr(
        "jobagent_v2.local_runtime.port_owner",
        lambda _host, port: owners[port],
    )
    monkeypatch.setattr("jobagent_v2.local_runtime._state_has_live_processes", lambda: True)

    with pytest.raises(RuntimeError) as error:
        assert_ports_available(config)

    message = str(error.value)
    assert "127.0.0.1:8765 is already in use by PID 1234" in message
    assert "lsof -nP -iTCP:8765 -sTCP:LISTEN" in message
    assert "./scripts/dev-down" in message


def test_dev_down_does_not_kill_unrelated_process_and_cleans_stale_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "dev-up.json"
    state_path.write_text(
        '{"processes": [{"name": "api", "pid": 99999, "command": ["python"]}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr("jobagent_v2.local_runtime.STATE_PATH", state_path)
    monkeypatch.setattr("jobagent_v2.local_runtime.process_command", lambda _pid: "unrelated")
    monkeypatch.setattr(
        "jobagent_v2.local_runtime.os.killpg",
        lambda *_args: pytest.fail("unrelated process should not be killed"),
    )

    assert stop_tracked_processes() == []
    assert not state_path.exists()


def test_stale_pid_state_is_cleaned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "dev-up.json"
    state_path.write_text(
        '{"processes": [{"name": "workers", "pid": 111, "command": ["python"]}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr("jobagent_v2.local_runtime.STATE_PATH", state_path)
    monkeypatch.setattr("jobagent_v2.local_runtime.process_command", lambda _pid: None)

    assert clean_state_if_stale() is True
    assert not state_path.exists()


def test_status_report_does_not_expose_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBAGENT_LLM_ENABLED", "true")
    monkeypatch.setenv("JOBAGENT_LLM_API_KEY", "secret-value")
    config = RuntimeConfig.from_env()
    monkeypatch.setattr("jobagent_v2.local_runtime.clean_state_if_stale", lambda: False)
    monkeypatch.setattr("jobagent_v2.local_runtime.read_state", lambda: None)
    monkeypatch.setattr("jobagent_v2.local_runtime.port_owner", lambda *_args: None)
    monkeypatch.setattr(
        "jobagent_v2.local_runtime._worker_health",
        lambda *_args, **_kwargs: (False, None),
    )

    report = status_report(config)

    assert report["llm_api_key_configured"] is True
    assert "secret-value" not in repr(report)


def test_demo_local_refuses_default_database(monkeypatch: pytest.MonkeyPatch) -> None:
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import demo_local

        monkeypatch.delenv("JOBAGENT_DB_PATH", raising=False)
        monkeypatch.delenv("JOBAGENT_ARTIFACT_DIR", raising=False)
        monkeypatch.setattr("jobagent_v2.config.load_local_env", lambda *_args, **_kwargs: None)
        assert demo_local.main([]) == 1
    finally:
        sys.path.remove(str(scripts_dir))


def test_setup_local_preserves_env_and_creates_configured_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import setup_local

        (tmp_path / ".env.example").write_text(
            "JOBAGENT_DB_PATH=data/local-test/from-example.sqlite3\n"
            "JOBAGENT_ARTIFACT_DIR=data/local-test/example-artifacts\n",
            encoding="utf-8",
        )
        env_local = tmp_path / ".env.local"
        env_local.write_text(
            "JOBAGENT_DB_PATH=data/local-test/jobagent.sqlite3\n"
            "JOBAGENT_ARTIFACT_DIR=data/local-test/artifacts\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(setup_local, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(setup_local.subprocess, "run", lambda *_args, **_kwargs: None)

        assert setup_local.main() == 0

        assert "from-example" not in env_local.read_text(encoding="utf-8")
        assert (tmp_path / "data" / "local-test").is_dir()
        assert (tmp_path / "data" / "local-test" / "artifacts").is_dir()
    finally:
        sys.path.remove(str(scripts_dir))


def test_dev_up_child_startup_failure_terminates_started_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import dev_up

        monkeypatch.setenv("JOBAGENT_LLM_ENABLED", "false")
        monkeypatch.setattr("jobagent_v2.local_runtime.require_local_env", lambda: None)
        monkeypatch.setattr(
            "jobagent_v2.config.load_local_env",
            lambda: SimpleNamespace(exists=False, path=Path(".env.local")),
        )
        monkeypatch.setattr(
            "jobagent_v2.local_runtime.assert_ports_available",
            lambda _config: None,
        )
        monkeypatch.setattr(
            "jobagent_v2.local_runtime.assert_startup_config",
            lambda _config: None,
        )
        monkeypatch.setattr(
            "jobagent_v2.local_runtime.print_safe_config_summary",
            lambda _config: None,
        )
        monkeypatch.setattr("jobagent_v2.local_runtime.clean_state_if_stale", lambda: False)
        monkeypatch.setattr(dev_up, "_python_executable", lambda: sys.executable)
        real_sleep = dev_up.time.sleep
        monkeypatch.setattr(dev_up.time, "sleep", lambda _seconds: real_sleep(0.001))
        terminated: list[int] = []
        fake_processes: dict[int, object] = {}

        class FakeProcess:
            _next_pid = 4000

            def __init__(self, command: list[str], **_kwargs: object) -> None:
                self.command = command
                self.pid = FakeProcess._next_pid
                FakeProcess._next_pid += 1
                self.returncode = 2 if any("worker_runner" in part for part in command) else None
                self.stdout = StringIO("")
                fake_processes[self.pid] = self

            def poll(self) -> int | None:
                return self.returncode

            def send_signal(self, _signal: object) -> None:
                terminated.append(self.pid)
                self.returncode = 0

            def kill(self) -> None:
                terminated.append(self.pid)
                self.returncode = -9

        monkeypatch.setattr(dev_up.subprocess, "Popen", FakeProcess)
        monkeypatch.setattr(dev_up.os, "getpgid", lambda pid: pid)

        def fake_killpg(pid: int, _signal: object) -> None:
            terminated.append(pid)
            process = fake_processes.get(pid)
            if process is not None:
                process.returncode = 0

        monkeypatch.setattr(dev_up.os, "killpg", fake_killpg)

        assert dev_up.main(["--skip-preflight"]) == 1
        assert 4000 in terminated
    finally:
        sys.path.remove(str(scripts_dir))


def test_db_status_initializes_empty_database_and_rejects_future_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "jobagent.sqlite3"
    current = inspect_database(db_path, initialize=True)
    assert current["status"] == "current"
    assert current["schema_version"] == SCHEMA_VERSION

    future = tmp_path / "future.sqlite3"
    with sqlite3.connect(future) as connection:
        connection.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION + 1),),
        )
    assert inspect_database(future)["status"] == "unsupported_future_schema"
    with pytest.raises(RuntimeError, match="newer than supported"):
        Repository(future)


def test_repository_migrates_packet_idempotency_column_before_index(tmp_path: Path) -> None:
    db_path = tmp_path / "old-packets.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('schema_version', '8')"
        )
        connection.execute(
            """CREATE TABLE packets (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                q2_task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )

    Repository(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(packets)").fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(packets)").fetchall()
        }
    assert "idempotency_key" in columns
    assert "idx_packets_regen_idempotency" in indexes


def test_release_smoke_script_importable_and_passes() -> None:
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import release_smoke

        result = release_smoke.run_smoke()
    finally:
        sys.path.remove(str(scripts_dir))

    assert result["status"] == "pass"
    assert result["review_resolution_status"] == "complete"
