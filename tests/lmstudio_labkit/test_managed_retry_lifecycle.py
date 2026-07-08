from __future__ import annotations

import json
from typing import Any

from lmstudio_labkit.schema_builders import build_simple_flat_schema

from lmstudio_labkit import (
    BenchmarkConfig,
    ManagedLMStudioExecutor,
    ManagedLMStudioTransport,
    run_matrix,
)


class RetryLifecycleHostRunner:
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
        if self.chat_count == 1:
            payload: dict[str, Any] = {"id": "wrong", "text": "Synthetic bad response"}
        else:
            payload = {"id": "ok", "text": "Synthetic response"}
        return {"choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}]}

    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append("cleanup_model")
        self.loaded_instances = 0
        return {"cleanup_verified": True}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        self.calls.append("count_loaded_instances")
        return self.loaded_instances


def retry_payload() -> dict[str, Any]:
    return {
        "run_id": "managed_retry_lifecycle",
        "models": [
            {"model_key": "mock", "model_id": "mock/text", "supported_modalities": ["text"]}
        ],
        "tasks": [
            {
                "task_id": "retry_task",
                "family": "simple_flat",
                "modality": "text",
                "language": "en_en",
                "prompt": "Synthetic prompt",
                "schema": build_simple_flat_schema(),
                "expected_ids": ["ok"],
                "id_paths": ["id"],
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
            "retry_policy": ["retry1"],
        },
        "safety": {"max_requests": 1},
    }


def test_managed_retry_runs_full_lifecycle_per_attempt(tmp_path) -> None:  # type: ignore[no-untyped-def]
    host = RetryLifecycleHostRunner()
    transport = ManagedLMStudioTransport(
        ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    )

    artifacts = run_matrix(
        BenchmarkConfig.from_dict(retry_payload()), tmp_path, transport=transport
    )

    assert host.calls == [
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
    ]
    row = json.loads(artifacts.cell_results.read_text(encoding="utf-8"))
    assert row["retry_count"] == 1
    assert row["retry_recovered"] is True
    assert row["status"] == "pass"
