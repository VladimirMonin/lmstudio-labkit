from __future__ import annotations

import csv
import json
from pathlib import Path

from lmstudio_labkit import BenchmarkConfig, run_matrix


def config_for_mode(fake_mode: str, retry_policy: str = "off") -> BenchmarkConfig:
    return BenchmarkConfig.from_dict(
        {
            "run_id": f"fake_{fake_mode}_{retry_policy}",
            "models": [
                {"model_key": "fake", "model_id": "fake/text", "supported_modalities": ["text"]}
            ],
            "tasks": [
                {
                    "task_id": "blocks",
                    "family": "blocks",
                    "modality": "text",
                    "prompt": "Synthetic prompt",
                    "schema_family": "blocks",
                    "expected_ids": [0, 1],
                    "expected_output": {
                        "blocks": [
                            {"id": 0, "text": "Русский блок"},
                            {"id": 1, "text": "Русский блок"},
                        ]
                    },
                    "fake_mode": fake_mode,
                }
            ],
            "axes": {
                "modality": ["text"],
                "language": ["ru_ru"],
                "structure_complexity": ["medium"],
                "volume": ["single"],
                "context_tier": ["8192"],
                "schema_variant": ["hardened_const"],
                "retry_policy": [retry_policy],
            },
        }
    )


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_fake_transport_failure_modes_are_recorded(tmp_path: Path) -> None:
    for mode in [
        "invalid_json",
        "missing_id",
        "duplicate_id",
        "reordered_ids",
        "wrong_language",
        "placeholder_text",
        "markdown_wrapped_json",
        "finish_length",
    ]:
        artifacts = run_matrix(config_for_mode(mode), tmp_path)
        rows = read_rows(artifacts.cell_results)
        assert rows[0]["status"] == "fail", mode
        assert rows[0]["error_category"] is not None, mode


def test_retry_recovers_and_metrics_capture_recovery(tmp_path: Path) -> None:
    artifacts = run_matrix(config_for_mode("retry_recovers", retry_policy="retry1"), tmp_path)
    row = read_rows(artifacts.cell_results)[0]

    assert row["status"] == "pass"
    assert row["retry_count"] == 1
    assert row["retry_recovered"] is True
    retry_summary = list(csv.DictReader(artifacts.retry_summary.open(encoding="utf-8")))
    assert retry_summary[0]["recovered_count"] == "1"


def test_retry_deterministic_fail_stays_failed(tmp_path: Path) -> None:
    artifacts = run_matrix(
        config_for_mode("retry_deterministic_fail", retry_policy="retry1"), tmp_path
    )
    row = read_rows(artifacts.cell_results)[0]

    assert row["status"] == "fail"
    assert row["retry_count"] == 1
    assert row["retry_recovered"] is False
