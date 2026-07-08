from __future__ import annotations

import pytest
from lmstudio_labkit.benchmarks import BenchmarkConfig, plan_matrix


def minimal_config_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": "budget_guards",
        "models": [
            {"model_key": "fake", "model_id": "fake/text", "supported_modalities": ["text"]}
        ],
        "tasks": [
            {
                "task_id": "t",
                "family": "simple_flat",
                "modality": "text",
                "language": "en_en",
                "structure_complexity": "simple",
                "volume": "single",
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


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "axes": {
                    "modality": ["text"],
                    "language": ["en_en"],
                    "structure_complexity": ["simple"],
                    "volume": ["single"],
                    "context_tier": ["8192"],
                    "schema_variant": ["baseline_loose"],
                    "retry_policy": ["off", "retry1"],
                },
                "safety": {"max_requests": 1},
            },
            "max_requests",
        ),
        (
            {
                "models": [
                    {"model_key": "a", "model_id": "fake/a", "supported_modalities": ["text"]},
                    {"model_key": "b", "model_id": "fake/b", "supported_modalities": ["text"]},
                ],
                "safety": {"max_models": 1},
            },
            "max_models",
        ),
        (
            {"axes": {"context_tier": ["16384"]}, "safety": {"max_context_tier": 8192}},
            "max_context_tier",
        ),
        ({"repeats": 2, "safety": {"max_repeats": 1}}, "max_repeats"),
        ({"axes": {"volume": ["stress"]}}, "allow_stress"),
        (
            {
                "tasks": [
                    {
                        "task_id": "image_probe",
                        "family": "image_caption",
                        "modality": "image",
                        "image_hash": "sha256:" + "a" * 64,
                        "prompt": "Synthetic image prompt",
                        "expected_output": {"id": "ok", "text": "Synthetic"},
                    }
                ],
                "axes": {"modality": ["image"]},
                "safety": {"live": True, "allow_image_live": False},
            },
            "allow_image_live",
        ),
    ],
)
def test_budget_guards_reject_configs_that_exceed_safety_limits(
    overrides: dict[str, object], message: str
) -> None:
    config = BenchmarkConfig.from_dict(minimal_config_payload(**overrides))

    with pytest.raises(ValueError, match=message):
        plan_matrix(config)
