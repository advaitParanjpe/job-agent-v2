"""Runtime configuration helpers for local release commands."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


RELEASE_VERSION = "0.1.0"
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8765
DEFAULT_FRONTEND_HOST = "127.0.0.1"
DEFAULT_FRONTEND_PORT = 5173
DEFAULT_DATA_DIR = Path("data")
DEFAULT_ARTIFACT_DIR = DEFAULT_DATA_DIR / "artifacts"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "jobagent_v2.sqlite3"


@dataclass(frozen=True)
class RuntimeConfig:
    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT
    frontend_host: str = DEFAULT_FRONTEND_HOST
    frontend_port: int = DEFAULT_FRONTEND_PORT
    data_dir: Path = DEFAULT_DATA_DIR
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR
    db_path: Path = DEFAULT_DB_PATH
    owner_id: str = "local"
    q1_poll_seconds: float = 5.0
    q2_poll_seconds: float = 5.0
    regeneration_poll_seconds: float = 5.0
    heartbeat_seconds: float = 10.0
    stale_processing_seconds: int = 900
    max_retry_attempts: int = 3
    semantic_enabled: bool = False
    semantic_model: str = "gpt-4o-mini"
    semantic_api_key_present: bool = False
    latex_executable: str = "pdflatex"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        data_dir = Path(os.getenv("JOBAGENT_DATA_DIR", str(DEFAULT_DATA_DIR)))
        artifact_dir = Path(os.getenv("JOBAGENT_ARTIFACT_DIR", str(data_dir / "artifacts")))
        return cls(
            api_host=os.getenv("JOBAGENT_API_HOST", DEFAULT_API_HOST),
            api_port=_port_env("JOBAGENT_API_PORT", DEFAULT_API_PORT),
            frontend_host=os.getenv("JOBAGENT_FRONTEND_HOST", DEFAULT_FRONTEND_HOST),
            frontend_port=_port_env("JOBAGENT_FRONTEND_PORT", DEFAULT_FRONTEND_PORT),
            data_dir=data_dir,
            artifact_dir=artifact_dir,
            db_path=Path(os.getenv("JOBAGENT_DB_PATH", str(data_dir / "jobagent_v2.sqlite3"))),
            owner_id=os.getenv("JOBAGENT_OWNER_ID", "local") or "local",
            q1_poll_seconds=_positive_float("JOBAGENT_Q1_POLL_SECONDS", 5.0),
            q2_poll_seconds=_positive_float("JOBAGENT_Q2_POLL_SECONDS", 5.0),
            regeneration_poll_seconds=_positive_float(
                "JOBAGENT_REGENERATION_POLL_SECONDS", 5.0
            ),
            heartbeat_seconds=_positive_float("JOBAGENT_HEARTBEAT_SECONDS", 10.0),
            stale_processing_seconds=_positive_int("JOBAGENT_STALE_PROCESSING_SECONDS", 900),
            max_retry_attempts=_positive_int("JOBAGENT_MAX_RETRY_ATTEMPTS", 3),
            semantic_enabled=os.getenv("JOBAGENT_LLM_ENABLED", "false").lower() == "true",
            semantic_model=os.getenv("JOBAGENT_LLM_MODEL", "gpt-4o-mini"),
            semantic_api_key_present=bool(os.getenv("JOBAGENT_LLM_API_KEY")),
            latex_executable=os.getenv("JOBAGENT_LATEX_EXECUTABLE", "pdflatex"),
            log_level=os.getenv("JOBAGENT_LOG_LEVEL", "INFO"),
        )

    def safe_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["data_dir"] = str(self.data_dir)
        value["artifact_dir"] = str(self.artifact_dir)
        value["db_path"] = str(self.db_path)
        value["semantic_api_key"] = "<redacted>" if self.semantic_api_key_present else None
        return value


def _port_env(name: str, default: int) -> int:
    value = _positive_int(name, default)
    if value > 65535:
        raise ValueError(f"{name} must be a valid TCP port")
    return value


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value
