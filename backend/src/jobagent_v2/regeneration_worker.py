"""Worker for reviewed packet regeneration."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jobagent_v2.master_cvs import MASTER_CV_ROOT, discover_master_cvs, pdf_page_count
from jobagent_v2.packets import (
    PacketGenerationError,
    build_master_packet_artifacts,
    family_master_cv,
    safe_artifact_directory,
    write_json,
)
from jobagent_v2.project_blocks import (
    ProjectBlockRegistryError,
    load_project_block_registry,
    validate_tailoring_decision,
)
from jobagent_v2.scoring import load_cv_families
from jobagent_v2.storage import (
    REGENERATION_MAX_ATTEMPTS,
    REGENERATION_RETRYABLE_ERRORS,
    Repository,
)
from jobagent_v2.tailoring import (
    TailoringError,
    load_tailoring_policy,
    render_tailored_tex,
    validate_tailored_tex,
)
from jobagent_v2.packets import compile_pdf
from jobagent_v2.util import utc_now_iso


PACKET_GENERATOR_VERSION = "phase-h-review-regeneration-v1"
LEASE_SECONDS = 900


class ReviewRegenerationError(RuntimeError):
    def __init__(self, code: str, reason: str, *, retryable: bool = False) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.retryable = retryable


class ReviewRegenerationWorker:
    def __init__(
        self,
        repository: Repository,
        artifact_root: Path | str,
        *,
        max_attempts: int = REGENERATION_MAX_ATTEMPTS,
        stale_processing_seconds: int = LEASE_SECONDS,
    ) -> None:
        self.repository = repository
        self.artifact_root = Path(artifact_root)
        self.max_attempts = max_attempts
        self.stale_processing_seconds = stale_processing_seconds
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def recover_stale(self) -> int:
        return self.repository.recover_stale_regeneration_jobs(
            now=utc_now_iso(),
            max_attempts=self.max_attempts,
        )

    def process_next(self) -> dict[str, Any] | None:
        expiry = datetime.now(timezone.utc) + timedelta(seconds=self.stale_processing_seconds)
        job = self.repository.claim_next_regeneration_job(
            owner="phase-h-review-regeneration-worker",
            lease_expires_at=expiry.isoformat(timespec="seconds"),
            max_attempts=self.max_attempts,
        )
        if job is None:
            return None
        try:
            packet = self._process(job)
            self.repository.complete_regeneration_job(str(job["id"]), str(packet["id"]))
        except ReviewRegenerationError as error:
            self.repository.fail_regeneration_job(
                str(job["id"]),
                code=error.code,
                reason=error.reason,
                retryable=error.retryable,
                max_attempts=self.max_attempts,
            )
        except OSError as error:
            self.repository.fail_regeneration_job(
                str(job["id"]),
                code="temporary_artifact_write_failure",
                reason=str(error),
                retryable=True,
                max_attempts=self.max_attempts,
            )
        return self.repository.get_regeneration_job(str(job["id"]))

    def _process(self, regen_job: dict[str, Any]) -> dict[str, Any]:
        resolution = self.repository.get_review_resolution(str(regen_job["review_resolution_id"]))
        if resolution["regeneration_status"] == "complete" and resolution["regeneration_packet_id"]:
            return self.repository.get_packet(str(resolution["regeneration_packet_id"]))
        existing = self._existing_success(str(regen_job["idempotency_key"]))
        if existing is not None:
            return existing
        action = str(resolution["action"])
        if action in {"defer", "mark_out_of_scope"}:
            raise ReviewRegenerationError(
                "regeneration_not_applicable",
                "Review outcome does not produce a new packet.",
                retryable=False,
            )
        family = str(resolution["resolved_family"])
        if family not in {"digital_ic", "verification", "software", "ml"}:
            raise ReviewRegenerationError(
                "invalid_reviewed_family", "Reviewed family is unsupported."
            )
        registry = load_project_block_registry()
        policy = load_tailoring_policy()
        if resolution["details"].get("registry_version") not in {
            None,
            registry["schema_version"],
        }:
            raise ReviewRegenerationError(
                "version_drift",
                "Reviewed project registry version is no longer current.",
            )
        if resolution["details"].get("policy_version") not in {
            None,
            policy["policy_version"],
        }:
            raise ReviewRegenerationError(
                "version_drift",
                "Reviewed tailoring policy version is no longer current.",
            )
        final_blocks = list(resolution["resolved_blocks"] or [])
        base_blocks = list(registry["base_project_order"][family])
        if not final_blocks:
            final_blocks = base_blocks
        self._validate_blocks(family, base_blocks, final_blocks, registry)
        source_packet_id = str(
            regen_job.get("source_packet_id")
            or resolution.get("source_packet_id")
            or ""
        )
        if not source_packet_id:
            latest = self.repository.get_latest_ready_packet_for_job(str(regen_job["job_id"]))
            source_packet_id = str(latest["id"]) if latest else ""
        if not source_packet_id:
            raise ReviewRegenerationError(
                "stale_or_missing_source_packet", "No prior valid packet is available."
            )
        source_packet = self.repository.get_packet(source_packet_id)
        if source_packet["status"] != "ready":
            raise ReviewRegenerationError(
                "stale_or_missing_source_packet", "Source packet is not ready."
            )
        job = self.repository.get_job(str(regen_job["job_id"]))
        if job["owner_id"] != regen_job["owner_id"]:
            raise ReviewRegenerationError(
                "ownership_mismatch", "Review owner does not match the job owner."
            )
        family_record = self._family_record(family)
        q2_task_id = str(source_packet["q2_task_id"])
        packet = self.repository.create_review_packet_attempt(
            job_id=str(job["id"]),
            q2_task_id=q2_task_id,
            source_packet_id=source_packet_id,
            review_id=str(regen_job["review_id"]),
            review_resolution_id=str(regen_job["review_resolution_id"]),
            idempotency_key=str(regen_job["idempotency_key"]),
            selected_cv_family=family,
            generation_reason=f"review_resolution:{action}",
        )
        if packet["status"] == "ready":
            return packet
        directory = safe_artifact_directory(
            self.artifact_root, str(job["id"]), str(packet["id"])
        )
        directory.mkdir(parents=True, exist_ok=True)
        reviewed_job = {**job, "selected_cv_family": family}
        try:
            master_artifacts = build_master_packet_artifacts(
                packet_id=str(packet["id"]),
                job=reviewed_job,
                family=family_record,
                output_dir=directory,
            )
            compile_log = "approved master copied unchanged"
            page_count = master_artifacts.page_count
            tex_path = master_artifacts.tex_path
            pdf_path = master_artifacts.pdf_path
            tailoring_decision_path = None
            selected = dict(master_artifacts.selected_cv)
            selected["review_regeneration"] = self._review_metadata(
                regen_job, resolution, source_packet_id
            )
            if final_blocks != base_blocks:
                (
                    tex_path,
                    pdf_path,
                    compile_log,
                    page_count,
                    tailoring_decision_path,
                ) = self._build_tailored(
                    directory=directory, packet_id=str(packet["id"]), job=reviewed_job,
                    family=family, base_blocks=base_blocks, final_blocks=final_blocks,
                    registry=registry, policy=policy,
                )
                selected.update({
                    "source": "reviewed_master_cv_with_one_block_tailoring",
                    "immutable": False,
                    "project_blocks": {
                        "base_blocks": base_blocks,
                        "final_blocks": final_blocks,
                    },
                })
            else:
                selected.update({
                    "source": "reviewed_approved_master_cv",
                    "immutable": True,
                    "project_blocks": {
                        "base_blocks": base_blocks,
                        "final_blocks": final_blocks,
                    },
                })
            selected_path = directory / "selected_cv.json"
            write_json(selected_path, selected)
            (directory / "compile.log").write_text(compile_log, encoding="utf-8")
            manifest = self._manifest(
                regen_job=regen_job,
                resolution=resolution,
                packet_id=str(packet["id"]),
                source_packet_id=source_packet_id,
                selected=selected,
                directory=directory,
                page_count=page_count,
                failure=None,
            )
            manifest_path = directory / "manifest.json"
            write_json(manifest_path, manifest)
            return self.repository.complete_review_packet_attempt(
                packet_id=str(packet["id"]),
                artifact_directory=str(directory),
                pdf_path=str(pdf_path),
                tex_path=str(tex_path),
                selected_cv_path=str(selected_path),
                manifest_path=str(manifest_path),
                page_count=page_count,
                tailoring_decision_path=(
                    str(tailoring_decision_path) if tailoring_decision_path else None
                ),
            )
        except PacketGenerationError as error:
            raise ReviewRegenerationError(error.stage, error.reason) from error
        except (ProjectBlockRegistryError, TailoringError, ValueError) as error:
            raise ReviewRegenerationError("policy_validation_failed", str(error)) from error

    def _existing_success(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM packets WHERE idempotency_key = ? AND status = 'ready'",
                (idempotency_key,),
            ).fetchone()
        from jobagent_v2.storage import row_to_packet

        return row_to_packet(row) if row else None

    def _validate_blocks(
        self,
        family: str,
        base_blocks: list[str],
        final_blocks: list[str],
        registry: dict[str, Any],
    ) -> None:
        by_id = {str(block["block_id"]): block for block in registry["blocks"]}
        if len(final_blocks) != len(set(final_blocks)):
            raise ReviewRegenerationError(
                "duplicate_underlying_project", "Reviewed block order contains duplicates."
            )
        unknown = [block_id for block_id in final_blocks if block_id not in by_id]
        if unknown:
            raise ReviewRegenerationError(
                "unknown_or_incompatible_block", "Reviewed block is not registered."
            )
        projects = [str(by_id[block_id]["project_id"]) for block_id in final_blocks]
        if len(projects) != len(set(projects)):
            raise ReviewRegenerationError(
                "duplicate_underlying_project",
                "Reviewed blocks duplicate an underlying project.",
            )
        removed = list(set(base_blocks) - set(final_blocks))
        inserted = list(set(final_blocks) - set(base_blocks))
        if len(removed) > 1 or len(inserted) > 1:
            raise ReviewRegenerationError(
                "too_many_substitutions", "Reviewed packet changes more than one project."
            )
        decision = {
            "base_family": family,
            "base_blocks": base_blocks,
            "final_order": final_blocks,
            "removed_block": removed[0] if removed else None,
            "inserted_block": inserted[0] if inserted else None,
            "job_evidence": [],
            "reason": "Reviewed packet regeneration validation.",
            "policy_version": registry["policy_version"],
        }
        validate_tailoring_decision(decision, registry)

    def _build_tailored(
        self,
        *,
        directory: Path,
        packet_id: str,
        job: dict[str, Any],
        family: str,
        base_blocks: list[str],
        final_blocks: list[str],
        registry: dict[str, Any],
        policy: dict[str, Any],
    ) -> tuple[Path, Path, str, int, Path]:
        records = {record.family_id: record for record in discover_master_cvs(MASTER_CV_ROOT)}
        record = records[family]
        master_tex_path = Path(record.tex_path)
        tex = render_tailored_tex(
            master_tex_path.read_text(encoding="utf-8"), final_blocks, registry
        )
        decision = {
            "audit_version": "phase-h-review-regeneration-v1",
            "job_id": str(job["id"]),
            "packet_id": packet_id,
            "base_family": family,
            "classification_decision": (job.get("family_classification") or {}).get(
                "decision"
            ),
            "base_blocks": base_blocks,
            "final_order": final_blocks,
            "removed_block": next(iter(set(base_blocks) - set(final_blocks)), None),
            "inserted_block": next(iter(set(final_blocks) - set(base_blocks)), None),
            "replacement_gain": 0.0,
            "reason": "Reviewed project selection approved by user.",
            "job_evidence": [],
            "requires_review": False,
            "tailoring_status": "tailored",
            "fallback_reason": None,
            "policy_version": policy["policy_version"],
            "registry_version": registry["schema_version"],
            "project_registry_policy_version": registry["policy_version"],
            "classifier_version": str(job.get("family_classifier_version") or ""),
        }
        validate_tailored_tex(
            tex, master_tex_path=master_tex_path, decision=decision, registry=registry
        )
        candidate_dir = directory / "reviewed-candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate_pdf, compile_log, page_count = compile_pdf(tex, candidate_dir)
        page_count = page_count if page_count is not None else pdf_page_count(candidate_pdf)
        if page_count != 1:
            raise ReviewRegenerationError(
                "multi_page_pdf", "Regenerated PDF is not exactly one page."
            )
        tex_path = directory / "cv.tex"
        pdf_path = directory / "cv.pdf"
        tex_path.write_text(tex, encoding="utf-8")
        shutil.copy2(candidate_pdf, pdf_path)
        shutil.rmtree(candidate_dir, ignore_errors=True)
        decision_path = directory / "tailoring_decision.json"
        write_json(decision_path, decision)
        return tex_path, pdf_path, compile_log, page_count, decision_path

    def _family_record(self, family_id: str) -> dict[str, Any]:
        for family in load_cv_families():
            if str(family["id"]) == family_id:
                if not family_master_cv(family):
                    raise ReviewRegenerationError(
                        "invalid_reviewed_family",
                        "Reviewed family has no approved master.",
                    )
                return family
        raise ReviewRegenerationError("invalid_reviewed_family", "Reviewed family is unsupported.")

    def _review_metadata(
        self,
        regen_job: dict[str, Any],
        resolution: dict[str, Any],
        source_packet_id: str,
    ) -> dict[str, Any]:
        return {
            "regeneration_job_id": regen_job["id"],
            "review_id": regen_job["review_id"],
            "review_resolution_id": regen_job["review_resolution_id"],
            "source_packet_id": source_packet_id,
            "attempt": regen_job["attempt_count"],
            "resolved_family": resolution["resolved_family"],
            "resolved_blocks": resolution["resolved_blocks"],
            "packet_generator_version": PACKET_GENERATOR_VERSION,
        }

    def _manifest(
        self,
        *,
        regen_job: dict[str, Any],
        resolution: dict[str, Any],
        packet_id: str,
        source_packet_id: str,
        selected: dict[str, Any],
        directory: Path,
        page_count: int | None,
        failure: dict[str, Any] | None,
    ) -> dict[str, Any]:
        paths = {
            "directory": str(directory),
            "pdf": str(directory / "cv.pdf"),
            "tex": str(directory / "cv.tex"),
            "selected_cv": str(directory / "selected_cv.json"),
        }
        if (directory / "tailoring_decision.json").is_file():
            paths["tailoring_decision"] = str(directory / "tailoring_decision.json")
        return {
            "manifest_version": "phase-h-review-regeneration-manifest-v1",
            "packet_id": packet_id,
            "job_id": regen_job["job_id"],
            "owner_id": regen_job["owner_id"],
            "generation_kind": "review_regeneration",
            "source_packet_id": source_packet_id,
            "review_id": regen_job["review_id"],
            "review_resolution_id": regen_job["review_resolution_id"],
            "regeneration_job_id": regen_job["id"],
            "generation_attempt": regen_job["attempt_count"],
            "idempotency_key": regen_job["idempotency_key"],
            "final_family": resolution["resolved_family"],
            "final_project_blocks": resolution["resolved_blocks"],
            "regeneration_reason": f"review_resolution:{resolution['action']}",
            "packet_generator_version": PACKET_GENERATOR_VERSION,
            "selected_cv_family": selected.get("cv_family"),
            "master_cv": selected.get("master_cv"),
            "tailoring": selected.get("tailoring"),
            "immutable": bool(selected.get("immutable")),
            "generated_at": utc_now_iso(),
            "artifact_paths": paths,
            "page_count": page_count,
            "compile_result": "success" if failure is None else "failed",
            "failure": failure,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process reviewed packet regeneration jobs.")
    parser.add_argument("--db-path", default="data/jobagent_v2.sqlite3")
    parser.add_argument("--artifact-root", default="artifacts")
    parser.add_argument("--once", action="store_true", help="Process at most one job.")
    args = parser.parse_args(argv)
    worker = ReviewRegenerationWorker(Repository(args.db_path), args.artifact_root)
    worker.recover_stale()
    processed = worker.process_next()
    if args.once:
        print(json.dumps({"processed": processed is not None, "job": processed}, sort_keys=True))
        return 0
    count = 1 if processed is not None else 0
    while processed is not None:
        processed = worker.process_next()
        if processed is not None:
            count += 1
    print(json.dumps({"processed_count": count}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
