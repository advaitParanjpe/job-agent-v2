from __future__ import annotations

from jobagent_v2.hybrid_scoring import score_hybrid_job
from jobagent_v2.llm_client import LLMConfig, SemanticLLMClient
from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository


def test_hybrid_result_persists_semantic_diagnostics(
    service: JobService, repository: Repository
) -> None:
    created = service.create_job({
        "url": "https://example.com/hybrid",
        "page_title": "RTL Engineer - Acme",
        "visible_text": "Responsibilities\nDesign SystemVerilog RTL ASIC products.\n"
        "Qualifications\nVerilog SystemVerilog RTL ASIC Python semiconductor.",
        "source_site": "example.com", "captured_at": "2026-06-19T12:00:00Z",
    })
    job = repository.get_job(str(created["job_id"]))
    job.update({
        "jd_text": "Responsibilities\nSystemVerilog RTL ASIC.\n"
        "Qualifications\nVerilog Python."
    })
    result = score_hybrid_job(
        job,
        SemanticLLMClient(LLMConfig(False, None, "fake-model", 1, 0)),
    )
    repository.save_scoring_result(str(created["job_id"]), result)

    score = service.get_score(str(created["job_id"]))["score"]
    semantic = service.get_semantic_assessment(str(created["job_id"]))["semantic_assessment"]
    assert score is not None and score["semantic_assessment"] is not None
    assert semantic is not None
    assert semantic["scoring_mode"] == "deterministic_only"
