from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol, cast

from .output_budget import (
    AdaptiveOutputBudgetPolicy,
    decide_output_budget,
    observe_output_budget,
)
from .requests import RequestPlan, RequestResult


class ManagedExecutorError(RuntimeError):
    """Raised when managed executor guardrails reject a request."""


SUPPORTED_MANAGED_CONTEXT_LENGTHS = frozenset({8192, 16384, 32768})


@dataclass(frozen=True, slots=True)
class ManagedExecutionResult:
    raw_response: str
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    finish_reason: str | None
    load_verified: bool
    cleanup_verified: bool
    final_loaded_instances: int | None
    cached_tokens: int | None = None
    post_load_instances: int | None = None
    strict_schema_runtime_support: bool | None = None
    hardened_schema_validation_available: bool = True
    session_id: str | None = None
    session_request_index: int | None = None
    session_request_count: int | None = None
    load_scope: str | None = None
    cleanup_scope: str | None = None
    loaded_before_session: int | None = None
    loaded_after_session_load: int | None = None
    session_cleanup_verified: bool | None = None
    output_budget_attempts: int = 1
    output_budgets_used: tuple[int, ...] = ()
    output_budget_stop_reason: str | None = None


class ManagedHostRunner(Protocol):
    """Host-owned LM Studio lifecycle and compat-chat seam.

    The public lab kit does not own process lifecycle or private host coupling.
    Tests and host applications inject an object matching this narrow protocol.
    """

    def load_model(
        self,
        *,
        model_id: str,
        context_length: int,
        parallel: int,
    ) -> object: ...

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
    ) -> object: ...

    def cleanup_model(self, *, model_id: str) -> object: ...

    def count_loaded_instances(self, *, model_id: str) -> int | None: ...


@dataclass(frozen=True, slots=True)
class ManagedLMStudioExecutor:
    """Guarded adapter for a host-managed LM Studio runner.

    Version 1 intentionally supports a narrow text-only live shape: structured
    JSON over OpenAI-compatible ``/v1/chat/completions`` with explicit context
    lengths, parallel 1, and temperature 0. It performs no network I/O unless a
    host runner is injected.
    """

    host_runner: ManagedHostRunner
    allow_model_loads: bool = False
    endpoint_path: str = "/v1/chat/completions"
    context_length: int = 8192
    parallel: int = 1
    temperature: float = 0.0
    strict_json_schema: bool = True
    output_budget_policy: AdaptiveOutputBudgetPolicy | None = None

    def __post_init__(self) -> None:
        if self.endpoint_path != "/v1/chat/completions":
            raise ManagedExecutorError("managed executor supports only /v1/chat/completions")
        if self.context_length not in SUPPORTED_MANAGED_CONTEXT_LENGTHS:
            supported = ", ".join(str(item) for item in sorted(SUPPORTED_MANAGED_CONTEXT_LENGTHS))
            raise ManagedExecutorError(f"managed executor supported context lengths: {supported}")
        if self.parallel != 1:
            raise ManagedExecutorError("managed executor v1 requires parallel 1")
        if self.temperature != 0:
            raise ManagedExecutorError("managed executor v1 requires temperature 0")

    def execute(self, plan: RequestPlan) -> ManagedExecutionResult:
        return self._execute_plans((plan,), load_scope="per_request", cleanup_scope="per_request")[
            0
        ]

    def execute_session(self, plans: Sequence[RequestPlan]) -> tuple[ManagedExecutionResult, ...]:
        return self._execute_plans(plans, load_scope="per_session", cleanup_scope="per_session")

    def _execute_plans(
        self,
        plans: Sequence[RequestPlan],
        *,
        load_scope: str,
        cleanup_scope: str,
    ) -> tuple[ManagedExecutionResult, ...]:
        if not plans:
            return ()
        for plan in plans:
            self._validate_plan(plan)
        if not self.allow_model_loads:
            raise ManagedExecutorError(
                "managed executor model loads require allow_model_loads=true"
            )
        first_plan = plans[0]
        model_id = first_plan.options.model_id
        if any(plan.options.model_id != model_id for plan in plans):
            raise ManagedExecutorError("managed executor session requires one model_id")
        if any(plan.options.context_tier != first_plan.options.context_tier for plan in plans):
            raise ManagedExecutorError("managed executor session requires one context_tier")
        if any(
            plan.options.endpoint_family != first_plan.options.endpoint_family for plan in plans
        ):
            raise ManagedExecutorError("managed executor session requires one endpoint_family")
        pre_load_instances = self.host_runner.count_loaded_instances(model_id=model_id)
        if pre_load_instances is None:
            raise ManagedExecutorError("managed executor pre-load state was not verified")
        if pre_load_instances != 0:
            raise ManagedExecutorError("managed executor refuses to reuse dirty loaded state")
        load_response = self.host_runner.load_model(
            model_id=model_id,
            context_length=self.context_length,
            parallel=self.parallel,
        )
        load_verified = _load_verified(
            load_response,
            context_length=self.context_length,
            parallel=self.parallel,
        )
        if not load_verified:
            cleanup_response = self.host_runner.cleanup_model(model_id=model_id)
            cleanup_verified = _verified_flag(cleanup_response, "cleanup_verified")
            final_loaded_instances = self.host_runner.count_loaded_instances(model_id=model_id)
            if not cleanup_verified or final_loaded_instances != 0:
                raise ManagedExecutorError("managed executor load and cleanup were not verified")
            mismatch = _load_verification_mismatch(
                load_response,
                context_length=self.context_length,
                parallel=self.parallel,
            )
            if mismatch is not None:
                raise ManagedExecutorError(mismatch)
            raise ManagedExecutorError("managed executor load was not verified")
        post_load_instances = self.host_runner.count_loaded_instances(model_id=model_id)
        if post_load_instances is None:
            cleanup_response = self.host_runner.cleanup_model(model_id=model_id)
            cleanup_verified = _verified_flag(cleanup_response, "cleanup_verified")
            final_loaded_instances = self.host_runner.count_loaded_instances(model_id=model_id)
            if not cleanup_verified or final_loaded_instances != 0:
                raise ManagedExecutorError(
                    "managed executor load state and cleanup were not verified"
                )
            raise ManagedExecutorError("managed executor loaded state was not verified")
        if post_load_instances <= 0:
            cleanup_response = self.host_runner.cleanup_model(model_id=model_id)
            cleanup_verified = _verified_flag(cleanup_response, "cleanup_verified")
            final_loaded_instances = self.host_runner.count_loaded_instances(model_id=model_id)
            if not cleanup_verified or final_loaded_instances != 0:
                raise ManagedExecutorError(
                    "managed executor load state and cleanup were not verified"
                )
            raise ManagedExecutorError("managed executor loaded instance was not visible")
        session_id = _session_id(model_id=model_id, plans=plans)
        payloads: list[
            tuple[
                str,
                float,
                int | None,
                int | None,
                int | None,
                str | None,
                tuple[int, ...],
                str | None,
            ]
        ] = []
        try:
            for plan in plans:
                adaptive_policy = (
                    self.output_budget_policy if plan.options.max_tokens is None else None
                )
                budgets: tuple[int | None, ...] = (
                    adaptive_policy.stages_for(plan.envelope.response_contract)
                    if adaptive_policy is not None
                    else (plan.options.max_tokens,)
                )
                if adaptive_policy is not None:
                    adaptive_policy = adaptive_policy.resolved_for(plan.envelope.response_contract)
                budgets_used: list[int] = []
                total_latency_ms = 0.0
                raw_response = ""
                prompt_tokens: int | None = None
                completion_tokens: int | None = None
                cached_tokens: int | None = None
                finish_reason: str | None = None
                stop_reason: str | None = (
                    "caller_override" if plan.options.max_tokens is not None else None
                )
                for attempt_index, max_tokens in enumerate(budgets, start=1):
                    started = time.monotonic()
                    chat_options: dict[str, Any] = {
                        "endpoint_path": self.endpoint_path,
                        "model_id": model_id,
                        "messages": _messages_from_plan(plan),
                        "response_format": _response_format_from_plan(
                            plan, strict_json_schema=self.strict_json_schema
                        ),
                        "temperature": self.temperature,
                        "timeout_s": plan.options.timeout_s,
                    }
                    if max_tokens is not None:
                        chat_options["max_tokens"] = max_tokens
                    raw_payload = self.host_runner.chat_completion(**chat_options)
                    total_latency_ms += (time.monotonic() - started) * 1000
                    (
                        raw_response,
                        prompt_tokens,
                        completion_tokens,
                        cached_tokens,
                        finish_reason,
                    ) = _parse_chat_payload(raw_payload)
                    if adaptive_policy is None:
                        break
                    assert max_tokens is not None
                    budgets_used.append(max_tokens)
                    observation = observe_output_budget(
                        raw_response=raw_response,
                        contract=plan.envelope.response_contract,
                        budget=max_tokens,
                        finish_reason=finish_reason,
                        completion_tokens=completion_tokens,
                    )
                    decision = decide_output_budget(
                        adaptive_policy,
                        attempt_index=attempt_index,
                        observation=observation,
                    )
                    stop_reason = decision.reason
                    if decision.action == "stop":
                        break
                payloads.append(
                    (
                        raw_response,
                        round(total_latency_ms, 3),
                        prompt_tokens,
                        completion_tokens,
                        cached_tokens,
                        finish_reason,
                        tuple(budgets_used),
                        stop_reason,
                    )
                )
        finally:
            cleanup_response = self.host_runner.cleanup_model(model_id=model_id)
            cleanup_verified = _verified_flag(cleanup_response, "cleanup_verified")
            final_loaded_instances = self.host_runner.count_loaded_instances(model_id=model_id)
            if not cleanup_verified:
                raise ManagedExecutorError("managed executor cleanup was not verified")
            if final_loaded_instances != 0:
                raise ManagedExecutorError("managed executor final loaded instances must be zero")
        results: list[ManagedExecutionResult] = []
        for index, payload in enumerate(payloads, start=1):
            (
                raw_response,
                latency_ms,
                prompt_tokens,
                completion_tokens,
                cached_tokens,
                finish_reason,
                output_budgets_used,
                output_budget_stop_reason,
            ) = payload
            results.append(
                ManagedExecutionResult(
                    raw_response=raw_response,
                    latency_ms=latency_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cached_tokens,
                    finish_reason=finish_reason,
                    load_verified=load_verified,
                    cleanup_verified=cleanup_verified,
                    final_loaded_instances=final_loaded_instances,
                    post_load_instances=post_load_instances,
                    strict_schema_runtime_support=self.strict_json_schema,
                    hardened_schema_validation_available=True,
                    session_id=session_id,
                    session_request_index=index,
                    session_request_count=len(payloads),
                    load_scope=load_scope,
                    cleanup_scope=cleanup_scope,
                    loaded_before_session=pre_load_instances,
                    loaded_after_session_load=post_load_instances,
                    session_cleanup_verified=cleanup_verified,
                    output_budget_attempts=max(1, len(output_budgets_used)),
                    output_budgets_used=output_budgets_used,
                    output_budget_stop_reason=output_budget_stop_reason,
                )
            )
        return tuple(results)

    def _validate_plan(self, plan: RequestPlan) -> None:
        if plan.envelope.modality == "image":
            raise NotImplementedError("managed executor v1 does not support image requests")
        if plan.envelope.modality != "text":
            raise ManagedExecutorError("managed executor v1 supports text modality only")
        if plan.options.endpoint_family != "openai_compat":
            raise ManagedExecutorError(
                "managed executor v1 supports only openai_compat endpoint family"
            )
        if plan.options.context_tier != str(self.context_length):
            raise ManagedExecutorError("managed executor context_tier must match executor context")
        if plan.options.temperature != 0:
            raise ManagedExecutorError("managed executor v1 requires temperature 0")
        if plan.envelope.response_contract.mode != "json":
            raise ManagedExecutorError("managed executor v1 supports structured JSON only")
        if plan.envelope.response_contract.schema is None:
            raise ManagedExecutorError("managed executor v1 requires a JSON schema")


@dataclass(frozen=True, slots=True)
class ManagedLMStudioTransport:
    """Matrix transport adapter for ``ManagedLMStudioExecutor`` results."""

    executor: ManagedLMStudioExecutor

    def execute(self, plan: RequestPlan, *, attempt_index: int = 1) -> tuple[str, RequestResult]:
        if attempt_index < 1:
            raise ManagedExecutorError("attempt_index must be positive")
        execution = self.executor.execute(plan)
        return _transport_result(plan=plan, execution=execution)

    def execute_session(
        self, plans: Sequence[RequestPlan], *, attempt_index: int = 1
    ) -> tuple[tuple[str, RequestResult], ...]:
        if attempt_index < 1:
            raise ManagedExecutorError("attempt_index must be positive")
        executions = self.executor.execute_session(tuple(plans))
        return tuple(
            _transport_result(plan=plan, execution=execution)
            for plan, execution in zip(plans, executions, strict=True)
        )


def _transport_result(
    *, plan: RequestPlan, execution: ManagedExecutionResult
) -> tuple[str, RequestResult]:
    return (
        execution.raw_response,
        RequestResult.from_raw_response(
            request_id=plan.envelope.request_id,
            model_id=plan.options.model_id,
            raw_response=execution.raw_response,
            status="ok",
            latency_ms=execution.latency_ms,
            token_counts=_token_counts(execution),
            finish_reason=execution.finish_reason,
            lifecycle_metadata=_lifecycle_metadata(execution),
        ),
    )


def _session_id(*, model_id: str, plans: Sequence[RequestPlan]) -> str:
    material = "|".join([model_id, *(plan.envelope.request_id for plan in plans)])
    return "session_" + sha256(material.encode("utf-8")).hexdigest()[:16]


def _lifecycle_metadata(execution: ManagedExecutionResult) -> dict[str, object]:
    return {
        "session_id": execution.session_id,
        "session_request_index": execution.session_request_index,
        "session_request_count": execution.session_request_count,
        "load_scope": execution.load_scope,
        "cleanup_scope": execution.cleanup_scope,
        "loaded_before_session": execution.loaded_before_session,
        "loaded_after_session_load": execution.loaded_after_session_load,
        "final_loaded_instances": execution.final_loaded_instances,
        "session_cleanup_verified": execution.session_cleanup_verified,
        "output_budget_attempts": execution.output_budget_attempts,
        "output_budgets_used": list(execution.output_budgets_used),
        "output_budget_stop_reason": execution.output_budget_stop_reason,
    }


def _messages_from_plan(plan: RequestPlan) -> tuple[Mapping[str, str], ...]:
    if plan.envelope.chat_messages:
        return tuple(
            {"role": message.role, "content": message.content}
            for message in plan.envelope.chat_messages
        )
    return tuple({"role": "user", "content": item.text} for item in plan.envelope.text_inputs)


def _response_format_from_plan(
    plan: RequestPlan, *, strict_json_schema: bool = True
) -> Mapping[str, object]:
    schema = plan.envelope.response_contract.schema
    if schema is None:
        raise ManagedExecutorError("managed executor v1 requires a JSON schema")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "labkit_response",
            "schema": _lmstudio_runtime_schema(schema),
            "strict": strict_json_schema,
        },
    }


def _lmstudio_runtime_schema(schema: Mapping[str, object]) -> Mapping[str, object]:
    """Lower LabKit validation schemas to the LM Studio JSON-schema subset.

    LabKit keeps stricter validation locally (including ordered ``prefixItems``
    with per-position ``const`` ids). LM Studio's live ``json_schema`` endpoint
    rejects that shape, so the runtime request uses an equivalent-enough array
    item schema and LabKit validates exact order after generation.
    """

    return cast(Mapping[str, object], _lower_prefix_items_schema(schema))


def _lower_prefix_items_schema(value: Any) -> Any:
    if isinstance(value, Mapping):
        lowered = {str(key): _lower_prefix_items_schema(item) for key, item in value.items()}
        prefix_items = value.get("prefixItems")
        if isinstance(prefix_items, Sequence) and not isinstance(
            prefix_items, (str, bytes, bytearray)
        ):
            merged = _merge_prefix_items(tuple(prefix_items))
            if merged is not None:
                lowered.pop("prefixItems", None)
                if lowered.get("items") is False:
                    lowered.pop("items", None)
                lowered["items"] = merged
        return lowered
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_lower_prefix_items_schema(item) for item in value]
    return value


def _merge_prefix_items(prefix_items: Sequence[object]) -> dict[str, Any] | None:
    if not prefix_items or not all(isinstance(item, Mapping) for item in prefix_items):
        return None
    first = prefix_items[0]
    assert isinstance(first, Mapping)
    merged: dict[str, Any] = {
        str(key): _lower_prefix_items_schema(item) for key, item in first.items()
    }
    properties = first.get("properties")
    if not isinstance(properties, Mapping):
        return merged
    maybe_merged_properties = merged.get("properties", {})
    merged_properties: dict[str, Any] = (
        dict(maybe_merged_properties) if isinstance(maybe_merged_properties, Mapping) else {}
    )
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_name, str) or not isinstance(prop_schema, Mapping):
            continue
        const_values: list[object] = []
        all_have_const = True
        for item in prefix_items:
            assert isinstance(item, Mapping)
            item_properties = item.get("properties")
            if not isinstance(item_properties, Mapping):
                all_have_const = False
                break
            maybe_schema = item_properties.get(prop_name)
            if not isinstance(maybe_schema, Mapping) or "const" not in maybe_schema:
                all_have_const = False
                break
            const_values.append(maybe_schema["const"])
        if all_have_const:
            merged_properties[prop_name] = {"enum": const_values}
    if merged_properties:
        merged["properties"] = merged_properties
    return merged


def _parse_chat_payload(
    payload: object,
) -> tuple[str, int | None, int | None, int | None, str | None]:
    if isinstance(payload, str):
        return payload, None, None, None, None
    if not isinstance(payload, Mapping):
        raise ManagedExecutorError("chat completion payload must be text or a mapping")
    raw_response = _extract_content(payload)
    if raw_response is None:
        raise ManagedExecutorError("chat completion payload did not include message content")
    usage = payload.get("usage")
    prompt_tokens = (
        _int_from_mapping(usage, "prompt_tokens") if isinstance(usage, Mapping) else None
    )
    completion_tokens = (
        _int_from_mapping(usage, "completion_tokens") if isinstance(usage, Mapping) else None
    )
    cached_tokens = _cached_tokens_from_usage(usage) if isinstance(usage, Mapping) else None
    finish_reason = _extract_finish_reason(payload)
    return raw_response, prompt_tokens, completion_tokens, cached_tokens, finish_reason


def _cached_tokens_from_usage(usage: Mapping[str, object]) -> int | None:
    direct = _int_from_mapping(usage, "cached_tokens")
    if direct is not None:
        return direct
    for details_key in ("prompt_tokens_details", "input_tokens_details"):
        details = usage.get(details_key)
        if isinstance(details, Mapping):
            cached = _int_from_mapping(details, "cached_tokens")
            if cached is not None:
                return cached
    return None


def _extract_content(payload: Mapping[str, object]) -> str | None:
    direct = payload.get("content")
    if isinstance(direct, str):
        return direct
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        return None
    message = first_choice.get("message")
    if isinstance(message, Mapping):
        content = message.get("content")
        return content if isinstance(content, str) else None
    text = first_choice.get("text")
    return text if isinstance(text, str) else None


def _extract_finish_reason(payload: Mapping[str, object]) -> str | None:
    direct = payload.get("finish_reason")
    if isinstance(direct, str):
        return direct
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
        finish_reason = choices[0].get("finish_reason")
        return finish_reason if isinstance(finish_reason, str) else None
    return None


def _int_from_mapping(mapping: Mapping[str, object], key: str) -> int | None:
    value = mapping.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _verified_flag(value: object, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        flag = value.get(key)
        if isinstance(flag, bool):
            return flag
        status = value.get("status")
        if isinstance(status, str):
            return status.lower() in {"ok", "success", "verified", "loaded", "unloaded"}
    return False


def _load_verified(value: object, *, context_length: int, parallel: int) -> bool:
    if not _verified_flag(value, "load_verified"):
        return False
    if not isinstance(value, Mapping):
        return False
    applied = value.get("applied_load_config")
    if not isinstance(applied, Mapping):
        applied = value.get("load_config")
    if not isinstance(applied, Mapping):
        return False
    observed_context = _first_int_value(applied, "context_length", "contextLength")
    observed_parallel = _first_int_value(applied, "parallel", "n_parallel", "numParallelSequences")
    if observed_context != context_length:
        return False
    if observed_parallel != parallel:
        return False
    return True


def _load_verification_mismatch(value: object, *, context_length: int, parallel: int) -> str | None:
    if not _verified_flag(value, "load_verified"):
        return None
    if not isinstance(value, Mapping):
        return None
    applied = value.get("applied_load_config")
    if not isinstance(applied, Mapping):
        applied = value.get("load_config")
    if not isinstance(applied, Mapping):
        return None
    observed_context = _first_int_value(applied, "context_length", "contextLength")
    observed_parallel = _first_int_value(applied, "parallel", "n_parallel", "numParallelSequences")
    if observed_context != context_length:
        return "runner_or_runtime_context_mismatch"
    if observed_parallel != parallel:
        return "runner_or_runtime_parallel_mismatch"
    return None


def _first_int_value(mapping: Mapping[str, object], *keys: str) -> int | None:
    for key in keys:
        value = _int_from_mapping(mapping, key)
        if value is not None:
            return value
    return None


@dataclass(frozen=True, slots=True)
class LocalLMStudioHostRunner:
    """Minimal local LM Studio host runner for explicit operator live-small runs.

    It uses only the local LM Studio HTTP API, never downloads models, and stores no
    raw prompt/response artifacts by itself. The caller must still opt in through
    ``ManagedLMStudioExecutor(allow_model_loads=True)`` and CLI live flags.
    """

    base_url: str = "http://127.0.0.1:1234"
    default_timeout_s: float = 120.0
    allow_remote_base_url: bool = False

    def __post_init__(self) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ManagedExecutorError("base_url scheme must be http or https")
        if (
            parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            and not self.allow_remote_base_url
        ):
            raise ManagedExecutorError("remote base_url requires allow_remote_base_url=true")

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        payload = {
            "model": model_id,
            "context_length": context_length,
            "parallel": parallel,
            "echo_load_config": True,
        }
        response = self._request_json("/api/v1/models/load", payload, self.default_timeout_s)
        if not isinstance(response, Mapping):
            return {"load_verified": False}
        applied = response.get("applied_load_config")
        if not isinstance(applied, Mapping):
            applied = response.get("load_config")
        return {
            "load_verified": isinstance(applied, Mapping),
            "applied_load_config": applied if isinstance(applied, Mapping) else None,
            "load_config": response.get("load_config")
            if isinstance(response.get("load_config"), Mapping)
            else None,
            "instance_id": _first_str(response, ("instance_id", "instanceId", "id")),
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
        if endpoint_path != "/v1/chat/completions":
            raise ManagedExecutorError("local managed runner supports only /v1/chat/completions")
        payload = {
            "model": model_id,
            "messages": list(messages),
            "response_format": dict(response_format),
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return self._request_json(endpoint_path, payload, timeout_s)

    def cleanup_model(self, *, model_id: str) -> object:
        instance_ids = self._loaded_instance_ids(model_id=model_id)
        if instance_ids is None:
            return {"cleanup_verified": False}
        for instance_id in instance_ids:
            self._request_json(
                "/api/v1/models/unload",
                {"instance_id": instance_id},
                self.default_timeout_s,
            )
        return {"cleanup_verified": self.count_loaded_instances(model_id=model_id) == 0}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        instance_ids = self._loaded_instance_ids(model_id=model_id)
        return None if instance_ids is None else len(instance_ids)

    def _loaded_instance_ids(self, *, model_id: str) -> list[str] | None:
        response = self._request_json("/api/v1/models", None, self.default_timeout_s)
        if not isinstance(response, Mapping):
            return None
        models = response.get("models", response.get("data"))
        if not isinstance(models, Sequence) or isinstance(models, (str, bytes, bytearray)):
            return None
        instance_ids: list[str] = []
        for item in models:
            if not isinstance(item, Mapping):
                continue
            identifiers = {
                item.get("id"),
                item.get("model"),
                item.get("path"),
                item.get("key"),
                item.get("name"),
            }
            if model_id in identifiers:
                loaded = item.get("loaded_instances", item.get("instances"))
                if isinstance(loaded, Sequence) and not isinstance(loaded, (str, bytes, bytearray)):
                    for instance in loaded:
                        if isinstance(instance, Mapping):
                            instance_id = _first_str(instance, ("id", "instance_id", "instanceId"))
                            if instance_id is not None:
                                instance_ids.append(instance_id)
                    continue
                if item.get("loaded") is True or item.get("state") == "loaded":
                    instance_id = _first_str(item, ("instance_id", "instanceId", "id", "key"))
                    if instance_id is not None:
                        instance_ids.append(instance_id)
        return instance_ids

    def _request_json(
        self, path: str, payload: Mapping[str, object] | None, timeout_s: float
    ) -> Mapping[str, object]:
        import json
        from urllib import request as urllib_request
        from urllib.error import HTTPError, URLError

        url = self.base_url.rstrip("/") + path
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=data,
            method="GET" if payload is None else "POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib_request.urlopen(req, timeout=timeout_s) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            detail = _safe_http_error_detail(error)
            raise ManagedExecutorError(
                f"LM Studio HTTP error: {error.code} at {path}{detail}"
            ) from error
        except URLError as error:
            raise ManagedExecutorError("LM Studio local endpoint is not reachable") from error
        try:
            decoded = json.loads(raw) if raw else {}
        except json.JSONDecodeError as error:
            raise ManagedExecutorError("LM Studio response was not JSON") from error
        if not isinstance(decoded, Mapping):
            raise ManagedExecutorError("LM Studio response JSON must be an object")
        return decoded


def _coerce_positive_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _safe_http_error_detail(error: object) -> str:
    read = getattr(error, "read", None)
    if not callable(read):
        return ""
    try:
        raw_value = read()
        raw = (
            raw_value.decode("utf-8", errors="replace")[:500]
            if isinstance(raw_value, bytes | bytearray)
            else str(raw_value)[:500]
        )
    except Exception:
        return ""
    if not raw:
        return ""
    try:
        import json

        payload = json.loads(raw)
    except Exception:
        return ": response_body=non_json"
    if not isinstance(payload, Mapping):
        return ": response_body=non_object"
    maybe_error = payload.get("error")
    if isinstance(maybe_error, Mapping):
        payload = maybe_error
    safe: dict[str, object] = {}
    for key in ("error", "message", "code", "type", "param"):
        value = payload.get(key)
        if isinstance(value, str):
            safe[key] = value[:200]
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
    if not safe:
        return ": response_body=object_without_safe_error_fields"
    parts = [f"{key}={safe[key]!r}" for key in sorted(safe)]
    return ": " + ", ".join(parts)


def _first_str(payload: Mapping[str, object], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _token_counts(result: ManagedExecutionResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    if result.prompt_tokens is not None:
        counts["prompt"] = result.prompt_tokens
    if result.completion_tokens is not None:
        counts["completion"] = result.completion_tokens
    if result.cached_tokens is not None:
        counts["cached"] = result.cached_tokens
    return counts


__all__ = [
    "LocalLMStudioHostRunner",
    "ManagedExecutionResult",
    "ManagedExecutorError",
    "ManagedHostRunner",
    "ManagedLMStudioExecutor",
    "ManagedLMStudioTransport",
]
