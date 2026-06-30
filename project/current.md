# Current Milestone

## Project Objective
`job-agent-v2` is a local-only job application queue and canonical
packet-generation system: capture job postings from a browser, store and
deduplicate them, run deterministic intake and scoring, promote suitable jobs
into packet generation, render approved canonical CV packets, process reviewed
packet outcomes, and expose the workflow through a local API, dashboard,
Chrome extension, and local worker loops.

## Current Verified State
- Capture, dedupe, deterministic intake, four-family classification,
  candidate-fit scoring, promotion, approved master-CV packet generation,
  bounded one-block tailoring, calibration evaluation, backend review APIs,
  minimal dashboard review workflow, review-driven packet regeneration, and
  operational worker scheduling/monitoring are implemented.
- Supported CV families remain `digital_ic`, `verification`, `software`, and
  `ml`.
- Canonical master CVs and approved project-block text are immutable.
- Tailoring remains bounded to at most one approved whole-project substitution.
- Classification, tailoring, review decisions, regeneration jobs, worker
  status, and packet attempts are persisted separately for auditability.
- Q1, Q2, and review-regeneration workers can run continuously through
  `jobagent_v2.worker_runner`.
- Worker/queue health is visible through local API endpoints and the dashboard.
- Successful reviewed outcomes create linked packet artifacts; previous ready
  packets remain available.
- Optional semantic evidence remains opt-in; standard validation is offline and
  deterministic.

## Recently Completed Milestone
Operational Worker Scheduling and Monitoring.

Final status: COMPLETE.

Completion evidence:
- Added `jobagent_v2.worker_runner` with independently runnable `q1`, `q2`,
  and `regeneration` loops, plus combined `--all` mode.
- Wrapped existing run-once worker logic rather than duplicating Q1, Q2, or
  regeneration business behavior.
- Added environment-backed polling intervals, deterministic idle backoff,
  heartbeat settings, graceful SIGINT/SIGTERM handling, and per-job failure
  isolation.
- Added durable `worker_instances` and `worker_events` tables for current
  status, bounded event history, current/last jobs, processed/failure counts,
  heartbeats, and runner version.
- Added queue summaries from existing `jobs`, `q2_tasks`, and
  `review_regeneration_jobs`, including queued/processing/failed counts,
  retryable counts, oldest queued timestamps, stale processing counts, and
  retry-exhausted counts.
- Added `GET /api/workers/status`, `GET /api/workers/{worker_type}/status`,
  and `GET /api/workers/queues`.
- Added compact dashboard worker monitoring for Q1, Q2, and regeneration
  status, queue counts, stale/failure warnings, current job, and last
  success/failure.
- Added safe JSON operational logs that avoid CV content, full JDs, review
  notes, secrets, stack traces, and raw artifact paths.
- Added `docs/worker_operations.md` and updated API/README documentation.
- Validation passed on 2026-06-30: `python3 scripts/check.py` reported 184
  backend tests passed, 2 local TeX compile tests skipped, plus frontend and
  extension checks.
- `git diff --check` passed on 2026-06-30.
- `git status --short` was inspected.
- Final diff was inspected for secrets, PII in logs, unsafe paths, generated
  clutter, accidental CV edits, and production database writes.

## Active Milestone
End-to-end Release Hardening.

## Why This Milestone Is Next
The core local workflow now exists from capture through reviewed packet
regeneration and operational worker monitoring. The next step should make that
workflow easier to validate, install, and run reliably without changing the
canonical CV policy or adding free-form generation.

## Scope
- Add or update end-to-end smoke documentation/checks for capture through
  reviewed packet regeneration.
- Verify package data for required JSON config, templates, master CVs,
  frontend assets, and extension assets.
- Clarify local setup checks for Python, Node, LaTeX, and optional live
  semantic credentials.
- Document local SQLite migration/backup expectations.
- Document the CI-equivalent validation path around `python3 scripts/check.py`.

## Out Of Scope
- Free-form CV generation or bullet rewriting.
- Changing classifier/tailoring thresholds automatically.
- Production authentication or multi-user hardening.
- Hosted services, credentials, paid integrations, or deployment.
- Application submission workflow integration.
- Broad dashboard redesign.

## Acceptance Criteria
- [ ] A local operator can follow documented checks from API startup through
      worker execution and reviewed packet regeneration.
- [ ] Required package data is verified by tests or explicit checks.
- [ ] Setup documentation covers Python, Node, LaTeX, worker loops, API,
      dashboard, extension, and optional live semantic settings.
- [ ] Local SQLite backup/migration guidance is documented.
- [ ] Existing Q1/Q2/regeneration APIs and worker status APIs remain
      compatible.
- [ ] `python3 scripts/check.py` passes.
- [ ] `git diff --check` passes.
- [ ] `git status --short` is inspected.
- [ ] Final status is set to `COMPLETE` only after validation passes and
      history/roadmap/current are updated.

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
- `docs/phase_1_api.md`
- `docs/review_api.md`
- `docs/worker_operations.md`
- `scripts/check.py`
- `pyproject.toml`
- `backend/src/jobagent_v2/worker_runner.py`
- `backend/src/jobagent_v2/storage.py`
- `backend/src/jobagent_v2/api.py`
- `frontend/src/app.js`
- `extension/`

## Decisions And Constraints
- Source code, tests, and reproducible commands are stronger evidence than
  stale phase reports.
- Older `docs/build_reports/*` files are historical snapshots.
- The product boundary from ADR-001 remains active: no generated CV prose.
- Keep offline validation deterministic.
- Preserve local-only operation and SQLite persistence.
- Do not touch `data/jobagent_v2.sqlite3`.
- Do not begin implementation of this milestone unless explicitly requested.

## Known Risks
- End-to-end smoke checks must use isolated databases and artifact roots.
- Local TeX availability remains environment-dependent.
- Release hardening should not drift into hosted deployment or auth work.

## Progress Log
- 2026-06-30: End-to-end Release Hardening selected after Operational Worker
  Scheduling and Monitoring completion. No implementation started.
