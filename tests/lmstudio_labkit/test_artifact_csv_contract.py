from __future__ import annotations

import csv
from pathlib import Path

from lmstudio_labkit import BenchmarkConfig, run_matrix

CELL_SUMMARY_COLUMNS = {
    "cell_id",
    "model_key",
    "model_id",
    "task_id",
    "modality",
    "language",
    "structure_complexity",
    "volume",
    "context_tier",
    "schema_variant",
    "retry_policy",
    "execution_mode",
    "cache_mode",
    "cache_group_id",
    "warmup_request_index",
    "is_warmup_request",
    "stable_prefix_hash",
    "schema_hash",
    "prompt_template_hash",
    "dynamic_input_hash",
    "repeat_group_id",
    "same_input_hash",
    "cache_hit_inferred",
    "cache_hit_reported",
    "kv_reuse_proven",
    "session_id",
    "session_request_index",
    "session_request_count",
    "load_scope",
    "cleanup_scope",
    "loaded_before_session",
    "loaded_after_session_load",
    "final_loaded_instances",
    "session_cleanup_verified",
    "execution_target",
    "resource_telemetry_mode",
    "resource_telemetry_status",
    "resource_ram_required",
    "resource_vram_required",
    "repeat_index",
    "status",
    "json_parse_status",
    "json_schema_status",
    "business_status",
    "id_exact_status",
    "language_status",
    "image_ground_truth_status",
    "finish_reason_length_status",
    "missing_id_count",
    "unexpected_id_count",
    "duplicate_id_count",
    "order_mismatch",
    "first_mismatch_index",
    "placeholder_hit_count",
    "markdown_fence_count",
    "finish_reason",
    "retry_count",
    "retry_recovered",
    "error_category",
    "latency_ms",
    "ttft_ms",
    "prompt_processing_ms",
    "total_latency_ms",
    "tokens_per_sec",
    "prompt_tokens",
    "completion_tokens",
    "response_char_count",
    "ram_before_mb",
    "ram_peak_mb",
    "ram_after_mb",
    "vram_before_mb",
    "vram_peak_mb",
    "vram_after_mb",
}

MODEL_SUMMARY_COLUMNS = {
    "model_key",
    "model_id",
    "attempt_count",
    "pass_count",
    "fail_count",
    "pass_rate",
    "json_parse_pass_rate",
    "schema_pass_rate",
    "id_exact_pass_rate",
    "language_pass_rate",
    "retry_attempted_count",
    "retry_recovered_count",
    "retry_dependency_rate",
    "finish_length_count",
    "median_latency_ms",
    "p95_latency_ms",
}


def contract_config() -> BenchmarkConfig:
    return BenchmarkConfig.from_dict(
        {
            "run_id": "artifact_contract",
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
            },
        }
    )


def test_artifact_csv_contract_includes_required_a5_columns(tmp_path: Path) -> None:
    artifacts = run_matrix(contract_config(), tmp_path)

    cell_fieldnames = csv.DictReader(artifacts.cell_summary.open(encoding="utf-8")).fieldnames
    model_fieldnames = csv.DictReader(artifacts.model_summary.open(encoding="utf-8")).fieldnames

    assert cell_fieldnames is not None
    assert model_fieldnames is not None
    assert CELL_SUMMARY_COLUMNS <= set(cell_fieldnames)
    assert MODEL_SUMMARY_COLUMNS <= set(model_fieldnames)


def test_artifact_csv_contract_flattens_axis_and_resource_values(tmp_path: Path) -> None:
    artifacts = run_matrix(contract_config(), tmp_path)

    cell_rows = list(csv.DictReader(artifacts.cell_summary.open(encoding="utf-8")))
    model_rows = list(csv.DictReader(artifacts.model_summary.open(encoding="utf-8")))

    assert cell_rows[0]["modality"] == "text"
    assert cell_rows[0]["language"] == "ru_ru"
    assert cell_rows[0]["structure_complexity"] == "medium"
    assert cell_rows[0]["schema_variant"] == "hardened_const"
    assert cell_rows[0]["execution_mode"] == "cold_per_request"
    assert cell_rows[0]["json_parse_status"] == "pass"
    assert cell_rows[0]["id_exact_status"] == "pass"
    assert cell_rows[0]["finish_reason"] == "stop"
    assert int(cell_rows[0]["completion_tokens"]) > 0
    assert int(cell_rows[0]["response_char_count"]) > 0
    assert model_rows[0]["attempt_count"] == "1"
    assert model_rows[0]["pass_count"] == "1"
    assert model_rows[0]["json_parse_pass_rate"] == "1.0"
