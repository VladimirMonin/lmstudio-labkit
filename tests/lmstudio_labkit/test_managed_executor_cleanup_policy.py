from __future__ import annotations

import json
from typing import Any, ClassVar

import pytest

from lmstudio_labkit import (
    ChatMessage,
    ExecutionOptions,
    LocalLMStudioHostRunner,
    ManagedExecutorError,
    ManagedLMStudioExecutor,
    RequestEnvelope,
    RequestPlan,
    ResponseContract,
    build_simple_flat_schema,
)


class MockManagedHostRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.loaded_instances = 0

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.calls.append(("load_model", {"model_id": model_id}))
        self.loaded_instances = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def chat_completion(self, **kwargs: object) -> object:
        self.calls.append(("chat_completion", dict(kwargs)))
        return {
            "choices": [
                {
                    "message": {"content": json.dumps({"id": "ok", "text": "Synthetic response"})},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5},
        }

    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append(("cleanup_model", {"model_id": model_id}))
        self.loaded_instances = 0
        return {"cleanup_verified": True}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        self.calls.append(("count_loaded_instances", {"model_id": model_id}))
        return self.loaded_instances


def structured_plan() -> RequestPlan:
    return RequestPlan(
        cell_id="managed-cell",
        envelope=RequestEnvelope(
            request_id="managed-cell",
            modality="text",
            chat_messages=(ChatMessage(role="user", content="Return structured JSON"),),
            response_contract=ResponseContract(
                mode="json",
                schema=build_simple_flat_schema(),
                expected_output={"id": "ok", "text": "Synthetic response"},
            ),
        ),
        options=ExecutionOptions(
            model_id="mock/text",
            endpoint_family="openai_compat",
            context_tier="8192",
            temperature=0.0,
            timeout_s=30.0,
            live=True,
        ),
    )


class FailingChatHostRunner(MockManagedHostRunner):
    def chat_completion(self, **kwargs: object) -> object:
        self.calls.append(("chat_completion", dict(kwargs)))
        raise RuntimeError("synthetic chat failure")


class CleanupFailureHostRunner(MockManagedHostRunner):
    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append(("cleanup_model", {"model_id": model_id}))
        self.loaded_instances = 1
        return {"cleanup_verified": False}


class InsufficientLoadHostRunner(MockManagedHostRunner):
    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.calls.append(("load_model", {"model_id": model_id}))
        self.loaded_instances = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": 4096, "parallel": parallel},
        }


def test_managed_executor_cleans_up_when_chat_completion_fails() -> None:
    host = FailingChatHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    with pytest.raises(RuntimeError, match="synthetic chat failure"):
        executor.execute(structured_plan())

    assert [name for name, _payload in host.calls] == [
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
    ]


def test_managed_executor_fails_when_cleanup_is_not_verified() -> None:
    host = CleanupFailureHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    with pytest.raises(ManagedExecutorError, match="cleanup was not verified"):
        executor.execute(structured_plan())


def test_managed_executor_fails_when_load_shape_is_not_verified() -> None:
    host = InsufficientLoadHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    with pytest.raises(ManagedExecutorError, match="load was not verified"):
        executor.execute(structured_plan())

    assert [name for name, _payload in host.calls] == [
        "count_loaded_instances",
        "load_model",
        "cleanup_model",
        "count_loaded_instances",
    ]


def test_managed_executor_fails_when_final_instances_remain_loaded() -> None:
    host = MockManagedHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    def leave_loaded(*, model_id: str) -> object:
        host.calls.append(("cleanup_model", {"model_id": model_id}))
        host.loaded_instances = 1
        return {"cleanup_verified": True}

    host.cleanup_model = leave_loaded  # type: ignore[method-assign]

    with pytest.raises(ManagedExecutorError, match="final loaded instances"):
        executor.execute(structured_plan())


class RecordingLocalRunner(LocalLMStudioHostRunner):
    calls: ClassVar[list[tuple[str, object]]] = []
    loaded_instances: ClassVar[list[str]] = []

    def __init__(self) -> None:
        super().__init__()
        type(self).calls = []
        type(self).loaded_instances = ["google/gemma-4-e2b", "google/gemma-4-e2b:2"]

    def _request_json(self, path: str, payload: object, timeout_s: float) -> dict[str, object]:
        type(self).calls.append((path, payload))
        if path == "/api/v1/models" and payload is None:
            return {
                "models": [
                    {
                        "key": "google/gemma-4-e2b",
                        "type": "llm",
                        "loaded_instances": [{"id": item} for item in type(self).loaded_instances],
                    }
                ]
            }
        if path == "/api/v1/models/unload" and isinstance(payload, dict):
            instance_id = payload.get("instance_id")
            if isinstance(instance_id, str) and instance_id in type(self).loaded_instances:
                type(self).loaded_instances.remove(instance_id)
            return {"status": "ok"}
        raise AssertionError(f"unexpected request {path} {payload}")


def test_local_runner_unloads_loaded_instances_by_instance_id() -> None:
    runner = RecordingLocalRunner()

    result = runner.cleanup_model(model_id="google/gemma-4-e2b")

    assert result == {"cleanup_verified": True}
    assert runner.loaded_instances == []
    assert runner.calls == [
        ("/api/v1/models", None),
        ("/api/v1/models/unload", {"instance_id": "google/gemma-4-e2b"}),
        ("/api/v1/models/unload", {"instance_id": "google/gemma-4-e2b:2"}),
        ("/api/v1/models", None),
    ]
