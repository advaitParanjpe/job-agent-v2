# Project Roadmap

This roadmap reconciles the original `jobagent_v2_plan/` direction, historical build reports, current source code, and validation evidence as of 2026-06-29. Older phase reports remain useful historical records, but this file is the active planning surface.

## Product boundary
JobAgent V2 is a local-only personal job application queue and canonical packet-generation system. It is not a SaaS app, scraper-first automation system, auto-apply bot, full ATS, or generated-prose CV rewriter.

The preferred route is one reliable local workflow:

```text
capture job -> persist/dedupe -> intake -> score/rank -> promote -> generate canonical packet -> review artifacts
```

## Completed and verified

### Phase 0: Planning and bootstrap
Status: complete.

Evidence:
- Planning docs exist under `jobagent_v2_plan/`.
- Bootstrap report exists at `docs/build_reports/phase_0b_repository_bootstrap.md`.
- Python package, test layout, frontend placeholder, extension skeleton, and `scripts/check.py` are present.

### Phase 1: Persistent queue skeleton
Status: complete, superseded by later real workers.

Evidence:
- SQLite `jobs` and `job_events` tables in `backend/src/jobagent_v2/storage.py`.
- API/service/worker path in `backend/src/jobagent_v2/api.py`, `service.py`, and `workers.py`.
- Integration coverage in `backend/tests/integration/test_phase1_flow.py`.

Superseded notes:
- Original dummy intake/Q2 placeholders are no longer the current behavior. Queue 1 now performs deterministic intake and scoring. Queue 2 now generates real packet artifacts.

### Phase 2: Real intake
Status: complete.

Evidence:
- `backend/src/jobagent_v2/intake.py` implements JD extraction, quality bands, field provenance, warnings, failure/manual-review states, and update mapping.
- URL normalization is implemented in `backend/src/jobagent_v2/url_utils.py`.
- Intake tests and fixtures exist under `backend/tests/unit/test_intake_parser.py`, `test_intake_hardening.py`, `test_url_normalization_phase2.py`, and `backend/tests/integration/test_phase2_intake_flow.py`.

### Phase 3: Deterministic Queue 1 scoring
Status: complete with generic starter truth-bank data.

Evidence:
- `backend/src/jobagent_v2/scoring.py` structures JDs, classifies role family, selects CV family, loads configured truth banks, scores blocks, and computes recommendations.
- Configured families and truth banks are under `backend/src/jobagent_v2/data/`.
- Persistence for `job_scores` and `job_block_scores` is in `backend/src/jobagent_v2/storage.py`.
- Coverage exists in `backend/tests/unit/test_scoring.py` and `backend/tests/integration/test_phase3_scoring_flow.py`.

Limitations:
- Truth banks are placeholder canonical content, not user-reviewed personal CV data.
- Scoring is deterministic and heuristic; it is useful for local triage but not a validated production ranking model.

### Phase 3B/3C: Optional hybrid semantic evidence
Status: functionally complete offline; live semantic quality not verified in this audit.

Evidence:
- `backend/src/jobagent_v2/hybrid_scoring.py` validates semantic evidence and preserves deterministic final aggregation.
- `backend/src/jobagent_v2/llm_client.py` contains opt-in OpenAI transport and fallback behavior.
- Tests cover fallback and mocked provider behavior in `backend/tests/unit/test_hybrid_scoring.py`, `test_openai_transport.py`, and `backend/tests/integration/test_phase3b_hybrid_flow.py`.
- `.env.example` documents opt-in live provider settings.

Limitations:
- No credentialed live provider smoke test was run during this audit.
- Live provider/model availability and billing are operator responsibilities.

### Phase 4: Promotion scheduler
Status: complete.

Evidence:
- `backend/src/jobagent_v2/promotion.py` implements threshold/manual/star policy and capacity/budget controls.
- Durable `q2_tasks` persistence, leasing, retry, and recovery are in `backend/src/jobagent_v2/storage.py`.
- Tests are in `backend/tests/integration/test_phase4_promotion_flow.py`.

### Phase 5: Basic packet generation
Status: complete with placeholder canonical content.

Evidence:
- `backend/src/jobagent_v2/packets.py` builds selected CV JSON, renders LaTeX, compiles PDF, counts pages when `pdfinfo` is available, and writes manifests.
- Packet attempt persistence and artifact serving are in `backend/src/jobagent_v2/storage.py`, `service.py`, and `api.py`.
- Template exists at `backend/src/jobagent_v2/templates/basic_cv.tex`.
- Tests are in `backend/tests/unit/test_phase5_packets.py` and `backend/tests/integration/test_phase5_packet_generation.py`.
- `python3 scripts/check.py` passed on 2026-06-29 with 73 backend tests plus frontend and extension checks.

Limitations:
- Generated packets are technically valid but use generic starter truth-bank content until Phase 6.
- Multi-page packets are flagged for fitting but not fixed.

## Recently completed

### Archived Job Restore/Re-Score and Semantic Requirement Extraction
Status: complete.

Goal:
- Make duplicate capture truthful for archived, active, completed, and failed
  jobs, and add a grounded semantic requirement layer on top of deterministic
  requirement extraction.

Delivered:
- Structured duplicate outcomes for archived, active, completed, and failed
  existing jobs.
- Owner-scoped restore, re-score, restore-and-re-score, and analysis-history
  API/service paths.
- Additive versioned `analysis_runs` persistence and latest-run score
  filtering so new scoring attempts do not overwrite previous analyses.
- Restore behavior that preserves prior packets, reviews, regenerated packets,
  and audit records.
- Frontend/extension messaging and actions for restore, restore-and-re-score,
  re-score, and previous analyses.
- Semantic requirement validation/fusion with approved capability ontology,
  evidence grounding, negation and generic-language rejection, confidence
  discounting for semantic-only findings, and conservative reuse by the
  existing requirement-aware project selector.
- Offline semantic requirement diagnostic and evaluation command.

Validation evidence:
- `PYTHONPATH=backend/src pytest backend/tests/unit -q`: 179 passed, 2 skipped.
- `node frontend/scripts/test-dashboard.mjs`: passed.
- `python3 scripts/evaluate_cross_domain_portfolio.py`: shortlist recall 1.0,
  unexpected shortlist rate 0.0, no failures.
- `PYTHONPATH=backend/src python3 scripts/evaluate_semantic_requirements.py`:
  capability precision 1.0, capability recall 1.0, false positives 0 on the
  small fixture set.
- `./scripts/semantic-requirements-check --no-network`: `simulated_success`.
- `./scripts/semantic-requirements-check`: safe live failure
  `response_invalid` with no key printed.
- `python3 scripts/check.py`: 221 passed, 2 skipped, plus frontend and
  extension checks.
- `git diff --check`: passed.

Important limitations:
- Live semantic requirement success was not verified; semantic fusion remains
  feature-flagged/fallback-first.
- The evaluation set is intentionally small and invariant-style, not a broad
  calibration dataset.
- True multi-owner same-URL insertion remains constrained by the legacy local
  unique normalized-URL schema.

### Requirement-Aware Cross-Family Project Portfolio Selection
Status: complete.

Goal:
- Decouple base CV-family selection from approved project portfolio selection
  so cross-domain roles can consider bridge projects without weakening
  canonical-content guarantees.

Delivered:
- Added grounded requirement extraction with normalized capabilities,
  evidence quotes, specificity, importance, differentiation value, and
  required/preferred source context.
- Added project portfolio metadata for every approved block: home family,
  eligible families, bounded capabilities, bridge domains, evidence terms, and
  portfolio strength.
- Added requirement-aware portfolio scoring across eligible approved projects,
  including requirement coverage, specificity coverage, bridge bonus,
  base-family affinity, shortlist reasons, and counterfactual gain.
- Preserved one-substitution policy, explicit compatibility checks, exact
  approved project-block text, immutable master CVs, and one-page validation.
- Added a Qualcomm-style ML/NPU regression fixture that keeps the ML base CV,
  shortlists TinyNPU, records NPU/accelerator coverage, and surfaces the
  option for review when automatic substitution is not justified.
- Added negative controls for generic ML and pure RTL roles.
- Updated the frontend to show Base CV and Project Portfolio separately with
  requirement coverage and alternatives under disclosures.
- Added `scripts/evaluate_cross_domain_portfolio.py` for offline invariant
  evaluation.

Validation evidence:
- `PYTHONPATH=backend/src pytest backend/tests/unit -q`: 171 passed, 2 skipped.
- `node frontend/scripts/test-dashboard.mjs`: passed.
- `python3 scripts/evaluate_cross_domain_portfolio.py`: 6 examples,
  shortlist recall 1.0, unexpected shortlist rate 0.0, no failures.
- `python3 scripts/check.py`: 213 backend tests passed, 2 skipped, plus
  frontend and extension checks.
- `git diff --check`: passed.

Important limitations:
- Portfolio weights remain deterministic initial policy weights behind the
  current conservative review/substitution policy; they were not promoted from
  a broad real-job calibration run.
- Semantic requirement extraction is not yet active; deterministic extraction
  provides the current requirement analysis.

### Minimal Retro Frontend and Stage-Based Workflow Redesign
Status: complete.

Goal:
- Make the local frontend feel like a minimal, calm, product-like workstation
  interface centered on one stage-based job pipeline and one obvious next
  action.

Delivered:
- Added a central frontend stage model for Added, Analysing role, Choosing CV,
  Generating packet, Ready, Needs review, Reviewed, Regenerating, Reviewed
  packet ready, failed/action-needed, and archived states.
- Redesigned Jobs with a compact list, selected-job panel, current-stage card,
  text step indicator, key result strip, and one primary action.
- Hid score bars, deterministic evidence, semantic evidence, packet manifest
  links, version metadata, and archive/delete behavior behind disclosures.
- Redesigned Reviews as an inbox with a staged recommendation/change/confirm
  detail flow.
- Redesigned System as compact status cards with technical diagnostics under
  disclosures.
- Added a CSS custom-property design system for the minimal retro visual style:
  warm neutral background, thin borders, monospace status labels, square
  progress markers, restrained green accent, and no fake terminal effects.
- Updated README with navigation, stage workflow, advanced-detail placement,
  and visual design intent.

Validation evidence:
- `node frontend/scripts/test-dashboard.mjs`: passed.
- `python3 scripts/check.py`: 206 backend tests passed, 2 skipped, plus
  frontend and extension checks.
- `./scripts/dev-up --open`: started successfully and served redesigned
  frontend assets; the stack was stopped cleanly.
- `git diff --check`: passed.

Important limitations:
- Interactive browser inspection was limited by tool visibility; validation is
  based on dev startup logs and deterministic frontend DOM tests.

### Frontend Usability, Demo Cleanup, and Semantic Observability
Status: complete.

Goal:
- Make the local dashboard understandable without queue-architecture knowledge,
  expose semantic success/fallback explicitly, and safely remove demo data.

Delivered:
- Added `Jobs`, `Reviews`, and `System` top-level navigation.
- Made Jobs the default master/detail workflow view with summary counts,
  filters, workflow timeline, selected-job detail, candidate-fit section,
  CV-family classification section, semantic analysis section, packet section,
  and progressive diagnostics.
- Moved worker status, queue diagnostics, semantic LLM configuration, and demo
  cleanup controls to System.
- Simplified Reviews while preserving backend-validated review actions and
  expandable evidence.
- Added explicit semantic status and safe metadata for live success, disabled,
  not configured, fallback, request failure, invalid response, timeout, and not
  attempted states.
- Added `./scripts/semantic-check` with offline fake mode and live mode that
  does not print credentials or write to the jobs database.
- Added job `source_provenance`, demo seeding provenance, owner-scoped
  clear-demo API/CLI, and conservative individual delete/archive behavior.

Validation evidence:
- `PYTHONPATH=backend/src pytest backend/tests/unit -q`: 164 passed, 2 skipped.
- `node frontend/scripts/test-dashboard.mjs`: passed.
- `./scripts/semantic-check --no-network`: passed with selected family
  `verification` and evidence count 3.
- `python3 scripts/check.py`: 206 backend tests passed, 2 skipped, plus
  frontend and extension checks.
- `git diff --check`: passed.

Important limitations:
- Live `./scripts/semantic-check` ran without printing the configured key but
  returned `request_failed`; live semantic success was not verified in this
  environment.

### State Reconstruction and Terminology Normalization
Status: complete.

Goal:
- Make repository state truthful and durable for future autonomous Codex sessions.

Scope:
- Create `project/current.md`, `project/roadmap.md`, and `project/history.md`.
- Add `AGENTS.md`.
- Update README/API/server/source labels that misrepresent the current implementation.
- Run the standard validation commands.

Validation evidence:
- `python3 scripts/check.py` passed on 2026-06-29.
- `git diff --check` passed on 2026-06-29.

### Phase 6A: Canonical Truth-Bank Registration and Validation
Status: complete.

Goal:
- Make real canonical CV families registerable, versioned, previewable, and strongly validated without inventing personal CV content.

Scope direction:
- Define and enforce a versioned truth-bank schema.
- Reject placeholder profile content, duplicate IDs, unsupported block types, missing provenance, and incomplete header/education content in registered real truth banks.
- Add deterministic preview/listing support for local validation.
- Keep starter fixtures available only as explicit dev/test data if needed.

Validation evidence:
- `python3 scripts/check.py` passed on 2026-06-29 with 89 backend tests plus frontend and extension checks.
- `git diff --check` passed on 2026-06-29.

### Phase A: Canonical Master-CV Registration and Validation
Status: complete.

Goal:
- Register and validate four fixed approved master CVs, expose them to packet generation, and avoid dynamic rewriting.

Delivered:
- Registered `digital_ic`, `verification`, `software`, and `ml`.
- Validated each family has approved `.tex` and one-page readable `.pdf`.
- Recorded immutable metadata, paths, hashes, family IDs, and approval status.
- Packet generation copies approved master `.tex` and `.pdf` unchanged.
- No dynamic rewriting, skills rewriting, or project substitution was added.

Validation evidence:
- `python3 scripts/check.py` passed on 2026-06-29 with 96 backend tests passed, 1 local TeX compile test skipped, plus frontend and extension checks.
- `git diff --check` passed on 2026-06-29.

### Phase B: Auditable Four-Family Job Classification
Status: complete.

Goal:
- Classify each job across all four approved families before candidate-fit scoring.

Delivered:
- Added a versioned deterministic classifier configuration at `backend/src/jobagent_v2/data/family_classifier.json`.
- Added `backend/src/jobagent_v2/family_classifier.py` with normalized scores for `digital_ic`, `verification`, `software`, and `ml`.
- Preserved rule evidence, optional semantic evidence, selected family, confidence, decision category, review flag, classifier version, and config version.
- Combined deterministic and optional semantic scores with configurable 60/40 weighting; deterministic-only behavior remains the offline default.
- Persisted family classification separately from candidate-fit scoring in `job_family_classifications` and job snapshot fields.
- Integrated selected family into packet generation while still copying approved master `.tex` and `.pdf` artifacts unchanged.
- Added docs at `docs/family_classification.md`.

Policy notes:
- Python for UVM regression infrastructure should remain verification-oriented.
- Python for performance modeling alongside RTL ownership should remain Digital IC-oriented.
- ML training, inference, quantization, evaluation, and ML infrastructure should score toward ML.
- Backend APIs, distributed systems, databases, developer tools, and production software should score toward Software.

Validation evidence:
- `python3 -m pytest backend/tests/unit/test_family_classifier.py backend/tests/unit/test_scoring.py backend/tests/integration/test_phase3_scoring_flow.py backend/tests/integration/test_phase5_packet_generation.py -q` passed on 2026-06-29 with 41 tests.
- `python3 scripts/check.py` passed on 2026-06-29 with 128 backend tests passed, 1 local TeX compile test skipped, plus frontend and extension checks.
- `git diff --check` passed on 2026-06-29.

Important limitations:
- Deterministic weights are heuristic and may need tuning after real job review.
- Live semantic family-classification quality was not credential-tested; tests use deterministic fake providers.
- Hybrid/close/low-confidence classifications are auditable but no project substitution occurs yet.

## Recently completed

### Phase C: Bounded Project-Block Tailoring
Status: complete.

Goal:
- Tailor only through approved whole-project blocks after family classification is reliable.

Scope direction:
- Use approved project blocks only.
- Initially allow at most one whole-project substitution.
- Optionally reorder whole project blocks.
- Never rewrite, shorten, merge, split, or generate bullets.
- Preserve fixed header/contact, education, coursework, and experience.
- Ensure the resulting PDF remains one page.
- Record an audit trail for every classification, substitution, and ordering decision.

Initial milestone boundary:
- First establish an approved project-block registry and policy enforcement.
- If current approved master CVs do not contain enough safely structured approved project blocks, document the required user-approved input contract rather than fabricating content.

Delivered:
- Added `backend/src/jobagent_v2/data/project_block_registry.json` with 12 approved whole-project block variants from the four canonical master CVs.
- Added `backend/src/jobagent_v2/project_blocks.py` with deterministic master-TeX extraction, exact text/hash validation, family eligibility, compatibility rules, render-budget validation, and future decision-record validation.
- Registered family-specific variants separately, including Software and ML `SparrowML` blocks.
- Enforced maximum one substitution, no bullet rewriting, no dynamic skills, no education/experience editing, and explicit compatibility.
- Added documentation at `docs/project_block_registry.md`.

Validation evidence:
- `python3 -m pytest backend/tests/unit/test_project_blocks.py backend/tests/unit/test_master_cvs.py backend/tests/unit/test_family_classifier.py backend/tests/integration/test_phase5_packet_generation.py -q` passed on 2026-06-29 with 60 passed, 2 skipped.
- `python3 scripts/check.py` passed on 2026-06-29 with 148 backend tests passed, 2 local TeX compile tests skipped, plus frontend and extension checks.
- `git diff --check` passed on 2026-06-29.

### Phase D: One-Block Tailoring Selection and Packet Integration
Status: complete.

Goal:
- Consume the Phase B classifier and Phase C registry to produce at most one approved whole-project substitution in packet generation.

Delivered:
- Added a versioned Phase D tailoring policy at `backend/src/jobagent_v2/data/tailoring_policy.json`.
- Added `backend/src/jobagent_v2/tailoring.py` with deterministic approved-block scoring, one-substitution selection, compatibility enforcement, deterministic project reordering, structural Projects-section TeX replacement, immutable-section validation, one-page PDF validation, and master fallback.
- Integrated tailoring into Queue 2 packet generation for approved master families.
- Persisted complete audit records in SQLite `job_tailoring_decisions` and packet `tailoring_decision.json` artifacts.
- Preserved master-copy behavior when no tailoring is selected or when tailored validation fails.
- Added documentation at `docs/bounded_tailoring.md`.

Validation evidence:
- `python3 -m pytest backend/tests/unit/test_tailoring.py backend/tests/unit/test_project_blocks.py backend/tests/unit/test_master_cvs.py backend/tests/unit/test_family_classifier.py backend/tests/unit/test_scoring.py backend/tests/integration/test_phase3_scoring_flow.py backend/tests/integration/test_phase5_packet_generation.py -q` passed on 2026-06-30 with 74 passed, 2 skipped.
- `python3 scripts/check.py` passed on 2026-06-30 with 154 backend tests passed, 2 local TeX compile tests skipped, plus frontend and extension checks.
- `git diff --check` passed on 2026-06-30.

Important limitations:
- Tailoring thresholds are heuristic and need labelled real-job calibration.
- Reviewable close/hybrid decisions are auditable but there is no dedicated review UI yet.
- Real PDF compilation remains dependent on local LaTeX availability; unavailable or failed compilation falls back to the master.

### Phase E: Classifier and Tailoring Threshold Calibration
Status: complete.

Goal:
- Calibrate classifier and tailoring thresholds using a labelled real-job evaluation set.

Delivered:
- Added an offline labelled dataset format and a 90-example versioned dataset.
- Added deterministic evaluation for family classification, decision/review behavior, and bounded tailoring decisions.
- Added bounded threshold search and conservative promotion gates.
- Generated JSON and Markdown calibration reports under `reports/calibration/`.
- Did not promote a candidate config because holdout safety gates failed.

Validation evidence:
- `python3 scripts/check.py` passed on 2026-06-30 with 162 backend tests passed, 2 local TeX compile tests skipped, plus frontend and extension checks.
- `git diff --check` passed on 2026-06-30.

Important limitations:
- Dataset examples are concise synthetic/paraphrased role patterns.
- Wrong high-confidence no-review and out-of-scope review-rate gates did not pass.
- Live semantic evaluation was not run.

### Phase F: Review API for Classification and Tailoring Decisions
Status: complete.

Goal:
- Expose auditable classification and tailoring decisions through local review APIs before release hardening.

Delivered:
- Added durable owner-scoped review queue and append-only review resolution history.
- Created pending reviews from review-required classification and tailoring outcomes.
- Added review list/detail/resolve/feedback API and service methods.
- Validated family overrides, out-of-scope marking, master-unchanged choices, and approved compatible project-block replacement.
- Preserved original classification and tailoring audit rows.
- Added owner-scoped packet artifact serving.
- Added review API documentation and focused backend tests.

Validation evidence:
- `python3 scripts/check.py` passed on 2026-06-30 with 172 backend tests passed, 2 local TeX compile tests skipped, plus frontend and extension checks.
- `git diff --check` passed on 2026-06-30.

Important limitations:
- Review-driven packet regeneration is recorded as queued status but is not consumed by a worker yet.
- The dashboard does not yet expose the review workflow.

## Active milestone

### Phase G: Minimal Review UI Integration
Status: complete.

Goal:
- Add a minimal local dashboard workflow for inspecting and resolving pending Phase F reviews.

Delivered:
- Added a dashboard review queue and compact review-detail workflow.
- Exposed family scores, classification evidence, tailoring decisions, immutable guarantees, allowed actions, and resolution history without raw JSON.
- Added owner-scoped frontend review API helpers and manual clear-match review creation.
- Submitted only registered family IDs and backend-approved replacement tuples.
- Displayed queued regeneration honestly without claiming reviewed packets were regenerated.
- Added backend metadata for family/project display names and approved compatible replacement options.

Validation evidence:
- `python3 scripts/check.py` passed on 2026-06-30 with 173 backend tests passed, 2 local TeX compile tests skipped, plus frontend and extension checks.
- `git diff --check` passed on 2026-06-30.

Important limitations:
- Review-driven packet regeneration is still queued only.
- The UI is minimal and should not expand into resume editing.

## Active milestone

### Phase H: Review-Driven Packet Regeneration Worker
Status: complete.

Goal:
- Consume queued review resolutions and generate linked reviewed packet artifacts without weakening canonical-content guarantees.

Scope direction:
- Process review resolutions with `regeneration_status: queued`.
- Validate resolved family/project choices against approved masters, registry, and one-substitution policy.
- Create linked packet artifact versions while preserving previous valid packets and original audit records.
- Update regeneration status accurately for queued, processing, complete, and failed outcomes.
- Keep packet APIs and dashboard status display compatible.

Delivered:
- Added durable review-regeneration jobs with SQLite claiming, lease recovery,
  attempt counts, timestamps, safe failure fields, and source/generated packet
  linkage.
- Added idempotent reviewed packet generation for family-master outcomes and
  one approved project-block substitution outcomes.
- Preserved previous ready packets and original automated audit records.
- Exposed reviewed packet status and links through the review API/dashboard.
- Added the local worker command
  `PYTHONPATH=backend/src python3 -m jobagent_v2.regeneration_worker --once`
  and API endpoint `POST /api/workers/regeneration/run-once`.

Validation evidence:
- `python3 scripts/check.py` passed on 2026-06-30 with 177 backend tests passed,
  2 local TeX compile tests skipped, plus frontend and extension checks.
- `git diff --check` passed on 2026-06-30.

Important limitations:
- The worker is currently run manually through a command or local API endpoint.
- Scheduling, monitoring, and operator-facing worker health are not yet built.

## Blocked or deferred

### Live semantic quality review
Status: deferred/operator-dependent.

Goal:
- Run a small credentialed smoke and semantic-quality comparison only when the operator explicitly enables live LLM settings.

Required external input:
- `JOBAGENT_LLM_API_KEY`, selected model, and willingness to make paid provider calls.

## Future milestones

### Operational worker scheduling and monitoring
Status: complete.

Goal:
- Make local Q1/Q2/regeneration worker execution observable and easy to run
  without changing the canonical CV policy.

Potential scope:
- Document and/or add a single local worker loop command.
- Add queue-health/status reporting for Q1, Q2, and review regeneration.
- Add stale-job recovery visibility and concise operational logs.
- Keep all processing local-only and deterministic.

Delivered:
- Added `jobagent_v2.worker_runner` with independently runnable `q1`, `q2`,
  and `regeneration` loops plus combined `--all` mode.
- Added environment-backed polling, deterministic idle backoff, heartbeat
  persistence, graceful SIGINT/SIGTERM stop handling, and JSON operational logs.
- Added durable worker instance and worker event status tables.
- Added queue summaries and health diagnostics derived from `jobs`,
  `q2_tasks`, and `review_regeneration_jobs`.
- Added worker status APIs and a compact dashboard Worker status section.
- Documented startup commands, health rules, queue metrics, logging, stale
  recovery, and troubleshooting in `docs/worker_operations.md`.

Validation evidence:
- `python3 scripts/check.py` passed on 2026-06-30 with 184 backend tests passed,
  2 local TeX compile tests skipped, plus frontend and extension checks.
- `git diff --check` passed on 2026-06-30.

Important limitations:
- The local `--all` runner is intentionally simple and not a process manager.
- It does not spawn worker processes from the HTTP API.
- Packaging and one-command local startup remain future release-hardening work.

### End-to-end release hardening
Status: complete.

Goal:
- Make the local capture-to-reviewed-packet workflow easier to validate and
  prepare for release without changing canonical CV content policy.

Potential scope:
- End-to-end smoke documentation and checks from capture through reviewed
  packet regeneration.
- Package-data verification for required JSON, templates, master CVs, and
  frontend/extension assets.
- Clear local setup checks for Python, Node, LaTeX, and optional live semantic
  credentials.
- Migration/backup notes for local SQLite data.
- CI-equivalent command documentation around `python3 scripts/check.py`.

Delivered:
- Set release-candidate version metadata to `v0.1.0`.
- Added release configuration helpers, preflight diagnostics, and database
  schema inspection.
- Added `./scripts/dev-up` / `scripts/dev_up.py` for local API, workers, and
  frontend startup with preflight and child-process shutdown.
- Added `scripts/release_smoke.py` for an isolated deterministic flow through
  Q1, Q2, review resolution, reviewed regeneration, packet versioning, and
  worker status.
- Added `scripts/demo_seed.py` with synthetic demo jobs in a separate demo
  database by default.
- Repaired migration ordering for older packet schemas before creating the
  regeneration idempotency index.
- Replaced stale README phase language with release-candidate setup, startup,
  smoke, worker, review, privacy, and troubleshooting guidance.
- Added `docs/release_checklist.md` and `CHANGELOG.md`.

Validation evidence:
- `PYTHONPATH=backend/src pytest backend/tests/unit/test_release_hardening.py -q`:
  7 passed.
- `python3 scripts/release_smoke.py`: passed.
- `python3 scripts/demo_seed.py --db-path /tmp/jobagent-demo-seed.sqlite3 --artifact-root /tmp/jobagent-demo-artifacts`:
  created 7 synthetic jobs.
- `PYTHONPATH=backend/src python3 -m jobagent_v2.preflight --json --skip-port-check`:
  passed.
- `python3 scripts/check.py`: 191 backend tests passed, 2 local TeX compile
  tests skipped, plus frontend and extension checks.
- `git diff --check`: passed.

Important limitations:
- `python3 -m build` could not be run in the current environment because the
  `build` module was not installed before this milestone; `build>=1.2` is now
  included in the dev extra for clean release environments.
- The release remains local-first and owner-scoped; production authentication,
  hosted deployment, and multi-user hardening remain out of scope.

### Local setup and one-command startup simplification
Status: complete.

Goal:
- Let a local operator test the complete application, including optional live
  LLM semantic classification, through repository-root `.env.local`
  configuration without manually exporting environment variables each session.

Delivered:
- Added repository-root `.env.local` loading through
  `jobagent_v2.config.load_local_env`.
- Added supported `./scripts/setup-local`, `./scripts/dev-down`,
  `./scripts/dev-status`, and `./scripts/demo-local` commands.
- Kept `.env.local` and `.runtime/` local-only through explicit gitignore
  entries.
- Preserved deterministic offline defaults and operator precedence: exported
  shell variables win over `.env.local`.
- Wired local env loading into one-command startup and relevant local CLIs:
  preflight, database status, API server, worker runner, review regeneration,
  calibration, and live LLM smoke.
- Updated README and `.env.example` with the setup-local workflow, isolated
  local-test database/artifact paths, live semantic opt-in settings,
  shutdown/status commands, demo seeding, and port-conflict troubleshooting.
- `dev-up` validates missing/placeholder LLM keys without a live network call,
  prints only safe LLM configuration status, prefixes child output, and writes
  ignored PID state for safe shutdown.
- `dev-down` stops only tracked child processes after live process identity
  checks where available.

Validation evidence:
- `PYTHONPATH=backend/src pytest backend/tests/unit/test_release_hardening.py -q`:
  18 passed.
- `./scripts/setup-local`: created `.env.local` from `.env.example` after
  approved pip network access.
- `./scripts/dev-status`: reported stopped services and missing API key without
  exposing secrets.
- `./scripts/dev-up --skip-preflight`: failed helpfully when LLM was enabled
  and the key was missing.
- Isolated `./scripts/dev-up --skip-preflight` startup smoke passed with `/tmp`
  data and alternate ports; `./scripts/dev-down` stopped the tracked API,
  worker, and frontend PIDs.
- `./scripts/demo-local`: created 7 jobs in `data/local-test/jobagent.sqlite3`.
- `python3 scripts/check.py`: 202 backend tests passed, 2 local TeX compile
  tests skipped, plus frontend and extension checks.
- `git diff --check`: passed.

Important limitations:
- Live semantic quality was not credential-tested.
- `.env.local` is a local convenience, not production secret management.

### Deterministic one-page validation and fitting
Status: not started.

Goal:
- Apply bounded layout tiers and optional-block removal without changing canonical wording.

Acceptance direction:
- Render, measure page count, apply only permitted layout changes, prune at most configured optional blocks, preserve required education/header/skills, and fail visibly with manual review if no safe fit is possible.

### Phase 8: Workflow and review polish
Status: not started.

Goal:
- Make the local review loop efficient after the core artifacts are truthful.

Potential scope:
- Retry buttons and clearer failure recovery.
- Archive/mark applied.
- Packet preview/open actions and manifest explanation polish.
- Regenerate action with attempt history.
- Family and section-order visibility.

### Release readiness
Status: superseded by `job-agent-v2 v0.1.0` release-candidate hardening.

Goal:
- Make a clean local install/run experience.

Potential scope:
- Package-data verification for truth banks and templates.
- Clear setup instructions for Python, Node, LaTeX, and optional OpenAI.
- CI equivalent to `python3 scripts/check.py`.
- Migration and backup notes for local SQLite data.

## Superseded or rejected roadmap items
- Generated CV prose, LLM bullet rewriting, paraphrasing, semantic refinement, generated summaries/headlines, rewrite scoring loops, and truth-checking generated rewrites are rejected for the core product by `docs/architecture_decisions/ADR-001-canonical-cv-tailoring.md`.
- Free-form resume generation is not a roadmap goal.
- Hosted SaaS/beta auth, quotas, R2/Supabase/Netlify deployment assumptions, and auto-apply workflows are outside the current product boundary.
- Literal in-memory ranked buffers are unnecessary for current scope; SQLite queries remain the durable source of truth.
