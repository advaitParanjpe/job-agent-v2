"""Runtime configuration helpers for local release commands."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_VERSION = "0.1.0"
LOCAL_ENV_FILENAME = ".env.local"
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8765
DEFAULT_FRONTEND_HOST = "127.0.0.1"
DEFAULT_FRONTEND_PORT = 5173
DEFAULT_DATA_DIR = Path("data")
DEFAULT_ARTIFACT_DIR = DEFAULT_DATA_DIR / "artifacts"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "jobagent_v2.sqlite3"
PLACEHOLDER_API_KEYS = {"YOUR_API_KEY_HERE", "replace-me", "changeme", "replace-with-local-key"}


@dataclass(frozen=True)
class LocalEnvLoadResult:
    path: Path
    exists: bool
    loaded_keys: tuple[str, ...]
    skipped_keys: tuple[str, ...]


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
    semantic_api_key_placeholder: bool = False
    latex_executable: str = "pdflatex"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        data_dir = Path(os.getenv("JOBAGENT_DATA_DIR", str(DEFAULT_DATA_DIR)))
        artifact_dir = Path(os.getenv("JOBAGENT_ARTIFACT_DIR", str(data_dir / "artifacts")))
        api_key = os.getenv("JOBAGENT_LLM_API_KEY", "")
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
            semantic_api_key_present=bool(api_key),
            semantic_api_key_placeholder=api_key.strip() in PLACEHOLDER_API_KEYS,
            latex_executable=os.getenv("JOBAGENT_LATEX_EXECUTABLE", "pdflatex"),
            log_level=os.getenv("JOBAGENT_LOG_LEVEL", "INFO"),
        )

    def safe_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["data_dir"] = str(self.data_dir)
        value["artifact_dir"] = str(self.artifact_dir)
        value["db_path"] = str(self.db_path)
        value["semantic_api_key"] = redacted_secret(
            "configured" if self.semantic_api_key_present else ""
        )
        return value

    def llm_summary_lines(self) -> list[str]:
        return [
            f"LLM semantic classification: {'enabled' if self.semantic_enabled else 'disabled'}",
            f"LLM model: {self.semantic_model}",
            "LLM API key: configured" if self.semantic_api_key_present else "LLM API key: missing",
        ]

    def validate_llm_startup(self) -> list[str]:
        errors: list[str] = []
        if self.semantic_api_key_placeholder:
            errors.append(
                "JOBAGENT_LLM_API_KEY is an obvious placeholder; paste a real key or set "
                "JOBAGENT_LLM_ENABLED=false for deterministic local operation."
            )
        if self.semantic_enabled and not self.semantic_api_key_present:
            errors.append(
                "JOBAGENT_LLM_ENABLED=true but JOBAGENT_LLM_API_KEY is missing. "
                "Set the key in .env.local, or set JOBAGENT_LLM_ENABLED=false to run "
                "with deterministic behavior where supported."
            )
        return errors


def load_local_env(
    path: Path | None = None,
    *,
    override: bool = False,
) -> LocalEnvLoadResult:
    """Load repository-local dotenv settings into os.environ."""
    env_path = path or REPO_ROOT / LOCAL_ENV_FILENAME
    if not env_path.exists():
        return LocalEnvLoadResult(env_path, False, (), ())
    loaded: list[str] = []
    skipped: list[str] = []
    for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), 1):
        parsed = _parse_env_line(raw_line, line_number, env_path)
        if parsed is None:
            continue
        key, value = parsed
        if not override and key in os.environ:
            skipped.append(key)
            continue
        os.environ[key] = value
        loaded.append(key)
    return LocalEnvLoadResult(env_path, True, tuple(loaded), tuple(skipped))


def redacted_secret(value: str | None) -> str | None:
    return "<redacted>" if value else None


def _parse_env_line(raw_line: str, line_number: int, path: Path) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export "):].lstrip()
    if "=" not in line:
        raise ValueError(f"{path}:{line_number}: expected KEY=value")
    key, value = line.split("=", 1)
    key = key.strip()
    if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
        raise ValueError(f"{path}:{line_number}: invalid environment variable name")
    return key, _parse_env_value(value.strip(), line_number, path)


def _parse_env_value(value: str, line_number: int, path: Path) -> str:
    if not value:
        return ""
    quote = value[0]
    if quote in {"'", '"'}:
        if len(value) < 2 or value[-1] != quote:
            raise ValueError(f"{path}:{line_number}: unterminated quoted value")
        inner = value[1:-1]
        if quote == '"':
            return bytes(inner, "utf-8").decode("unicode_escape")
        return inner
    comment_index = value.find(" #")
    if comment_index >= 0:
        value = value[:comment_index]
    return value.strip()


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
