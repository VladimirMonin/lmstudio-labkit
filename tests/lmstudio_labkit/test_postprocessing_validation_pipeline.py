from __future__ import annotations

import json

from lmstudio_labkit.benchmarks import BenchmarkConfig, plan_matrix
from lmstudio_labkit.requests import ResponseContract
from lmstudio_labkit.validation import validate_response


def _result(summary, name: str):
    return next(item for item in summary.results if item.name == name)


def test_validate_response_runs_term_normalization_from_contract() -> None:
    contract = ResponseContract(
        mode="json",
        language="ru_en_mixed",
        language_policy="preserve_mixed_language",
        language_include_paths=("blocks[*].text",),
        task_intent="term_normalization",
        expected_terms=(
            {"source_variants": ["джанго", "django"], "normalized": "Django"},
            {"source_variants": ["кувен", "qwen"], "normalized": "Qwen"},
        ),
        expected_output={"blocks": [{"id": 0, "text": "Используем Django и Qwen."}]},
    )
    raw = json.dumps(
        {"blocks": [{"id": 0, "text": "Используем Django и Qwen."}]},
        ensure_ascii=False,
    )

    summary = validate_response(raw, contract, input_text="используем джанго и кувен")

    term = _result(summary, "term_normalization_status")
    assert term.status == "pass"
    assert term.metrics["expected_terms_normalized"] == 2


def test_validate_response_runs_punctuation_metrics_from_contract() -> None:
    contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="preserve_input_language",
        language_include_paths=("clean_text",),
        task_intent="punctuation_restore",
        punctuation_policy="hard",
        expected_output={"clean_text": "Сегодня проверяем Django."},
    )
    raw = json.dumps({"clean_text": "Сегодня проверяем Django."}, ensure_ascii=False)

    summary = validate_response(raw, contract, input_text="сегодня проверяем django")

    punctuation = _result(summary, "punctuation_metrics")
    assert punctuation.status == "pass"
    assert (
        punctuation.metrics["punctuation_count_after"]
        > punctuation.metrics["punctuation_count_before"]
    )


def test_validate_response_runs_paragraphing_and_filler_cleanup_from_contract() -> None:
    paragraph_contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="preserve_input_language",
        language_include_paths=("clean_text",),
        task_intent="paragraphing",
        paragraph_count_min=2,
        expected_output={"clean_text": "Первый абзац.\n\nВторой абзац."},
    )
    paragraph_raw = json.dumps({"clean_text": "Первый абзац.\n\nВторой абзац."}, ensure_ascii=False)
    paragraph_summary = validate_response(paragraph_raw, paragraph_contract)
    assert _result(paragraph_summary, "paragraphing_metrics").status == "pass"

    filler_contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="preserve_input_language",
        language_include_paths=("clean_text",),
        task_intent="filler_cleanup",
        expected_output={"clean_text": "Сегодня проверяем Django."},
    )
    filler_raw = json.dumps({"clean_text": "Сегодня проверяем Django."}, ensure_ascii=False)
    filler_summary = validate_response(
        filler_raw, filler_contract, input_text="ну сегодня как бы проверяем django"
    )
    filler = _result(filler_summary, "filler_cleanup")
    assert filler.status == "pass"
    assert filler.metrics["filler_terms_after"] == 0


def test_task_config_maps_postprocessing_validators_into_response_contract() -> None:
    config = BenchmarkConfig.from_dict(
        {
            "run_id": "pipeline_contract_mapping",
            "models": [{"model_key": "m", "model_id": "offline-model"}],
            "tasks": [
                {
                    "task_id": "term_task",
                    "family": "postprocessing",
                    "language": "ru_en_mixed",
                    "structure_complexity": "medium",
                    "response_schema_complexity": "blocks",
                    "volume": "many",
                    "task_intent": "term_normalization",
                    "input_profile": "raw_asr_ru_term_noise",
                    "output_language_policy": "preserve_mixed_language",
                    "prompt_variant": "term_glossary",
                    "validation_policy": "auto_schema_language_manual_quality",
                    "prompt": "сегодня используем джанго и кувен",
                    "expected_output": {"blocks": [{"id": 0, "text": "Django и Qwen"}]},
                    "expected_terms": [
                        {"source_variants": ["джанго"], "normalized": "Django"},
                        {"source_variants": ["кувен"], "normalized": "Qwen"},
                    ],
                    "language_include_paths": ["blocks[*].text"],
                    "punctuation_policy": "diagnostic",
                    "paragraph_count_min": 1,
                    "filler_terms": ["ну", "как бы"],
                }
            ],
            "axes": {
                "language": ["ru_en_mixed"],
                "structure_complexity": ["medium"],
                "response_schema_complexity": ["blocks"],
                "volume": ["many"],
                "task_intent": ["term_normalization"],
                "input_profile": ["raw_asr_ru_term_noise"],
                "output_language_policy": ["preserve_mixed_language"],
                "prompt_variant": ["term_glossary"],
                "validation_policy": ["auto_schema_language_manual_quality"],
            },
        }
    )
    plan = plan_matrix(config)
    contract = plan.cells[0].to_request_plan().envelope.response_contract

    assert contract.expected_terms[0]["normalized"] == "Django"
    assert contract.language_include_paths == ("blocks[*].text",)
    assert contract.task_intent == "term_normalization"
    assert contract.validation_policy == "auto_schema_language_manual_quality"
    assert contract.paragraph_count_min == 1
    assert contract.filler_terms == ("ну", "как бы")
