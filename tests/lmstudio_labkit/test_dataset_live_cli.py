from __future__ import annotations

import json
from pathlib import Path

import yaml
from lmstudio_labkit.cli import main as cli_main
from lmstudio_labkit.datasets import load_task_manifest, load_task_specs
from lmstudio_labkit.live_bridge import (
    LiveBridgeError,
    LiveBridgeOptions,
    ManagedLiveBridge,
    validate_live_guardrails,
)
from lmstudio_labkit.requests import ExecutionOptions, RequestEnvelope, RequestPlan


def test_dataset_manifest_loader_builds_task_spec() -> None:
    manifest = load_task_manifest(
        "experiments/lmstudio/structured_matrix/datasets/text/ru_medium_blocks.yaml"
    )
    spec = manifest.to_task_spec()

    assert spec.task_id == "ru_medium_blocks_001"
    assert spec.expected_ids == (0, 1, 2)
    assert spec.schema is not None
    assert spec.schema["properties"]["blocks"]["maxItems"] == 3


def test_dataset_loader_discovers_text_and_image_specs() -> None:
    specs = load_task_specs("experiments/lmstudio/structured_matrix/datasets")
    modalities = {spec.modality for spec in specs}

    assert {"text", "image"} <= modalities


def test_live_transport_guardrails_reject_remote_without_flag() -> None:
    with pytest_raises_live():
        validate_live_guardrails(
            LiveBridgeOptions(live=True, base_url="http://example.test:1234"),
            request_count=1,
        )


def test_live_transport_mocked_success() -> None:
    plan = RequestPlan(
        cell_id="cell_1",
        envelope=RequestEnvelope.text("req_1", "synthetic prompt"),
        options=ExecutionOptions(model_id="fake/text", live=True),
    )
    bridge = ManagedLiveBridge(
        executor=lambda request_plan: '{"id":"ok","text":"Synthetic"}',
        options=LiveBridgeOptions(live=True),
    )

    raw, result = bridge.execute(plan)

    assert json.loads(raw)["id"] == "ok"
    assert result.safe_metadata()["response_hash"]


def test_cli_safety_profiles_reject_live_without_flags(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "run_id": "cli_safety",
                "models": [
                    {"model_key": "fake", "model_id": "fake/text", "supported_modalities": ["text"]}
                ],
                "tasks": [
                    {
                        "task_id": "t",
                        "prompt": "Synthetic",
                        "expected_output": {"id": "x", "text": "Synthetic"},
                    }
                ],
                "safety": {"live": False, "allow_model_downloads": False},
            }
        ),
        encoding="utf-8",
    )

    try:
        cli_main(
            [
                "run",
                "--config",
                str(config_path),
                "--output-root",
                str(tmp_path),
                "--profile",
                "live-small",
            ]
        )
    except SystemExit as exc:
        assert "requires --live" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("live profile should fail without --live")


def test_cli_offline_smoke_config_runs(tmp_path: Path) -> None:
    assert (
        cli_main(
            [
                "run",
                "--config",
                "experiments/lmstudio/structured_matrix/configs/matrix.smoke.yaml",
                "--output-root",
                str(tmp_path),
                "--profile",
                "offline-fake",
            ]
        )
        == 0
    )


class pytest_raises_live:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        assert exc_type is LiveBridgeError
        return True
