# Phase 2 Real Intake

## Phase objective

Replace Phase 1 dummy intake with a deterministic intake pipeline:

```text
captured page payload
-> URL normalization
-> duplicate detection
-> JD extraction
-> JD quality diagnostics
-> company/title/location extraction
-> persisted structured intake result
-> scored/manual_review/failed intake state
```

Phase 2 ends after intake. No job scoring, CV-family selection, truth-bank loading,
promotion policy, packet generation, PDF generation, or LLM call was implemented.

## Scope implemented

- Deterministic URL normalization:
  - lowercases scheme/host.
  - removes fragments.
  - removes obvious tracking parameters.
  - preserves job-identifying query parameters.
  - unwraps common redirect parameters when the wrapped value is an HTTP(S) URL.
- Exact duplicate detection remains idempotent through normalized URL uniqueness.
- Probable duplicate warning based on identical JD fingerprint or same company/title.
- Deterministic JD extraction from captured `visible_text`.
- JD quality diagnostics with:
  - `good`
  - `usable_with_warnings`
  - `manual_review`
  - `failed`
- Deterministic company, title, and location extraction with field provenance.
- Intake warnings, manual-review reason, and failure reason persistence.
- Retry support for failed/manual-review intake states.
- Dashboard display for location, JD quality, warnings, manual review, and failures.
- API response extensions for Phase 2 intake fields.
- Additive SQLite schema migration for existing Phase 1 databases.

## Architecture decisions

- Kept the Phase 1 `scored` status as the successful intake-complete state because
  `status_model.md` does not define a separate `intake_complete` status.
- Used `queued -> extracting -> structuring -> scored` for successful/usable intake.
- Used `queued -> extracting -> structuring -> manual_review` for weak intake.
- Used `queued -> extracting -> structuring -> failed` for unusable intake.
- Stored structured diagnostics in JSON columns rather than overloading `reason`.
- Kept the extension simple; backend remains responsible for all intake interpretation.
- Kept Q2 Phase 1 placeholder behavior intact.

## Files added

- `backend/src/jobagent_v2/intake.py`
- `backend/tests/fixtures/intake_pages/clean_company.txt`
- `backend/tests/fixtures/intake_pages/greenhouse_like.txt`
- `backend/tests/fixtures/intake_pages/lever_like.txt`
- `backend/tests/fixtures/intake_pages/workday_noisy.txt`
- `backend/tests/fixtures/intake_pages/linkedin_like.txt`
- `backend/tests/fixtures/intake_pages/too_little.txt`
- `backend/tests/fixtures/intake_pages/missing_company.txt`
- `backend/tests/fixtures/intake_pages/missing_location.txt`
- `backend/tests/unit/test_intake_parser.py`
- `backend/tests/unit/test_url_normalization_phase2.py`
- `backend/tests/integration/test_phase2_intake_flow.py`
- `docs/build_reports/phase_2_real_intake.md`

## Files modified

- `README.md`
- `backend/src/jobagent_v2/statuses.py`
- `backend/src/jobagent_v2/storage.py`
- `backend/src/jobagent_v2/url_utils.py`
- `backend/src/jobagent_v2/workers.py`
- `backend/tests/conftest.py`
- `backend/tests/contract/test_api_contract.py`
- `backend/tests/integration/test_phase1_flow.py`
- `backend/tests/unit/test_dummy_workers.py`
- `docs/phase_1_api.md`
- `frontend/src/index.html`
- `frontend/src/app.js`
- `frontend/scripts/test-dashboard.mjs`
- `jobagent_v2_plan/build_roadmap.md`

## V1 references consulted

- `jobagent_v2_plan/v1_reference_map.md` Phase 2 entries:
  - URL canonicalization.
  - JD parser heuristics.
  - extension capture/extraction lessons.
- Targeted V1 read-only references:
  - `job-agent-v1/src/discovery/url_utils.py`
  - `job-agent-v1/src/discovery/job_parser.py`

No V1 source code was copied wholesale. The V2 implementation is independent.

## Tests added

- URL normalization:
  - idempotency.
  - tracking parameter stripping.
  - job-identifying query preservation.
  - redirect wrapper unwrapping.
  - stable duplicate keys.
- Intake parser:
  - clean company careers page.
  - Greenhouse-like page.
  - Lever-like page.
  - Workday-like noisy page.
  - LinkedIn-like visible text fixture.
  - too-little-content failure.
  - missing company warning.
  - missing location warning.
- Contract:
  - API responses include Phase 2 intake fields.
- Integration:
  - good fixture reaches successful intake state.
  - weak fixture reaches `manual_review`.
  - bad fixture reaches `failed`.
  - exact duplicate returns existing job.
  - probable duplicate warning persists.
  - retry requeues failed intake without creating a duplicate.
  - restart preserves clean JD and diagnostics.
  - Phase 1 database migrates without data loss.
- Frontend:
  - JD quality column.
  - location column.
  - warning rendering.
  - retry action visibility for `manual_review`.

## Commands run

```text
sed -n '1,260p' jobagent_v2_plan/architecture.md
sed -n '1,300p' jobagent_v2_plan/data_model.md
sed -n '1,320p' jobagent_v2_plan/pipeline.md
sed -n '1,240p' jobagent_v2_plan/status_model.md
sed -n '1,280p' jobagent_v2_plan/build_roadmap.md
sed -n '1,220p' docs/phase_1_api.md
rg -n "Phase 2|URL canonicalization|JD parser|Extension JSON|Extension ATS|DOM scoring" jobagent_v2_plan/v1_reference_map.md
sed -n '1,240p' ../job-agent-v1/src/discovery/url_utils.py
sed -n '1,280p' ../job-agent-v1/src/discovery/job_parser.py
python3 -m pytest
npm run build
npm test
node scripts/validate.mjs
node scripts/test-popup.mjs
python3 scripts/check.py
curl -L https://jobs.lever.co/scaleai
curl -L https://job-boards.greenhouse.io/anthropic
curl -L https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
curl -L https://job-boards.greenhouse.io/anthropic | rg -o 'job-boards\\.greenhouse\\.io/anthropic/jobs/[0-9]+' | head -3
PYTHONPATH=backend/src python3 -c "<manual smoke parser command>"
git diff -- job-agent-v1
git status --short --untracked-files=no job-agent-v1
rg -n "OpenAI|LLM|truth_bank|truth bank|cv_family|CV family|compatibility score|block scoring|recommendation generation|promotion scheduler|ring-buffer|auto-apply|email ingestion|PDF|LaTeX|one-page|auth|quota" backend/src frontend/src extension
find backend/src backend/tests frontend/src frontend/scripts extension docs jobagent_v2_plan scripts -maxdepth 4 -type f -print | sort
git status --short
git rev-parse --short HEAD
```

Cleanup after checks:

```text
rm -rf job-agent-v2/.pytest_cache job-agent-v2/backend/src/jobagent_v2/__pycache__ job-agent-v2/backend/tests/__pycache__ job-agent-v2/backend/tests/contract/__pycache__ job-agent-v2/backend/tests/integration/__pycache__ job-agent-v2/backend/tests/unit/__pycache__ job-agent-v2/frontend/dist job-agent-v2/.DS_Store job-agent-v2/docs/.DS_Store
```

## Test results

Backend:

```text
python3 -m pytest
38 passed in 0.17s
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
pytest -> 38 passed
frontend build -> passed
frontend dashboard checks -> passed
extension validation -> passed
extension popup checks -> passed
format check -> passed
lint check -> passed
type-oriented import contract -> passed
```

## Manual smoke-test results

Limited current-page probes were performed against three real public career/job pages.
No private page content was committed.

| Source | URL | Company extracted | Title extracted | Location extracted | JD quality outcome | Warnings | Final intake status |
|---|---|---|---|---|---|---|---|
| Greenhouse | `https://job-boards.greenhouse.io/anthropic/jobs/4926227008` | `Anthropic` | `Performance Engineer, GPU` | `San Francisco, CA` | `good` | none | `scored` |
| Ashby | `https://jobs.ashbyhq.com/openai` | `ashby` from source-site fallback | null | null | `failed` | too short, missing responsibilities, missing qualifications, missing title/location | `failed` |
| Workday | `https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite` | `workday` from source-site fallback | null | null | `failed` | too short, missing responsibilities, missing qualifications, missing title/location | `failed` |

The Ashby and Workday probes returned JavaScript shell/career landing text in this
environment rather than reliable browser-visible job descriptions. The deterministic
pipeline failed them visibly instead of inventing fields.

## Acceptance-criteria evidence

1. Real captured page payload persists:
   - `Repository.create_or_get_job`.
   - contract tests.
2. URL normalization is deterministic and idempotent:
   - `test_url_normalization_phase2.py`.
3. Exact duplicate jobs do not create duplicate records:
   - normalized URL unique constraint.
   - `test_duplicate_url_returns_existing_job_after_normalization`.
4. JD text is extracted from deterministic fixtures:
   - `test_intake_parser.py`.
5. Good JD input reaches successful intake-complete state:
   - `test_real_intake_worker_good_fixture_reaches_intake_complete`.
6. Weak JD input reaches `manual_review` with warnings:
   - `test_weak_fixture_reaches_manual_review`.
7. Unusable input reaches `failed` with failure reason:
   - `test_bad_fixture_reaches_failed`.
8. Company, title, and location are extracted without invention:
   - parser tests for page-title patterns, visible-text labels, missing company, and missing location.
9. Intake diagnostics survive backend restart:
   - `test_restart_preserves_clean_jd_and_diagnostics`.
10. Retry reprocesses failed/manual-review intake without creating a duplicate:
    - `test_retry_requeues_failed_intake_without_duplicate`.
11. Dashboard clearly shows intake outcome and warnings:
    - `frontend/src/app.js`.
    - `frontend/scripts/test-dashboard.mjs`.
12. Every transition is recorded in event history:
    - Phase 1 and Phase 2 integration tests check event history.
13. All Phase 1 tests still pass:
    - Phase 1 integration tests remain in `test_phase1_flow.py`.
14. All Phase 2 tests and project checks pass:
    - `python3 scripts/check.py` passed.

## Known limitations

- `scored` is used as the successful intake-complete status for compatibility with
  `status_model.md`; no job compatibility scoring is performed.
- Company fallback to `source_site` is marked low-confidence and can be imperfect.
- The parser is heuristic and intentionally conservative.
- Workday/Ashby app-shell pages often require browser-captured visible text; raw HTTP
  shell content fails visibly.
- Probable duplicate detection is warning-only.
- Existing API documentation file remains named `phase_1_api.md`, but its content now
  documents Phase 2 response fields.

## Deferred Phase 3 work

- JD semantic structuring for scoring.
- CV-family selection.
- Truth-bank loading.
- Job compatibility scoring.
- Block scoring.
- Recommendation generation.
- Dashboard ranking by score/recommendation.

## Final changed-area directory structure

```text
backend/src/jobagent_v2/__init__.py
backend/src/jobagent_v2/api.py
backend/src/jobagent_v2/app.py
backend/src/jobagent_v2/intake.py
backend/src/jobagent_v2/schemas.py
backend/src/jobagent_v2/server.py
backend/src/jobagent_v2/service.py
backend/src/jobagent_v2/statuses.py
backend/src/jobagent_v2/storage.py
backend/src/jobagent_v2/url_utils.py
backend/src/jobagent_v2/util.py
backend/src/jobagent_v2/workers.py
backend/tests/conftest.py
backend/tests/contract/test_api_contract.py
backend/tests/fixtures/intake_pages/clean_company.txt
backend/tests/fixtures/intake_pages/greenhouse_like.txt
backend/tests/fixtures/intake_pages/lever_like.txt
backend/tests/fixtures/intake_pages/linkedin_like.txt
backend/tests/fixtures/intake_pages/missing_company.txt
backend/tests/fixtures/intake_pages/missing_location.txt
backend/tests/fixtures/intake_pages/too_little.txt
backend/tests/fixtures/intake_pages/workday_noisy.txt
backend/tests/integration/test_phase1_flow.py
backend/tests/integration/test_phase2_intake_flow.py
backend/tests/unit/test_dummy_workers.py
backend/tests/unit/test_intake_parser.py
backend/tests/unit/test_state_and_url.py
backend/tests/unit/test_url_normalization_phase2.py
docs/build_reports/phase_2_real_intake.md
docs/phase_1_api.md
frontend/scripts/test-dashboard.mjs
frontend/src/app.js
frontend/src/index.html
jobagent_v2_plan/build_roadmap.md
```

## Final git status

`git diff -- job-agent-v1` produced no output.

`git status --short --untracked-files=no job-agent-v1` produced no output.

`git status --short` from `job-agent-v2/`:

```text
 M README.md
 M backend/src/jobagent_v2/statuses.py
 M backend/src/jobagent_v2/storage.py
 M backend/src/jobagent_v2/url_utils.py
 M backend/src/jobagent_v2/workers.py
 M backend/tests/conftest.py
 M backend/tests/contract/test_api_contract.py
 M backend/tests/integration/test_phase1_flow.py
 M backend/tests/unit/test_dummy_workers.py
 M docs/phase_1_api.md
 M frontend/scripts/test-dashboard.mjs
 M frontend/src/app.js
 M frontend/src/index.html
 M jobagent_v2_plan/build_roadmap.md
?? backend/src/jobagent_v2/intake.py
?? backend/tests/fixtures/
?? backend/tests/integration/test_phase2_intake_flow.py
?? backend/tests/unit/test_intake_parser.py
?? backend/tests/unit/test_url_normalization_phase2.py
```

Checkpoint identifier:

```text
a868536
```

PHASE READY FOR REVIEW
