"""Release preflight checks for a local JobAgent checkout."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jobagent_v2.config import (
    LOCAL_ENV_FILENAME,
    RELEASE_VERSION,
    REPO_ROOT,
    RuntimeConfig,
    load_local_env,
)
from jobagent_v2.db_status import inspect_database
from jobagent_v2.family_classifier import load_classifier_config
from jobagent_v2.local_runtime import port_owner
from jobagent_v2.master_cvs import MasterCVValidationError, discover_master_cvs
from jobagent_v2.project_blocks import load_project_block_registry
from jobagent_v2.tailoring import load_tailoring_policy


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str
    blocking: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_preflight(
    *,
    config: RuntimeConfig | None = None,
    strict_latex: bool = False,
    check_ports: bool = True,
) -> dict[str, Any]:
    cfg = config or RuntimeConfig.from_env()
    checks = [
        _check_python(),
        _check_package("pypdf"),
        _check_package("openai"),
        _check_local_env(),
        _check_llm_config(cfg),
        _check_writable_directory(cfg.data_dir, "data_directory"),
        _check_writable_directory(cfg.artifact_dir, "artifact_directory"),
        _check_master_cvs(),
        _check_project_registry(),
        _check_classifier_config(),
        _check_tailoring_policy(),
        _check_database(cfg.db_path),
        _check_frontend_files(),
        _check_extension_files(),
        _check_latex(cfg.latex_executable, strict=strict_latex),
    ]
    if check_ports:
        checks.extend([
            _check_port(cfg.api_host, cfg.api_port, "api_port"),
            _check_port(cfg.frontend_host, cfg.frontend_port, "frontend_port"),
        ])
    failures = [item for item in checks if item.blocking and item.status == "fail"]
    warnings = [item for item in checks if item.status == "warn"]
    return {
        "release_version": RELEASE_VERSION,
        "ok": not failures,
        "checks": [item.to_dict() for item in checks],
        "blocking_failures": len(failures),
        "warnings": len(warnings),
        "config": cfg.safe_dict(),
    }


def _check_python() -> CheckResult:
    if sys.version_info < (3, 11):
        return CheckResult("python_version", "fail", "Python 3.11 or newer is required.", True)
    return CheckResult("python_version", "pass", sys.version.split()[0])


def _check_package(name: str) -> CheckResult:
    if importlib.util.find_spec(name) is None:
        return CheckResult(f"python_package:{name}", "fail", f"Missing package: {name}", True)
    return CheckResult(f"python_package:{name}", "pass", "available")


def _check_local_env() -> CheckResult:
    path = REPO_ROOT / LOCAL_ENV_FILENAME
    if not path.exists():
        return CheckResult("local_env", "pass", ".env.local not present; using process environment")
    return CheckResult("local_env", "pass", ".env.local present; secrets are redacted")


def _check_llm_config(config: RuntimeConfig) -> CheckResult:
    errors = config.validate_llm_startup()
    if errors:
        return CheckResult("llm_config", "fail", " ".join(errors), True)
    if config.semantic_enabled:
        return CheckResult("llm_config", "pass", "semantic evidence enabled; API key configured")
    return CheckResult(
        "llm_config",
        "pass",
        "semantic evidence disabled; deterministic behavior is used where supported",
    )


def _check_writable_directory(path: Path, name: str) -> CheckResult:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".jobagent_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return CheckResult(name, "fail", "Directory is not writable.", True)
    return CheckResult(name, "pass", "writable")


def _check_master_cvs() -> CheckResult:
    try:
        records = discover_master_cvs()
    except MasterCVValidationError as error:
        return CheckResult("master_cvs", "fail", str(error), True)
    families = sorted(record.family_id for record in records)
    return CheckResult("master_cvs", "pass", f"validated families: {', '.join(families)}")


def _check_project_registry() -> CheckResult:
    try:
        registry = load_project_block_registry()
    except Exception as error:
        return CheckResult("project_block_registry", "fail", str(error), True)
    return CheckResult("project_block_registry", "pass", str(registry["schema_version"]))


def _check_classifier_config() -> CheckResult:
    try:
        config = load_classifier_config()
    except Exception as error:
        return CheckResult("family_classifier_config", "fail", str(error), True)
    return CheckResult("family_classifier_config", "pass", str(config["config_version"]))


def _check_tailoring_policy() -> CheckResult:
    try:
        policy = load_tailoring_policy()
    except Exception as error:
        return CheckResult("tailoring_policy", "fail", str(error), True)
    return CheckResult("tailoring_policy", "pass", str(policy["policy_version"]))


def _check_database(path: Path) -> CheckResult:
    try:
        status = inspect_database(path, initialize=True)
    except Exception as error:
        return CheckResult("database", "fail", str(error), True)
    if status["status"] == "unsupported_future_schema":
        return CheckResult("database", "fail", "Database schema is newer than supported.", True)
    return CheckResult("database", "pass", f"schema {status.get('schema_version')}")


def _check_frontend_files() -> CheckResult:
    required = [Path("frontend/src/index.html"), Path("frontend/src/app.js")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        return CheckResult("frontend_files", "fail", f"missing: {', '.join(missing)}", True)
    return CheckResult("frontend_files", "pass", "present")


def _check_extension_files() -> CheckResult:
    required = [Path("extension/manifest.json"), Path("extension/popup.js")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        return CheckResult("extension_files", "fail", f"missing: {', '.join(missing)}", True)
    return CheckResult("extension_files", "pass", "present")


def _check_latex(executable: str, *, strict: bool) -> CheckResult:
    if shutil.which(executable) is None:
        return CheckResult(
            "latex",
            "fail" if strict else "warn",
            "pdflatex unavailable; master-copy packets work, tailored compilation will fail.",
            strict,
        )
    return CheckResult("latex", "pass", f"{executable} available")


def _check_port(host: str, port: int, name: str) -> CheckResult:
    owner = port_owner(host, port)
    if owner is not None:
        message = (
            f"{owner.describe()}. Inspect with: "
            f"lsof -nP -iTCP:{port} -sTCP:LISTEN. "
            "If this is a previous job-agent-v2 stack, run ./scripts/dev-down."
        )
        return CheckResult(name, "fail", message, True)
    return CheckResult(name, "pass", f"{host}:{port} available")


def main(argv: list[str] | None = None) -> int:
    load_local_env()
    parser = argparse.ArgumentParser(description="Run local release preflight checks.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--strict-latex", action="store_true")
    parser.add_argument("--skip-port-check", action="store_true")
    args = parser.parse_args(argv)
    result = run_preflight(
        strict_latex=args.strict_latex,
        check_ports=not args.skip_port_check,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"JobAgent V2 v{result['release_version']} preflight")
        for item in result["checks"]:
            print(f"{item['status'].upper():4} {item['name']}: {item['message']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
