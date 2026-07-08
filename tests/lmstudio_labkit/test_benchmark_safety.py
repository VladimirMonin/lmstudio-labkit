from __future__ import annotations

import json

import pytest
from lmstudio_labkit.benchmarks import BenchmarkSafetyConfig, plan_matrix

from lmstudio_labkit import BenchmarkConfig, run_matrix


def minimal_config_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": "safe_api",
        "models": [
            {"model_key": "fake", "model_id": "fake/text", "supported_modalities": ["text"]}
        ],
        "tasks": [
            {
                "task_id": "t",
                "family": "simple_flat",
                "modality": "text",
                "prompt": "Synthetic prompt",
                "expected_output": {"id": "ok", "text": "Synthetic"},
            }
        ],
        "axes": {
            "modality": ["text"],
            "language": ["en_en"],
            "structure_complexity": ["simple"],
            "volume": ["single"],
            "context_tier": ["8192"],
            "schema_variant": ["baseline_loose"],
            "retry_policy": ["off"],
        },
        "repeats": 1,
    }
    payload.update(overrides)
    return payload


def test_default_safety_config_keeps_offline_fake_runner_privacy_safe(tmp_path) -> None:
    config = BenchmarkConfig.from_dict(minimal_config_payload())

    assert config.safety == BenchmarkSafetyConfig()
    artifacts = run_matrix(config, tmp_path)
    cell_results = artifacts.cell_results.read_text(encoding="utf-8")

    assert json.loads(artifacts.planner_summary.read_text(encoding="utf-8"))["live"] is False
    assert "Synthetic prompt" not in cell_results
    assert "raw_response" not in cell_results


@pytest.mark.parametrize(
    ("safety", "message"),
    [
        ({"live": True}, "live=false"),
        ({"allow_model_downloads": True}, "model downloads"),
        ({"allow_model_loads": True}, "model loads"),
        ({"allow_remote_base_url": True}, "remote base URLs"),
        ({"allow_raw_prompt_response_artifacts": True}, "raw prompt/response artifacts"),
        ({"allow_image_live": True}, "image live execution"),
        ({"allow_stress": True}, "stress"),
    ],
)
def test_python_api_rejects_unsafe_safety_flags_without_cli(
    tmp_path, safety: dict[str, object], message: str
) -> None:
    config = BenchmarkConfig.from_dict(minimal_config_payload(safety=safety))

    with pytest.raises(ValueError, match=message):
        run_matrix(config, tmp_path)


def test_python_api_enforces_request_model_context_and_repeat_budgets() -> None:
    too_many_requests = BenchmarkConfig.from_dict(
        minimal_config_payload(
            axes={
                "modality": ["text"],
                "language": ["en_en"],
                "structure_complexity": ["simple"],
                "volume": ["single"],
                "context_tier": ["8192"],
                "schema_variant": ["baseline_loose"],
                "retry_policy": ["off", "retry1"],
            },
            safety={"max_requests": 1},
        )
    )
    too_many_models = BenchmarkConfig.from_dict(
        minimal_config_payload(
            models=[
                {"model_key": "a", "model_id": "fake/a", "supported_modalities": ["text"]},
                {"model_key": "b", "model_id": "fake/b", "supported_modalities": ["text"]},
            ],
            safety={"max_models": 1},
        )
    )
    too_large_context = BenchmarkConfig.from_dict(
        minimal_config_payload(
            axes={
                "modality": ["text"],
                "language": ["en_en"],
                "structure_complexity": ["simple"],
                "volume": ["single"],
                "context_tier": ["16384"],
                "schema_variant": ["baseline_loose"],
                "retry_policy": ["off"],
            },
            safety={"max_context_tier": 8192},
        )
    )
    too_many_repeats = BenchmarkConfig.from_dict(
        minimal_config_payload(repeats=2, safety={"max_repeats": 1})
    )

    with pytest.raises(ValueError, match="max_requests"):
        plan_matrix(too_many_requests)
    with pytest.raises(ValueError, match="max_models"):
        plan_matrix(too_many_models)
    with pytest.raises(ValueError, match="max_context_tier"):
        plan_matrix(too_large_context)
    with pytest.raises(ValueError, match="max_repeats"):
        plan_matrix(too_many_repeats)


def test_invalid_safety_budget_values_fail_before_planning() -> None:
    with pytest.raises(ValueError, match="max_runtime_minutes"):
        BenchmarkConfig.from_dict(minimal_config_payload(safety={"max_runtime_minutes": 0}))

    assert (
        BenchmarkConfig.from_dict(
            minimal_config_payload(safety={"max_runtime_minutes": None})
        ).safety.max_runtime_minutes
        is None
    )

    with pytest.raises(ValueError, match="allow_image_live"):
        BenchmarkConfig.from_dict(minimal_config_payload(safety={"allow_image_live": "yes"}))
