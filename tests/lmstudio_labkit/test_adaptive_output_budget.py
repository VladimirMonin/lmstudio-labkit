from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from lmstudio_labkit import (
    AdaptiveOutputBudgetPolicy,
    ChatMessage,
    ExecutionOptions,
    ManagedLMStudioExecutor,
    OutputBudgetObservation,
    RequestEnvelope,
    RequestPlan,
    ResponseContract,
    build_blocks_schema,
    build_simple_flat_schema,
    decide_output_budget,
    observe_output_budget,
)


def json_contract() -> ResponseContract:
    return ResponseContract(mode="json", schema=build_simple_flat_schema())


def test_complete_valid_structure_stops_at_current_budget() -> None:
    observation = observe_output_budget(
        raw_response=json.dumps({"id": "ok", "text": "complete"}),
        contract=json_contract(),
        budget=1024,
        finish_reason="stop",
        completion_tokens=24,
    )

    decision = decide_output_budget(
        AdaptiveOutputBudgetPolicy(stages=(1024, 2048, 4096)),
        attempt_index=1,
        observation=observation,
    )

    assert observation.structure_status == "valid"
    assert observation.truncation_observed is False
    assert decision.action == "stop"
    assert decision.reason == "complete_valid_structure"
    assert decision.next_budget is None


def test_complete_unstructured_output_stops_without_sweeping_later_stages() -> None:
    observation = observe_output_budget(
        raw_response="Complete plain text.",
        contract=ResponseContract(mode="text"),
        budget=1024,
        finish_reason="stop",
        completion_tokens=12,
    )

    decision = decide_output_budget(
        AdaptiveOutputBudgetPolicy(stages=(1024, 2048, 4096)),
        attempt_index=1,
        observation=observation,
    )

    assert observation.structure_status == "not_applicable"
    assert decision.action == "stop"
    assert decision.reason == "complete_output"


@pytest.mark.parametrize(
    "observation",
    [
        OutputBudgetObservation(1024, "length", 700, "parse_incomplete"),
        OutputBudgetObservation(1024, None, 1024, "valid"),
    ],
)
def test_observed_truncation_escalates_to_the_next_stage(
    observation: OutputBudgetObservation,
) -> None:
    decision = decide_output_budget(
        AdaptiveOutputBudgetPolicy(stages=(1024, 2048, 4096)),
        attempt_index=1,
        observation=observation,
    )

    assert decision.action == "escalate"
    assert decision.reason == "observed_truncation"
    assert decision.next_budget == 2048


def test_parse_incomplete_structure_escalates() -> None:
    observation = observe_output_budget(
        raw_response='{"id":"ok","text":',
        contract=json_contract(),
        budget=1024,
        finish_reason="stop",
        completion_tokens=20,
    )

    decision = decide_output_budget(
        AdaptiveOutputBudgetPolicy(stages=(1024, 2048, 4096)),
        attempt_index=1,
        observation=observation,
    )

    assert observation.structure_status == "parse_incomplete"
    assert decision.action == "escalate"
    assert decision.reason == "incomplete_structure"
    assert decision.next_budget == 2048


@pytest.mark.parametrize(
    ("raw_response", "expected_status", "expected_reason"),
    [
        (json.dumps({"id": "ok"}), "schema_invalid", "complete_schema_invalid"),
        ('{"id":"ok","text":"TODO"}', "quality_invalid", "complete_quality_failure"),
        ("{broken", "parse_invalid", "malformed_json"),
    ],
)
def test_complete_schema_quality_or_syntax_failure_stops_without_escalation(
    raw_response: str,
    expected_status: str,
    expected_reason: str,
) -> None:
    observation = observe_output_budget(
        raw_response=raw_response,
        contract=json_contract(),
        budget=1024,
        finish_reason="stop",
        completion_tokens=20,
    )

    decision = decide_output_budget(
        AdaptiveOutputBudgetPolicy(stages=(1024, 2048)),
        attempt_index=1,
        observation=observation,
    )

    assert observation.structure_status == expected_status
    assert decision.action == "stop"
    assert decision.reason == expected_reason
    assert decision.next_budget is None


@pytest.mark.parametrize(
    ("raw_response", "expected_status", "expected_reason"),
    [
        (
            json.dumps({"id": "ok", "text": "complete"}),
            "valid",
            "complete_valid_structure",
        ),
        (json.dumps({"id": "ok"}), "schema_invalid", "complete_schema_invalid"),
        ('{"id":"ok","text":"TODO"}', "quality_invalid", "complete_quality_failure"),
    ],
)
def test_explicit_stop_wins_over_completion_tokens_equal_to_budget(
    raw_response: str,
    expected_status: str,
    expected_reason: str,
) -> None:
    observation = observe_output_budget(
        raw_response=raw_response,
        contract=json_contract(),
        budget=1024,
        finish_reason="stop",
        completion_tokens=1024,
    )

    decision = decide_output_budget(
        AdaptiveOutputBudgetPolicy(stages=(1024, 2048)),
        attempt_index=1,
        observation=observation,
    )

    assert observation.structure_status == expected_status
    assert observation.truncation_observed is False
    assert decision.action == "stop"
    assert decision.reason == expected_reason
    assert decision.next_budget is None


def test_policy_stops_at_explicit_upper_bound_after_persistent_failure() -> None:
    policy = AdaptiveOutputBudgetPolicy(stages=(512, 1024))
    observation = OutputBudgetObservation(1024, "length", 1024, "parse_incomplete")

    decision = decide_output_budget(policy, attempt_index=2, observation=observation)

    assert decision.action == "stop"
    assert decision.reason == "observed_truncation_limit_reached"
    assert decision.next_budget is None


@pytest.mark.parametrize("stages", [(), (0,), (128, 256), (1024, 1024), (2048, 1024)])
def test_policy_rejects_unbounded_or_non_increasing_stage_shapes(
    stages: tuple[int, ...],
) -> None:
    with pytest.raises(ValueError):
        AdaptiveOutputBudgetPolicy(stages=stages)


def test_default_policy_derives_stages_from_measurable_contract_shape() -> None:
    policy = AdaptiveOutputBudgetPolicy()
    small_contract = ResponseContract(
        mode="json",
        schema=build_simple_flat_schema(),
        expected_output={"id": "ok", "text": "short"},
    )
    large_ids = tuple(range(16))
    large_contract = ResponseContract(
        mode="json",
        schema=build_blocks_schema(
            large_ids,
            "hardened_const",
            max_text_length=1024,
        ),
        expected_ids=large_ids,
    )

    small_stages = policy.stages_for(small_contract)
    large_stages = policy.stages_for(large_contract)

    assert small_stages[0] < large_stages[0]
    assert small_stages[-1] < large_stages[-1]
    assert large_stages[-1] <= policy.maximum_tokens


def test_explicit_policy_stages_remain_unchanged_and_bounded() -> None:
    policy = AdaptiveOutputBudgetPolicy(stages=(512, 1024), maximum_tokens=1024)

    assert policy.stages_for(json_contract()) == (512, 1024)
    with pytest.raises(ValueError, match="maximum_tokens"):
        AdaptiveOutputBudgetPolicy(stages=(512, 2048), maximum_tokens=1024)


class ScriptedHostRunner:
    def __init__(self, responses: Sequence[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.loaded_instances = 0

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.calls.append(("load_model", {"model_id": model_id}))
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
        messages: Sequence[Mapping[str, str]],
        response_format: Mapping[str, object],
        temperature: float,
        timeout_s: float,
        max_tokens: int | None = None,
    ) -> object:
        self.calls.append(("chat_completion", {"max_tokens": max_tokens}))
        return self.responses.pop(0)

    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append(("cleanup_model", {"model_id": model_id}))
        self.loaded_instances = 0
        return {"cleanup_verified": True}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        return self.loaded_instances


def completion(content: str, *, finish_reason: str = "stop", tokens: int = 20) -> object:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 8, "completion_tokens": tokens},
    }


def structured_plan(*, max_tokens: int | None = None) -> RequestPlan:
    return RequestPlan(
        cell_id="adaptive-budget-cell",
        envelope=RequestEnvelope(
            request_id="adaptive-budget-cell",
            modality="text",
            chat_messages=(ChatMessage(role="user", content="Return synthetic JSON"),),
            response_contract=json_contract(),
        ),
        options=ExecutionOptions(
            model_id="mock/text",
            context_tier="8192",
            max_tokens=max_tokens,
            live=True,
        ),
    )


def test_managed_executor_escalates_only_until_structure_is_valid() -> None:
    host = ScriptedHostRunner(
        [
            completion('{"id":"ok","text":'),
            completion(json.dumps({"id": "ok", "text": "complete"})),
        ]
    )
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        output_budget_policy=AdaptiveOutputBudgetPolicy(stages=(1024, 2048, 4096)),
    )

    result = executor.execute(structured_plan())

    chat_calls = [payload for name, payload in host.calls if name == "chat_completion"]
    assert [payload["max_tokens"] for payload in chat_calls] == [1024, 2048]
    assert result.output_budget_attempts == 2
    assert result.output_budgets_used == (1024, 2048)
    assert result.output_budget_stop_reason == "complete_valid_structure"
    assert host.calls[-1][0] == "cleanup_model"


def test_managed_executor_uses_contract_derived_default_stages() -> None:
    host = ScriptedHostRunner([completion(json.dumps({"id": "ok", "text": "complete"}))])
    policy = AdaptiveOutputBudgetPolicy()
    plan = structured_plan()
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        output_budget_policy=policy,
    )

    result = executor.execute(plan)

    expected_first_stage = policy.stages_for(plan.envelope.response_contract)[0]
    chat_calls = [payload for name, payload in host.calls if name == "chat_completion"]
    assert chat_calls == [{"max_tokens": expected_first_stage}]
    assert result.output_budgets_used == (expected_first_stage,)
    assert result.output_budget_stop_reason == "complete_valid_structure"


def test_managed_executor_does_not_escalate_complete_schema_failure() -> None:
    host = ScriptedHostRunner([completion(json.dumps({"id": "ok"}))])
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        output_budget_policy=AdaptiveOutputBudgetPolicy(stages=(1024, 2048)),
    )

    result = executor.execute(structured_plan())

    chat_calls = [payload for name, payload in host.calls if name == "chat_completion"]
    assert chat_calls == [{"max_tokens": 1024}]
    assert result.output_budget_stop_reason == "complete_schema_invalid"
    assert result.final_loaded_instances == 0


def test_explicit_caller_override_bypasses_adaptive_policy_unchanged() -> None:
    host = ScriptedHostRunner([completion('{"id":"ok","text":')])
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        output_budget_policy=AdaptiveOutputBudgetPolicy(stages=(1024, 2048, 4096)),
    )

    result = executor.execute(structured_plan(max_tokens=777))

    chat_calls = [payload for name, payload in host.calls if name == "chat_completion"]
    assert chat_calls == [{"max_tokens": 777}]
    assert result.output_budget_attempts == 1
    assert result.output_budgets_used == ()
    assert result.output_budget_stop_reason == "caller_override"


def test_managed_executor_stops_after_last_configured_stage() -> None:
    host = ScriptedHostRunner(
        [
            completion('{"id":"ok","text":'),
            completion('{"id":"ok","text":"still'),
            completion('{"id":"ok","text":"again'),
        ]
    )
    executor = ManagedLMStudioExecutor(
        host_runner=host,
        allow_model_loads=True,
        output_budget_policy=AdaptiveOutputBudgetPolicy(stages=(256, 512, 1024)),
    )

    result = executor.execute(structured_plan())

    chat_calls = [payload for name, payload in host.calls if name == "chat_completion"]
    assert [payload["max_tokens"] for payload in chat_calls] == [256, 512, 1024]
    assert result.output_budget_attempts == 3
    assert result.output_budgets_used == (256, 512, 1024)
    assert result.output_budget_stop_reason == "incomplete_structure_limit_reached"
    assert host.calls[-1][0] == "cleanup_model"
