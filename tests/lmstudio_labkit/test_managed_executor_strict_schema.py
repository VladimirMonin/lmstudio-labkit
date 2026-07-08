from __future__ import annotations

import json
from typing import Any

from lmstudio_labkit.benchmarks import BenchmarkConfig

from lmstudio_labkit import (
    ChatMessage,
    ExecutionOptions,
    ManagedLMStudioExecutor,
    RequestEnvelope,
    RequestPlan,
    ResponseContract,
    build_simple_flat_schema,
)


class CapturingHostRunner:
    def __init__(self) -> None:
        self.response_formats: list[dict[str, Any]] = []
        self.loaded_instances = 0

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.loaded_instances = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def chat_completion(self, **kwargs: object) -> object:
        self.response_formats.append(dict(kwargs)["response_format"])  # type: ignore[arg-type]
        return {
            "choices": [
                {
                    "message": {"content": json.dumps({"id": "ok", "text": "Synthetic response"})},
                    "finish_reason": "stop",
                }
            ]
        }

    def cleanup_model(self, *, model_id: str) -> object:
        self.loaded_instances = 0
        return {"cleanup_verified": True}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        return self.loaded_instances


def structured_plan() -> RequestPlan:
    return RequestPlan(
        cell_id="strict-schema-cell",
        envelope=RequestEnvelope(
            request_id="strict-schema-cell",
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


def test_managed_executor_emits_strict_schema_by_default() -> None:
    host = CapturingHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    result = executor.execute(structured_plan())

    assert host.response_formats[0]["json_schema"]["strict"] is True
    assert result.strict_schema_runtime_support is True
    assert result.hardened_schema_validation_available is True


def test_managed_executor_allows_explicit_non_strict_schema() -> None:
    host = CapturingHostRunner()
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        strict_json_schema=False,
    )

    result = executor.execute(structured_plan())

    assert host.response_formats[0]["json_schema"]["strict"] is False
    assert result.strict_schema_runtime_support is False


def test_benchmark_config_parses_structured_runtime_default_and_override() -> None:
    payload = {
        "run_id": "strict_schema_parse",
        "models": [{"model_key": "m", "model_id": "mock/text"}],
        "tasks": [{"task_id": "t", "prompt": "Synthetic prompt"}],
        "safety": {"max_requests": 1},
    }

    assert BenchmarkConfig.from_dict(payload).structured_runtime.strict_json_schema is True
    payload["structured_runtime"] = {"strict_json_schema": False}
    assert BenchmarkConfig.from_dict(payload).structured_runtime.strict_json_schema is False
