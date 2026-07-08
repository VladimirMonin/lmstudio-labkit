from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRUCTURED_MATRIX_ROOT = PROJECT_ROOT / "experiments" / "lmstudio" / "structured_matrix"
CONFIG_ROOT = STRUCTURED_MATRIX_ROOT / "configs"
SUITE_ROOT = STRUCTURED_MATRIX_ROOT / "suites"
BASELINE_CONFIG = CONFIG_ROOT / "matrix.live_small_text_remote.e2b_e4b.yaml"
WARMUP_CONFIG = CONFIG_ROOT / "matrix.live_small_text_remote_warmup.e2b_e4b.yaml"
REMOTE_SUITE = SUITE_ROOT / "l3_16_live_small_text_remote.yaml"
EXPECTED_MODEL_IDS = {"google/gemma-4-e2b", "google/gemma-4-e4b"}
EXPECTED_AXES = {
    "modality": ["text"],
    "language": ["ru_ru"],
    "structure_complexity": ["medium"],
    "volume": ["single"],
    "context_tier": [8192],
    "schema_variant": ["hardened_const"],
    "retry_policy": ["off"],
    "execution_mode": ["cold_per_request"],
    "execution_target": ["remote_link"],
    "resource_telemetry_mode": ["timing_only"],
    "lmstudio_parallel": [1],
    "app_concurrency": [1],
    "queue_pressure_mode": [False],
    "text_interaction_mode": ["single_question"],
}


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _planned_cell_count(payload: dict[str, Any]) -> int:
    axes = payload["axes"]
    axis_values = [axes[name] for name in sorted(axes)]
    axis_product = tuple(product(*axis_values))
    return len(payload["models"]) * len(payload["tasks"]) * len(axis_product)


def _assert_remote_small_text_config(
    payload: dict[str, Any],
    *,
    expected_run_id: str,
    expected_cache_mode: str,
    expected_max_requests: int,
) -> None:
    assert payload["run_id"] == expected_run_id
    assert {model["model_id"] for model in payload["models"]} == EXPECTED_MODEL_IDS
    assert len(payload["models"]) == 2
    assert len(payload["tasks"]) == 1
    assert _planned_cell_count(payload) == 2

    task = payload["tasks"][0]
    assert task["modality"] == "text"
    assert task["language"] == "ru_ru"
    assert task["language_policy"] == "strict_ru"
    assert task["structure_complexity"] == "medium"
    assert task["volume"] == "single"
    assert task["expected_ids"] == [0, 1]

    axes = payload["axes"]
    for name, expected in EXPECTED_AXES.items():
        assert axes[name] == expected
    assert axes["cache_mode"] == [expected_cache_mode]
    assert axes["resource_telemetry_mode"] == ["timing_only"]

    assert payload["structured_runtime"] == {"strict_json_schema": True}
    remote_policy = payload["remote_link"]["telemetry_policy"]
    assert payload["remote_link"]["enabled"] is True
    assert remote_policy["base_url_kind"] == "remote"
    assert remote_policy["scheme"] == "https"
    assert remote_policy["raw_base_url_stored"] is False
    assert remote_policy["raw_prompt_response_stored"] is False
    assert "base_url" in remote_policy["forbidden_artifact_fields"]
    assert "prompt" in remote_policy["forbidden_artifact_fields"]
    assert "response" in remote_policy["forbidden_artifact_fields"]
    assert {"base_url_kind", "scheme", "endpoint_family", "status", "timing_ms"}.issubset(
        remote_policy["allowed_artifact_fields"]
    )
    assert "execution_target" in remote_policy["allowed_artifact_fields"]
    assert "resource_telemetry_mode" in remote_policy["allowed_artifact_fields"]

    safety = payload["safety"]
    assert safety == {
        "live": True,
        "allow_model_downloads": False,
        "allow_model_loads": True,
        "allow_remote_base_url": True,
        "allow_raw_prompt_response_artifacts": False,
        "allow_image_live": False,
        "allow_stress": False,
        "max_requests": expected_max_requests,
        "max_runtime_minutes": safety["max_runtime_minutes"],
        "max_context_tier": 8192,
        "max_models": 2,
        "max_repeats": 1,
    }


def test_l3_16_remote_text_configs_parse_and_plan_offline() -> None:
    baseline = _load_yaml(BASELINE_CONFIG)
    warmup = _load_yaml(WARMUP_CONFIG)

    _assert_remote_small_text_config(
        baseline,
        expected_run_id="matrix_live_small_text_remote_e2b_e4b",
        expected_cache_mode="none",
        expected_max_requests=2,
    )
    _assert_remote_small_text_config(
        warmup,
        expected_run_id="matrix_live_small_text_remote_warmup_e2b_e4b",
        expected_cache_mode="warmup_first",
        expected_max_requests=4,
    )

    warmup_policy = warmup["remote_link"]["telemetry_policy"]
    assert warmup_policy["warmup_request_recorded"] is True
    assert warmup_policy["measured_request_recorded"] is True
    assert warmup_policy["kv_reuse_proven"] is False
    assert "is_warmup_request" in warmup_policy["allowed_artifact_fields"]
    assert "cache_group_id" in warmup_policy["allowed_artifact_fields"]


def test_l3_16_remote_suite_orders_warmup_after_baseline() -> None:
    suite = _load_yaml(REMOTE_SUITE)

    assert suite == {
        "suite_id": "l3_16_live_small_text_remote",
        "stop_on_failure": True,
        "configs": [
            {
                "config": "../configs/matrix.live_small_text_remote.e2b_e4b.yaml",
                "required": True,
            },
            {
                "config": "../configs/matrix.live_small_text_remote_warmup.e2b_e4b.yaml",
                "required": True,
                "run_after": ["matrix_live_small_text_remote_e2b_e4b"],
            },
        ],
    }

    for entry in suite["configs"]:
        assert (REMOTE_SUITE.parent / entry["config"]).resolve().is_file()
    assert "run_after" not in suite["configs"][0]
    assert suite["configs"][1]["run_after"] == [
        _load_yaml(BASELINE_CONFIG)["run_id"],
    ]
