"""Explicit semantic requirement diagnostic that never writes to the jobs database."""

from __future__ import annotations

import argparse
import json
import os
from time import perf_counter
from typing import Any

from jobagent_v2.config import RuntimeConfig, load_local_env
from jobagent_v2.requirements import extract_requirements


SEMANTIC_REQUIREMENTS_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["role_dimensions", "requirements", "cross_domain_summary"],
    "properties": {
        "role_dimensions": {
            "type": "object",
            "additionalProperties": {"type": "number"},
        },
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "requirement_text",
                    "normalized_capabilities",
                    "importance",
                    "specificity",
                    "required_or_preferred",
                    "evidence_quote",
                    "concise_reason",
                ],
                "properties": {
                    "requirement_text": {"type": "string"},
                    "normalized_capabilities": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "importance": {"type": "number", "minimum": 0, "maximum": 1},
                    "specificity": {"type": "number", "minimum": 0, "maximum": 1},
                    "required_or_preferred": {"type": "string"},
                    "evidence_quote": {"type": "string"},
                    "concise_reason": {"type": "string"},
                },
            },
        },
        "cross_domain_summary": {"type": "string"},
    },
}


SYNTHETIC_JOB = {
    "id": "semantic-requirements-diagnostic",
    "selected_cv_family": "ml",
    "title": "Machine Learning Runtime Engineer",
    "jd_text": (
        "Responsibilities: deploy efficient inference on constrained devices, "
        "optimize models for heterogeneous compute targets, partner with accelerator "
        "architecture teams, and improve inference latency across CPU, GPU, and "
        "accelerator backends."
    ),
    "structured_jd": {
        "title": "Machine Learning Runtime Engineer",
        "responsibilities": [
            "Deploy efficient inference on constrained devices",
            "Optimize models for heterogeneous compute targets",
            "Partner with accelerator architecture teams",
            "Improve inference latency across CPU, GPU, and accelerator backends",
        ],
        "must_have_requirements": ["Python and PyTorch deployment experience"],
        "nice_to_have_requirements": [],
        "skills": ["Python", "PyTorch"],
        "technologies": ["PyTorch"],
        "domains": ["machine learning"],
        "keywords": ["inference", "runtime"],
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one explicit semantic requirement extraction diagnostic."
    )
    parser.add_argument("--no-network", action="store_true", help="Use deterministic fake mode.")
    args = parser.parse_args(argv)
    load_local_env()
    runtime = RuntimeConfig.from_env()
    if args.no_network:
        provider = _fake_provider
        enabled = True
        simulated = True
    else:
        if not runtime.semantic_enabled:
            print("Semantic requirement check failed: JOBAGENT_LLM_ENABLED=false.")
            return 1
        if not runtime.semantic_api_key_present:
            print(
                "Semantic requirement check failed: JOBAGENT_LLM_API_KEY is missing. "
                "The key was not printed."
            )
            return 1
        print("This command sends one provider request and may incur provider cost.")
        provider = _live_provider(runtime.semantic_model)
        enabled = True
        simulated = False
    start = perf_counter()
    analysis = extract_requirements(
        SYNTHETIC_JOB,
        semantic_provider=provider,
        semantic_enabled=enabled,
    )
    elapsed = round((perf_counter() - start) * 1000)
    semantic = analysis["semantic_requirements"]
    metadata = semantic["metadata"]
    status = (
        "simulated_success"
        if simulated and semantic["status"] == "live_success"
        else semantic["status"]
    )
    print(f"status: {status}")
    print(f"model: {metadata.get('model')}")
    print(f"latency_ms: {metadata.get('latency_ms') or elapsed}")
    print(f"accepted_semantic_requirements: {metadata.get('accepted_count')}")
    print(f"rejected_requirement_count: {metadata.get('rejected_count')}")
    caps = sorted({
        cap
        for requirement in semantic.get("accepted_requirements", [])
        for cap in requirement.get("normalized_capabilities", [])
    })
    print(f"normalized_capabilities: {', '.join(caps) if caps else 'none'}")
    return 0 if status in {"simulated_success", "live_success"} else 1


def _fake_provider(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "role_dimensions": {
            "machine_learning": 0.8,
            "edge_ai": 0.76,
            "hardware_acceleration": 0.74,
            "compiler_runtime": 0.62,
        },
        "requirements": [
            {
                "requirement_text": "Deploy efficient inference on constrained devices",
                "normalized_capabilities": [
                    "edge_ai",
                    "on_device_inference",
                    "performance_optimization",
                ],
                "importance": 0.82,
                "specificity": 0.78,
                "required_or_preferred": "responsibility",
                "evidence_quote": "deploy efficient inference on constrained devices",
                "concise_reason": "Grounded edge deployment and latency requirement.",
            },
            {
                "requirement_text": "Work with accelerator architecture teams",
                "normalized_capabilities": ["hardware_acceleration", "ml_accelerator"],
                "importance": 0.76,
                "specificity": 0.72,
                "required_or_preferred": "responsibility",
                "evidence_quote": "partner with accelerator architecture teams",
                "concise_reason": "Grounded collaboration with accelerator architecture.",
            },
        ],
        "cross_domain_summary": (
            "The role combines ML deployment with hardware-aware runtime optimization."
        ),
    }


def _live_provider(model: str):
    def provider(prompt: dict[str, Any]) -> dict[str, Any]:
        try:
            from openai import APIError, APITimeoutError, OpenAI
        except ImportError as error:
            raise ValueError("OpenAI SDK is not installed") from error
        try:
            client = OpenAI(
                api_key=os.getenv("JOBAGENT_LLM_API_KEY"),
                timeout=float(os.getenv("JOBAGENT_LLM_TIMEOUT_SECONDS", "10")),
                max_retries=0,
            )
            response = client.responses.create(
                model=model,
                instructions=(
                    "Extract only grounded technical requirements from the supplied job. "
                    "Use exact evidence_quote text from the job. Use only approved "
                    "capability names from approved_capabilities."
                ),
                input=json.dumps(prompt, sort_keys=True),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "jobagent_semantic_requirements",
                        "strict": True,
                        "schema": SEMANTIC_REQUIREMENTS_OUTPUT_SCHEMA,
                    }
                },
            )
        except APITimeoutError as error:
            raise TimeoutError("OpenAI request timed out") from error
        except APIError as error:
            raise ValueError("OpenAI provider request failed") from error
        output_text = getattr(response, "output_text", "")
        if not isinstance(output_text, str) or not output_text.strip():
            raise ValueError("OpenAI response did not contain structured output")
        return json.loads(output_text)

    return provider


if __name__ == "__main__":
    raise SystemExit(main())
