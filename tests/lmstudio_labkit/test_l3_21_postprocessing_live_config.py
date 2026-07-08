from __future__ import annotations

from pathlib import Path

from lmstudio_labkit.benchmarks import BenchmarkConfig

from lmstudio_labkit import benchmarks

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (
    ROOT
    / "experiments/lmstudio/structured_matrix/configs/matrix.l3_21_postprocessing_screening.live.yaml"
)


def test_l3_21_postprocessing_live_config_scope_is_bounded() -> None:
    config = BenchmarkConfig.from_file(CONFIG)
    plan = benchmarks._build_matrix_plan(config)

    assert [model.model_id for model in config.models] == [
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
    ]
    assert len(plan.cells) == 32
    assert config.safety.live is True
    assert config.safety.allow_model_loads is True
    assert config.safety.allow_model_downloads is False
    assert config.safety.allow_raw_prompt_response_artifacts is False
    assert config.safety.allow_image_live is False
    assert config.safety.allow_stress is False
    assert config.axes["execution_mode"] == ("cold_per_request",)
    assert config.axes["cache_mode"] == ("none",)
    assert config.axes["execution_target"] == ("live_small",)
    assert config.axes["response_schema_complexity"] == ("simple", "blocks")
    assert config.axes["retry_policy"] == ("off", "retry1")
    assert "session_loaded" not in config.axes["execution_mode"]
    assert "warmup_first" not in config.axes["cache_mode"]
    assert "complex" not in config.axes["response_schema_complexity"]


def test_l3_21_postprocessing_live_cells_keep_text_only_no_parallel() -> None:
    config = BenchmarkConfig.from_file(CONFIG)
    plan = benchmarks._build_matrix_plan(config)

    assert {cell.axes["modality"] for cell in plan.cells} == {"text"}
    assert {cell.axes["lmstudio_parallel"] for cell in plan.cells} == {"1"}
    assert {cell.axes["app_concurrency"] for cell in plan.cells} == {"1"}
    assert {cell.axes["queue_pressure_mode"] for cell in plan.cells} == {"off"}
    assert {cell.axes["resource_telemetry_mode"] for cell in plan.cells} == {"timing_only"}
