# Phase 2B Intake Hardening

## Objective

Harden deterministic extraction of company, job title, location, and job
description without beginning Phase 3.

## Capture-flow audit

The prior flow was:

```text
browser page
-> extension document.body.innerText
-> POST /api/jobs
-> raw_visible_text
-> heuristic backend intake
-> selected fields
```

Useful information was lost at the extension boundary:

- JSON-LD `JobPosting` objects.
- Open Graph and standard meta tags.
- headings.
- ATS-specific title/company/location/description candidates.
- capture diagnostics and detected site.

The hardening flow is now:

```text
browser page
-> visible text plus structured evidence
-> persisted raw payload and evidence
-> deterministic evidence candidate collection
-> explicit field-priority resolution
-> persisted selected fields, alternatives, provenance, warnings, diagnostics
```

## Scope implemented

- Extension captures evidence only:
  - URL and `document.title`.
  - cleaned visible text.
  - JSON-LD `JobPosting` objects.
  - Open Graph and standard meta tags.
  - top-level headings.
  - likely title/company/location/description DOM candidates.
  - detected ATS/site: Greenhouse, Lever, Workday, LinkedIn, Ashby,
    SmartRecruiters, or generic.
  - capture diagnostics.
- Backend persists `capture_evidence`, `detected_site`, and
  `extraction_candidates`.
- Backend collects candidates from JSON-LD, DOM candidates, meta tags, headings,
  page title, visible text, source site, and URL patterns.
- Field resolution uses deterministic priorities:
  - JSON-LD JobPosting.
  - ATS/DOM candidates.
  - meta tags.
  - headings/page-title/visible-text patterns.
  - URL and source-site fallbacks.
- Selected value, source, confidence, and alternatives are persisted in
  `field_provenance`.
- JD extraction prefers JSON-LD description, then high-confidence DOM description
  candidates, then cleaned visible text.
- JSON-LD description now receives quality diagnostics based on its content rather
  than being failed because a page shell has short visible text.
- Weak/missing evidence remains `manual_review` or `failed`; fields remain unknown
  rather than invented.

## V1 references consulted

- `jobagent_v2_plan/v1_reference_map.md`:
  - extension visible-text cleanup.
  - JSON-LD extraction.
  - ATS extraction.
  - DOM fallback diagnostics.
- Read-only V1 files:
  - `browser_extension/extractors/common.js`
  - `browser_extension/extractors/jsonld.js`
  - `browser_extension/extractors/ats.js`
  - `browser_extension/extractors/dom_score.js`

No V1 source was copied wholesale.

## Files modified

- `backend/src/jobagent_v2/schemas.py`
- `backend/src/jobagent_v2/storage.py`
- `backend/src/jobagent_v2/intake.py`
- `backend/src/jobagent_v2/workers.py`
- `extension/popup.js`
- `extension/scripts/validate.mjs`
- `extension/scripts/test-popup.mjs`
- `docs/phase_1_api.md`

## Files added

- `backend/tests/unit/test_intake_hardening.py`
- `docs/build_reports/phase_2b_intake_hardening.md`

## Regression coverage

Added deterministic tests for:

- JSON-LD JobPosting extraction.
- meta-tag extraction.
- ATS/DOM candidate extraction.
- conflicting evidence and persisted alternatives.
- missing fields without invented values.
- JSON-LD JD fallback.
- no over-truncation of long visible-text JD content.
- expanded extension evidence payload.
- persistence-compatible schema migration through existing test coverage.

Existing Phase 1 and Phase 2 tests remain in the full suite.

## Commands run

```text
sed -n '1,260p' extension/popup.js
sed -n '1,320p' backend/src/jobagent_v2/schemas.py backend/src/jobagent_v2/intake.py backend/src/jobagent_v2/workers.py
sed -n '1,360p' backend/src/jobagent_v2/storage.py
rg -n "Extension visible|JSON-LD|ATS extraction|DOM scoring|Phase 2" jobagent_v2_plan/v1_reference_map.md
sed -n '1,260p' ../job-agent-v1/browser_extension/extractors/common.js ../job-agent-v1/browser_extension/extractors/jsonld.js ../job-agent-v1/browser_extension/extractors/ats.js ../job-agent-v1/browser_extension/extractors/dom_score.js
python3 -m pytest
python3 scripts/check.py
npm run build
npm test
node scripts/validate.mjs
node scripts/test-popup.mjs
git diff -- job-agent-v1
git status --short --untracked-files=no job-agent-v1
git status --short
git rev-parse --short HEAD
```

## Test results

```text
python3 -m pytest: 48 passed
python3 scripts/check.py: passed
npm run build: frontend build complete
npm test: frontend dashboard checks passed
node scripts/validate.mjs: extension structure is valid
node scripts/test-popup.mjs: extension popup checks passed
```

## Diagnostics exposed

Job detail/list responses now expose:

```text
capture_evidence
detected_site
extraction_candidates
field_provenance
extraction_method
extraction_warnings
raw_text_length
clean_text_length
```

The main dashboard remains focused on selected fields, quality, status, and
warnings; deep evidence is available through the API job detail response.

## Dashboard intake-field investigation and fix

### Root cause

The affected jobs had been persisted correctly as raw captures, but had not been
processed by Queue 1. Their only event was `job_created`, their
`intake_status` was `queued`, and `company`, `title`, `location`, and
`jd_quality_band` were all null in SQLite. The dashboard correctly rendered
those null values as `-`.

Queue 1 is deliberately exposed as an explicit local worker endpoint:

```text
POST /api/workers/q1/run-once
```

The server does not start a background worker. That matches the existing local
queue scaffold, but the dashboard did not expose the required manual intake
step.

### Backend findings

- SQLite schema and `row_to_job` use the canonical fields `company`, `title`,
  `location`, `jd_quality_band`, and `role_family`.
- Before Q1 ran, both affected rows had null intake output fields and no intake
  transition events.
- After Q1 ran, the real captured NVIDIA and Infineon rows persisted non-null
  company, title, location, and `good` JD quality with `scored` intake status.
- `role_family` remains null intentionally: role-family classification is
  deferred to Phase 3.

### API findings

- `GET /api/jobs` and `GET /api/jobs/{job_id}` both serialize the same
  canonical field names.
- The processed NVIDIA detail response contained all selected fields, quality,
  extraction method, candidates, and field provenance.
- Event history recorded `queued -> extracting -> structuring -> scored`.

### Frontend findings and fix

- The dashboard already reads the canonical API names directly:
  `company`, `title`, `location`, `jd_quality_band`, and `role_family`.
- The rebuilt `frontend/dist/` bundle matches the source and contains those
  mappings, so no stale-build or stale field-name mismatch was found.
- Added an explicit **Process intake queue** action that calls the documented
  Q1 endpoint and refreshes the table. This makes the required local worker
  step visible without adding a background scheduler.

### Regression coverage added

- Contract test: a completed intake record retains the canonical company,
  title, location, JD-quality, and null role fields in both list and detail
  responses.
- Frontend test: a completed-intake-style row renders non-null title, location,
  and JD quality in their table columns, while a null role renders as `-`.
- Frontend test: the explicit Q1 action is present in the dashboard markup.

### Manual verification result

Used the two affected real captured rows already present in the running local
database. Calling `POST /api/workers/q1/run-once` twice moved each through the
complete persisted Q1 flow. SQLite, list API, detail API, and events all showed
the populated values described above; the rebuilt dashboard bundle maps them to
the corresponding columns. The runtime database was not reset because the
existing backend process on port 8765 owned the active user data; deleting it
while that process remained active would have invalidated the verification.

The Infineon capture still exposes a malformed JSON-LD location value. That is
an extraction-quality issue, not the dashboard-field-loss defect addressed by
this pass, and remains within the existing Phase 2B live-fixture validation
block.

## Additional real-extraction hardening

### Queued jobs

New raw captures remain blank until Q1 runs because the local server does not
start a background Q1 worker. This is confirmed by the persisted status and
event history: a new job has `intake_status = queued`, a `job_created` event,
and no derived intake fields.

The dashboard now renders this state as `Queued - not processed` rather than a
bare queued value. The **Process intake queue** button remains available for
debugging. Automatic Q1 worker startup is deferred to a future queue-runtime
decision; it is not part of Phase 2, and the Phase 4 promotion scheduler is a
separate Q2 policy.

### NVIDIA diagnostics and normalization

Sanitized Workday-shaped regression payload:

```text
company candidates
  raw: 2100 NVIDIA USA
  normalized: NVIDIA
  selected: JSON-LD JobPosting, high confidence
  normalization: leading_street_number_removed, country_suffix_removed
  alternative: New College Grad 2026 from page-title company heuristic

title candidates
  raw: ASIC Design Engineer - New College Grad 2026
  JSON-LD, DOM, heading: normalized to ASIC Design Engineer
  independent meta-tag and page-title candidates: ASIC Design Engineer
  selected: JSON-LD JobPosting, high confidence
  normalization: campaign_suffix_removed

location candidates
  JSON-LD PostalAddress: Santa Clara, CA, US
  selected: JSON-LD JobPosting, high confidence
```

Campaign cleanup is intentionally narrow: it accepts only known separate
campaign/category suffixes and requires two distinct supporting shorter-source
types before normalizing a higher-priority full title. It does not truncate
ordinary titles.

### Infineon diagnostics and normalization

Sanitized JSON-LD regression payload has two structured locations:

```text
San Jose + CA,US + Country{name: US}
CA,US + Country{name: US}
```

The resolver renders typed scalar components rather than stringifying objects,
deduplicates region/country components, and suppresses a second location when
it is a subset of the first. The persisted selected candidate is:

```text
company: Infineon (JSON-LD JobPosting, high)
title: Graduate - Senior Engineer Digital IC Design (JSON-LD JobPosting, high)
location: San Jose, CA, US (JSON-LD JobPosting, high)
location normalization: structured address components and duplicate removal
```

### Regression coverage and fresh-runtime verification

- Added sanitized NVIDIA Workday and Infineon structured-location fixtures.
- Added company normalization coverage for leading address numbers and country
  suffixes.
- Added campaign-title normalization coverage with provenance containing raw
  value, normalized value, source, confidence, alternatives, and normalization.
- Added structured JSON-LD location coverage for strings, addresses, nested
  country objects, lists, repeated components, and object-syntax rejection.
- Added persistence coverage for queued-before-Q1 and normalized-after-Q1
  records.
- Added dashboard coverage for `Queued - not processed` and for completed
  fields plus null role rendering.

Used a fresh temporary SQLite/artifact runtime on port 8766. The NVIDIA fixture
was blank and queued before Q1, then resolved to `NVIDIA`, `ASIC Design
Engineer`, and `Santa Clara, CA, US`. The Infineon fixture resolved to
`Infineon`, `Graduate - Senior Engineer Digital IC Design`, and `San Jose, CA,
US`. A third job remained visibly queued until processing. The browser extension
could not be reloaded from this environment; the payload contract and rebuilt
frontend bundle were verified instead.

## Manual validation status

The request requires validation of at least five real job pages and proof that the
known manually failed pages are fixed. Specific failed URLs or sanitized captured
payloads were not provided in this conversation.

The extension cannot be exercised against a live browser page from this execution
environment. Consequently, this pass cannot truthfully claim:

- that the previously manually failed pages are fixed;
- that five real browser-captured pages passed;
- that each real page has a verified expected-versus-extracted comparison.

The implementation provides targeted regression coverage for the documented
failure classes, but human validation with the actual failed URLs/payloads is still
required.

## Known limitations

- ATS handling is evidence-driven selector capture, not a scraper.
- A page can still expose only a JavaScript shell; it should become
  `manual_review` or `failed` instead of being falsely accepted.
- The extension does not run final extraction logic by design.
- User-provided actual failures are required to finalize regression fixtures for
  those pages.

## Deferred work

- Phase 3 scoring and all CV/LLM functionality remain unimplemented.
- No scheduler, promotion, packet, PDF, or tailoring work was added.

## Final git status

`git diff -- job-agent-v1` produced no output.

`git status --short --untracked-files=no job-agent-v1` produced no output.

`git status --short` from `job-agent-v2/` includes the current Phase 2/2B changes
and pre-existing uncommitted Phase 2 work, including the dashboard intake-field
fix.

Checkpoint identifier:

```text
a868536
```

PHASE BLOCKED — HUMAN DECISION REQUIRED
