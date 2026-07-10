from __future__ import annotations

import json
from typing import Any

import pytest

from lmstudio_labkit import (
    ChatMessage,
    ExecutionOptions,
    ManagedExecutionResult,
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
        self.calls.append(
            (
                "load_model",
                {"model_id": model_id, "context_length": context_length, "parallel": parallel},
            )
        )
        self.loaded_instances = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def chat_completion(
        self,
        *,
        endpoint_path: str,
        model_id: str,
        messages: object,
        response_format: object,
        temperature: float,
        timeout_s: float,
        max_tokens: int | None = None,
    ) -> object:
        self.calls.append(
            (
                "chat_completion",
                {
                    "endpoint_path": endpoint_path,
                    "model_id": model_id,
                    "messages": messages,
                    "response_format": response_format,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "timeout_s": timeout_s,
                },
            )
        )
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


class LegacySignatureManagedHostRunner(MockManagedHostRunner):
    def chat_completion(
        self,
        *,
        endpoint_path: str,
        model_id: str,
        messages: object,
        response_format: object,
        temperature: float,
        timeout_s: float,
    ) -> object:
        return super().chat_completion(
            endpoint_path=endpoint_path,
            model_id=model_id,
            messages=messages,
            response_format=response_format,
            temperature=temperature,
            timeout_s=timeout_s,
        )


class CachedUsageManagedHostRunner(MockManagedHostRunner):
    def chat_completion(
        self,
        *,
        endpoint_path: str,
        model_id: str,
        messages: object,
        response_format: object,
        temperature: float,
        timeout_s: float,
        max_tokens: int | None = None,
    ) -> object:
        payload = super().chat_completion(
            endpoint_path=endpoint_path,
            model_id=model_id,
            messages=messages,
            response_format=response_format,
            temperature=temperature,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
        )
        assert isinstance(payload, dict)
        payload["usage"] = {
            "prompt_tokens": 120,
            "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 96},
        }
        return payload


def structured_plan(**option_overrides: object) -> RequestPlan:
    options = {
        "model_id": "mock/text",
        "endpoint_family": "openai_compat",
        "context_tier": "8192",
        "temperature": 0.0,
        "timeout_s": 30.0,
        "live": True,
    }
    options.update(option_overrides)
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
        options=ExecutionOptions(**options),
    )


def test_managed_executor_requires_explicit_model_load_permission() -> None:
    host = MockManagedHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host)

    with pytest.raises(ManagedExecutorError, match="allow_model_loads=true"):
        executor.execute(structured_plan())

    assert host.calls == []


def test_managed_executor_executes_single_mocked_compat_chat_request() -> None:
    host = MockManagedHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    result = executor.execute(structured_plan())

    assert isinstance(result, ManagedExecutionResult)
    assert json.loads(result.raw_response) == {"id": "ok", "text": "Synthetic response"}
    assert result.prompt_tokens == 7
    assert result.completion_tokens == 5
    assert result.cached_tokens is None
    assert result.finish_reason == "stop"
    assert result.load_verified is True
    assert result.cleanup_verified is True
    assert result.final_loaded_instances == 0
    assert [name for name, _payload in host.calls] == [
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
    ]
    chat_payload = host.calls[3][1]
    assert chat_payload["endpoint_path"] == "/v1/chat/completions"
    assert chat_payload["max_tokens"] is None
    assert chat_payload["temperature"] == 0.0
    assert chat_payload["response_format"]["type"] == "json_schema"
    assert host.calls[1][1]["context_length"] == 8192
    assert host.calls[1][1]["parallel"] == 1


def test_managed_executor_preserves_reported_cached_token_usage() -> None:
    host = CachedUsageManagedHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    result = executor.execute(structured_plan())

    assert result.cached_tokens == 96


def test_unset_budget_preserves_legacy_host_runner_signature_and_cleanup() -> None:
    host = LegacySignatureManagedHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    result = executor.execute(structured_plan())

    assert result.finish_reason == "stop"
    assert result.final_loaded_instances == 0
    assert host.loaded_instances == 0
    assert host.calls[-2:] == [
        ("cleanup_model", {"model_id": "mock/text"}),
        ("count_loaded_instances", {"model_id": "mock/text"}),
    ]


@pytest.mark.parametrize("max_tokens", [1, 1024, 32768])
def test_managed_executor_forwards_explicit_max_tokens_unchanged(max_tokens: int) -> None:
    host = MockManagedHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    result = executor.execute(structured_plan(max_tokens=max_tokens))

    assert result.finish_reason == "stop"
    assert host.calls[3][0] == "chat_completion"
    assert host.calls[3][1]["max_tokens"] == max_tokens
    assert host.calls[-2:] == [
        ("cleanup_model", {"model_id": "mock/text"}),
        ("count_loaded_instances", {"model_id": "mock/text"}),
    ]


def test_managed_executor_passes_16384_context_to_host_runner() -> None:
    host = MockManagedHostRunner()
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        context_length=16384,
    )

    result = executor.execute(structured_plan(context_tier="16384"))

    assert result.load_verified is True
    assert host.calls[1][0] == "load_model"
    assert host.calls[1][1]["context_length"] == 16384
    assert host.calls[1][1]["parallel"] == 1


def test_managed_executor_passes_32768_context_to_host_runner() -> None:
    host = MockManagedHostRunner()
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        context_length=32768,
    )

    result = executor.execute(structured_plan(context_tier="32768"))

    assert result.load_verified is True
    assert host.calls[1][1]["context_length"] == 32768


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"endpoint_path": "/v1/responses"}, "/v1/chat/completions"),
        ({"context_length": 4096}, "supported context"),
        ({"parallel": 2}, "parallel 1"),
        ({"temperature": 0.2}, "temperature 0"),
    ],
)
def test_managed_executor_rejects_non_v1_guardrail_shapes(
    overrides: dict[str, Any], match: str
) -> None:
    with pytest.raises(ManagedExecutorError, match=match):
        ManagedLMStudioExecutor(host_runner=MockManagedHostRunner(), **overrides)


def test_managed_executor_rejects_non_compat_or_non_8192_plan() -> None:
    executor = ManagedLMStudioExecutor(host_runner=MockManagedHostRunner(), allow_model_loads=True)

    with pytest.raises(ManagedExecutorError, match="openai_compat"):
        executor.execute(structured_plan(endpoint_family="native"))

    with pytest.raises(ManagedExecutorError, match="context_tier must match executor context"):
        executor.execute(structured_plan(context_tier="32768"))


def test_managed_executor_rejects_context_tier_mismatch_with_executor_context() -> None:
    executor = ManagedLMStudioExecutor(
        host_runner=MockManagedHostRunner(),
        allow_model_loads=True,
        context_length=16384,
    )

    with pytest.raises(ManagedExecutorError, match="context_tier must match executor context"):
        executor.execute(structured_plan(context_tier="32768"))
