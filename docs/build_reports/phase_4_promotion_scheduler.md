# Phase 4: Promotion Scheduler and Q2 Queueing

## Objective and scope

Phase 4 adds durable promotion between scored Queue 1 jobs and the existing dummy
Queue 2 artifact worker. It does not select CV blocks, tailor content, or generate a
real packet.

## Implemented

- SQLite `q2_tasks` records with one task per job, task status, priority, promotion
  reason, score snapshot, override flag, attempts, lease data, failure reason, and
  timestamps.
- Configurable policy: 60-second intended poll interval, capacity 8, worker
  concurrency 1, automatic threshold 82, manual-review threshold 70, and daily
  automatic budget 10. Manual Generate now bypasses threshold and automatic budget.
- Deterministic scheduler route `POST /api/workers/promotion/run-once`.
- Persistent star and high/normal priority controls, promotion events, queue API,
  stale lease recovery, and a dummy Q2 worker that consumes Q2 tasks.
- Dashboard columns/actions for star/priority, Q2 status, and promotion reason.

## Policy

Eligible jobs are scored, non-archived, unblocked, and have no existing Q2 task.
Automatic promotion selects starred/high-priority jobs or jobs scoring at least 82,
ordered by manual priority, star, score, then creation time. Hard blockers reject both
automatic and manual promotion. Expired Q2 leases requeue until three attempts, then
fail. Capacity counts queued plus claimed/running tasks; worker concurrency counts only
claimed/running tasks.

## Files changed

- `backend/src/jobagent_v2/storage.py`
- `backend/src/jobagent_v2/promotion.py`
- `backend/src/jobagent_v2/workers.py`
- `backend/src/jobagent_v2/service.py`
- `backend/src/jobagent_v2/api.py`
- `backend/tests/integration/test_phase4_promotion_flow.py`
- `frontend/src/app.js`, `frontend/src/index.html`, and dashboard checks
- `.env.example`, `docs/phase_1_api.md`, and `jobagent_v2_plan/build_roadmap.md`

## Verification

`PYTHONPATH=backend/src python3 -m pytest backend/tests -q` passed: 70 tests.
`npm run test` and `npm run build` in `frontend/` passed. The initial root-level npm
command was invalid because this repository keeps `package.json` under `frontend/`.

## Manual validation and limitations

The required six-job manual policy validation has not been run in this pass. The local
server starts the promotion loop by default; set `JOBAGENT_PROMOTION_SCHEDULER_ENABLED`
to `false` for deterministic manual testing, then use the explicit promotion route.
Phase 5 real packet work remains deferred.

PHASE BLOCKED — HUMAN DECISION REQUIRED
