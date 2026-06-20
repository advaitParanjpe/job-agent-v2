# JobAgent V2 Architecture

## 0. Product boundary

JobAgent V2 is a local-only job application queue and packet-generation system.

The goal is:

```text
Click jobs quickly → score them cheaply → rank them → generate packets only for the best jobs → review everything in one dashboard
```

JobAgent V2 is not intended to be:

```text
a deployed SaaS product
a multi-user beta app
a scraper-first system
an auto-apply bot
a full ATS/CRM
an email-alert automation system
```

The system should optimize for personal throughput, local reliability, easy debugging, and truthful CV generation.

---

## 1. High-level system

```text
Chrome Extension
  ↓
Backend API
  ↓
Persistent Job Database
  ↓
Queue 1: Intake + Scoring
  ↓
Scored Candidate Backlog
  ↓
Promotion Scheduler
  ↓
Queue 2: Packet Generation
  ↓
Packet Store
  ↓
Dashboard
```

The key separation is:

```text
Queue 1 = cheap triage
Queue 2 = expensive packet generation
```

Queue 1 answers:

```text
Should I care about this job?
```

Queue 2 answers:

```text
Create the application packet for this job.
```

---

## 2. Chrome Extension

The Chrome extension should be extremely simple.

### Main action

```text
Add to Queue
```

### Payload sent to backend

The extension should not only send the URL. It should send enough page context for the backend to extract the JD reliably.

```text
source_url
page_title
visible_page_text
optional_html_snapshot
timestamp
source_site, if detectable
```

Reason: some job pages cannot be reliably fetched by the backend from URL alone, especially authenticated or dynamic pages such as LinkedIn, Workday, Lever, Greenhouse, and company portals.

### Extension responsibilities

```text
capture current page URL
capture visible page text
capture page title
send payload to backend
show simple result state
```

### Extension non-responsibilities

```text
no JD parsing
no scoring
no LLM calls
no CV generation
no heavy frontend logic
```

### Possible extension responses

```text
added_to_queue
already_queued
already_processed
duplicate_possible
extraction_failed
backend_unavailable
```

---

## 3. Backend Intake

The backend should create a durable raw job record before attempting expensive processing.

### Intake flow

```text
Receive extension payload
↓
Normalize/canonicalize URL
↓
Check dedupe
↓
Create raw job record
↓
Push job_id to Queue 1
```

The backend should not parse the JD before creating the raw job record. If parsing fails later, the dashboard should still show a visible failure state.

### Dedupe signals

```text
canonical_url
company + normalized title
JD text hash
source site job ID, if detectable
```

### Intake outcomes

```text
new_job_added
already_queued
already_scored
already_has_packet
duplicate_possible
failed_to_create_job
```

---

## 4. Queue 1: Intake and Scoring

Queue 1 is a persistent database-backed intake/scoring queue.

It processes raw jobs into scored candidates.

### Queue 1 responsibilities

```text
extract clean JD
structure JD
measure JD quality
select CV family
load relevant truth bank
score job against truth bank
score individual CV blocks
compute final compatibility score
save scored candidate metadata
```

### Queue 1 non-responsibilities

```text
no CV rewriting
no PDF generation
no one-page fitting
no final packet creation
```

---

## 5. Scored Candidate Backlog / RB

The "RB" idea is useful as a bounded scored-candidate window, but it should not be the only source of truth.

The database should remain the durable source of truth.

A practical implementation can treat the scored backlog as a database query rather than a literal in-memory ring buffer.

Example:

```sql
SELECT *
FROM jobs
WHERE intake_status = 'scored'
AND packet_status IN ('not_requested', 'queued')
ORDER BY manual_priority DESC, overall_score DESC, added_at ASC
LIMIT 64;
```

This gives the system the behavior of a bounded ranked buffer without risking data loss if the app crashes.

### If a literal RB is implemented

Initial size:

```text
8 slots
```

Growth rule:

```text
if RB is full and Q1 has more than 1 waiting item:
    double RB size
```

Maximum size:

```text
64 slots
```

However, even with an in-memory RB, every item must also be represented in the database.

---

## 6. CV Family Selection

The user will maintain 3/4 base CVs.

Suggested families:

```text
hardware / RTL / ASIC / FPGA
embedded / firmware / semiconductor applications
SWE / backend / data
architecture / GPU / accelerator / systems
```

For each job, Queue 1 should select:

```text
primary_cv_family
secondary_cv_family, optional
confidence
reason
```

Example output:

```json
{
  "primary_cv_family": "hardware_rtl",
  "secondary_cv_family": "gpu_architecture",
  "confidence": 0.86,
  "reason": "JD emphasizes RTL, SystemVerilog, verification, synthesis, and SoC integration."
}
```

---

## 7. Truth Bank Strategy

Do not extract the truth bank from the selected CV every time if avoidable.

Instead, maintain precomputed truth banks per CV family:

```text
truth_banks/
  hardware_truth_bank.json
  embedded_truth_bank.json
  swe_truth_bank.json
  architecture_truth_bank.json
```

Each truth bank should include:

```text
education
experience blocks
project blocks
skills groups
allowed metrics
allowed technologies
claim sources
forbidden claims
optional achievements
```

Education should mostly remain fixed.

---

## 8. Job and Block Scoring

Scoring is critical.

The system should score:

```text
the job as a whole
each CV block against the job
```

A "block" means one project, one work experience, one skills group, or another reusable CV unit.

### Block scoring dimensions

```text
technical_match
keyword_match
role_responsibility_match
evidence_strength
seniority_fit
recency
impressiveness
domain_match
risk_of_overclaim
```

Example aggregate block score:

```text
block_score =
  0.25 * technical_match
+ 0.20 * role_responsibility_match
+ 0.15 * keyword_match
+ 0.15 * evidence_strength
+ 0.10 * domain_match
+ 0.10 * impressiveness
+ 0.05 * recency
- 0.20 * risk_of_overclaim
```

These weights are starting defaults and should be easy to tune.

### Final job compatibility score

Do not average all block scores. That would punish the user for having irrelevant blocks in the truth bank.

Instead:

```text
final_score =
  0.25 * role_family_fit
+ 0.25 * must_have_coverage
+ 0.20 * top_3_block_average
+ 0.10 * skills_match
+ 0.10 * domain_match
+ 0.10 * evidence_strength
- gap_penalty
- overclaim_risk_penalty
- practical_constraint_penalty
```

### Scoring output

Queue 1 should produce:

```text
overall_score
recommendation
role_family
selected_cv_family
top_matching_blocks
critical_gaps
reason
JD quality score
```

---

## 9. Promotion Scheduler

The promotion scheduler decides which scored jobs enter Queue 2.

It should not promote everything automatically.

### Promotion policy

Initial policy:

```text
score >= 82        → auto-promote to Queue 2
70 <= score < 82   → scored only, manual generate available
score < 70         → no packet
starred job        → force packet
archived job       → never packet
```

### Polling and Q2 fill policy

The promotion scheduler should poll the scored-candidate backlog approximately once per minute.

On each poll:

```text
check available Q2 capacity
while Q2 has an empty slot:
    select the highest-scoring eligible candidate
    promote it into Q2
    repeat until Q2 is full or no eligible candidates remain
```

The intended behavior is to keep Q2 full whenever eligible scored candidates are available, so packet generation does not sit idle between jobs.

Promotion ordering should be:

```text
manual priority / starred first
overall score descending
added_at ascending as the tie-breaker
```

A manual `Generate now` action should bypass the one-minute wait and attempt immediate promotion, subject to Q2 capacity.

### Capacity, budget, and concurrency

Q2 queue capacity and Q2 worker concurrency are separate settings. Q2 may hold several waiting jobs while only one packet is generated at a time.

Initial limits:

```text
max_concurrent_q1_jobs = 2
q2_capacity = configurable, initially small
max_concurrent_q2_jobs = 1
max_auto_packets_per_day = 10
auto_promote_threshold = 82
manual_generate_ignores_threshold = true
```

When a Q2 job completes or fails, it frees a slot. The next scheduler poll should refill that slot with the highest-scoring eligible candidate.

---

## 10. Queue 2: Packet Generation

Queue 2 processes only selected jobs.

### Q2 input

```text
job_id
selected_cv_family
structured_jd
block_scores
generation_priority
manual_overrides, optional
```

### Q2 responsibilities

```text
build CV plan
select visible blocks
choose section order
select approved skills
render PDF
fit to one page
save final packet
save packet manifest
```

### Q2 non-responsibilities

```text
no raw page extraction
no initial JD parsing
no initial job scoring unless re-run requested
no generated prose
no bullet rewriting or semantic paraphrasing
```

### Canonical content policy

All rendered experience and project wording must come unchanged from the selected CV
family or validated truth bank. The system may include a block, exclude an optional
block, move a block or section, and select approved skills. It may not rewrite a
bullet, paraphrase a claim, add a claim, alter a metric, infer an unsupported
technology, or generate new CV prose. LaTeX escaping, whitespace, and bounded layout
changes are safe formatting operations.

---

## 11. Dashboard

The dashboard should be a clean local table.

### MVP columns

```text
Company
Title
Score
Rec
Role
Packet status
Reason
PDF
Actions
```

### Actions

```text
Generate now
Regenerate
Archive
Mark applied
Open JD
Open PDF
```

### Optional later columns

```text
Location
Source
Added date
Deadline
Manual priority
Notes
CV family
```

---

## 12. Manual Overrides

The system should assist, not fully decide.

Important manual controls:

```text
Star job
Generate packet now
Regenerate packet
Archive
Mark applied
Force CV family
Force include block
Force exclude block
```

MVP controls:

```text
Generate now
Regenerate
Archive
Mark applied
```

---

## 13. Key Design Corrections

1. The extension should send URL plus visible page content, not URL only.
2. The backend should create a raw durable job record before parsing.
3. Q1/RB items should be called raw jobs or scored candidates, not packets.
4. The final word "packet" should mean generated CV PDF plus metadata.
5. A database-backed scored backlog is probably simpler than a literal in-memory ring buffer.
6. Canonical CV blocks may be selected, excluded, and reordered, but never rewritten.
7. Fitting may adjust bounded layout settings and remove only the lowest-value optional block.
8. Generated prose, rewrite acceptance gates, and truth-checking generated text are rejected.
9. Every generated packet should have a manifest.
10. Every failure should be visible and retryable where possible.
