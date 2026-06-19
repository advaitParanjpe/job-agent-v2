# Phase 1 API

Base URL for local development:

```text
http://127.0.0.1:8765
```

## `POST /api/jobs`

Creates a raw job capture or returns the existing job for a duplicate normalized URL.

Request:

```json
{
  "url": "https://example.com/jobs/123",
  "page_title": "Example Engineer",
  "visible_text": "Visible page text",
  "source_site": "example.com",
  "captured_at": "2026-06-19T12:00:00Z"
}
```

Response:

```json
{
  "job_id": "...",
  "intake_status": "queued",
  "packet_status": "not_requested",
  "duplicate": false,
  "job": {}
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

Runs one dummy Q1 item through:

```text
queued -> extracting -> scoring -> scored
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

