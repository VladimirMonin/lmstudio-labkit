from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

from lmstudio_managed.metrics import (
    MemoryRecommendationCatalog,
    memory_recommendation_catalog_schema,
)

from .config import ExperimentConfig
from .live_config import LiveSmokeConfig
from .privacy import sanitize_metric_payload
from .structured import SCHEMA_PASS_MEANING

RESULT_FILE_NAMES = (
    "experiment.yaml",
    "environment.json",
    "load_configs.jsonl",
    "requests.jsonl",
    "metrics.jsonl",
    "gpu_samples.csv",
    "structured_errors.jsonl",
    "report.md",
    "summary.csv",
)
LIVE_RESULT_FILE_NAMES = (
    "experiment.yaml",
    "environment.json",
    "metrics.jsonl",
    "system_samples.jsonl",
    "system_summary.json",
    "structured_errors.jsonl",
    "report.md",
    "summary.csv",
)
LIVE_CHUNKED_RESULT_FILE_NAMES = (
    "experiment.yaml",
    "environment.json",
    "metrics.jsonl",
    "system_samples.jsonl",
    "system_summary.json",
    "structured_errors.jsonl",
    "batch_summary.json",
    "report.md",
    "summary.csv",
)
CONCURRENCY_DIAGNOSTICS_RESULT_FILE_NAMES = (
    "environment.json",
    "metrics.jsonl",
    "system_samples.jsonl",
    "system_summary.json",
    "structured_errors.jsonl",
    "summary.json",
    "report.md",
)
MEMORY_RECOMMENDATION_RESULT_FILE_NAMES = (
    "gpu_memory_matrix.md",
    "gpu_memory_matrix.json",
    "gpu_memory_matrix.csv",
    "model_memory_recommendations.json",
    "model_memory_recommendation_catalog.schema.json",
)

STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES = (
    "experiment_id",
    "run_id",
    "mode",
    "dataset_id",
    "fixture_set_id",
    "status",
    "schema_version",
    "total_count",
    "json_parse_pass_count",
    "json_parse_pass_rate",
    "schema_pass_count",
    "schema_pass_rate",
    "business_pass_count",
    "business_pass_rate",
    "ids_exact_pass_count",
    "ids_exact_pass_rate",
    "reasoning_leak_count",
    "finish_length_count",
    "duplicate_id_count",
    "empty_text_count",
    "invalid_json_count",
    "schema_error_count",
)


def _format_report_value(value: Any) -> str:
    return "null" if value is None else str(value)


def _format_count_and_rate(summary: Mapping[str, Any], prefix: str) -> str:
    count = _format_report_value(summary.get(f"{prefix}_count"))
    rate = _format_report_value(summary.get(f"{prefix}_rate"))
    return f"count `{count}`, rate `{rate}`"


def build_structured_validation_summary_csv_row(
    summary: Mapping[str, Any],
    *,
    experiment_id: str | None = None,
    run_id: str | None = None,
    mode: str | None = None,
    dataset_id: str | None = None,
    fixture_set_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "mode": mode,
        "dataset_id": dataset_id,
        "fixture_set_id": fixture_set_id,
        "status": status,
        "schema_version": summary.get("schema_version"),
        "total_count": summary.get("total_count"),
        "json_parse_pass_count": summary.get("json_parse_pass_count"),
        "json_parse_pass_rate": summary.get("json_parse_pass_rate"),
        "schema_pass_count": summary.get("schema_pass_count"),
        "schema_pass_rate": summary.get("schema_pass_rate"),
        "business_pass_count": summary.get("business_pass_count"),
        "business_pass_rate": summary.get("business_pass_rate"),
        "ids_exact_pass_count": summary.get("ids_exact_pass_count"),
        "ids_exact_pass_rate": summary.get("ids_exact_pass_rate"),
        "reasoning_leak_count": summary.get("reasoning_leak_count"),
        "finish_length_count": summary.get("finish_length_count"),
        "duplicate_id_count": summary.get("duplicate_id_count"),
        "empty_text_count": summary.get("empty_text_count"),
        "invalid_json_count": summary.get("invalid_json_count"),
        "schema_error_count": summary.get("schema_error_count"),
    }


def write_json_file(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    sanitized_payload, _ = sanitize_metric_payload(payload)
    target.write_text(
        json.dumps(sanitized_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_yaml_file(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    sanitized_payload, _ = sanitize_metric_payload(payload)
    target.write_text(
        yaml.safe_dump(
            sanitized_payload,
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def write_csv_file(
    path: str | Path,
    *,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            sanitized_row, _ = sanitize_metric_payload(row)
            writer.writerow(sanitized_row)


def render_dry_run_report(
    *,
    config: ExperimentConfig,
    environment: Mapping[str, Any],
    run_id: str,
    dataset_rows: Sequence[Mapping[str, Any]],
    load_config_count: int,
    request_count: int,
    structured_error_count: int,
    structured_validation_summary: Mapping[str, Any] | None = None,
    output_files: Sequence[str] = RESULT_FILE_NAMES,
) -> str:
    privacy = config.privacy
    models = ", ".join(model.key for model in config.models)
    modes = ", ".join(config.modes)
    datasets = ", ".join(config.datasets)
    environment_lines = [
        f"- schema_version: `{environment['schema_version']}`",
        f"- dry_run: `{str(environment['dry_run']).lower()}`",
        f"- platform_system: `{environment['platform_system']}`",
        f"- platform_release: `{environment['platform_release']}`",
        f"- platform_machine: `{environment['platform_machine']}`",
        f"- python_version: `{environment['python_version']}`",
    ]
    if environment.get("git_commit"):
        environment_lines.append(f"- git_commit: `{environment['git_commit']}`")
    if environment.get("git_branch"):
        environment_lines.append(f"- git_branch: `{environment['git_branch']}`")

    dataset_lines = [
        (
            f"- `{row['dataset_id']}` — items: `{row['items_count']}`, "
            f"chars: `{row['chars']}`, "
            f"estimated_input_tokens: `{row['estimated_input_tokens']}`, "
            f"actual_input_tokens: `{_format_report_value(row['actual_input_tokens'])}`, "
            f"estimate_error_ratio: `{_format_report_value(row['estimate_error_ratio'])}`, "
            f"tokenizer: `{row['tokenizer']['method']}/{row['tokenizer']['family']}/{row['tokenizer']['version']}`, "
            f"hash: `{row['content_hash']}`"
        )
        for row in dataset_rows
    ]
    output_list = "\n".join(f"- `{file_name}`" for file_name in output_files)
    report_lines = [
        "# LM Studio Lab Report",
        "",
        "## Run",
        "",
        f"- experiment_id: `{config.experiment_id}`",
        f"- run_id: `{run_id}`",
        "- Mode: dry-run",
        "- Network: disabled",
        "- LM Studio API: not called",
        "- host application runtime imports: forbidden",
        "",
        "## Experiment",
        "",
        f"- models: `{models}`",
        f"- modes: `{modes}`",
        f"- datasets: `{datasets}`",
        f"- repeats: `{config.repeats}`",
        f"- warmup_runs: `{config.warmup_runs}`",
        f"- load_configs: `{load_config_count}`",
        f"- planned_requests: `{request_count}`",
        "",
        "## Environment",
        "",
        *environment_lines,
        "",
        "## Datasets",
        "",
        *dataset_lines,
        "",
        "## Metrics Summary",
        "",
        f"- planned metric rows: `{request_count}`",
        f"- structured_errors: `{structured_error_count}`",
        "- Live latency/quality metrics: not measured in dry-run",
        "",
    ]
    if structured_validation_summary is not None:
        report_lines.extend(
            [
                "## Structured Validation",
                "",
                "- Mode: offline structured validation",
                "- LM Studio API: not called",
                f"- schema_pass meaning: {SCHEMA_PASS_MEANING}",
                (
                    "- json_parse_pass: "
                    f"{_format_count_and_rate(structured_validation_summary, 'json_parse_pass')}"
                ),
                (
                    "- schema_pass: "
                    f"{_format_count_and_rate(structured_validation_summary, 'schema_pass')}"
                ),
                (
                    "- business_pass: "
                    f"{_format_count_and_rate(structured_validation_summary, 'business_pass')}"
                ),
                (
                    "- ids_exact_pass: "
                    f"{_format_count_and_rate(structured_validation_summary, 'ids_exact_pass')}"
                ),
                (
                    f"- reasoning_leak_count: `{_format_report_value(structured_validation_summary.get('reasoning_leak_count'))}`"
                ),
                (
                    f"- finish_length_count: `{_format_report_value(structured_validation_summary.get('finish_length_count'))}`"
                ),
                (
                    f"- duplicate_id_count: `{_format_report_value(structured_validation_summary.get('duplicate_id_count'))}`"
                ),
                (
                    f"- empty_text_count: `{_format_report_value(structured_validation_summary.get('empty_text_count'))}`"
                ),
                (
                    f"- invalid_json_count: `{_format_report_value(structured_validation_summary.get('invalid_json_count'))}`"
                ),
                (
                    f"- schema_error_count: `{_format_report_value(structured_validation_summary.get('schema_error_count'))}`"
                ),
                "",
            ]
        )
    report_lines.extend(
        [
            "## Privacy",
            "",
            f"- store_prompt_hash: `{str(privacy.store_prompt_hash).lower()}`",
            f"- store_prompt_text: `{str(privacy.store_prompt_text).lower()}`",
            f"- store_response_text: `{str(privacy.store_response_text).lower()}`",
            "- raw prompts/transcripts/responses/paths: not stored",
            "",
            "## Notes",
            "",
            "- JSONL files may be empty when a dry-run stage emits no records.",
            "- Output files:",
            output_list,
            "",
        ]
    )
    return "\n".join(report_lines)


def render_live_smoke_report(
    *,
    config: LiveSmokeConfig,
    environment: Mapping[str, Any],
    run_id: str,
    dataset_row: Mapping[str, Any],
    metric_row: Mapping[str, Any],
    structured_error_count: int,
    output_files: Sequence[str] = LIVE_RESULT_FILE_NAMES,
) -> str:
    model = config.models[0]
    validation = (
        metric_row.get("validation") if isinstance(metric_row.get("validation"), Mapping) else {}
    )
    tokens = metric_row.get("tokens") if isinstance(metric_row.get("tokens"), Mapping) else {}
    timing = metric_row.get("timing") if isinstance(metric_row.get("timing"), Mapping) else {}
    environment_lines = [
        f"- schema_version: `{environment['schema_version']}`",
        f"- dry_run: `{str(environment['dry_run']).lower()}`",
        f"- platform_system: `{environment['platform_system']}`",
        f"- platform_release: `{environment['platform_release']}`",
        f"- platform_machine: `{environment['platform_machine']}`",
        f"- python_version: `{environment['python_version']}`",
    ]
    output_list = "\n".join(f"- `{file_name}`" for file_name in output_files)
    report_lines = [
        "# LM Studio Lab Report",
        "",
        "## Run",
        "",
        f"- experiment_id: `{config.experiment_id}`",
        f"- run_id: `{run_id}`",
        "- Mode: live structured smoke",
        "- Network: enabled by --live",
        "- LM Studio API: called",
        "- host application runtime imports: forbidden",
        "",
        "## Experiment",
        "",
        f"- model_key: `{model.key}`",
        f"- model_id: `{model.model_id}`",
        f"- mode: `{config.modes[0]}`",
        f"- dataset: `{config.datasets[0]}`",
        f"- repeats: `{config.repeats}`",
        f"- warmup_runs: `{config.warmup_runs}`",
        "- planned_requests: `1`",
        "",
        "## Environment",
        "",
        *environment_lines,
        "",
        "## Dataset",
        "",
        (
            f"- `{dataset_row['dataset_id']}` — items: `{dataset_row['items_count']}`, "
            f"chars: `{dataset_row['chars']}`, "
            f"estimated_input_tokens: `{dataset_row['estimated_input_tokens']}`, "
            f"actual_input_tokens: `{_format_report_value(dataset_row['actual_input_tokens'])}`, "
            f"estimate_error_ratio: `{_format_report_value(dataset_row['estimate_error_ratio'])}`, "
            f"tokenizer: `{dataset_row['tokenizer']['method']}/{dataset_row['tokenizer']['family']}/{dataset_row['tokenizer']['version']}`, "
            f"hash: `{dataset_row['content_hash']}`"
        ),
        "",
        "## Metrics Summary",
        "",
        f"- endpoint_kind: `{_format_report_value(metric_row.get('endpoint_kind'))}`",
        f"- finish_reason: `{_format_report_value(validation.get('finish_reason'))}`",
        f"- json_parse_pass: `{_format_report_value(validation.get('json_parse_pass'))}`",
        f"- schema_pass: `{_format_report_value(validation.get('schema_pass'))}`",
        f"- business_pass: `{_format_report_value(validation.get('business_pass'))}`",
        f"- reasoning_leak: `{_format_report_value(validation.get('reasoning_leak'))}`",
        f"- error_category: `{_format_report_value(metric_row.get('error_category'))}`",
        f"- structured_errors: `{structured_error_count}`",
        f"- prompt_tokens: `{_format_report_value(tokens.get('prompt_tokens'))}`",
        f"- completion_tokens: `{_format_report_value(tokens.get('completion_tokens'))}`",
        f"- total_tokens: `{_format_report_value(tokens.get('total_tokens'))}`",
        f"- total_elapsed_ms: `{_format_report_value(timing.get('total_elapsed_ms'))}`",
        "",
        "## Privacy",
        "",
        f"- store_prompt_hash: `{str(config.privacy.store_prompt_hash).lower()}`",
        f"- store_prompt_text: `{str(config.privacy.store_prompt_text).lower()}`",
        f"- store_response_text: `{str(config.privacy.store_response_text).lower()}`",
        "- raw prompts/transcripts/responses/paths: not stored",
        "",
        "## Notes",
        "",
        "- Live path sends one explicit LM Studio compat request only when --live is set.",
        "- Output files:",
        output_list,
        "",
    ]
    return "\n".join(report_lines)


def render_live_chunked_smoke_report(
    *,
    config: LiveSmokeConfig,
    environment: Mapping[str, Any],
    run_id: str,
    dataset_row: Mapping[str, Any],
    batch_summary: Mapping[str, Any],
    structured_error_count: int,
    output_files: Sequence[str] = LIVE_CHUNKED_RESULT_FILE_NAMES,
) -> str:
    model = config.models[0]
    environment_lines = [
        f"- schema_version: `{environment['schema_version']}`",
        f"- dry_run: `{str(environment['dry_run']).lower()}`",
        f"- platform_system: `{environment['platform_system']}`",
        f"- platform_release: `{environment['platform_release']}`",
        f"- platform_machine: `{environment['platform_machine']}`",
        f"- python_version: `{environment['python_version']}`",
    ]
    output_list = "\n".join(f"- `{file_name}`" for file_name in output_files)
    report_lines = [
        "# LM Studio Lab Report",
        "",
        "## Run",
        "",
        f"- experiment_id: `{config.experiment_id}`",
        f"- run_id: `{run_id}`",
        "- Mode: live structured smoke (chunked)",
        "- Network: enabled by --live",
        "- LM Studio API: called",
        "- host application runtime imports: forbidden",
        "",
        "## Experiment",
        "",
        f"- model_key: `{model.key}`",
        f"- model_id: `{model.model_id}`",
        f"- mode: `{config.modes[0]}`",
        f"- dataset: `{config.datasets[0]}`",
        f"- repeats: `{config.repeats}`",
        f"- warmup_runs: `{config.warmup_runs}`",
        f"- effective_profile: `{_format_report_value(batch_summary.get('effective_profile'))}`",
        f"- warmup_is_productive: `{_format_report_value(batch_summary.get('warmup_is_productive'))}`",
        f"- warmup_policy: `{_format_report_value(batch_summary.get('warmup_policy'))}`",
        f"- app_concurrency: `{_format_report_value(batch_summary.get('app_concurrency'))}`",
        f"- chunks_count: `{_format_report_value(batch_summary.get('chunks_count'))}`",
        f"- chunk_size_blocks: `{_format_report_value(batch_summary.get('chunk_size_blocks'))}`",
        f"- planned_requests: `{_format_report_value(batch_summary.get('planned_requests'))}`",
        "",
        "## Environment",
        "",
        *environment_lines,
        "",
        "## Dataset",
        "",
        (
            f"- `{dataset_row['dataset_id']}` — items: `{dataset_row['items_count']}`, "
            f"chars: `{dataset_row['chars']}`, "
            f"estimated_input_tokens: `{dataset_row['estimated_input_tokens']}`, "
            f"actual_input_tokens: `{_format_report_value(dataset_row['actual_input_tokens'])}`, "
            f"estimate_error_ratio: `{_format_report_value(dataset_row['estimate_error_ratio'])}`, "
            f"tokenizer: `{dataset_row['tokenizer']['method']}/{dataset_row['tokenizer']['family']}/{dataset_row['tokenizer']['version']}`, "
            f"hash: `{dataset_row['content_hash']}`"
        ),
        "",
        "## Batch Summary",
        "",
        f"- warmup_request_count: `{_format_report_value(batch_summary.get('warmup_request_count'))}`",
        f"- measured_batches: `{_format_report_value(batch_summary.get('measured_batches'))}`",
        f"- measured_request_count: `{_format_report_value(batch_summary.get('measured_request_count'))}`",
        f"- all_chunks_pass: `{_format_report_value(batch_summary.get('all_chunks_pass'))}`",
        f"- batch_business_pass: `{_format_report_value(batch_summary.get('batch_business_pass'))}`",
        f"- all_ids_covered: `{_format_report_value(batch_summary.get('all_ids_covered'))}`",
        f"- missing_id_count: `{_format_report_value(batch_summary.get('missing_id_count'))}`",
        f"- duplicate_id_count: `{_format_report_value(batch_summary.get('duplicate_id_count'))}`",
        f"- failed_chunk_ids: `{_format_report_value(batch_summary.get('failed_chunk_ids'))}`",
        f"- json_parse_pass_count: `{_format_report_value(batch_summary.get('json_parse_pass_count'))}`",
        f"- schema_pass_count: `{_format_report_value(batch_summary.get('schema_pass_count'))}`",
        f"- business_pass_count: `{_format_report_value(batch_summary.get('business_pass_count'))}`",
        f"- reasoning_leak_count: `{_format_report_value(batch_summary.get('reasoning_leak_count'))}`",
        f"- finish_length_count: `{_format_report_value(batch_summary.get('finish_length_count'))}`",
        f"- structured_errors: `{structured_error_count}`",
        f"- total_prompt_tokens: `{_format_report_value(batch_summary.get('total_prompt_tokens'))}`",
        f"- total_completion_tokens: `{_format_report_value(batch_summary.get('total_completion_tokens'))}`",
        f"- total_tokens: `{_format_report_value(batch_summary.get('total_tokens'))}`",
        f"- total_latency_ms: `{_format_report_value(batch_summary.get('total_latency_ms'))}`",
        f"- avg_chunk_latency_ms: `{_format_report_value(batch_summary.get('avg_chunk_latency_ms'))}`",
        f"- max_chunk_latency_ms: `{_format_report_value(batch_summary.get('max_chunk_latency_ms'))}`",
        f"- warmup_wall_time_ms: `{_format_report_value(batch_summary.get('warmup_wall_time_ms'))}`",
        f"- parallel_batch_wall_time_ms: `{_format_report_value(batch_summary.get('parallel_batch_wall_time_ms'))}`",
        f"- total_batch_wall_time_ms: `{_format_report_value(batch_summary.get('total_batch_wall_time_ms'))}`",
        f"- avg_batch_wall_time_ms: `{_format_report_value(batch_summary.get('avg_batch_wall_time_ms'))}`",
        f"- max_batch_wall_time_ms: `{_format_report_value(batch_summary.get('max_batch_wall_time_ms'))}`",
        f"- end_to_end_wall_time_ms: `{_format_report_value(batch_summary.get('end_to_end_wall_time_ms'))}`",
        f"- avg_end_to_end_wall_time_ms: `{_format_report_value(batch_summary.get('avg_end_to_end_wall_time_ms'))}`",
        f"- sequential_baseline_wall_time_ms: `{_format_report_value(batch_summary.get('sequential_baseline_wall_time_ms'))}`",
        f"- baseline_end_to_end_wall_time_ms: `{_format_report_value(batch_summary.get('baseline_end_to_end_wall_time_ms'))}`",
        f"- speedup_vs_sequential_baseline: `{_format_report_value(batch_summary.get('speedup_vs_sequential_baseline'))}`",
        f"- speedup_excluding_warmup: `{_format_report_value(batch_summary.get('speedup_excluding_warmup'))}`",
        f"- speedup_including_warmup: `{_format_report_value(batch_summary.get('speedup_including_warmup'))}`",
        f"- effective_speedup: `{_format_report_value(batch_summary.get('effective_speedup'))}`",
        "",
        "## Privacy",
        "",
        f"- store_prompt_hash: `{str(config.privacy.store_prompt_hash).lower()}`",
        f"- store_prompt_text: `{str(config.privacy.store_prompt_text).lower()}`",
        f"- store_response_text: `{str(config.privacy.store_response_text).lower()}`",
        "- raw prompts/transcripts/responses/paths: not stored",
        "",
        "## Notes",
        "",
        "- Live chunked path sends measured LM Studio compat requests only when --live is set.",
        "- App-level chunk concurrency changes compat scheduling only; native load/unload/download flow stays untouched.",
        "- No native load/unload/download endpoints are called by this run.",
        "- Output files:",
        output_list,
        "",
    ]
    return "\n".join(report_lines)


def render_concurrency_diagnostics_report(
    *,
    environment: Mapping[str, Any],
    summary: Mapping[str, Any],
    output_files: Sequence[str] = CONCURRENCY_DIAGNOSTICS_RESULT_FILE_NAMES,
) -> str:
    environment_lines = [
        f"- schema_version: `{environment['schema_version']}`",
        f"- dry_run: `{str(environment['dry_run']).lower()}`",
        f"- platform_system: `{environment['platform_system']}`",
        f"- platform_release: `{environment['platform_release']}`",
        f"- platform_machine: `{environment['platform_machine']}`",
        f"- python_version: `{environment['python_version']}`",
    ]
    output_list = "\n".join(f"- `{file_name}`" for file_name in output_files)
    report_lines = [
        "# LM Studio Lab Concurrency Diagnostics Report",
        "",
        "## Run",
        "",
        f"- run_id: `{summary.get('run_id')}`",
        f"- diagnostic_kind: `{summary.get('diagnostic_kind')}`",
        f"- model_key: `{summary.get('model_key')}`",
        f"- model_id: `{summary.get('model_id')}`",
        f"- endpoint_kind: `{summary.get('endpoint_kind')}`",
        f"- app_concurrency: `{_format_report_value(summary.get('app_concurrency'))}`",
        "- Endpoint policy: compat `/v1/chat/completions` only",
        "- Native load/unload/download: not called",
        "- Raw prompt/response storage: disabled",
        "",
        "## Environment",
        "",
        *environment_lines,
        "",
        "## Summary",
        "",
        f"- request_count: `{_format_report_value(summary.get('request_count'))}`",
        f"- all_requests_pass: `{_format_report_value(summary.get('all_requests_pass'))}`",
        f"- json_parse_pass_count: `{_format_report_value(summary.get('json_parse_pass_count'))}`",
        f"- schema_pass_count: `{_format_report_value(summary.get('schema_pass_count'))}`",
        f"- business_pass_count: `{_format_report_value(summary.get('business_pass_count'))}`",
        f"- finish_length_count: `{_format_report_value(summary.get('finish_length_count'))}`",
        f"- reasoning_leak_count: `{_format_report_value(summary.get('reasoning_leak_count'))}`",
        f"- structured_error_count: `{_format_report_value(summary.get('structured_error_count'))}`",
        f"- total_wall_time_ms: `{_format_report_value(summary.get('total_wall_time_ms'))}`",
        f"- avg_request_latency_ms: `{_format_report_value(summary.get('avg_request_latency_ms'))}`",
        f"- max_request_latency_ms: `{_format_report_value(summary.get('max_request_latency_ms'))}`",
        "",
        "## Notes",
        "",
        "- This harness records only hashes, counts, token telemetry, timing, and safe validation flags.",
        "- No native `/api/v1/models/load`, unload, download, or generation-management endpoints are used.",
        "- Output files:",
        output_list,
        "",
    ]
    return "\n".join(report_lines)


def render_phase_metrics_report(summary: Mapping[str, Any]) -> str:
    """Render phase telemetry without overstating prefill/decode precision."""

    lines = [
        "# Phase-aware System Telemetry",
        "",
        f"- telemetry_valid: `{summary.get('telemetry_valid')}`",
        f"- memory_evidence_valid: `{summary.get('memory_evidence_valid')}`",
        f"- phase_order_valid: `{summary.get('phase_order_valid')}`",
        f"- timestamp_order_valid: `{summary.get('timestamp_order_valid')}`",
        f"- sampler_failure_count: `{summary.get('sampler_failure_count')}`",
        f"- configured_sample_interval_s: `{_format_report_value(summary.get('configured_sample_interval_s'))}`",
        f"- actual_sample_interval_s: `{_format_report_value(summary.get('actual_sample_interval_s'))}`",
        "",
        "## Phase evidence",
        "",
    ]
    phase_summaries = summary.get("phase_summaries")
    if isinstance(phase_summaries, Sequence) and not isinstance(phase_summaries, (str, bytes)):
        for phase in phase_summaries:
            if not isinstance(phase, Mapping):
                continue
            lines.append(
                f"- `{phase.get('marker')}`: samples `{phase.get('sample_count')}`, "
                f"derivation `{phase.get('derivation_methods')}`, confidence `{phase.get('confidence_levels')}`"
            )
    lines.extend(
        [
            "",
            "Coarse polling is never presented as precise prefill/decode evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def write_memory_recommendation_artifacts(
    output_dir: str | Path,
    catalog: MemoryRecommendationCatalog,
) -> dict[str, Path]:
    """Write one validated recommendation payload consistently across public formats."""

    if not isinstance(catalog, MemoryRecommendationCatalog):
        raise TypeError("catalog must be a MemoryRecommendationCatalog")
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    payload = catalog.to_dict()
    catalog.validate_payload(payload)
    for row in payload["recommendations"]:
        for field_name in ("model_artifact", "artifact_revision"):
            if _is_private_filesystem_reference(row[field_name]):
                raise ValueError("recommendation catalog contains publication-unsafe values")
    sanitized_payload, redaction_count = sanitize_metric_payload(payload)
    if redaction_count:
        raise ValueError("recommendation catalog contains publication-unsafe values")
    rows = sanitized_payload["recommendations"]
    assert isinstance(rows, list)
    paths = {
        "matrix_markdown": target / MEMORY_RECOMMENDATION_RESULT_FILE_NAMES[0],
        "matrix_json": target / MEMORY_RECOMMENDATION_RESULT_FILE_NAMES[1],
        "matrix_csv": target / MEMORY_RECOMMENDATION_RESULT_FILE_NAMES[2],
        "catalog_json": target / MEMORY_RECOMMENDATION_RESULT_FILE_NAMES[3],
        "catalog_schema": target / MEMORY_RECOMMENDATION_RESULT_FILE_NAMES[4],
    }
    encoded = json.dumps(sanitized_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    paths["matrix_json"].write_text(encoded, encoding="utf-8")
    paths["catalog_json"].write_text(encoded, encoding="utf-8")
    schema = memory_recommendation_catalog_schema()
    paths["catalog_schema"].write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fieldnames = tuple(schema["properties"]["recommendations"]["items"]["required"])
    csv_rows = tuple(
        {
            field_name: (
                json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                if isinstance(value, (list, dict))
                else value
            )
            for field_name, value in row.items()
        }
        for row in rows
    )
    write_csv_file(paths["matrix_csv"], fieldnames=fieldnames, rows=csv_rows)
    paths["matrix_markdown"].write_text(
        _render_memory_recommendation_markdown(
            schema_revision=catalog.schema_revision,
            fieldnames=fieldnames,
            rows=rows,
        ),
        encoding="utf-8",
    )
    return paths


def _is_private_filesystem_reference(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    return (
        lowered.startswith("file://")
        or normalized.startswith("~")
        or PurePosixPath(normalized).is_absolute()
        or PureWindowsPath(normalized).is_absolute()
    )


def _render_memory_recommendation_markdown(
    *,
    schema_revision: str,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# GPU Memory Recommendation Matrix",
        "",
        f"- schema_revision: `{schema_revision}`",
        "- Fixed model cost and context/concurrency overhead are reported separately.",
        "- Each concurrency lane uses its measured envelope; P1 is never multiplied to predict P2/P4.",
        "- Safety reserve is separate from measured peak. One run can never approve a profile.",
        "",
        "| " + " | ".join(fieldnames) + " |",
        "| " + " | ".join("---" for _ in fieldnames) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(_markdown_recommendation_value(row.get(field)) for field in fieldnames)
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _markdown_recommendation_value(value: Any) -> str:
    if isinstance(value, list):
        rendered = ", ".join(str(item) for item in value)
    elif value is None:
        rendered = "null"
    else:
        rendered = str(value)
    return rendered.replace("\n", " ").replace("|", "\\|")


__all__ = [
    "CONCURRENCY_DIAGNOSTICS_RESULT_FILE_NAMES",
    "LIVE_CHUNKED_RESULT_FILE_NAMES",
    "LIVE_RESULT_FILE_NAMES",
    "MEMORY_RECOMMENDATION_RESULT_FILE_NAMES",
    "RESULT_FILE_NAMES",
    "STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES",
    "build_structured_validation_summary_csv_row",
    "render_concurrency_diagnostics_report",
    "render_dry_run_report",
    "render_live_chunked_smoke_report",
    "render_live_smoke_report",
    "render_phase_metrics_report",
    "write_csv_file",
    "write_json_file",
    "write_memory_recommendation_artifacts",
    "write_yaml_file",
]
