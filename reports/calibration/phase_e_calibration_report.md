# Phase E Calibration Report

Generated: 2026-06-30T11:37:24Z
Dataset: phase-e-real-role-patterns-v1 (phase-e-labelled-jobs-v1)
Semantic mode: deterministic

## Dataset
- Total examples: 90
- Train: 70
- Holdout: 20
- Categories: {"digital_ic": 15, "hybrid": 20, "ml": 15, "out_of_scope": 10, "software": 15, "verification": 15}

## Baseline Holdout Metrics
- Macro F1: 0.8485
- Primary accuracy: 1.0
- Wrong high-confidence no-review rate: 0.05
- Out-of-scope review rate: 0.6667
- Unnecessary substitution rate: 0.0
- Invalid substitution rate: 0.0

## Baseline Configuration
- Classifier config version: phase-b-family-classifier-config-v1
- Decision thresholds: {"clear_min_score": 0.65, "clear_min_margin": 0.25, "close_max_margin": 0.12, "low_confidence_max_score": 0.4, "hybrid_min_margin": 0.13}
- Combination weights: {"deterministic_weight": 0.6, "semantic_weight": 0.4}
- Tailoring policy version: phase-d-one-block-tailoring-v1
- Minimum replacement gain: 0.15
- Clear-match replacement gain: 0.2
- Dominant-family margin: 0.25

## Candidate Holdout Metrics
- Macro F1: 0.8485
- Primary accuracy: 1.0
- Wrong high-confidence no-review rate: 0.05
- Out-of-scope review rate: 0.6667
- Unnecessary substitution rate: 0.0
- Invalid substitution rate: 0.0

## Candidate Configuration
- Classifier config version: phase-b-family-classifier-config-v1
- Decision thresholds: {"clear_min_score": 0.68, "clear_min_margin": 0.25, "close_max_margin": 0.12, "low_confidence_max_score": 0.4, "hybrid_min_margin": 0.13}
- Combination weights: {"deterministic_weight": 0.6, "semantic_weight": 0.4}
- Tailoring policy version: phase-d-one-block-tailoring-v1
- Minimum replacement gain: 0.15
- Clear-match replacement gain: 0.2
- Dominant-family margin: 0.25

## Holdout Failure Cases
- Wrong high-confidence no-review examples: ['out-008-holdout-analog-layout']
- Review-flagged examples: ['hyb-019-holdout-fpga-ai', 'out-009-holdout-program-manager', 'out-010-holdout-field-sales']
- Tailoring safety errors: none
- Expected swaps missed: ['dic-015-holdout-npu', 'ml-014-holdout-edge', 'hyb-019-holdout-fpga-ai']

## Acceptance Gates
- macro_f1_no_regression: True
- wrong_high_confidence_rate_max_0: False
- no_invalid_substitutions: True
- unnecessary_substitution_rate_max_0_05: True
- out_of_scope_review_rate_min_0_80: False
- Overall: False

## Promotion Decision
- Promote: False
- Reason: Candidate must improve train objective and pass holdout safety gates.

## Limitations
- Dataset examples are concise synthetic/paraphrased role patterns.
- Bulk tailoring evaluation is structural and does not compile every PDF.
- Live semantic evaluation was not run unless semantic_mode is live.
