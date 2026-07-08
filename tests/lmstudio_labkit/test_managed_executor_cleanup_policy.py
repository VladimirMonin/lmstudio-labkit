from __future__ import annotations

import json
from typing import Any

import pytest

from lmstudio_labkit import (
    ChatMessage,
    ExecutionOptions,
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
        return {"load_verified": True, "context_length": context_length, "parallel": parallel}

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
        return {"load_verified": True, "context_length": 4096, "parallel": parallel}


def test_managed_executor_cleans_up_when_chat_completion_fails() -> None:
    host = FailingChatHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    with pytest.raises(RuntimeError, match="synthetic chat failure"):
        executor.execute(structured_plan())

    assert [name for name, _payload in host.calls] == [
        "load_model",
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

    assert [name for name, _payload in host.calls] == ["load_model", "cleanup_model"]


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
