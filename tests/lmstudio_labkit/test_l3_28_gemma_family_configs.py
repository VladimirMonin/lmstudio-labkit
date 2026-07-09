from __future__ import annotations

from pathlib import Path

import yaml
from lmstudio_labkit.benchmarks import _build_matrix_plan

from lmstudio_labkit import BenchmarkConfig

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "experiments/lmstudio/structured_matrix/configs"
SUITE_PATH = (
    ROOT / "experiments/lmstudio/structured_matrix/suites/l3_28_gemma_family_expansion.yaml"
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


def test_l3_28_suite_is_staged_and_gemma_only() -> None:
    payload = yaml.safe_load(SUITE_PATH.read_text(encoding="utf-8"))

    assert payload["suite_id"] == "l3_28_gemma_family_expansion"
    assert [entry["id"] for entry in payload["configs"]] == [
        "readiness",
        "load_only_12b_26b",
        "transcript_cleanup_canary",
        "structured_json_canary",
        "context_screening_example",
        "vision_capability_preflight",
    ]
    for entry in payload["configs"]:
        config = _load_config(Path(entry["config"]).name)
        assert _model_ids(config) <= GEMMA_MODELS
        assert not any("qwen" in model.model_id.lower() for model in config.models)
        assert config.safety.allow_model_downloads is False
        assert config.safety.allow_stress is False


def test_l3_28_readiness_is_metadata_only_manifest() -> None:
    config = _load_config("matrix.l3_28a_gemma_readiness.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 4
    assert _model_ids(config) == GEMMA_MODELS
    assert {cell.task.task_intent for cell in plan.cells} == {"readiness_metadata_probe"}
    assert config.safety.live is False
    assert config.safety.allow_model_loads is False
    assert config.safety.allow_raw_prompt_response_artifacts is False


def test_l3_28_load_only_manifest_has_expected_context_guards() -> None:
    config = _load_config("matrix.l3_28b_gemma_load_only_12b_26b.yaml")
    plan = _build_matrix_plan(config)

    assert _model_ids(config) == {
        "google/gemma-4-12b-qat",
        "google/gemma-4-26b-a4b-qat",
    }
    assert len(plan.cells) == 5
    by_model = {}
    for cell in plan.cells:
        by_model.setdefault(cell.model.model_id, set()).add(cell.axes["context_tier"])
    assert by_model["google/gemma-4-12b-qat"] == {"8192", "16384", "32768"}
    assert by_model["google/gemma-4-26b-a4b-qat"] == {"8192", "16384"}
    assert config.safety.live is False
    assert config.safety.max_context_tier == 32768


def test_l3_28_transcript_cleanup_canary_is_bounded_family_scope() -> None:
    config = _load_config("matrix.l3_28c_gemma_transcript_cleanup_canary.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 20
    assert _model_ids(config) == GEMMA_MODELS
    assert {cell.task.task_intent for cell in plan.cells} == {"transcript_cleanup"}
    assert {cell.task.response_schema_complexity for cell in plan.cells} == {"simple"}
    assert {cell.task.prompt_variant for cell in plan.cells} == {"strict_no_new_facts_v2"}
    assert {cell.task.manual_review_policy for cell in plan.cells} == {"local_raw_prose_quality"}
    assert {cell.axes["context_tier"] for cell in plan.cells} == {"8192"}
    assert {cell.axes["retry_policy"] for cell in plan.cells} == {"off"}
    assert config.safety.max_requests == 20
    assert config.safety.allow_raw_prompt_response_artifacts is True
    assert config.safety.allow_image_live is False


def test_l3_28_structured_json_canary_uses_hardened_blocks_for_12b() -> None:
    config = _load_config("matrix.l3_28d_gemma_structured_json_canary.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 12
    assert _model_ids(config) == {
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
        "google/gemma-4-12b-qat",
    }
    assert "google/gemma-4-26b-a4b-qat" not in _model_ids(config)
    assert {cell.task.response_schema_complexity for cell in plan.cells} == {"simple", "blocks"}
    block_cells = [cell for cell in plan.cells if cell.task.response_schema_complexity == "blocks"]
    assert block_cells
    assert {cell.axes["schema_variant"] for cell in block_cells} == {"per_position_id_const"}
    assert {cell.axes["retry_policy"] for cell in plan.cells} == {"off"}
    assert config.safety.allow_raw_prompt_response_artifacts is False


def test_l3_28_context_screening_is_example_only_and_bounded() -> None:
    config = _load_config("matrix.l3_28e_gemma_context_screening.example.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 18
    assert _model_ids(config) == {
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
        "google/gemma-4-12b-qat",
    }
    assert {cell.axes["context_tier"] for cell in plan.cells} == {"8192", "16384", "32768"}
    assert config.safety.live is False
    assert config.safety.max_requests == 18


def test_l3_28_vision_capability_config_does_not_plan_image_live_by_default() -> None:
    config = _load_config("matrix.l3_28f_gemma_vision_capability_canary.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 0
    assert plan.skip_reasons == {"unsupported_modality": 16}
    assert _model_ids(config) == GEMMA_MODELS
    assert config.safety.live is False
    assert config.safety.allow_image_live is False
    assert config.safety.max_requests == 1
