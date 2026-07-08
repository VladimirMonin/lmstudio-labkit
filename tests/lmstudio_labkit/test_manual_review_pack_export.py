from __future__ import annotations

import json
from pathlib import Path

import pytest
from lmstudio_labkit.review_pack import export_review_pack


def _write_minimal_run(run: Path) -> None:
    run.mkdir()
    (run / "cell_results.jsonl").write_text(
        '{"cell_id":"c1","model_key":"m","task_id":"t","axes":{"task_intent":"punctuation_restore"},"status":"pass","validation":{"status":"pass"}}\n',
        encoding="utf-8",
    )


def test_export_review_pack_from_sanitized_run(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_minimal_run(run)
    out = tmp_path / "pack"
    result = export_review_pack(run, out)
    assert result["status"] == "ok"
    assert result["raw_outputs_included"] is False
    assert (out / "README.md").exists()
    assert (out / "sampled_cases.md").exists()
    assert (out / "rubric.yaml").exists()
    assert (out / "reviewer_notes.md").exists()


def test_export_review_pack_can_include_local_only_raw_outputs_under_tmp(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    _write_minimal_run(run)
    (run / "raw_cases.jsonl").write_text(
        json.dumps(
            {
                "cell_id": "c1",
                "prompt": "raw prompt for local review",
                "raw_response": "raw response for local review",
                "raw_base_url": "http://127.0.0.1:1234",
                "token": "secret-token",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "pack"

    result = export_review_pack(
        run,
        out,
        include_raw_outputs_local_only=True,
    )

    assert result["status"] == "ok"
    assert result["raw_outputs_included"] is True
    assert result["raw_case_count"] == 1
    raw_path = out / "raw_outputs.local-only.jsonl"
    assert raw_path.exists()
    exported = json.loads(raw_path.read_text(encoding="utf-8"))
    assert exported["raw_response"] == "raw response for local review"
    assert "raw_base_url" not in exported
    assert "token" not in exported
    assert "WARNING" in (out / "README.md").read_text(encoding="utf-8")


def test_export_review_pack_rejects_raw_outputs_inside_repository(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_minimal_run(run)
    repo_root = Path(__file__).resolve().parents[2]
    out = repo_root / "raw-review-pack-should-not-be-created"

    with pytest.raises(ValueError, match="must not be written inside the repository"):
        export_review_pack(run, out, include_raw_outputs_local_only=True)

    assert not out.exists()
