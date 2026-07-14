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
    NativeChatDiagnosticResult,
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


class NativeManagedHostRunner(MockManagedHostRunner):
    def __init__(
        self,
        *,
        reasoning_tokens: int = 0,
        reasoning_text: str = "",
        allowed_options: tuple[str, ...] = ("off", "on"),
    ) -> None:
        super().__init__()
        self.reasoning_tokens = reasoning_tokens
        self.reasoning_text = reasoning_text
        self.allowed_options = allowed_options

    def preflight_native_reasoning(
        self,
        *,
        model_id: str,
        reasoning: str,
    ) -> tuple[tuple[str, ...], str]:
        self.calls.append(
            (
                "preflight_native_reasoning",
                {"model_id": model_id, "reasoning": reasoning},
            )
        )
        if reasoning not in self.allowed_options:
            raise ManagedExecutorError(
                f"native reasoning {reasoning} is not advertised by exact model {model_id}"
            )
        return self.allowed_options, "on"

    def native_chat_completion(self, **kwargs: object) -> NativeChatDiagnosticResult:
        self.calls.append(("native_chat_completion", dict(kwargs)))
        return NativeChatDiagnosticResult(
            http_status=200,
            content_type="application/json",
            raw_body=b"{}",
            raw_envelope={},
            sse_frames=(),
            reasoning_text=self.reasoning_text,
            message_text=json.dumps({"id": "ok", "text": "Synthetic response"}),
            numeric_stats={
                "input_tokens": 7,
                "total_output_tokens": 5,
                "reasoning_output_tokens": self.reasoning_tokens,
            },
            finish_reason="stop",
            boundary="terminal",
        )


def test_compat_executor_rejects_explicit_reasoning_before_host_call() -> None:
    host = MockManagedHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    with pytest.raises(ManagedExecutorError, match="unsupported on /v1/chat/completions"):
        executor.execute(structured_plan(reasoning_mode="off"))

    assert host.calls == []


def test_native_executor_rejects_unadvertised_off_before_load() -> None:
    host = NativeManagedHostRunner(allowed_options=("on",))
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        endpoint_path="/api/v1/chat",
    )

    with pytest.raises(ManagedExecutorError, match="not advertised"):
        executor.execute(
            structured_plan(
                endpoint_family="native",
                reasoning_mode="off",
                max_tokens=64,
            )
        )

    assert [name for name, _payload in host.calls] == ["preflight_native_reasoning"]


def test_native_executor_fails_closed_on_reasoning_leak_and_cleans_up() -> None:
    host = NativeManagedHostRunner(reasoning_tokens=3, reasoning_text="hidden")
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        endpoint_path="/api/v1/chat",
    )

    with pytest.raises(ManagedExecutorError, match="reasoning_control_not_applied"):
        executor.execute(
            structured_plan(
                endpoint_family="native",
                reasoning_mode="off",
                max_tokens=64,
            )
        )

    assert host.loaded_instances == 0
    assert [name for name, _payload in host.calls][-2:] == [
        "cleanup_model",
        "count_loaded_instances",
    ]


def test_native_executor_accepts_measured_zero_reasoning_json_message() -> None:
    host = NativeManagedHostRunner()
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        endpoint_path="/api/v1/chat",
    )

    result = executor.execute(
        structured_plan(
            endpoint_family="native",
            reasoning_mode="off",
            max_tokens=64,
        )
    )

    assert json.loads(result.raw_response) == {"id": "ok", "text": "Synthetic response"}
    assert result.reasoning_mode == "off"
    assert result.reasoning_output_tokens == 0
    assert result.reasoning_control_applied is True
    assert result.strict_schema_runtime_support is False
    assert result.cleanup_verified is True
    native_call = next(payload for name, payload in host.calls if name == "native_chat_completion")
    assert native_call["reasoning"] == "off"
    assert native_call["max_output_tokens"] == 64
    assert "response_format" not in native_call
