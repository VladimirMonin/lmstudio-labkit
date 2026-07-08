"""Offline structured matrix planning and fake execution harness."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import product
from pathlib import Path
from typing import Any

from .config import ExperimentConfig, load_experiment_config, load_raw_experiment_config
from .datasets import DatasetManifest, load_dataset_manifest
from .metrics import SCHEMA_VERSION, append_jsonl_record
from .privacy import find_privacy_violations
from .report import write_csv_file, write_json_file
from .structured import validate_factual_blocks_response

MATRIX_PLAN_OUTPUT_FILE_NAMES = (
    "experiment.yaml",
    "planner_summary.json",
    "matrix_cells.jsonl",
    "cell_summary.csv",
    "privacy_scan.json",
    "report.md",
)
MATRIX_FAKE_RUN_OUTPUT_FILE_NAMES = (
    "experiment.yaml",
    "planner_summary.json",
    "cell_results.jsonl",
    "cell_summary.csv",
    "model_summary.csv",
    "failure_summary.csv",
    "retry_summary.csv",
    "resource_summary.csv",
    "privacy_scan.json",
    "report.md",
)
MATRIX_CELL_FIELDNAMES = (
    "run_id",
    "cell_id",
    "model_key",
    "mode",
    "dataset_id",
    "modality",
    "language",
    "structure_complexity",
    "volume",
    "context_tier",
    "schema_variant",
    "retry_policy",
    "repeat_index",
    "status",
    "business_pass",
    "error_category",
)
MODEL_SUMMARY_FIELDNAMES = (
    "run_id",
    "model_key",
    "planned_cells",
    "completed_cells",
    "business_pass_count",
    "business_pass_rate",
)
FAILURE_SUMMARY_FIELDNAMES = (
    "run_id",
    "failure_category",
    "affected_models",
    "count",
)
RETRY_SUMMARY_FIELDNAMES = (
    "run_id",
    "retry_policy",
    "attempt_count",
    "business_pass_count",
    "recovery_rate",
)
RESOURCE_SUMMARY_FIELDNAMES = (
    "run_id",
    "model_key",
    "context_tier",
    "estimated_input_tokens",
    "actual_input_tokens",
    "estimated_output_tokens",
    "actual_output_tokens",
    "latency_ms",
)
_SAFE_ID_REPLACEMENTS = str.maketrans({"/": "_", "\\": "_", " ": "_"})


@dataclass(frozen=True, slots=True)
class StructuredMatrixPlan:
    config: ExperimentConfig
    run_id: str
    matrix_axes: Mapping[str, tuple[str, ...]]
    cells: tuple[dict[str, Any], ...]

    def planner_summary(self) -> dict[str, Any]:
        selected_axes = {key: list(value) for key, value in self.matrix_axes.items()}
        planned_repeats = self.config.repeats
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "experiment_id": self.config.experiment_id,
            "config_hash": _hash_text(json.dumps(self.config.to_dict(), sort_keys=True)),
            "selected_axes": selected_axes,
            "cell_count": len(self.cells),
            "planned_repeats": planned_repeats,
            "live_mode": False,
            "offline_mode": True,
            "fake_runner": False,
            "privacy_mode": "publication_safe",
            "schema_versions": [SCHEMA_VERSION],
            "raw_prompt_response_stored": False,
        }


def _hash_text(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def _safe_id(value: str) -> str:
    safe = value.translate(_SAFE_ID_REPLACEMENTS)
    return "".join(
        character if character.isalnum() or character in "_.-" else "_" for character in safe
    )


def _require_string_axis(value: Any, *, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = tuple(value)
    else:
        raise ValueError(f"matrix.{field_name} must be a string or list of strings")
    normalized = tuple(str(item).strip() for item in items if str(item).strip())
    if not normalized:
        raise ValueError(f"matrix.{field_name} must not be empty")
    return normalized


def _matrix_axis(
    matrix_payload: Mapping[str, Any],
    field_name: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if field_name not in matrix_payload:
        return default
    return _require_string_axis(matrix_payload[field_name], field_name=field_name)


def _load_matrix_axes(raw_payload: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    raw_matrix = raw_payload.get("matrix", {})
    if raw_matrix is None:
        raw_matrix = {}
    if not isinstance(raw_matrix, Mapping):
        raise ValueError("matrix must be a mapping")
    retry_default = (
        ("retry1",) if int(raw_payload.get("business_failure_retry_limit") or 0) > 0 else ("off",)
    )
    schema_default = (str(raw_payload.get("structured_schema_variant") or "baseline_loose"),)
    return {
        "modality": _matrix_axis(raw_matrix, "modality", ("text",)),
        "language": _matrix_axis(raw_matrix, "language", ("en_en",)),
        "structure_complexity": _matrix_axis(raw_matrix, "structure_complexity", ("simple",)),
        "volume": _matrix_axis(raw_matrix, "volume", ("single",)),
        "schema_variant": _matrix_axis(raw_matrix, "schema_variant", schema_default),
        "retry_policy": _matrix_axis(raw_matrix, "retry_policy", retry_default),
    }


def _load_config_and_axes(
    config_path: str | Path,
) -> tuple[bytes, ExperimentConfig, dict[str, tuple[str, ...]]]:
    config_bytes = Path(config_path).read_bytes()
    _, raw_payload = load_raw_experiment_config(config_path)
    config = load_experiment_config(config_path)
    axes = _load_matrix_axes(raw_payload)
    return config_bytes, config, axes


def _default_run_id(experiment_id: str, *, fake_run: bool = False) -> str:
    suffix = "matrix_fake_run" if fake_run else "matrix_plan"
    return f"{experiment_id}_{suffix}"


def _prepare_run_dir(*, output_root: Path, run_id: str, experiment_id: str) -> Path:
    run_dir = output_root / f"run_{run_id}_{experiment_id}"
    if run_dir.exists():
        raise FileExistsError(
            f"matrix output already exists for run_id {run_id!r} and experiment_id {experiment_id!r}"
        )
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _context_tier(load_config: Mapping[str, Any]) -> str:
    value = load_config.get("context_length")
    return str(value) if value is not None else "model-specific"


def build_structured_matrix_plan(
    config_path: str | Path, *, run_id: str | None = None
) -> StructuredMatrixPlan:
    _, config, axes = _load_config_and_axes(config_path)
    resolved_run_id = run_id or _default_run_id(config.experiment_id)
    dataset_manifests = {
        dataset_id: load_dataset_manifest(dataset_id) for dataset_id in config.datasets
    }

    cells: list[dict[str, Any]] = []
    cell_index = 1
    axis_names = tuple(axes)
    axis_products = tuple(product(*(axes[name] for name in axis_names)))
    for model in config.models:
        for load_config in model.iter_load_configs():
            context_tier = _context_tier(load_config)
            for mode in config.modes:
                for dataset_id, manifest in dataset_manifests.items():
                    for repeat_index in range(1, config.repeats + 1):
                        for axis_values in axis_products:
                            axis_payload = dict(zip(axis_names, axis_values, strict=True))
                            cell_id = f"cell_{cell_index:05d}"
                            request_metadata = {
                                "cell_id": cell_id,
                                "model_key": model.key,
                                "mode": mode,
                                "dataset_id": dataset_id,
                                "dataset_hash": manifest.content_hash,
                                "context_tier": context_tier,
                                "repeat_index": repeat_index,
                                **axis_payload,
                            }
                            cells.append(
                                {
                                    "schema_version": SCHEMA_VERSION,
                                    "run_id": resolved_run_id,
                                    "cell_id": cell_id,
                                    "model_key": model.key,
                                    "mode": mode,
                                    "dataset_id": dataset_id,
                                    "dataset_hash": manifest.content_hash,
                                    "dataset_items_count": manifest.items_count,
                                    "estimated_input_tokens": manifest.estimated_input_tokens,
                                    "actual_input_tokens": manifest.actual_input_tokens,
                                    "context_tier": context_tier,
                                    "load_config_hash": _hash_text(
                                        json.dumps(load_config, sort_keys=True)
                                    ),
                                    "repeat_index": repeat_index,
                                    "request_metadata_hash": _hash_text(
                                        json.dumps(request_metadata, sort_keys=True)
                                    ),
                                    "raw_prompt_response_stored": False,
                                    "status": "planned",
                                    **axis_payload,
                                }
                            )
                            cell_index += 1
    return StructuredMatrixPlan(
        config=config,
        run_id=resolved_run_id,
        matrix_axes=axes,
        cells=tuple(cells),
    )


def _cell_summary_row(
    cell: Mapping[str, Any], *, status: str, result: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    result = result or {}
    return {
        "run_id": cell.get("run_id"),
        "cell_id": cell.get("cell_id"),
        "model_key": cell.get("model_key"),
        "mode": cell.get("mode"),
        "dataset_id": cell.get("dataset_id"),
        "modality": cell.get("modality"),
        "language": cell.get("language"),
        "structure_complexity": cell.get("structure_complexity"),
        "volume": cell.get("volume"),
        "context_tier": cell.get("context_tier"),
        "schema_variant": cell.get("schema_variant"),
        "retry_policy": cell.get("retry_policy"),
        "repeat_index": cell.get("repeat_index"),
        "status": status,
        "business_pass": result.get("business_pass"),
        "error_category": result.get("error_category"),
    }


def _scan_privacy_payloads(
    payloads: Sequence[Mapping[str, Any]], *, artifact_names: Sequence[str]
) -> dict[str, Any]:
    violations: list[str] = []
    for index, payload in enumerate(payloads):
        violations.extend(find_privacy_violations(payload, context=f"artifact[{index}]"))
    categories = sorted({violation.rsplit(" ", 1)[-1] for violation in violations})
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": "matrix-artifacts.v1",
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "violation_categories": categories,
        "scanned_artifact_names": list(artifact_names),
    }


def _render_matrix_report(
    *,
    title: str,
    plan: StructuredMatrixPlan,
    status: str,
    output_files: Sequence[str],
    result_summary: Mapping[str, Any] | None = None,
) -> str:
    summary = plan.planner_summary()
    output_list = "\n".join(f"- `{file_name}`" for file_name in output_files)
    lines = [
        title,
        "",
        "## Run",
        "",
        f"- experiment_id: `{plan.config.experiment_id}`",
        f"- run_id: `{plan.run_id}`",
        "- Mode: offline structured matrix",
        "- Network: disabled",
        "- LM Studio API: not called",
        f"- status: `{status}`",
        "",
        "## Plan",
        "",
        f"- cell_count: `{summary['cell_count']}`",
        f"- planned_repeats: `{summary['planned_repeats']}`",
        f"- selected_axes: `{json.dumps(summary['selected_axes'], sort_keys=True)}`",
        "",
    ]
    if result_summary is not None:
        lines.extend(
            [
                "## Fake Runner Summary",
                "",
                f"- completed_cells: `{result_summary.get('completed_cells')}`",
                f"- business_pass_count: `{result_summary.get('business_pass_count')}`",
                f"- failure_count: `{result_summary.get('failure_count')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Privacy",
            "",
            "- raw prompts: not stored",
            "- raw responses: not stored",
            "- raw local paths: not stored",
            "- artifacts contain hashes, counts, statuses, model identifiers, axis values, and validation summaries only",
            "",
            "## Output Files",
            "",
            output_list,
            "",
        ]
    )
    return "\n".join(lines)


def create_structured_matrix_plan_artifacts(
    config_path: str | Path,
    *,
    output_root: str | Path,
    run_id: str | None = None,
) -> Path:
    config_bytes, _, _ = _load_config_and_axes(config_path)
    plan = build_structured_matrix_plan(config_path, run_id=run_id)
    run_dir = _prepare_run_dir(
        output_root=Path(output_root),
        run_id=plan.run_id,
        experiment_id=plan.config.experiment_id,
    )
    (run_dir / "experiment.yaml").write_bytes(config_bytes)
    planner_summary = plan.planner_summary()
    write_json_file(run_dir / "planner_summary.json", planner_summary)
    matrix_path = run_dir / "matrix_cells.jsonl"
    matrix_path.write_text("", encoding="utf-8")
    for cell in plan.cells:
        append_jsonl_record(matrix_path, cell)
    write_csv_file(
        run_dir / "cell_summary.csv",
        fieldnames=MATRIX_CELL_FIELDNAMES,
        rows=[_cell_summary_row(cell, status="planned") for cell in plan.cells],
    )
    privacy_scan = _scan_privacy_payloads(
        [planner_summary, *plan.cells],
        artifact_names=MATRIX_PLAN_OUTPUT_FILE_NAMES,
    )
    write_json_file(run_dir / "privacy_scan.json", privacy_scan)
    (run_dir / "report.md").write_text(
        _render_matrix_report(
            title="# LM Studio Lab Structured Matrix Plan",
            plan=plan,
            status="planned",
            output_files=MATRIX_PLAN_OUTPUT_FILE_NAMES,
        ),
        encoding="utf-8",
    )
    return run_dir


def _expected_ids_for_dataset(manifest: DatasetManifest) -> tuple[int, ...]:
    return tuple(range(manifest.items_count))


def _fake_response_for_cell(cell: Mapping[str, Any], expected_ids: Sequence[int]) -> str:
    fail_this_cell = str(cell.get("schema_variant")) == "fake_failure"
    returned_ids = tuple(expected_ids)
    if fail_this_cell and returned_ids:
        returned_ids = returned_ids[:-1]
    return json.dumps(
        {
            "schema_version": "factual_blocks.v1",
            "status": "success",
            "blocks": [
                {
                    "block_id": block_id,
                    "normalized_text": f"Synthetic normalized block {block_id}.",
                    "status": "success",
                    "warnings": [],
                }
                for block_id in returned_ids
            ],
            "warnings": [],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _build_fake_result_record(
    *,
    cell: Mapping[str, Any],
    manifest: DatasetManifest,
    fake_output: str,
) -> dict[str, Any]:
    expected_ids = _expected_ids_for_dataset(manifest)
    validation = validate_factual_blocks_response(fake_output, expected_block_ids=expected_ids)
    validation_payload = validation.to_dict()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": cell["run_id"],
        "cell_id": cell["cell_id"],
        "model_key": cell["model_key"],
        "mode": cell["mode"],
        "dataset_id": cell["dataset_id"],
        "dataset_hash": cell["dataset_hash"],
        "modality": cell["modality"],
        "language": cell["language"],
        "structure_complexity": cell["structure_complexity"],
        "volume": cell["volume"],
        "context_tier": cell["context_tier"],
        "schema_variant": cell["schema_variant"],
        "retry_policy": cell["retry_policy"],
        "repeat_index": cell["repeat_index"],
        "input_hash": cell["request_metadata_hash"],
        "output_hash": _hash_text(fake_output),
        "output_chars": len(fake_output),
        "estimated_input_tokens": manifest.estimated_input_tokens,
        "actual_input_tokens": manifest.actual_input_tokens,
        "estimated_output_tokens": len(fake_output) // 3,
        "actual_output_tokens": None,
        "latency_ms": 0.0,
        "fake_runner": True,
        "offline_mode": True,
        "raw_prompt_response_stored": False,
        "json_parse_pass": validation.json_parse_pass,
        "schema_pass": validation.schema_pass,
        "business_pass": validation.business_pass,
        "ids_exact_pass": validation.ids_exact_pass,
        "reasoning_leak": validation.reasoning_leak,
        "error_category": validation.error_category,
        "validation": validation_payload,
    }


def _aggregate_model_summary(
    run_id: str, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_model: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        by_model[str(record["model_key"])].append(record)
    rows: list[dict[str, Any]] = []
    for model_key, model_records in sorted(by_model.items()):
        pass_count = sum(record.get("business_pass") is True for record in model_records)
        total = len(model_records)
        rows.append(
            {
                "run_id": run_id,
                "model_key": model_key,
                "planned_cells": total,
                "completed_cells": total,
                "business_pass_count": pass_count,
                "business_pass_rate": pass_count / total if total else None,
            }
        )
    return rows


def _aggregate_failure_summary(
    run_id: str, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        category = str(record.get("error_category") or "none")
        if category == "none":
            continue
        by_category[category][str(record["model_key"])] += 1
    return [
        {
            "run_id": run_id,
            "failure_category": category,
            "affected_models": ";".join(sorted(counter)),
            "count": sum(counter.values()),
        }
        for category, counter in sorted(by_category.items())
    ]


def _aggregate_retry_summary(
    run_id: str, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_policy: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        by_policy[str(record["retry_policy"])].append(record)
    return [
        {
            "run_id": run_id,
            "retry_policy": retry_policy,
            "attempt_count": len(policy_records),
            "business_pass_count": sum(
                record.get("business_pass") is True for record in policy_records
            ),
            "recovery_rate": None if retry_policy == "off" else 0.0,
        }
        for retry_policy, policy_records in sorted(by_policy.items())
    ]


def _aggregate_resource_summary(
    run_id: str, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        key = (str(record["model_key"]), str(record["context_tier"]))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "run_id": run_id,
                "model_key": key[0],
                "context_tier": key[1],
                "estimated_input_tokens": record.get("estimated_input_tokens"),
                "actual_input_tokens": record.get("actual_input_tokens"),
                "estimated_output_tokens": record.get("estimated_output_tokens"),
                "actual_output_tokens": record.get("actual_output_tokens"),
                "latency_ms": record.get("latency_ms"),
            }
        )
    return rows


def create_structured_matrix_fake_run_artifacts(
    config_path: str | Path,
    *,
    output_root: str | Path,
    run_id: str | None = None,
) -> Path:
    config_bytes, _, _ = _load_config_and_axes(config_path)
    plan = build_structured_matrix_plan(
        config_path,
        run_id=run_id
        or _default_run_id(load_experiment_config(config_path).experiment_id, fake_run=True),
    )
    run_dir = _prepare_run_dir(
        output_root=Path(output_root),
        run_id=plan.run_id,
        experiment_id=plan.config.experiment_id,
    )
    (run_dir / "experiment.yaml").write_bytes(config_bytes)
    planner_summary = {**plan.planner_summary(), "fake_runner": True}
    write_json_file(run_dir / "planner_summary.json", planner_summary)

    manifests = {
        dataset_id: load_dataset_manifest(dataset_id) for dataset_id in plan.config.datasets
    }
    records: list[dict[str, Any]] = []
    results_path = run_dir / "cell_results.jsonl"
    results_path.write_text("", encoding="utf-8")
    for cell in plan.cells:
        manifest = manifests[str(cell["dataset_id"])]
        fake_output = _fake_response_for_cell(cell, _expected_ids_for_dataset(manifest))
        result = _build_fake_result_record(cell=cell, manifest=manifest, fake_output=fake_output)
        records.append(result)
        append_jsonl_record(results_path, result)

    write_csv_file(
        run_dir / "cell_summary.csv",
        fieldnames=MATRIX_CELL_FIELDNAMES,
        rows=[_cell_summary_row(record, status="completed", result=record) for record in records],
    )
    model_rows = _aggregate_model_summary(plan.run_id, records)
    failure_rows = _aggregate_failure_summary(plan.run_id, records)
    retry_rows = _aggregate_retry_summary(plan.run_id, records)
    resource_rows = _aggregate_resource_summary(plan.run_id, records)
    write_csv_file(
        run_dir / "model_summary.csv", fieldnames=MODEL_SUMMARY_FIELDNAMES, rows=model_rows
    )
    write_csv_file(
        run_dir / "failure_summary.csv",
        fieldnames=FAILURE_SUMMARY_FIELDNAMES,
        rows=failure_rows,
    )
    write_csv_file(
        run_dir / "retry_summary.csv", fieldnames=RETRY_SUMMARY_FIELDNAMES, rows=retry_rows
    )
    write_csv_file(
        run_dir / "resource_summary.csv",
        fieldnames=RESOURCE_SUMMARY_FIELDNAMES,
        rows=resource_rows,
    )
    privacy_scan = _scan_privacy_payloads(
        [planner_summary, *records, *model_rows, *failure_rows, *retry_rows, *resource_rows],
        artifact_names=MATRIX_FAKE_RUN_OUTPUT_FILE_NAMES,
    )
    write_json_file(run_dir / "privacy_scan.json", privacy_scan)
    business_pass_count = sum(record.get("business_pass") is True for record in records)
    result_summary = {
        "completed_cells": len(records),
        "business_pass_count": business_pass_count,
        "failure_count": len(records) - business_pass_count,
    }
    (run_dir / "report.md").write_text(
        _render_matrix_report(
            title="# LM Studio Lab Structured Matrix Fake Run",
            plan=plan,
            status="completed",
            output_files=MATRIX_FAKE_RUN_OUTPUT_FILE_NAMES,
            result_summary=result_summary,
        ),
        encoding="utf-8",
    )
    return run_dir


__all__ = [
    "MATRIX_CELL_FIELDNAMES",
    "MATRIX_FAKE_RUN_OUTPUT_FILE_NAMES",
    "MATRIX_PLAN_OUTPUT_FILE_NAMES",
    "StructuredMatrixPlan",
    "build_structured_matrix_plan",
    "create_structured_matrix_fake_run_artifacts",
    "create_structured_matrix_plan_artifacts",
]
