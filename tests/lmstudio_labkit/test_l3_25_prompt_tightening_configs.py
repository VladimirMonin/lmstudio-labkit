from __future__ import annotations

from pathlib import Path

import yaml
from lmstudio_labkit.benchmarks import _build_matrix_plan

from lmstudio_labkit import BenchmarkConfig, plan_matrix

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "experiments/lmstudio/structured_matrix/configs"

L3_22_CONFIGS = [
    "matrix.l3_22_focused_simple_postprocessing.live.yaml",
    "matrix.l3_22_focused_simple_postprocessing.offline.yaml",
    "matrix.l3_22_simple_postprocessing_canary.e2b_e4b.yaml",
    "matrix.l3_22_simple_postprocessing_product_like.e2b_e4b.yaml",
]

L3_25_CONFIGS = [
    "matrix.l3_25_focused_simple_postprocessing.live.yaml",
    "matrix.l3_25_focused_simple_postprocessing.offline.yaml",
    "matrix.l3_25_simple_postprocessing_canary.e2b_e4b.yaml",
    "matrix.l3_25_simple_postprocessing_product_like.e2b_e4b.yaml",
    "matrix.l3_25_prompt_tightening_canary.e2b_e4b.yaml",
]


def _prompt_variants(config_name: str) -> set[str]:
    payload = yaml.safe_load(CONFIG_DIR.joinpath(config_name).read_text())
    return {task["prompt_variant"] for task in payload["tasks"]}


def test_l3_22_configs_remain_historical_strict_no_new_facts_baseline() -> None:
    for config_name in L3_22_CONFIGS:
        variants = _prompt_variants(config_name)
        assert "strict_no_new_facts" in variants
        assert "strict_no_new_facts_v2" not in variants


def test_l3_25_configs_use_tightened_transcript_cleanup_prompt() -> None:
    for config_name in L3_25_CONFIGS:
        variants = _prompt_variants(config_name)
        assert "strict_no_new_facts_v2" in variants
        assert "term_glossary" in variants


def test_l3_25_offline_config_plans_without_live_side_effects() -> None:
    config = BenchmarkConfig.from_file(
        CONFIG_DIR / "matrix.l3_25_focused_simple_postprocessing.offline.yaml"
    )
    plan = plan_matrix(config)

    assert plan.cells
    assert config.safety.live is False
    assert config.safety.allow_model_loads is False
    assert config.safety.allow_raw_prompt_response_artifacts is False


def test_l3_25_canary_is_tiny_live_shape() -> None:
    config = BenchmarkConfig.from_file(
        CONFIG_DIR / "matrix.l3_25_prompt_tightening_canary.e2b_e4b.yaml"
    )
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 6
    assert {cell.model.model_id for cell in plan.cells} == {
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
    }
    assert {cell.task.task_intent for cell in plan.cells} == {
        "transcript_cleanup",
        "term_normalization",
    }
    assert all(cell.axes["retry_policy"] == "off" for cell in plan.cells)
    assert all(cell.axes["execution_mode"] == "cold_per_request" for cell in plan.cells)
    assert all(cell.axes["cache_mode"] == "none" for cell in plan.cells)
    assert config.safety.max_requests == 8
    assert config.safety.allow_raw_prompt_response_artifacts is False


def test_l3_26_product_benchmark_is_prepared_but_bounded() -> None:
    config = BenchmarkConfig.from_file(
        CONFIG_DIR / "matrix.l3_26_product_benchmark_simple_postprocessing.e2b_e4b.yaml"
    )
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 60
    assert config.repeats == 5
    assert {cell.model.model_id for cell in plan.cells} == {
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
    }
    assert {cell.task.task_intent for cell in plan.cells} == {"transcript_cleanup"}
    assert {cell.task.response_schema_complexity for cell in plan.cells} == {"simple"}
    assert {cell.task.prompt_variant for cell in plan.cells} == {"strict_no_new_facts_v2"}
    assert all(cell.axes["retry_policy"] == "off" for cell in plan.cells)
    assert config.safety.max_requests == 60
    assert config.safety.allow_image_live is False
    assert config.safety.allow_stress is False
