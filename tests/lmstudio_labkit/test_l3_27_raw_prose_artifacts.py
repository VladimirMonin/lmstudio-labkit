from __future__ import annotations

import json
from pathlib import Path

import pytest
from lmstudio_labkit.benchmarks import BenchmarkConfig, FakeTransport, run_matrix
from lmstudio_labkit.live_bridge import LiveBridgeError, LiveBridgeOptions

_SIMPLE_SCHEMA = {
    "type": "object",
    "required": ["language", "clean_text", "warnings"],
    "additionalProperties": False,
    "properties": {
        "language": {"type": "string"},
        "clean_text": {"type": "string", "minLength": 1},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


def _raw_enabled_config() -> BenchmarkConfig:
    return BenchmarkConfig.from_dict(
        {
            "run_id": "matrix_l3_27_raw_prose_quality_unit",
            "models": [
                {
                    "model_key": "gemma4_e2b",
                    "model_id": "google/gemma-4-e2b",
                    "supported_modalities": ["text"],
                    "supported_context_tiers": ["8192"],
                }
            ],
            "tasks": [
                {
                    "task_id": "l327_transcript_cleanup_simple_unit",
                    "family": "postprocessing",
                    "modality": "text",
                    "language": "ru_ru",
                    "structure_complexity": "simple",
                    "response_schema_complexity": "simple",
                    "volume": "single",
                    "task_intent": "transcript_cleanup",
                    "input_profile": "l327_unit_raw_prose",
                    "output_language_policy": "preserve_input_language",
                    "prompt_variant": "strict_no_new_facts_v2",
                    "validation_policy": "auto_schema_language_manual_quality",
                    "prompt": "Return JSON only. Input transcript: ну это тестовая фраза",
                    "source_text": "ну это тестовая фраза",
                    "source_fixture_id": "l327_unit_raw_prose",
                    "schema_family": "simple",
                    "schema": _SIMPLE_SCHEMA,
                    "expected_output": {
                        "language": "ru",
                        "clean_text": "Это тестовая фраза.",
                        "warnings": [],
                    },
                    "fake_mode": "valid",
                    "manual_review_policy": "local_raw_prose_quality",
                    "near_identity_policy": "warning",
                }
            ],
            "axes": {
                "modality": ["text"],
                "language": ["ru_ru"],
                "task_intent": ["transcript_cleanup"],
                "input_profile": ["l327_unit_raw_prose"],
                "output_language_policy": ["preserve_input_language"],
                "prompt_variant": ["strict_no_new_facts_v2"],
                "response_schema_complexity": ["simple"],
                "structure_complexity": ["simple"],
                "volume": ["single"],
                "context_tier": ["8192"],
                "schema_variant": ["hardened_const"],
                "retry_policy": ["off"],
                "execution_mode": ["cold_per_request"],
                "cache_mode": ["none"],
                "execution_target": ["live_small"],
                "resource_telemetry_mode": ["timing_only"],
                "lmstudio_parallel": [1],
                "app_concurrency": [1],
                "queue_pressure_mode": [False],
                "temperature": [0],
                "validation_policy": ["auto_schema_language_manual_quality"],
            },
            "safety": {
                "live": True,
                "allow_model_downloads": False,
                "allow_model_loads": False,
                "allow_remote_base_url": False,
                "allow_raw_prompt_response_artifacts": True,
                "max_models": 1,
                "max_context_tier": 8192,
                "max_repeats": 1,
                "allow_image_live": False,
                "allow_stress": False,
                "max_requests": 1,
            },
            "structured_runtime": {"strict_json_schema": True},
            "repeats": 1,
        }
    )


def test_live_raw_prose_artifacts_are_written_only_for_local_temp_run(tmp_path: Path) -> None:
    config = _raw_enabled_config()
    result = run_matrix(
        config,
        tmp_path,
        transport=FakeTransport(),
        live_options=LiveBridgeOptions(live=True, profile="live-screening", max_requests=1),
    )

    raw_path = result.output_dir / "raw_cases.jsonl"
    assert raw_path.exists()
    raw_case = json.loads(raw_path.read_text(encoding="utf-8"))
    assert raw_case["source_text"] == "ну это тестовая фраза"
    assert "Это тестовая фраза" in raw_case["raw_response"]
    assert raw_case["model_id"] == "google/gemma-4-e2b"
    assert "base_url" not in raw_case


def test_live_raw_prose_artifacts_reject_repository_output_dir() -> None:
    config = _raw_enabled_config()
    repo_root = Path(__file__).resolve().parents[2]

    with pytest.raises(LiveBridgeError, match="must not be written inside the repository"):
        run_matrix(
            config,
            repo_root,
            transport=FakeTransport(),
            live_options=LiveBridgeOptions(live=True, profile="live-screening", max_requests=1),
        )

    assert not (repo_root / config.run_id / "raw_cases.jsonl").exists()
