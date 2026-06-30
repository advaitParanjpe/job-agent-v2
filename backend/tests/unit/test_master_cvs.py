from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pypdf import PdfWriter

from jobagent_v2.master_cvs import (
    EXPECTED_MASTER_FAMILIES,
    MASTER_CV_SCHEMA_VERSION,
    MasterCVValidationError,
    discover_master_cvs,
    validate_master_tex_compiles,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
MASTER_ROOT = REPO_ROOT / "master-cvs"


def copy_master_root(tmp_path: Path) -> Path:
    root = tmp_path / "master-cvs"
    shutil.copytree(MASTER_ROOT, root)
    return root


def write_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)


def test_all_four_approved_master_cvs_register_successfully() -> None:
    records = discover_master_cvs(MASTER_ROOT)

    assert [record.family_id for record in records] == [
        "digital_ic",
        "verification",
        "software",
        "ml",
    ]
    assert {record.display_name for record in records} == {
        str(config["display_name"]) for config in EXPECTED_MASTER_FAMILIES.values()
    }
    assert all(record.schema_version == MASTER_CV_SCHEMA_VERSION for record in records)
    assert all(record.approved for record in records)
    assert all(record.dynamic_skills_allowed is False for record in records)
    assert all(record.pdf_page_count == 1 for record in records)
    assert all(
        record.immutable_sections == ["header", "Education", "Experience"]
        for record in records
    )


def test_missing_tex_file_fails(tmp_path: Path) -> None:
    root = copy_master_root(tmp_path)
    (root / "digital_ic_master.tex").unlink()

    with pytest.raises(MasterCVValidationError, match="missing \\.tex"):
        discover_master_cvs(root)


def test_missing_pdf_file_fails(tmp_path: Path) -> None:
    root = copy_master_root(tmp_path)
    (root / "digital_ic_master.pdf").unlink()

    with pytest.raises(MasterCVValidationError, match="missing \\.pdf"):
        discover_master_cvs(root)


def test_unknown_family_file_fails(tmp_path: Path) -> None:
    root = copy_master_root(tmp_path)
    (root / "unknown_master.tex").write_text("not approved", encoding="utf-8")

    with pytest.raises(MasterCVValidationError, match="unexpected master CV file"):
        discover_master_cvs(root)


def test_duplicate_family_registration_fails(tmp_path: Path) -> None:
    root = copy_master_root(tmp_path)
    duplicate_dir = root / "duplicate"
    duplicate_dir.mkdir()
    shutil.copy2(root / "digital_ic_master.tex", duplicate_dir / "digital_ic_master.tex")

    with pytest.raises(MasterCVValidationError, match="duplicate master CV file"):
        discover_master_cvs(root)


def test_multi_page_pdf_fails(tmp_path: Path) -> None:
    root = copy_master_root(tmp_path)
    write_pdf(root / "digital_ic_master.pdf", pages=2)

    with pytest.raises(MasterCVValidationError, match="exactly one page"):
        discover_master_cvs(root)


def test_malformed_pdf_fails(tmp_path: Path) -> None:
    root = copy_master_root(tmp_path)
    (root / "digital_ic_master.pdf").write_bytes(b"not a pdf")

    with pytest.raises(MasterCVValidationError, match="unreadable or malformed"):
        discover_master_cvs(root)


def test_compilation_of_approved_tex_sources_is_one_page() -> None:
    if shutil.which("pdflatex") is None:
        pytest.skip("pdflatex is not installed")
    try:
        page_counts = validate_master_tex_compiles(MASTER_ROOT)
    except MasterCVValidationError as error:
        if "not found" in str(error) or "pdflatex failed" in str(error):
            pytest.skip(f"local LaTeX toolchain cannot compile approved masters: {error}")
        raise

    assert page_counts == {"digital_ic": 1, "verification": 1, "software": 1, "ml": 1}
