# Phase 3C Live LLM Provider Transport

## Objective

Connect the existing semantic-assessment client to the official OpenAI Responses
SDK while preserving Phase 3B's deterministic final score and recommendation.

## Provider Transport Design

`SemanticLLMClient` now defaults to `openai_structured_transport` when no test
transport is injected. The transport creates an OpenAI client from the existing
environment configuration, sets SDK retries to zero, and relies on the existing
client retry loop for bounded retry behavior. It requests `json_schema` output
with `strict: true`, parses JSON, and leaves semantic validation to the existing
Phase 3B schema validator.

The provider sees only the semantic prompt. It cannot return a final score,
recommendation, section score, or promotion decision. Hybrid and deterministic
aggregation remain unchanged.

## Configuration

`.env.example` documents:

```text
JOBAGENT_LLM_ENABLED
JOBAGENT_LLM_API_KEY
JOBAGENT_LLM_MODEL
JOBAGENT_LLM_TIMEOUT_SECONDS
JOBAGENT_LLM_RETRY_COUNT
```

The repository ignores `.env` files. No key is logged or persisted. The default
model is `gpt-4o-mini`; an explicit configured model is always used when set.

## Files Changed

- `backend/src/jobagent_v2/llm_client.py`
- `backend/tests/unit/test_openai_transport.py`
- `scripts/live_llm_smoke.py`
- `.env.example`, `.gitignore`, `pyproject.toml`
- `docs/phase_1_api.md`
- `docs/build_reports/phase_3c_live_llm_transport.md`

## Tests

Offline tests cover provider request construction, strict schema request shape,
response parsing, malformed output, missing key, timeout/provider errors, retry
exhaustion, and mocked live-compatible success. Existing fallback tests remain.
No default test makes a network request.

Commands run:

```text
python3 -m pytest backend/tests/unit/test_openai_transport.py backend/tests/unit/test_hybrid_scoring.py
python3 scripts/check.py
```

## Explicit Live Smoke Test

```bash
export JOBAGENT_LLM_ENABLED=true
export JOBAGENT_LLM_API_KEY='your-local-key'
export JOBAGENT_LLM_MODEL=gpt-4o-mini
export JOBAGENT_LLM_TIMEOUT_SECONDS=10
export JOBAGENT_LLM_RETRY_COUNT=1
PYTHONPATH=backend/src python3 scripts/live_llm_smoke.py --live
```

The script makes exactly one semantic request only when `--live` is supplied.
It prints mode, status, model, prompt version, and final deterministic score;
it never prints the API key.

## Known Limitations

- No real credentialed smoke test was run in this environment.
- Provider/model availability and billing remain an operator responsibility.
- Human review of the live semantic quality and ten-job comparison is still
  required before readiness.
- Phase 4 promotion, scheduling, and packet generation remain unimplemented.

PHASE BLOCKED — HUMAN DECISION REQUIRED
