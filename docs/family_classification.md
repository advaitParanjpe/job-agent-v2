# Auditable Four-Family Job Classification

Phase B classifies each normalized job into exactly one of the four approved
canonical master-CV families:

- `digital_ic`
- `verification`
- `software`
- `ml`

This classification answers "which fixed approved master CV is the closest
base family for this job?" It is separate from candidate-fit scoring. A job can
classify confidently as `digital_ic` while still receiving a low candidate-fit
score because of seniority, authorization, location, or skill gaps.

## Deterministic Configuration

Deterministic classification is configured in
`backend/src/jobagent_v2/data/family_classifier.json`.

The configuration is versioned with:

- `classifier_version`: implementation contract;
- `config_version`: signal and threshold contract.

Signals are grouped by title, responsibility, qualification, domain, and
tool/language evidence. Title and responsibility signals carry more weight than
incidental tool mentions. Phrase matching is used rather than isolated token
counting, so evidence such as `backend APIs`, `timing closure`, or
`functional coverage` is preserved as auditable matches.

## Responsibility Over Tool Policy

The classifier prioritizes the work being performed and the primary artifact
being built:

- Python infrastructure for UVM regression triage is verification-oriented.
- RTL implementation for an accelerator remains Digital IC-oriented even when
  Python is used for performance modelling.
- PyTorch model training, model evaluation, quantization, and deployment score
  toward ML.
- Backend APIs, databases, developer tools, distributed systems, and production
  infrastructure score toward Software, including many AI-product backend roles
  where model development is not the core responsibility.

## Semantic Classification

`jobagent_v2.family_classifier` supports an optional semantic provider. By
default no semantic provider is configured, so classification remains fully
offline and credential-free. When semantic classification is unavailable or
malformed, the classifier records an unavailable semantic evidence entry and
uses deterministic scores alone.

When a semantic provider is supplied, it must return structured output with
normalized scores for all four families and extracted evidence. Scores are
combined with the configured default weights:

- 60% deterministic classification;
- 40% semantic classification.

No test requires live credentials. Tests use deterministic fake semantic
providers.

The dashboard exposes semantic status explicitly instead of implying success
from an empty evidence list:

- `live_success`: live provider output was validated and used.
- `disabled`: semantic mode is disabled.
- `not_configured`: semantic mode is enabled but no key is configured.
- `fallback_used`: deterministic fallback was used.
- `request_failed`: the provider request failed safely.
- `response_invalid`: provider output failed validation.
- `timed_out`: the request timed out.
- `not_attempted`: no request was attempted for this job.

Persisted semantic diagnostics include enabled/attempted/fallback flags, model,
provider, timestamps/latency where available, safe failure code/summary,
semantic assessment summary, deterministic family decision, and the final
selection rule. API responses and the dashboard must not expose API keys,
authorization headers, stack traces, or private model reasoning.

Verify semantic mode without writing to the jobs database:

```bash
./scripts/semantic-check --no-network
./scripts/semantic-check
```

The live form sends one small synthetic UVM/Python verification request and may
incur provider cost. It prints only success/failure, model, latency, selected
family, and evidence count.

## Decision Policy

The initial configurable thresholds are:

- `clear_match`: top score at least `0.65` and at least `0.25` above second.
- `close_match`: top two scores within `0.12`; requires review.
- `low_confidence`: top score no greater than `0.40`; requires review.
- `hybrid_match`: meaningful but non-clear lead; does not perform tailoring in
  this milestone.

If a title signal conflicts with the selected family, a would-be clear match is
downgraded to `hybrid_match` so the decision remains auditable.

User-facing surfaces must not show `hybrid_match` alone. They should present it
as a mixed role, for example "Mixed role: Verification + Software", followed by
the selected CV family, secondary family, review requirement, and rule-based or
semantic evidence that caused the result.

## Persistence

Classification results are stored separately from candidate-fit score records:

- `jobs.family_classification_json`
- `jobs.family_classifier_version`
- `jobs.family_classification_decision`
- `jobs.family_classification_requires_review`
- `job_family_classifications`

The existing `selected_cv_family`, `secondary_cv_family`,
`cv_family_confidence`, and `cv_family_selection_json` fields remain as a
compatibility snapshot for packet generation and existing API/UI paths.

## Packet Workflow

Packet generation uses the persisted `selected_cv_family` to copy the matching
approved master `.tex` and `.pdf` unchanged. The classifier never rewrites:

- header/contact information;
- education;
- experience;
- coursework;
- family-specific skills;
- approved master TeX or PDF content.

Phase B does not implement project swapping, project ordering, bullet rewriting,
dynamic skills, or free-form CV generation.

## Naming Note

`phase6b-master-cv-v1` remains the schema identifier for the previous canonical
master-CV registry milestone. It is intentionally separate from roadmap
"Phase B", which is the family-classification milestone. Renaming the master-CV
schema would add migration churn without improving runtime behavior.
