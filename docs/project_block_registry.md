# Project-Block Registry and Policy

Phase C defines approved whole-project blocks for future bounded tailoring. It
does not activate production packet substitution.

## Registry Schema

The registry lives at:

```text
backend/src/jobagent_v2/data/project_block_registry.json
```

It uses:

- `schema_version`: `project-block-registry-v1`
- `policy_version`: `phase-c-project-tailoring-policy-v1`

Each block records:

- stable `block_id`
- stable underlying `project_id`
- display name
- family and explicit eligible families
- approval and immutability flags
- source master family
- exact heading, subtitle, dates, and bullets
- tags
- render budget
- evidence references
- content hash

The implementation in `backend/src/jobagent_v2/project_blocks.py` extracts the
project section from the approved master `.tex` files and validates the registry
against that source.

## Approved Inventory

Digital IC:

- `tinynpu_digital_ic_v1`
- `sparrow_v_digital_ic_v1`
- `sparrow_cluster_digital_ic_v1`

Verification:

- `axi4_stream_packet_router_verification_v1`
- `agentic_rtl_security_verification_v1`
- `sparrow_v_verification_v1`

Software:

- `jobagent_software_v1`
- `agentic_rtl_security_discovery_software_v1`
- `sparrowml_software_v1`

Machine Learning:

- `dementia_speech_classification_ml_v1`
- `sparrowml_ml_v1`
- `speakup_ml_v1`

Family-specific variants are intentionally separate. For example,
`sparrowml_software_v1` and `sparrowml_ml_v1` share an underlying project but
have different approved wording and emphasis.

## Immutable Content Rules

The system must not dynamically modify:

- header/contact information
- education
- experience
- coursework
- family-specific skills
- wording inside approved project blocks

Project blocks are complete units. The agent must not rewrite, shorten, merge,
split, or generate bullets.

## Validation Rules

Registry validation rejects:

- duplicate block IDs
- duplicate content under conflicting IDs
- unknown families
- missing bullets
- unapproved or mutable blocks
- forbidden section content from Education, Experience, Skills, or header areas
- unsupported dynamic placeholders
- malformed LaTeX fragments
- unregistered master project blocks
- registry text that does not exactly match the approved master source
- content hash drift
- oversized blocks
- invalid compatibility rules
- invalid future tailoring decision records

The approved master CVs remain the source of truth. If a master project block is
edited, registry validation fails until the registry is deliberately updated.

## Render Budget

Phase C uses a deterministic conservative rendered-line estimate:

- one heading line
- bullet lines estimated from plain-text length and configured characters per
  rendered line

This is not source-line counting. It is a stable offline guardrail until Phase D
adds packet-level compile and one-page validation for an actual bounded variant.

Environment-dependent TeX compile checks remain optional and skip when the local
LaTeX toolchain is incomplete.

## Substitution Policy

Initial policy:

- `maximum_project_substitutions`: `1`
- `bullet_rewriting_allowed`: `false`
- `project_block_editing_allowed`: `false`
- `dynamic_skills_allowed`: `false`
- `education_editing_allowed`: `false`
- `experience_editing_allowed`: `false`
- `project_reordering_allowed`: `true`

Compatibility is explicit. A block is not eligible merely because it shares a
project name or technologies.

Current examples:

- `sparrowml_ml_v1` may be reviewed as a crossover replacement for
  `sparrow_cluster_digital_ic_v1` in a hybrid Digital IC/ML role.
- `sparrow_v_verification_v1` may replace
  `agentic_rtl_security_verification_v1` within the Verification family.
- `jobagent_software_v1` remains Software-family content.
- `dementia_speech_classification_ml_v1` remains ML-family content.

## Audit Record

Future tailoring decisions must reference approved block IDs only. The validator
supports this shape:

```json
{
  "base_family": "digital_ic",
  "base_blocks": [
    "tinynpu_digital_ic_v1",
    "sparrow_v_digital_ic_v1",
    "sparrow_cluster_digital_ic_v1"
  ],
  "removed_block": "sparrow_cluster_digital_ic_v1",
  "inserted_block": "sparrowml_ml_v1",
  "final_order": [
    "tinynpu_digital_ic_v1",
    "sparrow_v_digital_ic_v1",
    "sparrowml_ml_v1"
  ],
  "reason": "Hybrid Digital IC/ML role evidence.",
  "job_evidence": [],
  "requires_review": true,
  "policy_version": "phase-c-project-tailoring-policy-v1"
}
```

Arbitrary replacement text is not accepted.

## Current Limitation

Production packet generation still copies the selected approved master CV
unchanged. Phase D should consume the registry and classification output,
evaluate approved compatible blocks, permit at most one substitution, optionally
reorder whole blocks, compile the result, verify one-page output, and write the
audit record.
