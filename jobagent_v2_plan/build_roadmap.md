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

Goal:

```text
Generate a valid CV packet without reframing.
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

## Phase 6: Reframing and truth checking

Goal:

```text
Improve selected CV blocks without hallucination.
```

Build:

```text
selected-block reframing
one attempt per block
max 2–3 reframed blocks
truth checker
style checker
rescore original vs reframed
accept/reject gate
rewrite summary in manifest
```

Acceptance gate:

```text
truth_check_passes
AND no unsupported claims
AND no unsupported metric changes
AND no new technology invented
AND style_check_passes
AND reframed_score >= original_score
```

Acceptance test:

```text
Reframed blocks are only accepted when truth-safe and score-improving
Rejected reframes preserve original text
Manifest records accepted/rejected rewrites
```

---

## Phase 7: One-page fitting

Goal:

```text
Make the CV one page without making it ugly.
```

Build fitting tiers:

```text
Tier 0: normal template
Tier 1: tighter spacing
Tier 2: slightly smaller font
Tier 3: remove lowest-scoring optional bullet
Tier 4: remove lowest-scoring optional block
Tier 5: remove second-lowest optional block
Tier 6: manual review fail state
```

Hard limits:

```text
minimum font size: 9.5pt
minimum margin: 0.4in
max block removals: 2
never remove education
never remove contact/header
never remove role-critical required skills
```

Acceptance test:

```text
PDF page count is measured after each render
System stops once one page is achieved
System fails to manual_review if one page cannot be achieved cleanly
```

---

## Phase 8: Polish and reliability

Goal:

```text
Make it pleasant to use daily.
```

Build:

```text
retry buttons
archive/mark applied
Open JD
Open PDF
filter by status
sort by score
manual notes
export CSV, optional
```

Acceptance test:

```text
Daily usage flow works:
capture many jobs
review ranked table
generate packets for top jobs
mark applied/archive
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
