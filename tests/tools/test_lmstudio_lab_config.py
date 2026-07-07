from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools import lmstudio_lab


def test_load_experiment_config_applies_defaults_and_expands_load_grid(tmp_path) -> None:
    config_path = tmp_path / "experiment.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "exp-grid",
                "models": [
                    {
                        "key": "gemma4_12b_qat",
                        "load": {
                            "context_length": [8192, 16384],
                            "parallel": [1, 2],
                            "flash_attention": True,
                            "eval_batch_size": 512,
                        },
                    }
                ],
                "modes": ["json_schema_single"],
                "datasets": ["blocks_json_small"],
                "repeats": 2,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = lmstudio_lab.load_experiment_config(config_path)

    assert config.experiment_id == "exp-grid"
    assert config.hardware_profile is None
    assert config.lmstudio_base_url == "http://127.0.0.1:1234"
    assert config.warmup_runs == 0
    assert config.privacy.store_prompt_text is False
    assert config.privacy.store_response_text is False
    assert config.privacy.store_prompt_hash is True
    assert config.models[0].iter_load_configs() == (
        {
            "context_length": 8192,
            "parallel": 1,
            "flash_attention": True,
            "eval_batch_size": 512,
        },
        {
            "context_length": 8192,
            "parallel": 2,
            "flash_attention": True,
            "eval_batch_size": 512,
        },
        {
            "context_length": 16384,
            "parallel": 1,
            "flash_attention": True,
            "eval_batch_size": 512,
        },
        {
            "context_length": 16384,
            "parallel": 2,
            "flash_attention": True,
            "eval_batch_size": 512,
        },
    )


def test_load_experiment_config_accepts_explicit_privacy_booleans(tmp_path) -> None:
    config_path = tmp_path / "privacy.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "exp-privacy",
                "models": [{"key": "qwen", "load": {"parallel": [1]}}],
                "modes": ["json_schema_single"],
                "datasets": ["blocks_json_small"],
                "repeats": 1,
                "privacy": {
                    "store_prompt_text": True,
                    "store_response_text": True,
                    "store_prompt_hash": False,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = lmstudio_lab.load_experiment_config(config_path)

    assert config.privacy.store_prompt_text is True
    assert config.privacy.store_response_text is True
    assert config.privacy.store_prompt_hash is False


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    (
        ("store_prompt_text", "false"),
        ("store_response_text", 0),
        ("store_prompt_hash", "true"),
    ),
)
def test_load_experiment_config_requires_boolean_privacy_fields(
    tmp_path,
    field_name: str,
    field_value: object,
) -> None:
    config_path = tmp_path / "invalid_privacy.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "exp-invalid-privacy",
                "models": [{"key": "qwen", "load": {"parallel": [1]}}],
                "modes": ["json_schema_single"],
                "datasets": ["blocks_json_small"],
                "repeats": 1,
                "privacy": {field_name: field_value},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=rf"privacy\.{field_name} must be a boolean"):
        lmstudio_lab.load_experiment_config(config_path)


@pytest.mark.parametrize(
    ("field_name", "field_value", "error_fragment"),
    (
        ("repeats", 0, "repeats must be >= 1"),
        ("warmup_runs", -1, "warmup_runs must be >= 0"),
    ),
)
def test_load_experiment_config_validates_non_negative_counts(
    tmp_path,
    field_name: str,
    field_value: int,
    error_fragment: str,
) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "exp-invalid",
                "models": [{"key": "qwen", "load": {"parallel": [1]}}],
                "modes": ["json_schema_single"],
                "datasets": ["blocks_json_small"],
                "repeats": 1,
                field_name: field_value,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=error_fragment):
        lmstudio_lab.load_experiment_config(config_path)


def test_validate_experiment_config_payload_rejects_forbidden_private_fields() -> None:
    payload = {
        "experiment_id": "unsafe-private-field",
        "models": [{"key": "qwen", "load": {"parallel": [1]}}],
        "modes": ["json_schema_single"],
        "datasets": ["blocks_json_small"],
        "repeats": 1,
        "prompt": "SENTINEL_PROMPT",
    }

    with pytest.raises(ValueError, match="unsafe experiment config"):
        lmstudio_lab.validate_experiment_config_payload(payload)


def test_validate_experiment_config_payload_rejects_absolute_paths() -> None:
    payload = {
        "experiment_id": "unsafe-path",
        "models": [{"key": "qwen", "load": {"parallel": [1]}}],
        "modes": ["json_schema_single"],
        "datasets": ["blocks_json_small"],
        "repeats": 1,
        "notes": str(Path("C:/Users/tester/private/experiment.yaml")),
    }

    with pytest.raises(ValueError, match="unsafe experiment config"):
        lmstudio_lab.validate_experiment_config_payload(payload)
