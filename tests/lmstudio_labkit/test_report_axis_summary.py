from __future__ import annotations

import json
from pathlib import Path

from lmstudio_labkit.reports import compare_runs, summarize_run

from lmstudio_labkit import BenchmarkConfig, run_matrix


def test_report_axis_summary_and_compare_outputs(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(
        {
            "run_id": "reports",
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
                },
                {
                    "task_id": "bad",
                    "family": "blocks",
                    "modality": "text",
                    "language": "ru_ru",
                    "structure_complexity": "medium",
                    "volume": "single",
                    "prompt": "Synthetic",
                    "schema_family": "blocks",
                    "expected_ids": [0],
                    "expected_output": {"blocks": [{"id": 0, "text": "Русский блок"}]},
                    "fake_mode": "missing_id",
                },
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
    artifacts = run_matrix(config, tmp_path)

    summary = summarize_run(artifacts.output_dir)
    comparison = compare_runs(artifacts.output_dir, artifacts.output_dir)

    report = (artifacts.output_dir / "report.md").read_text(encoding="utf-8")

    assert summary["per_axis"]["language=ru_ru"]["attempt_count"] == 2
    assert summary["per_language"]["language=ru_ru"]["attempt_count"] == 2
    assert summary["per_complexity"]["structure_complexity=medium"]["attempt_count"] == 2
    assert summary["per_schema_variant"]["schema_variant=hardened_const"]["attempt_count"] == 2
    assert summary["per_retry_policy"]["retry_policy=off"]["attempt_count"] == 2
    assert summary["skipped_cell_count"] == 0
    assert summary["safety_budget"]["live"] is False
    assert summary["live_screening_readiness"] == "offline-default-live-screening-not-enabled"
    assert summary["failure_taxonomy"]
    assert "## Model summary" in report
    assert "### Language" in report
    assert "### Complexity" in report
    assert "### Schema variant" in report
    assert "### Retry" in report
    assert "## Skipped cells" in report
    assert "## Safety budget" in report
    assert "## Live-screening readiness" in report
    assert (artifacts.output_dir / "summary.json").exists()
    assert (artifacts.output_dir / "axis_summary.csv").exists()
    assert (artifacts.output_dir / "compare_summary.md").exists()
    assert comparison["delta"]["pass_rate"] == 0.0
    json.loads((artifacts.output_dir / "compare_summary.json").read_text(encoding="utf-8"))
