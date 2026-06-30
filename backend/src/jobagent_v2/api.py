"""Local HTTP API for JobAgent V2."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from jobagent_v2.schemas import ValidationError
from jobagent_v2.service import JobService
from jobagent_v2.statuses import InvalidTransitionError
from jobagent_v2.storage import JobNotFoundError, Repository


API_DOCUMENTATION = {
    "POST /api/jobs": "Create or return a duplicate raw job from extension capture payload.",
    "GET /api/jobs": "List active jobs. Use include_archived=true to include archived jobs.",
    "GET /api/jobs/{job_id}": "Return one job.",
    "POST /api/jobs/{job_id}/generate": "Manually promote a scored job into Q2.",
    "POST /api/jobs/{job_id}/star": "Star a job and set high manual priority.",
    "POST /api/jobs/{job_id}/unstar": "Remove a job star and restore normal priority.",
    "POST /api/jobs/{job_id}/priority": "Set manual priority to normal or high.",
    "GET /api/jobs/{job_id}/q2-task": "Return the job's persistent Q2 task, if any.",
    "GET /api/jobs/{job_id}/packet": "Return the latest packet attempt for a job.",
    "GET /api/packets/{packet_id}": "Return a packet attempt.",
    "GET /api/packets/{packet_id}/manifest": "Return a packet manifest.",
    "GET /api/packets/{packet_id}/pdf": "Serve a generated packet PDF.",
    "GET /api/reviews": "List review items. Defaults to pending reviews.",
    "GET /api/reviews/{review_id}": "Return a complete review item.",
    "POST /api/reviews/{review_id}/resolve": "Resolve a review with a validated action.",
    "GET /api/reviews/feedback": "Export reviewed outcomes for later calibration.",
    "POST /api/jobs/{job_id}/reviews": "Create a manual review for a job decision.",
    "POST /api/jobs/{job_id}/retry": "Retry failed/manual-review work.",
    "POST /api/jobs/{job_id}/archive": "Archive a job.",
    "GET /api/jobs/{job_id}/events": "Return persisted job event history.",
    "GET /api/jobs/{job_id}/score": "Return persisted Phase 3 scoring diagnostics.",
    "GET /api/jobs/{job_id}/block-scores": "Return persisted block-level scores.",
    "GET /api/jobs/{job_id}/semantic-assessment": "Return persisted hybrid semantic diagnostics.",
    "POST /api/jobs/{job_id}/rescore": "Rescore a completed intake job.",
    "POST /api/workers/q1/run-once": "Run one Queue 1 intake/scoring job.",
    "POST /api/workers/q2/run-once": "Run one Queue 2 packet-generation job.",
    "POST /api/workers/regeneration/run-once": "Run one reviewed packet-regeneration job.",
    "POST /api/workers/promotion/run-once": "Run one deterministic promotion scheduler cycle.",
    "GET /api/queue/q2": "List persistent Q2 tasks and queue capacity diagnostics.",
}


def create_service(db_path: Path | str, artifact_root: Path | str) -> JobService:
    return JobService(Repository(db_path), artifact_root)


def make_handler(service: JobService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "JobAgentV2Local/0.1"

        def do_OPTIONS(self) -> None:
            self._send_json({"ok": True})

        def do_GET(self) -> None:
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)
                if path == "/api/health":
                    self._send_json({"ok": True})
                    return
                if path == "/api/docs":
                    self._send_json({"endpoints": API_DOCUMENTATION})
                    return
                if path == "/api/jobs":
                    include_archived = query.get("include_archived", ["false"])[0] == "true"
                    self._send_json(service.list_jobs(include_archived=include_archived))
                    return
                if path == "/api/queue/q2":
                    self._send_json(service.list_q2_tasks())
                    return
                if path == "/api/reviews":
                    self._send_json(
                        service.list_reviews(
                            owner_id=self._owner_id(query),
                            status=_single_query(query, "status", "pending"),
                            review_type=_single_query(query, "review_type"),
                            family=_single_query(query, "family"),
                            job_id=_single_query(query, "job_id"),
                        )
                    )
                    return
                if path == "/api/reviews/feedback":
                    self._send_json(
                        service.export_review_feedback(owner_id=self._owner_id(query))
                    )
                    return
                review_id, review_suffix = _match_review_route(path)
                if review_id and review_suffix == "":
                    self._send_json(
                        service.get_review(review_id, owner_id=self._owner_id(query))
                    )
                    return
                packet_id, packet_suffix = _match_packet_route(path)
                if packet_id and packet_suffix == "":
                    self._send_json(service.get_packet(packet_id))
                    return
                if packet_id and packet_suffix in {"/manifest", "/pdf"}:
                    file_key = "manifest_path" if packet_suffix == "/manifest" else "pdf_path"
                    try:
                        file_path = service.packet_artifact(
                            packet_id,
                            file_key,
                            owner_id=self._owner_id(query),
                        )
                    except FileNotFoundError:
                        self._send_json({"error": "packet artifact is unavailable"}, status=404)
                        return
                    content_type = (
                        "application/json" if packet_suffix == "/manifest" else "application/pdf"
                    )
                    self._send_file(file_path, content_type)
                    return
                job_id, suffix = _match_job_route(path)
                if job_id and suffix == "":
                    self._send_json(service.get_job(job_id))
                    return
                if job_id and suffix == "/events":
                    self._send_json(service.get_events(job_id))
                    return
                if job_id and suffix == "/score":
                    self._send_json(service.get_score(job_id))
                    return
                if job_id and suffix == "/block-scores":
                    self._send_json(service.get_block_scores(job_id))
                    return
                if job_id and suffix == "/semantic-assessment":
                    self._send_json(service.get_semantic_assessment(job_id))
                    return
                if job_id and suffix == "/q2-task":
                    self._send_json(service.get_q2_task(job_id))
                    return
                if job_id and suffix == "/packet":
                    self._send_json(service.get_packet_for_job(job_id))
                    return
                self._send_json({"error": "not found"}, status=404)
            except JobNotFoundError as error:
                self._send_json({"error": str(error)}, status=404)
            except Exception as error:
                self._send_json({"error": str(error)}, status=500)

        def do_POST(self) -> None:
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/api/jobs":
                    self._send_json(service.create_job(self._read_json()), status=201)
                    return
                if path == "/api/workers/q1/run-once":
                    self._send_json(service.run_q1_once())
                    return
                if path == "/api/workers/q2/run-once":
                    self._send_json(service.run_q2_once())
                    return
                if path == "/api/workers/regeneration/run-once":
                    self._send_json(service.run_regeneration_once())
                    return
                if path == "/api/workers/promotion/run-once":
                    self._send_json(service.run_promotion_once())
                    return
                review_id, review_suffix = _match_review_route(path)
                if review_id and review_suffix == "/resolve":
                    self._send_json(
                        service.resolve_review(
                            review_id,
                            self._read_json(),
                            owner_id=self._owner_id({}),
                        )
                    )
                    return
                job_id, suffix = _match_job_route(path)
                if job_id and suffix == "/generate":
                    self._send_json(service.generate_now(job_id))
                    return
                if job_id and suffix == "/star":
                    self._send_json(service.set_star(job_id, True))
                    return
                if job_id and suffix == "/unstar":
                    self._send_json(service.set_star(job_id, False))
                    return
                if job_id and suffix == "/priority":
                    self._send_json(service.set_priority(job_id, self._read_json()))
                    return
                if job_id and suffix == "/retry":
                    self._send_json(service.retry(job_id))
                    return
                if job_id and suffix == "/archive":
                    self._send_json(service.archive(job_id))
                    return
                if job_id and suffix == "/rescore":
                    self._send_json(service.rescore(job_id))
                    return
                if job_id and suffix == "/reviews":
                    self._send_json(
                        service.create_review(
                            job_id,
                            self._read_json(),
                            owner_id=self._owner_id({}),
                        ),
                        status=201,
                    )
                    return
                self._send_json({"error": "not found"}, status=404)
            except (ValidationError, ValueError, InvalidTransitionError) as error:
                self._send_json({"error": str(error)}, status=400)
            except JobNotFoundError as error:
                self._send_json({"error": str(error)}, status=404)
            except Exception as error:
                self._send_json({"error": str(error)}, status=500)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> Any:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as error:
                raise ValidationError("request body must be valid JSON") from error

        def _send_json(self, payload: Any, *, status: int = 200) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-JobAgent-Owner")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            if not path.is_file():
                self._send_json({"error": "packet artifact is unavailable"}, status=404)
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _owner_id(self, query: dict[str, list[str]]) -> str:
            owner = self.headers.get("X-JobAgent-Owner") or _single_query(
                query, "owner_id", "local"
            )
            return owner.strip() or "local"

    Handler.service = service
    return Handler


def create_http_server(
    host: str,
    port: int,
    *,
    db_path: Path | str,
    artifact_root: Path | str,
) -> ThreadingHTTPServer:
    service = create_service(db_path, artifact_root)
    return ThreadingHTTPServer((host, port), make_handler(service))


def _match_job_route(path: str) -> tuple[str | None, str]:
    prefix = "/api/jobs/"
    if not path.startswith(prefix):
        return None, ""
    rest = path[len(prefix) :]
    if "/" in rest:
        job_id, suffix = rest.split("/", 1)
        return job_id, f"/{suffix}"
    return rest, ""


def _match_packet_route(path: str) -> tuple[str | None, str]:
    prefix = "/api/packets/"
    if not path.startswith(prefix):
        return None, ""
    rest = path[len(prefix):]
    if "/" in rest:
        packet_id, suffix = rest.split("/", 1)
        return packet_id, f"/{suffix}"
    return rest, ""


def _match_review_route(path: str) -> tuple[str | None, str]:
    prefix = "/api/reviews/"
    if not path.startswith(prefix):
        return None, ""
    rest = path[len(prefix):]
    if "/" in rest:
        review_id, suffix = rest.split("/", 1)
        return review_id, f"/{suffix}"
    return rest, ""


def _single_query(
    query: dict[str, list[str]],
    key: str,
    default: str | None = None,
) -> str | None:
    values = query.get(key)
    if not values:
        return default
    value = values[0].strip()
    return value or default
