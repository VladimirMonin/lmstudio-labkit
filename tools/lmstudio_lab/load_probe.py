from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from urllib import request as urllib_request
from urllib.parse import urlunsplit

from .model_probe import (
    _CONTEXT_KEY_ALIASES,
    _LOCALHOST_NAMES,
    _PARALLEL_KEY_ALIASES,
    _attach_candidate_fields,
    _categorize_transport_error,
    _collect_int_candidates,
    _normalize_base_url,
    _normalize_key,
    _safe_float,
    _safe_int,
    _safe_model_id,
    _sanitize_external_mapping,
    _sha256_text,
)

type LoadProbeTransport = Callable[[urllib_request.Request, float], bytes]

LOAD_PROBE_ENDPOINT_PATH = "/api/v1/models/load"
LOAD_PROBE_RESULT_FILE_NAMES = (
    "environment.json",
    "load_probe.json",
    "report.md",
)

_CONFIG_CONTAINER_KEYS = frozenset(
    {
        "load_config",
        "applied_config",
        "config",
        "effective_config",
        "model_config",
        "loaded_config",
    }
)


@dataclass(frozen=True, slots=True)
class LoadProbeResult:
    summary: dict[str, object]


def _default_transport(request: urllib_request.Request, timeout_s: float) -> bytes:
    with urllib_request.urlopen(request, timeout=timeout_s) as response:
        return response.read()


def _require_safe_model_id(model_id: object) -> str:
    safe_model_id = _safe_model_id(model_id)
    if safe_model_id is None:
        raise ValueError("model_id must use a safe model identifier")
    return safe_model_id


def validate_load_probe_model_id(model_id: object) -> str:
    return _require_safe_model_id(model_id)


def _require_positive_int(value: object, *, field_name: str) -> int:
    integer_value = _safe_int(value)
    if integer_value is None or integer_value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return integer_value


def _require_positive_float(value: object, *, field_name: str) -> float:
    float_value = _safe_float(value)
    if float_value is None or float_value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return float_value


def is_local_load_probe_base_url(base_url: str) -> bool:
    return _normalize_base_url(base_url).hostname.lower() in _LOCALHOST_NAMES


def build_load_probe_url(base_url: str) -> str:
    parsed = _normalize_base_url(base_url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, LOAD_PROBE_ENDPOINT_PATH, "", ""))


def _base_summary(
    *,
    model_id: str,
    allow_remote: bool,
    is_localhost: bool,
    timeout_s: float,
    requested_context_length: int,
    requested_parallel: int,
) -> dict[str, object]:
    return {
        "probe_kind": "native_model_load",
        "endpoint_path": LOAD_PROBE_ENDPOINT_PATH,
        "allow_remote": allow_remote,
        "is_localhost": is_localhost,
        "timeout_s": timeout_s,
        "model_id": model_id,
        "requested_context_length": requested_context_length,
        "requested_parallel": requested_parallel,
    }


def _build_request_payload(
    *,
    model_id: str,
    context_length: int,
    parallel: int,
) -> dict[str, object]:
    return {
        "model": model_id,
        "context_length": context_length,
        "parallel": parallel,
        "echo_load_config": True,
    }


def _collect_sanitized_config_containers(
    payload: object,
    output: dict[str, dict[str, object]],
) -> None:
    if isinstance(payload, Mapping):
        for raw_key, raw_value in payload.items():
            normalized_key = _normalize_key(raw_key)
            if normalized_key in _CONFIG_CONTAINER_KEYS and isinstance(raw_value, Mapping):
                sanitized = _sanitize_external_mapping(raw_value)
                if sanitized and normalized_key not in output:
                    output[normalized_key] = sanitized
            _collect_sanitized_config_containers(raw_value, output)
        return
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for item in payload:
            _collect_sanitized_config_containers(item, output)


def _build_sanitized_applied_config(payload: object) -> dict[str, object] | None:
    containers: dict[str, dict[str, object]] = {}
    _collect_sanitized_config_containers(payload, containers)
    if not containers:
        return None
    if len(containers) == 1:
        return next(iter(containers.values()))
    return dict(containers)


def _extract_candidate_values(payload: object, *, aliases: frozenset[str]) -> set[int]:
    candidates: set[int] = set()
    _collect_int_candidates(payload, aliases, candidates)
    return {value for value in candidates if value > 0}


def _build_verification(
    *,
    requested_value: int,
    candidates: Sequence[int],
) -> bool | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0] == requested_value
    if requested_value not in candidates:
        return False
    return None


def probe_lmstudio_load(
    base_url: str,
    *,
    model_id: str,
    context_length: int = 32768,
    parallel: int = 1,
    allow_remote: bool = False,
    timeout_s: float = 120.0,
    transport: LoadProbeTransport | None = None,
    display_model_id: str | None = None,
    resolved_native_load_id_hash: str | None = None,
) -> LoadProbeResult:
    safe_model_id = _require_safe_model_id(model_id)
    safe_display_model_id = safe_model_id
    if display_model_id is not None:
        safe_display_model_id = _require_safe_model_id(display_model_id)
    requested_context_length = _require_positive_int(
        context_length,
        field_name="context_length",
    )
    requested_parallel = _require_positive_int(parallel, field_name="parallel")
    request_timeout_s = _require_positive_float(timeout_s, field_name="timeout_s")

    parsed = _normalize_base_url(base_url)
    is_localhost = parsed.hostname.lower() in _LOCALHOST_NAMES
    if not allow_remote and not is_localhost:
        raise ValueError("base_url must stay on localhost unless allow_remote is true")

    summary = _base_summary(
        model_id=safe_display_model_id,
        allow_remote=allow_remote,
        is_localhost=is_localhost,
        timeout_s=request_timeout_s,
        requested_context_length=requested_context_length,
        requested_parallel=requested_parallel,
    )
    if isinstance(resolved_native_load_id_hash, str) and resolved_native_load_id_hash:
        summary["resolved_native_load_id_hash"] = resolved_native_load_id_hash
    request_body = json.dumps(
        _build_request_payload(
            model_id=safe_model_id,
            context_length=requested_context_length,
            parallel=requested_parallel,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib_request.Request(
        build_load_probe_url(base_url),
        data=request_body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    effective_transport = transport or _default_transport

    try:
        response_bytes = effective_transport(request, request_timeout_s)
    except Exception as error:
        status, error_category, http_status = _categorize_transport_error(error)
        summary["status"] = status
        summary["error_category"] = error_category
        if http_status is not None:
            summary["http_status"] = http_status
        return LoadProbeResult(summary=summary)

    response_text = response_bytes.decode("utf-8", errors="replace")
    summary["response_hash"] = _sha256_text(response_text)
    summary["response_chars"] = len(response_text)

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        summary["status"] = "decode_error"
        summary["error_category"] = "json"
        return LoadProbeResult(summary=summary)

    if not isinstance(payload, Mapping):
        summary["status"] = "invalid_shape"
        summary["error_category"] = "unknown"
        return LoadProbeResult(summary=summary)

    context_candidates = sorted(_extract_candidate_values(payload, aliases=_CONTEXT_KEY_ALIASES))
    parallel_candidates = sorted(_extract_candidate_values(payload, aliases=_PARALLEL_KEY_ALIASES))
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

    sanitized_applied_config = _build_sanitized_applied_config(payload)
    if sanitized_applied_config:
        summary["sanitized_applied_config"] = sanitized_applied_config

    summary["status"] = "ok"
    summary["error_category"] = None
    return LoadProbeResult(summary=summary)


def render_load_probe_report(
    *,
    run_id: str,
    summary: Mapping[str, object],
    output_files: Sequence[str] = LOAD_PROBE_RESULT_FILE_NAMES,
) -> str:
    lines = [
        "# LM Studio Load Probe Report",
        "",
        "## Run",
        "",
        "- command: `probe-load`",
        f"- run_id: `{run_id}`",
        f"- endpoint_path: `{summary.get('endpoint_path')}`",
        f"- allow_remote: `{str(bool(summary.get('allow_remote'))).lower()}`",
        f"- is_localhost: `{str(bool(summary.get('is_localhost'))).lower()}`",
        f"- timeout_s: `{summary.get('timeout_s')}`",
        f"- model_id: `{summary.get('model_id')}`",
        f"- requested_context_length: `{summary.get('requested_context_length')}`",
        f"- requested_parallel: `{summary.get('requested_parallel')}`",
        "",
        "## Result",
        "",
        f"- status: `{summary.get('status')}`",
        f"- error_category: `{summary.get('error_category')}`",
    ]
    if summary.get("http_status") is not None:
        lines.append(f"- http_status: `{summary.get('http_status')}`")
    if summary.get("response_hash") is not None:
        lines.append(f"- response_hash: `{summary.get('response_hash')}`")
    if summary.get("response_chars") is not None:
        lines.append(f"- response_chars: `{summary.get('response_chars')}`")
    if summary.get("resolved_native_load_id_hash") is not None:
        lines.append(
            f"- resolved_native_load_id_hash: `{summary.get('resolved_native_load_id_hash')}`"
        )
    for field_name in (
        "target_found_compat",
        "target_found_native",
        "target_hash_match",
        "native_load_id_resolved",
        "identity_status",
        "identity_error_category",
        "applied_context_length",
        "applied_context_length_candidates",
        "applied_parallel",
        "applied_parallel_candidates",
        "context_length_verified",
        "parallel_verified",
    ):
        if field_name in summary:
            lines.append(f"- {field_name}: `{summary.get(field_name)}`")

    lines.extend(
        [
            "",
            "## Privacy",
            "",
            "- raw response body: not stored",
            "- raw base URL: not stored",
            "- model list/chat/generate/unload/download endpoints: not used",
            "- paths/urls/provider body/secrets/messages/content: stripped",
            "",
            "## Output Files",
            "",
            *(f"- `{file_name}`" for file_name in output_files),
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "LOAD_PROBE_ENDPOINT_PATH",
    "LOAD_PROBE_RESULT_FILE_NAMES",
    "LoadProbeResult",
    "LoadProbeTransport",
    "build_load_probe_url",
    "is_local_load_probe_base_url",
    "probe_lmstudio_load",
    "render_load_probe_report",
    "validate_load_probe_model_id",
]
