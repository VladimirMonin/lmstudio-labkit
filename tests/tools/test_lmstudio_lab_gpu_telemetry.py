from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from libs.lmstudio_managed.metrics import (
    GpuProcessKind,
    GpuTelemetryEvidenceLevel,
    TelemetryStatus,
)
from tools.lmstudio_lab import system_metrics

_MIB = 1024 * 1024


class FakeNvml:
    NVML_DEVICE_MIG_ENABLE = 1
    NVML_VALUE_NOT_AVAILABLE = (1 << 64) - 1

    def __init__(self) -> None:
        self.shutdown_called = False
        self.handles = ("gpu-0", "gpu-1")

    def nvmlInit(self) -> None:
        return None

    def nvmlShutdown(self) -> None:
        self.shutdown_called = True

    def nvmlDeviceGetCount(self) -> int:
        return len(self.handles)

    def nvmlDeviceGetHandleByIndex(self, index: int) -> str:
        return self.handles[index]

    def nvmlDeviceGetIndex(self, handle: str) -> int:
        return self.handles.index(handle)

    def nvmlDeviceGetUUID(self, handle: str) -> str:
        return f"private-uuid-{handle}"

    def nvmlDeviceGetName(self, handle: str) -> str:
        return f"Private GPU {handle}"

    def nvmlDeviceGetMemoryInfo(self, handle: str) -> SimpleNamespace:
        used = 0 if handle == "gpu-0" else 4096 * _MIB
        return SimpleNamespace(total=24576 * _MIB, used=used, free=(24576 * _MIB) - used)

    def nvmlDeviceGetUtilizationRates(self, handle: str) -> SimpleNamespace:
        if handle == "gpu-1":
            raise RuntimeError("counter unsupported")
        return SimpleNamespace(gpu=0, memory=0)

    def nvmlDeviceGetPowerUsage(self, handle: str) -> int:
        if handle == "gpu-1":
            raise RuntimeError("counter unsupported")
        return 0

    def nvmlDeviceGetMigMode(self, handle: str) -> tuple[int, int]:
        return (0, 0)

    def nvmlDeviceGetComputeRunningProcesses(self, handle: str) -> list[SimpleNamespace]:
        if handle == "gpu-0":
            return [SimpleNamespace(pid=1234, usedGpuMemory=0)]
        return [SimpleNamespace(pid=9999, usedGpuMemory=128 * _MIB)]

    def nvmlDeviceGetGraphicsRunningProcesses(self, handle: str) -> list[SimpleNamespace]:
        if handle == "gpu-0":
            return [SimpleNamespace(pid=4321, usedGpuMemory=256 * _MIB)]
        return []


class FakeMigNvml(FakeNvml):
    def __init__(self) -> None:
        super().__init__()
        self.handles = ("gpu-0",)

    def nvmlDeviceGetMigMode(self, handle: str) -> tuple[int, int]:
        return (self.NVML_DEVICE_MIG_ENABLE, self.NVML_DEVICE_MIG_ENABLE)

    def nvmlDeviceGetMaxMigDeviceCount(self, handle: str) -> int:
        return 2

    def nvmlDeviceGetMigDeviceHandleByIndex(self, handle: str, index: int) -> str:
        if index == 0:
            return "mig-0"
        raise RuntimeError("empty MIG slot")

    def nvmlDeviceGetDeviceHandleFromMigDeviceHandle(self, handle: str) -> str:
        return "gpu-0"

    def nvmlDeviceGetUUID(self, handle: str) -> str:
        return f"private-uuid-{handle}"

    def nvmlDeviceGetName(self, handle: str) -> str:
        return "Private MIG Device" if handle == "mig-0" else "Private GPU"

    def nvmlDeviceGetMemoryInfo(self, handle: str) -> SimpleNamespace:
        if handle == "mig-0":
            return SimpleNamespace(total=10240 * _MIB, used=1024 * _MIB, free=9216 * _MIB)
        return super().nvmlDeviceGetMemoryInfo(handle)

    def nvmlDeviceGetComputeRunningProcesses(self, handle: str) -> list[SimpleNamespace]:
        return []

    def nvmlDeviceGetGraphicsRunningProcesses(self, handle: str) -> list[SimpleNamespace]:
        return []


class FakeDisappearingProcessNvml(FakeNvml):
    def nvmlDeviceGetComputeRunningProcesses(self, handle: str) -> list[SimpleNamespace]:
        if handle == "gpu-1":
            return [SimpleNamespace(pid=9999, usedGpuMemory=self.NVML_VALUE_NOT_AVAILABLE)]
        return super().nvmlDeviceGetComputeRunningProcesses(handle)


def test_nvml_collects_all_devices_processes_and_preserves_measured_zero() -> None:
    nvml = FakeNvml()

    sample = system_metrics.collect_gpu_telemetry(
        timestamp_utc="2026-07-14T00:00:00Z",
        nvml_module=nvml,
    )

    assert sample.status == TelemetryStatus.AVAILABLE
    assert sample.evidence_level == GpuTelemetryEvidenceLevel.NVML_PROCESS_ATTRIBUTED
    assert len(sample.devices) == 2
    first, second = sample.devices
    assert first.vram_used_mb == 0.0
    assert first.vram_free_mb == 24576.0
    assert first.gpu_util_percent == 0.0
    assert first.gpu_power_watts == 0.0
    assert [process.kind for process in first.processes] == [
        GpuProcessKind.COMPUTE,
        GpuProcessKind.GRAPHICS,
    ]
    assert first.processes[0].used_gpu_memory_mb == 0.0
    assert second.gpu_util_percent is None
    assert second.gpu_power_watts is None
    assert second.processes[0].used_gpu_memory_mb == 128.0
    assert nvml.shutdown_called is True


def test_disappearing_nvml_process_preserves_unknown_and_downgrades_evidence() -> None:
    sample = system_metrics.collect_gpu_telemetry(nvml_module=FakeDisappearingProcessNvml())

    assert sample.status == TelemetryStatus.AVAILABLE
    assert sample.evidence_level == GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY
    assert sample.devices[1].processes[0].used_gpu_memory_mb is None
    assert sample.devices[1].evidence_level == GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY


def test_nvml_enumerates_mig_devices_with_hashed_parent_identity() -> None:
    sample = system_metrics.collect_gpu_telemetry(nvml_module=FakeMigNvml())

    assert len(sample.devices) == 2
    physical, mig = sample.devices
    assert physical.mig_enabled is True
    assert physical.is_mig_device is False
    assert mig.is_mig_device is True
    assert mig.mig_device_index == 0
    assert mig.parent_device_id_hash == physical.device_id_hash
    assert mig.vram_total_mb == 10240.0


def test_nvml_without_process_queries_is_device_only() -> None:
    nvml = FakeNvml()
    nvml.nvmlDeviceGetComputeRunningProcesses = None  # type: ignore[method-assign]
    nvml.nvmlDeviceGetGraphicsRunningProcesses = None  # type: ignore[method-assign]

    sample = system_metrics.collect_gpu_telemetry(nvml_module=nvml)

    assert sample.status == TelemetryStatus.AVAILABLE
    assert sample.evidence_level == GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY
    assert all(
        device.evidence_level == GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY
        for device in sample.devices
    )
    assert all(device.processes == () for device in sample.devices)


def test_nvidia_smi_fallback_is_multi_device_and_never_process_attributed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_metrics, "_load_nvml_module", lambda: None)

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=(
                "0, GPU-private-0, Private GPU 0, 24576, 0, 24576, 0, 0, 0\n"
                "1, GPU-private-1, Private GPU 1, 16384, 1024, 15360, 50, 10, N/A\n"
            ),
            stderr="",
        )

    sample = system_metrics.collect_gpu_telemetry(subprocess_runner=runner)

    assert sample.status == TelemetryStatus.AVAILABLE
    assert sample.evidence_level == GpuTelemetryEvidenceLevel.NVIDIA_SMI_DEVICE_ONLY
    assert [device.device_index for device in sample.devices] == [0, 1]
    assert sample.devices[0].vram_used_mb == 0.0
    assert sample.devices[1].gpu_power_watts is None
    assert all(device.processes == () for device in sample.devices)


def test_nvidia_smi_fallback_orders_devices_by_index() -> None:
    sample = system_metrics.parse_nvidia_smi_devices_csv_output(
        "1, GPU-private-1, Private GPU 1, 16384, 1024, 15360, 50, 10, 90\n"
        "0, GPU-private-0, Private GPU 0, 24576, 0, 24576, 0, 0, 0\n"
    )

    assert [device.device_index for device in sample.devices] == [0, 1]


def test_malformed_nvidia_smi_fallback_returns_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_metrics, "_load_nvml_module", lambda: None)

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="broken,row\n", stderr=""
        )

    sample = system_metrics.collect_gpu_telemetry(subprocess_runner=runner)

    assert sample.status == TelemetryStatus.ERROR
    assert sample.evidence_level == GpuTelemetryEvidenceLevel.UNAVAILABLE
    assert sample.error_category == "nvidia_smi_parse_error"
    assert sample.devices == ()


def test_missing_nvml_and_nvidia_smi_returns_typed_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_metrics, "_load_nvml_module", lambda: None)

    def runner(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    sample = system_metrics.collect_gpu_telemetry(subprocess_runner=runner)

    assert sample.status == TelemetryStatus.UNAVAILABLE
    assert sample.evidence_level == GpuTelemetryEvidenceLevel.UNAVAILABLE
    assert sample.error_category == "nvidia_smi_unavailable"


def test_gpu_telemetry_serialization_is_publication_safe() -> None:
    sample = system_metrics.collect_gpu_telemetry(nvml_module=FakeNvml())

    serialized = json.dumps(sample.to_dict(), sort_keys=True)

    assert "private-uuid" not in serialized
    assert "Private GPU" not in serialized
    assert '"pid"' not in serialized
    assert "1234" not in serialized
    assert "9999" not in serialized
    assert "cmdline" not in serialized
    assert "username" not in serialized
    assert all(device.device_id_hash.startswith("sha256:") for device in sample.devices)
    assert all(
        process.process_id_hash.startswith("sha256:")
        for device in sample.devices
        for process in device.processes
    )


def test_snapshot_exposes_typed_gpu_telemetry_and_legacy_first_device_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_metrics, "psutil", None)

    snapshot = system_metrics.collect_system_snapshot(
        timestamp_utc="2026-07-14T00:00:00Z",
        monotonic_seconds=1.5,
        nvml_module=FakeNvml(),
    )

    assert snapshot.gpu_telemetry is not None
    assert snapshot.gpu_telemetry.timestamp_utc == snapshot.timestamp_utc
    assert snapshot.gpu_evidence_level == GpuTelemetryEvidenceLevel.NVML_PROCESS_ATTRIBUTED
    assert snapshot.gpu_index == 0
    assert snapshot.vram_used_mb == 0.0
    assert snapshot.vram_free_mb == 24576.0
