from __future__ import annotations

import json
from pathlib import Path

from lmstudio_labkit.suites import plan_suite, run_suite, summarize_suite
from suite_test_helpers import write_config, write_suite


def test_plan_suite_writes_summary_report_and_decision_record(tmp_path: Path) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "suite_matrix")
    write_suite(suite, config)

    plan_suite(suite, tmp_path / "out-plan")
    suite_dir = tmp_path / "out-plan" / "suite_test"
    summary = json.loads((suite_dir / "suite_summary.json").read_text(encoding="utf-8"))
    report = (suite_dir / "suite_report.md").read_text(encoding="utf-8")
    decision = (suite_dir / "suite_decision_record.md").read_text(encoding="utf-8")

    assert summary["mode"] == "plan"
    assert summary["status"] == "pass"
    assert "No live inference" in report
    assert "Review the suite artifacts" in decision


def test_summarize_suite_refreshes_report_and_decision_record(tmp_path: Path) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "suite_matrix")
    write_suite(suite, config)

    run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=True)
    suite_dir = tmp_path / "out-run" / "suite_test"
    summary = summarize_suite(suite_dir)
    report = (suite_dir / "suite_report.md").read_text(encoding="utf-8")
    decision = (suite_dir / "suite_decision_record.md").read_text(encoding="utf-8")

    assert summary["status"] == "pass"
    assert "run_count: `1`" in report
    assert "No model load or model download" in decision
