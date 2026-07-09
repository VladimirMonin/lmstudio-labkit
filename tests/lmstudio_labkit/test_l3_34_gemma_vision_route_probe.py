from __future__ import annotations

from pathlib import Path

from lmstudio_labkit.benchmarks import _build_matrix_plan

from lmstudio_labkit import BenchmarkConfig

CONFIG_DIR = Path("experiments/lmstudio/structured_matrix/configs")
REPORT_DIR = Path("experiments/lmstudio/results_summaries")
DOCS_DIR = Path("docs/live_demo")

GEMMA_MODELS = {
    "google/gemma-4-e2b",
    "google/gemma-4-e4b",
    "google/gemma-4-12b-qat",
    "google/gemma-4-26b-a4b-qat",
}


def _config(name: str) -> BenchmarkConfig:
    return BenchmarkConfig.from_file(CONFIG_DIR / name)


def _model_ids(config: BenchmarkConfig) -> set[str]:
    return {model.model_id for model in config.models}


def test_l3_34_route_probe_is_tiny_non_live_and_text_only_until_capability_proof() -> None:
    config = _config("matrix.l3_34_gemma_vision_route_probe.yaml")
    plan = _build_matrix_plan(config)

    assert config.run_id == "matrix_l3_34_gemma_vision_route_probe"
    assert _model_ids(config) == GEMMA_MODELS
    assert {model.supported_modalities for model in config.models} == {("text",)}
    assert len(config.tasks) == 1
    task = config.tasks[0]
    assert isinstance(task.expected_output, dict)
    assert task.input_profile == "ui_settings_ru_001"
    assert task.response_schema_complexity == "simple_description"
    assert task.expected_output["capability_status_when_text_only"] == ("no_image_route_available")
    assert task.expected_output["live_image_request_when_text_only"] == "forbidden"
    assert set(config.axes["resize_profile"]) == {"max_side_1024"}
    assert set(config.axes["output_language"]) == {"ru_ru"}
    assert config.safety.live is False
    assert config.safety.allow_image_live is False
    assert config.safety.allow_model_loads is False
    assert config.safety.allow_model_downloads is False
    assert config.safety.allow_raw_prompt_response_artifacts is False
    assert config.safety.max_requests == 4
    assert len(plan.cells) == 0
    assert plan.skip_reasons == {"unsupported_modality": 4}


def test_l3_34_route_probe_preserves_visible_text_language_policy() -> None:
    task = _config("matrix.l3_34_gemma_vision_route_probe.yaml").tasks[0]

    assert isinstance(task.expected_output, dict)
    assert isinstance(task.image_ground_truth, dict)
    assert task.expected_output["visible_text_policy"] == "preserve_original_visible_text"
    assert task.expected_output["description_language"] == "output_language"
    assert task.expected_output["summary_language"] == "output_language"
    assert task.image_ground_truth["visible_text_policy"] == "preserve_original_visible_text"
    assert "do not translate OCR text" in task.prompt


def test_l3_34_route_probe_reports_exist_and_declare_no_live_image_request() -> None:
    report = (REPORT_DIR / "l3_34_gemma_vision_route_capability_decision_record.md").read_text(
        encoding="utf-8"
    )
    latest = (DOCS_DIR / "latest_gemma_vision_route_probe" / "README.md").read_text(
        encoding="utf-8"
    )

    for text in (report, latest):
        assert "No live image request" in text
        assert "no_image_route_available" in text
        assert "unsupported_modality" in text
        assert "quality" in text
        assert "L3.35" in text
    assert "route_rejected_image_payload" in report
    assert "quality_failure=false" in report
    assert "allow_image_live=false" in latest
