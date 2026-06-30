# Project History

This file records verified completed milestones and major architectural decisions. Historical phase reports remain in `docs/build_reports/`; this file summarizes the active evidence needed for handoff.

## Completed milestones

### State Reconstruction and Terminology Normalization
Completion date: 2026-06-29.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Created the durable project-management workflow: `project/current.md`, `project/roadmap.md`, `project/history.md`, and `AGENTS.md`.
- Reconstructed the actual repository state from planning docs, build reports, source, tests, fixtures, frontend, extension, configuration, and git history.
- Updated README and active API/server/source labels to reflect the verified Phase 5 implementation instead of stale Phase 1/2 or dummy-only status.
- Added current `Queue1Worker` and `Queue2Worker` class names while preserving `DummyQ1Worker` and `DummyQ2Worker` compatibility aliases for older tests and local scripts.

Validation evidence:
- `python3 -m pytest backend/tests/unit/test_dummy_workers.py backend/tests/integration/test_phase1_flow.py backend/tests/integration/test_phase5_packet_generation.py -q`: 13 passed.
- `python3 scripts/check.py`: 73 backend tests passed; frontend build/dashboard checks passed; extension validation/popup checks passed.
- `git diff --check`: passed.

Important limitations:
- The next active milestone remains unimplemented.
- The committed truth banks are still generic starter content and are not suitable as real personal CV data.
- Historical file names such as `docs/phase_1_api.md` remain for compatibility.

### Phase 6A Canonical Truth-Bank Registration and Validation
Completion date: 2026-06-29.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Added `backend/src/jobagent_v2/truth_banks.py` with a versioned truth-bank schema, validation rules, registered/starter content classes, placeholder rejection, JSON loading, and deterministic previews.
- Wired `backend/src/jobagent_v2/scoring.py` to use the Phase 6A validator for existing truth-bank loads while explicitly allowing bundled starter fixtures for deterministic development and tests.
- Marked bundled truth banks in `backend/src/jobagent_v2/data/truth_banks/` as `content_class: starter_fixture` and `schema_version: phase6a-truth-bank-v1`.
- Updated `.gitignore` and `pyproject.toml` so backend family/truth-bank JSON and LaTeX templates are durable package data instead of ignored local artifacts.
- Added `backend/tests/unit/test_truth_banks.py` covering valid registered fixtures, critical rejection paths, starter-fixture rejection, preview behavior, and scoring-loader compatibility.
- Added `docs/truth_bank_registration.md` and linked it from `README.md`.

Validation evidence:
- `python3 -m pytest backend/tests/unit/test_truth_banks.py backend/tests/unit/test_scoring.py backend/tests/unit/test_phase5_packets.py -q`: 22 passed.
- `python3 -m pytest backend/tests/unit/test_truth_banks.py backend/tests/unit/test_scoring.py backend/tests/integration/test_phase5_packet_generation.py -q`: 23 passed after package-data ignore fixes.
- `python3 scripts/check.py`: 89 backend tests passed; frontend build/dashboard checks passed; extension validation/popup checks passed.
- `git diff --check`: passed.
- `git status --short`: inspected.

Important limitations:
- No real personal CV/truth-bank content was added.
- Bundled truth banks remain starter fixtures for tests and development only.
- Phase 6B requires user-approved canonical source material before production packet content can be registered.

### Canonical Master-CV Registration and Validation
Completion date: 2026-06-29.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Added `backend/src/jobagent_v2/master_cvs.py` to discover and validate fixed approved master CV artifacts.
- Registered exactly four canonical families: `digital_ic`, `verification`, `software`, and `ml`.
- Updated `backend/src/jobagent_v2/data/cv_families.json` with approved master-CV metadata, immutable-section policy, and dynamic-skills-disabled flags.
- Added starter scoring support truth banks for `digital_ic`, `verification`, and `ml` while preventing starter truth-bank material from rendering packets for master-registered families.
- Updated packet generation to copy approved master `.tex` and `.pdf` artifacts unchanged for registered master families and record master metadata in packet artifacts/manifests.
- Added `backend/tests/unit/test_master_cvs.py` and updated scoring, contract, and packet integration tests for the four-family design.
- Added `docs/master_cv_registration.md` and linked it from `README.md`.

Validation evidence:
- `python3 -m pytest backend/tests/unit/test_master_cvs.py backend/tests/unit/test_scoring.py backend/tests/integration/test_phase3_scoring_flow.py backend/tests/integration/test_phase5_packet_generation.py -q`: 16 passed, 1 skipped.
- `python3 scripts/check.py`: 96 backend tests passed, 1 local TeX compile test skipped; frontend build/dashboard checks passed; extension validation/popup checks passed.
- `git diff --check`: passed.

Important limitations:
- The local TeX distribution has `pdflatex` but is missing at least one package required to recompile the approved masters, so the compile-validation test skips in this environment. Approved committed PDFs are still directly validated as readable one-page PDFs.
- Byte-level comparison between freshly compiled PDFs and approved PDFs is intentionally not required because LaTeX/PDF output can vary by environment.
- Full deterministic plus semantic family classification is not implemented in this milestone.
- Bounded project substitution and project ordering are not implemented.

### Phase B Auditable Four-Family Job Classification
Completion date: 2026-06-29.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Added `backend/src/jobagent_v2/family_classifier.py` and versioned deterministic configuration at `backend/src/jobagent_v2/data/family_classifier.json`.
- Classified every scoreable job across exactly `digital_ic`, `verification`, `software`, and `ml`.
- Returned normalized scores, selected family, secondary family, confidence, decision category, review flag, deterministic rule evidence, optional semantic evidence, classifier version, and config version.
- Preserved offline behavior: semantic family classification is optional, fakeable in tests, and falls back safely when unavailable or malformed.
- Integrated the selected family into existing scoring and packet generation without changing approved master CV content.
- Persisted classification audit data separately from candidate-fit score data through additive SQLite columns and `job_family_classifications`.
- Added `docs/family_classification.md`, including the distinction between roadmap Phase B and the existing `phase6b-master-cv-v1` master-CV schema name.

Validation evidence:
- `python3 -m pytest backend/tests/unit/test_family_classifier.py backend/tests/unit/test_scoring.py backend/tests/integration/test_phase3_scoring_flow.py backend/tests/integration/test_phase5_packet_generation.py -q`: 41 passed.
- `python3 scripts/check.py`: 128 backend tests passed, 1 local TeX compile test skipped; frontend build/dashboard checks passed; extension validation/popup checks passed.
- `git diff --check`: passed.
- `git status --short`: inspected.

Important limitations:
- Deterministic classifier weights are heuristic and need real-job review over time.
- Live semantic family-classification quality was not credential-tested.
- Hybrid/close/low-confidence decisions are persisted and auditable, but no project substitution or ordering is implemented.
- Candidate-fit scoring still uses starter truth-bank fixtures for block scoring support; packet rendering for registered families continues to copy approved masters unchanged.

### Phase C Bounded Project-Block Tailoring Registry and Policy
Completion date: 2026-06-29.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Added `backend/src/jobagent_v2/data/project_block_registry.json` with 12 approved whole-project block variants extracted from the four canonical master CVs.
- Registered stable block IDs, underlying project IDs, family-specific variants, family eligibility, approval/immutability flags, tags, render budgets, evidence refs, and content hashes.
- Added `backend/src/jobagent_v2/project_blocks.py` to parse project blocks from master `.tex` sources and validate exact registry agreement.
- Enforced duplicate-ID rejection, duplicate-content rejection, unknown-family rejection, missing-bullet rejection, unapproved-block rejection, forbidden section rejection, unsupported placeholder rejection, base-order validation, explicit replacement compatibility, and conservative render-budget validation.
- Defined and validated future tailoring decision records with base family, base blocks, removed/inserted block IDs, final order, evidence, review flag, and policy version.
- Added `docs/project_block_registry.md` and linked it from `README.md`.

Registered approved block inventory:
- Digital IC: `tinynpu_digital_ic_v1`, `sparrow_v_digital_ic_v1`, `sparrow_cluster_digital_ic_v1`.
- Verification: `axi4_stream_packet_router_verification_v1`, `agentic_rtl_security_verification_v1`, `sparrow_v_verification_v1`.
- Software: `jobagent_software_v1`, `agentic_rtl_security_discovery_software_v1`, `sparrowml_software_v1`.
- ML: `dementia_speech_classification_ml_v1`, `sparrowml_ml_v1`, `speakup_ml_v1`.

Validation evidence:
- `python3 -m pytest backend/tests/unit/test_project_blocks.py backend/tests/unit/test_master_cvs.py backend/tests/unit/test_family_classifier.py backend/tests/integration/test_phase5_packet_generation.py -q`: 60 passed, 2 skipped.
- `python3 scripts/check.py`: 148 backend tests passed, 2 local TeX compile tests skipped; frontend build/dashboard checks passed; extension validation/popup checks passed.
- `git diff --check`: passed.
- `git status --short`: inspected.

Important limitations:
- Production packet generation still copies approved master `.tex` and `.pdf` files unchanged; it does not yet perform project substitution or reordering.
- Render-size validation uses a deterministic conservative rendered-line estimate, not real PDF box measurement.
- Environment-dependent TeX compile checks skip when the local LaTeX toolchain is incomplete.
- No free-form CV generation, bullet rewriting, dynamic skills, or master-CV modifications were introduced.

### Phase D One-Block Tailoring Selection and Packet Integration
Completion date: 2026-06-30.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Added `backend/src/jobagent_v2/data/tailoring_policy.json` with versioned replacement-gain, clear-match, dominant-family, reordering, one-page, duplicate-project, and scoring-weight policy.
- Added `backend/src/jobagent_v2/tailoring.py` to score approved compatible project blocks, choose at most one substitution, optionally reorder final whole blocks, replace only the Projects section, validate immutable TeX regions, compile tailored candidates, verify one-page PDF output, and fall back to the approved master.
- Integrated bounded tailoring into Queue 2 packet generation for registered approved master CV families.
- Preserved the selected master family as the base; no tailoring path switches the whole CV family.
- Persisted complete audit records in SQLite `job_tailoring_decisions` and wrote packet-level `tailoring_decision.json` artifacts.
- Extended packet selected-CV and manifest artifacts with master metadata, final project block IDs, tailoring status, review flag, fallback reason, policy version, registry version, and classifier version.
- Kept approved master files in `master-cvs/` unchanged; tailored artifacts are written only to generated packet directories.
- Added `docs/bounded_tailoring.md` and linked it from `README.md`.

Validation evidence:
- `python3 -m pytest backend/tests/unit/test_tailoring.py backend/tests/integration/test_phase5_packet_generation.py -q`: 12 passed.
- `python3 -m pytest backend/tests/unit/test_tailoring.py backend/tests/unit/test_project_blocks.py backend/tests/unit/test_master_cvs.py backend/tests/unit/test_family_classifier.py backend/tests/unit/test_scoring.py backend/tests/integration/test_phase3_scoring_flow.py backend/tests/integration/test_phase5_packet_generation.py -q`: 74 passed, 2 skipped.
- `python3 scripts/check.py`: 154 backend tests passed, 2 local TeX compile tests skipped; frontend build/dashboard checks passed; extension validation/popup checks passed.
- `git diff --check`: passed.
- `git status --short`: inspected.

Important limitations:
- Tailoring and classifier thresholds remain heuristic and need labelled real-job calibration.
- Close and cross-family hybrid decisions are auditable and review-flagged, but no dedicated review UI/API exists yet.
- Tailored PDF validation depends on local LaTeX availability; unavailable or failed compilation falls back to the approved master.
- Scoring is deterministic and offline; semantic project-block scoring is not implemented and no semantic rationale is fabricated.

### Phase E Classifier and Tailoring Threshold Calibration
Completion date: 2026-06-30.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Added `backend/src/jobagent_v2/calibration.py` with offline labelled dataset loading, schema validation, deterministic family-classifier evaluation, structural tailoring evaluation, confusion matrices, classification metrics, decision/review metrics, tailoring safety metrics, bounded threshold search, acceptance gates, and report generation.
- Added `backend/src/jobagent_v2/data/evaluation/labelled_jobs.json` with 90 concise synthetic/paraphrased labelled role-pattern examples: 15 Digital IC, 15 Verification, 15 Software, 15 ML, 20 hybrid/ambiguous, and 10 out-of-scope.
- Preserved a 70-example train split and 20-example holdout split.
- Added deterministic semantic modes: deterministic baseline, fake semantic provider for tests, and optional live semantic mode that falls back offline when credentials are unavailable.
- Generated machine-readable and human-readable reports at `reports/calibration/phase_e_calibration_report.json` and `reports/calibration/phase_e_calibration_report.md`.
- Added `backend/tests/unit/test_calibration.py` covering dataset validation, duplicate IDs, unknown labels, invalid block IDs, deterministic split, repeatable evaluation, metric math, parameter-search determinism, promotion gates, report generation, fake semantic behavior, live semantic fallback, and no production-database writes.
- Added `docs/calibration.md` and linked it from `README.md`.

Baseline deterministic holdout metrics:
- Macro F1: 0.8485.
- Primary-family acceptable accuracy: 1.0.
- Wrong high-confidence no-review rate: 0.05.
- Out-of-scope review rate: 0.6667.
- Unnecessary automatic substitution rate: 0.0.
- Invalid substitution rate: 0.0.

Promotion decision:
- No production classifier or tailoring-policy config was promoted.
- Candidate search did not pass safety gates because wrong high-confidence no-review and out-of-scope review-rate gates failed.

Validation evidence:
- `python3 -m pytest backend/tests/unit/test_calibration.py backend/tests/unit/test_family_classifier.py backend/tests/unit/test_tailoring.py -q`: 40 passed.
- `PYTHONPATH=backend/src python3 -m jobagent_v2.calibration evaluate`: regenerated JSON/Markdown reports with `promote: false`.
- `python3 scripts/check.py`: 162 backend tests passed, 2 local TeX compile tests skipped; frontend build/dashboard checks passed; extension validation/popup checks passed.
- `git diff --check`: passed.
- `git status --short`: inspected.

Important limitations:
- The labelled dataset is synthetic/paraphrased and should be expanded with reviewed real-job examples over time.
- Bulk tailoring evaluation is structural and does not compile every candidate PDF.
- Live semantic evaluation was not run; default validation remains deterministic/offline.
- The failed safety gates indicate review workflow support is needed before release hardening.

### Phase F Review API for Classification and Tailoring Decisions
Completion date: 2026-06-30.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Added owner-scoped review persistence with additive `jobs.owner_id`, `review_items`, and append-only `review_resolutions`.
- Automated classification and tailoring saves now create pending review items for low-confidence, close, hybrid, review-required, fallback, and rejected decisions.
- Original `job_family_classifications` and `job_tailoring_decisions` audit records remain unchanged by review resolutions.
- Added local review service/API support for listing, filtering, retrieving, resolving, and exporting review feedback.
- Added validated review actions for approving classifications, overriding family, marking out of scope, approving/rejecting tailoring, choosing master unchanged, approving order, deferring, and selecting an approved compatible replacement block.
- Enforced family IDs, approved block IDs, compatibility rules, one-substitution constraints, duplicate prevention, reviewer identity, notes, owner-scoped review access, and owner-scoped packet artifact serving.
- Recorded packet-changing resolutions with `regeneration_status: queued` without overwriting existing packet artifacts.
- Added `docs/review_api.md` and linked it from `README.md`.
- Added `backend/tests/unit/test_review_api.py` covering review creation, duplicate suppression, clear no-review behavior, manual clear-match review creation, ownership, family override, invalid family rejection, compatible/incompatible replacement validation, feedback export, and API docs.

Validation evidence:
- `python3 -m py_compile backend/src/jobagent_v2/storage.py backend/src/jobagent_v2/service.py backend/src/jobagent_v2/api.py backend/src/jobagent_v2/schemas.py`: passed.
- `PYTHONPATH=backend/src pytest backend/tests/unit/test_review_api.py -q`: 10 passed.
- `PYTHONPATH=backend/src pytest backend/tests/integration/test_phase3_scoring_flow.py backend/tests/integration/test_phase5_packet_generation.py backend/tests/contract/test_api_contract.py -q`: 17 passed.
- `PYTHONPATH=backend/src pytest backend/tests/integration/test_phase2_intake_flow.py -q`: 9 passed.
- `python3 scripts/check.py`: 172 backend tests passed, 2 local TeX compile tests skipped; frontend build/dashboard checks passed; extension validation/popup checks passed.
- `git diff --check`: passed.
- `git status --short`: inspected.

Important limitations:
- Review-driven packet regeneration is recorded as queued status but no worker consumes those review resolutions yet.
- The dashboard does not yet expose a usable review workflow.
- Owner scoping is local-header based, consistent with the current local-only product boundary, not a hosted authentication system.
- Review feedback export is for later calibration only; it does not retrain or mutate production configuration.

### Phase G Minimal Review UI Integration
Completion date: 2026-06-30.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Added a minimal dashboard Review queue section with status, type, and family filters.
- Added review-detail rendering for classification scores, selected and secondary family labels, deterministic evidence, semantic-unavailable state, classifier/config versions, tailoring proposal details, immutable-content notice, allowed actions, and resolution history.
- Added owner-scoped frontend API helpers for review listing, detail retrieval, resolution, and manual review creation.
- Added manual `Review family selection` action for scored jobs, including clear-match decisions.
- Added client-side validation that only registered families and backend-provided approved replacement tuples can be submitted.
- Added queued-regeneration messaging that explicitly says automatic regeneration has not yet processed the packet.
- Added backend review metadata for human-readable family labels, registered project block previews, base project order, and approved compatible replacement options.
- Updated `docs/review_api.md` with dashboard workflow behavior.
- Extended `frontend/scripts/test-dashboard.mjs` and `backend/tests/unit/test_review_api.py`.

Validation evidence:
- `node frontend/scripts/test-dashboard.mjs`: passed.
- `PYTHONPATH=backend/src pytest backend/tests/unit/test_review_api.py -q`: 11 passed.
- `python3 scripts/check.py`: 173 backend tests passed, 2 local TeX compile tests skipped; frontend build/dashboard checks passed; extension validation/popup checks passed.
- `git diff --check`: passed.
- `git status --short`: inspected.

Important limitations:
- Packet-changing review resolutions still remain queued until a regeneration worker is implemented.
- The UI is intentionally minimal and not a broad dashboard redesign.
- Owner scoping remains local-header based, not hosted authentication.

### Phase 0B Repository Bootstrap
Completion date: reconstructed from commit history; exact date not recorded in this audit.

Relevant commit:
- `4cb0ec6 Bootstrap JobAgent V2 repository`

Main functionality delivered:
- Independent `job-agent-v2` skeleton with Python backend package layout, tests, frontend placeholder, extension skeleton, `scripts/check.py`, `.gitignore`, and V2 planning references.

Validation evidence:
- Historical report: `docs/build_reports/phase_0b_repository_bootstrap.md`.

Important limitations:
- No real queue, intake, scoring, or packet functionality existed at this point.

### Phase 1 Persistent Queue Skeleton
Completion date: reconstructed from commit history; exact date not recorded in this audit.

Relevant commit:
- `a868536 Implement Phase 1 persistent queue skeleton`

Main functionality delivered:
- Local API, SQLite job/event persistence, dashboard table, Chrome extension capture, status transitions, Generate now, retry/archive actions, and deterministic placeholder workers.

Validation evidence:
- Historical report: `docs/build_reports/phase_1_queue_skeleton.md`.
- Current tests: `backend/tests/integration/test_phase1_flow.py`.

Important limitations:
- Original dummy behavior was later superseded by real intake, scoring, promotion, and packet generation.

### Phase 2 Real Intake
Completion date: reconstructed from commit history; exact date not recorded in this audit.

Relevant commit:
- `70c654b Implement and harden Phase 2 job intake`

Main functionality delivered:
- Deterministic URL normalization, JD extraction, quality diagnostics, company/title/location extraction, duplicate warnings, failure/manual-review state handling, and retry support.

Validation evidence:
- Historical reports: `docs/build_reports/phase_2_real_intake.md` and `docs/build_reports/phase_2b_intake_hardening.md`.
- Current tests: `backend/tests/unit/test_intake_parser.py`, `test_intake_hardening.py`, `test_url_normalization_phase2.py`, and `backend/tests/integration/test_phase2_intake_flow.py`.

Important limitations:
- Heuristic extraction remains brittle across changing job-site DOMs.

### Phase 3 Deterministic And Hybrid Scoring
Completion date: reconstructed from commit history; exact date not recorded in this audit.

Relevant commits:
- `f6f5bbf Implement Phase 3 hybrid scoring with live LLM transport`

Main functionality delivered:
- Deterministic JD structuring, CV-family selection, truth-bank loading, block scoring, overall recommendation, persisted scoring diagnostics, optional validated semantic evidence, and opt-in OpenAI transport with offline fallback.

Validation evidence:
- Historical reports: `docs/build_reports/phase_3_real_scoring.md`, `docs/build_reports/phase_3b_hybrid_scoring.md`, and `docs/build_reports/phase_3c_live_llm_transport.md`.
- Current tests: `backend/tests/unit/test_scoring.py`, `test_hybrid_scoring.py`, `test_openai_transport.py`, and scoring integration tests.

Important limitations:
- Several historical reports were marked blocked for human review, but later commits continued implementation. During the 2026-06-29 audit, offline validation passed; live semantic quality remains unverified.

### Phase 4 Promotion Scheduler
Completion date: reconstructed from commit history; exact date not recorded in this audit.

Relevant commit:
- `f925bd1 Implement Phase 4 durable promotion scheduler`

Main functionality delivered:
- Persistent Q2 queue, threshold/manual/star promotion policy, capacity and budget controls, leasing, stale task recovery, queue APIs, and dashboard exposure.

Validation evidence:
- Historical report: `docs/build_reports/phase_4_promotion_scheduler.md`.
- Current tests: `backend/tests/integration/test_phase4_promotion_flow.py`.

Important limitations:
- The report said manual policy review was pending, but current code and tests validate core policy mechanics.

### Phase 5 Basic Packet Generation
Completion date: reconstructed from commit history; exact date not recorded in this audit.

Relevant commit:
- `af25d12 Implement Phase 5 deterministic packet generation`

Main functionality delivered:
- Deterministic selected-CV construction from canonical truth-bank blocks, LaTeX rendering, PDF compilation, selected CV and manifest artifacts, persistent packet attempts, packet API endpoints, and dashboard links.

Validation evidence:
- Historical report: `docs/build_reports/phase_5_basic_packet_generation.md`.
- Current tests: `backend/tests/unit/test_phase5_packets.py` and `backend/tests/integration/test_phase5_packet_generation.py`.
- `python3 scripts/check.py` passed on 2026-06-29 with 73 backend tests plus frontend and extension checks.

Important limitations:
- Starter truth banks are placeholders. Output is structurally valid but not production-useful until replaced with approved personal canonical content.
- One-page fitting is not implemented.

### Phase H Review-Driven Packet Regeneration Worker
Completion date: 2026-06-30.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Added durable `review_regeneration_jobs` persistence with queued,
  processing, complete, and failed states, lease owner/expiry, attempt count,
  timestamps, failure code/reason, source packet, generated packet, and stable
  idempotency key.
- Added reviewed packet metadata on `packets`, linking each reviewed artifact to
  the source packet, review item, review resolution, idempotency key, and
  generation reason.
- Implemented `jobagent_v2.regeneration_worker` with atomic SQLite claiming,
  stale lease recovery, max-attempt retry policy, idempotent success reuse, and
  safe failure recording.
- Regenerated reviewed family-master outcomes by copying the approved canonical
  master `.tex` and `.pdf` into a new packet artifact directory.
- Regenerated reviewed one-block tailoring outcomes by replacing only the
  Projects section from registered approved blocks, validating immutable
  sections and one-page PDF output, then promoting artifacts only after checks
  pass.
- Preserved prior ready packets and original classification/tailoring/review
  audit records.
- Added a local API worker endpoint at
  `POST /api/workers/regeneration/run-once` and the CLI command
  `PYTHONPATH=backend/src python3 -m jobagent_v2.regeneration_worker --once`.
- Updated review API/dashboard status reporting so queued, processing,
  complete, and failed regeneration states are visible with prior/reviewed
  packet links where available.

Validation evidence:
- `PYTHONPATH=backend/src pytest backend/tests/unit/test_regeneration_worker.py -q`: 4 passed.
- `PYTHONPATH=backend/src pytest backend/tests/unit/test_review_api.py backend/tests/integration/test_phase5_packet_generation.py -q`: 18 passed.
- `node frontend/scripts/test-dashboard.mjs`: passed.
- `python3 scripts/check.py`: 177 backend tests passed, 2 local TeX compile tests skipped, plus frontend and extension checks.
- `git diff --check`: passed.
- `git status --short`: inspected.

Important limitations:
- Retry is intentionally narrow: only worker interruption and temporary artifact
  write failures are retryable by default.
- The worker remains a local command/API action; continuous scheduling and
  monitoring are left to the next operational milestone.
- Real TeX compilation quality is still environment-dependent, with failures
  reported honestly instead of falling back to an unreviewed packet.

### Operational Worker Scheduling and Monitoring
Completion date: 2026-06-30.

Relevant commit:
- Not committed at the time of this audit.

Main functionality delivered:
- Added `jobagent_v2.worker_runner` with independent continuous loops for
  `q1`, `q2`, and `regeneration`, plus combined `--all` mode.
- Kept worker loops as wrappers around existing run-once worker logic; Q1, Q2,
  and regeneration business behavior was not reimplemented.
- Added environment-backed polling intervals, deterministic idle backoff,
  heartbeat settings, and graceful SIGINT/SIGTERM stop handling.
- Added durable `worker_instances` and `worker_events` tables for current
  worker state, bounded operational history, processed/failure counts,
  heartbeat timestamps, current job, last success/failure, polling interval,
  and runner version.
- Added queue summaries derived from existing `jobs`, `q2_tasks`, and
  `review_regeneration_jobs`, including queued/processing/failed counts,
  retryable counts, oldest queued item, stale processing counts, and
  max-attempt-exhausted counts where applicable.
- Added worker health and queue health API responses for healthy, idle,
  degraded, and offline states.
- Added compact dashboard worker monitoring with Q1, Q2, and regeneration
  status, queue counts, stale/failure warnings, current job, and last
  success/failure.
- Added safe JSON operational logs for worker start/stop, idle/backoff,
  job start, completion, and failure without CV content, full JDs, review
  notes, secrets, stack traces, or raw artifact paths.
- Documented startup commands, polling configuration, lifecycle, health rules,
  queue metrics, structured logs, manual controls, stale recovery, and
  troubleshooting in `docs/worker_operations.md`.

Validation evidence:
- `PYTHONPATH=backend/src pytest backend/tests/unit/test_worker_runner.py backend/tests/contract/test_api_contract.py -q`: 14 passed.
- `node frontend/scripts/test-dashboard.mjs`: passed.
- `python3 scripts/check.py`: 184 backend tests passed, 2 local TeX compile tests skipped, plus frontend and extension checks.
- `git diff --check`: passed.
- `git status --short`: inspected.

Important limitations:
- The `--all` runner is a simple local loop, not a supervised process manager.
- HTTP endpoints expose status and manual run-once controls but do not spawn
  arbitrary worker processes.
- Packaging and one-command startup remain future release-hardening work.

## Major architectural decisions

### Canonical CV Tailoring
Decision date: recorded in ADR, exact date not audited.

Evidence:
- `docs/architecture_decisions/ADR-001-canonical-cv-tailoring.md`.

Decision:
- Tailoring is performed through CV-family selection, canonical block selection, section ordering, approved skill selection, deterministic rendering, bounded one-page fitting, and manual review.
- Generated prose rewriting, paraphrasing, semantic refinement, generated summaries/headlines, rewrite scoring loops, and truth-checking generated rewrites are rejected for the core runtime product.

### Local-first durable storage
Decision date: reconstructed from Phase 1.

Evidence:
- `backend/src/jobagent_v2/storage.py`.
- `jobagent_v2_plan/architecture.md` and `data_model.md`.

Decision:
- SQLite is the durable source of truth for jobs, events, scoring diagnostics, Q2 tasks, and packet attempts.

### Offline deterministic validation by default
Decision date: reconstructed from current implementation.

Evidence:
- `scripts/check.py`.
- `backend/src/jobagent_v2/llm_client.py`.
- `.env.example`.

Decision:
- The standard check command must run without network access, credentials, or paid services.
- Live OpenAI semantic requests are explicit opt-in only.

## Audit notes from 2026-06-29

Verified facts:
- Git history at audit time: `68305a4 Simplify V2 to canonical CV tailoring` was HEAD.
- `git status --short` showed an existing modified `.gitignore`.
- `python3 scripts/check.py` passed before milestone implementation.

Discrepancies found:
- `README.md` claimed the repository was currently in Phase 2 and did not implement scoring, CV tailoring, PDF generation, or LLM calls.
- `docs/phase_1_api.md` was titled "Phase 3 API" while also documenting Phase 5 endpoints.
- Several runtime/doc strings still referred to "Phase 1" or "dummy" workers despite real intake/scoring and packet generation.
- Historical build reports for Phase 3/3B/3C/4 were marked blocked/pending even though later commits implemented subsequent phases.
