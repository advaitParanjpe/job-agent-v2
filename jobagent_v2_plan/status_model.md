# JobAgent V2 Status Model

## 0. Principle

Use separate statuses for intake/scoring and packet generation.

A job can be successfully scored without having a generated packet.

---

## 1. Intake status

Field:

```text
intake_status
```

Allowed values:

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

### Meaning

```text
raw_added       = backend created job record
queued          = waiting for Queue 1
extracting      = extracting JD from captured content
structuring     = converting JD to structured JSON
scoring         = scoring job and blocks
scored          = Queue 1 completed successfully
duplicate       = job appears to already exist
failed          = unrecoverable intake/scoring failure
manual_review   = user input needed before scoring can continue
```

---

## 2. Packet status

Field:

```text
packet_status
```

Allowed values:

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

### Meaning

```text
not_requested      = no packet requested/generated yet
queued             = waiting for Queue 2
generating         = building CV plan
rendering          = generating PDF
fitting            = applying bounded deterministic layout and optional-block fitting
ready              = final packet is available
failed             = packet generation failed
manual_review      = user input needed
skipped_low_score  = score below auto-generation threshold
```

---

## 3. Recommended status combinations

### Newly added job

```text
intake_status = queued
packet_status = not_requested
```

### Scored job, no packet yet

```text
intake_status = scored
packet_status = not_requested
```

### Low-scoring job

```text
intake_status = scored
packet_status = skipped_low_score
```

### Job waiting for packet generation

```text
intake_status = scored
packet_status = queued
```

### Packet ready

```text
intake_status = scored
packet_status = ready
```

### Intake failed

```text
intake_status = failed
packet_status = not_requested
```

### Packet failed

```text
intake_status = scored
packet_status = failed
```

---

## 4. Failure fields

For failures, store:

```text
failure_stage
failure_reason
failure_metadata_json
retry_available
```

### Common failure stages

```text
extension_capture
backend_intake
dedupe
jd_extraction
jd_structuring
cv_family_selection
job_scoring
block_scoring
promotion
cv_plan
render
fit
save_output
```

---

## 5. Retry behavior

### Retry intake

Allowed when:

```text
jd_extraction failed
jd_structuring failed
job_scoring failed
```

Action:

```text
reset intake_status to queued
clear intake failure fields
preserve original job record
```

### Retry packet

Allowed when:

```text
packet generation failed
render failed
one-page fit failed
```

Action:

```text
reset packet_status to queued
create new packet attempt
preserve old failed attempt for debugging
```

### Manual review

Used when:

```text
JD extraction quality too low
CV did not fit after max pruning
practical constraints are unclear
```

---

## 6. Dashboard labels

Map raw statuses to user-facing labels.

```text
queued              → Queued
extracting          → Extracting JD
scoring             → Scoring
scored              → Scored
skipped_low_score   → Low priority
generating          → Generating packet
ready               → Ready
failed              → Failed
manual_review       → Needs review
```

---

## 7. Event logging

Status transitions should create events.

Example:

```json
{
  "event_type": "status_changed",
  "stage": "packet_generation",
  "message": "packet_status changed from rendering to fitting",
  "metadata": {
    "old_status": "rendering",
    "new_status": "fitting"
  }
}
```
