# JobAgent V2 Pipeline

## 0. Pipeline overview

```text
Chrome Extension
  ↓
Backend Intake
  ↓
Queue 1: JD extraction + scoring
  ↓
Scored Candidate Backlog
  ↓
Promotion Scheduler
  ↓
Queue 2: CV packet generation
  ↓
Dashboard
```

---

## 1. Extension capture pipeline

### Input

User clicks:

```text
Add to Queue
```

### Extension captures

```text
source_url
page_title
visible_page_text
optional_html_snapshot
timestamp
source_site, if detectable
```

### Backend response

```text
added_to_queue
already_queued
already_processed
duplicate_possible
backend_unavailable
```

---

## 2. Backend intake pipeline

```text
Receive extension payload
↓
Normalize URL
↓
Compute raw text hash
↓
Run dedupe check
↓
Create or update job record
↓
Set intake_status = queued
↓
Push job_id to Queue 1
```

If duplicate:

```text
Do not create duplicate job unless user explicitly requests it.
Return existing job_id and status.
```

---

## 3. Queue 1 pipeline: intake and scoring

Queue 1 processes raw jobs into scored candidates.

### Step 1: JD extraction

Input:

```text
raw_text
page_title
source_url
optional_html_snapshot
```

Output:

```text
jd_text
company, if extractable
title, if extractable
location, if extractable
```

Failure conditions:

```text
JD too short
navigation text dominates
company/title cannot be inferred
no responsibilities or qualifications found
```

### Step 2: JD quality scoring

Compute:

```text
jd_quality_score
```

Based on:

```text
length
presence of responsibilities
presence of qualifications
presence of skills
presence of company/title
low boilerplate ratio
```

If poor:

```text
intake_status = manual_review or failed
reason = "JD extraction quality too low"
```

### Step 3: JD structuring

Convert extracted JD into structured JSON.

Fields:

```text
company
title
location
employment_type
seniority
role_family
responsibilities
must_have_skills
nice_to_have_skills
tools
domains
education_requirements
work_authorization_constraints
start_date_constraints
```

### Step 4: CV family selection

Choose the best CV family.

Possible families:

```text
hardware / RTL / ASIC / FPGA
embedded / firmware / semiconductor applications
SWE / backend / data
architecture / GPU / accelerator / systems
```

Output:

```text
primary_cv_family
secondary_cv_family
confidence
reason
```

### Step 5: Load truth bank

Load the precomputed truth bank for the selected CV family.

Example:

```text
truth_banks/hardware_truth_bank.json
```

### Step 6: Score each CV block

For each block, compute:

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
aggregate_score
reason
```

### Step 7: Compute final job compatibility score

Recommended formula:

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

### Step 8: Save scored candidate

Save:

```text
overall_score
recommendation
role_family
selected_cv_family
top_matching_blocks
critical_gaps
reason
intake_status = scored
packet_status = not_requested or skipped_low_score
```

---

## 4. Promotion scheduler pipeline

The promotion scheduler decides whether a scored job enters Queue 2.

### Initial policy

```text
score >= 82        → auto-promote to Queue 2
70 <= score < 82   → scored only, manual generate available
score < 70         → no packet
starred job        → force packet
archived job       → never packet
```

### Promotion ordering

```text
manual_priority DESC
overall_score DESC
added_at ASC
```

### Promotion constraints

```text
max_auto_packets_per_day = 10
max_concurrent_q2_jobs = 1
manual_generate_ignores_threshold = true
```

### Output

```text
packet_status = queued
job_id pushed to Queue 2
```

---

## 5. Queue 2 pipeline: packet generation

Queue 2 creates the tailored CV packet.

```text
Q2 task → load selected CV family → load canonical truth-bank blocks → rank existing
blocks → choose section order → construct selected CV → render → one-page fitting →
final packet
```

### Step 1: Load job context

Load:

```text
structured_jd
selected_cv_family
truth_bank
block_scores
manual_overrides
```

### Step 2: Select candidate blocks

Select blocks based on:

```text
block aggregate score
role family
section balance
required blocks
manual include/exclude overrides
```

Education remains fixed.

### Step 3: Compute section scores

Compute scores for:

```text
Experience
Projects
Skills
```

Example:

```text
section_score =
  0.50 * best_block_score
+ 0.30 * average_selected_block_score
+ 0.20 * section_role_relevance
```

Section scores influence:

```text
section order
pruning priority
dashboard explanation
```

### Step 4: Choose section order

Common section orders:

For hardware / RTL / ASIC / FPGA roles:

```text
Education
Projects
Experience
Skills
```

For industry / applications / embedded roles:

```text
Education
Experience
Projects
Skills
```

The final decision should use:

```text
section scores
role family
selected visible blocks
manual override, if present
```

### Step 5: Build initial CV plan

The CV plan contains:

```text
selected blocks
section order
selected skill groups
template settings
initial bullet order
```

### Step 6: Render canonical selected CV

All selected block and skill wording is canonical truth-bank content. Rendering may
escape LaTeX and apply configured layout settings; it must not rewrite, paraphrase, or
generate CV prose.

Generate:

```text
.tex
.pdf
```

Save intermediate files for debugging.

### Step 7: Deterministic one-page fitting

Check page count after each render.

Fitting tiers:

```text
Tier 0: normal template
Tier 1: tighter spacing
Tier 2: slightly smaller font
Tier 3: remove the lowest-scoring optional block
Tier 4: manual review fail state
```

Hard constraints:

```text
minimum font size: 9.5pt
minimum margin: 0.4in
max block removals: 2
never remove education
never remove contact/header
never remove role-critical required skills
never alter wording inside a bullet
```

### Step 8: Save final packet

Save:

```text
pdf_path
tex_path
jd_snapshot
score_json
manifest_json
packet_status = ready
```

---

## 6. Dashboard update pipeline

Dashboard reads from the database.

### Columns

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

---

## 7. Failure handling pipeline

Failures should be visible.

Each failure should store:

```text
failure_stage
failure_reason
failure_metadata_json
retry_available
```

Examples:

```text
intake_failed: JD extraction quality too low
scoring_failed: LLM JSON parse failed
packet_failed: PDF render failed
manual_review: CV did not fit after max pruning
```

---

## 8. Retry policy

Retries should be stage-specific.

```text
JD extraction failed → allow retry with selected text/manual paste
scoring failed → retry scoring
packet failed → retry packet generation
fit failed → manual review
```

---

## 9. Logging

Every major transition should write a packet event.

Examples:

```text
job_added
jd_extracted
jd_structured
cv_family_selected
job_scored
promoted_to_q2
packet_generation_started
pdf_rendered
fit_tier_applied
optional_block_excluded_for_fit
packet_failed
```
