from __future__ import annotations

import csv
import json
from pathlib import Path

from lmstudio_labkit.live_bridge import LiveBridgeOptions
from lmstudio_labkit.snapshots import export_latest_text_remote_snapshot

from lmstudio_labkit import BenchmarkConfig, LiveBridgeTransport, run_matrix


def remote_timing_payload() -> dict[str, object]:
    return {
        "run_id": "remote_timing_only",
        "models": [
            {
                "model_key": "fake_remote",
                "model_id": "fake/remote-text",
                "supported_modalities": ["text"],
                "supported_context_tiers": ["8192"],
            }
        ],
        "tasks": [
            {
                "task_id": "remote_text_probe",
                "family": "simple_flat",
                "modality": "text",
                "language": "en_en",
                "structure_complexity": "simple",
                "volume": "single",
                "prompt": "Synthetic prompt",
                "expected_output": {"id": "ok", "text": "Synthetic response"},
            }
        ],
        "axes": {
            "modality": ["text"],
            "language": ["en_en"],
            "structure_complexity": ["simple"],
            "volume": ["single"],
            "context_tier": ["8192"],
            "schema_variant": ["baseline_loose"],
            "retry_policy": ["off"],
            "execution_target": ["remote_link"],
            "resource_telemetry_mode": ["timing_only"],
        },
        "safety": {"live": True, "max_requests": 1, "max_models": 1, "max_repeats": 1},
    }


def test_remote_link_timing_only_does_not_require_ram_or_vram(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(remote_timing_payload())
    options = LiveBridgeOptions(
        live=True,
        allow_remote=True,
        base_url="https://example.test/private",
        max_requests=1,
    )

    artifacts = run_matrix(
        config,
        tmp_path,
        transport=LiveBridgeTransport(
            executor=lambda plan: json.dumps({"id": "ok", "text": "Synthetic response"}),
            options=options,
        ),
        live_options=options,
    )

    cell_row = next(csv.DictReader(artifacts.cell_summary.open(encoding="utf-8")))
    resource_row = next(csv.DictReader(artifacts.resource_summary.open(encoding="utf-8")))
    assert cell_row["execution_target"] == "remote_link"
    assert cell_row["resource_telemetry_mode"] == "timing_only"
    assert cell_row["resource_telemetry_status"] == "timing_only"
    assert cell_row["resource_ram_required"] == "False"
    assert cell_row["resource_vram_required"] == "False"
    assert cell_row["ram_peak_mb"] == ""
    assert cell_row["vram_peak_mb"] == ""
    assert resource_row["resource_telemetry_status"] == "timing_only"
    assert resource_row["ram_peak_mb"] == ""
    assert resource_row["vram_peak_mb"] == ""


def test_latest_snapshot_export_is_public_safe(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(remote_timing_payload())
    options = LiveBridgeOptions(
        live=True,
        allow_remote=True,
        base_url="https://example.test/private-path",
        max_requests=1,
    )
    artifacts = run_matrix(
        config,
        tmp_path / "runs",
        transport=LiveBridgeTransport(
            executor=lambda plan: json.dumps({"id": "ok", "text": "Synthetic response"}),
            options=options,
        ),
        live_options=options,
    )

    result = export_latest_text_remote_snapshot(artifacts.output_dir, tmp_path / "latest")

    assert result["status"] == "pass"
    assert Path(result["report"]).name == "report.md"
    assert (tmp_path / "latest" / "report.md").exists()
    for summary_name in ("model_summary.csv", "failure_summary.csv", "retry_summary.csv"):
        summary_path = tmp_path / "latest" / summary_name
        assert summary_path.exists()
        assert summary_path.read_text(encoding="utf-8").strip()
    assert Path(result["model_summary"]).name == "model_summary.csv"
    assert Path(result["failure_summary"]).name == "failure_summary.csv"
    assert Path(result["retry_summary"]).name == "retry_summary.csv"
    snapshot_text = Path(result["snapshot"]).read_text(encoding="utf-8")
    snapshot = json.loads(snapshot_text)
    assert snapshot["live_bridge"]["base_url_kind"] == "remote"
    assert snapshot["live_bridge"]["base_url_scheme"] == "https"
    assert snapshot["execution_targets"] == ["remote_link"]
    assert snapshot["execution_modes"] == ["cold_per_request"]
    assert snapshot["cache_modes"] == ["none"]
    assert snapshot["resource_telemetry_modes"] == ["timing_only"]
    assert snapshot["safety"]["raw_prompt_response_stored"] is False
    assert "Synthetic prompt" not in snapshot_text
    assert "Synthetic response" not in snapshot_text
    assert "example.test" not in snapshot_text
    assert str(artifacts.output_dir) not in snapshot_text
    privacy_scan = json.loads(Path(result["privacy_scan"]).read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
