# Codex Handoff Instructions

Start every session by reading `project/current.md`, then inspect the relevant source, tests, and recent git state before trusting status text.

Work on the single active milestone in `project/current.md`. Update its Progress log at meaningful checkpoints, run every listed validation command, and set Final status only when the milestone is complete or a documented hard blocker is real.

When a milestone completes, update `project/history.md` with validation evidence, update `project/roadmap.md`, and then write the next active milestone into `project/current.md`. Do not begin a broad new implementation after selecting the next milestone unless the user explicitly asks.

Treat `docs/build_reports/` as historical snapshots. If they conflict with code, tests, or reproducible commands, prefer the current implementation evidence and record the discrepancy.

Keep the product local-only and canonical-content based. Do not add generated CV prose, paid services, credentials, hosted deployment, or destructive migrations without explicit justification.
