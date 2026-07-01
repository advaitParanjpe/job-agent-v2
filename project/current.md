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
  database status inspection, local setup/status/shutdown commands, `.env.local`
  local configuration loading, demo seeding, and an isolated release smoke flow
  are implemented.
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

## Active Milestone
No active implementation milestone.

## Recently Completed Milestone
Archived Job Restore/Re-Score and Semantic Requirement Extraction.

Final status: COMPLETE.

Completion evidence:
- Reproduced the misleading `already queued` path: duplicate capture matched
  an archived row by normalized URL, returned its stale `intake_status='queued'`,
  and the extension mapped every duplicate to "Already queued"; no active Q2
  task was required.
- Added structured capture outcomes for `created`, `existing_active`,
  `existing_complete`, `existing_archived`, and `existing_failed`.
- Added owner-scoped `restore`, `rescore`, `restore-and-rescore`, and
  `analyses` API/service paths.
- Added additive `analysis_runs` persistence, latest-run pointers, active-run
  idempotency, and append-only score/classification/semantic history.
- Re-score uses captured local content and does not refresh the live posting.
- Restore preserves previous analyses, packets, reviews, and audit records and
  does not enqueue work unless explicitly requested.
- Frontend/extension status language no longer says `Already queued` for
  archived or completed duplicates; job details expose re-score, restore, and
  previous analyses.
- Added grounded semantic requirement validation, approved-capability ontology
  checks, negation/marketing/IT-hardware rejection, deterministic plus semantic
  fusion, semantic-only confidence discounting, and conservative project
  integration through the existing requirement-aware portfolio path.
- Added `./scripts/semantic-requirements-check` and
  `scripts/evaluate_semantic_requirements.py`.
- Semantic requirement extraction remains feature-flagged/fallback-first; the
  live diagnostic ran but returned `response_invalid`, so live semantic fusion
  was not promoted from provider evidence.
- Validation passed on 2026-07-01:
  `PYTHONPATH=backend/src pytest backend/tests/unit -q` reported 179 passed,
  2 skipped.
- `node frontend/scripts/test-dashboard.mjs` passed.
- `python3 scripts/evaluate_cross_domain_portfolio.py` passed with 6 examples,
  shortlist recall 1.0, unexpected shortlist rate 0.0, and no failures.
- `PYTHONPATH=backend/src python3 scripts/evaluate_semantic_requirements.py`
  passed with 6 examples, capability precision 1.0, capability recall 1.0,
  and semantic-only false positives 0.
- `./scripts/semantic-requirements-check --no-network` reported
  `simulated_success`.
- `./scripts/semantic-requirements-check` ran with the configured local
  credential without printing it and failed safely as `response_invalid`.
- `python3 scripts/check.py` reported 221 passed, 2 skipped, plus frontend and
  extension checks.
- `git diff --check` passed.
- `git status --short` was inspected.
- Isolated startup smoke with `/tmp` DB/artifacts and alternate ports printed
  startup/worker logs and stopped cleanly, but API probes from the tool
  environment could not connect to the alternate API port; direct API/service
  restore-flow tests covered the behavior.

## Next State
The repository has no active implementation milestone.

Do not begin a broad new implementation milestone unless the user explicitly
asks.

## Candidate Next Milestones
- Packaging polish if release evaluation finds packaging gaps.
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
- `scripts/setup-local`
- `scripts/setup_local.py`
- `scripts/dev-down`
- `scripts/dev_down.py`
- `scripts/dev-status`
- `scripts/dev_status.py`
- `scripts/demo-local`
- `scripts/demo_local.py`
- `scripts/live_llm_smoke.py`
- `.env.example`
- `scripts/release_smoke.py`
- `scripts/demo_seed.py`
- `scripts/check.py`
- `pyproject.toml`
- `backend/src/jobagent_v2/preflight.py`
- `backend/src/jobagent_v2/db_status.py`
- `backend/src/jobagent_v2/config.py`
- `backend/src/jobagent_v2/local_runtime.py`
- `backend/src/jobagent_v2/llm_client.py`

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
- Live semantic classification still requires the operator to provide a local
  API key and explicitly enable it in `.env.local`.

## Progress Log
- 2026-07-01: Started Archived Job Restore/Re-Score and Semantic Requirement
  Extraction. Initial work is tracing current capture/deduplication, archive,
  queue idempotency, packet preservation, and requirement/project-selection
  paths before changing user-facing messages.
- 2026-07-01: Reproduced archived duplicate behavior in an isolated SQLite DB:
  duplicate capture matched `jobs.normalized_url`, returned the archived row
  with stale `intake_status='queued'`, and the extension mapped all duplicates
  to "Already queued"; no active Q2 row was involved in the repro.
- 2026-07-01: Added structured duplicate outcomes, owner-scoped restore,
  restore-and-re-score, manual re-score, analysis history, additive
  `analysis_runs` persistence, latest-run score filtering, and frontend/
  extension status language that no longer treats archived duplicates as
  active queue work.
- 2026-07-01: Added grounded semantic requirement validation, deterministic
  plus semantic fusion, semantic-only confidence discounting, offline semantic
  requirement diagnostic, and small semantic requirement evaluation with
  paraphrase positives and negative controls.
- 2026-07-01: Focused validation passed:
  `PYTHONPATH=backend/src pytest backend/tests/unit/test_archive_rescore_and_semantic_requirements.py backend/tests/unit/test_state_and_url.py -q`
  reported 12 passed; `PYTHONPATH=backend/src pytest backend/tests/unit -q`
  reported 179 passed, 2 skipped; `node frontend/scripts/test-dashboard.mjs`
  passed; `node extension/scripts/test-popup.mjs` passed;
  `./scripts/semantic-requirements-check --no-network` reported
  `simulated_success`; `PYTHONPATH=backend/src python3 scripts/evaluate_semantic_requirements.py`
  reported precision 1.0, recall 1.0, and false positives 0 on 6 fixtures.
- 2026-06-30: End-to-End Release Hardening completed and recorded. No active
  implementation milestone remains; release candidate is ready for manual
  evaluation.
- 2026-06-30: Started scoped Local Setup and One-Command Startup
  Simplification milestone for repository-root `.env.local` configuration.
- 2026-06-30: Added repository-root `.env.local` loading, `setup-local`,
  `dev-down`, `dev-status`, `demo-local`, tracked runtime PID state, actionable
  port diagnostics, LLM key validation, and isolated local-test defaults.
  Existing shell environment variables take precedence; secrets remain redacted
  and `.env.local` remains ignored.
- 2026-06-30: Focused validation passed:
  `PYTHONPATH=backend/src pytest backend/tests/unit/test_release_hardening.py -q`
  reported 18 passed. `./scripts/dev-up --skip-preflight` also failed
  helpfully with LLM enabled and a missing API key.
- 2026-06-30: Full validation passed: `python3 scripts/check.py` reported 202
  backend tests passed, 2 local TeX compile tests skipped, plus frontend and
  extension checks; `git diff --check` passed; `git status --short` was
  inspected.
- 2026-06-30: Isolated startup smoke passed using `/tmp` database/artifact/data
  paths and alternate ports `8766`/`5174`; API, Q1/Q2/regeneration workers, and
  frontend started, `dev-status` reached worker health, and `dev-down` stopped
  the tracked child PIDs.
- 2026-06-30: `./scripts/setup-local` created `.env.local` from `.env.example`;
  `./scripts/dev-status` reported the missing key without printing secrets; and
  `./scripts/demo-local` created 7 jobs in the configured local-test database.
- 2026-06-30: Local Setup and One-Command Startup Simplification completed and
  recorded. No active implementation milestone remains; release candidate is
  ready for manual evaluation.
- 2026-06-30: Started Frontend Usability, Demo Cleanup, and Semantic
  Observability milestone.
- 2026-06-30: Inspected current frontend/API behavior and traced an isolated
  demo `hybrid_match` Queue 1 result. Existing UI exposed dense queue
  terminology and raw `hybrid`/semantic-unavailable state without explaining
  the selected/secondary families.
- 2026-06-30: Implemented Jobs/Reviews/System navigation, job master/detail
  view, workflow timeline, candidate-fit versus CV-family classification
  separation, semantic status presentation, demo provenance/cleanup,
  individual delete/archive behavior, and semantic diagnostic command.
- 2026-06-30: Validation passed:
  `PYTHONPATH=backend/src pytest backend/tests/unit -q` reported 164 passed,
  2 skipped; `node frontend/scripts/test-dashboard.mjs` passed;
  `./scripts/semantic-check --no-network` passed; `python3 scripts/check.py`
  reported 206 backend tests passed, 2 skipped, plus frontend and extension
  checks; `git diff --check` passed; `git status --short` was inspected.
- 2026-06-30: Live `./scripts/semantic-check` ran with the configured local
  credential without printing it and failed safely as `request_failed`; no live
  semantic success was verified in this environment.
- 2026-06-30: Frontend Usability, Demo Cleanup, and Semantic Observability
  completed and recorded. No active implementation milestone remains.
- 2026-06-30: Started Minimal Retro Frontend and Stage-Based Workflow
  Redesign. Pre-edit inspection found the current UI still overexposes summary
  cards, multi-badge job rows, score bars, semantic metadata, and simultaneous
  review controls in default views.
- 2026-06-30: Implemented central stage mapping, minimal retro visual system,
  compact Jobs master/detail layout, staged Reviews flow, compact System cards,
  and collapsed advanced scoring/classification/semantic/technical details.
- 2026-06-30: Validation passed: `node frontend/scripts/test-dashboard.mjs`
  passed; `python3 scripts/check.py` reported 206 backend tests passed, 2
  skipped, plus frontend and extension checks. Manual `./scripts/dev-up --open`
  startup served the redesigned page assets and was stopped cleanly.
- 2026-06-30: Minimal Retro Frontend and Stage-Based Workflow Redesign
  completed and recorded. No active implementation milestone remains.
- 2026-07-01: Started Requirement-Aware Cross-Family Project Portfolio
  Selection. Initial trace found the current failure is family-gated candidate
  generation: for an ML base CV, `compatible_candidates()` only considers
  `registry.compatibility.ml`, and `tinynpu_digital_ic_v1` is eligible only for
  `digital_ic`, so TinyNPU never enters the ML project candidate set.
- 2026-07-01: Implemented requirement extraction, project capability metadata,
  requirement-aware global portfolio scoring across eligible approved blocks,
  conservative review surfacing for cross-family bridge candidates, frontend
  Base CV versus Project Portfolio presentation, and cross-domain evaluation.
- 2026-07-01: Validation passed:
  `PYTHONPATH=backend/src pytest backend/tests/unit -q` reported 171 passed,
  2 skipped; `node frontend/scripts/test-dashboard.mjs` passed;
  `python3 scripts/evaluate_cross_domain_portfolio.py` passed with no
  failures; `python3 scripts/check.py` reported 213 passed, 2 skipped, plus
  frontend and extension checks; `git diff --check` passed.
- 2026-07-01: Requirement-Aware Cross-Family Project Portfolio Selection
  completed and recorded. No active implementation milestone remains.
