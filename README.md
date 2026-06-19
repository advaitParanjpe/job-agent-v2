# JobAgent V2

Local-only job application queue and packet-generation system.

This repository is currently in Phase 0B bootstrap. It contains only project
structure, placeholder validation, and smoke tests. It intentionally does not
implement real queues, JD extraction, scoring, CV tailoring, PDF generation,
dashboard features, or LLM calls.

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

