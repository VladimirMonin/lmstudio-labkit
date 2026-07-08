from __future__ import annotations

import json
from pathlib import Path

import pytest
from lmstudio_labkit.live_bridge import LiveBridgeError, LiveBridgeOptions

from lmstudio_labkit import BenchmarkConfig, run_live_small_text_screening, run_matrix


def live_text_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": "live_small_screening",
        "models": [
            {
                "model_key": "screening_fake",
                "model_id": "fake/text-small",
                "supported_modalities": ["text"],
                "supported_context_tiers": ["8192"],
            }
        ],
        "tasks": [
            {
                "task_id": "small_text_probe",
                "family": "simple_flat",
                "modality": "text",
                "language": "en_en",
                "structure_complexity": "simple",
                "volume": "single",
                "prompt": "Synthetic private-free screening prompt",
                "expected_output": {"id": "ok", "text": "Synthetic response"},
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
        "safety": {
            "live": True,
            "allow_model_downloads": False,
            "allow_model_loads": False,
            "allow_remote_base_url": False,
            "allow_raw_prompt_response_artifacts": False,
            "allow_image_live": False,
            "allow_stress": False,
            "max_requests": 1,
            "max_models": 1,
            "max_context_tier": 8192,
            "max_repeats": 1,
        },
    }
    payload.update(overrides)
    return payload


def test_guarded_live_small_text_screening_uses_injected_executor_and_safe_artifacts(
    tmp_path: Path,
) -> None:
    seen_live_flags: list[bool] = []

    def executor(plan):
        seen_live_flags.append(plan.options.live)
        assert plan.envelope.modality == "text"
        return json.dumps({"id": "ok", "text": "Synthetic response"})

    config = BenchmarkConfig.from_dict(live_text_payload())

    artifacts = run_live_small_text_screening(
        config,
        tmp_path,
        executor=executor,
        options=LiveBridgeOptions(live=True, profile="live-small", max_requests=1),
    )

    planner_summary = json.loads(artifacts.planner_summary.read_text(encoding="utf-8"))
    cell_results = artifacts.cell_results.read_text(encoding="utf-8")
    privacy_scan = json.loads(artifacts.privacy_scan.read_text(encoding="utf-8"))

    assert seen_live_flags == [True]
    assert planner_summary["live"] is True
    assert planner_summary["lab_only_flags"] == {
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
        "final_user_facing_recommendation": False,
    }
    assert planner_summary["live_bridge"]["lab_only_flags"] == planner_summary["lab_only_flags"]
    assert "Synthetic private-free screening prompt" not in cell_results
    assert "Synthetic response" not in cell_results
    assert "raw_response" not in cell_results
    assert privacy_scan["status"] == "pass"


def test_offline_runner_still_rejects_live_safety_config(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(live_text_payload())

    with pytest.raises(ValueError, match="live=false"):
        run_matrix(config, tmp_path)


def test_guarded_live_small_text_screening_rejects_images_and_model_loads(tmp_path: Path) -> None:
    image_config = BenchmarkConfig.from_dict(
        live_text_payload(
            tasks=[
                {
                    "task_id": "image_probe",
                    "family": "image_caption",
                    "modality": "image",
                    "image_hash": "sha256:" + "a" * 64,
                    "prompt": "Synthetic image prompt",
                    "expected_output": {"id": "ok", "text": "Synthetic"},
                }
            ],
            axes={
                "modality": ["image"],
                "language": ["en_en"],
                "structure_complexity": ["simple"],
                "volume": ["single"],
                "context_tier": ["8192"],
                "schema_variant": ["baseline_loose"],
                "retry_policy": ["off"],
            },
        )
    )

    with pytest.raises(LiveBridgeError, match="text tasks only"):
        run_live_small_text_screening(
            image_config,
            tmp_path,
            executor=lambda plan: json.dumps({"id": "ok", "text": "Synthetic"}),
        )

    safety_payload = live_text_payload()["safety"]
    assert isinstance(safety_payload, dict)
    load_config = BenchmarkConfig.from_dict(
        live_text_payload(safety={**safety_payload, "allow_model_loads": True})
    )
    with pytest.raises(LiveBridgeError, match="allow_model_load=True"):
        run_live_small_text_screening(
            load_config,
            tmp_path,
            executor=lambda plan: json.dumps({"id": "ok", "text": "Synthetic"}),
        )
