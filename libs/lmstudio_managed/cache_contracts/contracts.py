"""Pure cache/stateful experiment contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ContextReuseMode(StrEnum):
    STATEFUL_ROOT_BRANCH = "stateful_root_branch"
    STATELESS_FULL_PREFIX = "stateless_full_prefix"
    COMPACT_MEMORY = "compact_memory"


class CacheMeasurementStatus(StrEnum):
    NOT_MEASURED_NO_LIVE = "not_measured_no_live"
    FUNCTIONAL_STATEFUL_OK = "functional_stateful_ok"
    INCONCLUSIVE = "inconclusive"


class CacheReuseVerdict(StrEnum):
    KV_REUSE_UNPROVEN = "kv_reuse_unproven"
    KV_REUSE_LIKELY = "kv_reuse_likely"
    KV_REUSE_PROVEN = "kv_reuse_proven"
    LATENCY_CANDIDATE = "latency_candidate"
    CACHE_PROXY_SIGNAL = "cache_proxy_signal"
    NO_REUSE_DETECTED = "no_reuse_detected"
    INCONCLUSIVE = "inconclusive"


class ResponsesCacheProbeStatus(StrEnum):
    RESPONSES_UNSUPPORTED = "responses_unsupported"
    RESPONSES_USABLE_NO_CACHE = "responses_usable_no_cache"
    RESPONSES_USABLE_NO_CACHE_AT_16K = "responses_usable_no_cache_at_16k"
    RESPONSES_CACHE_SIGNAL_PRESENT = "responses_cache_signal_present"
    RESPONSES_CACHE_ACCOUNTING_CANDIDATE = "responses_cache_accounting_candidate"
    RESPONSES_CACHE_ACCOUNTING_CANDIDATE_16K = "responses_cache_accounting_candidate_16k"
    RESPONSES_BLOCKED = "responses_blocked"


@dataclass(frozen=True, slots=True)
class ResponsesUsageSummary:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cached_tokens_available: bool = False
    raw_usage_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StatefulRootRequest:
    request_id: str
    model_key: str
    dataset_id: str
    root_context_hash: str
    estimated_input_tokens: int
    context_window: int
    mode: ContextReuseMode = ContextReuseMode.STATEFUL_ROOT_BRANCH
    raw_material_stored: bool = False


@dataclass(frozen=True, slots=True)
class StatefulBranchRequest:
    request_id: str
    root_request_id: str
    branch_id: str
    root_context_hash: str
    estimated_branch_tokens: int
    mode: ContextReuseMode = ContextReuseMode.STATEFUL_ROOT_BRANCH
    raw_material_stored: bool = False


@dataclass(frozen=True, slots=True)
class StatelessPrefixRequest:
    request_id: str
    branch_id: str
    prefix_context_hash: str
    estimated_input_tokens: int
    mode: ContextReuseMode = ContextReuseMode.STATELESS_FULL_PREFIX
    raw_material_stored: bool = False


@dataclass(frozen=True, slots=True)
class CompactMemoryRequest:
    request_id: str
    branch_id: str
    memory_hash: str
    estimated_memory_tokens: int
    estimated_branch_tokens: int
    mode: ContextReuseMode = ContextReuseMode.COMPACT_MEMORY
    raw_material_stored: bool = False


@dataclass(frozen=True, slots=True)
class CacheExperimentPlan:
    experiment_id: str
    model_key: str
    context_window: int
    root_request: StatefulRootRequest
    stateful_branch_requests: tuple[StatefulBranchRequest, ...] = ()
    stateless_prefix_requests: tuple[StatelessPrefixRequest, ...] = ()
    compact_memory_requests: tuple[CompactMemoryRequest, ...] = ()
    production_default: bool = False
    raw_material_stored: bool = False

    @property
    def planned_request_count(self) -> int:
        return (
            1
            + len(self.stateful_branch_requests)
            + len(self.stateless_prefix_requests)
            + len(self.compact_memory_requests)
        )


@dataclass(frozen=True, slots=True)
class CacheEvidence:
    experiment_id: str
    model_key: str
    measurement_status: CacheMeasurementStatus = CacheMeasurementStatus.NOT_MEASURED_NO_LIVE
    reuse_verdict: CacheReuseVerdict = CacheReuseVerdict.KV_REUSE_UNPROVEN
    successful_branch_count: int = 0
    ttft_ms: float | None = None
    prompt_processing_ms: float | None = None
    total_latency_ms: float | None = None
    cached_tokens: int | None = None
    cache_proxy: float | None = None
    direct_cache_hit_signal: bool = False
    ram_peak_mb: float | None = None
    vram_peak_mb: float | None = None
    production_default: bool = False
    raw_material_stored: bool = False

    @property
    def kv_reuse_proven(self) -> bool:
        has_direct_telemetry = (self.cached_tokens or 0) > 0 or self.direct_cache_hit_signal
        return self.reuse_verdict == CacheReuseVerdict.KV_REUSE_PROVEN and has_direct_telemetry

    @property
    def has_live_measurements(self) -> bool:
        return any(
            metric is not None
            for metric in (
                self.ttft_ms,
                self.prompt_processing_ms,
                self.total_latency_ms,
                self.cached_tokens,
                self.cache_proxy,
                self.direct_cache_hit_signal if self.direct_cache_hit_signal else None,
                self.ram_peak_mb,
                self.vram_peak_mb,
            )
        )


def _mapping_or_none(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _coerce_int(value: object) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _collect_usage_keys(payload: Mapping[str, Any], *, prefix: str = "") -> tuple[str, ...]:
    keys: list[str] = []
    for raw_key, raw_value in payload.items():
        key = str(raw_key).strip()
        if not key:
            continue
        dotted_key = f"{prefix}.{key}" if prefix else key
        keys.append(dotted_key)
        nested_mapping = _mapping_or_none(raw_value)
        if nested_mapping is not None:
            keys.extend(_collect_usage_keys(nested_mapping, prefix=dotted_key))
    return tuple(keys)


def parse_responses_usage(payload: Mapping[str, Any] | None) -> ResponsesUsageSummary:
    response_payload = _mapping_or_none(payload)
    if response_payload is None:
        return ResponsesUsageSummary()

    usage_payload = _mapping_or_none(response_payload.get("usage"))
    if usage_payload is None:
        return ResponsesUsageSummary()

    input_tokens_details = _mapping_or_none(usage_payload.get("input_tokens_details"))
    cached_tokens = None
    if input_tokens_details is not None:
        cached_tokens = _coerce_int(input_tokens_details.get("cached_tokens"))

    return ResponsesUsageSummary(
        input_tokens=_coerce_int(usage_payload.get("input_tokens")),
        output_tokens=_coerce_int(usage_payload.get("output_tokens")),
        total_tokens=_coerce_int(usage_payload.get("total_tokens")),
        cached_tokens=cached_tokens,
        cached_tokens_available=cached_tokens is not None,
        raw_usage_keys=tuple(sorted(set(_collect_usage_keys(usage_payload)))),
    )
