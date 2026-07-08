from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRUCTURED_MATRIX_ROOT = PROJECT_ROOT / "experiments" / "lmstudio" / "structured_matrix"
CONFIG_ROOT = STRUCTURED_MATRIX_ROOT / "configs"
SUITE_ROOT = STRUCTURED_MATRIX_ROOT / "suites"
WAVE1_CONFIG = CONFIG_ROOT / "matrix.l3_17_text_quality_remote.e2b_e4b.yaml"
WAVE2_CONFIG = CONFIG_ROOT / "matrix.l3_17_text_quality_remote.12b.yaml"
SUITE = SUITE_ROOT / "l3_17_text_quality_screening.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _planned_cell_count(payload: dict[str, Any]) -> int:
    axes = payload["axes"]
    compatible = 0
    for task in payload["tasks"]:
        values = [axes[name] for name in sorted(axes)]
        for combo in product(*values):
            axis = dict(zip(sorted(axes), combo, strict=True))
            if axis["modality"] != task["modality"]:
                continue
            if axis["language"] != task["language"]:
                continue
            if axis["structure_complexity"] != task["structure_complexity"]:
                continue
            if axis["volume"] != task["volume"]:
                continue
            compatible += 1
    return len(payload["models"]) * compatible * payload.get("repeats", 1)


def _assert_l3_17_config(
    payload: dict[str, Any], *, expected_run_id: str, expected_models: set[str], max_requests: int
) -> None:
    assert payload["run_id"] == expected_run_id
    assert {model["model_id"] for model in payload["models"]} == expected_models
    assert {model["supported_modalities"][0] for model in payload["models"]} == {"text"}
    assert {model["supported_context_tiers"][0] for model in payload["models"]} == {8192}
    assert {task["modality"] for task in payload["tasks"]} == {"text"}
    assert {task["language"] for task in payload["tasks"]} == {"ru_ru", "ru_en_mixed"}

    axes = payload["axes"]
    assert axes["modality"] == ["text"]
    assert axes["language"] == ["ru_ru", "ru_en_mixed"]
    assert axes["context_tier"] == [8192]
    assert axes["schema_variant"] == ["hardened_const"]
    assert axes["retry_policy"] == ["off", "retry1"]
    assert axes["execution_mode"] == ["cold_per_request"]
    assert axes["execution_target"] == ["remote_link"]
    assert axes["resource_telemetry_mode"] == ["timing_only"]
    assert axes["cache_mode"] == ["none"]
    assert axes["lmstudio_parallel"] == [1]
    assert axes["app_concurrency"] == [1]
    assert axes["queue_pressure_mode"] == [False]
    assert axes["text_interaction_mode"] == ["single_question"]
    assert _planned_cell_count(payload) * 3 // 2 == max_requests

    assert payload["structured_runtime"] == {"strict_json_schema": True}
    policy = payload["remote_link"]["telemetry_policy"]
    assert payload["remote_link"]["enabled"] is True
    assert policy["raw_base_url_stored"] is False
    assert policy["raw_prompt_response_stored"] is False
    assert policy["kv_reuse_proven"] is False
    assert {"base_url", "prompt", "response", "messages", "content"}.issubset(
        policy["forbidden_artifact_fields"]
    )

    safety = payload["safety"]
    assert safety == {
        "live": True,
        "allow_model_downloads": False,
        "allow_model_loads": True,
        "allow_remote_base_url": True,
        "allow_raw_prompt_response_artifacts": False,
        "allow_image_live": False,
        "allow_stress": False,
        "max_requests": max_requests,
        "max_runtime_minutes": 60,
        "max_context_tier": 8192,
        "max_models": len(expected_models),
        "max_repeats": 1,
    }


def test_l3_17_text_quality_configs_are_staged_and_guarded() -> None:
    wave1 = _load_yaml(WAVE1_CONFIG)
    wave2 = _load_yaml(WAVE2_CONFIG)

    _assert_l3_17_config(
        wave1,
        expected_run_id="matrix_l3_17_text_quality_remote_e2b_e4b",
        expected_models={"google/gemma-4-e2b", "google/gemma-4-e4b"},
        max_requests=24,
    )
    _assert_l3_17_config(
        wave2,
        expected_run_id="matrix_l3_17_text_quality_remote_12b",
        expected_models={"google/gemma-4-12b-qat"},
        max_requests=12,
    )


def test_l3_17_suite_runs_12b_only_after_e2b_e4b() -> None:
    suite = _load_yaml(SUITE)

    assert suite == {
        "suite_id": "l3_17_text_quality_screening",
        "stop_on_failure": True,
        "configs": [
            {
                "config": "../configs/matrix.l3_17_text_quality_remote.e2b_e4b.yaml",
                "required": True,
            },
            {
                "config": "../configs/matrix.l3_17_text_quality_remote.12b.yaml",
                "required": True,
                "run_after": ["matrix_l3_17_text_quality_remote_e2b_e4b"],
            },
        ],
    }
    for entry in suite["configs"]:
        assert (SUITE.parent / entry["config"]).resolve().is_file()
