# JobAgent V2

Local-only job application queue and packet-generation system.

This repository is currently in Phase 1. It contains a persistent local queue
skeleton with dummy workers. It intentionally does not implement real JD
extraction, scoring, CV tailoring, PDF generation, or LLM calls.

## Layout

```text
backend/     Python package and backend tests
frontend/    Placeholder frontend build
extension/   Placeholder Chrome extension structure
docs/        Build reports and project documentation
scripts/     Repository checks
```

## Check

Run the complete bootstrap check from this directory:

```bash
python3 scripts/check.py
```

## Local API

Run the Phase 1 API server:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.server
```

Endpoint documentation is in `docs/phase_1_api.md`.
