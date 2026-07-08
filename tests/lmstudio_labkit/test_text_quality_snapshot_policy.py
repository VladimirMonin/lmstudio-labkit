from __future__ import annotations

import json
from pathlib import Path

from lmstudio_labkit.live_bridge import LiveBridgeOptions
from lmstudio_labkit.snapshots import export_latest_text_remote_snapshot

from lmstudio_labkit import BenchmarkConfig, LiveBridgeTransport, run_matrix


def warning_payload() -> dict[str, object]:
    return {
        "run_id": "snapshot_policy_warning",
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
                "task_id": "simple_warning",
                "family": "simple_flat",
                "modality": "text",
                "language": "ru_ru",
                "language_policy": "strict_ru",
                "structure_complexity": "simple",
                "volume": "single",
                "prompt": "Synthetic Russian prompt",
                "schema": {
                    "type": "object",
                    "required": ["id", "summary"],
                    "additionalProperties": False,
                    "properties": {"id": {"const": 0}, "summary": {"type": "string"}},
                },
                "expected_ids": [0],
                "id_paths": ["id"],
                "expected_output": {"id": 0, "summary": "Кратко"},
                "min_length_ratio": 0.1,
                "max_length_ratio": 1.0,
                "length_ratio_policy": {"mode": "warning"},
            }
        ],
        "axes": {
            "modality": ["text"],
            "language": ["ru_ru"],
            "structure_complexity": ["simple"],
            "volume": ["single"],
            "context_tier": ["8192"],
            "schema_variant": ["hardened_const"],
            "retry_policy": ["off"],
            "execution_mode": ["cold_per_request"],
            "cache_mode": ["none"],
            "execution_target": ["remote_link"],
            "resource_telemetry_mode": ["timing_only"],
        },
        "safety": {"live": True, "max_requests": 1, "max_models": 1, "max_repeats": 1},
    }


def test_text_quality_snapshot_exports_length_ratio_warnings(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(warning_payload())
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
            executor=lambda plan: json.dumps(
                {"id": 0, "summary": "Очень длинное русское резюме для warning проверки"},
                ensure_ascii=False,
            ),
            options=options,
        ),
        live_options=options,
    )

    result = export_latest_text_remote_snapshot(artifacts.output_dir, tmp_path / "latest")
    snapshot = json.loads(Path(result["snapshot"]).read_text(encoding="utf-8"))
    report = Path(result["report"]).read_text(encoding="utf-8")

    assert snapshot["hard_fail_count"] == 0
    assert snapshot["warning_count"] == 1
    assert snapshot["length_ratio_warning_count"] == 1
    assert snapshot["warning_categories"] == {"too_long": 1}
    assert snapshot["length_ratio_failures"]["count"] == 1
    assert snapshot["length_ratio_failures"]["task_ids"] == ["simple_warning"]
    assert "hard_fail_count" in report
    assert "warning_count" in report
    assert "length_ratio_warning_count" in report
    assert "length_ratio_failures" in report
    assert "Synthetic Russian prompt" not in report
