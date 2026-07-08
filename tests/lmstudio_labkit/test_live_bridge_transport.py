from __future__ import annotations

import json
from pathlib import Path

import pytest
from lmstudio_labkit.live_bridge import LiveBridgeError, LiveBridgeOptions

from lmstudio_labkit import BenchmarkConfig, LiveBridgeTransport, run_matrix


def live_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": "live_bridge_transport",
        "models": [
            {
                "model_key": "fake",
                "model_id": "fake/text",
                "supported_modalities": ["text", "image"],
            }
        ],
        "tasks": [
            {
                "task_id": "t",
                "family": "simple_flat",
                "modality": "text",
                "language": "en_en",
                "prompt": "Synthetic prompt",
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
            "max_requests": 1,
            "max_models": 1,
            "max_context_tier": 8192,
            "max_repeats": 1,
        },
    }
    payload.update(overrides)
    return payload


def test_live_bridge_transport_requires_injected_executor_or_bridge() -> None:
    with pytest.raises(LiveBridgeError, match="injected executor or bridge"):
        LiveBridgeTransport(options=LiveBridgeOptions(live=True))


def test_live_bridge_transport_rejects_options_without_live_true() -> None:
    transport = LiveBridgeTransport(
        executor=lambda plan: json.dumps({"id": "ok", "text": "Synthetic response"}),
        options=LiveBridgeOptions(live=False),
    )
    config = BenchmarkConfig.from_dict(live_payload())

    with pytest.raises(LiveBridgeError, match="explicit live=True"):
        run_matrix(config, Path("/tmp/unused"), transport=transport, live_options=transport.options)


def test_live_bridge_transport_calls_executor_once_per_planned_cell(tmp_path: Path) -> None:
    payload = live_payload(
        models=[
            {"model_key": "a", "model_id": "fake/a", "supported_modalities": ["text"]},
            {"model_key": "b", "model_id": "fake/b", "supported_modalities": ["text"]},
        ],
        safety={"live": True, "max_requests": 2, "max_models": 2, "max_repeats": 1},
    )
    config = BenchmarkConfig.from_dict(payload)
    calls: list[str] = []

    def executor(plan):
        calls.append(plan.cell_id)
        return json.dumps({"id": "ok", "text": "Synthetic response"})

    options = LiveBridgeOptions(live=True, max_requests=2)

    run_matrix(
        config,
        tmp_path,
        transport=LiveBridgeTransport(executor=executor, options=options),
        live_options=options,
    )

    assert len(calls) == 2


def test_live_bridge_transport_checks_request_count_before_executor_call(tmp_path: Path) -> None:
    payload = live_payload(
        axes={
            "modality": ["text"],
            "language": ["en_en"],
            "structure_complexity": ["simple"],
            "volume": ["single"],
            "context_tier": ["8192"],
            "schema_variant": ["baseline_loose"],
            "retry_policy": ["off", "retry1"],
        },
        safety={"live": True, "max_requests": 2, "max_models": 1, "max_repeats": 1},
    )
    config = BenchmarkConfig.from_dict(payload)
    called = False

    def executor(plan):
        nonlocal called
        called = True
        return json.dumps({"id": "ok", "text": "Synthetic response"})

    options = LiveBridgeOptions(live=True, max_requests=1)

    with pytest.raises(LiveBridgeError, match="max_requests"):
        run_matrix(
            config,
            tmp_path,
            transport=LiveBridgeTransport(executor=executor, options=options),
            live_options=options,
        )

    assert called is False


def test_live_bridge_transport_runs_only_when_live_config_and_executor_are_injected(
    tmp_path: Path,
) -> None:
    config = BenchmarkConfig.from_dict(live_payload())
    seen_live: list[bool] = []

    def executor(plan):
        seen_live.append(plan.options.live)
        return json.dumps({"id": "ok", "text": "Synthetic response"})

    options = LiveBridgeOptions(live=True, profile="live-small", max_requests=1)
    artifacts = run_matrix(
        config,
        tmp_path,
        transport=LiveBridgeTransport(executor=executor, options=options),
        live_options=options,
    )

    assert seen_live == [True]
    planner_summary = json.loads(artifacts.planner_summary.read_text(encoding="utf-8"))
    assert planner_summary["live"] is True
    assert planner_summary["live_bridge"]["base_url_kind"] == "local"
    assert "127.0.0.1" not in artifacts.planner_summary.read_text(encoding="utf-8")
    assert "Synthetic response" not in artifacts.cell_results.read_text(encoding="utf-8")


def test_live_bridge_transport_requires_safety_live_true(tmp_path: Path) -> None:
    payload = live_payload(safety={"live": False, "max_requests": 1})
    config = BenchmarkConfig.from_dict(payload)
    options = LiveBridgeOptions(live=True, max_requests=1)

    with pytest.raises(LiveBridgeError, match="safety.live=true"):
        run_matrix(
            config,
            tmp_path,
            transport=LiveBridgeTransport(executor=lambda plan: "{}", options=options),
            live_options=options,
        )


def test_remote_base_url_without_allow_flag_is_blocked(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(live_payload())
    options = LiveBridgeOptions(
        live=True,
        base_url="https://remote.example.invalid/v1",
        allow_remote=False,
        max_requests=1,
    )

    with pytest.raises(LiveBridgeError, match="remote base_url"):
        run_matrix(
            config,
            tmp_path,
            transport=LiveBridgeTransport(executor=lambda plan: "{}", options=options),
            live_options=options,
        )


def test_image_live_raises_not_implemented(tmp_path: Path) -> None:
    payload = live_payload(
        tasks=[
            {
                "task_id": "image_probe",
                "family": "image_caption",
                "modality": "image",
                "language": "en_en",
                "image_hash": "sha256:" + "a" * 64,
                "prompt": "Synthetic image prompt",
                "expected_output": {"id": "ok", "text": "Synthetic response"},
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
    config = BenchmarkConfig.from_dict(payload)
    options = LiveBridgeOptions(live=True, max_requests=1)

    with pytest.raises(NotImplementedError, match="image live"):
        run_matrix(
            config,
            tmp_path,
            transport=LiveBridgeTransport(executor=lambda plan: "{}", options=options),
            live_options=options,
        )
