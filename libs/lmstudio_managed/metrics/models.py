"""Pure metrics DTOs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from ..lifecycle.state import ParallelSemantics
from ..validation.models import GenerationFailureKind, StructuredValidationStatus


class ModelScreeningVerdict(StrEnum):
    LAB_BASELINE = "lab_baseline"
    LAB_CANDIDATE_HEAVIER = "lab_candidate_heavier"
    NEEDS_REASONING_ROUTING = "needs_reasoning_routing"
    NEEDS_TIMEOUT_POLICY = "needs_timeout_policy"
    NEEDS_PROMPT_POLICY = "needs_prompt_policy"
    NOT_CANDIDATE_YET = "not_candidate_yet"


class TelemetryStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class GpuTelemetryEvidenceLevel(StrEnum):
    NVML_PROCESS_ATTRIBUTED = "nvml_process_attributed"
    NVML_DEVICE_ONLY = "nvml_device_only"
    NVIDIA_SMI_DEVICE_ONLY = "nvidia_smi_device_only"
    UNAVAILABLE = "unavailable"


class GpuProcessKind(StrEnum):
    COMPUTE = "compute"
    GRAPHICS = "graphics"


@dataclass(frozen=True, slots=True)
class GpuProcessSample:
    process_id_hash: str
    kind: GpuProcessKind
    used_gpu_memory_mb: float | None = None
    gpu_instance_id: int | None = None
    compute_instance_id: int | None = None


@dataclass(frozen=True, slots=True)
class GpuDeviceSample:
    device_index: int | None
    device_id_hash: str
    evidence_level: GpuTelemetryEvidenceLevel
    status: TelemetryStatus = TelemetryStatus.AVAILABLE
    name_hash: str | None = None
    vram_total_mb: float | None = None
    vram_used_mb: float | None = None
    vram_free_mb: float | None = None
    gpu_util_percent: float | None = None
    gpu_memory_util_percent: float | None = None
    gpu_power_watts: float | None = None
    processes: tuple[GpuProcessSample, ...] = ()
    mig_enabled: bool | None = None
    is_mig_device: bool = False
    mig_device_index: int | None = None
    parent_device_id_hash: str | None = None
    error_category: str | None = None


@dataclass(frozen=True, slots=True)
class GpuTelemetrySample:
    timestamp_utc: str
    evidence_level: GpuTelemetryEvidenceLevel
    status: TelemetryStatus
    devices: tuple[GpuDeviceSample, ...] = ()
    adapter: str | None = None
    error_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ParallelEvidence:
    configured_parallel: int | None
    applied_parallel: int | None
    parallel_verified: bool
    app_concurrency: int | None
    queue_pressure_mode: bool | None
    parallel_semantics: ParallelSemantics

    @property
    def is_true_parallel(self) -> bool:
        return (
            self.parallel_verified
            and self.configured_parallel is not None
            and self.app_concurrency is not None
            and self.configured_parallel == self.app_concurrency
            and self.applied_parallel == self.app_concurrency
            and self.queue_pressure_mode is False
            and self.parallel_semantics == ParallelSemantics.TRUE_PARALLEL
        )


@dataclass(frozen=True, slots=True)
class RequestMetrics:
    request_id: str
    finish_reason: str | None = None
    error_category: str | None = None
    failure_kind: GenerationFailureKind | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    total_elapsed_ms: float | None = None
    response_chars: int | None = None
    raw_prompt_response_stored: bool = False


@dataclass(frozen=True, slots=True)
class BatchMetrics:
    request_count: int
    business_pass_count: int
    finish_length_count: int
    structured_error_count: int
    total_wall_time_ms: float | None = None
    total_completion_tokens: int | None = None

    @property
    def business_pass_rate(self) -> float | None:
        if self.request_count <= 0:
            return None
        return self.business_pass_count / self.request_count


@dataclass(frozen=True, slots=True)
class SystemSample:
    vram_used_mb: float | None = None
    ram_used_mb: float | None = None
    gpu_util_percent: float | None = None
    gpu_telemetry: GpuTelemetrySample | None = None


@dataclass(frozen=True, slots=True)
class SystemSummary:
    vram_before_mb: float | None = None
    vram_peak_mb: float | None = None
    vram_after_mb: float | None = None
    ram_before_mb: float | None = None
    ram_peak_mb: float | None = None
    ram_after_mb: float | None = None
    process_rss_before_mb: float | None = None
    process_rss_peak_mb: float | None = None
    process_rss_after_mb: float | None = None
    gpu_util_peak_percent: float | None = None
    gpu_memory_util_peak_percent: float | None = None
    gpu_power_peak_watts: float | None = None


@dataclass(frozen=True, slots=True)
class ScreeningEvidence:
    model_key: str
    structured_status: StructuredValidationStatus | None = None
    verdict: ModelScreeningVerdict | None = None
    parallel_evidence: ParallelEvidence | None = None
    batch_metrics: BatchMetrics | None = None
    system_summary: SystemSummary | None = None
    token_normalized_speedup: float | None = None
