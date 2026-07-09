from __future__ import annotations

from pathlib import Path

import yaml
from lmstudio_labkit.benchmarks import _build_matrix_plan

from lmstudio_labkit import BenchmarkConfig

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "experiments/lmstudio/structured_matrix/configs"
IMAGE_DIR = ROOT / "experiments/lmstudio/structured_matrix/datasets/image"
SUITE_PATH = (
    ROOT
    / "experiments/lmstudio/structured_matrix/suites/l3_30_gemma_vision_matrix_preparation.yaml"
)
ASSET_PACK_PATH = IMAGE_DIR / "l330_gemma_vision_asset_pack.yaml"
DECISION_RECORD_PATH = (
    ROOT
    / "experiments/lmstudio/results_summaries/l3_30_gemma_vision_matrix_preparation_decision_record.md"
)

GEMMA_MODELS = {
    "google/gemma-4-e2b",
    "google/gemma-4-e4b",
    "google/gemma-4-12b-qat",
    "google/gemma-4-26b-a4b-qat",
}


def _load_config(name: str) -> BenchmarkConfig:
    return BenchmarkConfig.from_file(CONFIG_DIR / name)


def _model_ids(config: BenchmarkConfig) -> set[str]:
    return {model.model_id for model in config.models}


def test_l3_30_asset_pack_selects_ten_grounded_public_safe_assets() -> None:
    payload = yaml.safe_load(ASSET_PACK_PATH.read_text(encoding="utf-8"))

    assert payload["manifest_id"] == "l3_30_gemma_vision_asset_pack"
    assert payload["asset_status"] == "synthetic_public_safe"
    assert payload["selected_fixture_count"] == 10
    assert payload["resize_policy"] == {
        "mode": "fit_max_side",
        "crop": False,
        "primary_profile": "max_side_1024",
        "fallback_profile": "max_side_512",
        "original_size_default": False,
        "stored_format": "webp",
        "hash_algorithm": "sha256",
    }
    assert set(payload["schema_levels"]) == {"simple", "medium", "complex"}
    assert payload["schema_levels"]["complex"]["live_status"] == "prepared_only_not_first_live_run"

    assets = payload["assets"]
    assert len(assets) == 10
    for asset in assets:
        assert asset["file_name"].endswith(".webp")
        assert (IMAGE_DIR / asset["file_name"]).exists()
        assert (IMAGE_DIR / asset["expected_file"]).exists()
        assert asset["privacy"] == {"synthetic": True, "raw_public_safe": True}
        assert asset["ground_truth"]["identity_expected"] is False
        assert asset["ground_truth"]["sensitive_attributes_expected"] is False
        assert asset["ground_truth"]["private_product_expected"] is False
        assert asset["description"]
        assert asset["visible_text_examples"]


def test_l3_30_capability_gate_is_gemma_text_only_and_plans_zero_image_cells() -> None:
    config = _load_config("matrix.l3_30a_gemma_vision_capability_gate.yaml")
    plan = _build_matrix_plan(config)

    assert _model_ids(config) == GEMMA_MODELS
    assert {model.supported_modalities for model in config.models} == {("text",)}
    assert len(plan.cells) == 0
    assert plan.skip_reasons == {"unsupported_modality": 4}
    assert config.safety.live is False
    assert config.safety.allow_model_loads is False
    assert config.safety.allow_image_live is False
    assert config.safety.allow_raw_prompt_response_artifacts is False


def test_l3_30_prepared_matrix_contains_full_future_contract_but_no_current_image_cells() -> None:
    config = _load_config("matrix.l3_30b_gemma_vision_prepared_matrix.yaml")
    plan = _build_matrix_plan(config)

    assert _model_ids(config) == GEMMA_MODELS
    assert {model.supported_modalities for model in config.models} == {("text",)}
    assert len(config.tasks) == 60  # 10 assets x 2 output languages x 3 JSON levels.
    assert len(plan.cells) == 0
    assert plan.skip_reasons == {"unsupported_modality": 240}
    assert set(config.axes["resize_profile"]) == {"max_side_1024", "max_side_512"}
    assert {task.language for task in config.tasks} == {"ru_ru", "en_en"}
    assert {task.response_schema_complexity for task in config.tasks} == {
        "simple",
        "medium",
        "complex",
    }
    assert config.safety.max_requests == 160
    assert config.safety.live is False
    assert config.safety.allow_image_live is False

    complex_tasks = [task for task in config.tasks if task.response_schema_complexity == "complex"]
    assert complex_tasks
    assert all("prepared_only_complex" in task.tags for task in complex_tasks)
    assert {task.manual_review_policy for task in complex_tasks} == {"vision_prepared_only_complex"}


def test_l3_30_suite_and_decision_record_are_prepared_only() -> None:
    suite = yaml.safe_load(SUITE_PATH.read_text(encoding="utf-8"))
    text = DECISION_RECORD_PATH.read_text(encoding="utf-8")

    assert suite["suite_id"] == "l3_30_gemma_vision_matrix_preparation"
    assert [entry["id"] for entry in suite["configs"]] == [
        "vision_capability_gate",
        "vision_prepared_matrix",
    ]
    assert all(
        entry["expected_planned_requests_current_registry"] == 0 for entry in suite["configs"]
    )
    assert "Do not run image live from this prepared-only suite" in "\n".join(suite["notes"])
    assert "no_image_route_available" in text
    assert "no live image inference was run" in text
    assert "max_side_1024" in text
    assert "max_side_512" in text
