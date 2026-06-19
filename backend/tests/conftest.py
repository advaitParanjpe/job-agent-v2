from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from jobagent_v2.service import JobService
from jobagent_v2.storage import Repository


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "jobagent.sqlite3"


@pytest.fixture
def artifact_root(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


@pytest.fixture
def repository(db_path: Path) -> Repository:
    return Repository(db_path)


@pytest.fixture
def service(repository: Repository, artifact_root: Path) -> JobService:
    return JobService(repository, artifact_root)


@pytest.fixture
def capture_payload() -> dict[str, str]:
    return {
        "url": "https://Example.com/jobs/123?b=2&a=1#section",
        "page_title": "Example RTL Engineer",
        "visible_text": (
            "Example RTL Engineer\n"
            "Location: Austin, TX\n"
            "About the role\n"
            "You will design and verify RTL blocks for high-performance silicon products.\n"
            "Responsibilities\n"
            "You will implement SystemVerilog modules, review microarchitecture specs, "
            "debug simulation failures, and collaborate with verification engineers.\n"
            "Qualifications\n"
            "Requirements include experience with digital logic, computer architecture, "
            "Python scripting, version control, and clear technical communication.\n"
            "Preferred qualifications include exposure to synthesis, timing, FPGA "
            "prototyping, and hardware bring-up workflows."
        ),
        "source_site": "example.com",
        "captured_at": "2026-06-19T12:00:00Z",
    }


@pytest.fixture
def created_job(service: JobService, capture_payload: dict[str, str]) -> dict[str, object]:
    response = service.create_job(capture_payload)
    return response["job"]


@pytest.fixture
def fresh_repository(db_path: Path) -> Iterator[type[Repository]]:
    def factory() -> Repository:
        return Repository(db_path)

    yield factory
