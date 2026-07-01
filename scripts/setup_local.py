#!/usr/bin/env python3
"""Prepare a local checkout for one-command JobAgent startup."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"


def main() -> int:
    sys.path.insert(0, str(BACKEND_SRC))
    from jobagent_v2.config import RuntimeConfig, load_local_env

    venv_dir = REPO_ROOT / ".venv"
    if not venv_dir.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], cwd=REPO_ROOT, check=True)
        print("Created .venv")
    else:
        print("Preserved existing .venv")
    python = venv_dir / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", "-e", ".[dev]"],
        cwd=REPO_ROOT,
        check=True,
    )

    env_example = REPO_ROOT / ".env.example"
    env_local = REPO_ROOT / ".env.local"
    preserved = env_local.exists()
    if preserved:
        print("Preserved existing .env.local")
    else:
        env_local.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env.local from .env.example")

    load_local_env(env_local)
    config = RuntimeConfig.from_env()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    config.db_path.parent.mkdir(parents=True, exist_ok=True)

    print()
    print("Local setup complete.")
    print()
    print("1. Open .env.local")
    print("2. Set JOBAGENT_LLM_API_KEY")
    print("3. Run ./scripts/dev-up")
    print(f"4. Open http://{config.frontend_host}:{config.frontend_port}")
    print()
    print(f"Paste the API key on the JOBAGENT_LLM_API_KEY line in {env_local}")
    if preserved:
        print(".env.local was preserved and not overwritten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
