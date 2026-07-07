from __future__ import annotations

import hashlib
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from libs.lmstudio_managed.metrics import SystemSummary as ManagedSystemSummary

from .metrics import SCHEMA_VERSION, append_jsonl_record
from .report import write_json_file

try:
    import psutil
except ImportError:  # pragma: no cover - defensive fallback only
    psutil = None  # type: ignore[assignment]


_NVIDIA_SMI_COMMAND = (
    "nvidia-smi",
    "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,utilization.memory,power.draw",
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


def _hash_gpu_name(name: str | None) -> str | None:
    if name is None:
        return None
    text = name.strip()
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


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
    gpu_util_percent: float | None = None
    gpu_memory_util_percent: float | None = None
    gpu_power_watts: float | None = None
    error_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def parse_nvidia_smi_csv_output(csv_text: str) -> tuple[dict[str, Any], str | None]:
    """Parse the first `nvidia-smi` CSV row into privacy-safe GPU metrics."""

    rows = [line.strip() for line in csv_text.splitlines() if line.strip()]
    if not rows:
        return {}, "nvidia_smi_unavailable"

    first_row = rows[0]
    parts = [part.strip() for part in first_row.split(",")]
    if len(parts) != 7:
        return {}, "nvidia_smi_parse_error"

    gpu_index = _coerce_int(parts[0])
    if gpu_index is None:
        return {}, "nvidia_smi_parse_error"

    return (
        {
            "gpu_index": gpu_index,
            "gpu_name_hash": _hash_gpu_name(parts[1]),
            "vram_used_mb": _coerce_float(parts[2]),
            "vram_total_mb": _coerce_float(parts[3]),
            "gpu_util_percent": _coerce_float(parts[4]),
            "gpu_memory_util_percent": _coerce_float(parts[5]),
            "gpu_power_watts": _coerce_float(parts[6]),
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


def _collect_gpu_metrics(
    *,
    subprocess_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> tuple[dict[str, Any], str | None]:
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
        return {}, "nvidia_smi_unavailable"
    except subprocess.TimeoutExpired:
        return {}, "nvidia_smi_timeout"
    except Exception:
        return {}, "nvidia_smi_error"

    if completed.returncode != 0:
        return {}, "nvidia_smi_unavailable"

    return parse_nvidia_smi_csv_output(completed.stdout)


def collect_system_snapshot(
    *,
    providers: Mapping[str, str] | None = None,
    monotonic_seconds: float | None = None,
    timestamp_utc: str | None = None,
    subprocess_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> SystemMetricsSnapshot:
    """Collect one privacy-safe host/process/GPU snapshot.

    Future adapters can extend GPU collection for non-CUDA runtimes such as MLX
    without changing the public snapshot/summary contract.
    """

    error_category: str | None = None
    host_metrics, host_error = _collect_host_metrics()
    if host_error is not None:
        error_category = host_error

    process_name, process_rss_mb, process_error = _collect_process_metrics()
    if error_category is None and process_error is not None:
        error_category = process_error

    gpu_metrics, gpu_error = _collect_gpu_metrics(subprocess_runner=subprocess_runner)
    if error_category is None and gpu_error is not None:
        error_category = gpu_error

    return SystemMetricsSnapshot(
        timestamp_utc=timestamp_utc or _utc_now_iso(),
        monotonic_seconds=(time.monotonic() if monotonic_seconds is None else monotonic_seconds),
        providers={str(key): str(value) for key, value in (providers or {}).items()},
        cpu_percent=host_metrics.get("cpu_percent"),
        ram_total_mb=host_metrics.get("ram_total_mb"),
        ram_used_mb=host_metrics.get("ram_used_mb"),
        ram_available_mb=host_metrics.get("ram_available_mb"),
        process_name=process_name,
        process_rss_mb=process_rss_mb,
        gpu_index=gpu_metrics.get("gpu_index"),
        gpu_name_hash=gpu_metrics.get("gpu_name_hash"),
        vram_total_mb=gpu_metrics.get("vram_total_mb"),
        vram_used_mb=gpu_metrics.get("vram_used_mb"),
        gpu_util_percent=gpu_metrics.get("gpu_util_percent"),
        gpu_memory_util_percent=gpu_metrics.get("gpu_memory_util_percent"),
        gpu_power_watts=gpu_metrics.get("gpu_power_watts"),
        error_category=error_category,
    )


def summarize_system_samples(samples: Sequence[SystemMetricsSnapshot]) -> SystemMetricsSummary:
    if not samples:
        return SystemMetricsSummary()

    first = samples[0]
    last = samples[-1]
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

    def _collect_once(self) -> None:
        self.samples.append(self.collector(providers=self._providers))

    def _run(self) -> None:
        while not self._stop_event.wait(self.sample_interval_s):
            self._collect_once()

    def start(self, *, providers: Mapping[str, str] | None = None) -> None:
        self.samples = []
        self._providers = {str(key): str(value) for key, value in (providers or {}).items()}
        self._stop_event = threading.Event()
        self._collect_once()
        if self.sample_interval_s > 0:
            self._thread = threading.Thread(
                target=self._run,
                name="lmstudio-system-metrics",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, providers: Mapping[str, str] | None = None) -> SystemMetricsSummary:
        if providers is not None:
            self._providers = {str(key): str(value) for key, value in providers.items()}
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self.sample_interval_s * 2, 1.0))
            self._thread = None
        self._collect_once()
        return summarize_system_samples(self.samples)


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
    "SystemMetricsSampler",
    "SystemMetricsSnapshot",
    "SystemMetricsSummary",
    "collect_system_snapshot",
    "parse_nvidia_smi_csv_output",
    "summarize_system_samples",
    "write_system_telemetry_artifacts",
]
