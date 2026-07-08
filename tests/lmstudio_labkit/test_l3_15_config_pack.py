from __future__ import annotations

from pathlib import Path

import yaml
from lmstudio_labkit.suites import preflight_suite

from lmstudio_labkit import BenchmarkConfig, plan_matrix

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "experiments" / "lmstudio" / "structured_matrix" / "configs"
SUITE_DIR = ROOT / "experiments" / "lmstudio" / "structured_matrix" / "suites"
IMAGE_MANIFEST = (
    ROOT / "experiments" / "lmstudio" / "structured_matrix" / "datasets" / "image" / "manifest.yaml"
)


def test_l3_15_text_quality_suite_preflights_without_live() -> None:
    result = preflight_suite(SUITE_DIR / "l3_15_text_quality_screening.yaml")

    assert result["status"] == "pass"
    assert [item["run_id"] for item in result["results"]] == [
        "matrix_text_ru_tiny_e2b_e4b",
        "matrix_text_ru_screening_e2b_e4b",
    ]


def test_throughput_config_contains_cache_and_parallel_axes_without_live() -> None:
    config = BenchmarkConfig.from_file(CONFIG_DIR / "matrix.throughput_text_ru.e2b_e4b.yaml")
    plan = plan_matrix(config)

    assert config.safety.live is False
    assert config.safety.allow_model_loads is False
    assert config.axes["cache_mode"] == ("none", "warmup_first", "prompt_prefix_reuse")
    assert config.axes["lmstudio_parallel"] == ("1", "2")
    assert config.axes["app_concurrency"] == ("1", "2")
    assert "chunk_count" not in config.axes
    assert len(plan.cells) > 0


def test_image_manifest_is_synthetic_public_safe_contract() -> None:
    manifest = yaml.safe_load(IMAGE_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["asset_status"] == "synthetic_public_safe"
    assert manifest["resize_policy"]["mode"] == "fit_max_side"
    assert manifest["resize_policy"]["crop"] is False
    assert manifest["resize_policy"]["default_max_side"] == 1024
    assert manifest["resize_policy"]["fallback_max_side"] == 512
    assert manifest["resize_policy"]["jpeg_quality"] == 85
    assert len(manifest["fixtures"]) == 6
    assert all(item["status"] == "ready" for item in manifest["fixtures"])
    assert all(item["synthetic"] is True for item in manifest["fixtures"])
    assert "image_hash" in manifest["report_fields"]
