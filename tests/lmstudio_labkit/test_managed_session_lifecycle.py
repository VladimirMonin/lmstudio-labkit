from __future__ import annotations

import json
from typing import Any

from lmstudio_labkit.live_bridge import LiveBridgeOptions
from lmstudio_labkit.schema_builders import build_simple_flat_schema

from lmstudio_labkit import (
    BenchmarkConfig,
    ManagedLMStudioExecutor,
    ManagedLMStudioTransport,
    plan_matrix,
    run_matrix,
)


class SessionLifecycleHostRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.loaded_instances = 0
        self.chat_count = 0

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.calls.append("load_model")
        self.loaded_instances = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def chat_completion(self, **kwargs: object) -> object:
        self.calls.append("chat_completion")
        self.chat_count += 1
        payload = {"id": "ok", "text": f"Synthetic response {self.chat_count}"}
        return {
            "choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5},
        }

    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append("cleanup_model")
        self.loaded_instances = 0
        return {"cleanup_verified": True}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        self.calls.append("count_loaded_instances")
        return self.loaded_instances


def session_payload() -> dict[str, Any]:
    return {
        "run_id": "managed_session_lifecycle",
        "models": [
            {"model_key": "mock", "model_id": "mock/text", "supported_modalities": ["text"]}
        ],
        "tasks": [
            {
                "task_id": "session_task",
                "family": "simple_flat",
                "modality": "text",
                "language": "en_en",
                "prompt": "Synthetic prompt",
                "schema": build_simple_flat_schema(),
                "expected_ids": ["ok"],
                "id_paths": ["id"],
                "expected_output": {"id": "ok", "text": "Synthetic response"},
                "min_length_ratio": 0.1,
                "max_length_ratio": 5.0,
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
            "execution_mode": ["session_loaded"],
            "cache_mode": ["warmup_first"],
            "execution_target": ["remote_link"],
            "resource_telemetry_mode": ["timing_only"],
            "text_interaction_mode": ["same_text_repeat"],
        },
        "repeats": 3,
        "safety": {
            "live": True,
            "allow_model_loads": True,
            "allow_remote_base_url": True,
            "max_requests": 3,
            "max_repeats": 3,
        },
    }


def test_managed_executor_session_loads_once_for_multiple_requests() -> None:
    host = SessionLifecycleHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    config_payload = session_payload()
    config_payload["safety"] = {"max_requests": 3, "max_repeats": 3}
    config = BenchmarkConfig.from_dict(config_payload)
    plans = tuple(cell.to_request_plan() for cell in plan_matrix(config).cells)

    results = executor.execute_session(plans)

    assert len(results) == 3
    assert host.calls == [
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "chat_completion",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
    ]
    assert all(result.cleanup_verified for result in results)
    assert all(result.final_loaded_instances == 0 for result in results)


def test_run_matrix_session_loaded_uses_one_lifecycle_for_repeated_cells(tmp_path) -> None:  # type: ignore[no-untyped-def]
    host = SessionLifecycleHostRunner()
    transport = ManagedLMStudioTransport(
        ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    )

    artifacts = run_matrix(
        BenchmarkConfig.from_dict(session_payload()),
        tmp_path,
        transport=transport,
        live_options=LiveBridgeOptions(
            live=True,
            allow_model_load=True,
            allow_remote=True,
            max_requests=3,
        ),
    )

    assert host.calls == [
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "chat_completion",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
    ]
    rows = [
        json.loads(line)
        for line in artifacts.cell_results.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert [row["repeat_index"] for row in rows] == [0, 1, 2]
    assert [row["warmup_request_index"] for row in rows] == [1, 2, 3]
    assert [row["is_warmup_request"] for row in rows] == [True, False, False]
    assert all(row["axes"]["execution_mode"] == "session_loaded" for row in rows)
    assert all(row["status"] == "pass" for row in rows)
