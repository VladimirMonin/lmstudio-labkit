from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .requests import RequestPlan, RequestResult


class ManagedExecutorError(RuntimeError):
    """Raised when managed executor guardrails reject a request."""


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
    post_load_instances: int | None = None
    strict_schema_runtime_support: bool | None = None
    hardened_schema_validation_available: bool = True


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
    ) -> object: ...

    def cleanup_model(self, *, model_id: str) -> object: ...

    def count_loaded_instances(self, *, model_id: str) -> int | None: ...


@dataclass(frozen=True, slots=True)
class ManagedLMStudioExecutor:
    """Guarded adapter for a host-managed LM Studio runner.

    Version 1 intentionally supports one shape only: text, structured JSON,
    OpenAI-compatible ``/v1/chat/completions``, context 8192, parallel 1,
    temperature 0. It performs no network I/O unless a host runner is injected.
    """

    host_runner: ManagedHostRunner
    allow_model_loads: bool = False
    endpoint_path: str = "/v1/chat/completions"
    context_length: int = 8192
    parallel: int = 1
    temperature: float = 0.0
    strict_json_schema: bool = True

    def __post_init__(self) -> None:
        if self.endpoint_path != "/v1/chat/completions":
            raise ManagedExecutorError("managed executor supports only /v1/chat/completions")
        if self.context_length != 8192:
            raise ManagedExecutorError("managed executor v1 requires context 8192")
        if self.parallel != 1:
            raise ManagedExecutorError("managed executor v1 requires parallel 1")
        if self.temperature != 0:
            raise ManagedExecutorError("managed executor v1 requires temperature 0")

    def execute(self, plan: RequestPlan) -> ManagedExecutionResult:
        self._validate_plan(plan)
        if not self.allow_model_loads:
            raise ManagedExecutorError(
                "managed executor model loads require allow_model_loads=true"
            )
        started = time.monotonic()
        load_response = self.host_runner.load_model(
            model_id=plan.options.model_id,
            context_length=self.context_length,
            parallel=self.parallel,
        )
        load_verified = _load_verified(
            load_response,
            context_length=self.context_length,
            parallel=self.parallel,
        )
        if not load_verified:
            cleanup_response = self.host_runner.cleanup_model(model_id=plan.options.model_id)
            cleanup_verified = _verified_flag(cleanup_response, "cleanup_verified")
            final_loaded_instances = self.host_runner.count_loaded_instances(
                model_id=plan.options.model_id
            )
            if not cleanup_verified or final_loaded_instances != 0:
                raise ManagedExecutorError("managed executor load and cleanup were not verified")
            raise ManagedExecutorError("managed executor load was not verified")
        post_load_instances = self.host_runner.count_loaded_instances(
            model_id=plan.options.model_id
        )
        if post_load_instances is None:
            cleanup_response = self.host_runner.cleanup_model(model_id=plan.options.model_id)
            cleanup_verified = _verified_flag(cleanup_response, "cleanup_verified")
            final_loaded_instances = self.host_runner.count_loaded_instances(
                model_id=plan.options.model_id
            )
            if not cleanup_verified or final_loaded_instances != 0:
                raise ManagedExecutorError(
                    "managed executor load state and cleanup were not verified"
                )
            raise ManagedExecutorError("managed executor loaded state was not verified")
        if post_load_instances <= 0:
            cleanup_response = self.host_runner.cleanup_model(model_id=plan.options.model_id)
            cleanup_verified = _verified_flag(cleanup_response, "cleanup_verified")
            final_loaded_instances = self.host_runner.count_loaded_instances(
                model_id=plan.options.model_id
            )
            if not cleanup_verified or final_loaded_instances != 0:
                raise ManagedExecutorError(
                    "managed executor load state and cleanup were not verified"
                )
            raise ManagedExecutorError("managed executor loaded instance was not visible")
        try:
            raw_payload = self.host_runner.chat_completion(
                endpoint_path=self.endpoint_path,
                model_id=plan.options.model_id,
                messages=_messages_from_plan(plan),
                response_format=_response_format_from_plan(
                    plan, strict_json_schema=self.strict_json_schema
                ),
                temperature=self.temperature,
                timeout_s=plan.options.timeout_s,
            )
        finally:
            cleanup_response = self.host_runner.cleanup_model(model_id=plan.options.model_id)
            cleanup_verified = _verified_flag(cleanup_response, "cleanup_verified")
            final_loaded_instances = self.host_runner.count_loaded_instances(
                model_id=plan.options.model_id
            )
            if not cleanup_verified:
                raise ManagedExecutorError("managed executor cleanup was not verified")
            if final_loaded_instances != 0:
                raise ManagedExecutorError("managed executor final loaded instances must be zero")
        raw_response, prompt_tokens, completion_tokens, finish_reason = _parse_chat_payload(
            raw_payload
        )
        latency_ms = round((time.monotonic() - started) * 1000, 3)
        return ManagedExecutionResult(
            raw_response=raw_response,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
            load_verified=load_verified,
            cleanup_verified=cleanup_verified,
            final_loaded_instances=final_loaded_instances,
            post_load_instances=post_load_instances,
            strict_schema_runtime_support=self.strict_json_schema,
            hardened_schema_validation_available=True,
        )

    def _validate_plan(self, plan: RequestPlan) -> None:
        if plan.envelope.modality == "image":
            raise NotImplementedError("managed executor v1 does not support image requests")
        if plan.envelope.modality != "text":
            raise ManagedExecutorError("managed executor v1 supports text modality only")
        if plan.options.endpoint_family != "openai_compat":
            raise ManagedExecutorError(
                "managed executor v1 supports only openai_compat endpoint family"
            )
        if plan.options.context_tier != "8192":
            raise ManagedExecutorError("managed executor v1 requires context_tier=8192")
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
        return execution.raw_response, RequestResult.from_raw_response(
            request_id=plan.envelope.request_id,
            model_id=plan.options.model_id,
            raw_response=execution.raw_response,
            status="ok",
            latency_ms=execution.latency_ms,
            token_counts=_token_counts(execution),
            finish_reason=execution.finish_reason,
        )


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
            "schema": schema,
            "strict": strict_json_schema,
        },
    }


def _parse_chat_payload(payload: object) -> tuple[str, int | None, int | None, str | None]:
    if isinstance(payload, str):
        return payload, None, None, None
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
    finish_reason = _extract_finish_reason(payload)
    return raw_response, prompt_tokens, completion_tokens, finish_reason


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
    ) -> object:
        if endpoint_path != "/v1/chat/completions":
            raise ManagedExecutorError("local managed runner supports only /v1/chat/completions")
        payload = {
            "model": model_id,
            "messages": list(messages),
            "response_format": dict(response_format),
            "temperature": temperature,
        }
        return self._request_json(endpoint_path, payload, timeout_s)

    def cleanup_model(self, *, model_id: str) -> object:
        response = self._request_json(
            "/api/v1/models/unload",
            {"model": model_id},
            self.default_timeout_s,
        )
        status = str(response.get("status", "")).lower() if isinstance(response, Mapping) else ""
        return {"cleanup_verified": status in {"", "ok", "success", "unloaded"} or bool(response)}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        response = self._request_json("/api/v1/models", None, self.default_timeout_s)
        if not isinstance(response, Mapping):
            return None
        models = response.get("models", response.get("data"))
        if not isinstance(models, Sequence) or isinstance(models, (str, bytes, bytearray)):
            return None
        count = 0
        for item in models:
            if not isinstance(item, Mapping):
                continue
            identifiers = {item.get("id"), item.get("model"), item.get("path"), item.get("key")}
            if model_id in identifiers:
                loaded = item.get("loaded_instances", item.get("instances"))
                if isinstance(loaded, Sequence) and not isinstance(loaded, (str, bytes, bytearray)):
                    count += len(loaded)
                elif item.get("loaded") is True or item.get("state") == "loaded":
                    count += 1
        return count

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
            raise ManagedExecutorError(f"LM Studio HTTP error: {error.code}") from error
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
    return counts


__all__ = [
    "LocalLMStudioHostRunner",
    "ManagedExecutionResult",
    "ManagedExecutorError",
    "ManagedHostRunner",
    "ManagedLMStudioExecutor",
    "ManagedLMStudioTransport",
]
