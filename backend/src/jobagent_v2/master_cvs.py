"""Discovery and validation for approved immutable master CV artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader


MASTER_CV_SCHEMA_VERSION = "phase6b-master-cv-v1"
MASTER_CV_ROOT = Path(__file__).resolve().parents[3] / "master-cvs"
EXPECTED_MASTER_FAMILIES = {
    "digital_ic": {
        "stem": "digital_ic_master",
        "display_name": "Digital IC / RTL Design",
    },
    "verification": {
        "stem": "verification_master",
        "display_name": "Design Verification / SoC Verification",
    },
    "software": {
        "stem": "software_master",
        "display_name": "Software Engineering",
    },
    "ml": {
        "stem": "ml_master",
        "display_name": "Machine Learning Engineering",
    },
}
REQUIRED_SECTIONS = ("Education", "Experience", "Projects", "Skills")
IMMUTABLE_SECTION_NAMES = ("header", "Education", "Experience")


class MasterCVValidationError(ValueError):
    """Raised when approved master CV artifacts are missing or invalid."""


@dataclass(frozen=True)
class MasterCVRecord:
    family_id: str
    display_name: str
    tex_path: str
    pdf_path: str
    tex_sha256: str
    pdf_sha256: str
    pdf_page_count: int
    approved: bool
    immutable_sections: list[str]
    dynamic_skills_allowed: bool
    source: str
    schema_version: str = MASTER_CV_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_master_cvs(root: Path | str = MASTER_CV_ROOT) -> list[MasterCVRecord]:
    root = Path(root)
    if not root.is_dir():
        raise MasterCVValidationError(f"master CV directory does not exist: {root}")
    files = [path for path in root.rglob("*") if path.is_file()]
    _reject_unexpected_files(root, files)
    grouped: dict[str, dict[str, Path]] = {
        family_id: {} for family_id in EXPECTED_MASTER_FAMILIES
    }
    stem_to_family = {
        str(config["stem"]): family_id
        for family_id, config in EXPECTED_MASTER_FAMILIES.items()
    }
    for path in files:
        family_id = stem_to_family[path.stem]
        kind = path.suffix.lower().lstrip(".")
        if kind in grouped[family_id]:
            raise MasterCVValidationError(
                f"duplicate {kind} for master family {family_id}: {path.name}"
            )
        grouped[family_id][kind] = path
    records = []
    immutable_reference: dict[str, str] | None = None
    for family_id in EXPECTED_MASTER_FAMILIES:
        family_files = grouped[family_id]
        if "tex" not in family_files:
            raise MasterCVValidationError(f"missing .tex for master family {family_id}")
        if "pdf" not in family_files:
            raise MasterCVValidationError(f"missing .pdf for master family {family_id}")
        sections = extract_tex_sections(family_files["tex"])
        _validate_required_sections(sections, family_id)
        immutable = {name: sections[name] for name in IMMUTABLE_SECTION_NAMES}
        if immutable_reference is None:
            immutable_reference = immutable
        elif immutable != immutable_reference:
            raise MasterCVValidationError(
                "immutable header, education, or experience sections differ across masters"
            )
        page_count = pdf_page_count(family_files["pdf"])
        if page_count != 1:
            raise MasterCVValidationError(
                f"approved PDF for {family_id} must be exactly one page; got {page_count}"
            )
        records.append(
            MasterCVRecord(
                family_id=family_id,
                display_name=str(EXPECTED_MASTER_FAMILIES[family_id]["display_name"]),
                tex_path=str(family_files["tex"]),
                pdf_path=str(family_files["pdf"]),
                tex_sha256=_sha256(family_files["tex"]),
                pdf_sha256=_sha256(family_files["pdf"]),
                pdf_page_count=page_count,
                approved=True,
                immutable_sections=list(IMMUTABLE_SECTION_NAMES),
                dynamic_skills_allowed=False,
                source="user_approved_master_cv",
            )
        )
    return records


def master_cv_registry(root: Path | str = MASTER_CV_ROOT) -> dict[str, Any]:
    return {
        "schema_version": MASTER_CV_SCHEMA_VERSION,
        "families": [record.to_dict() for record in discover_master_cvs(root)],
    }


def validate_master_cv_registry(root: Path | str = MASTER_CV_ROOT) -> None:
    discover_master_cvs(root)


def compile_tex_to_pdf(
    tex_path: Path | str, *, timeout_seconds: int = 30
) -> tuple[Path, int]:
    executable = shutil.which("pdflatex")
    if executable is None:
        raise MasterCVValidationError("pdflatex is unavailable")
    tex_path = Path(tex_path)
    with tempfile.TemporaryDirectory(prefix="jobagent-master-cv-") as temp:
        build = Path(temp)
        result = subprocess.run(
            [
                executable,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory",
                str(build),
                str(tex_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        pdf_path = build / f"{tex_path.stem}.pdf"
        if result.returncode != 0 or not pdf_path.is_file():
            log = ((result.stdout or "") + "\n" + (result.stderr or ""))[-1200:]
            raise MasterCVValidationError(f"pdflatex failed for {tex_path.name}: {log}")
        stable = build / "compiled.pdf"
        shutil.copy2(pdf_path, stable)
        return stable, pdf_page_count(stable)


def validate_master_tex_compiles(root: Path | str = MASTER_CV_ROOT) -> dict[str, int]:
    page_counts = {}
    for record in discover_master_cvs(root):
        _, page_count = compile_tex_to_pdf(record.tex_path)
        if page_count != 1:
            raise MasterCVValidationError(
                f"compiled PDF for {record.family_id} must be exactly one page"
            )
        page_counts[record.family_id] = page_count
    return page_counts


def pdf_page_count(path: Path | str) -> int:
    try:
        reader = PdfReader(str(path))
        return len(reader.pages)
    except Exception as error:
        raise MasterCVValidationError(f"PDF is unreadable or malformed: {path}") from error


def extract_tex_sections(path: Path | str) -> dict[str, str]:
    text = Path(path).read_text(encoding="utf-8")
    matches = list(re.finditer(r"\\section\*\{([^}]+)\}", text))
    header_source = text[: matches[0].start()] if matches else text
    begin = header_source.find(r"\begin{document}")
    if begin != -1:
        header_source = header_source[begin + len(r"\begin{document}") :]
    sections: dict[str, str] = {
        "header": _normalize_tex(header_source)
    }
    for index, match in enumerate(matches):
        name = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[name] = _normalize_tex(text[match.start():end])
    return sections


def _validate_required_sections(sections: dict[str, str], family_id: str) -> None:
    missing = [name for name in REQUIRED_SECTIONS if not sections.get(name)]
    if missing:
        raise MasterCVValidationError(
            f"master family {family_id} is missing sections: {', '.join(missing)}"
        )
    if "Coursework:" not in sections["Education"]:
        raise MasterCVValidationError(f"master family {family_id} is missing coursework")


def _reject_unexpected_files(root: Path, files: list[Path]) -> None:
    allowed = {
        f"{config['stem']}{suffix}"
        for config in EXPECTED_MASTER_FAMILIES.values()
        for suffix in (".tex", ".pdf")
    }
    seen = {path.name for path in files}
    unknown = sorted(seen - allowed)
    if unknown:
        raise MasterCVValidationError(
            f"unexpected master CV file(s): {', '.join(unknown)}"
        )
    for name in allowed:
        matches = [path for path in files if path.name == name]
        if len(matches) > 1:
            rel = ", ".join(str(path.relative_to(root)) for path in matches)
            raise MasterCVValidationError(f"duplicate master CV file {name}: {rel}")


def _normalize_tex(value: str) -> str:
    without_comments = re.sub(r"(?<!\\)%.*", "", value)
    return re.sub(r"\s+", " ", without_comments).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_master_cv_registry(path: Path | str, root: Path | str = MASTER_CV_ROOT) -> None:
    value = master_cv_registry(root)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
