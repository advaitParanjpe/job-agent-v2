# Phase 5: Basic Packet Generation

## Objective and scope

Replace the Q2 placeholder artifact with a deterministic, local CV packet pipeline.
This phase selects existing canonical truth-bank content, renders it, compiles a PDF,
and persists explainable artifacts. It does not rewrite, truth-check rewrites, prune
content, or fit the document to one page.

## Implemented packet architecture

`q2_tasks` are claimed durably, then create a persistent `packets` attempt. The worker
loads the already stored job, selected family, validated truth bank, job block scores,
section scores, and task metadata. It writes `selected_cv.json`, `cv.tex`, `cv.pdf`,
`compile.log`, and `manifest.json` under:

```text
<artifact-root>/packets/<job-id>/<packet-id>/
```

Path components are UUID-safe and resolved under the configured artifact root. Packet
and task failures persist stage/reason, preserve the failed attempt and manifest, and
are retryable. Repeated worker runs do not create duplicate ready packets.

## Selection and rendering policy

- Required education/truth-bank header content is always included.
- Experience and project blocks use stored aggregate block scores, descending score
  then block ID; required blocks are retained and configured limits are two each.
- Every candidate receives a selected flag, rank, score, and reason in the selected CV
  and manifest.
- The stored Phase 3 `recommended_section_order` controls Experience versus Projects;
  Education leads and Skills ends the document.
- Skills are the intersection of validated truth-bank allowed skills with JD exact
  matches or selected-block evidence. No JD-only technology can be introduced.
- Rendering uses a versioned package template, typed selected-CV data, LaTeX escaping,
  a temporary build directory, explicit `pdflatex` detection, captured compilation log,
  timeout, and deterministic filenames.

The manifest records source/job metadata, family/truth-bank/scoring/template versions,
selection decisions, section order, skills provenance, score at generation, paths,
page count, warnings, and failure information. A multi-page document is marked
`requires_fitting`; Phase 5 does not alter content to solve it.

## Persistence, APIs, and dashboard

Added packet-attempt persistence with Q2 task linkage, status, artifact paths, page
count, and failure fields. APIs provide job packet lookup, packet lookup, manifest,
and safe PDF streaming. The dashboard shows packet status/family/page count, a
multi-page fitting warning, failure reason, and PDF/manifest links.

## Files added or materially changed

- `backend/src/jobagent_v2/packets.py`
- `backend/src/jobagent_v2/templates/basic_cv.tex`
- truth-bank JSON fixtures, worker, storage, service, and API modules
- Phase 5 packet unit/integration tests
- dashboard source/tests and API documentation

## Verification and limitations

Focused Phase 5 tests cover deterministic packet generation, selected-CV/manifest
alignment, PDF bytes, idempotency, persisted invalid-input failure, LaTeX escaping,
and artifact containment. The LaTeX toolchain used is `pdflatex`; missing tooling is a
visible retryable `compile` failure with remediation text.

### Final validation

The originally reported Phase 5 line-length violations in `api.py`, `packets.py`,
`storage.py`, and `workers.py` were corrected with manual line wrapping only. No
formatter was installed, checks were not weakened, and runtime behavior was preserved.

The following command now passes in full:

```bash
python3 scripts/check.py
```

It runs the 73 backend tests, format/lint/import checks, frontend build/dashboard
checks, and extension validation/popup checks. `git diff --check` also passes.

### Local packet-generation procedure

`pdflatex` is required; this environment resolves it at
`/Library/TeX/texbin/pdflatex`. From `job-agent-v2/`, start the backend with:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.server \
  --db-path data/jobagent_v2.sqlite3 --artifact-root data/artifacts
```

Create a capture through the extension or `POST /api/jobs`, then run
`POST /api/workers/q1/run-once` until the job is scored. Use Dashboard **Generate
now** (or `POST /api/jobs/{job_id}/generate`) to create Q2 work; alternatively the
promotion loop applies its configured policy. Run `POST /api/workers/q2/run-once` to
generate one packet. The dashboard **Open PDF** and **View manifest** links use
`GET /api/packets/{packet_id}/pdf` and `/manifest`; packet state is also available at
`GET /api/jobs/{job_id}/packet`. Failures appear in the dashboard Packet column and
packet response as `failure_stage` and `failure_reason`.

Generated files are stored at:

```text
data/artifacts/packets/<job-id>/<packet-id>/
```

### Required human PDF-review procedure

For each of the hardware/RTL, CPU/GPU architecture, embedded/firmware, and software
jobs: capture a representative JD, run Q1, confirm its selected family, click
**Generate now**, run Q2 once, then open the PDF and manifest from the dashboard.
Review `selected_cv.json` for selected experience/project block IDs, rank and reasons;
`manifest.json` for versions, selected/excluded blocks, section order, skills, paths,
and page count; `cv.tex` for rendered escaped source; `cv.pdf` for readability; and
`compile.log` when it exists for compiler diagnostics. Verify selected family, block
ordering, Experience/Projects order, skills, truthfulness, page count, manifest/PDF
consistency, and absence of invented claims. Record whether a multi-page output shows
`requires_fitting`; do not fit it in Phase 5.

The generic starter truth banks are still placeholder canonical profile data and need
replacement with the reviewed personal CV truth banks before production use. No
Phase 6 rewriting/truth checking or Phase 7 fitting has been added.

## Manual packet review

Automated packet generation is complete. Required human review of hardware/RTL,
CPU/GPU architecture, embedded, and software PDFs is still outstanding; record layout,
truthfulness, selected blocks, section order, skill provenance, and page count before
approving this phase.

PHASE BLOCKED — HUMAN DECISION REQUIRED
