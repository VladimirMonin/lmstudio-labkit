from __future__ import annotations

import pytest
from lmstudio_labkit.artifacts import write_run_artifacts
from lmstudio_labkit.privacy import scan_text


def test_privacy_scanner_detects_leaks() -> None:
    violations = scan_text(
        '{"raw_prompt":"secret", "url":"http://127.0.0.1:1234", "path":"/home/user/private"}'
    )

    categories = {item.category for item in violations}
    assert "raw_prompt_key" in categories
    assert "localhost_url" in categories
    assert "home_path" in categories


def test_privacy_scanner_allows_hashes() -> None:
    violations = scan_text(
        '{"response_hash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
    )

    assert violations == []


def test_artifact_writer_runs_privacy_scan_and_rejects_raw_response(tmp_path) -> None:
    with pytest.raises(ValueError):
        write_run_artifacts(
            tmp_path / "bad",
            {"run_id": "bad", "privacy_mode": "safe-default", "cell_count": 1},
            [{"cell_id": "c1", "status": "pass", "raw_response": "leak"}],
        )
