# One-Block Project Tailoring

Phase D integrates bounded tailoring into packet generation. The approved
master CV remains the default artifact; tailoring is only a validated
one-project-block substitution.

## When Tailoring Occurs

Packet generation starts from the family selected by the four-family
classifier: `digital_ic`, `verification`, `software`, or `ml`.

The tailoring engine loads:

- the selected approved master CV;
- the approved project-block registry;
- the compatibility rules;
- the versioned Phase D tailoring policy;
- the structured job description and family-classification evidence.

It may remove at most one approved base project block and insert at most one
explicitly compatible approved block. Whole project blocks may then be
reordered by deterministic score.

## When Tailoring Does Not Occur

The master CV is used unchanged when:

- classification is `low_confidence`;
- no compatible replacement exists;
- the best compatible replacement is below threshold;
- the replacement would duplicate an underlying project;
- the replacement is incompatible or unregistered;
- the tailored TeX is malformed;
- compilation is unavailable or fails;
- the generated PDF is unreadable or not exactly one page.

Close matches keep the selected family as the base and require review.
Low-confidence jobs use the master unchanged and require review.

Requirement-aware cross-family substitutions are conservative. One automatic
substitution is allowed only when the inserted block is eligible for the base
family, the approved compatibility pair is valid, a high-importance
requirement would gain coverage, the gain clears the configured threshold, and
one-page immutable-section validation passes. If a cross-family bridge project
is relevant but the automatic margin is not strong enough, the decision is
recorded as review-required instead of silently changing the packet.

## Thresholds

Thresholds live in `backend/src/jobagent_v2/data/tailoring_policy.json`.

Current policy:

- `minimum_replacement_gain`: `0.15`
- `clear_match_tailoring_gain`: `0.20`
- `dominant_family_margin`: `0.25`

Clear matches are conservative: the fixed master is used unless a compatible
replacement materially improves relevance. Hybrid matches may tailor with one
compatible substitution. Close matches may tailor but stay reviewable.

## Compatibility Rules

Compatibility is explicit in
`backend/src/jobagent_v2/data/project_block_registry.json`. A block is not
eligible merely because it shares keywords or an underlying project name.

The engine rejects:

- more than one substitution;
- incompatible replacement pairs;
- protected or non-base removals;
- unknown or unapproved blocks;
- duplicate underlying projects unless policy explicitly allows them;
- modified block text.

## Scoring

Project selection is separated from base CV-family selection:

1. The family classifier selects the approved master CV that best frames the
   role.
2. The requirement extractor identifies grounded job capabilities such as
   machine learning, quantization, edge AI, NPUs, hardware acceleration, RTL,
   verification, compiler/runtime work, Python, and C++. Deterministic
   extraction is always available; optional semantic requirement extraction can
   add grounded paraphrased requirements only after evidence quotes and
   approved capability names validate.
3. The portfolio scorer evaluates eligible approved project blocks across the
   registry, not only blocks whose home family matches the base CV.

The base family remains the narrative and skills anchor. It is a small scoring
preference for projects, not a hard eligibility boundary. For example, an ML
base CV can shortlist an approved Digital IC home-family bridge project when
the job explicitly values NPUs or ML accelerators.

Only registered approved blocks are scored. The deterministic scorer uses:

- responsibilities;
- domain phrases;
- primary technologies;
- project identifiers and headings;
- family-classifier evidence.

The requirement-aware scorer additionally records requirement coverage,
specificity coverage, bridge bonus, base-family affinity, counterfactual
coverage gain, and shortlist reasons. The score is not a crude total keyword
count. Responsibilities and high-specificity requirements carry more weight
than repeated generic language. If semantic scoring is unavailable, no semantic
rationale is recorded.

High-specificity requirements such as NPUs, ML accelerators, UVM, cache
coherence, quantization, CUDA/kernel optimization, RTL synthesis, and
on-device inference can place matching approved projects on the candidate
shortlist. Shortlisting means "must be evaluated"; it does not force automatic
selection.

Semantic-only requirements use a confidence discount and must clear stronger
grounding/specificity checks. They may improve scores, shortlist a project, or
trigger review, but they cannot force a final project into a CV or bypass
approved compatibility pairs, the one-substitution limit, immutable project
text, or packet validation.

## Reordering

Reordering is allowed only among final whole project blocks. It is
deterministic: blocks sort by descending tailoring relevance, then by stable
registry order and block ID. Education, Experience, and Skills are never
reordered.

## TeX and PDF Validation

Tailored TeX is generated by replacing only the Projects section of the
selected master `.tex`. Header/contact, Education, Experience, coursework, and
Skills remain byte-for-byte identical to the selected master source. Project
fragments are copied from registered approved master fragments.

For tailored candidates the worker:

1. renders candidate TeX in a temporary candidate directory;
2. compiles with the local TeX toolchain when available;
3. verifies the PDF is readable and exactly one page;
4. verifies immutable sections are unchanged;
5. verifies final project fragments match approved registry content;
6. promotes the candidate to packet artifacts only after validation.

If validation fails, the approved master `.tex` and `.pdf` remain the packet
outputs.

## Audit Records

Every packet for a registered master family writes a tailoring audit record,
including master-unchanged decisions. Records are persisted in SQLite
`job_tailoring_decisions` and written to `tailoring_decision.json` in the packet
artifact directory.

The audit includes:

- job ID and packet ID;
- base family and classifier version;
- classification decision;
- base and final block IDs;
- removed and inserted block IDs;
- block scores and evidence;
- replacement gain;
- review flag;
- tailoring status;
- fallback reason;
- Phase D policy version;
- project-registry schema and policy versions.
- extracted requirements and role dimensions when requirement-aware analysis
  was available;
- candidate project scores, shortlist reasons, and counterfactual gain for
  requirement-aware portfolio decisions.

Statuses include `master_unchanged`, `tailored`, `review_required`,
`fallback_to_master`, and `tailoring_rejected`.

## Reviewed Regeneration

Phase H consumes reviewed resolutions without adding new tailoring freedom.
The regeneration worker accepts only:

- a reviewed family master unchanged;
- the reviewed approved final block order from an existing tailoring decision;
- one explicitly compatible approved replacement;
- a reviewed instruction to use the master unchanged.

Deferred and out-of-scope reviews do not generate a packet. The worker
revalidates the reviewed family, block IDs, duplicate underlying projects,
one-substitution limit, registry version, and tailoring-policy version at
execution time. Conservative failure is preferred over silently substituting a
different family or project block after version drift.

Reviewed packets are written as new packet artifacts linked to the source
packet and review resolution. Prior valid packets are not overwritten or
deleted.

## Immutable Guarantees

The tailoring engine never rewrites, shortens, merges, splits, or generates
bullets. It never edits skills, education, experience, coursework, or
header/contact information. Approved master files in `master-cvs/` are not
modified; tailored artifacts are written only under generated packet output
directories.
