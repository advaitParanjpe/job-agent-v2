# ADR-001: Canonical CV Tailoring

## Status

Accepted

## Context

Phase 5 demonstrated that deterministic packet generation, selected canonical blocks,
and reviewable artifacts provide the useful tailoring value. Generated CV prose adds
truthfulness risk, latency, implementation complexity, and diminishing returns.

## Decision

JobAgent V2 tailors CVs through family selection, canonical block selection, ordering,
section ordering, and bounded one-page fitting—not generated prose.

All rendered experience and project wording must remain unchanged from a selected CV
family or validated truth bank. Formatting, escaping, whitespace, and bounded layout
changes are permitted.

## Supported tailoring mechanisms

- CV-family selection
- Experience/project block scoring, selection, ordering, and optional exclusion
- Projects-versus-Experience section ordering
- Approved truth-bank skill selection
- Deterministic rendering, bounded one-page fitting, and manual review

## Rejected alternatives

Free-form bullet rewriting, LLM reframing, paraphrasing, semantic refinement,
terminology substitution, generated summaries/headlines, rewrite-scoring loops, and
truth-checking generated rewrites are rejected for the core product. They are optional
research ideas only, disabled by default and not planned runtime features.

## Consequences

The system cannot claim improvements from generated wording. It must invest instead in
accurate real CV families, provenance, block scoring, transparent manifests, and safe
fit policy. A selected CV remains explainable because every rendered claim has a
canonical source.

## Impact on roadmap

Phase 6 registers real canonical CV families and truth banks. Phase 7 adds only
deterministic layout fitting and optional-block removal. Phase 8 completes review and
workflow polish. No roadmap phase implements generated prose.

## Impact on existing implementation

Phases 1–5 remain valid: Phase 3 scoring ranks existing content, and Phase 5 renders
canonical selected content. Existing placeholder truth banks are replaced in Phase 6;
no rewrite-specific persistence or worker stage is required.
