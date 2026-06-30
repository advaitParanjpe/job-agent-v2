# Canonical Master-CV Registration

This document defines the approved fixed-master CV registration contract.

## Directory Structure

Approved master CVs live in `master-cvs/` as a flat directory. Exactly these
families are supported:

```text
digital_ic_master.tex
digital_ic_master.pdf
verification_master.tex
verification_master.pdf
software_master.tex
software_master.pdf
ml_master.tex
ml_master.pdf
```

The registered family identifiers are:

```text
digital_ic
verification
software
ml
```

Display names:

```text
Digital IC / RTL Design
Design Verification / SoC Verification
Software Engineering
Machine Learning Engineering
```

Do not collapse Software and ML into one family.

## Validation Rules

`jobagent_v2.master_cvs.discover_master_cvs()` validates that:

- all four expected families are present;
- each family has exactly one `.tex` and one `.pdf`;
- unknown, duplicate, missing, or ambiguously named files fail;
- each approved PDF is readable and exactly one page;
- each `.tex` file contains `Education`, `Experience`, `Projects`, and `Skills`;
- coursework is present in `Education`;
- header/contact, education, and experience sections are structurally identical
  across all four masters after whitespace/comment normalization;
- metadata records stable family IDs, display names, paths, SHA-256 hashes,
  page count, approval status, immutable sections, and dynamic-skills policy.

The master records are user-approved and immutable. Header/contact, education,
experience, and coursework must not be rewritten, reordered, summarized, or
tailored. Skills are fixed per approved master and are not dynamically rewritten
for a job.

## Packet Behavior

For a family with approved `master_cv` metadata in
`backend/src/jobagent_v2/data/cv_families.json`, packet generation copies the
approved `.tex` and `.pdf` into the packet artifact directory unchanged. It does
not render from starter truth-bank content and does not rewrite bullets.

The packet manifest records the selected master metadata and marks the packet
as immutable.

## Compile Check

The validator includes `validate_master_tex_compiles()` for environments with a
complete LaTeX toolchain. Byte-level comparison between a freshly compiled PDF
and the approved committed PDF is intentionally not required because PDF builds
can include environment-dependent object IDs, timestamps, compression choices,
and package versions. The approved committed PDF remains the canonical artifact.

If the local TeX distribution is incomplete, the compile check may be skipped
while direct approved-PDF validation still runs.

## Future Work

Family classification is separate from candidate-fit scoring. The next phase
should classify jobs across all four families with evidence-backed normalized
scores and a review policy. Later bounded tailoring may only use approved whole
project blocks; it must never rewrite, merge, split, shorten, or generate
resume bullets.
