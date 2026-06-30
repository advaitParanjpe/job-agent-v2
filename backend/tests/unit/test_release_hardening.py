from __future__ import annotations

import socket
import sqlite3
import sys
from pathlib import Path

import pytest

from jobagent_v2.config import RuntimeConfig
from jobagent_v2.db_status import inspect_database
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
    class OccupiedSocket:
        def __enter__(self) -> "OccupiedSocket":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def settimeout(self, _timeout: float) -> None:
            return None

        def connect_ex(self, address: tuple[str, int]) -> int:
            return 0 if address[1] == 8765 else 1

    monkeypatch.setattr("jobagent_v2.preflight.socket.socket", lambda *_args: OccupiedSocket())
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
