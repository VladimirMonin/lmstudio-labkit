from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

from .json_normalization import JsonNormalizationPolicy, parse_json_response
from .requests import ResponseContract
from .validation import validate_json_schema, validate_response

StructureStatus = Literal[
    "valid",
    "parse_incomplete",
    "parse_invalid",
    "schema_invalid",
    "quality_invalid",
    "not_applicable",
]
BudgetAction = Literal["stop", "escalate"]


@dataclass(frozen=True, slots=True)
class AdaptiveOutputBudgetPolicy:
    """Bounded, evidence-driven output-token escalation policy.

    Explicit stages are preserved exactly. When stages are omitted, the policy
    derives a bounded sequence from measurable response-contract shape: schema
    capacity, expected-output size, and source-text length.
    """

    stages: tuple[int, ...] | None = None
    minimum_tokens: int = 256
    maximum_tokens: int = 8192

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_tokens, bool)
            or not isinstance(self.minimum_tokens, int)
            or self.minimum_tokens <= 0
        ):
            raise ValueError("minimum_tokens must be a positive integer")
        if (
            isinstance(self.maximum_tokens, bool)
            or not isinstance(self.maximum_tokens, int)
            or self.maximum_tokens < self.minimum_tokens
        ):
            raise ValueError("maximum_tokens must be an integer at least minimum_tokens")
        if self.stages is None:
            return
        if not self.stages:
            raise ValueError("output budget policy requires at least one stage")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in self.stages
        ):
            raise ValueError("output budget stages must be positive integers")
        if any(current >= following for current, following in pairwise(self.stages)):
            raise ValueError("output budget stages must be strictly increasing")
        if self.stages[0] < self.minimum_tokens:
            raise ValueError("output budget stages must not be below minimum_tokens")
        if self.stages[-1] > self.maximum_tokens:
            raise ValueError("output budget stages must not exceed maximum_tokens")

    def stages_for(self, contract: ResponseContract) -> tuple[int, ...]:
        if self.stages is not None:
            return self.stages

        estimated_tokens = max(1, math.ceil(_estimate_contract_chars(contract) / 3))
        first = _bounded_power_of_two(
            estimated_tokens,
            minimum=self.minimum_tokens,
            maximum=self.maximum_tokens,
        )
        upper_target = max(first, estimated_tokens * 2, first * 4)
        upper = _bounded_power_of_two(
            upper_target,
            minimum=first,
            maximum=self.maximum_tokens,
        )
        stages = [first]
        while stages[-1] < upper:
            stages.append(min(stages[-1] * 2, upper))
        return tuple(stages)

    def resolved_for(self, contract: ResponseContract) -> AdaptiveOutputBudgetPolicy:
        return AdaptiveOutputBudgetPolicy(
            stages=self.stages_for(contract),
            minimum_tokens=self.minimum_tokens,
            maximum_tokens=self.maximum_tokens,
        )


@dataclass(frozen=True, slots=True)
class OutputBudgetObservation:
    budget: int
    finish_reason: str | None
    completion_tokens: int | None
    structure_status: StructureStatus

    @property
    def truncation_observed(self) -> bool:
        if self.finish_reason is not None:
            return self.finish_reason == "length"
        return self.completion_tokens is not None and self.completion_tokens >= self.budget


@dataclass(frozen=True, slots=True)
class OutputBudgetDecision:
    action: BudgetAction
    reason: str
    current_budget: int
    next_budget: int | None
    attempt_index: int


def observe_output_budget(
    *,
    raw_response: str,
    contract: ResponseContract,
    budget: int,
    finish_reason: str | None,
    completion_tokens: int | None,
    json_normalization_policy: JsonNormalizationPolicy = "strict",
) -> OutputBudgetObservation:
    structure_status: StructureStatus = "not_applicable"
    if contract.mode == "json":
        normalized = parse_json_response(raw_response, policy=json_normalization_policy)
        parsed = normalized.parsed
        if parsed is None:
            structure_status = (
                "parse_incomplete"
                if _looks_like_incomplete_json(
                    raw_response,
                    normalized.raw_parse.error or {},
                )
                else "parse_invalid"
            )
        else:
            schema_result = (
                validate_json_schema(parsed, contract.schema)
                if contract.schema is not None
                else None
            )
            if schema_result is not None and schema_result.status == "fail":
                structure_status = "schema_invalid"
            else:
                quality = validate_response(
                    raw_response,
                    contract,
                    finish_reason=finish_reason,
                    input_char_count=(
                        len(contract.source_text) if contract.source_text is not None else None
                    ),
                    input_text=contract.source_text,
                    json_normalization_policy=json_normalization_policy,
                )
                structure_status = "valid" if quality.status == "pass" else "quality_invalid"
    else:
        quality = validate_response(
            raw_response,
            contract,
            finish_reason=finish_reason,
            input_char_count=(
                len(contract.source_text) if contract.source_text is not None else None
            ),
            input_text=contract.source_text,
        )
        structure_status = "not_applicable" if quality.status == "pass" else "quality_invalid"
    return OutputBudgetObservation(
        budget=budget,
        finish_reason=finish_reason,
        completion_tokens=completion_tokens,
        structure_status=structure_status,
    )


def decide_output_budget(
    policy: AdaptiveOutputBudgetPolicy,
    *,
    attempt_index: int,
    observation: OutputBudgetObservation,
) -> OutputBudgetDecision:
    if policy.stages is None:
        raise ValueError("output budget policy must be resolved for a response contract")
    stages = policy.stages
    if attempt_index < 1 or attempt_index > len(stages):
        raise ValueError("attempt_index must identify a configured output budget stage")
    expected_budget = stages[attempt_index - 1]
    if observation.budget != expected_budget:
        raise ValueError("observation budget must match the configured stage")

    escalation_reason: str | None = None
    if observation.truncation_observed:
        escalation_reason = "observed_truncation"
    elif observation.structure_status == "parse_incomplete":
        escalation_reason = "incomplete_structure"

    next_budget = stages[attempt_index] if attempt_index < len(stages) else None
    if escalation_reason is not None and next_budget is not None:
        return OutputBudgetDecision(
            action="escalate",
            reason=escalation_reason,
            current_budget=observation.budget,
            next_budget=next_budget,
            attempt_index=attempt_index,
        )
    if escalation_reason is not None:
        return OutputBudgetDecision(
            action="stop",
            reason=f"{escalation_reason}_limit_reached",
            current_budget=observation.budget,
            next_budget=None,
            attempt_index=attempt_index,
        )

    stop_reasons = {
        "valid": "complete_valid_structure",
        "schema_invalid": "complete_schema_invalid",
        "quality_invalid": "complete_quality_failure",
        "parse_invalid": "malformed_json",
        "not_applicable": "complete_output",
    }
    return OutputBudgetDecision(
        action="stop",
        reason=stop_reasons.get(observation.structure_status, "complete_output"),
        current_budget=observation.budget,
        next_budget=None,
        attempt_index=attempt_index,
    )


def _looks_like_incomplete_json(raw_response: str, error: Mapping[str, object]) -> bool:
    stripped = raw_response.rstrip()
    if not stripped:
        return True
    message = error.get("message")
    if isinstance(message, str) and message.startswith("Unterminated string"):
        return True
    position = error.get("offset")
    if isinstance(position, int) and position < len(stripped) - 1:
        return False

    stack: list[str] = []
    in_string = False
    escaped = False
    for character in stripped:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            stack.append(character)
        elif character in "]}":
            expected = "[" if character == "]" else "{"
            if not stack or stack.pop() != expected:
                return False
    return in_string or bool(stack)


def _estimate_contract_chars(contract: ResponseContract) -> int:
    estimates = [1]
    if contract.schema is not None:
        estimates.append(_estimate_schema_chars(contract.schema))
    if contract.expected_output is not None:
        estimates.append(
            len(
                json.dumps(
                    contract.expected_output,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        )
    if contract.source_text is not None:
        ratio = contract.max_length_ratio if contract.max_length_ratio is not None else 1.0
        estimates.append(math.ceil(len(contract.source_text) * max(0.1, ratio)))
    return max(estimates)


def _estimate_schema_chars(schema: Mapping[str, Any], *, depth: int = 0) -> int:
    if depth >= 12:
        return 256
    if "const" in schema:
        return len(json.dumps(schema["const"], ensure_ascii=False))
    enum = schema.get("enum")
    if isinstance(enum, Sequence) and not isinstance(enum, (str, bytes, bytearray)) and enum:
        return max(len(json.dumps(item, ensure_ascii=False)) for item in enum)

    schema_type = schema.get("type")
    if isinstance(schema_type, Sequence) and not isinstance(schema_type, str):
        schema_type = next((item for item in schema_type if item != "null"), "string")
    if schema_type == "string":
        return max(int(schema.get("minLength", 0)), int(schema.get("maxLength", 256))) + 2
    if schema_type in {"integer", "number"}:
        return 16
    if schema_type == "boolean":
        return 5
    if schema_type == "array":
        prefix_items = schema.get("prefixItems")
        if isinstance(prefix_items, Sequence) and not isinstance(
            prefix_items, (str, bytes, bytearray)
        ):
            item_sizes = [
                _estimate_schema_chars(item, depth=depth + 1)
                for item in prefix_items
                if isinstance(item, Mapping)
            ]
            return 2 + sum(item_sizes) + max(0, len(item_sizes) - 1)
        count = int(schema.get("maxItems", schema.get("minItems", 1)))
        item_schema = schema.get("items")
        item_size = (
            _estimate_schema_chars(item_schema, depth=depth + 1)
            if isinstance(item_schema, Mapping)
            else 16
        )
        return 2 + count * item_size + max(0, count - 1)
    if schema_type == "object" or isinstance(schema.get("properties"), Mapping):
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            return 256
        members = [
            len(json.dumps(str(name))) + 1 + _estimate_schema_chars(child, depth=depth + 1)
            for name, child in properties.items()
            if isinstance(child, Mapping)
        ]
        return 2 + sum(members) + max(0, len(members) - 1)
    return 256


def _bounded_power_of_two(value: int, *, minimum: int, maximum: int) -> int:
    bounded = max(minimum, min(value, maximum))
    power = 1 << (bounded - 1).bit_length()
    return min(power, maximum)


__all__ = [
    "AdaptiveOutputBudgetPolicy",
    "OutputBudgetDecision",
    "OutputBudgetObservation",
    "decide_output_budget",
    "observe_output_budget",
]
