from __future__ import annotations

import pytest

from jobagent_v2.packets import PacketGenerationError, latex_escape, safe_artifact_directory


def test_latex_escape_and_safe_artifact_paths(tmp_path) -> None:
    assert latex_escape("A&B_50%") == r"A\&B\_50\%"
    assert safe_artifact_directory(tmp_path, "job-1", "packet-2").is_relative_to(tmp_path)
    with pytest.raises(PacketGenerationError):
        safe_artifact_directory(tmp_path, "../job", "packet")
