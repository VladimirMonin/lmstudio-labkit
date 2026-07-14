from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from tools.lmstudio_lab import system_metrics as system_metrics_module

from lmstudio_managed.metrics import SystemSummary as ManagedSystemSummary
from tools import lmstudio_benchmark, lmstudio_lab

ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:[\\/][^\"\r\n]+"),
    re.compile(r"\\\\[^\"\r\n]+[\\/][^\"\r\n]+"),
    re.compile(r"/(?:Users|home)/[^\"\r\n]+"),
)


def _assert_no_private_paths(text: str) -> None:
    assert "C:\\Users\\Private\\LM Studio" not in text
    assert "/Users/private/lmstudio" not in text
    for pattern in ABSOLUTE_PATH_PATTERNS:
        assert pattern.search(text) is None


def _write_live_config(
    tmp_path: Path,
    *,
    dataset_id: str,
    warmup_runs: int = 0,
) -> Path:
    config_path = tmp_path / "live.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "live_json_smoke",
                "hardware_profile": "local_manual",
                "lmstudio_base_url": "http://127.0.0.1:1234",
                "allow_remote": False,
                "models": [
                    {
                        "key": "local_placeholder",
                        "model_id": "placeholder/local-model",
                        "load": {"context_length": [8192], "parallel": [1]},
                    }
                ],
                "modes": ["json_schema_single"],
                "datasets": [dataset_id],
                "repeats": 1,
                "warmup_runs": warmup_runs,
                "privacy": {
                    "store_prompt_text": False,
                    "store_response_text": False,
                    "store_prompt_hash": True,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path


def _make_fake_psutil() -> SimpleNamespace:
    class _FakeProcess:
        def __init__(self, name: str, rss_bytes: int) -> None:
            self.info = {
                "name": name,
                "memory_info": SimpleNamespace(rss=rss_bytes),
            }
            self.exe = r"C:\Users\Private\LM Studio\LM Studio.exe"
            self.cmdline = [self.exe, "--profile", "private"]
            self.cwd = r"C:\Users\Private\LM Studio"
            self.username = "private-user"
            self.environ = {"SECRET_TOKEN": "private"}

    return SimpleNamespace(
        cpu_percent=lambda interval=None: 37.5,
        virtual_memory=lambda: SimpleNamespace(
            total=16 * 1024 * 1024 * 1024,
            used=10 * 1024 * 1024 * 1024,
            available=6 * 1024 * 1024 * 1024,
        ),
        process_iter=lambda attrs=None: [
            _FakeProcess("python.exe", 100 * 1024 * 1024),
            _FakeProcess("LM Studio.exe", 512 * 1024 * 1024),
        ],
    )


def test_parse_nvidia_smi_csv_output_is_deterministic_and_hashes_gpu_name() -> None:
    csv_text = (
        "0, NVIDIA GeForce RTX 4090, 1024, 24564, 76, 12, 123.45\n"
        "1, NVIDIA GeForce RTX 4080, 2048, 16384, 50, 10, 111.0\n"
    )

    parsed, error_category = lmstudio_lab.parse_nvidia_smi_csv_output(csv_text)

    assert error_category is None
    assert parsed == {
        "gpu_index": 0,
        "gpu_name_hash": (f"sha256:{hashlib.sha256(b'NVIDIA GeForce RTX 4090').hexdigest()[:16]}"),
        "vram_used_mb": 1024.0,
        "vram_total_mb": 24564.0,
        "gpu_util_percent": 76.0,
        "gpu_memory_util_percent": 12.0,
        "gpu_power_watts": 123.45,
    }


def test_collect_system_snapshot_handles_missing_nvidia_smi_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_metrics_module, "psutil", _make_fake_psutil())

    def missing_runner(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    snapshot = lmstudio_lab.collect_system_snapshot(
        providers={"lmstudio_local": "live_run"},
        monotonic_seconds=12.5,
        timestamp_utc="2026-01-02T03:04:05Z",
        subprocess_runner=missing_runner,
    )

    assert snapshot.timestamp_utc == "2026-01-02T03:04:05Z"
    assert snapshot.monotonic_seconds == 12.5
    assert snapshot.providers == {"lmstudio_local": "live_run"}
    assert snapshot.cpu_percent == 37.5
    assert snapshot.ram_total_mb == pytest.approx(16384.0)
    assert snapshot.ram_used_mb == pytest.approx(10240.0)
    assert snapshot.ram_available_mb == pytest.approx(6144.0)
    assert snapshot.process_name == "lmstudio"
    assert snapshot.process_rss_mb == pytest.approx(512.0)
    assert snapshot.gpu_index is None
    assert snapshot.gpu_name_hash is None
    assert snapshot.vram_total_mb is None
    assert snapshot.error_category == "nvidia_smi_unavailable"


def test_collect_system_snapshot_keeps_process_artifact_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_metrics_module, "psutil", _make_fake_psutil())

    def fake_runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="0, NVIDIA RTX 4090, 512, 16384, 50, 25, 100.0\n",
            stderr="",
        )

    snapshot = lmstudio_lab.collect_system_snapshot(
        providers={"lmstudio_local": "privacy_check"},
        subprocess_runner=fake_runner,
    )

    serialized = json.dumps(snapshot.to_dict(), sort_keys=True)
    assert snapshot.process_name == "lmstudio"
    assert '"cmdline"' not in serialized
    assert '"cwd"' not in serialized
    assert '"username"' not in serialized
    assert '"env"' not in serialized
    assert "LM Studio.exe" not in serialized
    assert "private-user" not in serialized
    _assert_no_private_paths(serialized)


def test_system_metrics_sampler_summary_is_deterministic_with_fake_samples() -> None:
    before = lmstudio_lab.SystemMetricsSnapshot(
        timestamp_utc="2026-01-01T00:00:00Z",
        monotonic_seconds=1.0,
        ram_used_mb=1000.0,
        process_rss_mb=500.0,
        vram_used_mb=2000.0,
        gpu_util_percent=20.0,
        gpu_memory_util_percent=10.0,
        gpu_power_watts=90.0,
    )
    middle = lmstudio_lab.SystemMetricsSnapshot(
        timestamp_utc="2026-01-01T00:00:01Z",
        monotonic_seconds=2.0,
        providers={"lmstudio_local": "live_run"},
        ram_used_mb=1500.0,
        process_rss_mb=900.0,
        vram_used_mb=2600.0,
        gpu_util_percent=85.0,
        gpu_memory_util_percent=66.0,
        gpu_power_watts=140.0,
    )
    after = lmstudio_lab.SystemMetricsSnapshot(
        timestamp_utc="2026-01-01T00:00:02Z",
        monotonic_seconds=3.0,
        ram_used_mb=1200.0,
        process_rss_mb=700.0,
        vram_used_mb=2200.0,
        gpu_util_percent=35.0,
        gpu_memory_util_percent=22.0,
        gpu_power_watts=100.0,
    )
    templates = [before, after]

    def fake_collector(*, providers):
        template = templates.pop(0)
        return replace(template, providers=dict(providers))

    sampler = lmstudio_lab.SystemMetricsSampler(sample_interval_s=0, collector=fake_collector)
    sampler.start(providers={"lmstudio_local": "live_run"})
    sampler.samples.append(middle)
    summary = sampler.stop(providers={"lmstudio_local": "live_run"})

    assert len(sampler.samples) == 3
    assert summary.sample_count == 3
    assert summary.providers == {"lmstudio_local": "live_run"}
    assert summary.ram_before_mb == 1000.0
    assert summary.ram_peak_mb == 1500.0
    assert summary.ram_after_mb == 1200.0
    assert summary.process_rss_before_mb == 500.0
    assert summary.process_rss_peak_mb == 900.0
    assert summary.process_rss_after_mb == 700.0
    assert summary.vram_before_mb == 2000.0
    assert summary.vram_peak_mb == 2600.0
    assert summary.vram_after_mb == 2200.0
    assert summary.gpu_util_peak_percent == 85.0
    assert summary.gpu_memory_util_peak_percent == 66.0
    assert summary.gpu_power_peak_watts == 140.0


def test_system_metrics_summary_to_managed_summary_preserves_before_peak_after_and_to_dict() -> (
    None
):
    summary = lmstudio_lab.SystemMetricsSummary(
        sample_count=3,
        providers={"lmstudio_local": "live_run"},
        ram_before_mb=1000.0,
        ram_peak_mb=1500.0,
        ram_after_mb=1200.0,
        process_rss_before_mb=500.0,
        process_rss_peak_mb=900.0,
        process_rss_after_mb=700.0,
        vram_before_mb=2000.0,
        vram_peak_mb=2600.0,
        vram_after_mb=2200.0,
        gpu_util_peak_percent=85.0,
        gpu_memory_util_peak_percent=66.0,
        gpu_power_peak_watts=140.0,
    )

    managed = summary.to_managed_summary()

    assert isinstance(managed, ManagedSystemSummary)
    assert managed.ram_before_mb == 1000.0
    assert managed.ram_peak_mb == 1500.0
    assert managed.ram_after_mb == 1200.0
    assert managed.process_rss_before_mb == 500.0
    assert managed.process_rss_peak_mb == 900.0
    assert managed.process_rss_after_mb == 700.0
    assert managed.vram_before_mb == 2000.0
    assert managed.vram_peak_mb == 2600.0
    assert managed.vram_after_mb == 2200.0
    assert managed.gpu_util_peak_percent == 85.0
    assert managed.gpu_memory_util_peak_percent == 66.0
    assert managed.gpu_power_peak_watts == 140.0
    assert summary.to_dict() == {
        "schema_version": lmstudio_lab.SCHEMA_VERSION,
        "sample_count": 3,
        "providers": {"lmstudio_local": "live_run"},
        "ram_before_mb": 1000.0,
        "ram_peak_mb": 1500.0,
        "ram_after_mb": 1200.0,
        "process_rss_before_mb": 500.0,
        "process_rss_peak_mb": 900.0,
        "process_rss_after_mb": 700.0,
        "vram_before_mb": 2000.0,
        "vram_peak_mb": 2600.0,
        "vram_after_mb": 2200.0,
        "gpu_util_peak_percent": 85.0,
        "gpu_memory_util_peak_percent": 66.0,
        "gpu_power_peak_watts": 140.0,
        "configured_sample_interval_s": None,
        "actual_sample_interval_s": None,
        "sampler_failure_count": 0,
        "telemetry_valid": True,
        "phase_order_valid": True,
        "timestamp_order_valid": False,
        "memory_evidence_valid": False,
        "phase_summaries": (),
    }


def test_cli_live_chunked_run_writes_system_telemetry_artifacts_with_fake_sampler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
        warmup_runs=1,
    )
    sampler_instances: list[object] = []

    class FakeSystemSampler:
        def __init__(self, *, sample_interval_s: float = 1.0, collector=None) -> None:
            self.sample_interval_s = sample_interval_s
            self.collector = collector
            self.samples: list[lmstudio_lab.SystemMetricsSnapshot] = []
            self.started_providers = None
            self.stopped_providers = None
            sampler_instances.append(self)

        def start(self, *, providers=None) -> None:
            self.started_providers = providers

        def stop(self, *, providers=None) -> lmstudio_lab.SystemMetricsSummary:
            self.stopped_providers = providers
            self.samples = [
                lmstudio_lab.SystemMetricsSnapshot(
                    timestamp_utc="2026-01-01T00:00:00Z",
                    monotonic_seconds=1.0,
                    providers=dict(providers or {}),
                    cpu_percent=11.0,
                    ram_used_mb=2048.0,
                    process_name="lmstudio",
                    process_rss_mb=1024.0,
                    vram_used_mb=4096.0,
                    gpu_util_percent=20.0,
                ),
                lmstudio_lab.SystemMetricsSnapshot(
                    timestamp_utc="2026-01-01T00:00:01Z",
                    monotonic_seconds=2.0,
                    providers=dict(providers or {}),
                    cpu_percent=44.0,
                    ram_used_mb=3072.0,
                    process_name="lmstudio",
                    process_rss_mb=1536.0,
                    vram_used_mb=6144.0,
                    gpu_util_percent=75.0,
                ),
            ]
            return lmstudio_lab.SystemMetricsSummary(
                sample_count=2,
                providers=dict(providers or {}),
                ram_before_mb=2048.0,
                ram_peak_mb=3072.0,
                ram_after_mb=3072.0,
                process_rss_before_mb=1024.0,
                process_rss_peak_mb=1536.0,
                process_rss_after_mb=1536.0,
                vram_before_mb=4096.0,
                vram_peak_mb=6144.0,
                vram_after_mb=6144.0,
                gpu_util_peak_percent=75.0,
            )

    def fake_chunked_runner(config: lmstudio_lab.LiveSmokeConfig, **kwargs):
        metric = lmstudio_lab.LMStudioLabMetricRecord.from_parts(
            run_id=kwargs["run_id"],
            experiment_id=config.experiment_id,
            request_id="batch_0001_chunk_0000",
            dataset_id="blocks_json_medium_chunked",
            dataset_hash="sha256:chunked",
            model_key="local_placeholder",
            endpoint_kind="compat_chat",
            mode="json_schema_single",
            requested_context_length=8192,
            requested_parallel=1,
            app_concurrency=2,
            configured_parallel=1,
            applied_parallel=1,
            parallel_verified=None,
            queue_pressure_mode=True,
            parallel_semantics="queue_pressure",
            prompt_hash="sha256:prompt-chunked",
            response_hash="sha256:response-chunked",
            tokens=lmstudio_lab.TokenMetrics(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
            validation=lmstudio_lab.ValidationMetrics(
                json_parse_pass=True,
                schema_pass=True,
                business_pass=True,
                non_empty_text_pass=True,
                reasoning_leak=False,
                finish_reason="stop",
            ),
        )
        return lmstudio_lab.LiveChunkedSmokeOutcome(
            metrics=(metric,),
            structured_errors=(),
            batch_summary={
                "schema_version": lmstudio_lab.SCHEMA_VERSION,
                "run_id": kwargs["run_id"],
                "experiment_id": config.experiment_id,
                "dataset_id": "blocks_json_medium_chunked",
                "model_key": "local_placeholder",
                "requested_context_length": 8192,
                "requested_parallel": 1,
                "app_concurrency": 2,
                "configured_parallel": 1,
                "applied_parallel": 1,
                "parallel_verified": None,
                "queue_pressure_mode": True,
                "parallel_semantics": "queue_pressure",
                "effective_profile": "standard",
                "chunks_count": 1,
                "chunk_size_blocks": 25,
                "warmup_runs": 1,
                "warmup_is_productive": False,
                "warmup_policy": "concurrent_full_batch",
                "warmup_request_count": 1,
                "measured_batches": 1,
                "measured_request_count": 1,
                "planned_requests": 2,
                "all_chunks_pass": True,
                "batch_business_pass": True,
                "all_ids_covered": True,
                "missing_id_count": 0,
                "duplicate_id_count": 0,
                "failed_chunk_ids": [],
                "json_parse_pass_count": 1,
                "schema_pass_count": 1,
                "business_pass_count": 1,
                "reasoning_leak_count": 0,
                "finish_length_count": 0,
                "total_prompt_tokens": 10,
                "total_completion_tokens": 5,
                "total_tokens": 15,
                "warmup_wall_time_ms": 5.0,
                "parallel_batch_wall_time_ms": 10.0,
                "total_batch_wall_time_ms": 10.0,
                "avg_batch_wall_time_ms": 10.0,
                "max_batch_wall_time_ms": 10.0,
                "end_to_end_wall_time_ms": 15.0,
                "avg_end_to_end_wall_time_ms": 15.0,
                "sequential_baseline_wall_time_ms": 20.0,
                "baseline_end_to_end_wall_time_ms": 25.0,
                "speedup_vs_sequential_baseline": 2.0,
                "speedup_excluding_warmup": 2.0,
                "speedup_including_warmup": 25.0 / 15.0,
                "effective_speedup": 25.0 / 15.0,
                "raw_prompt_response_stored": False,
            },
        )

    monkeypatch.setattr(lmstudio_benchmark, "SystemMetricsSampler", FakeSystemSampler)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "run_live_chunked_structured_smoke",
        fake_chunked_runner,
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "system-live-chunked",
            "--app-concurrency",
            "2",
            "--chunked-warmup-policy",
            "concurrent_full_batch",
            "--system-sample-interval-s",
            "0.25",
        ]
    )

    assert exit_code == 0
    fake_sampler = sampler_instances[0]
    assert fake_sampler.sample_interval_s == 0.25
    assert fake_sampler.started_providers == {"lmstudio_local": "live_run"}
    assert fake_sampler.stopped_providers == {"lmstudio_local": "live_run"}

    run_dir = tmp_path / "results" / "run_system-live-chunked_live_json_smoke"
    assert (run_dir / "system_samples.jsonl").exists()
    assert (run_dir / "system_summary.json").exists()

    samples_text = (run_dir / "system_samples.jsonl").read_text(encoding="utf-8")
    summary_text = (run_dir / "system_summary.json").read_text(encoding="utf-8")
    assert '"cmdline"' not in samples_text
    assert '"username"' not in samples_text
    assert '"env"' not in samples_text
    assert '"prompt"' not in samples_text
    assert '"response"' not in samples_text
    _assert_no_private_paths(samples_text)
    _assert_no_private_paths(summary_text)

    summary_payload = json.loads(summary_text)
    assert summary_payload["ram_peak_mb"] == 3072.0
    assert summary_payload["process_rss_peak_mb"] == 1536.0
    assert summary_payload["vram_peak_mb"] == 6144.0
    assert summary_payload["gpu_util_peak_percent"] == 75.0
    batch_summary_payload = json.loads((run_dir / "batch_summary.json").read_text(encoding="utf-8"))
    assert batch_summary_payload["configured_parallel"] == 1
    assert batch_summary_payload["applied_parallel"] == 1
    assert batch_summary_payload["parallel_verified"] is None
    assert batch_summary_payload["queue_pressure_mode"] is True
    assert batch_summary_payload["parallel_semantics"] == "queue_pressure"


def test_cli_probe_concurrency_writes_system_telemetry_artifacts_with_fake_sampler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler_instances: list[object] = []

    class FakeSystemSampler:
        def __init__(self, *, sample_interval_s: float = 1.0, collector=None) -> None:
            self.sample_interval_s = sample_interval_s
            self.collector = collector
            self.samples: list[lmstudio_lab.SystemMetricsSnapshot] = []
            self.started_providers = None
            self.stopped_providers = None
            sampler_instances.append(self)

        def start(self, *, providers=None) -> None:
            self.started_providers = providers

        def stop(self, *, providers=None) -> lmstudio_lab.SystemMetricsSummary:
            self.stopped_providers = providers
            self.samples = [
                lmstudio_lab.SystemMetricsSnapshot(
                    timestamp_utc="2026-01-01T00:00:00Z",
                    monotonic_seconds=1.0,
                    providers=dict(providers or {}),
                    ram_used_mb=1024.0,
                    process_name="lmstudio",
                    process_rss_mb=768.0,
                ),
                lmstudio_lab.SystemMetricsSnapshot(
                    timestamp_utc="2026-01-01T00:00:01Z",
                    monotonic_seconds=2.0,
                    providers=dict(providers or {}),
                    ram_used_mb=1280.0,
                    process_name="lmstudio",
                    process_rss_mb=896.0,
                ),
            ]
            return lmstudio_lab.SystemMetricsSummary(
                sample_count=2,
                providers=dict(providers or {}),
                ram_before_mb=1024.0,
                ram_peak_mb=1280.0,
                ram_after_mb=1280.0,
                process_rss_before_mb=768.0,
                process_rss_peak_mb=896.0,
                process_rss_after_mb=896.0,
            )

    def fake_runner(**kwargs):
        metric = lmstudio_lab.LMStudioLabMetricRecord.from_parts(
            run_id=kwargs["run_id"],
            request_id="diag_0001",
            dataset_id="diagnostic_pair",
            dataset_hash="sha256:diag",
            model_key=kwargs["model_key"],
            model_id=kwargs["model_id"],
            endpoint_kind="compat_chat",
            mode=kwargs["diagnostic_kind"],
            app_concurrency=kwargs["app_concurrency"],
            configured_parallel=None,
            applied_parallel=kwargs.get("loaded_parallel"),
            parallel_verified=True,
            queue_pressure_mode=False,
            parallel_semantics="true_parallel",
            prompt_hash="sha256:prompt-diag",
            response_hash="sha256:response-diag",
            tokens=lmstudio_lab.TokenMetrics(
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
            ),
            validation=lmstudio_lab.ValidationMetrics(
                json_parse_pass=True,
                schema_pass=True,
                business_pass=True,
                non_empty_text_pass=True,
                reasoning_leak=False,
                finish_reason="stop",
            ),
        )
        return lmstudio_lab.LiveConcurrencyDiagnosticsOutcome(
            metrics=(metric,),
            structured_errors=(),
            summary={
                "schema_version": lmstudio_lab.SCHEMA_VERSION,
                "run_id": kwargs["run_id"],
                "diagnostic_kind": kwargs["diagnostic_kind"],
                "model_key": kwargs["model_key"],
                "model_id": kwargs["model_id"],
                "endpoint_kind": "compat_chat",
                "app_concurrency": kwargs["app_concurrency"],
                "configured_parallel": None,
                "applied_parallel": kwargs.get("loaded_parallel"),
                "parallel_verified": True,
                "parallel_semantics": "true_parallel",
                "loaded_parallel": kwargs.get("loaded_parallel"),
                "queue_pressure_mode": False,
                "request_count": 2,
                "all_requests_pass": True,
                "json_parse_pass_count": 2,
                "schema_pass_count": 2,
                "business_pass_count": 2,
                "finish_length_count": 0,
                "reasoning_leak_count": 0,
                "structured_error_count": 0,
                "total_prompt_tokens": 40,
                "total_completion_tokens": 20,
                "total_tokens": 60,
                "total_wall_time_ms": 12.0,
                "avg_request_latency_ms": 6.0,
                "max_request_latency_ms": 7.0,
                "raw_prompt_response_stored": False,
            },
        )

    monkeypatch.setattr(lmstudio_benchmark, "SystemMetricsSampler", FakeSystemSampler)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "run_live_concurrency_diagnostics",
        fake_runner,
    )

    exit_code = lmstudio_benchmark.main(
        [
            "probe-concurrency",
            "--base-url",
            "http://127.0.0.1:1234",
            "--model-id",
            "placeholder/local-model",
            "--kind",
            "structured_small_pair",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "system-probe-concurrency",
            "--loaded-parallel",
            "2",
            "--system-sample-interval-s",
            "0",
        ]
    )

    assert exit_code == 0
    fake_sampler = sampler_instances[0]
    assert fake_sampler.sample_interval_s == 0.0
    assert fake_sampler.started_providers == {"lmstudio_local": "probe_concurrency"}
    assert fake_sampler.stopped_providers == {"lmstudio_local": "probe_concurrency"}

    run_dir = tmp_path / "results" / "run_system-probe-concurrency_concurrency_diagnostics"
    assert (run_dir / "system_samples.jsonl").exists()
    assert (run_dir / "system_summary.json").exists()

    samples_text = (run_dir / "system_samples.jsonl").read_text(encoding="utf-8")
    summary_text = (run_dir / "system_summary.json").read_text(encoding="utf-8")
    assert '"cmdline"' not in samples_text
    assert '"username"' not in samples_text
    assert '"env"' not in samples_text
    assert '"prompt"' not in samples_text
    assert '"response"' not in samples_text
    _assert_no_private_paths(samples_text)
    _assert_no_private_paths(summary_text)

    summary_payload = json.loads(summary_text)
    assert summary_payload["ram_peak_mb"] == 1280.0
    assert summary_payload["process_rss_peak_mb"] == 896.0
    diagnostics_summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert diagnostics_summary["configured_parallel"] is None
    assert diagnostics_summary["applied_parallel"] == 2
    assert diagnostics_summary["parallel_verified"] is True
    assert diagnostics_summary["queue_pressure_mode"] is False
    assert diagnostics_summary["parallel_semantics"] == "true_parallel"
