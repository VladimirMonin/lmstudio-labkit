from __future__ import annotations

from pathlib import Path

import yaml

from lmstudio_labkit import BenchmarkConfig, plan_matrix

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "experiments/lmstudio/structured_matrix/configs"


def test_l3_20_offline_configs_do_not_allow_live() -> None:
    for name in [
        "matrix.l3_20_postprocessing_tiny.offline.yaml",
        "matrix.l3_20_postprocessing_screening.offline.yaml",
        "matrix.l3_20_postprocessing_overnight.example.yaml",
    ]:
        payload = yaml.safe_load(CONFIG_DIR.joinpath(name).read_text())
        assert payload["safety"]["live"] is False
        assert payload["safety"]["allow_model_loads"] is False
        assert payload["safety"]["allow_remote_base_url"] is False
        assert payload["safety"]["allow_raw_prompt_response_artifacts"] is False


def test_l3_20_tiny_config_plans_cells() -> None:
    config = BenchmarkConfig.from_file(CONFIG_DIR / "matrix.l3_20_postprocessing_tiny.offline.yaml")
    plan = plan_matrix(config)
    assert len(plan.cells) == 4
    assert plan.planner_summary()["live"] is False
