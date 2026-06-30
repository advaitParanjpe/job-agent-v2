# Classifier and Tailoring Calibration

Phase E adds an offline evaluation and calibration framework for the
four-family classifier and bounded one-block tailoring policy.

## Command

Run deterministic evaluation and threshold search:

```bash
PYTHONPATH=backend/src python3 -m jobagent_v2.calibration evaluate
```

By default this writes:

```text
reports/calibration/phase_e_calibration_report.json
reports/calibration/phase_e_calibration_report.md
```

The command does not write jobs to the production SQLite database.

## Dataset Format

The labelled dataset is versioned at:

```text
backend/src/jobagent_v2/data/evaluation/labelled_jobs.json
```

Each example records:

- stable `example_id`;
- `title` and concise paraphrased `description`;
- `category`;
- `split`: `train` or `holdout`;
- `expected_primary_family`;
- `acceptable_primary_families`;
- `acceptable_secondary_families`;
- expected classifier decision and review flag;
- expected tailoring action;
- acceptable and unacceptable inserted project blocks;
- label notes.

Out-of-scope examples use `expected_primary_family: null`,
`acceptable_primary_families: []`, and should require review.

## Labelling Rules

Use the primary work artifact as the family label:

- RTL/microarchitecture implementation: `digital_ic`.
- UVM, assertions, regressions, coverage, formal, or pre-silicon validation:
  `verification`.
- APIs, backend services, developer tools, platforms, infrastructure, and
  product software: `software`.
- model training, evaluation, quantization, inference quality, and model
  optimization: `ml`.

Hybrid examples may list multiple acceptable primary families. Review labels
should be used for genuinely ambiguous roles, out-of-scope roles, or cases
where a wrong confident family would be costly.

Do not copy job postings verbatim. Use concise synthetic or heavily
paraphrased role patterns.

## Split

The committed dataset has 90 examples:

- 15 Digital IC;
- 15 Verification;
- 15 Software;
- 15 ML;
- 20 hybrid or ambiguous;
- 10 out-of-scope.

It currently uses 70 train examples and 20 holdout examples. Holdout results
are used for promotion gates; train results guide candidate search.

## Metrics

Classification metrics include:

- primary-family accuracy;
- macro precision, recall, and F1;
- confusion matrix;
- top-two family recall;
- calibration by confidence band;
- close-match review recall;
- low-confidence detection rate.

Decision metrics include:

- clear-match precision;
- hybrid-match precision;
- review-flag precision and recall;
- out-of-scope review rate;
- wrong high-confidence no-review rate.

Tailoring metrics include:

- correct no-tailoring decisions;
- correct substitution decisions;
- unnecessary substitution rate;
- invalid substitution rate;
- inserted-block match rate;
- fallback rate.

The two primary safety metrics are wrong high-confidence no-review
classifications and unnecessary or invalid automatic substitutions.

## Search Objective

The deterministic search sweeps bounded classifier and tailoring thresholds.
The objective prioritizes:

1. minimizing wrong high-confidence no-review classifications;
2. minimizing unnecessary automatic substitutions;
3. improving macro F1;
4. improving hybrid-match precision;
5. avoiding excessive or insufficient review flags.

The search evaluates candidates in memory and does not overwrite production
configuration.

## Promotion Gates

A candidate is not promoted unless holdout gates pass:

- no macro-F1 regression;
- wrong high-confidence no-review rate is zero;
- no invalid substitutions;
- unnecessary substitution rate is at most 0.05;
- out-of-scope review rate is at least 0.80.

The generated Phase E report records the baseline config, best candidate,
metrics, gate results, and promotion decision. The current report does not
promote a new config because safety gates fail.

## Semantic Modes

Supported modes:

- `deterministic`: default, offline, no credentials.
- `fake`: uses deterministic fake semantic evidence for tests.
- `live`: uses the configured live semantic provider only when credentials are
  present; otherwise it falls back to deterministic behavior.

Live semantic results must be reported separately from deterministic baseline
results.

## Tailoring Evaluation

Bulk tailoring evaluation is structural: it classifies the job, chooses the
base family, scores compatible approved blocks, applies the current policy,
and validates compatibility. It does not compile every possible PDF during
threshold sweeps.

Real TeX/PDF validation remains covered by Phase D packet tests and should be
sampled separately when evaluating release readiness.

## Adding Labels

When adding examples:

1. use a new stable `example_id`;
2. keep text concise and paraphrased;
3. label the primary work artifact, not incidental tools;
4. add acceptable alternates for genuine hybrids;
5. mark out-of-scope roles as review-required;
6. state why the label is correct in `notes`;
7. keep a reserved holdout split.

Run `python3 -m pytest backend/tests/unit/test_calibration.py -q` after edits.
