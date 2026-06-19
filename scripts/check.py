#!/usr/bin/env python3
"""Run Phase 0B bootstrap checks without requiring network installs."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
PYTHON_FILES = [
    *sorted((ROOT / "backend" / "src").rglob("*.py")),
    *sorted((ROOT / "backend" / "tests").rglob("*.py")),
    *sorted((ROOT / "scripts").rglob("*.py")),
]


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(command)}")
    subprocess.run(command, cwd=cwd, env=env, check=True)


def check_format() -> None:
    bad: list[str] = []
    for path in PYTHON_FILES:
        text = path.read_text(encoding="utf-8")
        if not text.endswith("\n"):
            bad.append(f"{path}: missing trailing newline")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip() != line:
                bad.append(f"{path}:{line_number}: trailing whitespace")
            if len(line) > 100:
                bad.append(f"{path}:{line_number}: line longer than 100 characters")
    if bad:
        raise SystemExit("\n".join(bad))
    print("format check passed")


def check_lint() -> None:
    for path in PYTHON_FILES:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print("lint check passed")


def check_types() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_SRC)
    run(
        [
            sys.executable,
            "-c",
            "from jobagent_v2 import create_app_metadata; "
            "m=create_app_metadata(); "
            "assert isinstance(m['name'], str); "
            "assert m['implements_features'] is False",
        ],
        env=env,
    )
    print("type-oriented import contract passed")


def check_extension_manifest() -> None:
    manifest_path = ROOT / "extension" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 3:
        raise SystemExit("extension manifest must use MV3")
    if not manifest.get("action", {}).get("default_popup"):
        raise SystemExit("extension manifest must define an action popup")
    print("extension manifest check passed")


def main() -> None:
    check_format()
    check_lint()
    check_types()
    check_extension_manifest()
    run([sys.executable, "-m", "pytest"])
    run(["npm", "run", "build"], cwd=ROOT / "frontend")
    run(["node", "scripts/validate.mjs"], cwd=ROOT / "extension")


if __name__ == "__main__":
    main()

