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


class StrictLoadHostRunner:
    def __init__(
        self,
        load_response: object,
        *,
        post_load_instances: int | None = 1,
        final_instances: int | None = 0,
    ) -> None:
        self.load_response = load_response
        self.post_load_instances = post_load_instances
        self.final_instances = final_instances
        self.calls: list[str] = []

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.calls.append("load_model")
        return self.load_response

    def chat_completion(self, **kwargs: object) -> object:
        self.calls.append("chat_completion")
        return {
            "choices": [
                {
                    "message": {"content": json.dumps({"id": "ok", "text": "Synthetic response"})},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        }

    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append("cleanup_model")
        return {"cleanup_verified": True}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        self.calls.append("count_loaded_instances")
        if "load_model" not in self.calls:
            return 0
        if "chat_completion" in self.calls or "cleanup_model" in self.calls:
            return self.final_instances
        return self.post_load_instances


def structured_plan() -> RequestPlan:
    return RequestPlan(
        cell_id="strict-load-cell",
        envelope=RequestEnvelope(
            request_id="strict-load-cell",
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


def execute_with(
    load_response: object, *, post_load_instances: int | None = 1, final_instances: int | None = 0
) -> None:
    host = StrictLoadHostRunner(
        load_response,
        post_load_instances=post_load_instances,
        final_instances=final_instances,
    )
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    executor.execute(structured_plan())


@pytest.mark.parametrize(
    "load_response",
    [
        {"load_verified": True, "applied_load_config": {"context_length": 8192, "parallel": 1}},
        {"load_verified": True, "load_config": {"context_length": 8192, "parallel": 1}},
    ],
)
def test_exact_applied_or_load_config_passes(load_response: dict[str, Any]) -> None:
    execute_with(load_response)


@pytest.mark.parametrize(
    ("load_response", "match"),
    [
        ({"load_verified": True, "context_length": 8192, "parallel": 1}, "load was not verified"),
        (
            {
                "load_verified": True,
                "applied_load_config": {"context_length": 16384, "parallel": 1},
            },
            "runner_or_runtime_context_mismatch",
        ),
        (
            {"load_verified": True, "applied_load_config": {"context_length": 8192, "parallel": 2}},
            "runner_or_runtime_parallel_mismatch",
        ),
    ],
)
def test_missing_or_mismatched_applied_config_fails(
    load_response: dict[str, Any], match: str
) -> None:
    host = StrictLoadHostRunner(load_response)
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    with pytest.raises(ManagedExecutorError, match=match):
        executor.execute(structured_plan())

    assert "chat_completion" not in host.calls


@pytest.mark.parametrize(
    ("post_load_instances", "match"),
    [
        (0, "loaded instance was not visible"),
        (None, "loaded state was not verified"),
    ],
)
def test_post_load_loaded_state_must_be_proven(post_load_instances: int | None, match: str) -> None:
    host = StrictLoadHostRunner(
        {"load_verified": True, "applied_load_config": {"context_length": 8192, "parallel": 1}},
        post_load_instances=post_load_instances,
    )
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    with pytest.raises(ManagedExecutorError, match=match):
        executor.execute(structured_plan())

    assert "chat_completion" not in host.calls


@pytest.mark.parametrize("final_instances", [1, None])
def test_cleanup_final_loaded_instances_must_be_zero(final_instances: int | None) -> None:
    host = StrictLoadHostRunner(
        {"load_verified": True, "applied_load_config": {"context_length": 8192, "parallel": 1}},
        final_instances=final_instances,
    )
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    with pytest.raises(ManagedExecutorError, match="final loaded instances must be zero"):
        executor.execute(structured_plan())
