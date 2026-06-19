# Phase 3 Real Queue 1 Scoring

## Objective

Implement deterministic Queue 1 scoring and ranking after successful intake.
Phase 3 creates no packets, promotion policy, scheduler, CV rewriting, or PDF.

## Scope implemented

- Scoring-oriented deterministic JD structuring.
- Configurable CV families: `hardware_rtl`, `cpu_gpu_architecture`,
  `embedded_firmware`, and `software`.
- Versioned JSON truth-bank loading and validation.
- Family selection with evidence, confidence, optional secondary family, and
  persisted selector version.
- Explainable per-block dimensions, section summaries, overall score,
  recommendation, strengths, gaps, hard blockers, and score provenance.
- Additive SQLite `job_scores` and `job_block_scores` persistence plus queryable
  job-summary columns.
- Score and block-score APIs, manual rescore, dashboard score columns, ranking,
  and score-detail link.

## Scoring architecture

`scoring.py` separates JD structuring, family selection, truth-bank validation,
block scoring, section aggregation, overall aggregation, and persistence.
No LLM invocation exists. Truth-bank data lives in package configuration rather
than business logic.

Each block records 0-100 technical, keyword, responsibility, evidence,
seniority, recency, impressiveness, domain, and overclaim-risk dimensions.
The aggregate is a weighted sum of those dimensions minus risk, clamped to
0-100. Section score is `0.50 * best + 0.30 * top-block average + 0.20 * 75`.

Overall score is:

```text
0.25 role-family fit + 0.25 must-have coverage + 0.20 top-three block average
+ 0.10 skills match + 0.10 domain match + 0.10 evidence strength
- hard-blocker penalty
```

Recommendation bands are Strong apply (85+), Apply (75+), Consider (65+), and
Low priority. Citizenship or clearance requirements apply a 35-point penalty
and cap a positive recommendation at Consider.

## Q1 behavior

Successful Q1 flow is now:

```text
queued -> extracting -> structuring -> scoring -> scored
```

Scoring configuration or validation failure transitions `scoring -> failed`,
persists a reason and scoring status, and remains retryable. Manual rescore uses
`scored -> scoring -> scored` and replaces the previous score rows safely.

## CV-family configuration and truth banks

Each family configuration contains ID, display name, description, target role
patterns, enabled state, version, and truth-bank path. Each truth bank has a
family/version and reusable experience/project blocks with canonical text,
technologies, domains, metrics, recency, impressiveness, and provenance.

## V1 references consulted

- `jobagent_v2_plan/v1_reference_map.md` Phase 3 entries.
- Read-only audit material for truth-bank validation, block scoring, and CV
  selector lessons.

V1 source was not copied. The implementation avoids V1's user/session model,
LLM extraction flow, and packet orchestration.

## Tests and verification

Added unit coverage for structured JD, selector ambiguity, truth-bank failure,
hard blockers, recommendation bands, clamping, and stable aggregation.
Added integration coverage for score persistence/restart semantics, ranking,
rescore replacement, and block-score persistence. Added API contract coverage
for score and block-score response shapes. Frontend checks cover score,
recommendation, role, CV family, unscored, and queued rendering.

Commands run:

```text
python3 -m pytest
npm test
npm run build
python3 scripts/check.py
git diff --check
```

## Manual evaluation set

The ten sanitized cases and pre-review expectations are in
`docs/phase_3_evaluation_set.md`. Human review is pending, so this table does
not claim evaluation approval.

| Job | Expected family | Selected family | Expected recommendation | Actual recommendation | Top blocks | Human judgement | Notes |
|---|---|---|---|---|---|---|---|
| RTL ASIC | hardware_rtl | pending review | Strong apply | pending review | pending | pending | Baseline hardware case |
| GPU architecture | cpu_gpu_architecture | pending review | Apply | pending review | pending | pending | Architecture evidence |
| Firmware | embedded_firmware | pending review | Apply | pending review | pending | pending | Firmware evidence |
| Backend | software | pending review | Apply | pending review | pending | pending | Software evidence |
| GPU firmware | ambiguous | pending review | Consider | pending review | pending | pending | Family ambiguity |
| Cleared RTL | hardware_rtl | pending review | Consider | pending review | pending | pending | Hard blocker case |
| FPGA | hardware_rtl | pending review | Apply | pending review | pending | pending | Adjacent role |
| Distributed systems | software | pending review | Apply | pending review | pending | pending | Backend variant |
| Accelerator | cpu_gpu_architecture | pending review | Apply | pending review | pending | pending | Architecture variant |
| Senior embedded | embedded_firmware | pending review | Consider | pending review | pending | pending | Seniority mismatch |

## Known limitations and deferred Phase 4 work

- The truth banks are deterministic local starter configuration, not personal CV
  content approval.
- Manual family override is represented in persisted selection metadata but has
  no settings UI yet.
- Human evaluation of all ten cases is required before readiness.
- Phase 4 promotion thresholds, scheduler, Q2 queue policy, ring buffer, and
  all packet-generation work remain unimplemented.

## Final status

V2 has uncommitted Phase 2/2B/3 work. No V1 files were modified. Checkpoint:
`a868536`.

PHASE BLOCKED — HUMAN DECISION REQUIRED
