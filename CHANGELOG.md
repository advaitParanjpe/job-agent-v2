# Changelog

## job-agent-v2 v0.1.0

Release candidate date: 2026-06-30.

### Supported

- Local API, static dashboard, Chrome extension capture path, SQLite storage,
  and local filesystem packet artifacts.
- Queue 1 deterministic intake, scoring, and four-family classification.
- Queue 2 approved master-CV packet generation and bounded one-block tailoring.
- Review API/UI for classification and tailoring decisions.
- Review-driven packet regeneration with linked packet versions and prior
  packet preservation.
- Continuous local worker runner for `q1`, `q2`, and `regeneration`.
- Worker status, queue summaries, stale-job visibility, retry summaries, and
  safe operational events.
- Release preflight diagnostics, database schema inspection, one-command local
  startup, and isolated end-to-end smoke testing.

### Migration Notes

- The supported SQLite schema is initialized idempotently.
- Startup rejects databases with a newer unsupported schema version.
- Back up `data/jobagent_v2.sqlite3` before manual migration experiments.

### Caveats

- This is a local-first release candidate, not a hosted multi-user production
  service.
- Semantic evidence requires explicit opt-in and external credentials.
- Missing LaTeX only blocks tailored compilation paths; canonical master-copy
  packets can still use approved PDFs.
- Master CVs and approved project blocks are not generated or rewritten by the
  system.
