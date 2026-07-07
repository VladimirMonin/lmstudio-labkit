from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED_VALUE = "[REDACTED]"

_SAFE_KEY_ALLOWLIST = frozenset(
    {
        "actual_input_tokens",
        "actual_output_tokens",
        "applied_load_config",
        "average_prompt_processing_ms_by_mode",
        "allow_real_user_content",
        "completion_tokens",
        "content_hash",
        "content_nonempty",
        "dataset_hash",
        "dataset_id",
        "endpoint_family",
        "error_type",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "empty_text_count",
        "endpoint_path",
        "branch_material_hash",
        "branch_prompt_hash",
        "cache_hit_ratio",
        "cached_tokens",
        "cached_tokens_available",
        "cached_tokens_observed",
        "finish_status",
        "hash_response_id",
        "inference_endpoint_called",
        "input_chars",
        "input_hash",
        "input_tokens",
        "kv_reuse_proven",
        "live_25k_authorized",
        "lmstudio_version",
        "max_context_tokens",
        "max_output_tokens",
        "max_output_tokens_branch",
        "max_output_tokens_root",
        "model_id",
        "material_hash",
        "non_empty_text_pass",
        "normalized_text_length",
        "output_tokens",
        "previous_response_id_hash",
        "previous_response_id_supported",
        "previous_response_id_used",
        "production_default",
        "privacy_redaction_count",
        "prompt_processing_ms",
        "prompt_processing_available",
        "prompt_processing_events_seen",
        "prompt_chars",
        "prompt_hash",
        "prompt_tokens",
        "raw_usage_keys",
        "request_id",
        "request_role",
        "repeat_index",
        "repeat_phase",
        "reasoning_output_tokens",
        "response_chars",
        "response_hash",
        "response_id_hash",
        "response_id_present",
        "response_format",
        "response_format_kind",
        "response_format_schema_name",
        "response_format_strict",
        "responses_cache_probe_status",
        "root_material_hash",
        "root_prompt_hash",
        "raw_prompt_response_stored",
        "run_id",
        "sequence_index",
        "store_raw_prompt_response",
        "store_prompt_hash",
        "store_prompt_text",
        "store_response_id_raw",
        "store_response_text",
        "structured_prompt_variant",
        "structured_schema_variant",
        "structured_reasoning_control_variant",
        "stateful_branch_avg_prompt_processing_ms",
        "stateless_full_prefix_branch_avg_prompt_processing_ms",
        "compact_memory_branch_avg_prompt_processing_ms",
        "text_length",
        "total_latency_ms",
        "total_prompt_tokens",
        "total_output_tokens",
        "total_tokens",
        "wvm_runtime_integration",
    }
)
_SAFE_URL_VALUE_KEYS = frozenset({"lmstudio_base_url"})
_FORBIDDEN_EXACT_KEYS = frozenset(
    {
        "api_token",
        "api_key",
        "authorization",
        "bearer",
        "body",
        "content",
        "cmdline",
        "cwd",
        "error",
        "errors",
        "env",
        "file_path",
        "instance_id",
        "job_id",
        "message",
        "messages",
        "path",
        "prompt",
        "provider_body",
        "raw_body",
        "raw_response",
        "request_body",
        "response",
        "response_body",
        "secret",
        "text",
        "token",
        "transcript",
        "url",
        "username",
    }
)
_FORBIDDEN_KEY_SEGMENTS = frozenset(
    {
        "content",
        "message",
        "messages",
        "path",
        "prompt",
        "response",
        "text",
        "transcript",
    }
)
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_CAMELCASE_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_PASCALCASE_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_WINDOWS_PATH_SEGMENT_RE = r'[^\\/:*?"<>|\r\n ](?:[^\\/:*?"<>|\r\n]*[^\\/:*?"<>|\r\n ])?'
_POSIX_PATH_SEGMENT_RE = r"[^/\r\n \"'](?:[^/\r\n\"']*[^/\r\n \"'])?"
_WINDOWS_DRIVE_PATH_RE = re.compile(
    rf"(?i)[A-Z]:[\\/](?:{_WINDOWS_PATH_SEGMENT_RE}[\\/])*{_WINDOWS_PATH_SEGMENT_RE}"
)
_WINDOWS_UNC_PATH_RE = re.compile(
    rf"\\\\{_WINDOWS_PATH_SEGMENT_RE}[\\/]{_WINDOWS_PATH_SEGMENT_RE}(?:[\\/]{_WINDOWS_PATH_SEGMENT_RE})*"
)
_POSIX_HOME_PATH_RE = re.compile(
    rf"/(?:Users|home)/{_POSIX_PATH_SEGMENT_RE}(?:/{_POSIX_PATH_SEGMENT_RE})+"
)
_HTTP_URL_RE = re.compile(r"https?://[^\s\"']+")


def normalize_metric_key(key: object) -> str:
    """Return a lowercase underscore metric key shape."""
    text = str(key).strip()
    text = _PASCALCASE_BOUNDARY_RE.sub(r"\1_\2", text)
    text = _CAMELCASE_BOUNDARY_RE.sub(r"\1_\2", text)
    text = text.lower()
    normalized = _NORMALIZE_RE.sub("_", text).strip("_")
    return normalized or "unnamed"


def is_forbidden_metric_key(key: object) -> bool:
    """Return True when a metric key looks like raw user/provider content."""
    normalized = normalize_metric_key(key)
    if normalized in _SAFE_KEY_ALLOWLIST:
        return False
    if normalized in _FORBIDDEN_EXACT_KEYS:
        return True
    segments = [segment for segment in normalized.split("_") if segment]
    return any(segment in _FORBIDDEN_KEY_SEGMENTS for segment in segments)


def _sanitize_string_value(value: str) -> tuple[str, int]:
    if value == REDACTED_VALUE:
        return value, 0

    sanitized_value = value
    redaction_count = 0
    for pattern in (
        _HTTP_URL_RE,
        _WINDOWS_DRIVE_PATH_RE,
        _WINDOWS_UNC_PATH_RE,
        _POSIX_HOME_PATH_RE,
    ):
        matches = list(pattern.finditer(sanitized_value))
        if not matches:
            continue
        redaction_count += len(matches)
        sanitized_value = pattern.sub(REDACTED_VALUE, sanitized_value)
    return sanitized_value, redaction_count


def _contains_absolute_path(value: str) -> bool:
    return any(
        pattern.search(value)
        for pattern in (
            _WINDOWS_DRIVE_PATH_RE,
            _WINDOWS_UNC_PATH_RE,
            _POSIX_HOME_PATH_RE,
        )
    )


def sanitize_metric_value(value: Any) -> tuple[Any, int]:
    """Redact forbidden metric values recursively."""

    if isinstance(value, Mapping):
        sanitized_mapping: dict[str, Any] = {}
        redaction_count = 0
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if is_forbidden_metric_key(key):
                sanitized_mapping[key] = REDACTED_VALUE
                if raw_value != REDACTED_VALUE:
                    redaction_count += 1
                continue
            sanitized_value, nested_redactions = sanitize_metric_value(raw_value)
            sanitized_mapping[key] = sanitized_value
            redaction_count += nested_redactions
        return sanitized_mapping, redaction_count

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        sanitized_items = []
        redaction_count = 0
        for item in value:
            sanitized_item, nested_redactions = sanitize_metric_value(item)
            sanitized_items.append(sanitized_item)
            redaction_count += nested_redactions
        return sanitized_items, redaction_count

    if isinstance(value, str):
        return _sanitize_string_value(value)

    return value, 0


def sanitize_metric_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """Redact forbidden metric values recursively."""

    sanitized_payload, redaction_count = sanitize_metric_value(dict(payload))
    return sanitized_payload, redaction_count


def find_privacy_violations(payload: Any, *, context: str = "payload") -> tuple[str, ...]:
    """Return privacy violations without mutating the original payload."""

    violations: list[str] = []

    def _walk(value: Any, path: str, current_key: object | None = None) -> None:
        if isinstance(value, Mapping):
            for raw_key, raw_value in value.items():
                key = str(raw_key)
                next_path = f"{path}.{key}" if path else key
                if is_forbidden_metric_key(key):
                    violations.append(f"{next_path} uses a forbidden private field")
                _walk(raw_value, next_path, key)
            return

        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, item in enumerate(value):
                _walk(item, f"{path}[{index}]", current_key)
            return

        if isinstance(value, str):
            normalized_key = normalize_metric_key(current_key) if current_key is not None else ""
            if _HTTP_URL_RE.search(value) and normalized_key not in _SAFE_URL_VALUE_KEYS:
                violations.append(f"{path} contains a raw URL")
            if _contains_absolute_path(value):
                violations.append(f"{path} contains an absolute path")

    _walk(payload, context)
    return tuple(violations)
