# JobAgent V2 Data Model

## 0. Design goals

The data model should make the system:

```text
durable
debuggable
restart-safe
easy to inspect
easy to retry
safe against hallucinated CV claims
```

The database should be the source of truth. Queues and buffers can exist, but no important state should live only in memory.

---

## 1. Core entities

Recommended core tables:

```text
jobs
job_block_scores
packets
packet_blocks
packet_events
truth_banks
cv_blocks
manual_overrides
```

For MVP, the minimum set is:

```text
jobs
job_block_scores
packets
packet_events
```

---

## 2. `jobs`

Represents one captured job posting.

```text
id
source_url
canonical_url
source_site
page_title
raw_text
raw_html_path, optional
jd_text
jd_quality_score
company
title
location
structured_jd_json
role_family
selected_cv_family
secondary_cv_family
cv_family_confidence
intake_status
packet_status
overall_score
recommendation
reason
critical_gaps_json
top_matching_blocks_json
manual_priority
is_archived
is_applied
created_at
updated_at
```

### Notes

`raw_text` stores what the extension captured.

`jd_text` stores the cleaned extracted job description.

`structured_jd_json` stores normalized JD fields.

`manual_priority` lets the user force a job to the top.

---

## 3. `structured_jd_json`

Suggested schema:

```json
{
  "company": "AMD",
  "title": "RTL Design Engineer",
  "location": "Austin, TX",
  "employment_type": "Full-time",
  "seniority": "New grad / early career",
  "role_family": "RTL / ASIC",
  "responsibilities": [],
  "must_have_skills": [],
  "nice_to_have_skills": [],
  "tools": [],
  "domains": [],
  "hardware_keywords": [],
  "software_keywords": [],
  "education_requirements": [],
  "work_authorization_constraints": [],
  "start_date_constraints": [],
  "raw_constraints": []
}
```

---

## 4. `job_block_scores`

Represents the score of one CV block against one job.

```text
id
job_id
block_id
block_type
block_name
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
scoring_model
prompt_version
created_at
```

### Block types

```text
education
experience
project
skill_group
achievement
```

---

## 5. `cv_blocks`

Represents reusable CV content from a truth bank.

```text
id
truth_bank_id
block_type
block_name
canonical_text
bullet_json
claim_sources_json
allowed_metrics_json
allowed_technologies_json
forbidden_claims_json
is_required
is_optional
base_priority
created_at
updated_at
```

### Notes

Education should generally be required.

Projects and experience blocks may be optional depending on the selected CV family and target role.

---

## 6. `truth_banks`

Represents a CV-family-specific truth bank.

```text
id
name
cv_family
version
source_cv_path
truth_bank_json_path
created_at
updated_at
```

Suggested truth banks:

```text
hardware_truth_bank
embedded_truth_bank
swe_truth_bank
architecture_truth_bank
```

---

## 7. `packets`

Represents one generated application packet for a job.

Canonical content invariant: `packet_blocks.canonical_text` is copied unchanged from
the selected CV family or validated truth bank. Packet data records selection,
ordering, fitting, layout, exclusions, and artifact versions; it does not require
rewritten text, rewrite scores, prompt versions, truth checks, or rewrite acceptance
fields.

```text
id
job_id
status
pdf_path
tex_path
manifest_path
jd_snapshot_path
score_json_path
selected_cv_family
section_order_json
selected_blocks_json
fit_summary_json
selection_summary_json
created_at
updated_at
```

### Packet statuses

```text
queued
generating
rendering
fitting
ready
failed
manual_review
```

---

## 8. `packet_blocks`

Represents the actual blocks included in a packet.

```text
id
packet_id
job_id
block_id
block_type
block_name
section_name
position
source_block_id
canonical_text
block_score
selection_reason
was_pruned
prune_reason
created_at
```

This table is optional for MVP if the same information is stored in the packet manifest, but it is useful for debugging.

---

## 9. `packet_events`

Append-only event log for debugging.

```text
id
job_id
packet_id
event_type
stage
message
metadata_json
created_at
```

### Example event types

```text
job_added
dedupe_checked
jd_extracted
jd_structured
cv_family_selected
job_scored
block_scored
promoted_to_q2
packet_generation_started
pdf_rendered
fit_tier_applied
optional_block_excluded_for_fit
packet_ready
packet_failed
manual_override_applied
```

---

## 10. `manual_overrides`

Optional but useful later.

```text
id
job_id
override_type
override_value_json
reason
created_at
```

### Override types

```text
force_cv_family
force_include_block
force_exclude_block
manual_priority
manual_generate
archive
mark_applied
```

---

## 11. Job status fields

Use separate status fields.

### `intake_status`

```text
raw_added
queued
extracting
structuring
scoring
scored
duplicate
failed
manual_review
```

### `packet_status`

```text
not_requested
queued
generating
rendering
fitting
ready
failed
manual_review
skipped_low_score
```

This allows a job to be scored but not yet have a generated packet.

---

## 12. Packet manifest

Each final packet should save a manifest JSON.

Example:

```json
{
  "job": {
    "company": "AMD",
    "title": "RTL Design Engineer",
    "url": "..."
  },
  "score": 88,
  "recommendation": "Apply",
  "selected_cv_family": "hardware",
  "role_family": "RTL / ASIC",
  "selected_blocks": [
    "TinyNPU",
    "AXI4-Stream UVM Router",
    "PixelForge",
    "JLR Semiconductor Applications Intern"
  ],
  "section_order": [
    "Education",
    "Projects",
    "Experience",
    "Skills"
  ],
  "fit": {
    "template_tier": 2,
    "removed_optional_blocks": []
  },
  "versions": {
    "model": "TBD",
    "prompt_version": "v1",
    "truth_bank_version": "hardware_v1",
    "template_version": "v1",
    "scoring_weights_version": "v1"
  },
  "outputs": {
    "pdf_path": "...",
    "jd_snapshot_path": "...",
    "score_json_path": "..."
  }
}
```

---

## 13. Reproducibility fields

Every scoring and packet generation run should store:

```text
truth bank version
CV template version
scoring weights version
timestamp
```

This allows comparison if changes make outputs worse.

---

## 14. Failure handling fields

Failed jobs or packets should store:

```text
failure_stage
failure_reason
failure_metadata_json
retry_available
```

Examples:

```text
JD extraction failed
JD quality too low
company/title missing
LLM JSON parse failed
block scoring failed
PDF render failed
one-page fit failed
no suitable blocks found
```
