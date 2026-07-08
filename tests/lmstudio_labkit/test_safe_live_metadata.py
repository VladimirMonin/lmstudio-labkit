from __future__ import annotations

import json
from pathlib import Path

from lmstudio_labkit.live_bridge import LiveBridgeOptions, safe_live_metadata

from lmstudio_labkit import BenchmarkConfig, run_live_small_text_screening


def live_text_payload() -> dict[str, object]:
    return {
        "run_id": "safe_live_metadata",
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


def test_safe_live_metadata_classifies_local_without_persisting_base_url_host() -> None:
    metadata = safe_live_metadata(LiveBridgeOptions(live=True, base_url="http://127.0.0.1:1234/v1"))

    assert metadata["base_url_kind"] == "local"
    assert metadata["base_url_scheme"] == "http"
    assert "base_url" not in metadata
    assert "base_url_host" not in metadata
    assert "127.0.0.1" not in json.dumps(metadata, sort_keys=True)


def test_safe_live_metadata_classifies_remote_without_persisting_hostname() -> None:
    metadata = safe_live_metadata(
        LiveBridgeOptions(
            live=True,
            allow_remote=True,
            base_url="https://example.test:1234/private-path",
        )
    )

    assert metadata["base_url_kind"] == "remote"
    assert metadata["base_url_scheme"] == "https"
    assert "base_url" not in metadata
    assert "base_url_host" not in metadata
    assert "example.test" not in json.dumps(metadata, sort_keys=True)


def test_guarded_live_artifacts_store_only_safe_base_url_classification(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(live_text_payload())

    artifacts = run_live_small_text_screening(
        config,
        tmp_path,
        executor=lambda plan: json.dumps({"id": "ok", "text": "Synthetic response"}),
        options=LiveBridgeOptions(live=True, profile="live-small", max_requests=1),
    )

    planner_summary = json.loads(artifacts.planner_summary.read_text(encoding="utf-8"))
    serialized = artifacts.planner_summary.read_text(encoding="utf-8")

    assert planner_summary["live_bridge"]["base_url_kind"] == "local"
    assert planner_summary["live_bridge"]["base_url_scheme"] == "http"
    assert "base_url_host" not in planner_summary["live_bridge"]
    assert "127.0.0.1" not in serialized
