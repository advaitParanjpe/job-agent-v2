# Worker Operations

Operational Worker Scheduling and Monitoring adds local continuous worker loops
for the existing queues. It does not change classification, scoring, CV
tailoring, or packet-generation policy.

## Worker Types

- `q1`: deterministic intake, structuring, family classification, and
  candidate-fit scoring.
- `q2`: packet generation from promoted Q2 tasks.
- `regeneration`: reviewed packet regeneration from queued review resolutions.

Each worker wraps the existing run-once business logic. Queue claiming remains
authoritative in SQLite.

## Startup Commands

Release preflight:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.preflight
```

API, all workers, and frontend together:

```bash
./scripts/dev-up
```

API only:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.server
```

One worker only:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.worker_runner --worker q1
PYTHONPATH=backend/src python3 -m jobagent_v2.worker_runner --worker q2
PYTHONPATH=backend/src python3 -m jobagent_v2.worker_runner --worker regeneration
```

All workers in one local process:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.worker_runner --all
```

Frontend plus backend plus workers, in separate terminals:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.server
PYTHONPATH=backend/src python3 -m jobagent_v2.worker_runner --all
python3 -m http.server 5173 --directory frontend/src
```

Manual debugging endpoints remain available:

```http
POST /api/workers/q1/run-once
POST /api/workers/q2/run-once
POST /api/workers/regeneration/run-once
POST /api/workers/promotion/run-once
```

## Polling Configuration

Environment-backed settings:

```json
{
  "q1_poll_seconds": 5,
  "q2_poll_seconds": 5,
  "regeneration_poll_seconds": 5,
  "idle_backoff_max_seconds": 30,
  "health_heartbeat_seconds": 10,
  "max_consecutive_failures": 3
}
```

Environment variable names:

- `JOBAGENT_Q1_POLL_SECONDS`
- `JOBAGENT_Q2_POLL_SECONDS`
- `JOBAGENT_REGENERATION_POLL_SECONDS`
- `JOBAGENT_IDLE_BACKOFF_MAX_SECONDS`
- `JOBAGENT_HEARTBEAT_SECONDS`
- `JOBAGENT_MAX_CONSECUTIVE_FAILURES`

Empty queues cause deterministic idle backoff up to the configured maximum.
Finding work resets the backoff to the worker's normal poll interval.

## Lifecycle

Worker instances persist:

- worker type;
- generated instance ID;
- process ID;
- safe hostname;
- state;
- started/stopped timestamps;
- last heartbeat;
- current job;
- last completed job;
- last success/failure;
- processed and failure counts;
- polling interval;
- runner version.

States include `starting`, `idle`, `processing`, `backing_off`, `stopping`,
`stopped`, and `unhealthy`.

`SIGINT` and `SIGTERM` request graceful shutdown. The runner stops claiming new
work and marks its instance stopped. Existing Q2 and regeneration leases remain
recoverable through their existing stale-lease recovery paths.

## Health Rules

A worker instance is:

- `idle` when it has a recent heartbeat and is idle;
- `healthy` when it has a recent heartbeat and is starting, processing, or
  backing off;
- `degraded` when it reports unhealthy state or exceeds consecutive failure
  thresholds;
- `offline` when stopped or heartbeat age exceeds the configured threshold.

A queue is degraded when queued work has no healthy worker, stale processing
work exists, retry attempts are exhausted, failed work exists, or the oldest
queued item exceeds the configured queue-age threshold. An empty queue with a
healthy idle worker is healthy/idle, not a failure.

## Queue Metrics

`GET /api/workers/status` returns worker instances, queue summaries, health,
recent safe operational events, and safe config values.

`GET /api/workers/{worker_type}/status` returns the same view for one of:
`q1`, `q2`, or `regeneration`.

`GET /api/workers/queues` returns queue summaries only.

Metrics include queued count, processing count, failed count, retryable count,
oldest queued timestamp/age, stale processing count, and retry-exhausted count
where applicable.

## Structured Logs

Worker logs are JSON lines with:

- event type;
- worker type;
- worker instance ID;
- state;
- safe job ID where useful;
- safe error code;
- timestamp.

Logs intentionally avoid CV content, full job descriptions, review notes,
email addresses, phone numbers, environment secrets, stack traces, and raw
artifact paths.

## Troubleshooting

Recover stale Q2 work:

```http
POST /api/workers/promotion/run-once
```

Recover stale regeneration work:

```http
POST /api/workers/regeneration/run-once
```

Inspect failed regeneration:

```http
GET /api/reviews?status=regeneration_failed
GET /api/workers/status
```

If a worker is offline while work is queued, start:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.worker_runner --all
```
