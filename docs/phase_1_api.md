# Phase 3 API

Base URL for local development:

```text
http://127.0.0.1:8765
```

## Live Semantic Provider Configuration

The optional live provider uses the official OpenAI Responses SDK with strict
JSON-schema output. Export configuration locally or copy `.env.example` values
into your shell; no environment file is loaded automatically.

```bash
export JOBAGENT_LLM_ENABLED=true
export JOBAGENT_LLM_API_KEY='replace-with-local-key'
export JOBAGENT_LLM_MODEL=gpt-4o-mini
export JOBAGENT_LLM_TIMEOUT_SECONDS=10
export JOBAGENT_LLM_RETRY_COUNT=1
```

Run one explicit live semantic request only when intended:

```bash
PYTHONPATH=backend/src python3 scripts/live_llm_smoke.py --live
```

This command is not part of the default test suite. If a provider request,
credential, timeout, or schema failure occurs, normal Queue 1 scoring persists
deterministic fallback output instead.

## `POST /api/jobs`

Creates a raw job capture or returns the existing job for a duplicate normalized URL.
The job is queued for deterministic intake processing.

Request:

```json
{
  "url": "https://example.com/jobs/123",
  "page_title": "Example Engineer",
  "visible_text": "Visible page text",
  "source_site": "example.com",
  "captured_at": "2026-06-19T12:00:00Z",
  "evidence": {
    "document_title": "Example Engineer",
    "detected_site": "greenhouse",
    "json_ld_job_postings": [],
    "meta": {},
    "headings": [],
    "likely_title_elements": [],
    "likely_company_elements": [],
    "likely_location_elements": [],
    "likely_description_elements": [],
    "diagnostics": {}
  }
}
```

Response:

```json
{
  "job_id": "...",
  "intake_status": "queued",
  "packet_status": "not_requested",
  "duplicate": false,
  "job": {
    "job_id": "...",
    "source_url": "https://example.com/jobs/123",
    "normalized_url": "https://example.com/jobs/123",
    "duplicate_key": "https://example.com/jobs/123",
    "capture_evidence": {},
    "detected_site": "greenhouse",
    "extraction_candidates": {
      "company": [],
      "title": [],
      "location": []
    },
    "company": null,
    "title": null,
    "location": null,
    "jd_text": null,
    "jd_quality_score": null,
    "jd_quality_band": null,
    "jd_quality": null,
    "extraction_warnings": [],
    "failure_reason": null,
    "manual_review_reason": null,
    "intake_status": "queued",
    "packet_status": "not_requested"
  }
}
```

## `GET /api/jobs`

Returns active, non-archived jobs.

Query:

```text
include_archived=true
```

Response:

```json
{
  "jobs": []
}
```

## `GET /api/jobs/{job_id}`

Returns one persisted job.

Response:

```json
{
  "job": {}
}
```

Phase 2 intake fields included in job responses:

```text
normalized_url
duplicate_key
capture_evidence
detected_site
extraction_candidates
duplicate_warning
jd_text
jd_quality_score
jd_quality_band
jd_quality
structured_jd
company
title
location
extraction_method
extraction_warnings
failure_reason
manual_review_reason
field_provenance
raw_text_length
clean_text_length
jd_text_fingerprint
```

## `GET /api/jobs/{job_id}/score`

Returns persisted structured JD, CV-family selection, section scores, score
breakdown, strengths, gaps, and hard blockers.

## `GET /api/jobs/{job_id}/block-scores`

Returns every selected-truth-bank block score with its dimensions, aggregate,
matched requirements, unmatched requirements, risk, and scoring version.

## `GET /api/jobs/{job_id}/semantic-assessment`

Returns hybrid scoring diagnostics without credentials: scoring mode, LLM call
status/failure reason, model and prompt versions, deterministic and semantic
family evidence, family decision, and validated semantic assessment when one is
available.

## `POST /api/jobs/{job_id}/rescore`

Replaces the persisted hybrid or deterministic scoring result for an already scored job.
It transitions `scored -> scoring -> scored`; a scoring failure is persisted as
`failed` and remains retryable.

## `POST /api/jobs/{job_id}/generate`

Queues dummy Q2 work for the job. Duplicate active or completed packet work returns the
existing job state.

Response:

```json
{
  "job": {}
}
```

## `POST /api/jobs/{job_id}/retry`

Retries only `failed` or `manual_review` intake/packet states.

Response:

```json
{
  "job": {}
}
```

## `POST /api/jobs/{job_id}/archive`

Archives a job and hides it from the default dashboard list.

Response:

```json
{
  "job": {}
}
```

## `GET /api/jobs/{job_id}/events`

Returns persisted event history for a job.

Response:

```json
{
  "events": []
}
```

## `POST /api/workers/q1/run-once`

Runs one deterministic intake item through a compatible status flow.

Successful intake and scoring:

```text
queued -> extracting -> structuring -> scoring -> scored
```

Weak intake:

```text
queued -> extracting -> structuring -> manual_review
```

Unusable intake:

```text
queued -> extracting -> structuring -> failed
```

Response:

```json
{
  "processed": true,
  "job": {}
}
```

## `POST /api/workers/q2/run-once`

Runs one dummy Q2 item through:

```text
queued -> generating -> ready
```

Response:

```json
{
  "processed": true,
  "job": {}
}
```
