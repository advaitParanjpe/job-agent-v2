from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobagent_v2.master_cvs import discover_master_cvs
from jobagent_v2.service import JobService
from jobagent_v2.workers import DummyQ1Worker, DummyQ2Worker


def test_q2_generates_truthful_packet_and_is_idempotent(
    service: JobService, repository, artifact_root: Path, created_job
) -> None:
    scored = DummyQ1Worker(repository).process_next()
    assert scored is not None and scored["intake_status"] == "scored"
    classification = repository.get_family_classification(str(created_job["id"]))
    assert classification is not None
    assert classification["selected_family"] == "digital_ic"
    assert classification["decision"] in {"clear_match", "hybrid_match"}
    assert set(classification["family_scores"]) == {
        "digital_ic", "verification", "software", "ml",
    }
    assert scored["overall_score"] is not None
    assert scored["family_classification"]["selected_family"] == "digital_ic"
    service.generate_now(str(created_job["id"]))

    result = DummyQ2Worker(repository, artifact_root).process_next()
    assert result is not None and result["packet_status"] == "ready"
    packet = service.get_packet_for_job(str(created_job["id"]))["packet"]
    assert packet is not None and packet["status"] == "ready"
    assert Path(packet["pdf_path"]).read_bytes().startswith(b"%PDF")
    master = {record.family_id: record for record in discover_master_cvs()}["digital_ic"]
    assert Path(packet["pdf_path"]).read_bytes() == Path(master.pdf_path).read_bytes()
    assert Path(packet["tex_path"]).read_text(encoding="utf-8") == Path(
        master.tex_path
    ).read_text(encoding="utf-8")
    manifest = json.loads(Path(packet["manifest_path"]).read_text(encoding="utf-8"))
    selected = json.loads(Path(packet["selected_cv_path"]).read_text(encoding="utf-8"))
    assert manifest["section_order"] == selected["section_order"]
    assert manifest["master_cv"]["family_id"] == "digital_ic"
    assert manifest["immutable"] is True
    assert selected["source"] == "approved_master_cv"
    assert selected["dynamic_skills_allowed"] is False
    assert DummyQ2Worker(repository, artifact_root).process_next() is None


def test_missing_persisted_scoring_input_fails_visibly(
    service: JobService, repository, artifact_root: Path
) -> None:
    created = service.create_job({
        "url": "https://example.com/jobs/missing-packet-input",
        "page_title": "RTL Engineer",
        "visible_text": "Responsibilities\nRTL\nQualifications\nVerilog",
        "source_site": "example.com", "captured_at": "2026-06-20T12:00:00Z",
    })
    job_id = str(created["job_id"])
    with repository.connect() as connection:
        repository._update_job(connection, job_id, {"intake_status": "scored", "overall_score": 90,
                                                     "hard_blockers_json": "[]"})
    service.generate_now(job_id)
    result = DummyQ2Worker(repository, artifact_root).process_next()
    assert result is not None and result["packet_status"] == "failed"
    packet = service.get_packet_for_job(job_id)["packet"]
    assert packet is not None and packet["failure_stage"] == "validate_inputs"


def test_q2_generates_one_block_tailored_packet_with_audit(
    service: JobService, repository, artifact_root: Path, monkeypatch
) -> None:
    master = {record.family_id: record for record in discover_master_cvs()}["digital_ic"]
    master_tex_before = Path(master.tex_path).read_text(encoding="utf-8")
    master_pdf_before = Path(master.pdf_path).read_bytes()
    created = service.create_job({
        "url": "https://example.com/jobs/digital-ic-ml-hybrid",
        "page_title": "RTL ML Accelerator Engineer",
        "visible_text": (
            "RTL ML Accelerator Engineer\n"
            "Responsibilities\n"
            "Design RTL accelerators for machine learning inference and quantized sparse "
            "vector execution.\n"
            "Qualifications\n"
            "SystemVerilog Python C PyTorch quantization inference."
        ),
        "source_site": "example.com",
        "captured_at": "2026-06-20T12:00:00Z",
    })
    job_id = str(created["job_id"])
    classification = {
        "decision": "hybrid_match",
        "requires_review": False,
        "classifier_version": "phase-b-family-classifier-v1",
        "config_version": "phase-b-family-classifier-config-v1",
        "family_scores": {
            "digital_ic": 0.45, "verification": 0.1, "software": 0.1, "ml": 0.35,
        },
        "selected_family": "digital_ic",
        "secondary_family": "ml",
        "confidence": 0.45,
        "rule_evidence": [
            {
                "family": "ml", "section": "responsibility",
                "phrase": "machine learning inference", "polarity": "positive",
            }
        ],
        "semantic_evidence": [],
        "deterministic_scores": {
            "digital_ic": 0.45, "verification": 0.1, "software": 0.1, "ml": 0.35,
        },
        "semantic_scores": None,
    }
    structured = {
        "title": "RTL ML Accelerator Engineer",
        "responsibilities": [
            "Design RTL accelerators for machine learning inference and quantized sparse "
            "vector execution"
        ],
        "must_have_requirements": [
            "SystemVerilog Python C PyTorch quantization inference"
        ],
        "nice_to_have_requirements": [],
        "skills": ["systemverilog", "python", "c", "pytorch", "quantization", "inference"],
        "technologies": [
            "systemverilog", "python", "c", "pytorch", "quantization", "inference",
        ],
        "domains": ["ai"],
        "keywords": ["rtl", "accelerator", "machine learning", "sparse"],
    }
    with repository.connect() as connection:
        repository._update_job(connection, job_id, {
            "intake_status": "scored",
            "overall_score": 88,
            "hard_blockers_json": "[]",
            "selected_cv_family": "digital_ic",
            "secondary_cv_family": "ml",
            "cv_family_confidence": "medium",
            "scoring_version": "phase3-deterministic-v1",
            "structured_jd_json": json.dumps(structured, sort_keys=True),
            "family_classification_json": json.dumps(classification, sort_keys=True),
            "family_classifier_version": "phase-b-family-classifier-v1",
            "family_classification_decision": "hybrid_match",
            "family_classification_requires_review": 0,
        })

    def fake_compile(tex: str, output_dir: Path, timeout_seconds: int = 30):
        pdf = output_dir / "cv.pdf"
        pdf.write_bytes(b"%PDF tailored")
        return pdf, "fake tailored compile", 1

    monkeypatch.setattr("jobagent_v2.tailoring.compile_pdf", fake_compile)
    service.generate_now(job_id)
    result = DummyQ2Worker(repository, artifact_root).process_next()

    assert result is not None and result["packet_status"] == "ready"
    packet = service.get_packet_for_job(job_id)["packet"]
    assert packet is not None
    assert Path(packet["pdf_path"]).read_bytes() == b"%PDF tailored"
    assert packet["tailoring_decision_path"]
    decision = json.loads(Path(packet["tailoring_decision_path"]).read_text(encoding="utf-8"))
    assert decision["tailoring_status"] == "tailored"
    assert decision["removed_block"] == "sparrow_cluster_digital_ic_v1"
    assert decision["inserted_block"] == "sparrowml_ml_v1"
    persisted = repository.get_tailoring_decision(job_id)
    assert persisted is not None
    assert persisted["decision"]["final_order"] == decision["final_order"]
    manifest = json.loads(Path(packet["manifest_path"]).read_text(encoding="utf-8"))
    selected = json.loads(Path(packet["selected_cv_path"]).read_text(encoding="utf-8"))
    assert manifest["tailoring"]["tailoring_status"] == "tailored"
    assert selected["project_blocks"]["final_blocks"] == decision["final_order"]
    assert "SparrowML" in Path(packet["tex_path"]).read_text(encoding="utf-8")
    assert Path(master.tex_path).read_text(encoding="utf-8") == master_tex_before
    assert Path(master.pdf_path).read_bytes() == master_pdf_before


@pytest.mark.parametrize(
    ("family", "title", "text"),
    [
        (
            "digital_ic",
            "RTL Design Engineer",
            "Responsibilities\nImplement SystemVerilog RTL and microarchitecture.",
        ),
        (
            "verification",
            "Design Verification Engineer",
            "Responsibilities\nBuild UVM testbenches, SVA, scoreboards, and coverage.",
        ),
        (
            "software",
            "Backend Software Engineer",
            "Responsibilities\nBuild backend APIs, databases, and distributed systems.",
        ),
        (
            "ml",
            "Machine Learning Engineer",
            "Responsibilities\nTrain PyTorch models and evaluate inference quality.",
        ),
    ],
)
def test_classified_family_copies_matching_registered_master(
    service: JobService,
    repository,
    artifact_root: Path,
    family: str,
    title: str,
    text: str,
) -> None:
    created = service.create_job({
        "url": f"https://example.com/jobs/{family}",
        "page_title": title,
        "visible_text": f"{title}\nLocation: Austin, TX\n{text}\nQualifications\nRelevant degree.",
        "source_site": "example.com",
        "captured_at": "2026-06-20T12:00:00Z",
    })
    scored = DummyQ1Worker(repository).process_next()
    assert scored is not None and scored["selected_cv_family"] == family

    service.generate_now(str(created["job_id"]))
    result = DummyQ2Worker(repository, artifact_root).process_next()

    assert result is not None and result["packet_status"] == "ready"
    packet = service.get_packet_for_job(str(created["job_id"]))["packet"]
    assert packet is not None
    master = {record.family_id: record for record in discover_master_cvs()}[family]
    assert Path(packet["pdf_path"]).read_bytes() == Path(master.pdf_path).read_bytes()
    assert Path(packet["tex_path"]).read_text(encoding="utf-8") == Path(
        master.tex_path
    ).read_text(encoding="utf-8")
