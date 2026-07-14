from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from urllib import request as urllib_request
from urllib.parse import urlunsplit

from .lifecycle_policy import (
    LifecycleDecision,
    LoadConfig,
    LoadedInstanceRef,
    ObservedModelState,
    ensure_loaded_decision,
    ensure_unloaded_decision,
)
from .metrics import PhaseConfidence, PhaseDerivationMethod, PhaseMarker
from .model_probe import (
    _CONTEXT_KEY_ALIASES,
    _LOCALHOST_NAMES,
    _PARALLEL_KEY_ALIASES,
    _attach_candidate_fields,
    _categorize_transport_error,
    _collect_int_candidates,
    _normalize_base_url,
    _safe_float,
    _safe_int,
    _safe_model_id,
    _sha256_text,
)

logger = logging.getLogger(__name__)

type ModelLifecycleTransport = Callable[[urllib_request.Request, float], bytes]
type SleepFunc = Callable[[float], None]
type ManagedLifecycleOperation = Callable[[Mapping[str, object]], Mapping[str, object]]
type PhaseMarkerCallback = Callable[
    [PhaseMarker, PhaseDerivationMethod, PhaseConfidence],
    None,
]

MODEL_LIFECYCLE_LIST_ENDPOINT_PATH = "/api/v1/models"
MODEL_LIFECYCLE_LOAD_ENDPOINT_PATH = "/api/v1/models/load"
MODEL_LIFECYCLE_UNLOAD_ENDPOINT_PATH = "/api/v1/models/unload"
MODEL_LIFECYCLE_LIST_ENDPOINT_KIND = "native_list"
MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND = "native_load"
MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND = "native_unload"
MODEL_LIFECYCLE_RESULT_FILE_NAMES = (
    "environment.json",
    "lifecycle_summary.json",
    "lifecycle_events.jsonl",
    "report.md",
)
MODEL_LIFECYCLE_SCENARIO_CHOICES = (
    "controlled_load_echo",
    "unload_happy_path",
    "external_unload_reconcile",
    "duplicate_load_guard",
    "duplicate_load_behavior",
    "policy_backed_smoke",
    "policy_two_model_swap",
    "two_model_swap_plan",
    "unload_already_gone",
    "load_timeout_reconcile",
)

_SAFE_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SAFE_STATUS_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


@dataclass(frozen=True, slots=True)
class ModelLifecycleResult:
    summary: dict[str, object]
    event_records: tuple[dict[str, object], ...]


def _default_transport(request: urllib_request.Request, timeout_s: float) -> bytes:
    with urllib_request.urlopen(request, timeout=timeout_s) as response:
        return response.read()


def _require_safe_model_id(model_id: object) -> str:
    safe_model_id = _safe_model_id(model_id)
    if safe_model_id is None:
        raise ValueError("model_id must use a safe model identifier")
    return safe_model_id


def validate_model_lifecycle_model_id(model_id: object) -> str:
    return _require_safe_model_id(model_id)


def validate_model_lifecycle_api_token_env(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("api_token_env must be a safe environment variable name")
    text = value.strip()
    if _SAFE_ENV_VAR_RE.fullmatch(text) is None:
        raise ValueError("api_token_env must be a safe environment variable name")
    return text


def _require_positive_int(value: object, *, field_name: str) -> int:
    int_value = _safe_int(value)
    if int_value is None or int_value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return int_value


def _require_positive_float(value: object, *, field_name: str) -> float:
    float_value = _safe_float(value)
    if float_value is None or float_value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return float_value


def _require_supported_scenario(scenario: object) -> str:
    if not isinstance(scenario, str) or scenario not in MODEL_LIFECYCLE_SCENARIO_CHOICES:
        raise ValueError("scenario must be one of the supported lifecycle scenarios")
    return scenario


def is_local_model_lifecycle_base_url(base_url: str) -> bool:
    return _normalize_base_url(base_url).hostname.lower() in _LOCALHOST_NAMES


def build_model_lifecycle_list_url(base_url: str) -> str:
    parsed = _normalize_base_url(base_url)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, MODEL_LIFECYCLE_LIST_ENDPOINT_PATH, "", "")
    )


def build_model_lifecycle_load_url(base_url: str) -> str:
    parsed = _normalize_base_url(base_url)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, MODEL_LIFECYCLE_LOAD_ENDPOINT_PATH, "", "")
    )


def build_model_lifecycle_unload_url(base_url: str) -> str:
    parsed = _normalize_base_url(base_url)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, MODEL_LIFECYCLE_UNLOAD_ENDPOINT_PATH, "", "")
    )


def _endpoint_kinds_planned(scenario: str) -> list[str]:
    if scenario == "controlled_load_echo":
        return [MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND, MODEL_LIFECYCLE_LIST_ENDPOINT_KIND]
    if scenario == "unload_happy_path":
        return [
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
        ]
    if scenario == "external_unload_reconcile":
        return [MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND, MODEL_LIFECYCLE_LIST_ENDPOINT_KIND]
    if scenario == "duplicate_load_guard":
        return [MODEL_LIFECYCLE_LIST_ENDPOINT_KIND]
    if scenario == "duplicate_load_behavior":
        return [
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
        ]
    if scenario == "policy_backed_smoke":
        return [
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
        ]
    if scenario == "policy_two_model_swap":
        return [
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
        ]
    if scenario == "two_model_swap_plan":
        return [
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND,
            MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
        ]
    if scenario == "unload_already_gone":
        return [MODEL_LIFECYCLE_LIST_ENDPOINT_KIND]
    return [MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND, MODEL_LIFECYCLE_LIST_ENDPOINT_KIND]


def _base_summary(
    *,
    scenario: str,
    model_id: str,
    secondary_model_id: str | None,
    context_length: int,
    parallel: int,
    allow_remote: bool,
    is_localhost: bool,
    timeout_s: float,
    max_polls: int,
    poll_interval_s: float,
    execute_lifecycle: bool,
    api_token_present: bool,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "probe_kind": "model_lifecycle",
        "scenario": scenario,
        "model_id": model_id,
        "requested_context_length": context_length,
        "requested_parallel": parallel,
        "allow_remote": allow_remote,
        "is_localhost": is_localhost,
        "timeout_s": timeout_s,
        "max_polls": max_polls,
        "poll_interval_s": poll_interval_s,
        "execute_lifecycle": execute_lifecycle,
        "endpoint_kinds_planned": _endpoint_kinds_planned(scenario),
        "endpoint_kinds_used": [],
        "api_token_present": api_token_present,
        "list_called": False,
        "load_called": False,
        "load_call_count": 0,
        "unload_called": False,
        "unload_call_count": 0,
        "second_load_called": False,
        "cleanup_called": False,
    }
    if secondary_model_id is not None:
        summary["secondary_model_id"] = secondary_model_id
    if scenario in {"two_model_swap_plan", "policy_two_model_swap"}:
        summary["swap_policy"] = "single_model_safe_wvm_owned_only"
    return summary


def _safe_status(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _SAFE_STATUS_RE.fullmatch(text) is None:
        return None
    return text


def _request_headers(*, api_token: str | None, json_body: bool) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    return headers


def _append_endpoint_kind(summary: dict[str, object], endpoint_kind: str) -> None:
    endpoint_kinds_used = summary.setdefault("endpoint_kinds_used", [])
    if isinstance(endpoint_kinds_used, list):
        endpoint_kinds_used.append(endpoint_kind)


def _append_event(event_records: list[dict[str, object]], event: dict[str, object]) -> None:
    event_records.append(event)
    log_method = logger.warning if event.get("status") != "ok" else logger.info
    log_method(
        "model lifecycle request result scenario=%s event_kind=%s endpoint_kind=%s phase=%s status=%s observed_loaded_count=%s instance_id_hash=%s error_category=%s http_status=%s",
        event.get("scenario"),
        event.get("event_kind"),
        event.get("endpoint_kind"),
        event.get("phase"),
        event.get("status"),
        event.get("observed_loaded_count"),
        event.get("instance_id_hash"),
        event.get("error_category"),
        event.get("http_status"),
    )


def _log_plan(summary: Mapping[str, object]) -> None:
    logger.info(
        "model lifecycle plan built scenario=%s model_id=%s execute_lifecycle=%s allow_remote=%s endpoint_kinds_planned=%s",
        summary.get("scenario"),
        summary.get("model_id"),
        summary.get("execute_lifecycle"),
        summary.get("allow_remote"),
        summary.get("endpoint_kinds_planned"),
    )


def _log_duplicate_detection(*, model_id: str, observed_loaded_count: int, status: str) -> None:
    logger.info(
        "model lifecycle duplicate detection model_id=%s observed_loaded_count=%s status=%s",
        model_id,
        observed_loaded_count,
        status,
    )


def _log_reconcile_progress(
    *,
    scenario: str,
    model_id: str,
    observed_loaded_count: int,
    poll_index: int | None,
    status: str,
) -> None:
    logger.info(
        "model lifecycle reconcile scenario=%s model_id=%s observed_loaded_count=%s poll_index=%s status=%s",
        scenario,
        model_id,
        observed_loaded_count,
        poll_index,
        status,
    )


def _emit_manual_action_required(*, model_id: str) -> None:
    message = (
        "MANUAL_ACTION_REQUIRED unload "
        f"{model_id} manually in LM Studio and wait for loaded_instances=0 reconciliation."
    )
    print(message)
    logger.info(
        "model lifecycle manual action requested scenario=%s model_id=%s",
        "external_unload_reconcile",
        model_id,
    )


def _record_elapsed_ms(summary: dict[str, object], *, started_at: float) -> None:
    summary["elapsed_ms"] = round((time.monotonic() - started_at) * 1000.0, 3)


def _ordered_unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _increment_summary_count(summary: dict[str, object], field_name: str) -> None:
    summary[field_name] = (_safe_int(summary.get(field_name)) or 0) + 1


def _owned_instance_hashes(raw_instance_ids: Sequence[str]) -> list[str]:
    return [_sha256_text(instance_id) for instance_id in _ordered_unique(raw_instance_ids)]


def _capture_terminal_fields(summary: Mapping[str, object]) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    for field_name in ("status", "error_category", "http_status"):
        if field_name in summary:
            snapshot[field_name] = summary[field_name]
    return snapshot


def _restore_terminal_fields(summary: dict[str, object], snapshot: Mapping[str, object]) -> None:
    for field_name in ("status", "error_category", "http_status"):
        if field_name in snapshot:
            summary[field_name] = snapshot[field_name]
        else:
            summary.pop(field_name, None)


def _config_mismatch_detected(summary: Mapping[str, object]) -> bool:
    return (
        summary.get("context_length_verified") is False or summary.get("parallel_verified") is False
    )


def _log_terminal_state(summary: Mapping[str, object], *, warning: bool) -> None:
    log_method = logger.warning if warning else logger.info
    log_method(
        "model lifecycle terminal state scenario=%s model_id=%s status=%s observed_loaded_count=%s load_verified=%s error_category=%s",
        summary.get("scenario"),
        summary.get("model_id"),
        summary.get("status"),
        summary.get("observed_loaded_count"),
        summary.get("load_verified"),
        summary.get("error_category"),
    )


def _extract_model_list(payload: object) -> list[Mapping[str, object]] | None:
    raw_models: object | None = None
    if isinstance(payload, Mapping):
        raw_models = payload.get("models")
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        raw_models = payload
    if not isinstance(raw_models, Sequence) or isinstance(raw_models, (str, bytes, bytearray)):
        return None
    models: list[Mapping[str, object]] = []
    for item in raw_models:
        if not isinstance(item, Mapping):
            continue
        models.append(item)
    return models


def _matching_model_ids(model_payload: Mapping[str, object]) -> set[str]:
    ids: set[str] = set()
    for key in ("key", "id", "model_id", "model", "identifier", "name", "compat_model_id"):
        safe_model_id = _safe_model_id(model_payload.get(key))
        if safe_model_id is not None:
            ids.add(safe_model_id)
    return ids


def _extract_loaded_instances(model_payload: Mapping[str, object]) -> list[object]:
    for raw_key, raw_value in model_payload.items():
        normalized_key = str(raw_key).strip().lower().replace("-", "_")
        normalized_key = normalized_key.replace(" ", "_")
        if normalized_key != "loaded_instances":
            continue
        if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes, bytearray)):
            return list(raw_value)
    return []


def _extract_raw_instance_id(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, Mapping):
        for key in ("instance_id", "id", "load_id"):
            raw_id = value.get(key)
            if isinstance(raw_id, str) and raw_id.strip():
                return raw_id.strip()
    return None


def _loaded_state_for_model(payload: object, *, model_id: str) -> dict[str, object]:
    models = _extract_model_list(payload)
    if models is None:
        raise ValueError("shape")
    instance_ids: list[str] = []
    model_found = False
    for model_payload in models:
        if model_id not in _matching_model_ids(model_payload):
            continue
        model_found = True
        for instance in _extract_loaded_instances(model_payload):
            raw_instance_id = _extract_raw_instance_id(instance)
            if raw_instance_id is not None:
                instance_ids.append(raw_instance_id)
    return {
        "model_found": model_found,
        "instance_ids": tuple(instance_ids),
        "instance_id_hashes": tuple(_sha256_text(instance_id) for instance_id in instance_ids),
        "observed_loaded_count": len(instance_ids),
        "global_loaded_count": sum(len(_extract_loaded_instances(model)) for model in models),
    }


def _extract_positive_candidates(payload: object, *, aliases: frozenset[str]) -> list[int]:
    candidates: set[int] = set()
    _collect_int_candidates(payload, aliases, candidates)
    return sorted(value for value in candidates if value > 0)


def _build_verification(*, requested_value: int, candidates: Sequence[int]) -> bool | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0] == requested_value
    if requested_value not in candidates:
        return False
    return None


def _prepare_load_summary(
    *,
    summary: dict[str, object],
    payload: Mapping[str, object],
    requested_context_length: int,
    requested_parallel: int,
) -> str | None:
    raw_instance_id = _extract_raw_instance_id(payload)
    if raw_instance_id is None:
        return None
    summary["instance_id_hash"] = _sha256_text(raw_instance_id)
    echo_status = _safe_status(payload.get("status"))
    if echo_status is not None:
        summary["echo_status"] = echo_status
    context_candidates = _extract_positive_candidates(payload, aliases=_CONTEXT_KEY_ALIASES)
    parallel_candidates = _extract_positive_candidates(payload, aliases=_PARALLEL_KEY_ALIASES)
    _attach_candidate_fields(
        summary,
        field_name="applied_context_length",
        values=set(context_candidates),
    )
    _attach_candidate_fields(
        summary,
        field_name="applied_parallel",
        values=set(parallel_candidates),
    )
    summary["context_length_verified"] = _build_verification(
        requested_value=requested_context_length,
        candidates=context_candidates,
    )
    summary["parallel_verified"] = _build_verification(
        requested_value=requested_parallel,
        candidates=parallel_candidates,
    )
    return raw_instance_id


def _handle_transport_failure(
    *,
    summary: dict[str, object],
    event_records: list[dict[str, object]],
    scenario: str,
    endpoint_kind: str,
    phase: str,
    error: Exception,
) -> None:
    status, error_category, http_status = _categorize_transport_error(error)
    summary["status"] = status
    summary["error_category"] = error_category
    if http_status is not None:
        summary["http_status"] = http_status
    _append_event(
        event_records,
        {
            "scenario": scenario,
            "event_kind": "request_error",
            "endpoint_kind": endpoint_kind,
            "phase": phase,
            "status": status,
            "error_category": error_category,
            "http_status": http_status,
        },
    )


def _parse_json_response(
    *,
    summary: dict[str, object],
    event_records: list[dict[str, object]],
    scenario: str,
    endpoint_kind: str,
    phase: str,
    response_bytes: bytes,
) -> object | None:
    response_text = response_bytes.decode("utf-8", errors="replace")
    event: dict[str, object] = {
        "scenario": scenario,
        "event_kind": "request_complete",
        "endpoint_kind": endpoint_kind,
        "phase": phase,
        "status": "ok",
        "response_hash": _sha256_text(response_text),
        "response_chars": len(response_text),
    }
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        summary["status"] = "decode_error"
        summary["error_category"] = "json"
        event["status"] = "decode_error"
        event["error_category"] = "json"
        _append_event(event_records, event)
        return None
    _append_event(event_records, event)
    return payload


def _get_models_payload(
    *,
    base_url: str,
    timeout_s: float,
    transport: ModelLifecycleTransport,
    summary: dict[str, object],
    event_records: list[dict[str, object]],
    scenario: str,
    phase: str,
    api_token: str | None,
) -> object | None:
    summary["list_called"] = True
    _append_endpoint_kind(summary, MODEL_LIFECYCLE_LIST_ENDPOINT_KIND)
    request = urllib_request.Request(
        build_model_lifecycle_list_url(base_url),
        method="GET",
        headers=_request_headers(api_token=api_token, json_body=False),
    )
    try:
        response_bytes = transport(request, timeout_s)
    except Exception as error:
        _handle_transport_failure(
            summary=summary,
            event_records=event_records,
            scenario=scenario,
            endpoint_kind=MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
            phase=phase,
            error=error,
        )
        return None

    return _parse_json_response(
        summary=summary,
        event_records=event_records,
        scenario=scenario,
        endpoint_kind=MODEL_LIFECYCLE_LIST_ENDPOINT_KIND,
        phase=phase,
        response_bytes=response_bytes,
    )


def _get_models_state(
    *,
    base_url: str,
    timeout_s: float,
    transport: ModelLifecycleTransport,
    summary: dict[str, object],
    event_records: list[dict[str, object]],
    scenario: str,
    model_id: str,
    phase: str,
    api_token: str | None,
) -> dict[str, object] | None:
    payload = _get_models_payload(
        base_url=base_url,
        timeout_s=timeout_s,
        transport=transport,
        summary=summary,
        event_records=event_records,
        scenario=scenario,
        phase=phase,
        api_token=api_token,
    )
    if payload is None:
        return None
    try:
        state = _loaded_state_for_model(payload, model_id=model_id)
    except ValueError:
        summary["status"] = "invalid_shape"
        summary["error_category"] = "shape"
        if event_records:
            event_records[-1]["status"] = "invalid_shape"
            event_records[-1]["error_category"] = "shape"
        return None
    if event_records:
        event_records[-1]["observed_loaded_count"] = state["observed_loaded_count"]
        hashes = list(state["instance_id_hashes"])
        if hashes:
            event_records[-1]["instance_id_hashes"] = hashes
            event_records[-1]["instance_id_hash"] = hashes[0]
    summary["observed_loaded_count"] = state["observed_loaded_count"]
    summary["observed_global_loaded_count"] = state["global_loaded_count"]
    return state


def _get_named_models_state(
    *,
    base_url: str,
    timeout_s: float,
    transport: ModelLifecycleTransport,
    summary: dict[str, object],
    event_records: list[dict[str, object]],
    scenario: str,
    model_ids: Mapping[str, str],
    phase: str,
    api_token: str | None,
) -> dict[str, dict[str, object]] | None:
    payload = _get_models_payload(
        base_url=base_url,
        timeout_s=timeout_s,
        transport=transport,
        summary=summary,
        event_records=event_records,
        scenario=scenario,
        phase=phase,
        api_token=api_token,
    )
    if payload is None:
        return None

    states: dict[str, dict[str, object]] = {}
    try:
        for label, model_id in model_ids.items():
            states[label] = _loaded_state_for_model(payload, model_id=model_id)
    except ValueError:
        summary["status"] = "invalid_shape"
        summary["error_category"] = "shape"
        if event_records:
            event_records[-1]["status"] = "invalid_shape"
            event_records[-1]["error_category"] = "shape"
        return None

    if event_records:
        event_records[-1]["observed_loaded_counts"] = {
            label: state["observed_loaded_count"] for label, state in states.items()
        }
    return states


def _post_load(
    *,
    base_url: str,
    timeout_s: float,
    transport: ModelLifecycleTransport,
    summary: dict[str, object],
    event_records: list[dict[str, object]],
    scenario: str,
    model_id: str,
    context_length: int,
    parallel: int,
    api_token: str | None,
    phase: str = "load",
) -> str | None:
    summary["load_called"] = True
    summary["load_call_count"] = _safe_int(summary.get("load_call_count")) or 0
    summary["load_call_count"] = int(summary["load_call_count"]) + 1
    _append_endpoint_kind(summary, MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND)
    request_body = json.dumps(
        {
            "model": model_id,
            "context_length": context_length,
            "parallel": parallel,
            "echo_load_config": True,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib_request.Request(
        build_model_lifecycle_load_url(base_url),
        data=request_body,
        method="POST",
        headers=_request_headers(api_token=api_token, json_body=True),
    )
    try:
        response_bytes = transport(request, timeout_s)
    except Exception as error:
        _handle_transport_failure(
            summary=summary,
            event_records=event_records,
            scenario=scenario,
            endpoint_kind=MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND,
            phase=phase,
            error=error,
        )
        return None

    payload = _parse_json_response(
        summary=summary,
        event_records=event_records,
        scenario=scenario,
        endpoint_kind=MODEL_LIFECYCLE_LOAD_ENDPOINT_KIND,
        phase=phase,
        response_bytes=response_bytes,
    )
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        summary["status"] = "invalid_shape"
        summary["error_category"] = "shape"
        if event_records:
            event_records[-1]["status"] = "invalid_shape"
            event_records[-1]["error_category"] = "shape"
        return None

    raw_instance_id = _prepare_load_summary(
        summary=summary,
        payload=payload,
        requested_context_length=context_length,
        requested_parallel=parallel,
    )
    if raw_instance_id is None:
        summary["status"] = "invalid_shape"
        summary["error_category"] = "shape"
        if event_records:
            event_records[-1]["status"] = "invalid_shape"
            event_records[-1]["error_category"] = "shape"
        return None
    if event_records:
        event_records[-1]["instance_id_hash"] = summary["instance_id_hash"]
    return raw_instance_id


def _post_unload(
    *,
    base_url: str,
    timeout_s: float,
    transport: ModelLifecycleTransport,
    summary: dict[str, object],
    event_records: list[dict[str, object]],
    scenario: str,
    raw_instance_id: str,
    instance_id_hash: str,
    phase: str,
    api_token: str | None,
) -> bool:
    summary["unload_called"] = True
    summary["unload_call_count"] = _safe_int(summary.get("unload_call_count")) or 0
    summary["unload_call_count"] = int(summary["unload_call_count"]) + 1
    _append_endpoint_kind(summary, MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND)
    request_body = json.dumps(
        {"instance_id": raw_instance_id},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib_request.Request(
        build_model_lifecycle_unload_url(base_url),
        data=request_body,
        method="POST",
        headers=_request_headers(api_token=api_token, json_body=True),
    )
    try:
        response_bytes = transport(request, timeout_s)
    except Exception as error:
        _handle_transport_failure(
            summary=summary,
            event_records=event_records,
            scenario=scenario,
            endpoint_kind=MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND,
            phase=phase,
            error=error,
        )
        return False

    response_text = response_bytes.decode("utf-8", errors="replace")
    event: dict[str, object] = {
        "scenario": scenario,
        "event_kind": "request_complete",
        "endpoint_kind": MODEL_LIFECYCLE_UNLOAD_ENDPOINT_KIND,
        "phase": phase,
        "status": "ok",
        "instance_id_hash": instance_id_hash,
    }
    if response_text:
        event["response_hash"] = _sha256_text(response_text)
        event["response_chars"] = len(response_text)
    _append_event(event_records, event)
    return True


def _cleanup_exact_instance_ids(
    *,
    base_url: str,
    timeout_s: float,
    transport: ModelLifecycleTransport,
    summary: dict[str, object],
    event_records: list[dict[str, object]],
    scenario: str,
    model_id: str,
    raw_instance_ids: Sequence[str],
    api_token: str | None,
    persist_hash_field: str | None = None,
    verification_phase: str = "cleanup_verify",
) -> None:
    unique_raw_instance_ids = _ordered_unique(raw_instance_ids)
    cleanup_hashes = _owned_instance_hashes(unique_raw_instance_ids)
    if persist_hash_field is not None and cleanup_hashes:
        summary[persist_hash_field] = cleanup_hashes
    if not unique_raw_instance_ids:
        summary["cleanup_called"] = False
        return

    summary["cleanup_called"] = True
    primary_terminal_snapshot = _capture_terminal_fields(summary)
    cleanup_failures = 0
    for cleanup_index, raw_instance_id in enumerate(unique_raw_instance_ids, start=1):
        instance_id_hash = _sha256_text(raw_instance_id)
        unload_ok = _post_unload(
            base_url=base_url,
            timeout_s=timeout_s,
            transport=transport,
            summary=summary,
            event_records=event_records,
            scenario=scenario,
            raw_instance_id=raw_instance_id,
            instance_id_hash=instance_id_hash,
            phase=f"cleanup_unload_{cleanup_index}",
            api_token=api_token,
        )
        if not unload_ok:
            cleanup_failures += 1
            _restore_terminal_fields(summary, primary_terminal_snapshot)

    cleanup_state = _get_models_state(
        base_url=base_url,
        timeout_s=timeout_s,
        transport=transport,
        summary=summary,
        event_records=event_records,
        scenario=scenario,
        model_id=model_id,
        phase=verification_phase,
        api_token=api_token,
    )
    if cleanup_state is None:
        _restore_terminal_fields(summary, primary_terminal_snapshot)
        if cleanup_failures:
            summary["cleanup_post_failures"] = cleanup_failures
        summary["cleanup_verification_observed"] = False
        return

    remaining_hashes = set(cleanup_state["instance_id_hashes"])
    summary["cleanup_verification_observed"] = True
    summary["cleanup_final_loaded_count"] = cleanup_state["observed_loaded_count"]
    summary["cleanup_final_global_loaded_count"] = cleanup_state["global_loaded_count"]
    summary["cleanup_verified_count"] = sum(
        1 for instance_id_hash in cleanup_hashes if instance_id_hash not in remaining_hashes
    )
    summary["cleanup_remaining_count"] = sum(
        1 for instance_id_hash in cleanup_hashes if instance_id_hash in remaining_hashes
    )
    if cleanup_failures:
        summary["cleanup_post_failures"] = cleanup_failures
    _restore_terminal_fields(summary, primary_terminal_snapshot)


def _emit_phase_marker(
    callback: PhaseMarkerCallback | None,
    marker: PhaseMarker,
    derivation_method: PhaseDerivationMethod = PhaseDerivationMethod.DIRECT_EVENT,
    confidence: PhaseConfidence = PhaseConfidence.HIGH,
) -> None:
    if callback is None:
        return
    try:
        callback(marker, derivation_method, confidence)
    except Exception:
        logger.warning("phase telemetry callback failed marker=%s", marker.value)


def run_exact_model_operation(
    base_url: str,
    *,
    model_id: str,
    context_length: int,
    parallel: int,
    operation: ManagedLifecycleOperation,
    timeout_s: float = 120.0,
    transport: ModelLifecycleTransport | None = None,
    api_token: str | None = None,
    phase_callback: PhaseMarkerCallback | None = None,
) -> dict[str, object]:
    """Run a callback between exact native load and exact cleanup.

    Raw instance identifiers stay in-memory only. Returned data contains only
    privacy-safe hashes, counts, and verification status.
    """

    safe_model_id = _require_safe_model_id(model_id)
    requested_context_length = _require_positive_int(
        context_length,
        field_name="context_length",
    )
    requested_parallel = _require_positive_int(
        parallel,
        field_name="parallel",
    )
    request_transport = transport or _default_transport

    summary: dict[str, object] = {
        "model_id": safe_model_id,
        "requested_context_length": requested_context_length,
        "requested_parallel": requested_parallel,
        "load_verified": False,
        "raw_prompt_response_stored": False,
    }
    event_records: list[dict[str, object]] = []
    raw_owned_instance_ids: list[str] = []
    operation_summary: Mapping[str, object] | None = None
    cleanup_error: RuntimeError | None = None
    pending_exception: tuple[type[BaseException], BaseException, TracebackType | None] | None = None

    try:
        _emit_phase_marker(phase_callback, PhaseMarker.LOAD_STARTED)
        raw_instance_id = _post_load(
            base_url=base_url,
            timeout_s=timeout_s,
            transport=request_transport,
            summary=summary,
            event_records=event_records,
            scenario="managed_live_operation",
            model_id=safe_model_id,
            context_length=requested_context_length,
            parallel=requested_parallel,
            api_token=api_token,
            phase="managed_live_load",
        )
        if raw_instance_id is None:
            raise RuntimeError("native load failed")
        raw_owned_instance_ids.append(raw_instance_id)

        load_state = _get_models_state(
            base_url=base_url,
            timeout_s=timeout_s,
            transport=request_transport,
            summary=summary,
            event_records=event_records,
            scenario="managed_live_operation",
            model_id=safe_model_id,
            phase="managed_live_load_verify",
            api_token=api_token,
        )
        if load_state is None:
            raise RuntimeError("native load verification failed")

        owned_instance_hash = summary.get("instance_id_hash")
        materialized_hash_match = isinstance(
            owned_instance_hash, str
        ) and owned_instance_hash in set(load_state.get("instance_id_hashes", ()))
        summary["materialized_loaded_count"] = load_state.get("observed_loaded_count")
        summary["load_verified"] = bool(
            materialized_hash_match
            and summary.get("context_length_verified") is not False
            and summary.get("parallel_verified") is not False
        )
        if summary["load_verified"] is not True:
            raise RuntimeError("native load verification failed")
        _emit_phase_marker(phase_callback, PhaseMarker.LOADED_IDLE)

        applied_context_length = _safe_int(summary.get("applied_context_length"))
        applied_parallel = _safe_int(summary.get("applied_parallel"))
        safe_operation_state = {
            "model_id": safe_model_id,
            "requested_context_length": requested_context_length,
            "requested_parallel": requested_parallel,
            "applied_context_length": applied_context_length,
            "applied_parallel": applied_parallel,
            "context_length_verified": summary.get("context_length_verified"),
            "parallel_verified": summary.get("parallel_verified"),
            "instance_id_hash": summary.get("instance_id_hash"),
            "load_verified": summary["load_verified"],
            "verified_context_length": applied_context_length or requested_context_length,
        }
        _emit_phase_marker(
            phase_callback,
            PhaseMarker.REQUEST_DISPATCHED,
            PhaseDerivationMethod.ATTRIBUTABLE_REQUEST_INTERVAL,
            PhaseConfidence.MEDIUM,
        )
        operation_summary = operation(safe_operation_state)
        _emit_phase_marker(phase_callback, PhaseMarker.BATCH_COMPLETED)
        _emit_phase_marker(
            phase_callback,
            PhaseMarker.POST_BATCH_IDLE,
            PhaseDerivationMethod.UNAVAILABLE,
            PhaseConfidence.UNAVAILABLE,
        )
    except Exception:
        pending_exception = sys.exc_info()
    finally:
        if raw_owned_instance_ids:
            _emit_phase_marker(phase_callback, PhaseMarker.UNLOAD_STARTED)
            _cleanup_exact_instance_ids(
                base_url=base_url,
                timeout_s=timeout_s,
                transport=request_transport,
                summary=summary,
                event_records=event_records,
                scenario="managed_live_operation",
                model_id=safe_model_id,
                raw_instance_ids=raw_owned_instance_ids,
                api_token=api_token,
                persist_hash_field="cleanup_instance_id_hashes",
                verification_phase="managed_live_cleanup_verify",
            )
            cleanup_post_failures = _safe_int(summary.get("cleanup_post_failures")) or 0
            cleanup_verified_count = _safe_int(summary.get("cleanup_verified_count")) or 0
            final_loaded_instances = _safe_int(summary.get("cleanup_final_loaded_count"))
            final_global_loaded_instances = _safe_int(
                summary.get("cleanup_final_global_loaded_count")
            )
            summary["cleanup_verified_count"] = cleanup_verified_count
            summary["final_loaded_instances"] = final_loaded_instances
            summary["final_global_loaded_instances"] = final_global_loaded_instances
            if (
                summary.get("cleanup_verification_observed") is True
                and cleanup_verified_count == len(_ordered_unique(raw_owned_instance_ids))
                and final_loaded_instances == 0
                and cleanup_post_failures == 0
            ):
                summary["cleanup_status"] = "cleanup_verified"
                if final_global_loaded_instances == 0:
                    _emit_phase_marker(
                        phase_callback,
                        PhaseMarker.AFTER_UNLOAD_GLOBAL_ZERO,
                    )
            elif summary.get("cleanup_verification_observed") is True:
                summary["cleanup_status"] = "cleanup_incomplete"
            else:
                summary["cleanup_status"] = "cleanup_unverified"

            if summary.get("cleanup_status") != "cleanup_verified":
                cleanup_error = RuntimeError("native cleanup not verified")
        else:
            summary["cleanup_called"] = False
            summary["cleanup_verified_count"] = 0
            summary["final_loaded_instances"] = None
            summary["final_global_loaded_instances"] = None
            summary["cleanup_status"] = "cleanup_not_started"

        if pending_exception is not None:
            exc_type, exc, traceback = pending_exception
            if exc is not None:
                raise exc.with_traceback(traceback)
            raise exc_type
        if cleanup_error is not None:
            raise cleanup_error

    return {
        **(dict(operation_summary) if operation_summary is not None else {}),
        **summary,
    }


def _dry_run_result(summary: dict[str, object]) -> ModelLifecycleResult:
    summary["status"] = "planned"
    summary["error_category"] = None
    logger.info(
        "model lifecycle dry-run planned scenario=%s model_id=%s execute_lifecycle=%s status=%s",
        summary.get("scenario"),
        summary.get("model_id"),
        summary.get("execute_lifecycle"),
        summary.get("status"),
    )
    _log_terminal_state(summary, warning=False)
    return ModelLifecycleResult(summary=summary, event_records=())


def _cleanup_duplicate_load_behavior_instances(
    *,
    base_url: str,
    timeout_s: float,
    transport: ModelLifecycleTransport,
    summary: dict[str, object],
    event_records: list[dict[str, object]],
    scenario: str,
    model_id: str,
    raw_instance_ids: Sequence[str],
    api_token: str | None,
) -> None:
    _cleanup_exact_instance_ids(
        base_url=base_url,
        timeout_s=timeout_s,
        transport=transport,
        summary=summary,
        event_records=event_records,
        scenario=scenario,
        model_id=model_id,
        raw_instance_ids=raw_instance_ids,
        api_token=api_token,
        persist_hash_field="owned_instance_hashes",
    )


def _resolved_policy_load_config(
    *,
    summary: Mapping[str, object],
    model_id: str,
    requested_context_length: int,
    requested_parallel: int,
) -> LoadConfig:
    applied_context_length = (
        _safe_int(summary.get("applied_context_length")) or requested_context_length
    )
    applied_parallel = _safe_int(summary.get("applied_parallel")) or requested_parallel
    return LoadConfig(
        model_key=model_id,
        context_length=applied_context_length,
        parallel=applied_parallel,
    )


def _build_policy_observed_state(
    *,
    model_id: str,
    state: Mapping[str, object],
    owned_configs_by_hash: Mapping[str, LoadConfig],
) -> ObservedModelState:
    loaded_instances: list[LoadedInstanceRef] = []
    raw_hashes = state.get("instance_id_hashes")
    if isinstance(raw_hashes, Sequence) and not isinstance(raw_hashes, (str, bytes, bytearray)):
        for raw_hash in raw_hashes:
            if not isinstance(raw_hash, str):
                continue
            known_config = owned_configs_by_hash.get(raw_hash)
            loaded_instances.append(
                LoadedInstanceRef(
                    instance_hash=raw_hash,
                    model_key=model_id,
                    context_length=(known_config.context_length if known_config else None),
                    parallel=(known_config.parallel if known_config else None),
                    owned_by_policy=known_config is not None,
                )
            )
    return ObservedModelState.from_loaded_instances(model_id, loaded_instances)


def _record_policy_decision(
    *,
    summary: dict[str, object],
    event_records: list[dict[str, object]],
    scenario: str,
    phase: str,
    decision: LifecycleDecision,
    summary_label: str | None = None,
) -> None:
    policy_step_decisions = summary.setdefault("policy_step_decisions", [])
    if isinstance(policy_step_decisions, list):
        policy_step_decisions.append(summary_label or decision.action)

    event: dict[str, object] = {
        "scenario": scenario,
        "event_kind": "policy_decision",
        "endpoint_kind": "policy",
        "phase": phase,
        "status": "ok",
        "decision_action": decision.action,
        "decision_status": decision.status,
        "decision_reason": decision.reason,
        "observed_loaded_count": decision.observed_instance_count,
    }
    if decision.observed_instance_hashes:
        event["instance_id_hashes"] = list(decision.observed_instance_hashes)
    if decision.target_hashes:
        event["target_hashes"] = list(decision.target_hashes)
    event_records.append(event)
    logger.info(
        "model lifecycle policy decision scenario=%s phase=%s decision=%s observed_loaded_count=%s target_hash_count=%s",
        scenario,
        phase,
        decision.action,
        decision.observed_instance_count,
        len(decision.target_hashes),
    )


def _set_policy_decision_mismatch(
    *,
    summary: dict[str, object],
    phase: str,
    expected_action: str,
    decision: LifecycleDecision,
    status: str = "policy_smoke_decision_mismatch",
) -> None:
    summary["status"] = status
    summary["error_category"] = "policy"
    summary["policy_phase"] = phase
    summary["policy_expected_action"] = expected_action
    summary["policy_observed_action"] = decision.action
    summary["policy_reason"] = decision.reason


def _raw_instance_ids_for_hashes(
    *,
    target_hashes: Sequence[str],
    owned_raw_instance_ids_by_hash: Mapping[str, str],
) -> list[str]:
    raw_instance_ids: list[str] = []
    for target_hash in target_hashes:
        raw_instance_id = owned_raw_instance_ids_by_hash.get(target_hash)
        if raw_instance_id is None:
            return []
        raw_instance_ids.append(raw_instance_id)
    return raw_instance_ids


def probe_model_lifecycle(
    base_url: str,
    *,
    model_id: str,
    scenario: str,
    secondary_model_id: str | None = None,
    context_length: int = 8192,
    parallel: int = 1,
    allow_remote: bool = False,
    timeout_s: float = 120.0,
    max_polls: int = 30,
    poll_interval_s: float = 1.0,
    api_token_env: str = "LM_API_TOKEN",
    execute_lifecycle: bool = False,
    transport: ModelLifecycleTransport | None = None,
    sleep: SleepFunc | None = None,
) -> ModelLifecycleResult:
    safe_scenario = _require_supported_scenario(scenario)
    safe_model_id = _require_safe_model_id(model_id)
    safe_secondary_model_id = (
        _require_safe_model_id(secondary_model_id) if secondary_model_id is not None else None
    )
    request_timeout_s = _require_positive_float(timeout_s, field_name="timeout_s")
    requested_context_length = _require_positive_int(
        context_length,
        field_name="context_length",
    )
    requested_parallel = _require_positive_int(parallel, field_name="parallel")
    safe_max_polls = _require_positive_int(max_polls, field_name="max_polls")
    safe_poll_interval_s = _require_positive_float(
        poll_interval_s,
        field_name="poll_interval_s",
    )
    safe_api_token_env = validate_model_lifecycle_api_token_env(api_token_env)
    if (
        safe_scenario in {"two_model_swap_plan", "policy_two_model_swap"}
        and safe_secondary_model_id is None
    ):
        raise ValueError(f"secondary_model_id is required for {safe_scenario}")

    parsed = _normalize_base_url(base_url)
    is_localhost = parsed.hostname.lower() in _LOCALHOST_NAMES
    if not allow_remote and not is_localhost:
        raise ValueError("base_url must stay on localhost unless allow_remote is true")

    api_token = os.getenv(safe_api_token_env)
    api_token = api_token.strip() if isinstance(api_token, str) else None
    if not api_token:
        api_token = None
    api_token_present = api_token is not None
    summary = _base_summary(
        scenario=safe_scenario,
        model_id=safe_model_id,
        secondary_model_id=safe_secondary_model_id,
        context_length=requested_context_length,
        parallel=requested_parallel,
        allow_remote=allow_remote,
        is_localhost=is_localhost,
        timeout_s=request_timeout_s,
        max_polls=safe_max_polls,
        poll_interval_s=safe_poll_interval_s,
        execute_lifecycle=execute_lifecycle,
        api_token_present=api_token_present,
    )
    _log_plan(summary)
    if not execute_lifecycle:
        return _dry_run_result(summary)

    effective_transport = transport or _default_transport
    sleeper = sleep or time.sleep
    event_records: list[dict[str, object]] = []

    if safe_scenario == "controlled_load_echo":
        raw_instance_id = _post_load(
            base_url=base_url,
            timeout_s=request_timeout_s,
            transport=effective_transport,
            summary=summary,
            event_records=event_records,
            scenario=safe_scenario,
            model_id=safe_model_id,
            context_length=requested_context_length,
            parallel=requested_parallel,
            api_token=api_token,
        )
        if raw_instance_id is not None:
            state = _get_models_state(
                base_url=base_url,
                timeout_s=request_timeout_s,
                transport=effective_transport,
                summary=summary,
                event_records=event_records,
                scenario=safe_scenario,
                model_id=safe_model_id,
                phase="verify_load",
                api_token=api_token,
            )
            if state is not None:
                summary["load_verified"] = raw_instance_id in state["instance_ids"]
                summary["observed_loaded_count"] = state["observed_loaded_count"]
                summary["status"] = "ok" if summary["load_verified"] else "load_not_verified"
                summary["error_category"] = None if summary["load_verified"] else "reconcile"

    elif safe_scenario == "unload_happy_path":
        state_before = _get_models_state(
            base_url=base_url,
            timeout_s=request_timeout_s,
            transport=effective_transport,
            summary=summary,
            event_records=event_records,
            scenario=safe_scenario,
            model_id=safe_model_id,
            phase="before_unload",
            api_token=api_token,
        )
        if state_before is not None:
            summary["observed_loaded_count_before"] = state_before["observed_loaded_count"]
            if state_before["observed_loaded_count"] == 0:
                summary["status"] = "already_unloaded"
                summary["error_category"] = None
            else:
                raw_instance_id = state_before["instance_ids"][0]
                instance_id_hash = state_before["instance_id_hashes"][0]
                summary["instance_id_hash"] = instance_id_hash
                if _post_unload(
                    base_url=base_url,
                    timeout_s=request_timeout_s,
                    transport=effective_transport,
                    summary=summary,
                    event_records=event_records,
                    scenario=safe_scenario,
                    raw_instance_id=raw_instance_id,
                    instance_id_hash=instance_id_hash,
                    phase="unload",
                    api_token=api_token,
                ):
                    state_after = _get_models_state(
                        base_url=base_url,
                        timeout_s=request_timeout_s,
                        transport=effective_transport,
                        summary=summary,
                        event_records=event_records,
                        scenario=safe_scenario,
                        model_id=safe_model_id,
                        phase="after_unload",
                        api_token=api_token,
                    )
                    if state_after is not None:
                        summary["observed_loaded_count_after"] = state_after[
                            "observed_loaded_count"
                        ]
                        summary["status"] = (
                            "ok" if state_after["observed_loaded_count"] == 0 else "still_loaded"
                        )
                        summary["error_category"] = (
                            None if state_after["observed_loaded_count"] == 0 else "reconcile"
                        )

    elif safe_scenario == "external_unload_reconcile":
        started_at = time.monotonic()
        raw_instance_id = _post_load(
            base_url=base_url,
            timeout_s=request_timeout_s,
            transport=effective_transport,
            summary=summary,
            event_records=event_records,
            scenario=safe_scenario,
            model_id=safe_model_id,
            context_length=requested_context_length,
            parallel=requested_parallel,
            api_token=api_token,
        )
        if raw_instance_id is not None:
            state = _get_models_state(
                base_url=base_url,
                timeout_s=request_timeout_s,
                transport=effective_transport,
                summary=summary,
                event_records=event_records,
                scenario=safe_scenario,
                model_id=safe_model_id,
                phase="observe_external",
                api_token=api_token,
            )
            if state is not None:
                observed_loaded_count = state["observed_loaded_count"]
                load_verified = (
                    observed_loaded_count == 1 and raw_instance_id in state["instance_ids"]
                )
                summary["load_verified"] = load_verified
                summary["observed_loaded_count_initial"] = observed_loaded_count
                summary["observed_loaded_count_final"] = observed_loaded_count
                summary["poll_count"] = 0
                summary["polls_used"] = 0
                if observed_loaded_count == 0:
                    summary["status"] = "already_unloaded"
                    summary["error_category"] = None
                elif not load_verified:
                    summary["status"] = "load_not_verified"
                    summary["error_category"] = "reconcile"
                else:
                    _emit_manual_action_required(model_id=safe_model_id)
                    final_state = state
                    for poll_index in range(1, safe_max_polls + 1):
                        sleeper(safe_poll_interval_s)
                        final_state = _get_models_state(
                            base_url=base_url,
                            timeout_s=request_timeout_s,
                            transport=effective_transport,
                            summary=summary,
                            event_records=event_records,
                            scenario=safe_scenario,
                            model_id=safe_model_id,
                            phase=f"reconcile_poll_{poll_index}",
                            api_token=api_token,
                        )
                        if final_state is None:
                            break
                        summary["poll_count"] = poll_index
                        summary["polls_used"] = poll_index
                        summary["observed_loaded_count_final"] = final_state[
                            "observed_loaded_count"
                        ]
                        _log_reconcile_progress(
                            scenario=safe_scenario,
                            model_id=safe_model_id,
                            observed_loaded_count=final_state["observed_loaded_count"],
                            poll_index=poll_index,
                            status="polling",
                        )
                        if final_state["observed_loaded_count"] == 0:
                            summary["status"] = "externally_unloaded"
                            summary["error_category"] = None
                            break
                    else:
                        summary["status"] = "manual_unload_not_observed"
                        summary["error_category"] = "reconcile"
                        summary["cleanup_not_performed"] = True
                _record_elapsed_ms(summary, started_at=started_at)

    elif safe_scenario == "duplicate_load_guard":
        state = _get_models_state(
            base_url=base_url,
            timeout_s=request_timeout_s,
            transport=effective_transport,
            summary=summary,
            event_records=event_records,
            scenario=safe_scenario,
            model_id=safe_model_id,
            phase="duplicate_guard",
            api_token=api_token,
        )
        if state is not None:
            summary["observed_loaded_count"] = state["observed_loaded_count"]
            if state["instance_id_hashes"]:
                summary["instance_id_hashes"] = list(state["instance_id_hashes"])
            summary["status"] = (
                "duplicate_instances" if state["observed_loaded_count"] > 1 else "ok"
            )
            summary["error_category"] = None
            _log_duplicate_detection(
                model_id=safe_model_id,
                observed_loaded_count=state["observed_loaded_count"],
                status=str(summary["status"]),
            )

    elif safe_scenario == "duplicate_load_behavior":
        owned_raw_instance_ids: list[str] = []
        started_at = time.monotonic()
        baseline_state = _get_models_state(
            base_url=base_url,
            timeout_s=request_timeout_s,
            transport=effective_transport,
            summary=summary,
            event_records=event_records,
            scenario=safe_scenario,
            model_id=safe_model_id,
            phase="baseline",
            api_token=api_token,
        )
        if baseline_state is not None:
            baseline_loaded_count = baseline_state["observed_loaded_count"]
            summary["baseline_loaded_count"] = baseline_loaded_count
            summary["final_loaded_count"] = baseline_loaded_count
            if baseline_loaded_count != 0:
                summary["status"] = "preloaded_not_clean"
                summary["duplicate_outcome"] = "preloaded_not_clean"
                summary["cleanup_not_performed"] = True
                summary["error_category"] = None
            else:
                first_raw_instance_id = _post_load(
                    base_url=base_url,
                    timeout_s=request_timeout_s,
                    transport=effective_transport,
                    summary=summary,
                    event_records=event_records,
                    scenario=safe_scenario,
                    model_id=safe_model_id,
                    context_length=requested_context_length,
                    parallel=requested_parallel,
                    api_token=api_token,
                    phase="first_load",
                )
                if first_raw_instance_id is not None:
                    owned_raw_instance_ids.append(first_raw_instance_id)
                    summary["first_instance_id_hash"] = _sha256_text(first_raw_instance_id)
                    first_state = _get_models_state(
                        base_url=base_url,
                        timeout_s=request_timeout_s,
                        transport=effective_transport,
                        summary=summary,
                        event_records=event_records,
                        scenario=safe_scenario,
                        model_id=safe_model_id,
                        phase="after_first_load",
                        api_token=api_token,
                    )
                    if first_state is not None:
                        first_load_verified = first_raw_instance_id in first_state["instance_ids"]
                        summary["first_load_verified"] = first_load_verified
                        summary["load_verified"] = first_load_verified
                        summary["first_loaded_count"] = first_state["observed_loaded_count"]
                        if _config_mismatch_detected(summary):
                            summary["status"] = "config_mismatch"
                            summary["duplicate_outcome"] = "config_mismatch"
                            summary["final_loaded_count"] = first_state["observed_loaded_count"]
                            summary["error_category"] = "config"
                        elif not first_load_verified:
                            summary["status"] = "load_not_verified"
                            summary["duplicate_outcome"] = "load_not_verified"
                            summary["final_loaded_count"] = first_state["observed_loaded_count"]
                            summary["error_category"] = "reconcile"
                        else:
                            summary["second_load_called"] = True
                            second_raw_instance_id = _post_load(
                                base_url=base_url,
                                timeout_s=request_timeout_s,
                                transport=effective_transport,
                                summary=summary,
                                event_records=event_records,
                                scenario=safe_scenario,
                                model_id=safe_model_id,
                                context_length=requested_context_length,
                                parallel=requested_parallel,
                                api_token=api_token,
                                phase="second_load",
                            )
                            if second_raw_instance_id is not None:
                                owned_raw_instance_ids.append(second_raw_instance_id)
                                summary["second_instance_id_hash"] = _sha256_text(
                                    second_raw_instance_id
                                )
                            else:
                                summary["status"] = "duplicate_rejected"
                            final_state_terminal_snapshot = (
                                _capture_terminal_fields(summary)
                                if summary.get("status") == "duplicate_rejected"
                                else {}
                            )
                            final_state = _get_models_state(
                                base_url=base_url,
                                timeout_s=request_timeout_s,
                                transport=effective_transport,
                                summary=summary,
                                event_records=event_records,
                                scenario=safe_scenario,
                                model_id=safe_model_id,
                                phase="after_second_load",
                                api_token=api_token,
                            )
                            if final_state is None and final_state_terminal_snapshot:
                                _restore_terminal_fields(summary, final_state_terminal_snapshot)
                            if final_state is not None:
                                final_loaded_count = final_state["observed_loaded_count"]
                                distinct_instance_hashes = _ordered_unique(
                                    list(final_state["instance_id_hashes"])
                                )
                                summary["final_loaded_count"] = final_loaded_count
                                summary["distinct_instance_hash_count"] = len(
                                    distinct_instance_hashes
                                )
                                summary["duplicate_instance_count"] = final_loaded_count
                                if second_raw_instance_id is not None and _config_mismatch_detected(
                                    summary
                                ):
                                    summary["status"] = "config_mismatch"
                                    summary["error_category"] = "config"
                                elif summary.get("status") == "duplicate_rejected":
                                    if summary.get("error_category") is None:
                                        summary["error_category"] = "http_error"
                                elif final_loaded_count == 1:
                                    summary["status"] = "duplicate_reused_or_idempotent"
                                    summary["error_category"] = None
                                elif final_loaded_count >= 2 and len(distinct_instance_hashes) >= 2:
                                    summary["status"] = "duplicate_instances_confirmed"
                                    summary["error_category"] = None
                                else:
                                    summary["status"] = "duplicate_state_ambiguous"
                                    summary["error_category"] = "reconcile"
                            if summary.get("status") is not None:
                                summary["duplicate_outcome"] = summary["status"]
                if owned_raw_instance_ids:
                    _cleanup_duplicate_load_behavior_instances(
                        base_url=base_url,
                        timeout_s=request_timeout_s,
                        transport=effective_transport,
                        summary=summary,
                        event_records=event_records,
                        scenario=safe_scenario,
                        model_id=safe_model_id,
                        raw_instance_ids=owned_raw_instance_ids,
                        api_token=api_token,
                    )
                summary.pop("instance_id_hash", None)
                _record_elapsed_ms(summary, started_at=started_at)

    elif safe_scenario == "policy_backed_smoke":
        summary["policy_step_decisions"] = []
        summary["duplicate_prevented"] = False
        owned_raw_instance_ids_by_hash: dict[str, str] = {}
        owned_configs_by_hash: dict[str, LoadConfig] = {}
        requested_config = LoadConfig(
            model_key=safe_model_id,
            context_length=requested_context_length,
            parallel=requested_parallel,
        )
        baseline_state = _get_models_state(
            base_url=base_url,
            timeout_s=request_timeout_s,
            transport=effective_transport,
            summary=summary,
            event_records=event_records,
            scenario=safe_scenario,
            model_id=safe_model_id,
            phase="policy_baseline",
            api_token=api_token,
        )
        if baseline_state is not None:
            baseline_loaded_count = baseline_state["observed_loaded_count"]
            summary["baseline_loaded_count"] = baseline_loaded_count
            if baseline_loaded_count != 0:
                summary["status"] = "policy_smoke_preloaded_not_clean"
                summary["error_category"] = None
                summary["cleanup_not_performed"] = True
            else:
                initial_decision = ensure_loaded_decision(
                    requested_config,
                    _build_policy_observed_state(
                        model_id=safe_model_id,
                        state=baseline_state,
                        owned_configs_by_hash=owned_configs_by_hash,
                    ),
                )
                _record_policy_decision(
                    summary=summary,
                    event_records=event_records,
                    scenario=safe_scenario,
                    phase="ensure_loaded_absent",
                    decision=initial_decision,
                )
                if initial_decision.action != "load_required":
                    _set_policy_decision_mismatch(
                        summary=summary,
                        phase="ensure_loaded_absent",
                        expected_action="load_required",
                        decision=initial_decision,
                    )
                else:
                    raw_instance_id = _post_load(
                        base_url=base_url,
                        timeout_s=request_timeout_s,
                        transport=effective_transport,
                        summary=summary,
                        event_records=event_records,
                        scenario=safe_scenario,
                        model_id=safe_model_id,
                        context_length=requested_context_length,
                        parallel=requested_parallel,
                        api_token=api_token,
                        phase="policy_load",
                    )
                    if raw_instance_id is not None:
                        state_after_load = _get_models_state(
                            base_url=base_url,
                            timeout_s=request_timeout_s,
                            transport=effective_transport,
                            summary=summary,
                            event_records=event_records,
                            scenario=safe_scenario,
                            model_id=safe_model_id,
                            phase="policy_verify_load",
                            api_token=api_token,
                        )
                        if state_after_load is not None:
                            instance_id_hash = _sha256_text(raw_instance_id)
                            load_verified = (
                                state_after_load["observed_loaded_count"] == 1
                                and raw_instance_id in state_after_load["instance_ids"]
                            )
                            summary["load_verified"] = load_verified
                            summary["observed_loaded_count_after_load"] = state_after_load[
                                "observed_loaded_count"
                            ]
                            if not load_verified:
                                summary["status"] = "policy_smoke_load_not_verified"
                                summary["error_category"] = "reconcile"
                            else:
                                resolved_config = _resolved_policy_load_config(
                                    summary=summary,
                                    model_id=safe_model_id,
                                    requested_context_length=requested_context_length,
                                    requested_parallel=requested_parallel,
                                )
                                owned_raw_instance_ids_by_hash[instance_id_hash] = raw_instance_id
                                owned_configs_by_hash[instance_id_hash] = resolved_config
                                summary["instance_id_hash"] = instance_id_hash
                                summary["owned_instance_hashes"] = [instance_id_hash]

                                reuse_state = _get_models_state(
                                    base_url=base_url,
                                    timeout_s=request_timeout_s,
                                    transport=effective_transport,
                                    summary=summary,
                                    event_records=event_records,
                                    scenario=safe_scenario,
                                    model_id=safe_model_id,
                                    phase="policy_reuse_check",
                                    api_token=api_token,
                                )
                                if reuse_state is not None:
                                    reuse_decision = ensure_loaded_decision(
                                        requested_config,
                                        _build_policy_observed_state(
                                            model_id=safe_model_id,
                                            state=reuse_state,
                                            owned_configs_by_hash=owned_configs_by_hash,
                                        ),
                                    )
                                    _record_policy_decision(
                                        summary=summary,
                                        event_records=event_records,
                                        scenario=safe_scenario,
                                        phase="ensure_loaded_reuse",
                                        decision=reuse_decision,
                                    )
                                    if reuse_decision.action != "reuse_existing":
                                        _set_policy_decision_mismatch(
                                            summary=summary,
                                            phase="ensure_loaded_reuse",
                                            expected_action="reuse_existing",
                                            decision=reuse_decision,
                                        )
                                    else:
                                        summary["duplicate_prevented"] = True
                                        unload_state = _get_models_state(
                                            base_url=base_url,
                                            timeout_s=request_timeout_s,
                                            transport=effective_transport,
                                            summary=summary,
                                            event_records=event_records,
                                            scenario=safe_scenario,
                                            model_id=safe_model_id,
                                            phase="policy_before_unload",
                                            api_token=api_token,
                                        )
                                        if unload_state is not None:
                                            unload_decision = ensure_unloaded_decision(
                                                _build_policy_observed_state(
                                                    model_id=safe_model_id,
                                                    state=unload_state,
                                                    owned_configs_by_hash=owned_configs_by_hash,
                                                )
                                            )
                                            _record_policy_decision(
                                                summary=summary,
                                                event_records=event_records,
                                                scenario=safe_scenario,
                                                phase="ensure_unloaded_loaded",
                                                decision=unload_decision,
                                            )
                                            if unload_decision.action != "unload_required":
                                                _set_policy_decision_mismatch(
                                                    summary=summary,
                                                    phase="ensure_unloaded_loaded",
                                                    expected_action="unload_required",
                                                    decision=unload_decision,
                                                )
                                            else:
                                                target_hashes = list(unload_decision.target_hashes)
                                                raw_instance_ids = _raw_instance_ids_for_hashes(
                                                    target_hashes=target_hashes,
                                                    owned_raw_instance_ids_by_hash=(
                                                        owned_raw_instance_ids_by_hash
                                                    ),
                                                )
                                                if len(raw_instance_ids) != 1:
                                                    summary["status"] = (
                                                        "policy_smoke_owned_identity_missing"
                                                    )
                                                    summary["error_category"] = "policy"
                                                    summary["policy_phase"] = (
                                                        "ensure_unloaded_loaded"
                                                    )
                                                elif _post_unload(
                                                    base_url=base_url,
                                                    timeout_s=request_timeout_s,
                                                    transport=effective_transport,
                                                    summary=summary,
                                                    event_records=event_records,
                                                    scenario=safe_scenario,
                                                    raw_instance_id=raw_instance_ids[0],
                                                    instance_id_hash=target_hashes[0],
                                                    phase="policy_unload",
                                                    api_token=api_token,
                                                ):
                                                    state_after_unload = _get_models_state(
                                                        base_url=base_url,
                                                        timeout_s=request_timeout_s,
                                                        transport=effective_transport,
                                                        summary=summary,
                                                        event_records=event_records,
                                                        scenario=safe_scenario,
                                                        model_id=safe_model_id,
                                                        phase="policy_verify_unload",
                                                        api_token=api_token,
                                                    )
                                                    if state_after_unload is not None:
                                                        summary[
                                                            "observed_loaded_count_after_unload"
                                                        ] = state_after_unload[
                                                            "observed_loaded_count"
                                                        ]
                                                        if (
                                                            state_after_unload[
                                                                "observed_loaded_count"
                                                            ]
                                                            != 0
                                                        ):
                                                            summary["status"] = (
                                                                "policy_smoke_unload_not_verified"
                                                            )
                                                            summary["error_category"] = "reconcile"
                                                        else:
                                                            final_state = _get_models_state(
                                                                base_url=base_url,
                                                                timeout_s=request_timeout_s,
                                                                transport=effective_transport,
                                                                summary=summary,
                                                                event_records=event_records,
                                                                scenario=safe_scenario,
                                                                model_id=safe_model_id,
                                                                phase="policy_already_gone",
                                                                api_token=api_token,
                                                            )
                                                            if final_state is not None:
                                                                already_gone_decision = ensure_unloaded_decision(
                                                                    _build_policy_observed_state(
                                                                        model_id=safe_model_id,
                                                                        state=final_state,
                                                                        owned_configs_by_hash=owned_configs_by_hash,
                                                                    )
                                                                )
                                                                _record_policy_decision(
                                                                    summary=summary,
                                                                    event_records=event_records,
                                                                    scenario=safe_scenario,
                                                                    phase="ensure_unloaded_gone",
                                                                    decision=(
                                                                        already_gone_decision
                                                                    ),
                                                                )
                                                                if (
                                                                    already_gone_decision.action
                                                                    != "already_unloaded"
                                                                ):
                                                                    _set_policy_decision_mismatch(
                                                                        summary=summary,
                                                                        phase="ensure_unloaded_gone",
                                                                        expected_action=(
                                                                            "already_unloaded"
                                                                        ),
                                                                        decision=(
                                                                            already_gone_decision
                                                                        ),
                                                                    )
                                                                else:
                                                                    summary["status"] = (
                                                                        "policy_smoke_ok"
                                                                    )
                                                                    summary["error_category"] = None

    elif safe_scenario == "policy_two_model_swap":
        summary["policy_step_decisions"] = []
        summary["primary_load_call_count"] = 0
        summary["primary_unload_call_count"] = 0
        summary["secondary_load_call_count"] = 0
        summary["secondary_unload_call_count"] = 0
        owned_raw_instance_ids_by_hash: dict[str, str] = {}
        owned_configs_by_hash: dict[str, LoadConfig] = {}
        primary_requested_config = LoadConfig(
            model_key=safe_model_id,
            context_length=requested_context_length,
            parallel=requested_parallel,
        )
        secondary_requested_config = LoadConfig(
            model_key=safe_secondary_model_id or "",
            context_length=requested_context_length,
            parallel=requested_parallel,
        )
        baseline_states = _get_named_models_state(
            base_url=base_url,
            timeout_s=request_timeout_s,
            transport=effective_transport,
            summary=summary,
            event_records=event_records,
            scenario=safe_scenario,
            model_ids={
                "primary": safe_model_id,
                "secondary": safe_secondary_model_id or "",
            },
            phase="policy_swap_baseline",
            api_token=api_token,
        )
        if baseline_states is not None:
            primary_baseline_state = baseline_states["primary"]
            secondary_baseline_state = baseline_states["secondary"]
            summary["baseline_primary_loaded_count"] = primary_baseline_state[
                "observed_loaded_count"
            ]
            summary["baseline_secondary_loaded_count"] = secondary_baseline_state[
                "observed_loaded_count"
            ]
            if (
                primary_baseline_state["observed_loaded_count"] != 0
                or secondary_baseline_state["observed_loaded_count"] != 0
            ):
                summary["status"] = "policy_swap_preloaded_not_clean"
                summary["error_category"] = None
                summary["cleanup_not_performed"] = True
            else:
                primary_load_decision = ensure_loaded_decision(
                    primary_requested_config,
                    _build_policy_observed_state(
                        model_id=safe_model_id,
                        state=primary_baseline_state,
                        owned_configs_by_hash=owned_configs_by_hash,
                    ),
                )
                _record_policy_decision(
                    summary=summary,
                    event_records=event_records,
                    scenario=safe_scenario,
                    phase="primary_ensure_loaded",
                    decision=primary_load_decision,
                    summary_label=f"primary_{primary_load_decision.action}",
                )
                if primary_load_decision.action != "load_required":
                    _set_policy_decision_mismatch(
                        summary=summary,
                        phase="primary_ensure_loaded",
                        expected_action="load_required",
                        decision=primary_load_decision,
                        status="policy_swap_decision_mismatch",
                    )
                else:
                    _increment_summary_count(summary, "primary_load_call_count")
                    raw_primary_instance_id = _post_load(
                        base_url=base_url,
                        timeout_s=request_timeout_s,
                        transport=effective_transport,
                        summary=summary,
                        event_records=event_records,
                        scenario=safe_scenario,
                        model_id=safe_model_id,
                        context_length=requested_context_length,
                        parallel=requested_parallel,
                        api_token=api_token,
                        phase="policy_swap_primary_load",
                    )
                    if raw_primary_instance_id is not None:
                        primary_state_after_load = _get_models_state(
                            base_url=base_url,
                            timeout_s=request_timeout_s,
                            transport=effective_transport,
                            summary=summary,
                            event_records=event_records,
                            scenario=safe_scenario,
                            model_id=safe_model_id,
                            phase="policy_swap_primary_verify_load",
                            api_token=api_token,
                        )
                        if primary_state_after_load is not None:
                            summary["primary_loaded_after_load"] = primary_state_after_load[
                                "observed_loaded_count"
                            ]
                            primary_load_verified = (
                                primary_state_after_load["observed_loaded_count"] == 1
                                and raw_primary_instance_id
                                in primary_state_after_load["instance_ids"]
                            )
                            if not primary_load_verified:
                                summary["status"] = "policy_swap_primary_load_not_verified"
                                summary["error_category"] = "reconcile"
                            else:
                                primary_instance_hash = _sha256_text(raw_primary_instance_id)
                                owned_raw_instance_ids_by_hash[primary_instance_hash] = (
                                    raw_primary_instance_id
                                )
                                owned_configs_by_hash[primary_instance_hash] = (
                                    _resolved_policy_load_config(
                                        summary=summary,
                                        model_id=safe_model_id,
                                        requested_context_length=requested_context_length,
                                        requested_parallel=requested_parallel,
                                    )
                                )
                                summary["primary_instance_id_hash"] = primary_instance_hash

                                primary_unload_decision = ensure_unloaded_decision(
                                    _build_policy_observed_state(
                                        model_id=safe_model_id,
                                        state=primary_state_after_load,
                                        owned_configs_by_hash=owned_configs_by_hash,
                                    )
                                )
                                _record_policy_decision(
                                    summary=summary,
                                    event_records=event_records,
                                    scenario=safe_scenario,
                                    phase="primary_ensure_unloaded",
                                    decision=primary_unload_decision,
                                    summary_label=(f"primary_{primary_unload_decision.action}"),
                                )
                                if primary_unload_decision.action != "unload_required":
                                    _set_policy_decision_mismatch(
                                        summary=summary,
                                        phase="primary_ensure_unloaded",
                                        expected_action="unload_required",
                                        decision=primary_unload_decision,
                                        status="policy_swap_decision_mismatch",
                                    )
                                else:
                                    primary_unload_raw_ids = _raw_instance_ids_for_hashes(
                                        target_hashes=primary_unload_decision.target_hashes,
                                        owned_raw_instance_ids_by_hash=(
                                            owned_raw_instance_ids_by_hash
                                        ),
                                    )
                                    if len(primary_unload_raw_ids) != 1:
                                        summary["status"] = "policy_swap_primary_identity_missing"
                                        summary["error_category"] = "policy"
                                        summary["policy_phase"] = "primary_ensure_unloaded"
                                    else:
                                        _increment_summary_count(
                                            summary, "primary_unload_call_count"
                                        )
                                        primary_unload_ok = _post_unload(
                                            base_url=base_url,
                                            timeout_s=request_timeout_s,
                                            transport=effective_transport,
                                            summary=summary,
                                            event_records=event_records,
                                            scenario=safe_scenario,
                                            raw_instance_id=primary_unload_raw_ids[0],
                                            instance_id_hash=(
                                                primary_unload_decision.target_hashes[0]
                                            ),
                                            phase="policy_swap_primary_unload",
                                            api_token=api_token,
                                        )
                                        if primary_unload_ok:
                                            states_after_primary_unload = _get_named_models_state(
                                                base_url=base_url,
                                                timeout_s=request_timeout_s,
                                                transport=effective_transport,
                                                summary=summary,
                                                event_records=event_records,
                                                scenario=safe_scenario,
                                                model_ids={
                                                    "primary": safe_model_id,
                                                    "secondary": (safe_secondary_model_id or ""),
                                                },
                                                phase="policy_swap_after_primary_unload",
                                                api_token=api_token,
                                            )
                                            if states_after_primary_unload is not None:
                                                primary_state_after_unload = (
                                                    states_after_primary_unload["primary"]
                                                )
                                                secondary_state_before_load = (
                                                    states_after_primary_unload["secondary"]
                                                )
                                                summary["primary_loaded_after_unload"] = (
                                                    primary_state_after_unload[
                                                        "observed_loaded_count"
                                                    ]
                                                )
                                                if (
                                                    primary_state_after_unload[
                                                        "observed_loaded_count"
                                                    ]
                                                    != 0
                                                ):
                                                    summary["status"] = (
                                                        "policy_swap_primary_unload_not_verified"
                                                    )
                                                    summary["error_category"] = "reconcile"
                                                else:
                                                    secondary_load_decision = (
                                                        ensure_loaded_decision(
                                                            secondary_requested_config,
                                                            _build_policy_observed_state(
                                                                model_id=(
                                                                    safe_secondary_model_id or ""
                                                                ),
                                                                state=(secondary_state_before_load),
                                                                owned_configs_by_hash=(
                                                                    owned_configs_by_hash
                                                                ),
                                                            ),
                                                        )
                                                    )
                                                    _record_policy_decision(
                                                        summary=summary,
                                                        event_records=event_records,
                                                        scenario=safe_scenario,
                                                        phase="secondary_ensure_loaded",
                                                        decision=secondary_load_decision,
                                                        summary_label=(
                                                            f"secondary_{secondary_load_decision.action}"
                                                        ),
                                                    )
                                                    if (
                                                        secondary_load_decision.action
                                                        != "load_required"
                                                    ):
                                                        _set_policy_decision_mismatch(
                                                            summary=summary,
                                                            phase="secondary_ensure_loaded",
                                                            expected_action="load_required",
                                                            decision=secondary_load_decision,
                                                            status="policy_swap_decision_mismatch",
                                                        )
                                                    else:
                                                        _increment_summary_count(
                                                            summary,
                                                            "secondary_load_call_count",
                                                        )
                                                        raw_secondary_instance_id = _post_load(
                                                            base_url=base_url,
                                                            timeout_s=request_timeout_s,
                                                            transport=effective_transport,
                                                            summary=summary,
                                                            event_records=event_records,
                                                            scenario=safe_scenario,
                                                            model_id=(
                                                                safe_secondary_model_id or ""
                                                            ),
                                                            context_length=requested_context_length,
                                                            parallel=requested_parallel,
                                                            api_token=api_token,
                                                            phase=("policy_swap_secondary_load"),
                                                        )
                                                        if raw_secondary_instance_id is not None:
                                                            states_after_secondary_load = _get_named_models_state(
                                                                base_url=base_url,
                                                                timeout_s=request_timeout_s,
                                                                transport=effective_transport,
                                                                summary=summary,
                                                                event_records=event_records,
                                                                scenario=safe_scenario,
                                                                model_ids={
                                                                    "primary": safe_model_id,
                                                                    "secondary": (
                                                                        safe_secondary_model_id
                                                                        or ""
                                                                    ),
                                                                },
                                                                phase=(
                                                                    "policy_swap_after_secondary_load"
                                                                ),
                                                                api_token=api_token,
                                                            )
                                                            if (
                                                                states_after_secondary_load
                                                                is not None
                                                            ):
                                                                primary_state_after_secondary = (
                                                                    states_after_secondary_load[
                                                                        "primary"
                                                                    ]
                                                                )
                                                                secondary_state_after_load = (
                                                                    states_after_secondary_load[
                                                                        "secondary"
                                                                    ]
                                                                )
                                                                summary[
                                                                    "primary_loaded_after_secondary_load"
                                                                ] = primary_state_after_secondary[
                                                                    "observed_loaded_count"
                                                                ]
                                                                summary[
                                                                    "secondary_loaded_after_load"
                                                                ] = secondary_state_after_load[
                                                                    "observed_loaded_count"
                                                                ]
                                                                secondary_load_verified = (
                                                                    secondary_state_after_load[
                                                                        "observed_loaded_count"
                                                                    ]
                                                                    == 1
                                                                    and raw_secondary_instance_id
                                                                    in secondary_state_after_load[
                                                                        "instance_ids"
                                                                    ]
                                                                )
                                                                primary_remains_unloaded = (
                                                                    primary_state_after_secondary[
                                                                        "observed_loaded_count"
                                                                    ]
                                                                    == 0
                                                                )
                                                                summary[
                                                                    "single_model_safe_verified"
                                                                ] = bool(
                                                                    secondary_load_verified
                                                                    and primary_remains_unloaded
                                                                )
                                                                if not secondary_load_verified:
                                                                    summary["status"] = (
                                                                        "policy_swap_secondary_load_not_verified"
                                                                    )
                                                                    summary["error_category"] = (
                                                                        "reconcile"
                                                                    )
                                                                elif not primary_remains_unloaded:
                                                                    summary["status"] = (
                                                                        "policy_swap_primary_still_loaded_after_secondary"
                                                                    )
                                                                    summary["error_category"] = (
                                                                        "reconcile"
                                                                    )
                                                                else:
                                                                    secondary_instance_hash = _sha256_text(
                                                                        raw_secondary_instance_id
                                                                    )
                                                                    owned_raw_instance_ids_by_hash[
                                                                        secondary_instance_hash
                                                                    ] = raw_secondary_instance_id
                                                                    owned_configs_by_hash[
                                                                        secondary_instance_hash
                                                                    ] = _resolved_policy_load_config(
                                                                        summary=summary,
                                                                        model_id=(
                                                                            safe_secondary_model_id
                                                                            or ""
                                                                        ),
                                                                        requested_context_length=(
                                                                            requested_context_length
                                                                        ),
                                                                        requested_parallel=(
                                                                            requested_parallel
                                                                        ),
                                                                    )
                                                                    summary[
                                                                        "secondary_instance_id_hash"
                                                                    ] = secondary_instance_hash

                                                                    secondary_cleanup_decision = ensure_unloaded_decision(
                                                                        _build_policy_observed_state(
                                                                            model_id=(
                                                                                safe_secondary_model_id
                                                                                or ""
                                                                            ),
                                                                            state=(
                                                                                secondary_state_after_load
                                                                            ),
                                                                            owned_configs_by_hash=(
                                                                                owned_configs_by_hash
                                                                            ),
                                                                        )
                                                                    )
                                                                    _record_policy_decision(
                                                                        summary=summary,
                                                                        event_records=event_records,
                                                                        scenario=safe_scenario,
                                                                        phase=("secondary_cleanup"),
                                                                        decision=(
                                                                            secondary_cleanup_decision
                                                                        ),
                                                                        summary_label=(
                                                                            f"secondary_cleanup_{secondary_cleanup_decision.action}"
                                                                        ),
                                                                    )
                                                                    if (
                                                                        secondary_cleanup_decision.action
                                                                        != "unload_required"
                                                                    ):
                                                                        _set_policy_decision_mismatch(
                                                                            summary=summary,
                                                                            phase="secondary_cleanup",
                                                                            expected_action=(
                                                                                "unload_required"
                                                                            ),
                                                                            decision=(
                                                                                secondary_cleanup_decision
                                                                            ),
                                                                            status=(
                                                                                "policy_swap_decision_mismatch"
                                                                            ),
                                                                        )
                                                                    else:
                                                                        secondary_cleanup_raw_ids = _raw_instance_ids_for_hashes(
                                                                            target_hashes=(
                                                                                secondary_cleanup_decision.target_hashes
                                                                            ),
                                                                            owned_raw_instance_ids_by_hash=(
                                                                                owned_raw_instance_ids_by_hash
                                                                            ),
                                                                        )
                                                                        if (
                                                                            len(
                                                                                secondary_cleanup_raw_ids
                                                                            )
                                                                            != 1
                                                                        ):
                                                                            summary["status"] = (
                                                                                "policy_swap_secondary_identity_missing"
                                                                            )
                                                                            summary[
                                                                                "error_category"
                                                                            ] = "policy"
                                                                            summary[
                                                                                "policy_phase"
                                                                            ] = "secondary_cleanup"
                                                                        else:
                                                                            summary[
                                                                                "cleanup_secondary_target_instance_hashes"
                                                                            ] = list(
                                                                                secondary_cleanup_decision.target_hashes
                                                                            )
                                                                            _increment_summary_count(
                                                                                summary,
                                                                                "secondary_unload_call_count",
                                                                            )
                                                                            secondary_unload_ok = _post_unload(
                                                                                base_url=base_url,
                                                                                timeout_s=request_timeout_s,
                                                                                transport=effective_transport,
                                                                                summary=summary,
                                                                                event_records=event_records,
                                                                                scenario=safe_scenario,
                                                                                raw_instance_id=(
                                                                                    secondary_cleanup_raw_ids[
                                                                                        0
                                                                                    ]
                                                                                ),
                                                                                instance_id_hash=(
                                                                                    secondary_cleanup_decision.target_hashes[
                                                                                        0
                                                                                    ]
                                                                                ),
                                                                                phase=(
                                                                                    "policy_swap_secondary_cleanup"
                                                                                ),
                                                                                api_token=api_token,
                                                                            )
                                                                            if secondary_unload_ok:
                                                                                summary[
                                                                                    "cleanup_called"
                                                                                ] = True
                                                                                cleanup_states = _get_named_models_state(
                                                                                    base_url=base_url,
                                                                                    timeout_s=request_timeout_s,
                                                                                    transport=effective_transport,
                                                                                    summary=summary,
                                                                                    event_records=event_records,
                                                                                    scenario=safe_scenario,
                                                                                    model_ids={
                                                                                        "primary": safe_model_id,
                                                                                        "secondary": (
                                                                                            safe_secondary_model_id
                                                                                            or ""
                                                                                        ),
                                                                                    },
                                                                                    phase=(
                                                                                        "policy_swap_cleanup_verify"
                                                                                    ),
                                                                                    api_token=api_token,
                                                                                )
                                                                                if (
                                                                                    cleanup_states
                                                                                    is not None
                                                                                ):
                                                                                    primary_cleanup_state = cleanup_states[
                                                                                        "primary"
                                                                                    ]
                                                                                    secondary_cleanup_state = cleanup_states[
                                                                                        "secondary"
                                                                                    ]
                                                                                    summary[
                                                                                        "primary_loaded_after_cleanup"
                                                                                    ] = primary_cleanup_state[
                                                                                        "observed_loaded_count"
                                                                                    ]
                                                                                    summary[
                                                                                        "secondary_loaded_after_cleanup"
                                                                                    ] = secondary_cleanup_state[
                                                                                        "observed_loaded_count"
                                                                                    ]
                                                                                    summary[
                                                                                        "cleanup_secondary_verification_observed"
                                                                                    ] = True
                                                                                    summary[
                                                                                        "cleanup_secondary_verified_count"
                                                                                    ] = (
                                                                                        1
                                                                                        if secondary_cleanup_state[
                                                                                            "observed_loaded_count"
                                                                                        ]
                                                                                        == 0
                                                                                        else 0
                                                                                    )
                                                                                    summary[
                                                                                        "cleanup_secondary_remaining_count"
                                                                                    ] = (
                                                                                        0
                                                                                        if secondary_cleanup_state[
                                                                                            "observed_loaded_count"
                                                                                        ]
                                                                                        == 0
                                                                                        else 1
                                                                                    )
                                                                                    if (
                                                                                        primary_cleanup_state[
                                                                                            "observed_loaded_count"
                                                                                        ]
                                                                                        == 0
                                                                                        and secondary_cleanup_state[
                                                                                            "observed_loaded_count"
                                                                                        ]
                                                                                        == 0
                                                                                    ):
                                                                                        summary[
                                                                                            "status"
                                                                                        ] = "policy_swap_ok"
                                                                                        summary[
                                                                                            "error_category"
                                                                                        ] = None
                                                                                    else:
                                                                                        summary[
                                                                                            "status"
                                                                                        ] = "policy_swap_cleanup_not_verified"
                                                                                        summary[
                                                                                            "error_category"
                                                                                        ] = "reconcile"

    elif safe_scenario == "two_model_swap_plan":
        state_before = _get_models_state(
            base_url=base_url,
            timeout_s=request_timeout_s,
            transport=effective_transport,
            summary=summary,
            event_records=event_records,
            scenario=safe_scenario,
            model_id=safe_model_id,
            phase="before_swap",
            api_token=api_token,
        )
        if state_before is not None:
            summary["primary_observed_loaded_count_before"] = state_before["observed_loaded_count"]
            if state_before["observed_loaded_count"] > 1:
                summary["status"] = "duplicate_instances"
                summary["error_category"] = None
            else:
                primary_unload_attempted = False
                if state_before["observed_loaded_count"] == 1:
                    primary_unload_attempted = True
                    raw_instance_id = state_before["instance_ids"][0]
                    primary_instance_id_hash = state_before["instance_id_hashes"][0]
                    summary["primary_instance_id_hash"] = primary_instance_id_hash
                    summary["primary_unload_attempted"] = True
                    if not _post_unload(
                        base_url=base_url,
                        timeout_s=request_timeout_s,
                        transport=effective_transport,
                        summary=summary,
                        event_records=event_records,
                        scenario=safe_scenario,
                        raw_instance_id=raw_instance_id,
                        instance_id_hash=primary_instance_id_hash,
                        phase="swap_unload_primary",
                        api_token=api_token,
                    ):
                        raw_instance_id = None
                raw_secondary_instance_id = None
                if summary.get("status") is None:
                    raw_secondary_instance_id = _post_load(
                        base_url=base_url,
                        timeout_s=request_timeout_s,
                        transport=effective_transport,
                        summary=summary,
                        event_records=event_records,
                        scenario=safe_scenario,
                        model_id=safe_secondary_model_id or "",
                        context_length=requested_context_length,
                        parallel=requested_parallel,
                        api_token=api_token,
                    )
                if raw_secondary_instance_id is not None:
                    secondary_state = _get_models_state(
                        base_url=base_url,
                        timeout_s=request_timeout_s,
                        transport=effective_transport,
                        summary=summary,
                        event_records=event_records,
                        scenario=safe_scenario,
                        model_id=safe_secondary_model_id or "",
                        phase="after_swap",
                        api_token=api_token,
                    )
                    if secondary_state is not None:
                        summary["secondary_observed_loaded_count_after"] = secondary_state[
                            "observed_loaded_count"
                        ]
                        summary["secondary_load_verified"] = (
                            raw_secondary_instance_id in secondary_state["instance_ids"]
                        )
                        if summary.get("instance_id_hash") is not None:
                            summary["secondary_instance_id_hash"] = summary["instance_id_hash"]
                            del summary["instance_id_hash"]
                        secondary_ok = bool(summary.get("secondary_load_verified"))
                        if primary_unload_attempted:
                            summary["primary_observed_loaded_count_after"] = 0
                        summary["status"] = "ok" if secondary_ok else "load_not_verified"
                        summary["error_category"] = None if secondary_ok else "reconcile"

    elif safe_scenario == "unload_already_gone":
        state = _get_models_state(
            base_url=base_url,
            timeout_s=request_timeout_s,
            transport=effective_transport,
            summary=summary,
            event_records=event_records,
            scenario=safe_scenario,
            model_id=safe_model_id,
            phase="already_gone",
            api_token=api_token,
        )
        if state is not None:
            summary["observed_loaded_count"] = state["observed_loaded_count"]
            summary["status"] = (
                "already_unloaded" if state["observed_loaded_count"] == 0 else "still_loaded"
            )
            summary["error_category"] = None if state["observed_loaded_count"] == 0 else "loaded"

    elif safe_scenario == "load_timeout_reconcile":
        raw_instance_id = _post_load(
            base_url=base_url,
            timeout_s=request_timeout_s,
            transport=effective_transport,
            summary=summary,
            event_records=event_records,
            scenario=safe_scenario,
            model_id=safe_model_id,
            context_length=requested_context_length,
            parallel=requested_parallel,
            api_token=api_token,
        )
        if (
            summary.get("status") == "transport_error"
            and summary.get("error_category") == "timeout"
        ):
            state = _get_models_state(
                base_url=base_url,
                timeout_s=request_timeout_s,
                transport=effective_transport,
                summary=summary,
                event_records=event_records,
                scenario=safe_scenario,
                model_id=safe_model_id,
                phase="timeout_reconcile",
                api_token=api_token,
            )
            if state is None:
                summary["reconcile_status"] = summary.get("status")
                summary["reconcile_error_category"] = summary.get("error_category")
                summary["status"] = "load_reconcile_error"
                summary["error_category"] = "reconcile"
                summary["cleanup_not_performed"] = True
            else:
                observed_loaded_count = state["observed_loaded_count"]
                summary["observed_loaded_count"] = observed_loaded_count
                summary["observed_loaded_count_initial"] = observed_loaded_count
                summary["observed_loaded_count_final"] = observed_loaded_count
                if observed_loaded_count > 0:
                    summary["status"] = "load_succeeded_but_response_lost"
                    summary["error_category"] = None
                    summary["load_verified"] = True
                    if state["instance_id_hashes"]:
                        summary["instance_id_hash"] = state["instance_id_hashes"][0]
                    cleanup_safe_raw_instance_ids = (
                        state["instance_ids"] if observed_loaded_count == 1 else ()
                    )
                    if cleanup_safe_raw_instance_ids:
                        _cleanup_exact_instance_ids(
                            base_url=base_url,
                            timeout_s=request_timeout_s,
                            transport=effective_transport,
                            summary=summary,
                            event_records=event_records,
                            scenario=safe_scenario,
                            model_id=safe_model_id,
                            raw_instance_ids=cleanup_safe_raw_instance_ids,
                            api_token=api_token,
                            persist_hash_field="cleanup_target_instance_hashes",
                            verification_phase="timeout_cleanup_verify",
                        )
                        if "cleanup_final_loaded_count" in summary:
                            summary["observed_loaded_count_final"] = summary[
                                "cleanup_final_loaded_count"
                            ]
                    else:
                        summary["cleanup_not_performed"] = True
                else:
                    summary["status"] = "load_unknown_or_failed"
                    summary["error_category"] = "timeout"
                    summary["load_verified"] = False
        elif raw_instance_id is not None:
            state = _get_models_state(
                base_url=base_url,
                timeout_s=request_timeout_s,
                transport=effective_transport,
                summary=summary,
                event_records=event_records,
                scenario=safe_scenario,
                model_id=safe_model_id,
                phase="verify_load_after_timeout",
                api_token=api_token,
            )
            if state is not None:
                summary["load_verified"] = raw_instance_id in state["instance_ids"]
                summary["observed_loaded_count"] = state["observed_loaded_count"]
                summary["status"] = "ok" if summary["load_verified"] else "load_not_verified"
                summary["error_category"] = None if summary["load_verified"] else "reconcile"

    warning = summary.get("status") not in {
        "planned",
        "ok",
        "already_unloaded",
        "externally_unloaded",
        "duplicate_instances",
        "duplicate_reused_or_idempotent",
        "duplicate_instances_confirmed",
        "duplicate_rejected",
        "preloaded_not_clean",
        "policy_smoke_ok",
        "policy_smoke_preloaded_not_clean",
        "policy_swap_ok",
        "policy_swap_preloaded_not_clean",
        "config_mismatch",
        "duplicate_state_ambiguous",
        "load_succeeded_response_lost",
        "load_succeeded_but_response_lost",
        "load_unknown_or_failed",
        "load_reconcile_error",
        "not_loaded",
        "manual_unload_not_observed",
    }
    _log_terminal_state(summary, warning=warning)
    return ModelLifecycleResult(summary=summary, event_records=tuple(event_records))


def render_model_lifecycle_report(
    *,
    run_id: str,
    summary: Mapping[str, object],
    output_files: Sequence[str] = MODEL_LIFECYCLE_RESULT_FILE_NAMES,
) -> str:
    lines = [
        "# LM Studio Lifecycle Report",
        "",
        "## Run",
        "",
        "- command: `probe-lifecycle`",
        f"- run_id: `{run_id}`",
        f"- scenario: `{summary.get('scenario')}`",
        f"- model_id: `{summary.get('model_id')}`",
        f"- secondary_model_id: `{summary.get('secondary_model_id')}`",
        f"- execute_lifecycle: `{str(bool(summary.get('execute_lifecycle'))).lower()}`",
        f"- allow_remote: `{str(bool(summary.get('allow_remote'))).lower()}`",
        f"- is_localhost: `{str(bool(summary.get('is_localhost'))).lower()}`",
        f"- timeout_s: `{summary.get('timeout_s')}`",
        f"- max_polls: `{summary.get('max_polls')}`",
        f"- poll_interval_s: `{summary.get('poll_interval_s')}`",
        f"- endpoint_kinds_planned: `{summary.get('endpoint_kinds_planned')}`",
        f"- endpoint_kinds_used: `{summary.get('endpoint_kinds_used')}`",
        "",
        "## Result",
        "",
        f"- status: `{summary.get('status')}`",
        f"- error_category: `{summary.get('error_category')}`",
    ]
    for field_name in (
        "requested_context_length",
        "requested_parallel",
        "observed_loaded_count",
        "observed_loaded_count_before",
        "observed_loaded_count_after",
        "observed_loaded_count_initial",
        "observed_loaded_count_final",
        "baseline_loaded_count",
        "first_loaded_count",
        "final_loaded_count",
        "observed_loaded_count_after_load",
        "observed_loaded_count_after_unload",
        "poll_count",
        "polls_used",
        "elapsed_ms",
        "instance_id_hash",
        "instance_id_hashes",
        "first_instance_id_hash",
        "second_instance_id_hash",
        "owned_instance_hashes",
        "duplicate_instance_count",
        "distinct_instance_hash_count",
        "duplicate_outcome",
        "primary_instance_id_hash",
        "primary_observed_loaded_count_before",
        "primary_observed_loaded_count_after",
        "primary_unload_attempted",
        "secondary_instance_id_hash",
        "secondary_observed_loaded_count_after",
        "secondary_load_verified",
        "swap_policy",
        "baseline_primary_loaded_count",
        "baseline_secondary_loaded_count",
        "primary_load_call_count",
        "primary_unload_call_count",
        "secondary_load_call_count",
        "secondary_unload_call_count",
        "primary_loaded_after_load",
        "primary_loaded_after_unload",
        "secondary_loaded_after_load",
        "primary_loaded_after_secondary_load",
        "primary_loaded_after_cleanup",
        "secondary_loaded_after_cleanup",
        "single_model_safe_verified",
        "cleanup_secondary_target_instance_hashes",
        "cleanup_secondary_verified_count",
        "cleanup_secondary_remaining_count",
        "cleanup_secondary_verification_observed",
        "echo_status",
        "applied_context_length",
        "applied_context_length_candidates",
        "applied_parallel",
        "applied_parallel_candidates",
        "context_length_verified",
        "parallel_verified",
        "load_verified",
        "first_load_verified",
        "load_called",
        "load_call_count",
        "second_load_called",
        "unload_called",
        "unload_call_count",
        "cleanup_called",
        "cleanup_not_performed",
        "cleanup_verified_count",
        "cleanup_remaining_count",
        "cleanup_verification_observed",
        "cleanup_final_loaded_count",
        "cleanup_post_failures",
        "cleanup_target_instance_hashes",
        "api_token_present",
        "reconcile_status",
        "reconcile_error_category",
        "policy_step_decisions",
        "duplicate_prevented",
        "policy_phase",
        "policy_expected_action",
        "policy_observed_action",
        "policy_reason",
    ):
        if field_name in summary:
            lines.append(f"- {field_name}: `{summary.get(field_name)}`")
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- dry-run performs no network, load, or unload actions",
            "- execute mode uses only native list/load/unload endpoints",
            "- external_unload_reconcile prints MANUAL_ACTION_REQUIRED and waits for a manual unload observation",
            "- compat generation and download endpoints: not used",
            "- unload uses exact in-memory instance identity only; wildcard unload is not used",
            "- raw instance ids, base URL, token values, raw bodies, and local paths: not stored",
            "",
            "## Output Files",
            "",
            *(f"- `{file_name}`" for file_name in output_files),
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "MODEL_LIFECYCLE_LIST_ENDPOINT_PATH",
    "MODEL_LIFECYCLE_LOAD_ENDPOINT_PATH",
    "MODEL_LIFECYCLE_RESULT_FILE_NAMES",
    "MODEL_LIFECYCLE_SCENARIO_CHOICES",
    "MODEL_LIFECYCLE_UNLOAD_ENDPOINT_PATH",
    "ManagedLifecycleOperation",
    "ModelLifecycleResult",
    "ModelLifecycleTransport",
    "build_model_lifecycle_list_url",
    "build_model_lifecycle_load_url",
    "build_model_lifecycle_unload_url",
    "is_local_model_lifecycle_base_url",
    "probe_model_lifecycle",
    "render_model_lifecycle_report",
    "run_exact_model_operation",
    "validate_model_lifecycle_api_token_env",
    "validate_model_lifecycle_model_id",
]
