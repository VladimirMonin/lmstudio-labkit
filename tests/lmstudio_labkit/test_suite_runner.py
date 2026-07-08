from __future__ import annotations

import json
from pathlib import Path

from lmstudio_labkit.suites import plan_suite, preflight_suite, run_suite, summarize_suite


def write_config(path: Path, run_id: str) -> None:
    path.write_text(
        f"""
run_id: {run_id}
models:
  - model_key: fake
    model_id: fake/text
    supported_modalities: [text]
tasks:
  - task_id: t
    family: simple_flat
    modality: text
    language: en_en
    prompt: Synthetic prompt
    expected_output:
      id: ok
      text: Synthetic response
axes:
  modality: [text]
  language: [en_en]
  structure_complexity: [simple]
  volume: [single]
  context_tier: [8192]
  schema_variant: [baseline_loose]
  retry_policy: [off]
safety:
  max_requests: 1
""".lstrip(),
        encoding="utf-8",
    )


def write_suite(path: Path, config: Path) -> None:
    path.write_text(
        f"""
suite_id: suite_test
stop_on_failure: true
configs:
  - config: {config.name}
    required: true
""".lstrip(),
        encoding="utf-8",
    )


def test_preflight_suite_and_plan_suite(tmp_path: Path) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "suite_matrix")
    write_suite(suite, config)

    preflight = preflight_suite(suite)
    planned = plan_suite(suite, tmp_path / "out-plan")

    assert preflight["status"] == "pass"
    assert planned["status"] == "pass"
    assert (tmp_path / "out-plan" / "suite_test" / "suite_config.yaml").exists()
    assert (
        tmp_path / "out-plan" / "suite_test" / "runs" / "suite_matrix" / "planner_summary.json"
    ).exists()


def test_run_suite_resume_skips_completed_run(tmp_path: Path) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "suite_matrix")
    write_suite(suite, config)

    first = run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=True)
    second = run_suite(suite, tmp_path / "out-run", profile="offline-fake", resume=True)
    summary = summarize_suite(tmp_path / "out-run" / "suite_test")

    assert first["status"] == "pass"
    assert second["records"][0]["status"] == "skipped"
    assert summary["status"] == "pass"
    assert summary["run_count"] == 1
    suite_results = tmp_path / "out-run" / "suite_test" / "suite_results.jsonl"
    rows = [json.loads(line) for line in suite_results.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "skipped"
