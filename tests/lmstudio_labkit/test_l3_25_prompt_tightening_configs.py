from __future__ import annotations

from pathlib import Path

import yaml

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
