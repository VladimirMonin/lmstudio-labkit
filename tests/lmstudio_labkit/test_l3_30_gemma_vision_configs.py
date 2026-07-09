from __future__ import annotations

from pathlib import Path

import yaml
from lmstudio_labkit.benchmarks import _build_matrix_plan

from lmstudio_labkit import BenchmarkConfig

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "experiments/lmstudio/structured_matrix/configs"
SUITE_PATH = (
    ROOT
    / "experiments/lmstudio/structured_matrix/suites/l3_30_gemma_vision_matrix_preparation.yaml"
)
REPORT_PATH = (
    ROOT / "experiments/lmstudio/results_summaries/l3_30_gemma_vision_matrix_preparation_report.md"
)

GEMMA_MODELS = {
    "google/gemma-4-e2b",
    "google/gemma-4-e4b",
    "google/gemma-4-12b-qat",
    "google/gemma-4-26b-a4b-qat",
}

NEW_CONFIGS = [
    "matrix.l3_30a_gemma_vision_asset_manifest.offline.yaml",
    "matrix.l3_30b_gemma_vision_capability_preflight.yaml",
    "matrix.l3_30c_gemma_vision_canary.prepared.yaml",
    "matrix.l3_30d_gemma_vision_screening.prepared.yaml",
    "matrix.l3_30c_gemma_vision_tiny_capability_live.yaml",
    "matrix.l3_30e_gemma_vision_task_intent_routes.prepared.yaml",
]

TASK_INTENTS = {
    "image_description",
    "ocr_visible_text",
    "ui_understanding",
    "table_extraction",
    "chart_extraction",
    "code_understanding",
    "scene_understanding",
    "slide_extraction",
}


def _config(name: str) -> BenchmarkConfig:
    return BenchmarkConfig.from_file(CONFIG_DIR / name)


def _model_ids(config: BenchmarkConfig) -> set[str]:
    return {model.model_id for model in config.models}


def _assert_visible_text_policy(task) -> None:
    assert task.expected_output["visible_text_policy"] == "preserve_original_visible_text"
    assert task.expected_output["description_language"] == "output_language"
    assert task.expected_output["summary_language"] == "output_language"
    assert task.image_ground_truth["visible_text_policy"] == "preserve_original_visible_text"


def test_l3_30_suite_order_and_config_names_match_contract() -> None:
    suite = yaml.safe_load(SUITE_PATH.read_text(encoding="utf-8"))

    assert suite["suite_id"] == "l3_30_gemma_vision_matrix_preparation"
    assert suite["suite_order"] == [
        "asset_manifest_validation",
        "capability_preflight",
        "canary_prepared",
        "screening_prepared",
        "task_intent_routes_prepared",
    ]
    assert [Path(entry["config"]).name for entry in suite["configs"]] == NEW_CONFIGS
    assert "No image live artifacts yet" in "\n".join(suite["notes"])


def test_l3_30_asset_manifest_offline_config_is_safe_fake_text_validation() -> None:
    config = _config("matrix.l3_30a_gemma_vision_asset_manifest.offline.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 1
    assert plan.skip_reasons == {}
    assert config.safety.live is False
    assert config.safety.allow_image_live is False
    assert config.safety.allow_raw_prompt_response_artifacts is False
    assert config.tasks[0].task_intent == "asset_manifest_validation"


def test_l3_30_capability_preflight_is_gemma_text_only_and_plans_zero_image_cells() -> None:
    config = _config("matrix.l3_30b_gemma_vision_capability_preflight.yaml")
    plan = _build_matrix_plan(config)

    assert _model_ids(config) == GEMMA_MODELS
    assert {model.supported_modalities for model in config.models} == {("text",)}
    assert len(plan.cells) == 0
    assert plan.skip_reasons == {"unsupported_modality": 4}
    assert config.safety.live is False
    assert config.safety.allow_model_loads is False
    assert config.safety.allow_image_live is False


def test_l3_30_canary_shape_is_prepared_only_with_hard_cap_16() -> None:
    config = _config("matrix.l3_30c_gemma_vision_canary.prepared.yaml")
    plan = _build_matrix_plan(config)

    assert _model_ids(config) == GEMMA_MODELS
    assert len(config.tasks) == 4
    assert {task.response_schema_complexity for task in config.tasks} == {"simple_description"}
    assert {task.output_language_policy for task in config.tasks} == {"ru_ru"}
    assert set(config.axes["resize_profile"]) == {"max_side_1024"}
    assert config.safety.max_requests == 16
    assert len(plan.cells) == 0
    assert plan.skip_reasons == {"unsupported_modality": 16}
    for task in config.tasks:
        _assert_visible_text_policy(task)


def test_l3_30_screening_shape_is_prepared_only_without_complex_or_qwen() -> None:
    config = _config("matrix.l3_30d_gemma_vision_screening.prepared.yaml")
    plan = _build_matrix_plan(config)

    assert _model_ids(config) == GEMMA_MODELS
    assert all("qwen" not in model.model_id.casefold() for model in config.models)
    assert {task.response_schema_complexity for task in config.tasks} == {
        "simple_description",
        "medium_objects_text",
    }
    assert "complex_layout_extraction" not in {
        task.response_schema_complexity for task in config.tasks
    }
    assert {task.output_language_policy for task in config.tasks} == {"ru_ru", "en_en"}
    assert set(config.axes["resize_profile"]) == {"max_side_1024", "max_side_512"}
    assert config.safety.max_requests == 120
    assert len(plan.cells) == 0
    assert plan.skip_reasons == {"unsupported_modality": 304}
    for task in config.tasks:
        _assert_visible_text_policy(task)


def test_l3_30_tiny_capability_live_template_is_not_live_as_committed() -> None:
    config = _config("matrix.l3_30c_gemma_vision_tiny_capability_live.yaml")
    plan = _build_matrix_plan(config)

    assert _model_ids(config) == GEMMA_MODELS
    assert len(config.tasks) == 4
    assert config.safety.live is False
    assert config.safety.allow_image_live is False
    assert config.safety.allow_raw_prompt_response_artifacts is False
    assert config.safety.max_requests == 8
    assert set(config.axes["resize_profile"]) == {"max_side_1024"}
    assert len(plan.cells) == 0
    assert plan.skip_reasons == {"unsupported_modality": 16}
    for task in config.tasks:
        assert task.response_schema_complexity == "simple_description"
        assert task.output_language_policy == "ru_ru"
        _assert_visible_text_policy(task)


def test_l3_30_task_intent_routes_are_prepared_only_and_simple_schema() -> None:
    config = _config("matrix.l3_30e_gemma_vision_task_intent_routes.prepared.yaml")
    plan = _build_matrix_plan(config)

    assert _model_ids(config) == GEMMA_MODELS
    assert len(config.tasks) == 20
    assert {task.task_intent for task in config.tasks} == TASK_INTENTS
    assert {task.response_schema_complexity for task in config.tasks} == {"simple_task_intent"}
    assert {task.output_language_policy for task in config.tasks} == {"ru_ru", "en_en"}
    assert {task.language for task in config.tasks} == {"ru_ru", "en_en", "ru_en_mixed"}
    assert set(config.axes["resize_profile"]) == {"max_side_1024", "max_side_512"}
    assert set(config.axes["task_intent"]) == TASK_INTENTS
    assert config.safety.live is False
    assert config.safety.allow_image_live is False
    assert config.safety.allow_model_loads is False
    assert config.safety.allow_raw_prompt_response_artifacts is False
    assert config.safety.max_requests == 160
    assert len(plan.cells) == 0
    assert plan.skip_reasons == {"unsupported_modality": 1280}
    for task in config.tasks:
        assert task.schema_family == "simple_task_intent"
        assert task.expected_output is not None
        assert task.expected_output["task_intent"] == task.task_intent
        _assert_visible_text_policy(task)


def test_l3_30_report_declares_prepared_only_and_readiness_for_later_experiments() -> None:
    text = REPORT_PATH.read_text(encoding="utf-8")

    assert "No live image inference was run" in text
    assert "no_image_route_available" in text
    assert "L3.29 text/structured bounded matrix is prepared separately" in text
    assert "L3.30 vision capability/canary/screening is now prepared" in text
    assert "visible_text_policy" in text
    assert "Run L3.29 Gemma text/structured bounded matrix first" in text
    assert "Do not run full 480-cell image cartesian" in text
    assert "L3.30e task-intent route set" in text
    assert "schema: `simple_task_intent` only" in text
    assert "future upper bound: 160 cells" in text
