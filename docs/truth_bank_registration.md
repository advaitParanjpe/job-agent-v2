# Canonical Truth-Bank Registration

Phase 6A defines the local contract for registering real canonical CV families.
It does not provide real personal CV content. Use only user-approved canonical
resume/CV material when creating `registered` truth banks.

## Location

The current configured family file is:

```text
backend/src/jobagent_v2/data/cv_families.json
```

Each enabled family points to a truth-bank JSON file under:

```text
backend/src/jobagent_v2/data/truth_banks/
```

The bundled files in that directory are marked:

```json
"content_class": "starter_fixture"
```

Starter fixtures are allowed for deterministic development and tests only. They
are rejected by the registration validator unless the caller explicitly enables
starter-fixture mode.

## Required Truth-Bank Fields

Each real registered truth bank must be a JSON object with:

```json
{
  "family_id": "hardware_rtl",
  "version": "2026.06",
  "schema_version": "phase6a-truth-bank-v1",
  "content_class": "registered",
  "header": {
    "name": "Approved display name",
    "contact": "Approved contact line"
  },
  "education": ["Approved canonical education line"],
  "skill_groups": [
    {"name": "RTL", "skills": ["rtl", "systemverilog"]}
  ],
  "blocks": [
    {
      "id": "stable_block_id",
      "type": "experience",
      "name": "Approved block name",
      "canonical_text": "Approved canonical text.",
      "bullets": ["Approved canonical bullet."],
      "technologies": ["rtl"],
      "domains": ["semiconductor"],
      "metrics": [],
      "provenance": "Approved source document or review record",
      "is_required": true
    }
  ]
}
```

Supported block types are `experience` and `project`. Each block ID must be
unique and stable. Each block must declare `is_required` or `is_optional`.

## Validation Guarantees

`jobagent_v2.truth_banks.validate_truth_bank` rejects:

- family/version/schema mismatches;
- `starter_fixture` content when registering real data;
- missing header, contact, or education content;
- duplicate block IDs;
- unsupported block types;
- missing canonical text or bullets;
- missing technologies, domains, or provenance;
- obvious placeholder profile text such as `Candidate`, `placeholder`, or
  `Contact details maintained...`.

`jobagent_v2.scoring.load_truth_bank` uses the same schema validator but allows
the bundled starter fixtures explicitly so existing deterministic tests and dev
paths remain runnable.

## Preview And Discovery

Use `jobagent_v2.scoring.preview_truth_banks()` to list configured family
previews without rendering packets. The preview includes:

```text
family_id
display_name
family_version
truth_bank_path
validation_status
validation_errors
truth_bank_version
schema_version
content_class
blocks: id, type, name, required
```

By default, starter fixtures appear as invalid for registration. Pass
`allow_starter=True` only for development/test inspection.

## Content Rule

Do not invent personal resume facts, achievements, metrics, dates, employers,
schools, skills, or claims. If approved canonical material is unavailable,
Phase 6A is complete once the registration and validation mechanism is working;
creating real family content belongs to Phase 6B.
