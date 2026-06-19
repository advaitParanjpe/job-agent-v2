from jobagent_v2 import create_app_metadata


def test_backend_imports_and_reports_bootstrap_metadata() -> None:
    metadata = create_app_metadata()

    assert metadata == {
        "name": "jobagent-v2",
        "phase": "phase-0b",
        "implements_features": False,
    }

