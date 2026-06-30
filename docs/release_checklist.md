# JobAgent V2 Release Checklist

Target release candidate: `job-agent-v2 v0.1.0`.

Complete this checklist from a clean checkout before tagging a release.

## Repository

- [ ] `git status --short` contains only intentional release changes.
- [ ] No generated `__pycache__`, test databases, local logs, temporary PDFs,
      build outputs, or OS metadata are tracked.
- [ ] No credentials, semantic API keys, private job descriptions, phone
      numbers, email addresses, or review notes are committed.
- [ ] Canonical `master-cvs/` files are byte-for-byte unchanged unless the
      release explicitly approves a canonical CV update.
- [ ] Approved project-block registry text is unchanged unless the release
      explicitly approves registry content changes.

## Install And Package

- [ ] Python 3.11 or newer is installed.
- [ ] `python3 -m venv .venv-release` succeeds.
- [ ] `source .venv-release/bin/activate` succeeds.
- [ ] `pip install -e ".[dev]"` succeeds.
- [ ] `python3 -m build` succeeds or missing build tooling is documented.
- [ ] Required JSON config and TeX templates are present from an editable
      install.

## Preflight And Migration

- [ ] `PYTHONPATH=backend/src python3 -m jobagent_v2.preflight` reports no
      blocking failures.
- [ ] LaTeX absence is reported as an optional warning unless strict tailored
      generation is required.
- [ ] `PYTHONPATH=backend/src python3 -m jobagent_v2.db_status --db-path ...`
      reports the supported schema.
- [ ] Empty database initialization is verified.
- [ ] Repeated initialization is idempotent.
- [ ] Unsupported future schema failure is verified.
- [ ] Production/local user database is not modified by tests.

## End-To-End

- [ ] `python3 scripts/release_smoke.py` passes.
- [ ] `python3 scripts/demo_seed.py --db-path /tmp/jobagent-demo.sqlite3`
      creates deterministic synthetic jobs when demo data is desired.
- [ ] Queue 1 scoring and four-family classification are exercised.
- [ ] Queue 2 packet generation creates a ready packet.
- [ ] Review resolution queues regeneration.
- [ ] Regeneration creates a linked reviewed packet.
- [ ] Previous ready packet remains retrievable.
- [ ] Worker status and queue summaries are visible.
- [ ] Failure/retry behavior is visible and does not corrupt prior artifacts.

## Services

- [ ] `./scripts/dev-up` starts API, workers, and frontend.
- [ ] Startup fails clearly when a required port is occupied.
- [ ] `Ctrl-C` terminates child processes.
- [ ] API restart does not corrupt jobs, reviews, workers, or packets.
- [ ] Worker restart recovers stale eligible work.
- [ ] Dashboard renders empty database, worker offline, failed regeneration,
      and reviewed-packet states.
- [ ] Chrome extension can capture a supported local job payload.

## Validation

- [ ] `python3 scripts/check.py` passes.
- [ ] `git diff --check` passes.
- [ ] Frontend manual check passes at the documented local URL.
- [ ] Extension manual check passes against the local API.
- [ ] Release notes and README match actual commands.
- [ ] Known limitations are documented.
