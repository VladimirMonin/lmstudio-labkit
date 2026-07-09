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
L3_29_SUITE_PATH = (
    ROOT / "experiments/lmstudio/structured_matrix/suites/l3_29_gemma_family_bounded_matrix.yaml"
)
DECISION_RECORD_PATH = (
    ROOT / "experiments/lmstudio/results_summaries/l3_28_gemma_family_expansion_decision_record.md"
)
LOAD_ONLY_PLAN_PATH = (
    ROOT / "experiments/lmstudio/results_summaries/l3_28b_gemma_load_only_operator_plan.md"
)

GEMMA_MODELS = {
    "google/gemma-4-e2b",
    "google/gemma-4-e4b",
    "google/gemma-4-12b-qat",
    "google/gemma-4-26b-a4b-qat",
}


def _load_config(name: str) -> BenchmarkConfig:
    return BenchmarkConfig.from_file(CONFIG_DIR / name)


def _load_config_payload(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))


def _model_ids(config: BenchmarkConfig) -> set[str]:
    return {model.model_id for model in config.models}


def test_l3_28_suite_is_staged_and_gemma_only() -> None:
    payload = yaml.safe_load(SUITE_PATH.read_text(encoding="utf-8"))

    assert payload["suite_id"] == "l3_28_gemma_family_expansion"
    assert [entry["id"] for entry in payload["configs"]] == [
        "readiness",
        "load_only_12b_26b",
        "transcript_cleanup_canary_e2b_e4b_12b",
        "transcript_cleanup_tiny_canary_26b",
        "structured_json_canary",
        "context_screening_example",
        "vision_capability_preflight",
    ]
    assert payload["configs"][3]["required"] is False
    assert "Do not run full suite automatically." in "\n".join(payload["notes"])
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
    assert config.safety.allow_model_loads is False
    assert config.safety.max_context_tier == 32768

    payload = _load_config_payload("matrix.l3_28b_gemma_load_only_12b_26b.yaml")
    notes = "\n".join(payload["notes"])
    assert "Do not execute Phase B through lmstudio-benchmark run" in notes
    assert "no dedicated lmstudio-benchmark load-only command exists" in notes
    assert "no generation called" in notes


def test_l3_28_load_only_operator_plan_documents_required_command_shape() -> None:
    text = LOAD_ONLY_PLAN_PATH.read_text(encoding="utf-8")

    assert "Status: prepared-only" in text
    assert "Do **not** execute Phase B through `lmstudio-benchmark run`" in text
    assert "uv run lmstudio-benchmark load-only" in text
    assert "--output-root /tmp/labkit-l328-load-only" in text
    assert "no generation call was made" in text


def test_l3_28_transcript_cleanup_canary_c1_excludes_26b() -> None:
    config = _load_config("matrix.l3_28c1_gemma_transcript_cleanup_canary_e2b_e4b_12b.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 15
    assert _model_ids(config) == {
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
        "google/gemma-4-12b-qat",
    }
    assert "google/gemma-4-26b-a4b-qat" not in _model_ids(config)
    assert {cell.task.task_intent for cell in plan.cells} == {"transcript_cleanup"}
    assert {cell.task.response_schema_complexity for cell in plan.cells} == {"simple"}
    assert {cell.task.prompt_variant for cell in plan.cells} == {"strict_no_new_facts_v2"}
    assert {cell.task.manual_review_policy for cell in plan.cells} == {"local_raw_prose_quality"}
    assert {cell.axes["context_tier"] for cell in plan.cells} == {"8192"}
    assert {cell.axes["retry_policy"] for cell in plan.cells} == {"off"}
    assert config.safety.max_requests == 15
    assert config.safety.allow_raw_prompt_response_artifacts is True
    assert config.safety.allow_image_live is False
    payload = _load_config_payload(
        "matrix.l3_28c1_gemma_transcript_cleanup_canary_e2b_e4b_12b.yaml"
    )
    assert any("/tmp/labkit-l328c-transcript-cleanup" in note for note in payload["notes"])


def test_l3_28_transcript_cleanup_canary_c2_is_26b_tiny_and_optional() -> None:
    config = _load_config("matrix.l3_28c2_gemma_26b_transcript_cleanup_tiny_canary.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 3
    assert _model_ids(config) == {"google/gemma-4-26b-a4b-qat"}
    assert {cell.task.task_intent for cell in plan.cells} == {"transcript_cleanup"}
    assert {cell.task.response_schema_complexity for cell in plan.cells} == {"simple"}
    assert {cell.axes["context_tier"] for cell in plan.cells} == {"8192"}
    assert config.safety.max_models == 1
    assert config.safety.max_requests == 3
    assert config.safety.allow_raw_prompt_response_artifacts is True
    payload = _load_config_payload("matrix.l3_28c2_gemma_26b_transcript_cleanup_tiny_canary.yaml")
    notes = "\n".join(payload["notes"])
    assert "26B load-only passes at 8192 and 16384" in notes
    assert "owner explicitly approves 26B generation" in notes


def test_l3_28_structured_json_canary_uses_hardened_blocks_and_ru_payloads() -> None:
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
    assert {cell.axes["schema_variant"] for cell in block_cells} == {"hardened_const"}
    assert {cell.axes["retry_policy"] for cell in plan.cells} == {"off"}
    assert config.safety.allow_raw_prompt_response_artifacts is False

    by_id = {task.task_id: task.expected_output for task in config.tasks}
    assert all(output is not None for output in by_id.values())
    assert by_id["l328d_structured_simple_ru_ru"] is not None
    assert by_id["l328d_structured_simple_ru_ru"]["items"] == ["первый", "второй"]
    assert by_id["l328d_structured_simple_ru_en_mixed"] is not None
    assert by_id["l328d_structured_simple_ru_en_mixed"]["items"] == [
        "Django",
        "Qwen",
        "JSON schema",
    ]
    assert by_id["l328d_structured_blocks_ru_ru"] is not None
    assert by_id["l328d_structured_blocks_ru_ru"]["blocks"] == [
        {"id": 0, "text": "первый блок"},
        {"id": 1, "text": "второй блок"},
        {"id": 2, "text": "третий блок"},
    ]
    assert by_id["l328d_structured_blocks_ru_en_mixed"] is not None
    assert by_id["l328d_structured_blocks_ru_en_mixed"]["blocks"] == [
        {"id": 0, "text": "Django endpoint"},
        {"id": 1, "text": "Qwen adapter"},
        {"id": 2, "text": "JSON schema validation"},
    ]


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


def test_l3_28d_1_structured_repair_e2b_e4b_is_bounded() -> None:
    config = _load_config("matrix.l3_28d_1_structured_json_repair_e2b_e4b.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 8
    assert _model_ids(config) == {"google/gemma-4-e2b", "google/gemma-4-e4b"}
    assert "google/gemma-4-26b-a4b-qat" not in _model_ids(config)
    assert {cell.task.response_schema_complexity for cell in plan.cells} == {"simple", "blocks"}
    assert {cell.axes["schema_variant"] for cell in plan.cells} == {"hardened_const"}
    assert config.safety.max_requests == 8
    assert config.safety.allow_raw_prompt_response_artifacts is False
    for task in config.tasks:
        if task.response_schema_complexity == "simple":
            assert task.language_include_paths == ("items[*]",)
            assert "Return exactly this JSON shape" in task.prompt
        if task.response_schema_complexity == "blocks":
            assert task.language_include_paths == ("blocks[*].text",)
            assert "Preserve every id exactly" in task.prompt


def test_l3_28d_1_structured_repair_12b_excludes_26b_and_uses_retry_axis() -> None:
    config = _load_config("matrix.l3_28d_1_structured_json_repair_12b.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 8
    assert _model_ids(config) == {"google/gemma-4-12b-qat"}
    assert "google/gemma-4-26b-a4b-qat" not in _model_ids(config)
    assert {cell.axes["retry_policy"] for cell in plan.cells} == {"off", "retry1"}
    assert {cell.task.response_schema_complexity for cell in plan.cells} == {"simple", "blocks"}
    assert config.safety.max_requests == 8
    payload = _load_config_payload("matrix.l3_28d_1_structured_json_repair_12b.yaml")
    notes = "\n".join(payload["notes"])
    assert "Run only after E2B/E4B repair canary passes" in notes
    assert "No 26B structured JSON generation" in notes


def test_l3_29_suite_stays_within_bounded_matrix_cap() -> None:
    payload = yaml.safe_load(L3_29_SUITE_PATH.read_text(encoding="utf-8"))

    assert payload["suite_id"] == "l3_29_gemma_family_bounded_matrix"
    assert [entry["id"] for entry in payload["configs"]] == [
        "transcript_cleanup_screening",
        "transcript_cleanup_26b_controlled",
        "structured_json_bounded",
    ]
    assert payload["total_planned_requests"] == 149
    assert payload["hard_max_requests"] == 150
    assert "Do not run full suite automatically" in "\n".join(payload["notes"])


def test_l3_29_transcript_cleanup_screening_shape() -> None:
    config = _load_config("matrix.l3_29_gemma_transcript_cleanup_screening.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 120
    assert _model_ids(config) == {
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
        "google/gemma-4-12b-qat",
    }
    assert "google/gemma-4-26b-a4b-qat" not in _model_ids(config)
    assert {cell.task.task_intent for cell in plan.cells} == {"transcript_cleanup"}
    assert {cell.task.response_schema_complexity for cell in plan.cells} == {"simple"}
    assert {cell.axes["context_tier"] for cell in plan.cells} == {"8192", "16384"}
    assert {cell.axes["retry_policy"] for cell in plan.cells} == {"off"}
    assert {cell.task.language for cell in plan.cells} >= {"ru_ru", "ru_en_mixed", "en_en"}
    assert {cell.task.manual_review_policy for cell in plan.cells} == {"local_raw_prose_quality"}
    assert config.safety.max_requests == 120
    assert config.safety.allow_raw_prompt_response_artifacts is True
    assert config.safety.allow_image_live is False


def test_l3_29_26b_transcript_controlled_is_tiny_only() -> None:
    config = _load_config("matrix.l3_29_gemma_26b_transcript_cleanup_controlled.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 5
    assert _model_ids(config) == {"google/gemma-4-26b-a4b-qat"}
    assert {cell.task.task_intent for cell in plan.cells} == {"transcript_cleanup"}
    assert {cell.axes["context_tier"] for cell in plan.cells} == {"8192"}
    assert config.safety.max_requests == 5
    assert config.safety.max_models == 1
    payload = _load_config_payload("matrix.l3_29_gemma_26b_transcript_cleanup_controlled.yaml")
    assert "Do not broaden 26B to structured JSON" in "\n".join(payload["notes"])


def test_l3_29_structured_json_bounded_excludes_26b_and_uses_repair_contract() -> None:
    config = _load_config("matrix.l3_29_gemma_structured_json_bounded.yaml")
    plan = _build_matrix_plan(config)

    assert len(plan.cells) == 24
    assert _model_ids(config) == {
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
        "google/gemma-4-12b-qat",
    }
    assert "google/gemma-4-26b-a4b-qat" not in _model_ids(config)
    assert {cell.task.response_schema_complexity for cell in plan.cells} == {"simple", "blocks"}
    assert {cell.axes["schema_variant"] for cell in plan.cells} == {"hardened_const"}
    assert {cell.axes["retry_policy"] for cell in plan.cells} == {"off"}
    assert {
        cell.task.language_include_paths
        for cell in plan.cells
        if cell.task.response_schema_complexity == "simple"
    } == {("items[*]",)}
    assert {
        cell.task.language_include_paths
        for cell in plan.cells
        if cell.task.response_schema_complexity == "blocks"
    } == {("blocks[*].text",)}
    assert config.safety.max_requests == 24
    assert config.safety.allow_raw_prompt_response_artifacts is False
    payload = _load_config_payload("matrix.l3_29_gemma_structured_json_bounded.yaml")
    notes = "\n".join(payload["notes"])
    assert "26B structured JSON remains blocked" in notes
    assert "No complex schema" in notes


def test_l3_28_decision_record_has_admission_summary_columns() -> None:
    text = DECISION_RECORD_PATH.read_text(encoding="utf-8")

    for column in [
        "model_admission_status",
        "load_only_status",
        "generation_status",
        "structured_simple_status",
        "structured_blocks_status",
        "transcript_cleanup_status",
        "vision_route_status",
        "allowed_next_phase",
        "blocked_reason",
    ]:
        assert column in text
    assert "google/gemma-4-26b-a4b-qat" in text
    assert "C2 optional tiny only" in text
    assert "Do not run the full suite automatically" in text
