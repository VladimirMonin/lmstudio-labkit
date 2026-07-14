from __future__ import annotations

import json
from pathlib import Path

from libs.lmstudio_managed.metrics import (
    GpuDeviceSample,
    GpuTelemetryEvidenceLevel,
    GpuTelemetrySample,
    TelemetryStatus,
)
from tools.lmstudio_lab.managed_runner import ManagedLabRunner
from tools.lmstudio_lab.metrics import (
    PHASE_MARKER_ORDER,
    PhaseConfidence,
    PhaseDerivationMethod,
    PhaseMarker,
    PhaseMarkerRecord,
    validate_phase_marker_order,
)
from tools.lmstudio_lab.model_lifecycle import run_exact_model_operation
from tools.lmstudio_lab.report import render_phase_metrics_report
from tools.lmstudio_lab.system_metrics import (
    SystemMetricsSampler,
    SystemMetricsSnapshot,
    summarize_system_samples,
)


def _device(
    index: int,
    used_mb: float | None,
    *,
    status: TelemetryStatus = TelemetryStatus.AVAILABLE,
) -> GpuDeviceSample:
    return GpuDeviceSample(
        device_index=index,
        device_id_hash=f"sha256:device-{index}",
        evidence_level=GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY,
        status=status,
        vram_used_mb=used_mb,
    )


def _snapshot(
    marker: PhaseMarker,
    monotonic_seconds: float,
    *devices: GpuDeviceSample,
    ram_used_mb: float | None = None,
) -> SystemMetricsSnapshot:
    telemetry = GpuTelemetrySample(
        timestamp_utc="2026-07-14T00:00:00Z",
        evidence_level=(
            GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY
            if devices
            else GpuTelemetryEvidenceLevel.UNAVAILABLE
        ),
        status=TelemetryStatus.AVAILABLE if devices else TelemetryStatus.UNAVAILABLE,
        devices=tuple(devices),
        adapter="fake",
    )
    return SystemMetricsSnapshot(
        timestamp_utc="2026-07-14T00:00:00Z",
        monotonic_seconds=monotonic_seconds,
        ram_used_mb=ram_used_mb,
        vram_used_mb=devices[0].vram_used_mb if devices else None,
        gpu_telemetry=telemetry,
        gpu_evidence_level=telemetry.evidence_level,
        phase=PhaseMarkerRecord(
            marker=marker,
            sequence=PHASE_MARKER_ORDER.index(marker),
            derivation_method=PhaseDerivationMethod.DIRECT_EVENT,
            confidence=PhaseConfidence.HIGH,
        ),
    )


def test_phase_marker_order_is_canonical_and_rejects_regressions() -> None:
    records = tuple(
        PhaseMarkerRecord(
            marker=marker,
            sequence=index,
            derivation_method=PhaseDerivationMethod.DIRECT_EVENT,
            confidence=PhaseConfidence.HIGH,
        )
        for index, marker in enumerate(PHASE_MARKER_ORDER)
    )

    assert validate_phase_marker_order(records) is True
    assert validate_phase_marker_order((records[2], records[1])) is False
    assert tuple(marker.value for marker in PHASE_MARKER_ORDER) == (
        "clean_baseline",
        "load_started",
        "loaded_idle",
        "request_dispatched",
        "prefill_active",
        "first_token",
        "decode_active",
        "concurrent_peak",
        "batch_completed",
        "post_batch_idle",
        "unload_started",
        "after_unload_global_zero",
    )


def test_phase_summary_aggregates_multi_device_peaks_and_unavailable_values() -> None:
    samples = (
        _snapshot(
            PhaseMarker.CLEAN_BASELINE,
            1.0,
            _device(0, 100.0),
            _device(1, 200.0),
            ram_used_mb=1000.0,
        ),
        _snapshot(
            PhaseMarker.CONCURRENT_PEAK,
            2.0,
            _device(0, 700.0),
            _device(1, 900.0),
            ram_used_mb=1500.0,
        ),
        _snapshot(
            PhaseMarker.CONCURRENT_PEAK,
            3.0,
            _device(0, 800.0),
            _device(1, None, status=TelemetryStatus.ERROR),
            ram_used_mb=None,
        ),
    )

    summary = summarize_system_samples(samples, configured_sample_interval_s=0.5)

    assert summary.phase_order_valid is True
    assert summary.configured_sample_interval_s == 0.5
    assert summary.actual_sample_interval_s == 1.0
    phase = next(item for item in summary.phase_summaries if item.marker == "concurrent_peak")
    assert phase.sample_count == 2
    assert phase.ram_peak_mb == 1500.0
    assert [(item.device_index, item.vram_peak_mb) for item in phase.devices] == [
        (0, 800.0),
        (1, 900.0),
    ]
    assert phase.devices[1].unavailable_sample_count == 1
    assert summary.memory_evidence_valid is False


def test_timestamp_regression_and_missing_timestamp_invalidate_memory_evidence() -> None:
    valid_equal = (
        _snapshot(PhaseMarker.CLEAN_BASELINE, 1.0, _device(0, 100.0)),
        _snapshot(PhaseMarker.LOADED_IDLE, 1.0, _device(0, 200.0)),
    )
    regressing = (
        _snapshot(PhaseMarker.CLEAN_BASELINE, 2.0, _device(0, 100.0)),
        _snapshot(PhaseMarker.LOADED_IDLE, 1.0, _device(0, 200.0)),
    )
    missing = (
        _snapshot(PhaseMarker.CLEAN_BASELINE, 1.0, _device(0, 100.0)),
        _snapshot(PhaseMarker.LOADED_IDLE, 2.0, _device(0, 200.0)),
    )
    missing[1].monotonic_seconds = None

    equal_summary = summarize_system_samples(valid_equal)
    regressing_summary = summarize_system_samples(regressing)
    missing_summary = summarize_system_samples(missing)

    assert equal_summary.timestamp_order_valid is True
    assert equal_summary.actual_sample_interval_s == 0.0
    assert regressing_summary.timestamp_order_valid is False
    assert regressing_summary.actual_sample_interval_s is None
    assert regressing_summary.memory_evidence_valid is False
    assert missing_summary.timestamp_order_valid is False
    assert missing_summary.memory_evidence_valid is False


def test_typed_gpu_error_and_partial_device_error_invalidate_memory_evidence() -> None:
    typed_error = _snapshot(PhaseMarker.CLEAN_BASELINE, 1.0)
    typed_error.gpu_telemetry = GpuTelemetrySample(
        timestamp_utc="2026-07-14T00:00:00Z",
        evidence_level=GpuTelemetryEvidenceLevel.UNAVAILABLE,
        status=TelemetryStatus.ERROR,
        error_category="nvml_error",
    )
    partial = _snapshot(
        PhaseMarker.CLEAN_BASELINE,
        1.0,
        _device(0, 100.0),
        _device(1, None, status=TelemetryStatus.ERROR),
    )

    assert summarize_system_samples((typed_error,)).memory_evidence_valid is False
    assert summarize_system_samples((partial,)).memory_evidence_valid is False


def test_sampler_collector_failures_are_recorded_without_raising() -> None:
    calls = 0

    def failing_collector(*, providers):
        nonlocal calls
        calls += 1
        raise RuntimeError("private collector detail")

    sampler = SystemMetricsSampler(sample_interval_s=0, collector=failing_collector)

    sampler.start(providers={"lmstudio_local": "test"})
    sampler.mark_phase(PhaseMarker.REQUEST_DISPATCHED)
    summary = sampler.stop(providers={"lmstudio_local": "test"})

    assert calls == 3
    assert summary.sample_count == 3
    assert summary.sampler_failure_count == 3
    assert summary.telemetry_valid is False
    assert all(sample.error_category == "sampler_error" for sample in sampler.samples)
    assert "private collector detail" not in json.dumps(summary.to_dict())


def test_managed_runner_sampler_failure_does_not_change_business_outcome(tmp_path: Path) -> None:
    class BrokenSampler:
        samples: list[SystemMetricsSnapshot] = []

        def start(self, *, providers=None) -> None:
            raise RuntimeError("start failed")

        def stop(self, *, providers=None):
            raise RuntimeError("stop failed")

    runner = ManagedLabRunner(lambda request: None, system_sampler=BrokenSampler())

    result = runner.run_with_system_metrics(lambda: {"status": "ok"}, tmp_path)

    assert result["status"] == "ok"
    assert result["telemetry_valid"] is False
    assert result["sampler_failure_count"] == 2
    written = json.loads((tmp_path / "system_summary.json").read_text(encoding="utf-8"))
    assert written["telemetry_valid"] is False
    assert written["sampler_failure_count"] == 2


def test_managed_runner_phase_callback_failure_invalidates_telemetry_only(
    tmp_path: Path,
) -> None:
    class PhaseFailingSampler:
        samples: list[SystemMetricsSnapshot]

        def __init__(self) -> None:
            self.samples = []

        def start(self, *, providers=None) -> None:
            self.samples = []

        def mark_phase(self, marker, derivation_method, confidence) -> None:
            raise RuntimeError("private phase detail")

        def stop(self, *, providers=None):
            return summarize_system_samples(self.samples)

    runner = ManagedLabRunner(lambda request: None, system_sampler=PhaseFailingSampler())

    result = runner.run_with_system_metrics(
        lambda: runner.mark_system_phase(PhaseMarker.REQUEST_DISPATCHED) or {"status": "ok"},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert result["telemetry_valid"] is False
    assert result["sampler_failure_count"] == 1
    assert "private phase detail" not in json.dumps(result)
    written = json.loads((tmp_path / "system_summary.json").read_text(encoding="utf-8"))
    assert written["telemetry_valid"] is False
    assert written["sampler_failure_count"] == 1


def test_exact_lifecycle_emits_direct_phase_markers_in_order() -> None:
    raw_instance_id = "private-instance"
    calls = 0

    def transport(request, timeout_s: float) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps(
                {
                    "instance_id": raw_instance_id,
                    "context_length": 8192,
                    "parallel": 1,
                }
            ).encode()
        if calls == 2:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e2b",
                            "loaded_instances": [{"instance_id": raw_instance_id}],
                        }
                    ]
                }
            ).encode()
        if calls == 3:
            return b'{"status":"ok"}'
        if calls == 4:
            return json.dumps(
                {"models": [{"key": "google/gemma-4-e2b", "loaded_instances": []}]}
            ).encode()
        raise AssertionError("unexpected transport call")

    markers: list[tuple[PhaseMarker, PhaseDerivationMethod, PhaseConfidence]] = []

    result = run_exact_model_operation(
        "http://127.0.0.1:1234",
        model_id="google/gemma-4-e2b",
        context_length=8192,
        parallel=1,
        operation=lambda _state: {"status": "ok"},
        transport=transport,
        phase_callback=lambda marker, derivation_method, confidence: markers.append(
            (marker, derivation_method, confidence)
        ),
    )

    assert result["status"] == "ok"
    assert [marker for marker, _method, _confidence in markers] == [
        PhaseMarker.LOAD_STARTED,
        PhaseMarker.LOADED_IDLE,
        PhaseMarker.REQUEST_DISPATCHED,
        PhaseMarker.BATCH_COMPLETED,
        PhaseMarker.POST_BATCH_IDLE,
        PhaseMarker.UNLOAD_STARTED,
        PhaseMarker.AFTER_UNLOAD_GLOBAL_ZERO,
    ]
    assert markers[2][1:] == (
        PhaseDerivationMethod.ATTRIBUTABLE_REQUEST_INTERVAL,
        PhaseConfidence.MEDIUM,
    )
    assert markers[4][1:] == (
        PhaseDerivationMethod.UNAVAILABLE,
        PhaseConfidence.UNAVAILABLE,
    )
    assert all(
        method == PhaseDerivationMethod.DIRECT_EVENT
        for index, (_, method, _) in enumerate(markers)
        if index not in {2, 4}
    )


def test_exact_lifecycle_does_not_claim_global_zero_while_another_model_is_loaded() -> None:
    calls = 0

    def models_payload(target_loaded: bool) -> bytes:
        return json.dumps(
            {
                "models": [
                    {
                        "key": "google/gemma-4-e2b",
                        "loaded_instances": (
                            [{"instance_id": "private-target"}] if target_loaded else []
                        ),
                    },
                    {
                        "key": "other/model",
                        "loaded_instances": [{"instance_id": "private-other"}],
                    },
                ]
            }
        ).encode()

    def transport(request, timeout_s: float) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps(
                {"instance_id": "private-target", "context_length": 8192, "parallel": 1}
            ).encode()
        if calls == 2:
            return models_payload(True)
        if calls == 3:
            return b'{"status":"ok"}'
        if calls == 4:
            return models_payload(False)
        raise AssertionError("unexpected transport call")

    markers: list[PhaseMarker] = []
    result = run_exact_model_operation(
        "http://127.0.0.1:1234",
        model_id="google/gemma-4-e2b",
        context_length=8192,
        parallel=1,
        operation=lambda _state: {"status": "ok"},
        transport=transport,
        phase_callback=lambda marker, _method, _confidence: markers.append(marker),
    )

    assert result["cleanup_status"] == "cleanup_verified"
    assert result["final_loaded_instances"] == 0
    assert result["final_global_loaded_instances"] == 1
    assert PhaseMarker.AFTER_UNLOAD_GLOBAL_ZERO not in markers


def test_phase_report_states_precision_boundary() -> None:
    report = render_phase_metrics_report(
        {
            "telemetry_valid": False,
            "phase_order_valid": True,
            "sampler_failure_count": 1,
            "phase_summaries": [
                {
                    "marker": "prefill_active",
                    "sample_count": 0,
                    "derivation_methods": ["unavailable"],
                    "confidence_levels": ["unavailable"],
                }
            ],
        }
    )

    assert "telemetry_valid: `False`" in report
    assert "sampler_failure_count: `1`" in report
    assert "Coarse polling is never presented as precise prefill/decode evidence." in report
