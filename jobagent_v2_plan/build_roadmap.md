# JobAgent V2 Build Roadmap

## 0. Build philosophy

Do not start with the clever CV tailoring logic.

Start with the boring machine:

```text
capture job → store job → queue job → update status → show dashboard
```

Once the skeleton is reliable, add intelligence stage by stage.

The goal is an easy build, not a perfect first version.

Before implementing each phase, inspect the V1 reference map for related
components. Use V1 to recover lessons, tests, invariants, and edge cases. Do not
treat the map as permission to copy code.

## Canonical-content product boundary

The core product tailors through CV-family selection, canonical block scoring and
ordering, Projects-versus-Experience section ordering, approved skill selection,
optional block exclusion for fitting, deterministic rendering, and manual review.
All rendered wording is pre-approved canonical content. Free-form bullet rewriting,
LLM reframing, paraphrasing, terminology substitution, semantic refinement, generated
summaries/headlines, rewrite scoring loops, and truth-checking generated rewrites are
rejected ideas: they are not deferred phases and are not planned runtime features.

---

## Phase 0: Planning docs

Create and review:

```text
architecture.md
data_model.md
pipeline.md
status_model.md
build_roadmap.md
```

Decisions to settle:

```text
CV families
truth bank format
scoring dimensions
promotion thresholds
dashboard columns
manual actions
```

---

## Phase 1: Queue skeleton

Status: implemented for review in
`docs/build_reports/phase_1_queue_skeleton.md`.

Goal:

```text
End-to-end system skeleton with no LLM dependency.
```

Build:

```text
Chrome extension Add to Queue button
backend receive endpoint
jobs table
dashboard table
dummy Queue 1 worker
dummy Queue 2 worker
status transitions
event logging
```

Acceptance test:

```text
Click Add to Queue
Job appears in dashboard
Job moves through dummy statuses
No real scoring or packet generation yet
```

---

## Phase 2: Real intake

Status: implemented for review in
`docs/build_reports/phase_2_real_intake.md`.

Goal:

```text
Turn captured page content into a clean JD record.
```

Build:

```text
URL normalization
dedupe
JD extraction
JD quality score
company/title/location extraction
intake failure handling
manual review state for bad extraction
```

Acceptance test:

```text
Add jobs from several sites
System extracts JD text
Duplicate jobs do not create duplicate records
Bad pages fail visibly
```

---

## Phase 3: Real Queue 1 scoring

Status: implemented for human evaluation review in
`docs/build_reports/phase_3_real_scoring.md`.

Goal:

```text
Rank jobs before generating packets.
```

Build:

```text
JD structuring
CV family selection
truth bank loading
block scoring
overall job compatibility score
recommendation
reason generation
dashboard ranking
```

Acceptance test:

```text
Queue 10 jobs
System scores and ranks them
Dashboard shows Company, Title, Score, Rec, Role, Reason
No packets generated yet unless manually requested
```

---

## Phase 3B: Hybrid scoring

Status: implemented for human semantic-quality review in
`docs/build_reports/phase_3b_hybrid_scoring.md`.

Goal:

```text
Use validated semantic evidence while keeping final scoring deterministic.
```

## Phase 4: Promotion scheduler

Status: implemented pending manual queue-policy review in
`docs/build_reports/phase_4_promotion_scheduler.md`.

Goal:

```text
Move only good jobs into Queue 2.
```

Build:

```text
auto-promote threshold
manual Generate now button
packet budget
Q2 queue status
manual priority/star support
```

Initial policy:

```text
score >= 82        → auto-promote
70 <= score < 82   → manual generate available
score < 70         → skip packet
starred job        → force packet
```

Acceptance test:

```text
High-score jobs enter Q2
Low-score jobs do not
Manual Generate now bypasses threshold
Auto-packet budget is respected
```

---

## Phase 5: Basic packet generation

Status: manually validated successfully; ready for continuing roadmap review in
`docs/build_reports/phase_5_basic_packet_generation.md`.

Goal:

```text
Generate a valid packet from canonical CV content without generated prose.
```

Build:

```text
load selected CV family
select blocks using block scores
choose section order
select skills from allowed skill bank
render PDF
save packet files
save manifest
dashboard PDF link
```

Acceptance test:

```text
A high-score job produces a PDF
PDF uses selected blocks
PDF path appears in dashboard
Manifest explains selected blocks and section order
```

---

## Phase 6: Real CV Families and Canonical Truth Banks

Goal:

```text
Replace placeholder content with validated, role-specific canonical CV families.
```

Build:

```text
ingestion or registration of real role-specific CVs
canonical block IDs
validated experience/project/education/skills data
family metadata, versioning, and source provenance
CV-family preview and validation
replacement of placeholder truth-bank content
configurable families, including digital_ic_rtl, cpu_gpu_architecture,
soc_verification, fpga, embedded_firmware, and software
```

Acceptance test:

```text
Registered family previews contain only approved canonical content and version data.
```

---

## Phase 7: Deterministic One-Page Fitting

Goal:

```text
Fit a canonical selected CV to one page without changing its wording.
```

Build fitting tiers:

```text
Tier 0: normal template
Tier 1: tighter spacing
Tier 2: slightly smaller font
Tier 3: remove lowest-scoring optional block
Tier 4: visible manual-review failure
```

Hard limits:

```text
minimum font size: 9.5pt
minimum margin: 0.4in
max block removals: 2
never remove education
never remove contact/header
never remove role-critical required skills
never rewrite or compress a bullet
```

Acceptance test:

```text
Render, measure page count, apply only bounded layout changes, rerender, then remove
the lowest-scoring optional block if necessary. Fail visibly if no safe fit is possible.
```

---

## Phase 8: Workflow and Review Polish

Goal:

```text
Complete the local review and application-ready workflow.
```

Build:

```text
retry buttons
archive/mark applied
PDF preview/open action
manifest explanation
regenerate action
family and section-order visibility
failure recovery and queue reliability
```

Acceptance test:

```text
Capture, review ranked jobs, generate a canonical packet, inspect the PDF/manifest,
recover a failure, and mark the application workflow state. No auto-apply.
```

---

## Recommended first implementation cut

The first useful local version should include only:

```text
Chrome extension Add to Queue
backend job table
dashboard
JD extraction
CV family selection
job score
reason
manual Generate now placeholder
```

Do not implement rewriting first.

Rewriting should come after the system can reliably capture, score, rank, and generate basic packets.
