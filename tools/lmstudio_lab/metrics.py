from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from lmstudio_managed.metrics import RequestMetrics
from lmstudio_managed.validation import failure_kind_from_lab_category

from .privacy import (
    REDACTED_VALUE,
    is_forbidden_metric_key,
    normalize_metric_key,
    sanitize_metric_payload,
)

SCHEMA_VERSION = "1.0"
SAFE_ERROR_CATEGORIES = (
    "api_error",
    "context_fit_failed",
    "http_error",
    "lmstudio_unavailable",
    "model_not_found",
    "timeout",
    "network",
    "model_not_loaded",
    "model_load_failed",
    "oom",
    "json",
    "schema",
    "business",
    "reasoning",
    "empty",
    "finish",
    "privacy_violation",
    "unknown",
)
_SAFE_ENVELOPE_BOOL_KEYS = ("content_empty", "reasoning_content_present")


class PhaseMarker(StrEnum):
    CLEAN_BASELINE = "clean_baseline"
    LOAD_STARTED = "load_started"
    LOADED_IDLE = "loaded_idle"
    REQUEST_DISPATCHED = "request_dispatched"
    PREFILL_ACTIVE = "prefill_active"
    FIRST_RESPONSE_UNIT = "first_token"
    DECODE_ACTIVE = "decode_active"
    CONCURRENT_PEAK = "concurrent_peak"
    BATCH_COMPLETED = "batch_completed"
    POST_BATCH_IDLE = "post_batch_idle"
    UNLOAD_STARTED = "unload_started"
    AFTER_UNLOAD_GLOBAL_ZERO = "after_unload_global_zero"


PHASE_MARKER_ORDER = tuple(PhaseMarker)


class PhaseDerivationMethod(StrEnum):
    DIRECT_EVENT = "direct_event"
    ATTRIBUTABLE_REQUEST_INTERVAL = "attributable_request_interval"
    UNAVAILABLE = "unavailable"


class PhaseConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class PhaseMarkerRecord:
    marker: PhaseMarker
    sequence: int
    derivation_method: PhaseDerivationMethod
    confidence: PhaseConfidence


def validate_phase_marker_order(records: Sequence[PhaseMarkerRecord]) -> bool:
    """Validate monotonic event and canonical phase ordering."""

    previous_sequence = -1
    previous_rank = -1
    for record in records:
        rank = PHASE_MARKER_ORDER.index(record.marker)
        if record.sequence <= previous_sequence or rank < previous_rank:
            return False
        previous_sequence = record.sequence
        previous_rank = rank
    return True


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(int(value))
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_error_category(value: Any) -> str | None:
    category = _coerce_str(value)
    if category is None:
        return None
    normalized = normalize_metric_key(category)
    if normalized in SAFE_ERROR_CATEGORIES:
        return normalized
    return "unknown"


def _restore_safe_envelope_booleans(
    *,
    original_payload: Mapping[str, Any],
    sanitized_payload: dict[str, Any],
) -> int:
    restored_redactions = 0
    for key in _SAFE_ENVELOPE_BOOL_KEYS:
        if key not in original_payload:
            continue
        value = original_payload.get(key)
        coerced = _coerce_bool(value)
        if coerced is not None or value is None:
            if sanitized_payload.get(key) == REDACTED_VALUE:
                restored_redactions += 1
            sanitized_payload[key] = coerced
    return restored_redactions


@dataclass(slots=True)
class ResponseFormatSummary:
    kind: str | None = None
    schema_name: str | None = None
    strict: bool | None = None

    @classmethod
    def from_mapping(cls, response_format: Mapping[str, Any] | None) -> ResponseFormatSummary:
        if not isinstance(response_format, Mapping):
            return cls()

        kind = _coerce_str(response_format.get("type"))
        if kind != "json_schema":
            return cls(kind=kind)

        json_schema = response_format.get("json_schema")
        if not isinstance(json_schema, Mapping):
            return cls(kind=kind)

        return cls(
            kind=kind,
            schema_name=_coerce_str(json_schema.get("name")),
            strict=_coerce_bool(json_schema.get("strict")),
        )


@dataclass(slots=True)
class LoadConfigSummary:
    context_length: int | None = None
    parallel: int | None = None
    eval_batch_size: int | None = None
    flash_attention: bool | None = None
    num_experts: int | None = None
    offload_kv_cache_to_gpu: bool | None = None
    other_field_names: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, load_config: Mapping[str, Any] | None) -> tuple[LoadConfigSummary, int]:
        if not isinstance(load_config, Mapping):
            return cls(), 0

        other_field_names: list[str] = []
        redaction_count = 0
        known_names = {
            "context_length",
            "parallel",
            "n_parallel",
            "eval_batch_size",
            "flash_attention",
            "num_experts",
            "offload_kv_cache_to_gpu",
        }

        for raw_key in load_config:
            normalized = normalize_metric_key(raw_key)
            if normalized in known_names:
                continue
            if normalized in other_field_names:
                continue
            if is_forbidden_metric_key(raw_key):
                redaction_count += 1
                continue
            other_field_names.append(normalized)

        return (
            cls(
                context_length=_coerce_int(load_config.get("context_length")),
                parallel=_coerce_int(load_config.get("parallel", load_config.get("n_parallel"))),
                eval_batch_size=_coerce_int(load_config.get("eval_batch_size")),
                flash_attention=_coerce_bool(load_config.get("flash_attention")),
                num_experts=_coerce_int(load_config.get("num_experts")),
                offload_kv_cache_to_gpu=_coerce_bool(load_config.get("offload_kv_cache_to_gpu")),
                other_field_names=tuple(sorted(other_field_names)),
            ),
            redaction_count,
        )


@dataclass(slots=True)
class TokenMetrics:
    estimated_input_tokens: int | None = None
    estimate_scope: str = "dataset_only"
    actual_input_tokens: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    total_output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    estimated_output_tokens: int | None = None
    actual_output_tokens: int | None = None


@dataclass(slots=True)
class TimingMetrics:
    total_elapsed_ms: float | None = None
    time_to_first_token_ms: float | None = None
    generation_time_ms: float | None = None
    tokens_per_second: float | None = None


@dataclass(slots=True)
class ValidationMetrics:
    json_parse_pass: bool | None = None
    schema_pass: bool | None = None
    business_pass: bool | None = None
    ids_exact_pass: bool | None = None
    no_duplicate_ids: bool | None = None
    order_preserved: bool | None = None
    non_empty_text_pass: bool | None = None
    reasoning_leak: bool | None = None
    retry_count: int | None = None
    finish_reason: str | None = None
    expected_count: int | None = None
    returned_count: int | None = None
    expected_ids: tuple[int, ...] | None = None
    returned_ids: tuple[int, ...] | None = None
    duplicate_ids: tuple[int, ...] | None = None
    missing_ids: tuple[int, ...] | None = None
    extra_ids: tuple[int, ...] | None = None
    reordered_positions: tuple[dict[str, int | None], ...] | None = None
    reordered_count: int | None = None
    reordered_positions_truncated: bool | None = None


@dataclass(slots=True)
class SystemMetrics:
    process_rss_mb: float | None = None
    gpu_name: str | None = None
    gpu_utilization_percent: float | None = None
    gpu_vram_used_mb: float | None = None
    gpu_vram_total_mb: float | None = None


@dataclass(slots=True)
class LMStudioLabMetricRecord:
    run_id: str
    schema_version: str = SCHEMA_VERSION
    experiment_id: str | None = None
    request_id: str | None = None
    dataset_id: str | None = None
    dataset_hash: str | None = None
    model_key: str | None = None
    model_id: str | None = None
    endpoint_kind: str | None = None
    mode: str | None = None
    timestamp_utc: str = field(default_factory=_utc_now_iso)
    requested_context_length: int | None = None
    requested_parallel: int | None = None
    app_concurrency: int | None = None
    configured_parallel: int | None = None
    applied_parallel: int | None = None
    parallel_verified: bool | None = None
    queue_pressure_mode: bool | None = None
    parallel_semantics: str | None = None
    structured_schema_variant: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    flash_attention: bool | None = None
    offload_kv_cache_to_gpu: bool | None = None
    eval_batch_size: int | None = None
    num_experts: int | None = None
    stop_count: int | None = None
    prompt_hash: str | None = None
    prompt_chars: int | None = None
    response_hash: str | None = None
    response_chars: int | None = None
    content_empty: bool | None = None
    reasoning_content_present: bool | None = None
    response_format: ResponseFormatSummary = field(default_factory=ResponseFormatSummary)
    applied_load_config: LoadConfigSummary = field(default_factory=LoadConfigSummary)
    tokens: TokenMetrics = field(default_factory=TokenMetrics)
    timing: TimingMetrics = field(default_factory=TimingMetrics)
    validation: ValidationMetrics = field(default_factory=ValidationMetrics)
    system: SystemMetrics = field(default_factory=SystemMetrics)
    error_category: str | None = None
    error_status: str | None = None
    privacy_redaction_count: int = 0

    @classmethod
    def from_parts(
        cls,
        *,
        response_format: Mapping[str, Any] | None = None,
        applied_load_config: Mapping[str, Any] | None = None,
        tokens: TokenMetrics | None = None,
        timing: TimingMetrics | None = None,
        validation: ValidationMetrics | None = None,
        system: SystemMetrics | None = None,
        **kwargs: Any,
    ) -> LMStudioLabMetricRecord:
        response_summary = ResponseFormatSummary.from_mapping(response_format)
        load_config_summary, load_config_redactions = LoadConfigSummary.from_mapping(
            applied_load_config
        )
        if "error_category" in kwargs:
            kwargs["error_category"] = _normalize_error_category(kwargs.get("error_category"))
        return cls(
            response_format=response_summary,
            applied_load_config=load_config_summary,
            tokens=tokens or TokenMetrics(),
            timing=timing or TimingMetrics(),
            validation=validation or ValidationMetrics(),
            system=system or SystemMetrics(),
            privacy_redaction_count=load_config_redactions,
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        sanitized_payload, extra_redactions = sanitize_metric_payload(payload)
        restored_redactions = _restore_safe_envelope_booleans(
            original_payload=payload,
            sanitized_payload=sanitized_payload,
        )
        extra_redactions = max(0, extra_redactions - restored_redactions)
        if extra_redactions:
            current_count = _coerce_int(sanitized_payload.get("privacy_redaction_count")) or 0
            sanitized_payload["privacy_redaction_count"] = current_count + extra_redactions
        return sanitized_payload

    def to_managed_request_metrics(self) -> RequestMetrics:
        finish_reason = self.validation.finish_reason
        return RequestMetrics(
            request_id=self.request_id or self.run_id,
            finish_reason=finish_reason,
            error_category=self.error_category,
            failure_kind=failure_kind_from_lab_category(
                self.error_category,
                content_empty=self.content_empty,
                reasoning_content_present=self.reasoning_content_present,
                finish_reason=finish_reason,
            ),
            prompt_tokens=self.tokens.prompt_tokens,
            completion_tokens=self.tokens.completion_tokens,
            total_tokens=self.tokens.total_tokens,
            total_elapsed_ms=self.timing.total_elapsed_ms,
            response_chars=self.response_chars,
            raw_prompt_response_stored=False,
        )


def append_jsonl_record(
    file_path: str | Path,
    payload: LMStudioLabMetricRecord | Mapping[str, Any],
) -> dict[str, Any]:
    """Append one privacy-safe JSON object per line."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(payload, LMStudioLabMetricRecord):
        serialized = payload.to_dict()
    else:
        serialized, redaction_count = sanitize_metric_payload(payload)
        restored_redactions = _restore_safe_envelope_booleans(
            original_payload=payload,
            sanitized_payload=serialized,
        )
        redaction_count = max(0, redaction_count - restored_redactions)
        if redaction_count:
            current_count = _coerce_int(serialized.get("privacy_redaction_count")) or 0
            serialized["privacy_redaction_count"] = current_count + redaction_count

    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(serialized, ensure_ascii=False, sort_keys=True))
        handle.write("\n")

    return serialized


__all__ = [
    "LMStudioLabMetricRecord",
    "LoadConfigSummary",
    "PHASE_MARKER_ORDER",
    "PhaseConfidence",
    "PhaseDerivationMethod",
    "PhaseMarker",
    "PhaseMarkerRecord",
    "ResponseFormatSummary",
    "SAFE_ERROR_CATEGORIES",
    "SCHEMA_VERSION",
    "SystemMetrics",
    "TimingMetrics",
    "TokenMetrics",
    "ValidationMetrics",
    "append_jsonl_record",
    "validate_phase_marker_order",
]
