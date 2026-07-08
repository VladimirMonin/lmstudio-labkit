from __future__ import annotations

import csv
import json
from pathlib import Path

from lmstudio_labkit.reports import summarize_run

from lmstudio_labkit import BenchmarkConfig, run_matrix


def warmup_config() -> BenchmarkConfig:
    return BenchmarkConfig.from_dict(
        {
            "run_id": "cache_warmup",
            "models": [
                {"model_key": "fake", "model_id": "fake/text", "supported_modalities": ["text"]}
            ],
            "tasks": [
                {
                    "task_id": "blocks",
                    "family": "blocks",
                    "modality": "text",
                    "language": "ru_ru",
                    "structure_complexity": "medium",
                    "volume": "single",
                    "prompt": "Synthetic prompt",
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
                "cache_mode": ["warmup_first"],
            },
            "repeats": 3,
        }
    )


def test_warmup_first_marks_first_request_and_keeps_group_hashes(tmp_path: Path) -> None:
    artifacts = run_matrix(warmup_config(), tmp_path)

    records = [
        json.loads(line)
        for line in artifacts.cell_results.read_text(encoding="utf-8").splitlines()
        if line
    ]

    assert [record["warmup_request_index"] for record in records] == [1, 2, 3]
    assert [record["is_warmup_request"] for record in records] == [True, False, False]
    assert {record["cache_mode"] for record in records} == {"warmup_first"}
    assert {record["cache_hit_inferred"] for record in records} == {"unknown"}
    assert {record["cache_hit_reported"] for record in records} == {"unknown"}
    assert {record["kv_reuse_proven"] for record in records} == {False}
    assert len({record["cache_group_id"] for record in records}) == 1
    assert len({record["repeat_group_id"] for record in records}) == 1
    assert len({record["stable_prefix_hash"] for record in records}) == 1
    assert len({record["schema_hash"] for record in records}) == 1
    assert len({record["prompt_template_hash"] for record in records}) == 1
    assert len({record["dynamic_input_hash"] for record in records}) == 1
    assert len({record["same_input_hash"] for record in records}) == 1
    assert all(record["total_latency_ms"] is not None for record in records)
    assert all("ttft_ms" in record for record in records)
    assert all("prompt_processing_ms" in record for record in records)
    assert all("tokens_per_sec" in record for record in records)


def test_cache_warmup_fields_are_reported_in_csv_and_summary(tmp_path: Path) -> None:
    artifacts = run_matrix(warmup_config(), tmp_path)

    cell_rows = list(csv.DictReader(artifacts.cell_summary.open(encoding="utf-8")))
    resource_rows = list(csv.DictReader(artifacts.resource_summary.open(encoding="utf-8")))
    summary = summarize_run(artifacts.output_dir)
    report = artifacts.report.read_text(encoding="utf-8")

    assert cell_rows[0]["cache_mode"] == "warmup_first"
    assert cell_rows[0]["warmup_request_index"] == "1"
    assert cell_rows[0]["is_warmup_request"] == "True"
    assert cell_rows[0]["cache_hit_inferred"] == "unknown"
    assert cell_rows[0]["cache_hit_reported"] == "unknown"
    assert cell_rows[0]["kv_reuse_proven"] == "False"
    assert cell_rows[0]["total_latency_ms"] != ""
    assert "tokens_per_sec" in resource_rows[0]
    assert summary["per_cache_mode"]["cache_mode=warmup_first"]["attempt_count"] == 3
    assert summary["per_axis"]["cache_mode=warmup_first"]["attempt_count"] == 3
    assert "### Cache mode" in report
