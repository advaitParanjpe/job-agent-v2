# Phase 0B Repository Bootstrap

## Phase objective

Prepare `job-agent-v2/` as a clean, independent repository skeleton ready for
Phase 1 review, without implementing feature behavior.

Authoritative V2 planning files read:

- `job-agent-v2/jobagent_v2_plan/architecture.md`
- `job-agent-v2/jobagent_v2_plan/data_model.md`
- `job-agent-v2/jobagent_v2_plan/pipeline.md`
- `job-agent-v2/jobagent_v2_plan/status_model.md`
- `job-agent-v2/jobagent_v2_plan/build_roadmap.md`

Note: the requested `roadmap.md` file does not exist. The available roadmap file is
`build_roadmap.md`.

V1 audit files read:

- `job-agent-v1/docs/v2_audit/README.md`
- `job-agent-v1/docs/v2_audit/repository_map.md`
- `job-agent-v1/docs/v2_audit/v1_flow.md`
- `job-agent-v1/docs/v2_audit/reuse_inventory.md`
- `job-agent-v1/docs/v2_audit/data_model_analysis.md`
- `job-agent-v1/docs/v2_audit/queue_worker_analysis.md`
- `job-agent-v1/docs/v2_audit/test_reuse_analysis.md`
- `job-agent-v1/docs/v2_audit/prompt_schema_audit.md`
- `job-agent-v1/docs/v2_audit/dependency_audit.md`
- `job-agent-v1/docs/v2_audit/risk_register.md`
- `job-agent-v1/docs/v2_audit/v2_module_mapping.md`
- `job-agent-v1/docs/v2_audit/extraction_plan.md`

## Files created

- `job-agent-v2/.gitignore`
- `job-agent-v2/README.md`
- `job-agent-v2/pyproject.toml`
- `job-agent-v2/backend/src/jobagent_v2/__init__.py`
- `job-agent-v2/backend/src/jobagent_v2/app.py`
- `job-agent-v2/backend/tests/unit/test_backend_import.py`
- `job-agent-v2/backend/tests/integration/.gitkeep`
- `job-agent-v2/backend/tests/contract/.gitkeep`
- `job-agent-v2/backend/tests/regression/.gitkeep`
- `job-agent-v2/frontend/package.json`
- `job-agent-v2/frontend/src/index.html`
- `job-agent-v2/frontend/scripts/build-placeholder.mjs`
- `job-agent-v2/extension/manifest.json`
- `job-agent-v2/extension/popup.html`
- `job-agent-v2/extension/popup.js`
- `job-agent-v2/extension/scripts/validate.mjs`
- `job-agent-v2/scripts/check.py`
- `job-agent-v2/docs/build_reports/.gitkeep`
- `job-agent-v2/jobagent_v2_plan/v1_reference_map.md`
- `job-agent-v2/docs/build_reports/phase_0b_repository_bootstrap.md`

## Files modified

- None outside `job-agent-v2/`.
- `job-agent-v1/` was not edited. `git diff -- job-agent-v1` produced no output.
- A stray `job-agent-v2/.DS_Store` was removed from the V2 tree.

## Tooling decisions

- Backend uses a minimal Python package under `backend/src` with pytest discovery under
  `backend/tests`.
- `pyproject.toml` defines package metadata, pytest paths, and intended future
  `ruff`/`mypy` dev tooling.
- Because no dependency install was performed, the active bootstrap check uses only
  installed Python, pytest, and Node.
- `scripts/check.py` is the standard project check command. It runs:
  - format checks for newline, trailing whitespace, and line length.
  - lint checks by parsing Python files with `ast`.
  - a type-oriented import contract over the typed backend bootstrap metadata.
  - pytest.
  - frontend placeholder build.
  - extension manifest validation.
- Frontend placeholder build uses Node only and copies `frontend/src/index.html` to
  `frontend/dist/index.html`.
- Extension placeholder contains a valid MV3 manifest and disabled popup button only.

## Commands run

```text
sed -n '1,240p' job-agent-v2/jobagent_v2_plan/architecture.md
sed -n '1,240p' job-agent-v2/jobagent_v2_plan/data_model.md
sed -n '1,260p' job-agent-v2/jobagent_v2_plan/pipeline.md
sed -n '1,240p' job-agent-v2/jobagent_v2_plan/status_model.md
sed -n '1,260p' job-agent-v2/jobagent_v2_plan/roadmap.md
rg --files job-agent-v1/docs/v2_audit
find job-agent-v2/jobagent_v2_plan -maxdepth 2 -type f -print
sed -n '1,280p' job-agent-v2/jobagent_v2_plan/build_roadmap.md
sed -n '1,320p' job-agent-v1/docs/v2_audit/*.md
sed -n '1,360p' job-agent-v1/docs/v2_audit/extraction_plan.md
python3 --version
python3 -m pytest --version
python3 -m ruff --version
python3 -m mypy --version
node --version
npm --version
find job-agent-v2 -maxdepth 3 -print | sort
python3 scripts/check.py
git status --short job-agent-v1
git status --short job-agent-v2
rg -n "FastAPI|queue|extract|score|tailor|pdf|llm|OpenAI|dashboard|worker|POST|GET" job-agent-v2/backend job-agent-v2/frontend job-agent-v2/extension job-agent-v2/scripts
git diff -- job-agent-v1
git status --short --untracked-files=no job-agent-v1
git rev-parse --show-toplevel
git status --short job-agent-v1 job-agent-v2
git status --short --untracked-files=no job-agent-v1 job-agent-v2
find job-agent-v2 -maxdepth 4 -print | sort
```

Cleanup commands run after checks:

```text
rm -rf job-agent-v2/.pytest_cache job-agent-v2/backend/src/jobagent_v2/__pycache__ job-agent-v2/backend/tests/unit/__pycache__ job-agent-v2/frontend/dist
rm -f job-agent-v2/.DS_Store
```

## Results

- `python3 scripts/check.py`: passed.
- Pytest collected 1 smoke test and passed.
- Frontend placeholder build completed.
- Extension structure validation passed.
- `python3 -m ruff --version`: not installed in the current environment.
- `python3 -m mypy --version`: not installed in the current environment.
- No network install was attempted.
- No V1 source was copied.
- No Phase 1 functionality was implemented.

## Reuse candidates identified

The full V1 reference map is in
`job-agent-v2/jobagent_v2_plan/v1_reference_map.md`.

High-confidence candidates from the audit:

- URL canonicalization primitives.
- Browser extension extraction ideas and focused extractors.
- Deterministic JD parser heuristics.
- Work authorization guardrails.
- Truth-bank extraction, canonicalization, validation, and repair ideas.
- Structured scoring and CV selection schemas.
- Tailoring proposal/truth-check schemas and deterministic edit policy.
- LaTeX escaping, rendering, page count, fit, prune, and manifest primitives.
- Local path and artifact key safety checks.

Rejected or deferred V1 areas:

- Auth/session system.
- Beta quotas.
- Hosted R2/Supabase/Netlify deployment assumptions.
- In-memory packet run tracking.
- Synchronous score-and-generate extension route.
- V1 migration scripts.
- V1 React dashboard implementation.

## Risks

- Requested `roadmap.md` does not exist; `build_roadmap.md` was used.
- The Git root is `/Users/advaitparanjpe`, not the project directory, so unscoped
  `git status --short` includes unrelated home-directory noise.
- `ruff` and `mypy` are configured as intended dev tooling but are not currently
  installed.
- The backend is only an importable shell. Phase 1 must still choose exact API and
  storage dependencies before real queue skeleton work.
- Extension and frontend are placeholders only.

## Deferred work

- Real queues.
- Real JD extraction.
- Real scoring.
- CV tailoring.
- PDF generation.
- Dashboard features.
- LLM calls.
- Database schema and migrations.
- Durable worker and scheduler implementation.

## Final directory structure

```text
job-agent-v2
job-agent-v2/.gitignore
job-agent-v2/README.md
job-agent-v2/backend
job-agent-v2/backend/src
job-agent-v2/backend/src/jobagent_v2
job-agent-v2/backend/src/jobagent_v2/__init__.py
job-agent-v2/backend/src/jobagent_v2/app.py
job-agent-v2/backend/tests
job-agent-v2/backend/tests/contract
job-agent-v2/backend/tests/contract/.gitkeep
job-agent-v2/backend/tests/integration
job-agent-v2/backend/tests/integration/.gitkeep
job-agent-v2/backend/tests/regression
job-agent-v2/backend/tests/regression/.gitkeep
job-agent-v2/backend/tests/unit
job-agent-v2/backend/tests/unit/test_backend_import.py
job-agent-v2/docs
job-agent-v2/docs/build_reports
job-agent-v2/docs/build_reports/.gitkeep
job-agent-v2/docs/build_reports/phase_0b_repository_bootstrap.md
job-agent-v2/extension
job-agent-v2/extension/manifest.json
job-agent-v2/extension/popup.html
job-agent-v2/extension/popup.js
job-agent-v2/extension/scripts
job-agent-v2/extension/scripts/validate.mjs
job-agent-v2/frontend
job-agent-v2/frontend/package.json
job-agent-v2/frontend/scripts
job-agent-v2/frontend/scripts/build-placeholder.mjs
job-agent-v2/frontend/src
job-agent-v2/frontend/src/index.html
job-agent-v2/jobagent_v2_plan
job-agent-v2/jobagent_v2_plan/architecture.md
job-agent-v2/jobagent_v2_plan/build_roadmap.md
job-agent-v2/jobagent_v2_plan/data_model.md
job-agent-v2/jobagent_v2_plan/pipeline.md
job-agent-v2/jobagent_v2_plan/v1_reference_map.md
job-agent-v2/jobagent_v2_plan/status_model.md
job-agent-v2/pyproject.toml
job-agent-v2/scripts
job-agent-v2/scripts/check.py
```

## Final git status

Scoped status:

```text
?? job-agent-v1/
?? job-agent-v2/
```

Scoped status excluding untracked files:

```text
```

Interpretation:

- There are no tracked modifications under `job-agent-v1/`.
- The repository root is `/Users/advaitparanjpe`, so both project directories appear
  untracked from that root.
- All authored Phase 0B changes are under `job-agent-v2/`.

PHASE READY FOR REVIEW
