from __future__ import annotations

import pytest
from lmstudio_labkit.benchmarks import BenchmarkConfig, BenchmarkSafetyConfig, plan_matrix


def minimal_config_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": "safety_config",
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


def test_benchmark_safety_config_defaults_are_public_offline_budget() -> None:
    config = BenchmarkConfig.from_dict(minimal_config_payload())

    assert config.safety == BenchmarkSafetyConfig()
    assert config.safety.live is False
    assert config.safety.allow_model_downloads is False
    assert config.safety.allow_model_loads is False
    assert config.safety.allow_remote_base_url is False
    assert config.safety.allow_raw_prompt_response_artifacts is False
    assert config.safety.allow_image_live is False
    assert config.safety.allow_stress is False
    assert config.safety.max_requests == 100
    assert config.safety.max_models == 5
    assert config.safety.max_context_tier == 8192
    assert config.safety.max_repeats == 3


@pytest.mark.parametrize(
    ("safety", "message"),
    [
        ({"allow_raw_prompt_response_artifacts": True}, "raw prompt/response artifacts"),
        ({"allow_model_downloads": True}, "model downloads"),
    ],
)
def test_public_default_mode_rejects_raw_artifacts_and_model_downloads(
    safety: dict[str, object], message: str
) -> None:
    config = BenchmarkConfig.from_dict(minimal_config_payload(safety=safety))

    with pytest.raises(ValueError, match=message):
        plan_matrix(config)


def test_future_explicit_download_command_is_not_supported_by_public_config() -> None:
    config = BenchmarkConfig.from_dict(
        minimal_config_payload(safety={"live": True, "allow_model_downloads": True})
    )

    with pytest.raises(ValueError, match="model downloads"):
        plan_matrix(config)
