from __future__ import annotations

import csv
from pathlib import Path

from lmstudio_labkit import write_run_artifacts


def validation_result(name: str, status: str, metrics: dict | None = None) -> dict:
    return {"name": name, "status": status, "category": None, "metrics": metrics or {}}


def result_row(
    *,
    cell_id: str,
    status: str,
    validation_results: list[dict],
    latency_ms: float,
    retry_count: int = 0,
    retry_recovered: bool = False,
    finish_reason: str = "stop",
) -> dict:
    return {
        "cell_id": cell_id,
        "model_key": "fake",
        "model_id": "fake/text",
        "task_id": "blocks",
        "axes": {
            "modality": "text",
            "language": "ru_ru",
            "structure_complexity": "medium",
            "volume": "single",
            "context_tier": "8192",
            "schema_variant": "hardened_const",
            "retry_policy": "retry1",
        },
        "repeat_index": 0,
        "status": status,
        "validation": {"status": status, "results": validation_results},
        "result": {
            "status": "ok",
            "latency_ms": latency_ms,
            "token_counts": {"prompt": 12, "completion": 34},
            "response_char_count": 56,
            "finish_reason": finish_reason,
        },
        "retry_count": retry_count,
        "retry_recovered": retry_recovered,
        "error_category": None if status == "pass" else "id_order_mismatch",
    }


def test_validation_metrics_are_flattened_into_cell_summary(tmp_path: Path) -> None:
    artifacts = write_run_artifacts(
        tmp_path / "run",
        {"run_id": "flattening", "cell_count": 1},
        [
            result_row(
                cell_id="cell_fail",
                status="fail",
                finish_reason="length",
                validation_results=[
                    validation_result("finish_reason_length", "fail", {"finish_reason": "length"}),
                    validation_result("markdown_fence_leak", "fail", {"fence_count": 2}),
                    validation_result("json_parse", "pass"),
                    validation_result("json_schema", "pass", {"error_count": 0}),
                    validation_result(
                        "id_exact",
                        "fail",
                        {
                            "missing_count": 1,
                            "unexpected_count": 2,
                            "duplicate_count": 3,
                            "order_mismatch": True,
                            "first_mismatch_index": 4,
                        },
                    ),
                    validation_result("no_placeholder_text", "fail", {"hit_count": 5}),
                    validation_result("no_reasoning_leak", "pass"),
                    validation_result("language_compliance", "pass"),
                    validation_result("image_ground_truth", "skip"),
                ],
                latency_ms=20.0,
            )
        ],
    )

    row = list(csv.DictReader(artifacts.cell_summary.open(encoding="utf-8")))[0]

    assert row["finish_reason_length_status"] == "fail"
    assert row["business_status"] == "fail"
    assert row["markdown_fence_count"] == "2"
    assert row["id_exact_status"] == "fail"
    assert row["missing_id_count"] == "1"
    assert row["unexpected_id_count"] == "2"
    assert row["duplicate_id_count"] == "3"
    assert row["order_mismatch"] == "True"
    assert row["first_mismatch_index"] == "4"
    assert row["placeholder_hit_count"] == "5"
    assert row["latency_ms"] == "20.0"
    assert row["prompt_tokens"] == "12"
    assert row["completion_tokens"] == "34"
    assert row["response_char_count"] == "56"


def test_validation_metrics_are_aggregated_into_model_summary(tmp_path: Path) -> None:
    pass_results = [
        validation_result("finish_reason_length", "pass"),
        validation_result("json_parse", "pass"),
        validation_result("json_schema", "pass"),
        validation_result("id_exact", "pass"),
        validation_result("language_compliance", "pass"),
    ]
    fail_results = [
        validation_result("finish_reason_length", "fail"),
        validation_result("json_parse", "pass"),
        validation_result("json_schema", "fail"),
        validation_result("id_exact", "fail"),
        validation_result("language_compliance", "pass"),
    ]
    artifacts = write_run_artifacts(
        tmp_path / "run",
        {"run_id": "model_flattening", "cell_count": 2},
        [
            result_row(
                cell_id="cell_pass",
                status="pass",
                validation_results=pass_results,
                latency_ms=10.0,
                retry_count=1,
                retry_recovered=True,
            ),
            result_row(
                cell_id="cell_fail",
                status="fail",
                validation_results=fail_results,
                latency_ms=30.0,
                retry_count=1,
                retry_recovered=False,
                finish_reason="length",
            ),
        ],
    )

    row = list(csv.DictReader(artifacts.model_summary.open(encoding="utf-8")))[0]

    assert row["attempt_count"] == "2"
    assert row["pass_count"] == "1"
    assert row["fail_count"] == "1"
    assert row["pass_rate"] == "0.5"
    assert row["json_parse_pass_rate"] == "1.0"
    assert row["schema_pass_rate"] == "0.5"
    assert row["id_exact_pass_rate"] == "0.5"
    assert row["language_pass_rate"] == "1.0"
    assert row["retry_attempted_count"] == "2"
    assert row["retry_recovered_count"] == "1"
    assert row["retry_dependency_rate"] == "0.5"
    assert row["finish_length_count"] == "1"
    assert row["median_latency_ms"] == "20.0"
    assert row["p95_latency_ms"] == "30.0"
