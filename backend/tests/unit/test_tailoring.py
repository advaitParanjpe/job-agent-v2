from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from jobagent_v2.master_cvs import discover_master_cvs
from jobagent_v2.packets import PacketGenerationError
from jobagent_v2.project_blocks import (
    ProjectBlockRegistryError,
    load_project_block_registry,
    validate_replacement_pair,
)
from jobagent_v2.tailoring import (
    TailoringError,
    evaluate_tailoring,
    load_tailoring_policy,
    render_tailored_tex,
    select_tailoring_decision,
    validate_tailored_tex,
)


def _job(decision: str = "hybrid_match") -> dict[str, object]:
    return {
        "id": "job-1",
        "selected_cv_family": "digital_ic",
        "title": "RTL ML Accelerator Engineer",
        "jd_text": (
            "Responsibilities Design RTL accelerators for machine learning inference, "
            "PyTorch quantization, edge ML compiler runtime, and sparse vector execution. "
            "Qualifications SystemVerilog Python C PyTorch quantization inference."
        ),
        "structured_jd": {
            "title": "RTL ML Accelerator Engineer",
            "responsibilities": [
                "Design RTL accelerators for machine learning inference and quantized "
                "sparse vector execution"
            ],
            "must_have_requirements": [
                "SystemVerilog Python C PyTorch quantization inference"
            ],
            "nice_to_have_requirements": [],
            "skills": [
                "systemverilog", "python", "c", "pytorch", "quantization", "inference",
            ],
            "technologies": [
                "systemverilog", "python", "c", "pytorch", "quantization", "inference",
            ],
            "domains": ["ai"],
            "keywords": ["rtl", "accelerator", "machine learning", "sparse"],
        },
        "family_classification": {
            "decision": decision,
            "requires_review": decision in {"close_match", "low_confidence"},
            "classifier_version": "phase-b-family-classifier-v1",
            "family_scores": {
                "digital_ic": 0.45,
                "ml": 0.35,
                "software": 0.1,
                "verification": 0.1,
            },
            "rule_evidence": [
                {
                    "family": "ml",
                    "section": "responsibility",
                    "phrase": "machine learning inference",
                    "polarity": "positive",
                }
            ],
        },
    }


def test_low_confidence_uses_master_and_requires_review() -> None:
    decision = select_tailoring_decision(
        packet_id="packet-1",
        job=_job("low_confidence"),
        base_family="digital_ic",
        registry=load_project_block_registry(),
        policy=load_tailoring_policy(),
    )

    assert decision["tailoring_status"] == "review_required"
    assert decision["removed_block"] is None
    assert decision["inserted_block"] is None
    assert decision["requires_review"] is True


def test_digital_ic_ml_hybrid_replaces_one_compatible_block() -> None:
    decision = select_tailoring_decision(
        packet_id="packet-1",
        job=_job("hybrid_match"),
        base_family="digital_ic",
        registry=load_project_block_registry(),
        policy=load_tailoring_policy(),
    )

    assert decision["tailoring_status"] == "tailored"
    assert decision["removed_block"] == "sparrow_cluster_digital_ic_v1"
    assert decision["inserted_block"] == "sparrowml_ml_v1"
    assert len(set(decision["base_blocks"]) - set(decision["final_order"])) == 1
    assert len(set(decision["final_order"]) - set(decision["base_blocks"])) == 1
    assert decision["requires_review"] is True
    assert decision["replacement_gain"] >= 0.15


def test_reordering_is_deterministic_and_preserves_registered_text() -> None:
    registry = load_project_block_registry()
    decision = select_tailoring_decision(
        packet_id="packet-1",
        job=_job("hybrid_match"),
        base_family="digital_ic",
        registry=registry,
        policy=load_tailoring_policy(),
    )
    master = {item.family_id: item for item in discover_master_cvs()}["digital_ic"]

    tex = render_tailored_tex(
        Path(master.tex_path).read_text(encoding="utf-8"),
        decision["final_order"],
        registry,
    )

    assert decision["final_order"][0] == "sparrowml_ml_v1"
    validate_tailored_tex(
        tex,
        master_tex_path=master.tex_path,
        decision=decision,
        registry=registry,
    )


def test_invalid_substitution_and_modified_bullet_are_rejected() -> None:
    registry = load_project_block_registry()
    with pytest.raises(ProjectBlockRegistryError):
        validate_replacement_pair(
            "digital_ic",
            "tinynpu_digital_ic_v1",
            "jobagent_software_v1",
            registry,
        )
    decision = select_tailoring_decision(
        packet_id="packet-1",
        job=_job("hybrid_match"),
        base_family="digital_ic",
        registry=registry,
        policy=load_tailoring_policy(),
    )
    master = {item.family_id: item for item in discover_master_cvs()}["digital_ic"]
    tex = render_tailored_tex(
        Path(master.tex_path).read_text(encoding="utf-8"),
        decision["final_order"],
        registry,
    ).replace("INT8 quantization", "INT8 quantization and rewritten claims")

    with pytest.raises(TailoringError):
        validate_tailored_tex(
            tex,
            master_tex_path=master.tex_path,
            decision=decision,
            registry=registry,
        )


def test_tailored_compile_success_and_compile_unavailable_fallback(tmp_path, monkeypatch) -> None:
    master = {item.family_id: item for item in discover_master_cvs()}["digital_ic"]
    output = tmp_path / "packet"
    output.mkdir()
    shutil.copy2(master.tex_path, output / "cv.tex")
    shutil.copy2(master.pdf_path, output / "cv.pdf")

    def fake_compile(tex: str, output_dir: Path, timeout_seconds: int = 30):
        pdf = output_dir / "cv.pdf"
        pdf.write_bytes(b"%PDF fake tailored")
        return pdf, "fake compile", 1

    monkeypatch.setattr("jobagent_v2.tailoring.compile_pdf", fake_compile)
    result = evaluate_tailoring(
        packet_id="packet-1",
        job=_job("hybrid_match"),
        output_dir=output,
        master_tex_path=output / "cv.tex",
        master_pdf_path=output / "cv.pdf",
    )
    assert result.used_tailored_output is True
    assert result.decision["tailoring_status"] == "tailored"
    assert (output / "cv.pdf").read_bytes().startswith(b"%PDF fake tailored")

    def unavailable(tex: str, output_dir: Path, timeout_seconds: int = 30):
        raise PacketGenerationError("compile", "pdflatex is unavailable")

    fallback_output = tmp_path / "fallback"
    fallback_output.mkdir()
    shutil.copy2(master.tex_path, fallback_output / "cv.tex")
    shutil.copy2(master.pdf_path, fallback_output / "cv.pdf")
    monkeypatch.setattr("jobagent_v2.tailoring.compile_pdf", unavailable)
    fallback = evaluate_tailoring(
        packet_id="packet-2",
        job=_job("hybrid_match"),
        output_dir=fallback_output,
        master_tex_path=fallback_output / "cv.tex",
        master_pdf_path=fallback_output / "cv.pdf",
    )

    assert fallback.used_tailored_output is False
    assert fallback.decision["tailoring_status"] == "fallback_to_master"
    assert "pdflatex is unavailable" in fallback.decision["fallback_reason"]
    assert (fallback_output / "cv.tex").read_text(encoding="utf-8") == Path(
        master.tex_path
    ).read_text(encoding="utf-8")
