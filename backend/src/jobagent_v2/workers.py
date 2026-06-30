"""Deterministic workers for the local queue skeleton."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobagent_v2.intake import intake_result_to_updates, run_intake
from jobagent_v2.hybrid_scoring import score_hybrid_job
from jobagent_v2.promotion import PromotionConfig
from jobagent_v2.scoring import ScoringConfigurationError
from jobagent_v2.storage import Repository
from jobagent_v2.packets import (
    PacketGenerationError,
    build_master_packet_artifacts,
    build_selected_cv,
    compile_pdf,
    family_master_cv,
    render_latex,
    safe_artifact_directory,
    write_json,
)
from jobagent_v2.scoring import load_cv_families
from jobagent_v2.tailoring import evaluate_tailoring
from jobagent_v2.util import utc_now_iso


class Queue1Worker:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def process_next(self) -> dict[str, object] | None:
        job = self.repository.next_job_with_intake_status("queued")
        if job is None:
            return None
        job_id = str(job["id"])
        self.repository.transition_intake(
            job_id,
            "extracting",
            event_type="intake_extracting",
            message="Intake started deterministic JD extraction.",
        )
        result = run_intake(
            page_title=str(job["page_title"]),
            visible_text=str(job["raw_visible_text"]),
            source_site=str(job["source_site"]) if job["source_site"] else None,
            source_url=str(job["source_url"]),
            evidence=job["capture_evidence"] if isinstance(job["capture_evidence"], dict) else {},
        )
        updates = intake_result_to_updates(result)
        self.repository.transition_intake(
            job_id,
            "structuring",
            event_type="intake_structuring",
            message="Intake extracted JD text and diagnostics.",
            updates=updates,
            metadata={
                "quality_band": result.quality.band,
                "warnings": result.warnings,
            },
        )
        if result.quality.band == "failed":
            return self.repository.transition_intake(
                job_id,
                "failed",
                event_type="intake_failed",
                message=result.failure_reason or "Intake failed.",
                metadata={"warnings": result.warnings},
                updates={
                    "reason": result.failure_reason or "Intake failed.",
                    "failure_reason": result.failure_reason,
                },
            )
        if result.quality.band == "manual_review":
            return self.repository.transition_intake(
                job_id,
                "manual_review",
                event_type="intake_manual_review",
                message=result.manual_review_reason or "Intake requires manual review.",
                metadata={"warnings": result.warnings},
                updates={
                    "reason": result.manual_review_reason or "Intake requires manual review.",
                    "manual_review_reason": result.manual_review_reason,
                },
            )
        self.repository.transition_intake(
            job_id,
            "scoring",
            event_type="scoring_started",
            message="Intake complete; deterministic Queue 1 scoring started.",
            metadata={"quality_band": result.quality.band, "warnings": result.warnings},
        )
        return self._score_job(job_id)

    def rescore(self, job_id: str) -> dict[str, object]:
        self.repository.transition_intake(
            job_id, "scoring", event_type="rescore_started", message="Manual rescore started."
        )
        return self._score_job(job_id)

    def _score_job(self, job_id: str) -> dict[str, object]:
        job = self.repository.get_job(job_id)
        try:
            result = score_hybrid_job(job)
            self.repository.save_scoring_result(job_id, result)
        except (ScoringConfigurationError, OSError, ValueError) as error:
            return self.repository.transition_intake(
                job_id,
                "failed",
                event_type="scoring_failed",
                message=str(error),
                updates={
                    "failure_reason": str(error),
                    "reason": "Queue 1 scoring failed.",
                    "scoring_status": "failed",
                },
                metadata={"stage": "job_scoring"},
            )
        final_job = self.repository.transition_intake(
            job_id,
            "scored",
            event_type="job_scored",
            message="Deterministic Queue 1 scoring completed.",
            updates={"scoring_status": "complete"},
            metadata={"scoring_version": result.score_breakdown["formula_version"]},
        )
        duplicate = self.repository.find_probable_duplicate(
            job_id=job_id,
            company=str(job.get("company") or ""), title=str(job.get("title") or ""),
            jd_text_fingerprint=str(job.get("jd_text_fingerprint") or ""),
        )
        if duplicate is not None:
            final_job = self.repository.set_duplicate_warning(
                job_id,
                f"Probable duplicate of job {duplicate['id']}.",
            )
        return final_job


class Queue2Worker:
    def __init__(
        self,
        repository: Repository,
        artifact_root: Path | str,
        config: PromotionConfig | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_root = Path(artifact_root)
        self.config = config or PromotionConfig.from_env()
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def process_next(self) -> dict[str, object] | None:
        expiry = datetime.now(timezone.utc) + timedelta(seconds=self.config.lease_seconds)
        task = self.repository.claim_next_q2_task(
            owner="phase5-packet-worker",
            concurrency=self.config.q2_worker_concurrency,
            lease_expires_at=expiry.isoformat(timespec="seconds"),
        )
        if task is None:
            return None
        task = self.repository.start_q2_task(str(task["id"]))
        job = self.repository.get_job(str(task["job_id"]))
        packet = self.repository.create_packet_attempt(str(task["id"]), str(task["job_id"]))
        packet_id = str(packet["id"])
        directory: Path | None = None
        try:
            directory = safe_artifact_directory(self.artifact_root, str(job["id"]), packet_id)
            directory.mkdir(parents=True, exist_ok=True)
            if not job.get("selected_cv_family") or not job.get("scoring_version"):
                raise PacketGenerationError(
                    "validate_inputs", "job is missing validated scoring inputs"
                )
            family = _selected_family(job)
            if family_master_cv(family):
                master_artifacts = build_master_packet_artifacts(
                    packet_id=packet_id, job=job, family=family, output_dir=directory
                )
                tailoring = evaluate_tailoring(
                    packet_id=packet_id,
                    job=job,
                    output_dir=directory,
                    master_tex_path=master_artifacts.tex_path,
                    master_pdf_path=master_artifacts.pdf_path,
                )
                if tailoring.used_tailored_output:
                    tex_path = tailoring.tex_path or master_artifacts.tex_path
                    pdf_path = tailoring.pdf_path or master_artifacts.pdf_path
                    compile_log = tailoring.compile_log
                    page_count = tailoring.page_count
                    source = "approved_master_cv_with_one_block_tailoring"
                    immutable = False
                else:
                    tex_path = master_artifacts.tex_path
                    pdf_path = master_artifacts.pdf_path
                    compile_log = tailoring.compile_log
                    page_count = master_artifacts.page_count
                    source = "approved_master_cv"
                    immutable = True
                selected_dict = master_artifacts.selected_cv
                selected_dict.update({
                    "source": source,
                    "immutable": immutable,
                    "tailoring": tailoring.decision,
                    "project_blocks": {
                        "base_blocks": tailoring.decision.get("base_blocks", []),
                        "final_blocks": tailoring.decision.get("final_order", []),
                        "removed_block": tailoring.decision.get("removed_block"),
                        "inserted_block": tailoring.decision.get("inserted_block"),
                    },
                })
                tailoring_path = directory / "tailoring_decision.json"
                write_json(tailoring_path, tailoring.decision)
                self.repository.save_tailoring_decision(
                    str(job["id"]), packet_id, tailoring.decision
                )
            else:
                selected = build_selected_cv(
                    packet_id=packet_id, job=job,
                    block_scores=self.repository.list_block_scores(str(job["id"])),
                )
                tex = render_latex(selected)
                tex_path = directory / "cv.tex"
                tex_path.write_text(tex, encoding="utf-8")
                pdf_path, compile_log, page_count = compile_pdf(tex, directory)
                selected_dict = selected.to_dict()
                tailoring_path = None
            selected_path = directory / "selected_cv.json"
            write_json(selected_path, selected_dict)
            (directory / "compile.log").write_text(compile_log, encoding="utf-8")
            manifest = self._manifest(
                task, job, packet_id, selected_dict, directory, page_count, None
            )
            manifest_path = directory / "manifest.json"
            write_json(manifest_path, manifest)
            self.repository.complete_packet_attempt(
                str(task["id"]), packet_id, artifact_directory=str(directory),
                pdf_path=str(pdf_path), tex_path=str(tex_path),
                selected_cv_path=str(selected_path), manifest_path=str(manifest_path),
                page_count=page_count,
                tailoring_decision_path=str(tailoring_path) if tailoring_path else None,
            )
        except PacketGenerationError as error:
            self._write_failure_manifest(
                directory, task, job, packet_id, error.stage, error.reason
            )
            self.repository.fail_packet_attempt(
                str(task["id"]), packet_id, stage=error.stage, reason=error.reason
            )
        except (OSError, ValueError) as error:
            self._write_failure_manifest(
                directory, task, job, packet_id, "save_output", str(error)
            )
            self.repository.fail_packet_attempt(
                str(task["id"]), packet_id, stage="save_output", reason=str(error)
            )
        return self.repository.get_job(str(task["job_id"]))

    def _manifest(self, task, job, packet_id, selected, directory, page_count, failure):
        paths = {
            "directory": str(directory), "pdf": str(directory / "cv.pdf"),
            "tex": str(directory / "cv.tex"), "selected_cv": str(directory / "selected_cv.json"),
        }
        if selected.get("tailoring"):
            paths["tailoring_decision"] = str(directory / "tailoring_decision.json")
        selected_records = selected.get("selection_records", [])
        master_cv = selected.get("master_cv")
        tailoring = selected.get("tailoring")
        return {
            "manifest_version": "phase5-manifest-v1", "packet_id": packet_id,
            "job_id": job["id"], "q2_task_id": task["id"], "company": job["company"],
            "title": job["title"], "source_url": job["source_url"],
            "selected_cv_family": selected.get("cv_family"),
            "truth_bank_version": selected.get("truth_bank_version"),
            "cv_family_version": selected.get("cv_family_version"),
            "scoring_version": selected.get("scoring_version"),
            "template_version": "phase5-basic-cv-v1",
            "selected_blocks": [item for item in selected_records if item["selected"]],
            "excluded_blocks": [item for item in selected_records if not item["selected"]],
            "section_order": selected.get("section_order"),
            "selected_skills": selected.get("skill_selection"),
            "master_cv": master_cv,
            "tailoring": tailoring,
            "immutable": bool(selected.get("immutable")),
            "score_at_generation": job.get("overall_score"), "generated_at": utc_now_iso(),
            "artifact_paths": paths,
            "page_count": page_count,
            "warnings": ["requires_fitting"] if page_count and page_count > 1 else [],
            "compile_result": "success" if failure is None else "failed", "failure": failure,
        }

    def _write_failure_manifest(self, directory, task, job, packet_id, stage, reason):
        if directory is None:
            return
        try:
            manifest = self._manifest(
                task, job, packet_id, {}, directory, None, {"stage": stage, "reason": reason}
            )
            write_json(directory / "manifest.json", manifest)
        except OSError:
            return


def _selected_family(job: dict[str, object]) -> dict[str, object]:
    family_id = str(job.get("selected_cv_family") or "")
    for family in load_cv_families():
        if str(family["id"]) == family_id:
            return family
    raise PacketGenerationError("load_cv_family", f"unknown selected CV family: {family_id}")


# Backward-compatible aliases for existing tests and local scripts.
DummyQ1Worker = Queue1Worker
DummyQ2Worker = Queue2Worker
