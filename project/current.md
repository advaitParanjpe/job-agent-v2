# Current Milestone

## Project Objective
`job-agent-v2` is a local-only job application queue and canonical
packet-generation system: capture job postings from a browser, store and
deduplicate them, run deterministic intake and scoring, promote suitable jobs
into packet generation, render approved canonical CV packets, process reviewed
packet outcomes, and expose the workflow through a local API, dashboard, and
Chrome extension.

## Current Verified State
- Capture, dedupe, deterministic intake, four-family classification,
  candidate-fit scoring, promotion, approved master-CV packet generation,
  bounded one-block tailoring, calibration evaluation, backend review APIs,
  minimal dashboard review workflow, and review-driven packet regeneration are
  implemented.
- Supported CV families remain `digital_ic`, `verification`, `software`, and
  `ml`.
- Canonical master CVs and approved project-block text are immutable.
- Tailoring remains bounded to at most one approved whole-project substitution.
- Classification, tailoring, review decisions, regeneration jobs, and packet
  attempts are persisted separately for auditability.
- Packet-changing review resolutions now create durable regeneration jobs.
- Successful reviewed outcomes create linked packet artifacts; previous ready
  packets remain available.
- Optional semantic evidence remains opt-in; standard validation is offline and
  deterministic.

## Recently Completed Milestone
Phase H: Review-Driven Packet Regeneration Worker.

Final status: COMPLETE.

Completion evidence:
- Added durable `review_regeneration_jobs` with queued, processing, complete,
  and failed states; lease owner/expiry; attempt counts; queued/started/
  completed/failed timestamps; safe failure code/reason; source packet; and
  generated packet linkage.
- Added reviewed packet metadata on `packets`: generation kind, source packet,
  review item, review resolution, idempotency key, and generation reason.
- Implemented `jobagent_v2.regeneration_worker` with atomic SQLite claiming,
  stale lease recovery, max-attempt retry policy, idempotent success reuse, and
  safe failure recording.
- Implemented reviewed family-master regeneration by copying approved master
  `.tex` and `.pdf` artifacts unchanged into a new packet directory.
- Implemented reviewed one-block project regeneration by revalidating approved
  blocks, replacing only the Projects section, validating immutable sections,
  validating one-page PDF output, and promoting artifacts only after checks
  pass.
- Preserved previous valid packet artifacts and original automated
  classification/tailoring/review records.
- Exposed regeneration processing through
  `POST /api/workers/regeneration/run-once` and
  `PYTHONPATH=backend/src python3 -m jobagent_v2.regeneration_worker --once`.
- Updated review API/dashboard status display for queued, processing, complete,
  and failed regeneration states with prior/reviewed packet links.
- Updated `docs/review_api.md` and `docs/bounded_tailoring.md`.
- Validation passed on 2026-06-30: `python3 scripts/check.py` reported 177
  backend tests passed, 2 local TeX compile tests skipped, plus frontend and
  extension checks.
- `git diff --check` passed on 2026-06-30.
- `git status --short` was inspected.
- Final diff was inspected for credentials, unsafe paths, generated clutter,
  accidental CV changes, and production database writes.

## Active Milestone
Operational Worker Scheduling and Monitoring.

## Why This Milestone Is Next
Phase H made reviewed packet regeneration real, but it is still triggered by a
manual command or local API call. The next highest-leverage step is to make the
existing Q1, Q2, and review-regeneration workers easier to run and observe
locally without changing canonical CV policy or adding application submission
features.

## Scope
- Document and/or add a single local worker loop command for Q1, Q2, promotion,
  and review regeneration.
- Expose concise local queue-health/status reporting for Q1, Q2, and review
  regeneration.
- Surface stale-job recovery counts and safe worker failure summaries.
- Keep all processing local-only, deterministic, and compatible with isolated
  test databases.
- Preserve canonical master CVs, approved project blocks, review append-only
  behavior, and packet artifact versioning.

## Out Of Scope
- Free-form CV generation or bullet rewriting.
- Changing classifier/tailoring thresholds automatically.
- Hosted services, credentials, production auth, paid integrations, or
  deployment.
- Application submission workflow integration.
- Broad dashboard redesign.

## Acceptance Criteria
- [ ] A local operator can run or document one command that processes all
      current local worker queues safely.
- [ ] Queue-health/status output includes Q1, Q2, and review-regeneration
      counts without exposing local filesystem paths.
- [ ] Stale lease recovery is visible and deterministic in tests.
- [ ] Existing Q1/Q2/regeneration APIs remain compatible.
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
- `backend/src/jobagent_v2/workers.py`
- `backend/src/jobagent_v2/regeneration_worker.py`
- `backend/src/jobagent_v2/service.py`
- `backend/src/jobagent_v2/api.py`
- `backend/src/jobagent_v2/storage.py`
- `docs/phase_1_api.md`
- `docs/review_api.md`
- `frontend/src/app.js`
- `frontend/scripts/test-dashboard.mjs`

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
- Long-running worker loops need careful shutdown behavior in local shells.
- Queue health should avoid leaking artifact paths or stack traces.
- Operational visibility should not become a broader dashboard redesign.

## Progress Log
- 2026-06-30: Operational Worker Scheduling and Monitoring selected after
  Phase H completion. No implementation started.
