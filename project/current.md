# Current Milestone

## Project Objective
`job-agent-v2` is a local-only job application queue and canonical
packet-generation system: capture job postings from a browser, store and
deduplicate them, run deterministic intake and scoring, promote suitable jobs
into packet generation, render approved canonical CV packets, process reviewed
packet outcomes, and expose the workflow through a local API, dashboard,
Chrome extension, and local worker loops.

## Current Verified State
- Release candidate: `job-agent-v2 v0.1.0`.
- Capture, dedupe, deterministic intake, four-family classification,
  candidate-fit scoring, promotion, approved master-CV packet generation,
  bounded one-block tailoring, calibration evaluation, backend review APIs,
  minimal dashboard review workflow, review-driven packet regeneration,
  operational worker scheduling/monitoring, release preflight diagnostics,
  database status inspection, local startup coordination, demo seeding, and an
  isolated release smoke flow are implemented.
- Supported CV families remain `digital_ic`, `verification`, `software`, and
  `ml`.
- Canonical master CVs and approved project-block text are immutable.
- Tailoring remains bounded to at most one approved whole-project substitution.
- Classification, tailoring, review decisions, regeneration jobs, worker
  status, and packet attempts are persisted separately for auditability.
- Q1, Q2, and review-regeneration workers can run continuously through
  `jobagent_v2.worker_runner` or `./scripts/dev-up`.
- Worker/queue health is visible through local API endpoints and the dashboard.
- Successful reviewed outcomes create linked packet artifacts; previous ready
  packets remain available.
- Optional semantic evidence remains opt-in; standard validation is offline and
  deterministic.

## Recently Completed Milestone
End-to-End Release Hardening.

Final status: COMPLETE.

Completion evidence:
- Added release configuration, preflight diagnostics, database schema
  inspection, local stack startup, isolated release smoke testing, and
  deterministic demo seeding.
- Repaired migration ordering for older packet schemas before creating the
  regeneration idempotency index.
- Updated README, release checklist, worker operations docs, changelog, and
  release version metadata.
- Validation passed on 2026-06-30:
  `PYTHONPATH=backend/src pytest backend/tests/unit/test_release_hardening.py -q`
  reported 7 passed.
- `python3 scripts/release_smoke.py` passed using an isolated temporary
  database and artifact root.
- `python3 scripts/demo_seed.py --db-path /tmp/jobagent-demo-seed.sqlite3 --artifact-root /tmp/jobagent-demo-artifacts`
  created 7 synthetic jobs.
- `PYTHONPATH=backend/src python3 -m jobagent_v2.preflight --json --skip-port-check`
  passed.
- `python3 scripts/check.py` reported 191 backend tests passed, 2 local TeX
  compile tests skipped, plus frontend and extension checks.
- `git diff --check` passed.
- `git status --short` was inspected.
- `python3 -m build` was attempted but the active environment lacked the
  `build` module; `build>=1.2` is now in the dev extra for clean release
  environments.

## Active Milestone
No active implementation milestone.

## Next State
The repository is ready for manual release-candidate evaluation of
`job-agent-v2 v0.1.0`.

Do not begin a new implementation milestone automatically. If release
evaluation finds a blocker, record that narrow blocker here before coding.

## Candidate Next Milestones
- Packaging and one-command local startup polish if release evaluation finds
  startup or packaging gaps.
- Production authentication and multi-user hardening if the product boundary
  changes beyond local owner scoping.
- Reviewed real-job dataset expansion for calibration evidence.
- Application workflow integration.

Do not select free-form resume generation.

## Validation Commands
```bash
python3 scripts/check.py
git diff --check
git status --short
```

## Relevant Files
- `project/current.md`
- `project/roadmap.md`
- `project/history.md`
- `README.md`
- `CHANGELOG.md`
- `docs/release_checklist.md`
- `docs/worker_operations.md`
- `docs/review_api.md`
- `docs/bounded_tailoring.md`
- `docs/calibration.md`
- `scripts/dev-up`
- `scripts/dev_up.py`
- `scripts/release_smoke.py`
- `scripts/demo_seed.py`
- `scripts/check.py`
- `pyproject.toml`
- `backend/src/jobagent_v2/preflight.py`
- `backend/src/jobagent_v2/db_status.py`
- `backend/src/jobagent_v2/config.py`

## Decisions And Constraints
- Source code, tests, and reproducible commands are stronger evidence than
  stale phase reports.
- Older `docs/build_reports/*` files are historical snapshots.
- The product boundary from ADR-001 remains active: no generated CV prose.
- Keep offline validation deterministic.
- Preserve local-only operation and SQLite persistence.
- Preserve canonical master CVs and approved project-block text.
- Do not touch `data/jobagent_v2.sqlite3` during tests; use isolated databases
  for automated validation.

## Known Risks
- Local TeX availability remains environment-dependent.
- `python3 -m build` requires the `build` package from the dev extra in a clean
  environment.
- The release candidate is local-first and not production-authenticated.

## Progress Log
- 2026-06-30: End-to-End Release Hardening completed and recorded. No active
  implementation milestone remains; release candidate is ready for manual
  evaluation.
