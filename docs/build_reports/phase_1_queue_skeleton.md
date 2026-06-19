# Phase 1 Queue Skeleton

## Phase objective

Build the complete persistent system skeleton with no real JD intelligence and no
LLM dependency:

```text
Chrome extension Add to Queue
-> backend intake endpoint
-> persist raw job
-> dummy Q1 status transitions
-> Generate now
-> dummy Q2 status transitions
-> dashboard table
-> persisted event history
```

## Scope implemented

- Chrome extension Add to Queue capture.
- Extension-to-backend payload contract.
- Local backend API with documented endpoints.
- SQLite-backed persistent `jobs` and `job_events` tables.
- URL-based Phase 1 duplicate handling.
- Validated intake and packet status transitions.
- Dummy Q1 worker: `queued -> extracting -> scoring -> scored`.
- Dummy Q2 worker: `queued -> generating -> ready`.
- Placeholder JSON artifact for dummy Q2.
- Generate now, retry, and archive actions.
- Minimal dashboard table with active-job filtering and action endpoints.
- Contract, unit, integration, frontend, and extension checks.

## Architecture decisions

- Used Python stdlib `sqlite3` for local durable storage.
- Used a small stdlib HTTP server wrapper for local API serving, with tests focused on
  the service/API contract because the sandbox blocks binding sockets.
- Kept status mutation behind service/repository methods; API callers cannot submit
  arbitrary statuses.
- Kept Q1 and Q2 as deterministic `run once` workers for Phase 1.
- Stored a placeholder JSON artifact instead of generating any CV/PDF packet.
- Left score, recommendation, role family, JD extraction, and packet generation fields
  empty or placeholder-only.

## Files added

- `backend/src/jobagent_v2/api.py`
- `backend/src/jobagent_v2/schemas.py`
- `backend/src/jobagent_v2/server.py`
- `backend/src/jobagent_v2/service.py`
- `backend/src/jobagent_v2/statuses.py`
- `backend/src/jobagent_v2/storage.py`
- `backend/src/jobagent_v2/url_utils.py`
- `backend/src/jobagent_v2/util.py`
- `backend/src/jobagent_v2/workers.py`
- `backend/tests/conftest.py`
- `backend/tests/contract/test_api_contract.py`
- `backend/tests/integration/test_phase1_flow.py`
- `backend/tests/unit/test_dummy_workers.py`
- `backend/tests/unit/test_state_and_url.py`
- `docs/phase_1_api.md`
- `docs/build_reports/phase_1_queue_skeleton.md`
- `extension/scripts/test-popup.mjs`
- `frontend/scripts/test-dashboard.mjs`
- `frontend/src/app.js`
- `frontend/src/styles.css`

## Files modified

- `README.md`
- `backend/src/jobagent_v2/__init__.py`
- `backend/src/jobagent_v2/app.py`
- `extension/popup.html`
- `extension/popup.js`
- `extension/scripts/validate.mjs`
- `frontend/package.json`
- `frontend/scripts/build-placeholder.mjs`
- `frontend/src/index.html`
- `jobagent_v2_plan/build_roadmap.md`
- `scripts/check.py`

Existing pre-Phase-1 uncommitted documentation rename state is still present:

- `jobagent_v2_plan/reuse_manifest.md` deleted.
- `jobagent_v2_plan/v1_reference_map.md` present.
- `docs/build_reports/phase_0b_repository_bootstrap.md` already referenced the new map.

## V1 references consulted

- `jobagent_v2_plan/v1_reference_map.md` Phase 1 rows:
  - extension visible text cleanup.
  - active tab tracking.
  - V1 DB model lessons.
  - React dashboard lessons.
  - extension popup scoring flow marked `ignore`.
- No V1 source code was copied.

## Tests added

- Contract:
  - extension payload schema.
  - `POST /api/jobs` success response.
  - duplicate POST idempotency.
  - job list response schema.
  - Generate now response schema.
  - invalid request rejection.
- Unit:
  - valid state transitions.
  - invalid transition rejection.
  - URL normalization and duplicate key.
  - dummy deterministic behavior.
  - retry eligibility.
- Integration:
  - job persistence.
  - application restart persistence.
  - event history persistence.
  - dummy Q1 reaches `scored`.
  - dummy Q2 reaches `ready`.
  - Generate now idempotency.
  - duplicate URL returns existing job.
  - archived job hidden from active list.
  - worker restart does not duplicate completed work.
- Frontend:
  - dashboard columns.
  - status/value rendering.
  - safe text rendering.
  - action endpoints.
- Extension:
  - manifest validity.
  - Add to Queue payload fields.
  - no V1 auth/scoring flow tokens.
  - payload builder behavior.

## Commands run

```text
sed -n '1,260p' job-agent-v2/jobagent_v2_plan/architecture.md
sed -n '1,260p' job-agent-v2/jobagent_v2_plan/data_model.md
sed -n '1,280p' job-agent-v2/jobagent_v2_plan/pipeline.md
sed -n '1,240p' job-agent-v2/jobagent_v2_plan/status_model.md
sed -n '1,260p' job-agent-v2/jobagent_v2_plan/build_roadmap.md
sed -n '1,220p' job-agent-v2/docs/build_reports/phase_0b_repository_bootstrap.md
rg -n "Phase 1|V1 DB models|React dashboard|Extension visible|Active tab|Extension popup|URL canonicalization|reference map" job-agent-v2/jobagent_v2_plan/v1_reference_map.md
find job-agent-v2 -maxdepth 4 -type f -print | sort
python3 -m pytest
npm run build
npm test
node scripts/validate.mjs
node scripts/test-popup.mjs
python3 scripts/check.py
git diff -- job-agent-v1
git status --short --untracked-files=no job-agent-v1
rg -n "OpenAI|LLM|truth_bank|truth bank|jd_quality|CV family|cv_family|block scoring|PDF|LaTeX|auth|quota|auto-apply|email ingestion|real scheduler|ring-buffer" job-agent-v2/backend/src job-agent-v2/frontend/src job-agent-v2/extension
find job-agent-v2/backend job-agent-v2/frontend job-agent-v2/extension job-agent-v2/docs job-agent-v2/jobagent_v2_plan job-agent-v2/scripts -maxdepth 4 -type f -print | sort
git -C job-agent-v2 status --short
git -C job-agent-v2 rev-parse --short HEAD
```

Cleanup after checks:

```text
rm -rf job-agent-v2/.pytest_cache job-agent-v2/backend/src/jobagent_v2/__pycache__ job-agent-v2/backend/tests/__pycache__ job-agent-v2/backend/tests/contract/__pycache__ job-agent-v2/backend/tests/integration/__pycache__ job-agent-v2/backend/tests/unit/__pycache__ job-agent-v2/frontend/dist job-agent-v2/.DS_Store job-agent-v2/docs/.DS_Store
```

## Test results

`python3 -m pytest`:

```text
19 passed in 0.10s
```

Frontend:

```text
npm run build -> frontend build complete
npm test -> frontend dashboard checks passed
```

Extension:

```text
node scripts/validate.mjs -> extension structure is valid
node scripts/test-popup.mjs -> extension popup checks passed
```

Standard project check:

```text
python3 scripts/check.py -> passed
pytest -> 19 passed
frontend build -> passed
frontend dashboard checks -> passed
extension validation -> passed
extension popup checks -> passed
format check -> passed
lint check -> passed
type-oriented import contract -> passed
```

## Acceptance-criteria evidence

1. Clicking Add to Queue submits a captured page payload:
   - `extension/popup.js` captures URL, page title, visible text, source site, and timestamp.
   - `extension/scripts/test-popup.mjs` verifies payload construction.
2. Backend persists a job:
   - `Repository.create_or_get_job`.
   - `test_job_persists_and_survives_repository_restart`.
3. Job appears in dashboard:
   - `GET /api/jobs`.
   - `frontend/src/app.js` renders `jobs`.
   - `frontend/scripts/test-dashboard.mjs`.
4. Duplicate submission does not create a duplicate job:
   - unique `normalized_url`.
   - `test_duplicate_post_is_idempotent`.
5. Dummy Q1 moves through valid persisted states:
   - `DummyQ1Worker`.
   - `test_dummy_q1_reaches_scored`.
6. Generate now queues dummy Q2 work:
   - `JobService.generate_now`.
   - `test_generate_now_and_dummy_q2_reaches_ready`.
7. Dummy Q2 reaches ready:
   - `DummyQ2Worker`.
   - `test_generate_now_and_dummy_q2_reaches_ready`.
8. Every transition is recorded:
   - `job_events`.
   - `test_event_history_is_persisted`.
9. Restarting backend does not lose jobs or completed state:
   - `test_job_persists_and_survives_repository_restart`.
   - `test_worker_restart_does_not_duplicate_completed_work`.
10. Invalid state transitions are rejected:
    - `statuses.py`.
    - `test_invalid_state_transition_rejected`.
11. Archived jobs disappear from default dashboard:
    - `Repository.list_jobs(include_archived=False)`.
    - `test_archived_job_is_hidden_from_active_list`.
12. All tests and project checks pass:
    - `python3 scripts/check.py` passed.

## Known limitations

- HTTP server bind was not exercised by tests because the sandbox denies local socket
  binding; the service/API contract and server construction code are still present.
- No real scheduler policy exists.
- No automatic Q2 promotion threshold exists.
- No real JD extraction or scoring exists.
- No dashboard visual polish was attempted.
- Placeholder artifact links point to local artifact paths; no artifact-serving route was
  added in Phase 1.

## Deferred Phase 2 work

- Real URL canonicalization beyond basic Phase 1 normalization.
- Deduplication beyond normalized URL.
- JD extraction.
- JD quality scoring.
- Company/title/location inference beyond deterministic placeholders.
- Intake failure quality states for bad extraction.

## Final changed-area directory structure

```text
job-agent-v2/backend/src/jobagent_v2/__init__.py
job-agent-v2/backend/src/jobagent_v2/api.py
job-agent-v2/backend/src/jobagent_v2/app.py
job-agent-v2/backend/src/jobagent_v2/schemas.py
job-agent-v2/backend/src/jobagent_v2/server.py
job-agent-v2/backend/src/jobagent_v2/service.py
job-agent-v2/backend/src/jobagent_v2/statuses.py
job-agent-v2/backend/src/jobagent_v2/storage.py
job-agent-v2/backend/src/jobagent_v2/url_utils.py
job-agent-v2/backend/src/jobagent_v2/util.py
job-agent-v2/backend/src/jobagent_v2/workers.py
job-agent-v2/backend/tests/conftest.py
job-agent-v2/backend/tests/contract/test_api_contract.py
job-agent-v2/backend/tests/integration/test_phase1_flow.py
job-agent-v2/backend/tests/unit/test_dummy_workers.py
job-agent-v2/backend/tests/unit/test_state_and_url.py
job-agent-v2/docs/phase_1_api.md
job-agent-v2/docs/build_reports/phase_1_queue_skeleton.md
job-agent-v2/extension/popup.html
job-agent-v2/extension/popup.js
job-agent-v2/extension/scripts/test-popup.mjs
job-agent-v2/extension/scripts/validate.mjs
job-agent-v2/frontend/package.json
job-agent-v2/frontend/scripts/build-placeholder.mjs
job-agent-v2/frontend/scripts/test-dashboard.mjs
job-agent-v2/frontend/src/app.js
job-agent-v2/frontend/src/index.html
job-agent-v2/frontend/src/styles.css
job-agent-v2/jobagent_v2_plan/build_roadmap.md
job-agent-v2/scripts/check.py
```

## Final git status

`git diff -- job-agent-v1` produced no output.

`git status --short --untracked-files=no job-agent-v1` produced no output.

`git -C job-agent-v2 status --short`:

```text
 M README.md
 M backend/src/jobagent_v2/__init__.py
 M backend/src/jobagent_v2/app.py
 D backend/tests/unit/test_backend_import.py
 M docs/build_reports/phase_0b_repository_bootstrap.md
 M extension/popup.html
 M extension/popup.js
 M extension/scripts/validate.mjs
 M frontend/package.json
 M frontend/scripts/build-placeholder.mjs
 M frontend/src/index.html
 M jobagent_v2_plan/build_roadmap.md
 D jobagent_v2_plan/reuse_manifest.md
 M scripts/check.py
?? backend/src/jobagent_v2/api.py
?? backend/src/jobagent_v2/schemas.py
?? backend/src/jobagent_v2/server.py
?? backend/src/jobagent_v2/service.py
?? backend/src/jobagent_v2/statuses.py
?? backend/src/jobagent_v2/storage.py
?? backend/src/jobagent_v2/url_utils.py
?? backend/src/jobagent_v2/util.py
?? backend/src/jobagent_v2/workers.py
?? backend/tests/conftest.py
?? backend/tests/contract/test_api_contract.py
?? backend/tests/integration/test_phase1_flow.py
?? backend/tests/unit/test_dummy_workers.py
?? backend/tests/unit/test_state_and_url.py
?? docs/phase_1_api.md
?? extension/scripts/test-popup.mjs
?? frontend/scripts/test-dashboard.mjs
?? frontend/src/app.js
?? frontend/src/styles.css
?? jobagent_v2_plan/v1_reference_map.md
```

Checkpoint identifier:

```text
4cb0ec6
```

PHASE READY FOR REVIEW
