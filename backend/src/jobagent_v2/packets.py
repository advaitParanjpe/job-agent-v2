"""Deterministic Phase 5 selected-CV construction and local PDF rendering."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jobagent_v2.scoring import ScoringConfigurationError, load_cv_families, load_truth_bank


TEMPLATE_VERSION = "phase5-basic-cv-v1"
TEMPLATE_PATH = Path(__file__).with_name("templates") / "basic_cv.tex"
MAX_EXPERIENCE_BLOCKS = 2
MAX_PROJECT_BLOCKS = 2
MAX_BULLETS_PER_BLOCK = 4


class PacketGenerationError(RuntimeError):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


@dataclass(frozen=True)
class SelectedBlock:
    id: str
    type: str
    name: str
    canonical_text: str
    bullets: list[str]
    score: int
    selection_rank: int
    selection_reason: str


@dataclass(frozen=True)
class SelectedCV:
    packet_id: str
    job_id: str
    cv_family: str
    cv_family_version: str
    truth_bank_version: str
    scoring_version: str
    header: dict[str, str]
    education: list[str]
    experiences: list[SelectedBlock]
    projects: list[SelectedBlock]
    skills: list[str]
    section_order: list[str]
    selection_records: list[dict[str, Any]]
    skill_selection: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def safe_artifact_directory(root: Path | str, job_id: str, packet_id: str) -> Path:
    valid = re.fullmatch(r"[A-Za-z0-9-]+", job_id) and re.fullmatch(
        r"[A-Za-z0-9-]+", packet_id
    )
    if not valid:
        raise PacketGenerationError(
            "artifact_path", "job and packet IDs must be safe UUID-like values"
        )
    base = Path(root).resolve()
    target = (base / "packets" / job_id / packet_id).resolve()
    if base not in target.parents:
        raise PacketGenerationError("artifact_path", "packet artifact path escapes configured root")
    return target


def latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def build_selected_cv(
    *, packet_id: str, job: dict[str, Any], block_scores: list[dict[str, Any]]
) -> SelectedCV:
    family_id = str(job.get("selected_cv_family") or "")
    if not family_id or not job.get("structured_jd") or not job.get("scoring_version"):
        raise PacketGenerationError("validate_inputs", "job is missing validated scoring inputs")
    families = load_cv_families()
    family = next((item for item in families if item["id"] == family_id), None)
    if family is None:
        raise PacketGenerationError("load_cv_family", f"unknown selected CV family: {family_id}")
    try:
        bank = load_truth_bank(family)
    except (OSError, ValueError, ScoringConfigurationError) as error:
        raise PacketGenerationError("load_truth_bank", str(error)) from error
    by_id = {str(block["id"]): block for block in bank["blocks"]}
    if not block_scores:
        raise PacketGenerationError("validate_inputs", "stored block scores are required")
    unknown = [
        item["block_id"] for item in block_scores if item["block_id"] not in by_id
    ]
    if unknown:
        raise PacketGenerationError(
            "validate_inputs", "stored scores reference blocks outside selected CV family"
        )
    records: list[dict[str, Any]] = []
    selected: dict[str, list[SelectedBlock]] = {"experience": [], "project": []}
    limits = (("experience", MAX_EXPERIENCE_BLOCKS), ("project", MAX_PROJECT_BLOCKS))
    for block_type, limit in limits:
        candidates = [item for item in block_scores if item["block_type"] == block_type]
        candidates.sort(
            key=lambda item: (-int(item["aggregate_score"]), str(item["block_id"]))
        )
        required = [
            item for item in candidates
            if bool(by_id[str(item["block_id"])].get("is_required"))
        ]
        chosen_ids = {str(item["block_id"]) for item in required}
        for item in candidates:
            if len(chosen_ids) >= max(limit, len(required)):
                break
            chosen_ids.add(str(item["block_id"]))
        for rank, item in enumerate(candidates, start=1):
            block = by_id[str(item["block_id"])]
            include = str(item["block_id"]) in chosen_ids
            reason = "required block" if block.get("is_required") else (
                "ranked within configured section limit"
                if include else "excluded below configured section limit"
            )
            records.append(
                {"block_id": item["block_id"], "section": block_type, "selected": include,
                 "selection_rank": rank, "selection_reason": reason,
                 "block_score": item["aggregate_score"], "score_reason": item["reason"]}
            )
            if include:
                text = str(block["canonical_text"])
                bullets = list(block.get("bullets") or [text])[:MAX_BULLETS_PER_BLOCK]
                selected[block_type].append(
                    SelectedBlock(
                        str(block["id"]), block_type, str(block["name"]), text,
                        bullets, int(item["aggregate_score"]), rank, reason,
                    )
                )
    section_scores = job.get("section_scores") or {}
    recommended = section_scores.get("recommended_section_order")
    if not isinstance(recommended, list) or set(recommended) != {"experience", "projects"}:
        raise PacketGenerationError(
            "validate_inputs", "stored recommended section order is invalid"
        )
    middle = ["projects" if section == "projects" else "experience" for section in recommended]
    section_order = ["education", *middle, "skills"]
    allowed = _allowed_skills(bank)
    structured = job.get("structured_jd") or {}
    jd_skills = {str(value).lower() for value in structured.get("skills", [])}
    evidenced = {
        skill.lower() for blocks in selected.values() for item in blocks
        for skill in _block_technologies(by_id[item.id])
    }
    skills = sorted((allowed & (jd_skills | evidenced)), key=str.lower)
    if not skills:
        skills = sorted(allowed, key=str.lower)
    header = bank.get("header")
    education = bank.get("education")
    if not isinstance(header, dict) or not isinstance(education, list) or not education:
        raise PacketGenerationError(
            "load_truth_bank", "truth bank lacks canonical header or education content"
        )
    skill_selection = {
        "selected": skills, "excluded": sorted(allowed - set(skills)),
        "reason": "JD exact matches and selected-block evidence only",
        "source": "validated_truth_bank",
    }
    return SelectedCV(
        packet_id, str(job["id"]), family_id, str(family["version"]),
        str(bank["version"]), str(job["scoring_version"]),
        {str(key): str(value) for key, value in header.items()},
        [str(value) for value in education], selected["experience"], selected["project"],
        skills, section_order, records, skill_selection,
    )


def _block_technologies(block: dict[str, Any]) -> list[str]:
    return [str(value) for value in block.get("technologies", [])]


def _allowed_skills(bank: dict[str, Any]) -> set[str]:
    allowed = {skill for block in bank["blocks"] for skill in _block_technologies(block)}
    for group in bank.get("skill_groups", []):
        allowed.update(str(value) for value in group.get("skills", []))
    return allowed


def render_latex(selected: SelectedCV, *, template_path: Path = TEMPLATE_PATH) -> str:
    if not template_path.is_file():
        raise PacketGenerationError(
            "render", f"configured template path does not exist: {template_path}"
        )
    sections: list[str] = []
    data = {"education": selected.education, "experience": selected.experiences,
            "projects": selected.projects, "skills": selected.skills}
    labels = {"education": "Education", "experience": "Experience",
              "projects": "Projects", "skills": "Skills"}
    for name in selected.section_order:
        if name == "skills":
            body = latex_escape(", ".join(data[name]))
        elif name == "education":
            body = r"\\".join(latex_escape(value) for value in data[name])
        else:
            entries = []
            for block in data[name]:
                bullets = "\n".join(r"\item " + latex_escape(bullet) for bullet in block.bullets)
                entries.append(
                    r"\textbf{" + latex_escape(block.name) + r"}\\" + "\n"
                    + r"\begin{itemize}" + "\n" + bullets + "\n\\end{itemize}"
                )
            body = "\n".join(entries)
        sections.append("\\section*{" + labels[name] + "}\n" + body)
    source = template_path.read_text(encoding="utf-8")
    return source.replace("@@NAME@@", latex_escape(selected.header.get("name", ""))).replace(
        "@@CONTACT@@", latex_escape(selected.header.get("contact", ""))
    ).replace("@@SECTIONS@@", "\n".join(sections))


def compile_pdf(
    tex: str, output_dir: Path, *, timeout_seconds: int = 30
) -> tuple[Path, str, int | None]:
    executable = shutil.which("pdflatex")
    if executable is None:
        raise PacketGenerationError(
            "compile", "pdflatex is unavailable; install a LaTeX distribution and retry"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jobagent-packet-") as temporary:
        build = Path(temporary)
        tex_path = build / "cv.tex"
        tex_path.write_text(tex, encoding="utf-8")
        try:
            command = [executable, "-interaction=nonstopmode", "-halt-on-error",
                       "-output-directory", str(build), str(tex_path)]
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout_seconds, check=False
            )
        except subprocess.TimeoutExpired as error:
            raise PacketGenerationError(
                "compile", f"pdflatex timed out after {timeout_seconds}s"
            ) from error
        log = (result.stdout or "") + "\n" + (result.stderr or "")
        pdf = build / "cv.pdf"
        if result.returncode != 0 or not pdf.is_file():
            raise PacketGenerationError("compile", "pdflatex failed: " + log[-1200:])
        final = output_dir / "cv.pdf"
        shutil.copy2(pdf, final)
        count = _page_count(final)
        return final, log, count


def _page_count(pdf: Path) -> int | None:
    executable = shutil.which("pdfinfo")
    if executable is None:
        return None
    result = subprocess.run(
        [executable, str(pdf)], capture_output=True, text=True, timeout=10, check=False
    )
    match = re.search(r"^Pages:\s+(\d+)", result.stdout or "", flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
