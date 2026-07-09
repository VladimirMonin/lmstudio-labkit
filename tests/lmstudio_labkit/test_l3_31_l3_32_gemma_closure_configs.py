from __future__ import annotations

import json
from pathlib import Path

from lmstudio_labkit.benchmarks import _build_matrix_plan
from lmstudio_labkit.validation import validate_response

from lmstudio_labkit import BenchmarkConfig, plan_matrix

CONFIG_DIR = Path("experiments/lmstudio/structured_matrix/configs")
REPORT_DIR = Path("experiments/lmstudio/results_summaries")
DOCS_DIR = Path("docs/live_demo")


def _config(name: str) -> BenchmarkConfig:
    return BenchmarkConfig.from_file(CONFIG_DIR / name)


def _planned_count(name: str) -> int:
    config = _config(name)
    plan = _build_matrix_plan(config) if config.safety.live else plan_matrix(config)
    return len(plan.cells)


def _model_ids(config: BenchmarkConfig) -> set[str]:
    return {model.model_id for model in config.models}


def _all_axes(config: BenchmarkConfig, axis_name: str) -> set[str]:
    return set(config.axes[axis_name])


def test_l3_31_context_configs_have_expected_plan_sizes_and_gates() -> None:
    canary = _config("matrix.l3_31a_gemma_context_canary.yaml")
    screening = _config("matrix.l3_31b_gemma_context_screening.yaml")
    controlled_26b = _config("matrix.l3_31c_gemma_26b_context_controlled.yaml")

    assert _planned_count("matrix.l3_31a_gemma_context_canary.yaml") == 9
    assert _planned_count("matrix.l3_31b_gemma_context_screening.yaml") == 36
    assert _planned_count("matrix.l3_31c_gemma_26b_context_controlled.yaml") == 3

    assert _all_axes(canary, "context_tier") == {"16384"}
    assert _all_axes(screening, "context_tier") == {"16384", "32768"}
    assert _all_axes(controlled_26b, "context_tier") == {"16384"}

    assert canary.safety.live is True
    assert canary.safety.allow_model_loads is True
    assert canary.safety.max_requests == 9
    assert canary.safety.allow_raw_prompt_response_artifacts is False
    assert canary.safety.allow_image_live is False
    assert canary.safety.allow_stress is False

    assert screening.safety.live is False
    assert screening.safety.allow_model_loads is False
    assert screening.safety.max_requests == 36

    assert _model_ids(controlled_26b) == {"google/gemma-4-26b-a4b-qat"}
    assert controlled_26b.safety.live is False
    assert controlled_26b.safety.max_requests == 3
    assert _all_axes(controlled_26b, "response_schema_complexity") == {"simple"}
    assert _all_axes(controlled_26b, "task_intent") == {"transcript_cleanup"}


def test_l3_31_context_configs_are_gemma_only_and_exclude_qwen_image_cache() -> None:
    for name in [
        "matrix.l3_31a_gemma_context_canary.yaml",
        "matrix.l3_31b_gemma_context_screening.yaml",
        "matrix.l3_31c_gemma_26b_context_controlled.yaml",
    ]:
        config = _config(name)
        assert all("gemma" in model.model_id for model in config.models)
        assert all("qwen" not in model.model_id.lower() for model in config.models)
        assert _all_axes(config, "modality") == {"text"}
        assert _all_axes(config, "lmstudio_parallel") == {"1"}
        assert _all_axes(config, "app_concurrency") == {"1"}
        assert _all_axes(config, "queue_pressure_mode") == {"off"}
        assert _all_axes(config, "execution_mode") == {"cold_per_request"}
        assert _all_axes(config, "cache_mode") == {"none"}


def test_l3_32_json_complexity_configs_have_expected_plan_sizes() -> None:
    assert _planned_count("matrix.l3_32a_gemma_complex_json_canary_e2b_e4b.yaml") == 4
    assert _planned_count("matrix.l3_32b_gemma_complex_json_canary_12b.yaml") == 4
    assert _planned_count("matrix.l3_32c_gemma_structured_json_complexity_screening.yaml") == 96
    assert _planned_count("matrix.l3_32d_gemma_26b_structured_json_tiny.yaml") == 2


def test_l3_32_complex_json_is_staged_and_26b_is_tiny_only() -> None:
    canary = _config("matrix.l3_32a_gemma_complex_json_canary_e2b_e4b.yaml")
    model_12b = _config("matrix.l3_32b_gemma_complex_json_canary_12b.yaml")
    screening = _config("matrix.l3_32c_gemma_structured_json_complexity_screening.yaml")
    tiny_26b = _config("matrix.l3_32d_gemma_26b_structured_json_tiny.yaml")

    assert _model_ids(canary) == {"google/gemma-4-e2b", "google/gemma-4-e4b"}
    assert _all_axes(canary, "response_schema_complexity") == {"complex"}
    assert _all_axes(canary, "context_tier") == {"8192"}
    assert canary.safety.live is False
    assert canary.safety.allow_model_loads is False

    assert _model_ids(model_12b) == {"google/gemma-4-12b-qat"}
    assert _all_axes(model_12b, "retry_policy") == {"off", "retry1"}
    assert model_12b.safety.max_requests == 4

    assert _model_ids(screening) == {
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
        "google/gemma-4-12b-qat",
    }
    assert _all_axes(screening, "response_schema_complexity") == {
        "simple",
        "blocks",
        "complex",
    }
    assert screening.safety.max_requests == 96
    assert screening.safety.live is False

    assert _model_ids(tiny_26b) == {"google/gemma-4-26b-a4b-qat"}
    assert _all_axes(tiny_26b, "response_schema_complexity") == {"simple"}
    assert _all_axes(tiny_26b, "context_tier") == {"8192"}
    assert tiny_26b.safety.max_requests == 2
    assert tiny_26b.safety.live is False


def test_l3_32_complex_tasks_have_explicit_schema_and_language_paths() -> None:
    for name in [
        "matrix.l3_32a_gemma_complex_json_canary_e2b_e4b.yaml",
        "matrix.l3_32b_gemma_complex_json_canary_12b.yaml",
    ]:
        config = _config(name)
        for task in config.tasks:
            assert task.response_schema_complexity == "complex"
            assert task.schema is not None
            assert task.expected_output is not None
            assert task.language_include_paths == (
                "document.sections[*].title",
                "document.sections[*].elements[*].text",
            )


def test_l3_32_complex_tasks_have_offline_schema_fixture_validation() -> None:
    for name in [
        "matrix.l3_32a_gemma_complex_json_canary_e2b_e4b.yaml",
        "matrix.l3_32b_gemma_complex_json_canary_12b.yaml",
        "matrix.l3_32c_gemma_structured_json_complexity_screening.yaml",
    ]:
        config = _config(name)
        complex_cells = [
            cell
            for cell in plan_matrix(config).cells
            if cell.task.response_schema_complexity == "complex"
        ]
        assert complex_cells, name

        for cell in complex_cells:
            contract = cell.to_request_plan().envelope.response_contract
            assert contract.mode == "json"
            assert contract.schema is not None
            assert contract.expected_output is not None
            assert contract.language_include_paths == (
                "document.sections[*].title",
                "document.sections[*].elements[*].text",
            )

            valid_raw = json.dumps(contract.expected_output, ensure_ascii=False)
            valid_summary = validate_response(valid_raw, contract, finish_reason="stop")
            assert valid_summary.status == "pass"

            missing_nested_required = json.loads(valid_raw)
            del missing_nested_required["document"]["sections"][0]["elements"][0]["confidence_hint"]
            invalid_raw = json.dumps(missing_nested_required, ensure_ascii=False)
            invalid_summary = validate_response(invalid_raw, contract, finish_reason="stop")
            assert invalid_summary.status == "fail"
            assert any(
                result.name == "json_schema"
                and result.status == "fail"
                and result.category == "schema_error"
                for result in invalid_summary.results
            )


def test_l3_32_configs_do_not_reintroduce_per_position_id_const() -> None:
    for name in [
        "matrix.l3_32a_gemma_complex_json_canary_e2b_e4b.yaml",
        "matrix.l3_32b_gemma_complex_json_canary_12b.yaml",
        "matrix.l3_32c_gemma_structured_json_complexity_screening.yaml",
        "matrix.l3_32d_gemma_26b_structured_json_tiny.yaml",
    ]:
        config = _config(name)
        assert _all_axes(config, "schema_variant") == {"hardened_const"}
        assert "per_position_id_const" not in (CONFIG_DIR / name).read_text(encoding="utf-8")


def test_l3_31_l3_32_reports_and_demo_dirs_exist() -> None:
    assert (REPORT_DIR / "l3_31_gemma_context_screening_decision_record.md").is_file()
    assert (REPORT_DIR / "l3_32_gemma_json_complexity_decision_record.md").is_file()
    assert (DOCS_DIR / "latest_gemma_context_screening" / "README.md").is_file()
    assert (DOCS_DIR / "latest_gemma_json_complexity" / "README.md").is_file()
