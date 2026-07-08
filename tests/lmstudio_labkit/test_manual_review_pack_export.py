from __future__ import annotations

from pathlib import Path

from lmstudio_labkit.review_pack import export_review_pack


def test_export_review_pack_from_sanitized_run(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "cell_results.jsonl").write_text(
        '{"cell_id":"c1","model_key":"m","task_id":"t","axes":{"task_intent":"punctuation_restore"},"status":"pass","validation":{"status":"pass"}}\n'
    )
    out = tmp_path / "pack"
    result = export_review_pack(run, out)
    assert result["status"] == "ok"
    assert (out / "README.md").exists()
    assert (out / "sampled_cases.md").exists()
    assert (out / "rubric.yaml").exists()
    assert (out / "reviewer_notes.md").exists()
