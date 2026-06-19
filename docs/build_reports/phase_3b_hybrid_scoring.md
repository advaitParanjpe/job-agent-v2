# Phase 3B Hybrid Scoring

## Objective

Add validated LLM semantic evidence to Queue 1 while preserving deterministic
intake, hard constraints, final aggregation, and recommendation policy. No
promotion, scheduler, packet, rewrite, or PDF work was added.

## Architecture

The pipeline is deterministic intake and constraints, deterministic keyword
matching, optional semantic assessment, strict validation, deterministic hybrid
block conversion, deterministic overall aggregation, then deterministic
recommendation. The LLM never returns a final score, section score,
recommendation, or promotion decision.

`llm_client.py` is disabled by default and reads only environment configuration:
`JOBAGENT_LLM_ENABLED`, `JOBAGENT_LLM_API_KEY`, model, timeout, and retry count.
It requires an explicit transport, so tests never make network calls. Prompt
version `phase3b-semantic-assessment-v1` supplies clean JD, structured fields,
family evidence, and truth-bank summaries with an instruction to use only those
facts.

## Semantic Schema And Policies

Validated output requires role/family evidence, requirements, requirement-block
matches, every block's bounded 0-4 semantic dimensions, superficial-keyword
risk, strengths, gaps, ambiguities, and grounded reason. Invalid, malformed,
timeout, missing-key, and provider failures fall back without failing the job.

Family policy: agreement wins; high-confidence deterministic selection wins a
disagreement; otherwise a high-confidence grounded semantic result may override;
all other disagreements use deterministic tiebreaking.

Hybrid block aggregate is `0.55 * deterministic aggregate + 0.35 * semantic
subtotal - superficial-keyword penalty`, clamped 0-100. The final score is
`0.75 * deterministic overall + 0.25 * average hybrid block`, clamped 0-100.
Hard blockers still cap optimistic recommendations at Consider.

## Persistence And API

Additive `job_semantic_assessments` storage keeps model/prompt/schema versions,
mode, call status, fallback reason, family evidence/decision, and assessment.
Queryable job fields expose scoring mode and LLM status. Score detail merges the
semantic diagnostics; `GET /api/jobs/{job_id}/semantic-assessment` exposes them
directly.

Modes are `hybrid`, `deterministic_fallback`, and `deterministic_only`.

## V1 References

Consulted the Phase 3 V1 reference-map entries and audit lessons for truth-bank
validation and scored evidence. No V1 source was copied; V1's LLM pipeline,
session model, and packet orchestration were not reused.

## Tests And Commands

Added offline unit tests for schema bounded-scale validation, valid fake output,
family disagreement policy, missing-key fallback, timeout fallback, malformed
response fallback, clamping, and deterministic final ownership. Added integration
coverage for persisted semantic diagnostics. Existing Phase 1-3 tests remain.

Commands run:

```text
python3 -m pytest
npm test
npm run build
python3 scripts/check.py
git diff --check
```

## Evaluation Comparison

The Phase 3 ten-job set is reused. Human comparison remains pending; no tuning
was made for exact job titles.

| Job class | Deterministic | Hybrid | Human expectation | Rating |
|---|---|---|---|---|
| RTL/ASIC | baseline | fake semantic test only | hardware_rtl | pending |
| GPU architecture | baseline | pending live semantic review | architecture | pending |
| Firmware | baseline | pending live semantic review | embedded | pending |
| Backend | baseline | pending live semantic review | software | pending |
| Ambiguous GPU firmware | baseline | policy-tested | ambiguous family | pending |
| Cleared RTL | blocker-tested | blocker preserved | Consider | pending |
| Remaining four set cases | baseline | pending live semantic review | see evaluation set | pending |

Semantic value was demonstrated only with schema-valid fake evidence. No live
credentials were available, so no live smoke test was run. The fallback path was
exercised for disabled, missing-key, timeout, and malformed-output states.

## Limitations And Deferred Work

- A real provider transport and credentialed 2-3 job smoke test remain pending.
- Human review must judge hybrid quality at least as good as deterministic scoring.
- Phase 4 promotion, Q2 scheduling, ring buffer, and all packet work remain absent.

## Final Status

No V1 files were modified. Checkpoint: `a868536`.

PHASE BLOCKED — HUMAN DECISION REQUIRED
