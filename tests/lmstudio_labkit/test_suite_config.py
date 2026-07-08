from __future__ import annotations

from pathlib import Path

import pytest
from lmstudio_labkit.suites import SuiteConfig, plan_suite
from suite_test_helpers import write_config, write_suite

CONTRACT_FILES = {
    "suite_config.yaml",
    "suite_preflight.json",
    "suite_plan.json",
    "suite_results.jsonl",
    "suite_summary.json",
    "suite_report.md",
    "suite_decision_record.md",
    "runs",
}


def test_suite_config_accepts_path_id_and_writes_contract(tmp_path: Path) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "suite_matrix")
    write_suite(suite, config, entry_id="quality_gate")

    parsed = SuiteConfig.from_file(suite)
    planned = plan_suite(suite, tmp_path / "out-plan")
    suite_dir = tmp_path / "out-plan" / "suite_test"

    assert parsed.entries[0].entry_id == "quality_gate"
    assert planned["status"] == "pass"
    assert CONTRACT_FILES <= {path.name for path in suite_dir.iterdir()}
    assert (suite_dir / "runs" / "suite_matrix" / "planner_summary.json").exists()


def test_suite_rejects_unsafe_output_identifiers(tmp_path: Path) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "../escape")
    write_suite(suite, config)

    with pytest.raises(ValueError, match="run_id must be a safe local identifier"):
        plan_suite(suite, tmp_path / "out")
