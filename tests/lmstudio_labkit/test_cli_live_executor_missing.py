from __future__ import annotations

import json
from pathlib import Path

import pytest
from lmstudio_labkit.cli import main as cli_main

LIVE_CONFIG = "experiments/lmstudio/structured_matrix/configs/matrix.live_small_text.e2b_e4b.yaml"
LIVE_CONFIG_12B = (
    "experiments/lmstudio/structured_matrix/configs/matrix.live_small_text.e2b_e4b_12b.yaml"
)


def test_live_small_text_config_can_be_planned_offline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        cli_main(
            [
                "plan",
                "--config",
                LIVE_CONFIG,
                "--output-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    run_dir = tmp_path / "matrix_live_small_text_e2b_e4b"

    assert payload["status"] == "ok"
    assert payload["mode"] == "plan"
    assert (run_dir / "planner_summary.json").exists()
    summary = json.loads((run_dir / "planner_summary.json").read_text(encoding="utf-8"))
    assert summary["live"] is False
    assert summary["cell_count"] == 2
    assert summary["safety_budget"]["live"] is True
    assert summary["safety_budget"]["allow_model_loads"] is True


def test_live_small_12b_config_can_be_loaded() -> None:
    from lmstudio_labkit.benchmarks import BenchmarkConfig

    config = BenchmarkConfig.from_file(LIVE_CONFIG_12B)

    assert config.safety.live is True
    assert config.safety.allow_model_loads is True
    assert [model.model_key for model in config.models] == [
        "gemma4_e2b_q4km",
        "gemma4_e4b_q4km",
        "gemma4_12b_qat",
    ]
    assert [model.model_id for model in config.models] == [
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
        "google/gemma-4-12b-qat",
    ]
    assert config.tasks[0].language == "ru_ru"
    assert config.tasks[0].language_policy == "strict_ru"
    assert config.safety.max_requests == 3


def test_live_profile_fails_without_host_managed_executor(tmp_path: Path) -> None:
    with pytest.raises(
        SystemExit,
        match="live profile is valid, but no host-managed executor was provided",
    ):
        cli_main(
            [
                "run",
                "--config",
                LIVE_CONFIG,
                "--output-root",
                str(tmp_path),
                "--profile",
                "live-small",
                "--live",
                "--allow-model-loads",
            ]
        )
