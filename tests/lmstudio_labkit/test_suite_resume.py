from __future__ import annotations

import json
from pathlib import Path

import pytest
from lmstudio_labkit.suites import run_suite
from suite_test_helpers import read_jsonl, write_config, write_suite


def test_run_suite_rejects_existing_output_without_resume(tmp_path: Path) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "suite_matrix")
    write_suite(suite, config)

    run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=True)

    with pytest.raises(FileExistsError, match="suite output directory already exists"):
        run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=False)


def test_run_suite_resume_skips_only_complete_matching_run(tmp_path: Path) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "suite_matrix")
    write_suite(suite, config)

    first = run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=True)
    second = run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=True)
    suite_results = tmp_path / "out-run" / "suite_test" / "suite_results.jsonl"
    rows = read_jsonl(suite_results)

    assert first["status"] == "pass"
    assert second["records"][0]["status"] == "skipped"
    assert len(rows) == 1
    assert rows[0]["status"] == "skipped"


def test_run_suite_resume_reruns_incomplete_cell_results(tmp_path: Path) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "suite_matrix")
    write_suite(suite, config)

    run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=True)
    run_dir = tmp_path / "out-run" / "suite_test" / "runs" / "suite_matrix"
    (run_dir / "cell_results.jsonl").write_text("", encoding="utf-8")

    resumed = run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=True)

    assert resumed["records"][0]["status"] == "passed"
    assert len(read_jsonl(run_dir / "cell_results.jsonl")) == 1


def test_run_suite_resume_reruns_planner_hash_mismatch(tmp_path: Path) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "suite_matrix")
    write_suite(suite, config)

    run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=True)
    planner_path = (
        tmp_path / "out-run" / "suite_test" / "runs" / "suite_matrix" / "planner_summary.json"
    )
    planner = json.loads(planner_path.read_text(encoding="utf-8"))
    planner["config_hash"] = "mismatch"
    planner_path.write_text(json.dumps(planner, ensure_ascii=False, indent=2), encoding="utf-8")

    resumed = run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=True)

    assert resumed["records"][0]["status"] == "passed"
