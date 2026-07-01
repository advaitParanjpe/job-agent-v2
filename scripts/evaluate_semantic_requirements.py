from __future__ import annotations

from jobagent_v2.requirements import extract_requirements


FIXTURES = [
    (
        "heterogeneous-compute",
        "Optimize models for heterogeneous compute targets.",
        {"hardware_acceleration", "performance_optimization"},
    ),
    (
        "constrained-inference",
        "Deploy efficient inference on constrained devices.",
        {"edge_ai", "on_device_inference"},
    ),
    (
        "accelerator-architecture",
        "Partner with accelerator architecture teams.",
        {"hardware_acceleration", "ml_accelerator"},
    ),
    (
        "generic-data-science",
        "Analyze datasets and accelerate innovation with product partners.",
        set(),
    ),
    (
        "it-hardware",
        "Manage laptop hardware inventory for office employees.",
        set(),
    ),
    (
        "negated-edge",
        "This role does not deploy efficient inference on constrained devices.",
        set(),
    ),
]


def main() -> int:
    true_positive = 0
    expected_total = 0
    false_positive = 0
    accepted = 0
    rejected = 0
    failures: list[str] = []
    for name, text, expected in FIXTURES:
        analysis = extract_requirements(
            {
                "title": "ML Engineer",
                "jd_text": text,
                "structured_jd": {"responsibilities": [text]},
            },
            semantic_provider=_provider_for(text),
            semantic_enabled=True,
        )
        caps = {
            cap
            for req in analysis["semantic_requirements"]["accepted_requirements"]
            for cap in req["normalized_capabilities"]
        }
        accepted += analysis["semantic_requirements"]["metadata"]["accepted_count"]
        rejected += analysis["semantic_requirements"]["metadata"]["rejected_count"]
        true_positive += len(caps & expected)
        expected_total += len(expected)
        false_positive += len(caps - expected)
        if expected and not caps & expected:
            failures.append(f"{name}: missed expected {sorted(expected)}")
        if not expected and caps:
            failures.append(f"{name}: false positive {sorted(caps)}")
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, expected_total)
    print(f"fixtures: {len(FIXTURES)}")
    print(f"capability_precision: {precision:.3f}")
    print(f"capability_recall: {recall:.3f}")
    print(f"grounded_acceptance_count: {accepted}")
    print(f"unsupported_rejection_count: {rejected}")
    print(f"semantic_only_false_positive_count: {false_positive}")
    print(f"failures: {len(failures)}")
    for failure in failures:
        print(f"- {failure}")
    return 1 if failures else 0


def _provider_for(text: str):
    def provider(_prompt):
        lowered = text.casefold()
        requirements = []
        if "heterogeneous compute" in lowered:
            requirements.append(_req(text, ["hardware_acceleration", "performance_optimization"]))
        if "constrained devices" in lowered and "does not" not in lowered:
            requirements.append(_req(text, ["edge_ai", "on_device_inference"]))
        if "accelerator architecture" in lowered:
            requirements.append(_req(text, ["hardware_acceleration", "ml_accelerator"]))
        if "accelerate innovation" in lowered:
            requirements.append(_req("accelerate innovation", ["hardware_acceleration"]))
        if "laptop hardware" in lowered:
            requirements.append(_req("hardware", ["hardware_acceleration"]))
        if "does not" in lowered:
            requirements.append(
                _req("deploy efficient inference on constrained devices", ["edge_ai"])
            )
        return {"requirements": requirements}
    return provider


def _req(quote: str, caps: list[str]) -> dict[str, object]:
    return {
        "requirement_text": quote,
        "normalized_capabilities": caps,
        "importance": 0.76,
        "specificity": 0.72,
        "required_or_preferred": "responsibility",
        "evidence_quote": quote,
        "concise_reason": "Fixture semantic requirement.",
    }


if __name__ == "__main__":
    raise SystemExit(main())
