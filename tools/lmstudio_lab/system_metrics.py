from __future__ import annotations

import hashlib
import importlib
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from lmstudio_managed.metrics import (
    GpuDeviceSample,
    GpuProcessKind,
    GpuProcessSample,
    GpuTelemetryEvidenceLevel,
    GpuTelemetrySample,
    TelemetryStatus,
)
from lmstudio_managed.metrics import (
    SystemSummary as ManagedSystemSummary,
)

from .metrics import (
    SCHEMA_VERSION,
    PhaseConfidence,
    PhaseDerivationMethod,
    PhaseMarker,
    PhaseMarkerRecord,
    append_jsonl_record,
    validate_phase_marker_order,
)
from .report import write_json_file

try:
    import psutil
except ImportError:  # pragma: no cover - defensive fallback only
    psutil = None  # type: ignore[assignment]


_NVIDIA_SMI_COMMAND = (
    "nvidia-smi",
    "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free,"
    "utilization.gpu,utilization.memory,power.draw",
    "--format=csv,noheader,nounits",
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"n/a", "[not supported]"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _mb_from_bytes(value: Any) -> float | None:
    try:
        raw_value = float(value)
    except (TypeError, ValueError):
        return None
    return round(raw_value / (1024 * 1024), 3)


def _hash_public_identity(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace").strip()
    else:
        text = str(value).strip()
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def _hash_gpu_name(name: str | None) -> str | None:
    return _hash_public_identity(name)


def _safe_process_name(name: str | None) -> str | None:
    if name is None:
        return None
    normalized = name.strip().lower()
    if not normalized:
        return None
    if "lm studio" in normalized or "lmstudio" in normalized:
        return "lmstudio"
    return None


def _peak(values: Sequence[float | None]) -> float | None:
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return max(filtered)


@dataclass(slots=True)
class SystemMetricsSnapshot:
    schema_version: str = SCHEMA_VERSION
    timestamp_utc: str = field(default_factory=_utc_now_iso)
    monotonic_seconds: float | None = None
    providers: dict[str, str] = field(default_factory=dict)
    cpu_percent: float | None = None
    ram_total_mb: float | None = None
    ram_used_mb: float | None = None
    ram_available_mb: float | None = None
    process_name: str | None = None
    process_rss_mb: float | None = None
    gpu_index: int | None = None
    gpu_name_hash: str | None = None
    vram_total_mb: float | None = None
    vram_used_mb: float | None = None
    vram_free_mb: float | None = None
    gpu_util_percent: float | None = None
    gpu_memory_util_percent: float | None = None
    gpu_power_watts: float | None = None
    gpu_evidence_level: GpuTelemetryEvidenceLevel = GpuTelemetryEvidenceLevel.UNAVAILABLE
    gpu_telemetry: GpuTelemetrySample | None = None
    phase: PhaseMarkerRecord | None = None
    error_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DevicePhaseMetricsSummary:
    device_index: int | None
    device_id_hash: str
    vram_peak_mb: float | None
    unavailable_sample_count: int = 0


@dataclass(frozen=True, slots=True)
class PhaseMetricsSummary:
    marker: str
    sample_count: int
    ram_peak_mb: float | None
    process_rss_peak_mb: float | None
    vram_peak_mb: float | None
    derivation_methods: tuple[str, ...]
    confidence_levels: tuple[str, ...]
    devices: tuple[DevicePhaseMetricsSummary, ...] = ()


@dataclass(slots=True)
class SystemMetricsSummary:
    schema_version: str = SCHEMA_VERSION
    sample_count: int = 0
    providers: dict[str, str] = field(default_factory=dict)
    ram_before_mb: float | None = None
    ram_peak_mb: float | None = None
    ram_after_mb: float | None = None
    process_rss_before_mb: float | None = None
    process_rss_peak_mb: float | None = None
    process_rss_after_mb: float | None = None
    vram_before_mb: float | None = None
    vram_peak_mb: float | None = None
    vram_after_mb: float | None = None
    gpu_util_peak_percent: float | None = None
    gpu_memory_util_peak_percent: float | None = None
    gpu_power_peak_watts: float | None = None
    configured_sample_interval_s: float | None = None
    actual_sample_interval_s: float | None = None
    sampler_failure_count: int = 0
    telemetry_valid: bool = True
    phase_order_valid: bool = True
    timestamp_order_valid: bool = False
    memory_evidence_valid: bool = False
    phase_summaries: tuple[PhaseMetricsSummary, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_managed_summary(self) -> ManagedSystemSummary:
        return ManagedSystemSummary(
            vram_before_mb=self.vram_before_mb,
            vram_peak_mb=self.vram_peak_mb,
            vram_after_mb=self.vram_after_mb,
            ram_before_mb=self.ram_before_mb,
            ram_peak_mb=self.ram_peak_mb,
            ram_after_mb=self.ram_after_mb,
            process_rss_before_mb=self.process_rss_before_mb,
            process_rss_peak_mb=self.process_rss_peak_mb,
            process_rss_after_mb=self.process_rss_after_mb,
            gpu_util_peak_percent=self.gpu_util_peak_percent,
            gpu_memory_util_peak_percent=self.gpu_memory_util_peak_percent,
            gpu_power_peak_watts=self.gpu_power_peak_watts,
        )


def parse_nvidia_smi_devices_csv_output(
    csv_text: str,
    *,
    timestamp_utc: str | None = None,
) -> GpuTelemetrySample:
    """Parse all device rows without promoting fallback data to process evidence."""

    rows = [line.strip() for line in csv_text.splitlines() if line.strip()]
    if not rows:
        return GpuTelemetrySample(
            timestamp_utc=timestamp_utc or _utc_now_iso(),
            evidence_level=GpuTelemetryEvidenceLevel.UNAVAILABLE,
            status=TelemetryStatus.UNAVAILABLE,
            adapter="nvidia_smi",
            error_category="nvidia_smi_unavailable",
        )

    devices: list[GpuDeviceSample] = []
    for row in rows:
        parts = [part.strip() for part in row.split(",")]
        if len(parts) == 9:
            index_text, uuid, name, total, used, free, gpu_util, memory_util, power = parts
            identity_source = uuid
        elif len(parts) == 7:
            index_text, name, used, total, gpu_util, memory_util, power = parts
            free_value = None
            total_value = _coerce_float(total)
            used_value = _coerce_float(used)
            if total_value is not None and used_value is not None:
                free_value = total_value - used_value
            free = str(free_value) if free_value is not None else ""
            identity_source = f"index:{index_text}|name:{name}"
        else:
            return GpuTelemetrySample(
                timestamp_utc=timestamp_utc or _utc_now_iso(),
                evidence_level=GpuTelemetryEvidenceLevel.UNAVAILABLE,
                status=TelemetryStatus.ERROR,
                adapter="nvidia_smi",
                error_category="nvidia_smi_parse_error",
            )

        device_index = _coerce_int(index_text)
        device_id_hash = _hash_public_identity(identity_source)
        if device_index is None or device_id_hash is None:
            return GpuTelemetrySample(
                timestamp_utc=timestamp_utc or _utc_now_iso(),
                evidence_level=GpuTelemetryEvidenceLevel.UNAVAILABLE,
                status=TelemetryStatus.ERROR,
                adapter="nvidia_smi",
                error_category="nvidia_smi_parse_error",
            )
        devices.append(
            GpuDeviceSample(
                device_index=device_index,
                device_id_hash=device_id_hash,
                name_hash=_hash_gpu_name(name),
                evidence_level=GpuTelemetryEvidenceLevel.NVIDIA_SMI_DEVICE_ONLY,
                vram_total_mb=_coerce_float(total),
                vram_used_mb=_coerce_float(used),
                vram_free_mb=_coerce_float(free),
                gpu_util_percent=_coerce_float(gpu_util),
                gpu_memory_util_percent=_coerce_float(memory_util),
                gpu_power_watts=_coerce_float(power),
            )
        )

    devices.sort(key=lambda device: device.device_index if device.device_index is not None else -1)
    return GpuTelemetrySample(
        timestamp_utc=timestamp_utc or _utc_now_iso(),
        evidence_level=GpuTelemetryEvidenceLevel.NVIDIA_SMI_DEVICE_ONLY,
        status=TelemetryStatus.AVAILABLE,
        devices=tuple(devices),
        adapter="nvidia_smi",
    )


def parse_nvidia_smi_csv_output(csv_text: str) -> tuple[dict[str, Any], str | None]:
    """Compatibility parser returning the first device's legacy flat metrics."""

    telemetry = parse_nvidia_smi_devices_csv_output(csv_text)
    if telemetry.status != TelemetryStatus.AVAILABLE or not telemetry.devices:
        return {}, telemetry.error_category
    device = telemetry.devices[0]
    return (
        {
            "gpu_index": device.device_index,
            "gpu_name_hash": device.name_hash,
            "vram_used_mb": device.vram_used_mb,
            "vram_total_mb": device.vram_total_mb,
            "gpu_util_percent": device.gpu_util_percent,
            "gpu_memory_util_percent": device.gpu_memory_util_percent,
            "gpu_power_watts": device.gpu_power_watts,
        },
        None,
    )


def _collect_process_metrics() -> tuple[str | None, float | None, str | None]:
    if psutil is None:
        return None, None, "psutil_unavailable"

    try:
        process_iter = psutil.process_iter(attrs=["name", "memory_info"])
    except Exception:
        return None, None, "psutil_process_error"

    for process in process_iter:
        try:
            process_name = _safe_process_name(process.info.get("name"))
            if process_name is None:
                continue
            memory_info = process.info.get("memory_info")
            rss_value = getattr(memory_info, "rss", None)
            return process_name, _mb_from_bytes(rss_value), None
        except Exception:
            continue
    return None, None, None


def _collect_host_metrics() -> tuple[dict[str, Any], str | None]:
    if psutil is None:
        return {}, "psutil_unavailable"

    try:
        virtual_memory = psutil.virtual_memory()
        return (
            {
                "cpu_percent": _coerce_float(psutil.cpu_percent(interval=None)),
                "ram_total_mb": _mb_from_bytes(virtual_memory.total),
                "ram_used_mb": _mb_from_bytes(virtual_memory.used),
                "ram_available_mb": _mb_from_bytes(virtual_memory.available),
            },
            None,
        )
    except Exception:
        return {}, "psutil_host_error"


def _load_nvml_module() -> Any | None:
    try:
        return importlib.import_module("pynvml")
    except ImportError:
        return None


def _nvml_optional_call(nvml_module: Any, name: str, *args: Any) -> tuple[Any, bool]:
    function = getattr(nvml_module, name, None)
    if not callable(function):
        return None, False
    try:
        return function(*args), True
    except Exception:
        return None, False


def _nvml_memory_mb(nvml_module: Any, value: Any) -> float | None:
    if value is None or value == getattr(nvml_module, "NVML_VALUE_NOT_AVAILABLE", None):
        return None
    return _mb_from_bytes(value)


def _collect_nvml_processes(
    nvml_module: Any,
    handle: Any,
    *,
    identity_namespace: Any,
) -> tuple[tuple[GpuProcessSample, ...], bool]:
    processes: list[GpuProcessSample] = []
    all_queries_supported = True
    for function_name, kind in (
        ("nvmlDeviceGetComputeRunningProcesses", GpuProcessKind.COMPUTE),
        ("nvmlDeviceGetGraphicsRunningProcesses", GpuProcessKind.GRAPHICS),
    ):
        entries, query_supported = _nvml_optional_call(nvml_module, function_name, handle)
        if not query_supported:
            all_queries_supported = False
            continue
        for entry in entries or ():
            pid = getattr(entry, "pid", None)
            process_id_hash = _hash_public_identity(
                f"{identity_namespace}|pid:{pid}" if pid is not None else None
            )
            if process_id_hash is None:
                continue
            processes.append(
                GpuProcessSample(
                    process_id_hash=process_id_hash,
                    kind=kind,
                    used_gpu_memory_mb=_nvml_memory_mb(
                        nvml_module,
                        getattr(entry, "usedGpuMemory", None),
                    ),
                    gpu_instance_id=_coerce_int(getattr(entry, "gpuInstanceId", None)),
                    compute_instance_id=_coerce_int(getattr(entry, "computeInstanceId", None)),
                )
            )
    processes.sort(key=lambda process: (process.kind.value, process.process_id_hash))
    return tuple(processes), all_queries_supported


def _collect_nvml_device(
    nvml_module: Any,
    handle: Any,
    *,
    device_index: int,
    is_mig_device: bool = False,
    mig_device_index: int | None = None,
    parent_device_id_hash: str | None = None,
) -> GpuDeviceSample:
    reported_index, _ = _nvml_optional_call(nvml_module, "nvmlDeviceGetIndex", handle)
    uuid, _ = _nvml_optional_call(nvml_module, "nvmlDeviceGetUUID", handle)
    name, _ = _nvml_optional_call(nvml_module, "nvmlDeviceGetName", handle)
    identity_source = uuid or f"index:{device_index}|mig:{mig_device_index}|name:{name}"
    device_id_hash = _hash_public_identity(identity_source)
    if device_id_hash is None:
        device_id_hash = _hash_public_identity(f"index:{device_index}|mig:{mig_device_index}") or ""

    memory_info, _ = _nvml_optional_call(nvml_module, "nvmlDeviceGetMemoryInfo", handle)
    utilization, _ = _nvml_optional_call(
        nvml_module,
        "nvmlDeviceGetUtilizationRates",
        handle,
    )
    power_milliwatts, power_supported = _nvml_optional_call(
        nvml_module,
        "nvmlDeviceGetPowerUsage",
        handle,
    )
    processes, process_queries_supported = _collect_nvml_processes(
        nvml_module,
        handle,
        identity_namespace=identity_source,
    )

    mig_enabled: bool | None = None
    if not is_mig_device:
        mig_mode, mig_mode_supported = _nvml_optional_call(
            nvml_module,
            "nvmlDeviceGetMigMode",
            handle,
        )
        if mig_mode_supported and isinstance(mig_mode, (tuple, list)) and mig_mode:
            mig_enabled = mig_mode[0] == getattr(nvml_module, "NVML_DEVICE_MIG_ENABLE", 1)

    evidence_level = (
        GpuTelemetryEvidenceLevel.NVML_PROCESS_ATTRIBUTED
        if process_queries_supported
        and all(process.used_gpu_memory_mb is not None for process in processes)
        else GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY
    )
    power_value = _coerce_float(power_milliwatts) if power_supported else None
    return GpuDeviceSample(
        device_index=_coerce_int(reported_index) if reported_index is not None else device_index,
        device_id_hash=device_id_hash,
        name_hash=_hash_public_identity(name),
        evidence_level=evidence_level,
        vram_total_mb=_nvml_memory_mb(nvml_module, getattr(memory_info, "total", None)),
        vram_used_mb=_nvml_memory_mb(nvml_module, getattr(memory_info, "used", None)),
        vram_free_mb=_nvml_memory_mb(nvml_module, getattr(memory_info, "free", None)),
        gpu_util_percent=_coerce_float(getattr(utilization, "gpu", None)),
        gpu_memory_util_percent=_coerce_float(getattr(utilization, "memory", None)),
        gpu_power_watts=(power_value / 1000 if power_value is not None else None),
        processes=processes,
        mig_enabled=mig_enabled,
        is_mig_device=is_mig_device,
        mig_device_index=mig_device_index,
        parent_device_id_hash=parent_device_id_hash,
    )


def _collect_nvml_gpu_telemetry(
    nvml_module: Any,
    *,
    timestamp_utc: str,
) -> GpuTelemetrySample:
    initialized = False
    try:
        nvml_module.nvmlInit()
        initialized = True
        device_count = int(nvml_module.nvmlDeviceGetCount())
        devices: list[GpuDeviceSample] = []
        for device_index in range(device_count):
            try:
                handle = nvml_module.nvmlDeviceGetHandleByIndex(device_index)
                physical = _collect_nvml_device(
                    nvml_module,
                    handle,
                    device_index=device_index,
                )
            except Exception:
                devices.append(
                    GpuDeviceSample(
                        device_index=device_index,
                        device_id_hash=_hash_public_identity(f"index:{device_index}") or "",
                        evidence_level=GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY,
                        status=TelemetryStatus.ERROR,
                        error_category="nvml_device_error",
                    )
                )
                continue
            devices.append(physical)

            if physical.mig_enabled is not True:
                continue
            max_mig_count, max_mig_supported = _nvml_optional_call(
                nvml_module,
                "nvmlDeviceGetMaxMigDeviceCount",
                handle,
            )
            if not max_mig_supported:
                continue
            for mig_device_index in range(int(max_mig_count or 0)):
                mig_handle, mig_present = _nvml_optional_call(
                    nvml_module,
                    "nvmlDeviceGetMigDeviceHandleByIndex",
                    handle,
                    mig_device_index,
                )
                if not mig_present:
                    continue
                devices.append(
                    _collect_nvml_device(
                        nvml_module,
                        mig_handle,
                        device_index=device_index,
                        is_mig_device=True,
                        mig_device_index=mig_device_index,
                        parent_device_id_hash=physical.device_id_hash,
                    )
                )

        if not devices or all(device.status == TelemetryStatus.ERROR for device in devices):
            return GpuTelemetrySample(
                timestamp_utc=timestamp_utc,
                evidence_level=GpuTelemetryEvidenceLevel.UNAVAILABLE,
                status=TelemetryStatus.ERROR,
                adapter="nvml",
                error_category="nvml_device_error",
            )
        evidence_level = (
            GpuTelemetryEvidenceLevel.NVML_PROCESS_ATTRIBUTED
            if all(
                device.evidence_level == GpuTelemetryEvidenceLevel.NVML_PROCESS_ATTRIBUTED
                for device in devices
            )
            else GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY
        )
        return GpuTelemetrySample(
            timestamp_utc=timestamp_utc,
            evidence_level=evidence_level,
            status=TelemetryStatus.AVAILABLE,
            devices=tuple(devices),
            adapter="nvml",
        )
    except Exception:
        return GpuTelemetrySample(
            timestamp_utc=timestamp_utc,
            evidence_level=GpuTelemetryEvidenceLevel.UNAVAILABLE,
            status=TelemetryStatus.ERROR,
            adapter="nvml",
            error_category="nvml_error",
        )
    finally:
        if initialized:
            try:
                nvml_module.nvmlShutdown()
            except Exception:
                pass


def _collect_nvidia_smi_gpu_telemetry(
    *,
    timestamp_utc: str,
    subprocess_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> GpuTelemetrySample:
    runner = subprocess_runner or subprocess.run
    try:
        completed = runner(
            _NVIDIA_SMI_COMMAND,
            capture_output=True,
            check=False,
            text=True,
            timeout=2.0,
        )
    except FileNotFoundError:
        return GpuTelemetrySample(
            timestamp_utc=timestamp_utc,
            evidence_level=GpuTelemetryEvidenceLevel.UNAVAILABLE,
            status=TelemetryStatus.UNAVAILABLE,
            adapter="nvidia_smi",
            error_category="nvidia_smi_unavailable",
        )
    except subprocess.TimeoutExpired:
        error_category = "nvidia_smi_timeout"
    except Exception:
        error_category = "nvidia_smi_error"
    else:
        if completed.returncode == 0:
            return parse_nvidia_smi_devices_csv_output(
                completed.stdout,
                timestamp_utc=timestamp_utc,
            )
        error_category = "nvidia_smi_unavailable"

    return GpuTelemetrySample(
        timestamp_utc=timestamp_utc,
        evidence_level=GpuTelemetryEvidenceLevel.UNAVAILABLE,
        status=(
            TelemetryStatus.UNAVAILABLE
            if error_category == "nvidia_smi_unavailable"
            else TelemetryStatus.ERROR
        ),
        adapter="nvidia_smi",
        error_category=error_category,
    )


def collect_gpu_telemetry(
    *,
    timestamp_utc: str | None = None,
    nvml_module: Any | None = None,
    subprocess_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> GpuTelemetrySample:
    """Collect all visible NVIDIA devices with the strongest available evidence."""

    sample_timestamp = timestamp_utc or _utc_now_iso()
    resolved_nvml_module = nvml_module if nvml_module is not None else _load_nvml_module()
    if resolved_nvml_module is not None:
        nvml_sample = _collect_nvml_gpu_telemetry(
            resolved_nvml_module,
            timestamp_utc=sample_timestamp,
        )
        if nvml_sample.status == TelemetryStatus.AVAILABLE and nvml_sample.devices:
            return nvml_sample

    return _collect_nvidia_smi_gpu_telemetry(
        timestamp_utc=sample_timestamp,
        subprocess_runner=subprocess_runner,
    )


def collect_system_snapshot(
    *,
    providers: Mapping[str, str] | None = None,
    monotonic_seconds: float | None = None,
    timestamp_utc: str | None = None,
    nvml_module: Any | None = None,
    subprocess_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> SystemMetricsSnapshot:
    """Collect one privacy-safe host/process/GPU snapshot.

    Future adapters can extend GPU collection for non-CUDA runtimes such as MLX
    without changing the public snapshot/summary contract.
    """

    sample_timestamp = timestamp_utc or _utc_now_iso()
    error_category: str | None = None
    host_metrics, host_error = _collect_host_metrics()
    if host_error is not None:
        error_category = host_error

    process_name, process_rss_mb, process_error = _collect_process_metrics()
    if error_category is None and process_error is not None:
        error_category = process_error

    gpu_telemetry = collect_gpu_telemetry(
        timestamp_utc=sample_timestamp,
        nvml_module=nvml_module,
        subprocess_runner=subprocess_runner,
    )
    gpu_error = gpu_telemetry.error_category
    if error_category is None and gpu_error is not None:
        error_category = gpu_error

    first_gpu = gpu_telemetry.devices[0] if gpu_telemetry.devices else None

    return SystemMetricsSnapshot(
        timestamp_utc=sample_timestamp,
        monotonic_seconds=(time.monotonic() if monotonic_seconds is None else monotonic_seconds),
        providers={str(key): str(value) for key, value in (providers or {}).items()},
        cpu_percent=host_metrics.get("cpu_percent"),
        ram_total_mb=host_metrics.get("ram_total_mb"),
        ram_used_mb=host_metrics.get("ram_used_mb"),
        ram_available_mb=host_metrics.get("ram_available_mb"),
        process_name=process_name,
        process_rss_mb=process_rss_mb,
        gpu_index=first_gpu.device_index if first_gpu is not None else None,
        gpu_name_hash=first_gpu.name_hash if first_gpu is not None else None,
        vram_total_mb=first_gpu.vram_total_mb if first_gpu is not None else None,
        vram_used_mb=first_gpu.vram_used_mb if first_gpu is not None else None,
        vram_free_mb=first_gpu.vram_free_mb if first_gpu is not None else None,
        gpu_util_percent=first_gpu.gpu_util_percent if first_gpu is not None else None,
        gpu_memory_util_percent=(
            first_gpu.gpu_memory_util_percent if first_gpu is not None else None
        ),
        gpu_power_watts=first_gpu.gpu_power_watts if first_gpu is not None else None,
        gpu_evidence_level=gpu_telemetry.evidence_level,
        gpu_telemetry=gpu_telemetry,
        error_category=error_category,
    )


def _actual_sample_interval(samples: Sequence[SystemMetricsSnapshot]) -> float | None:
    if not _timestamp_order_valid(samples):
        return None
    known = [
        float(sample.monotonic_seconds)
        for sample in samples
        if sample.monotonic_seconds is not None
    ]
    if len(known) < 2:
        return None
    intervals = [later - earlier for earlier, later in zip(known, known[1:], strict=False)]
    return round(sum(intervals) / len(intervals), 6) if intervals else None


def _timestamp_order_valid(samples: Sequence[SystemMetricsSnapshot]) -> bool:
    timestamps = [sample.monotonic_seconds for sample in samples]
    if any(timestamp is None for timestamp in timestamps):
        return False
    known = [float(timestamp) for timestamp in timestamps if timestamp is not None]
    return all(later >= earlier for earlier, later in zip(known, known[1:], strict=False))


def _gpu_memory_evidence_valid(samples: Sequence[SystemMetricsSnapshot]) -> bool:
    for sample in samples:
        telemetry = sample.gpu_telemetry
        if (
            telemetry is None
            or telemetry.status is not TelemetryStatus.AVAILABLE
            or telemetry.evidence_level is GpuTelemetryEvidenceLevel.UNAVAILABLE
            or not telemetry.devices
        ):
            return False
        if any(
            device.status is not TelemetryStatus.AVAILABLE or device.vram_used_mb is None
            for device in telemetry.devices
        ):
            return False
    return True


def _summarize_phase(
    marker: PhaseMarker, samples: Sequence[SystemMetricsSnapshot]
) -> PhaseMetricsSummary:
    device_samples: dict[tuple[int | None, str], list[GpuDeviceSample]] = {}
    for sample in samples:
        telemetry = sample.gpu_telemetry
        for device in telemetry.devices if telemetry is not None else ():
            device_samples.setdefault((device.device_index, device.device_id_hash), []).append(
                device
            )
    devices = tuple(
        DevicePhaseMetricsSummary(
            device_index=device_index,
            device_id_hash=device_id_hash,
            vram_peak_mb=_peak([device.vram_used_mb for device in values]),
            unavailable_sample_count=sum(
                device.status != TelemetryStatus.AVAILABLE or device.vram_used_mb is None
                for device in values
            ),
        )
        for (device_index, device_id_hash), values in sorted(
            device_samples.items(),
            key=lambda item: (
                item[0][0] is None,
                item[0][0] if item[0][0] is not None else 0,
                item[0][1],
            ),
        )
    )
    phase_records = [sample.phase for sample in samples if sample.phase is not None]
    return PhaseMetricsSummary(
        marker=marker.value,
        sample_count=len(samples),
        ram_peak_mb=_peak([sample.ram_used_mb for sample in samples]),
        process_rss_peak_mb=_peak([sample.process_rss_mb for sample in samples]),
        vram_peak_mb=_peak([sample.vram_used_mb for sample in samples]),
        derivation_methods=tuple(
            sorted({record.derivation_method.value for record in phase_records})
        ),
        confidence_levels=tuple(sorted({record.confidence.value for record in phase_records})),
        devices=devices,
    )


def summarize_system_samples(
    samples: Sequence[SystemMetricsSnapshot],
    *,
    configured_sample_interval_s: float | None = None,
) -> SystemMetricsSummary:
    if not samples:
        return SystemMetricsSummary(
            configured_sample_interval_s=configured_sample_interval_s,
            telemetry_valid=False,
        )

    first = samples[0]
    last = samples[-1]
    phase_groups = {
        marker: [sample for sample in samples if sample.phase and sample.phase.marker == marker]
        for marker in PhaseMarker
    }
    phase_records_by_sequence = {
        sample.phase.sequence: sample.phase for sample in samples if sample.phase is not None
    }
    phase_records = tuple(
        phase_records_by_sequence[key] for key in sorted(phase_records_by_sequence)
    )
    sampler_failure_count = sum(sample.error_category == "sampler_error" for sample in samples)
    phase_order_valid = validate_phase_marker_order(phase_records)
    timestamp_order_valid = _timestamp_order_valid(samples)
    telemetry_valid = sampler_failure_count == 0
    return SystemMetricsSummary(
        sample_count=len(samples),
        providers=dict(last.providers or first.providers),
        ram_before_mb=first.ram_used_mb,
        ram_peak_mb=_peak([sample.ram_used_mb for sample in samples]),
        ram_after_mb=last.ram_used_mb,
        process_rss_before_mb=first.process_rss_mb,
        process_rss_peak_mb=_peak([sample.process_rss_mb for sample in samples]),
        process_rss_after_mb=last.process_rss_mb,
        vram_before_mb=first.vram_used_mb,
        vram_peak_mb=_peak([sample.vram_used_mb for sample in samples]),
        vram_after_mb=last.vram_used_mb,
        gpu_util_peak_percent=_peak([sample.gpu_util_percent for sample in samples]),
        gpu_memory_util_peak_percent=_peak([sample.gpu_memory_util_percent for sample in samples]),
        gpu_power_peak_watts=_peak([sample.gpu_power_watts for sample in samples]),
        configured_sample_interval_s=configured_sample_interval_s,
        actual_sample_interval_s=_actual_sample_interval(samples),
        sampler_failure_count=sampler_failure_count,
        telemetry_valid=telemetry_valid,
        phase_order_valid=phase_order_valid,
        timestamp_order_valid=timestamp_order_valid,
        memory_evidence_valid=(
            telemetry_valid
            and phase_order_valid
            and timestamp_order_valid
            and _gpu_memory_evidence_valid(samples)
        ),
        phase_summaries=tuple(
            _summarize_phase(marker, phase_groups[marker])
            for marker in PhaseMarker
            if phase_groups[marker]
        ),
    )


class SystemMetricsSampler:
    def __init__(
        self,
        *,
        sample_interval_s: float = 1.0,
        collector: Callable[..., SystemMetricsSnapshot] | None = None,
    ) -> None:
        self.sample_interval_s = sample_interval_s
        self.collector = collector or collect_system_snapshot
        self.samples: list[SystemMetricsSnapshot] = []
        self._providers: dict[str, str] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._collect_lock = threading.Lock()
        self._phase = PhaseMarkerRecord(
            marker=PhaseMarker.CLEAN_BASELINE,
            sequence=0,
            derivation_method=PhaseDerivationMethod.DIRECT_EVENT,
            confidence=PhaseConfidence.HIGH,
        )

    def _collect_once_locked(self) -> None:
        phase = self._phase
        try:
            sample = self.collector(providers=self._providers)
            sample.phase = phase
        except Exception:
            sample = SystemMetricsSnapshot(
                monotonic_seconds=time.monotonic(),
                providers=dict(self._providers),
                phase=phase,
                error_category="sampler_error",
            )
        self.samples.append(sample)

    def _collect_once(self) -> None:
        with self._collect_lock:
            self._collect_once_locked()

    def _run(self) -> None:
        while not self._stop_event.wait(self.sample_interval_s):
            self._collect_once()

    def start(self, *, providers: Mapping[str, str] | None = None) -> None:
        self.samples = []
        self._providers = {str(key): str(value) for key, value in (providers or {}).items()}
        self._stop_event = threading.Event()
        self._phase = PhaseMarkerRecord(
            marker=PhaseMarker.CLEAN_BASELINE,
            sequence=0,
            derivation_method=PhaseDerivationMethod.DIRECT_EVENT,
            confidence=PhaseConfidence.HIGH,
        )
        self._collect_once()
        if self.sample_interval_s > 0:
            self._thread = threading.Thread(
                target=self._run,
                name="lmstudio-system-metrics",
                daemon=True,
            )
            self._thread.start()

    def mark_phase(
        self,
        marker: PhaseMarker,
        derivation_method: PhaseDerivationMethod = PhaseDerivationMethod.DIRECT_EVENT,
        confidence: PhaseConfidence = PhaseConfidence.HIGH,
    ) -> None:
        with self._collect_lock:
            self._phase = PhaseMarkerRecord(
                marker=marker,
                sequence=self._phase.sequence + 1,
                derivation_method=derivation_method,
                confidence=confidence,
            )
            self._collect_once_locked()

    def stop(self, *, providers: Mapping[str, str] | None = None) -> SystemMetricsSummary:
        if providers is not None:
            self._providers = {str(key): str(value) for key, value in providers.items()}
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self.sample_interval_s * 2, 1.0))
            self._thread = None
        self._collect_once()
        return summarize_system_samples(
            self.samples,
            configured_sample_interval_s=self.sample_interval_s,
        )


def write_system_telemetry_artifacts(
    run_dir: Any,
    *,
    samples: Sequence[SystemMetricsSnapshot],
    summary: SystemMetricsSummary,
) -> None:
    system_samples_path = run_dir / "system_samples.jsonl"
    system_samples_path.write_text("", encoding="utf-8")
    for sample in samples:
        append_jsonl_record(system_samples_path, sample.to_dict())
    write_json_file(run_dir / "system_summary.json", summary.to_dict())


__all__ = [
    "DevicePhaseMetricsSummary",
    "PhaseMetricsSummary",
    "SystemMetricsSampler",
    "SystemMetricsSnapshot",
    "SystemMetricsSummary",
    "collect_gpu_telemetry",
    "collect_system_snapshot",
    "parse_nvidia_smi_csv_output",
    "parse_nvidia_smi_devices_csv_output",
    "summarize_system_samples",
    "write_system_telemetry_artifacts",
]
