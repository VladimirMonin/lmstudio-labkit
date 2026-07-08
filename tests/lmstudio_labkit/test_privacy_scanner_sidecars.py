from __future__ import annotations

import json
from pathlib import Path

import pytest
from lmstudio_labkit.reports import compare_runs, summarize_run

from lmstudio_labkit import BenchmarkConfig, run_matrix


def report_config() -> BenchmarkConfig:
    return BenchmarkConfig.from_dict(
        {
            "run_id": "privacy_sidecars",
            "models": [
                {"model_key": "fake", "model_id": "fake/text", "supported_modalities": ["text"]}
            ],
            "tasks": [
                {
                    "task_id": "valid",
                    "family": "blocks",
                    "modality": "text",
                    "language": "ru_ru",
                    "structure_complexity": "medium",
                    "volume": "single",
                    "prompt": "Synthetic",
                    "schema_family": "blocks",
                    "expected_ids": [0],
                    "expected_output": {"blocks": [{"id": 0, "text": "Русский блок"}]},
                    "fake_mode": "valid",
                }
            ],
            "axes": {
                "modality": ["text"],
                "language": ["ru_ru"],
                "structure_complexity": ["medium"],
                "volume": ["single"],
                "context_tier": ["8192"],
                "schema_variant": ["hardened_const"],
                "retry_policy": ["off"],
            },
        }
    )


def test_privacy_scanner_scans_generated_summary_and_compare_sidecars(tmp_path: Path) -> None:
    artifacts = run_matrix(report_config(), tmp_path)

    summarize_run(artifacts.output_dir)
    compare_runs(artifacts.output_dir, artifacts.output_dir)

    privacy_scan = json.loads(
        (artifacts.output_dir / "privacy_scan.json").read_text(encoding="utf-8")
    )

    assert privacy_scan["status"] == "pass"
    assert {
        "summary.json",
        "summary.csv",
        "axis_summary.csv",
        "failure_summary.csv",
        "retry_impact.csv",
        "compare_summary.json",
        "compare_summary.md",
    } <= set(privacy_scan["scanned_artifacts"])


def test_privacy_scanner_rejects_generated_summary_sidecar_leaks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "planner_summary.json").write_text(
        json.dumps(
            {
                "run_id": "sidecar_leak",
                "cell_count": 1,
                "privacy_mode": "safe-default",
                "safety_budget": {"live": False},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "cell_results.jsonl").write_text(
        json.dumps(
            {
                "cell_id": "c1",
                "model_key": "fake",
                "status": "pass",
                "axes": {"language": "http://127.0.0.1:1234"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="localhost_url"):
        summarize_run(run_dir)
