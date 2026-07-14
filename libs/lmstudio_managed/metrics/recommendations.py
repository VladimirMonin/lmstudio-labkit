"""Reusable GPU memory recommendation contracts and conservative status policy."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .models import GpuTelemetryEvidenceLevel

MEMORY_RECOMMENDATION_CATALOG_SCHEMA_REVISION = "model-memory-recommendation-catalog.v1"


class MemoryRecommendationStatus(StrEnum):
    APPROVED = "approved"
    MANUAL_ONLY = "manual_only"
    REJECTED = "rejected"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class SafetyReservePolicy:
    policy_id: str = "candidate-10pct-or-512mb"
    percent: float = 0.10
    absolute_floor_mb: float = 512.0

    def __post_init__(self) -> None:
        _require_text(self.policy_id, "policy_id")
        if not math.isfinite(self.percent) or self.percent < 0:
            raise ValueError("percent must be a finite non-negative number")
        if not math.isfinite(self.absolute_floor_mb) or self.absolute_floor_mb < 0:
            raise ValueError("absolute_floor_mb must be a finite non-negative number")

    def reserve_for(self, measured_peak_vram_mb: float) -> float:
        return round(max(self.absolute_floor_mb, measured_peak_vram_mb * self.percent), 3)


@dataclass(frozen=True, slots=True)
class MemoryCellObservation:
    attempt_id: str
    model_artifact: str
    artifact_revision: str
    artifact_checksum: str
    quantization: str
    context_tokens: int
    runtime_parallel: int
    application_concurrency: int
    workload_class: str
    placement_requirement: str
    kv_placement: str
    telemetry_evidence: GpuTelemetryEvidenceLevel
    clean_baseline_vram_mb: float | None
    loaded_idle_vram_mb: float | None
    measured_peak_vram_mb: float | None
    identity_verified: bool
    runtime_shape_verified: bool
    telemetry_valid: bool
    operation_succeeded: bool
    response_integrity_passed: bool
    cleanup_global_zero_passed: bool
    placement_observed: bool
    capacity_fit: bool
    thrash_observed: bool
    overlap_proven: bool
    phase_evidence_valid: bool
    independent_cycle_proven: bool
    immutable_owner_evidence_bound: bool

    def __post_init__(self) -> None:
        for field_name in (
            "attempt_id",
            "model_artifact",
            "artifact_revision",
            "artifact_checksum",
            "quantization",
            "workload_class",
            "placement_requirement",
            "kv_placement",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_sha256(self.artifact_checksum, "artifact_checksum")
        for field_name in ("context_tokens", "runtime_parallel", "application_concurrency"):
            value = getattr(self, field_name)
            minimum = 0 if field_name == "application_concurrency" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field_name} must be an integer >= {minimum}")
        for field_name in (
            "clean_baseline_vram_mb",
            "loaded_idle_vram_mb",
            "measured_peak_vram_mb",
        ):
            value = getattr(self, field_name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{field_name} must be null or a finite non-negative number")
        values = (
            self.clean_baseline_vram_mb,
            self.loaded_idle_vram_mb,
            self.measured_peak_vram_mb,
        )
        if all(value is not None for value in values):
            baseline, loaded, peak = values
            if not baseline <= loaded <= peak:  # type: ignore[operator]
                raise ValueError(
                    "VRAM observations must satisfy clean_baseline <= loaded_idle <= peak"
                )
        for field_name in (
            "identity_verified",
            "runtime_shape_verified",
            "telemetry_valid",
            "operation_succeeded",
            "response_integrity_passed",
            "cleanup_global_zero_passed",
            "placement_observed",
            "capacity_fit",
            "thrash_observed",
            "overlap_proven",
            "phase_evidence_valid",
            "independent_cycle_proven",
            "immutable_owner_evidence_bound",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")

    def cell_identity(self) -> tuple[object, ...]:
        return (
            self.model_artifact,
            self.artifact_revision,
            self.artifact_checksum,
            self.quantization,
            self.context_tokens,
            self.runtime_parallel,
            self.application_concurrency,
            self.workload_class,
            self.placement_requirement,
            self.kv_placement,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MemoryRecommendation:
    model_artifact: str
    artifact_revision: str
    artifact_checksum: str
    quantization: str
    context_tokens: int
    runtime_parallel: int
    application_concurrency: int
    workload_class: str
    placement_requirement: str
    kv_placement: str
    measured_peak_vram_mb: float | None
    fixed_model_cost_vram_mb: float | None
    context_concurrency_overhead_vram_mb: float | None
    safety_reserve_policy: str
    safety_reserve_vram_mb: float | None
    recommended_vram_mb: float | None
    telemetry_evidence: GpuTelemetryEvidenceLevel
    evidence_revision: str
    repeat_count: int
    required_repeats: int
    status: MemoryRecommendationStatus
    status_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["telemetry_evidence"] = self.telemetry_evidence.value
        payload["status"] = self.status.value
        payload["status_reasons"] = list(self.status_reasons)
        return payload


@dataclass(frozen=True, slots=True)
class MemoryRecommendationCatalog:
    recommendations: tuple[MemoryRecommendation, ...]
    schema_revision: str = MEMORY_RECOMMENDATION_CATALOG_SCHEMA_REVISION

    def __post_init__(self) -> None:
        if self.schema_revision != MEMORY_RECOMMENDATION_CATALOG_SCHEMA_REVISION:
            raise ValueError("unsupported recommendation catalog schema revision")
        identities = tuple(_recommendation_sort_key(row) for row in self.recommendations)
        if len(set(identities)) != len(identities):
            raise ValueError("recommendation catalog contains duplicate cell identities")
        if identities != tuple(sorted(identities)):
            raise ValueError("recommendation catalog rows must be sorted by exact cell identity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "recommendations": [row.to_dict() for row in self.recommendations],
        }

    @classmethod
    def validate_payload(cls, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("catalog payload must be an object")
        if set(payload) != {"schema_revision", "recommendations"}:
            raise ValueError("catalog top-level fields do not match the versioned schema")
        if payload.get("schema_revision") != MEMORY_RECOMMENDATION_CATALOG_SCHEMA_REVISION:
            raise ValueError("catalog schema_revision mismatch")
        rows = payload.get("recommendations")
        if not isinstance(rows, list):
            raise ValueError("catalog recommendations must be an array")
        required = set(_CATALOG_ROW_FIELDS)
        identities: list[tuple[object, ...]] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != required:
                raise ValueError("catalog row fields do not match the versioned schema")
            _validate_catalog_row(row)
            identities.append(_catalog_payload_sort_key(row))
        if len(set(identities)) != len(identities):
            raise ValueError("recommendation catalog contains duplicate cell identities")
        if identities != sorted(identities):
            raise ValueError("recommendation catalog rows must be sorted by exact cell identity")


_CATALOG_ROW_FIELDS = (
    "model_artifact",
    "artifact_revision",
    "artifact_checksum",
    "quantization",
    "context_tokens",
    "runtime_parallel",
    "application_concurrency",
    "workload_class",
    "placement_requirement",
    "kv_placement",
    "measured_peak_vram_mb",
    "fixed_model_cost_vram_mb",
    "context_concurrency_overhead_vram_mb",
    "safety_reserve_policy",
    "safety_reserve_vram_mb",
    "recommended_vram_mb",
    "telemetry_evidence",
    "evidence_revision",
    "repeat_count",
    "required_repeats",
    "status",
    "status_reasons",
)


def build_memory_recommendation(
    observations: tuple[MemoryCellObservation, ...],
    *,
    required_repeats: int = 3,
    reserve_policy: SafetyReservePolicy | None = None,
) -> MemoryRecommendation:
    if not observations:
        raise ValueError("observations must not be empty")
    if (
        isinstance(required_repeats, bool)
        or not isinstance(required_repeats, int)
        or required_repeats < 3
    ):
        raise ValueError("required_repeats must be an integer >= 3")
    if len({row.attempt_id for row in observations}) != len(observations):
        raise ValueError("attempt_id values must be unique")
    identity = observations[0].cell_identity()
    if any(row.cell_identity() != identity for row in observations[1:]):
        raise ValueError("all observations must describe one exact recommendation cell")

    policy = reserve_policy or SafetyReservePolicy()
    peaks = _complete_metric_values(observations, "measured_peak_vram_mb")
    fixed_costs = _derived_values(
        observations,
        left="loaded_idle_vram_mb",
        right="clean_baseline_vram_mb",
    )
    active_overheads = _derived_values(
        observations,
        left="measured_peak_vram_mb",
        right="loaded_idle_vram_mb",
    )
    measured_peak = max(peaks) if peaks is not None else None
    fixed_cost = max(fixed_costs) if fixed_costs is not None else None
    active_overhead = max(active_overheads) if active_overheads is not None else None
    safety_reserve = policy.reserve_for(measured_peak) if measured_peak is not None else None
    recommended = (
        round(measured_peak + safety_reserve, 3)
        if measured_peak is not None and safety_reserve is not None
        else None
    )
    telemetry_evidence = min(
        (row.telemetry_evidence for row in observations),
        key=_telemetry_rank,
    )
    status, reasons = _classify_recommendation_status(
        observations,
        required_repeats=required_repeats,
        complete_metrics=peaks is not None
        and fixed_costs is not None
        and active_overheads is not None,
        telemetry_evidence=telemetry_evidence,
    )
    first = observations[0]
    return MemoryRecommendation(
        model_artifact=first.model_artifact,
        artifact_revision=first.artifact_revision,
        artifact_checksum=first.artifact_checksum,
        quantization=first.quantization,
        context_tokens=first.context_tokens,
        runtime_parallel=first.runtime_parallel,
        application_concurrency=first.application_concurrency,
        workload_class=first.workload_class,
        placement_requirement=first.placement_requirement,
        kv_placement=first.kv_placement,
        measured_peak_vram_mb=measured_peak,
        fixed_model_cost_vram_mb=fixed_cost,
        context_concurrency_overhead_vram_mb=active_overhead,
        safety_reserve_policy=policy.policy_id,
        safety_reserve_vram_mb=safety_reserve,
        recommended_vram_mb=recommended,
        telemetry_evidence=telemetry_evidence,
        evidence_revision=_evidence_revision(observations),
        repeat_count=len(observations),
        required_repeats=required_repeats,
        status=status,
        status_reasons=reasons,
    )


def memory_recommendation_catalog_schema() -> dict[str, Any]:
    nullable_number = {"type": ["number", "null"], "minimum": 0}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": MEMORY_RECOMMENDATION_CATALOG_SCHEMA_REVISION,
        "title": "LM Studio model memory recommendation catalog",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_revision", "recommendations"],
        "properties": {
            "schema_revision": {"const": MEMORY_RECOMMENDATION_CATALOG_SCHEMA_REVISION},
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(_CATALOG_ROW_FIELDS),
                    "properties": {
                        "model_artifact": {"type": "string", "minLength": 1},
                        "artifact_revision": {"type": "string", "minLength": 1},
                        "artifact_checksum": {
                            "type": "string",
                            "pattern": "^sha256:[0-9a-fA-F]{64}$",
                        },
                        "quantization": {"type": "string", "minLength": 1},
                        "context_tokens": {"type": "integer", "minimum": 1},
                        "runtime_parallel": {"type": "integer", "minimum": 1},
                        "application_concurrency": {"type": "integer", "minimum": 0},
                        "workload_class": {"type": "string", "minLength": 1},
                        "placement_requirement": {"type": "string", "minLength": 1},
                        "kv_placement": {"type": "string", "minLength": 1},
                        "measured_peak_vram_mb": nullable_number,
                        "fixed_model_cost_vram_mb": nullable_number,
                        "context_concurrency_overhead_vram_mb": nullable_number,
                        "safety_reserve_policy": {"type": "string", "minLength": 1},
                        "safety_reserve_vram_mb": nullable_number,
                        "recommended_vram_mb": nullable_number,
                        "telemetry_evidence": {
                            "enum": [level.value for level in GpuTelemetryEvidenceLevel]
                        },
                        "evidence_revision": {
                            "type": "string",
                            "pattern": "^sha256:[0-9a-fA-F]{64}$",
                        },
                        "repeat_count": {"type": "integer", "minimum": 1},
                        "required_repeats": {"type": "integer", "minimum": 3},
                        "status": {"enum": [status.value for status in MemoryRecommendationStatus]},
                        "status_reasons": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        },
    }


def _classify_recommendation_status(
    observations: tuple[MemoryCellObservation, ...],
    *,
    required_repeats: int,
    complete_metrics: bool,
    telemetry_evidence: GpuTelemetryEvidenceLevel,
) -> tuple[MemoryRecommendationStatus, tuple[str, ...]]:
    rejection_reasons: list[str] = []
    if any(not row.operation_succeeded for row in observations):
        rejection_reasons.append("runtime_failure_observed")
    if any(not row.capacity_fit for row in observations):
        rejection_reasons.append("capacity_reserve_does_not_fit")
    if any(row.thrash_observed for row in observations):
        rejection_reasons.append("memory_thrash_observed")
    if any(not row.response_integrity_passed for row in observations):
        rejection_reasons.append("response_integrity_failed")
    if any(not row.cleanup_global_zero_passed for row in observations):
        rejection_reasons.append("cleanup_global_zero_failed")
    if rejection_reasons:
        return MemoryRecommendationStatus.REJECTED, tuple(rejection_reasons)

    insufficient_reasons: list[str] = []
    if len(observations) < required_repeats:
        insufficient_reasons.append("required_repeats_incomplete")
    if not complete_metrics:
        insufficient_reasons.append("memory_metrics_incomplete")
    if any(not row.identity_verified for row in observations):
        insufficient_reasons.append("exact_identity_unverified")
    if any(not row.runtime_shape_verified for row in observations):
        insufficient_reasons.append("runtime_shape_unverified")
    if any(not row.telemetry_valid for row in observations):
        insufficient_reasons.append("telemetry_invalid")
    if any(not row.overlap_proven for row in observations):
        insufficient_reasons.append("application_overlap_unproven")
    if any(not row.phase_evidence_valid for row in observations):
        insufficient_reasons.append("phase_evidence_invalid")
    if any(not row.independent_cycle_proven for row in observations):
        insufficient_reasons.append("independent_cycle_unproven")
    if any(not row.immutable_owner_evidence_bound for row in observations):
        insufficient_reasons.append("immutable_owner_evidence_unbound")
    if telemetry_evidence is GpuTelemetryEvidenceLevel.UNAVAILABLE:
        insufficient_reasons.append("telemetry_unavailable")
    if insufficient_reasons:
        return MemoryRecommendationStatus.INSUFFICIENT_EVIDENCE, tuple(insufficient_reasons)

    manual_reasons: list[str] = []
    if telemetry_evidence is not GpuTelemetryEvidenceLevel.NVML_PROCESS_ATTRIBUTED:
        manual_reasons.append("process_attribution_unproven")
    if any(not row.placement_observed for row in observations):
        manual_reasons.append("physical_placement_unproven")
    if manual_reasons:
        return MemoryRecommendationStatus.MANUAL_ONLY, tuple(manual_reasons)
    return MemoryRecommendationStatus.APPROVED, ("all_approval_gates_passed",)


def _complete_metric_values(
    observations: tuple[MemoryCellObservation, ...], field_name: str
) -> tuple[float, ...] | None:
    values = tuple(getattr(row, field_name) for row in observations)
    if any(value is None for value in values):
        return None
    return tuple(float(value) for value in values if value is not None)


def _derived_values(
    observations: tuple[MemoryCellObservation, ...], *, left: str, right: str
) -> tuple[float, ...] | None:
    left_values = _complete_metric_values(observations, left)
    right_values = _complete_metric_values(observations, right)
    if left_values is None or right_values is None:
        return None
    return tuple(
        round(left_value - right_value, 3)
        for left_value, right_value in zip(left_values, right_values, strict=True)
    )


def _evidence_revision(observations: tuple[MemoryCellObservation, ...]) -> str:
    rows = sorted((row.to_dict() for row in observations), key=lambda row: str(row["attempt_id"]))
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _telemetry_rank(level: GpuTelemetryEvidenceLevel) -> int:
    return {
        GpuTelemetryEvidenceLevel.UNAVAILABLE: 0,
        GpuTelemetryEvidenceLevel.NVIDIA_SMI_DEVICE_ONLY: 1,
        GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY: 2,
        GpuTelemetryEvidenceLevel.NVML_PROCESS_ATTRIBUTED: 3,
    }[level]


def _recommendation_sort_key(row: MemoryRecommendation) -> tuple[object, ...]:
    return (
        row.model_artifact,
        row.artifact_revision,
        row.artifact_checksum,
        row.quantization,
        row.context_tokens,
        row.runtime_parallel,
        row.application_concurrency,
        row.workload_class,
        row.placement_requirement,
        row.kv_placement,
    )


def _catalog_payload_sort_key(row: dict[str, Any]) -> tuple[object, ...]:
    return tuple(
        row[field_name]
        for field_name in (
            "model_artifact",
            "artifact_revision",
            "artifact_checksum",
            "quantization",
            "context_tokens",
            "runtime_parallel",
            "application_concurrency",
            "workload_class",
            "placement_requirement",
            "kv_placement",
        )
    )


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_sha256(value: object, field_name: str) -> None:
    _require_text(value, field_name)
    assert isinstance(value, str)
    digest = value.removeprefix("sha256:")
    if (
        not value.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in digest)
    ):
        raise ValueError(f"{field_name} must be a complete sha256 digest")


def _validate_catalog_row(row: dict[str, Any]) -> None:
    for field_name in (
        "model_artifact",
        "artifact_revision",
        "artifact_checksum",
        "quantization",
        "workload_class",
        "placement_requirement",
        "kv_placement",
        "safety_reserve_policy",
        "evidence_revision",
    ):
        _require_text(row[field_name], field_name)
    _require_sha256(row["artifact_checksum"], "artifact_checksum")
    _require_sha256(row["evidence_revision"], "evidence_revision")
    for field_name, minimum in (
        ("context_tokens", 1),
        ("runtime_parallel", 1),
        ("application_concurrency", 0),
        ("repeat_count", 1),
        ("required_repeats", 3),
    ):
        value = row[field_name]
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{field_name} must be an integer >= {minimum}")
    for field_name in (
        "measured_peak_vram_mb",
        "fixed_model_cost_vram_mb",
        "context_concurrency_overhead_vram_mb",
        "safety_reserve_vram_mb",
        "recommended_vram_mb",
    ):
        value = row[field_name]
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{field_name} must be null or a finite non-negative number")
    if row["status"] not in set(MemoryRecommendationStatus):
        raise ValueError("invalid recommendation status")
    if row["telemetry_evidence"] not in set(GpuTelemetryEvidenceLevel):
        raise ValueError("invalid telemetry evidence level")
    if (
        not isinstance(row["status_reasons"], list)
        or not row["status_reasons"]
        or not all(isinstance(reason, str) and reason for reason in row["status_reasons"])
    ):
        raise ValueError("status_reasons must be a non-empty string array")
    _validate_catalog_status_semantics(row)


_APPROVED_REASON = "all_approval_gates_passed"
_MANUAL_REASONS = frozenset(
    {
        "process_attribution_unproven",
        "physical_placement_unproven",
    }
)
_INSUFFICIENT_REASONS = frozenset(
    {
        "required_repeats_incomplete",
        "memory_metrics_incomplete",
        "exact_identity_unverified",
        "runtime_shape_unverified",
        "telemetry_invalid",
        "telemetry_unavailable",
        "application_overlap_unproven",
        "phase_evidence_invalid",
        "independent_cycle_unproven",
        "immutable_owner_evidence_unbound",
    }
)
_REJECTED_REASONS = frozenset(
    {
        "runtime_failure_observed",
        "capacity_reserve_does_not_fit",
        "memory_thrash_observed",
        "response_integrity_failed",
        "cleanup_global_zero_failed",
    }
)
_MEMORY_VALUE_FIELDS = (
    "measured_peak_vram_mb",
    "fixed_model_cost_vram_mb",
    "context_concurrency_overhead_vram_mb",
    "safety_reserve_vram_mb",
    "recommended_vram_mb",
)


def _validate_catalog_status_semantics(row: dict[str, Any]) -> None:
    status = MemoryRecommendationStatus(row["status"])
    reasons = tuple(row["status_reasons"])
    reason_set = set(reasons)
    repeats_complete = row["repeat_count"] >= row["required_repeats"]
    metrics_complete = all(row[field_name] is not None for field_name in _MEMORY_VALUE_FIELDS)
    evidence = GpuTelemetryEvidenceLevel(row["telemetry_evidence"])

    if status is MemoryRecommendationStatus.APPROVED:
        if (
            reasons != (_APPROVED_REASON,)
            or not repeats_complete
            or not metrics_complete
            or evidence is not GpuTelemetryEvidenceLevel.NVML_PROCESS_ATTRIBUTED
        ):
            raise ValueError("approved recommendation is inconsistent with its evidence fields")
        return

    if status is MemoryRecommendationStatus.MANUAL_ONLY:
        if (
            not reason_set <= _MANUAL_REASONS
            or not repeats_complete
            or not metrics_complete
            or evidence is GpuTelemetryEvidenceLevel.UNAVAILABLE
        ):
            raise ValueError("manual_only recommendation is inconsistent with its evidence fields")
        return

    if status is MemoryRecommendationStatus.REJECTED:
        if not reason_set <= _REJECTED_REASONS:
            raise ValueError("rejected recommendation contains an invalid status reason")
        return

    if not reason_set <= _INSUFFICIENT_REASONS:
        raise ValueError("insufficient_evidence recommendation contains an invalid status reason")
    if not repeats_complete and "required_repeats_incomplete" not in reason_set:
        raise ValueError("incomplete repeats require required_repeats_incomplete")
    if not metrics_complete and "memory_metrics_incomplete" not in reason_set:
        raise ValueError("incomplete metrics require memory_metrics_incomplete")
    if (
        evidence is GpuTelemetryEvidenceLevel.UNAVAILABLE
        and "telemetry_unavailable" not in reason_set
    ):
        raise ValueError("unavailable telemetry requires telemetry_unavailable")


__all__ = [
    "MEMORY_RECOMMENDATION_CATALOG_SCHEMA_REVISION",
    "MemoryCellObservation",
    "MemoryRecommendation",
    "MemoryRecommendationCatalog",
    "MemoryRecommendationStatus",
    "SafetyReservePolicy",
    "build_memory_recommendation",
    "memory_recommendation_catalog_schema",
]
