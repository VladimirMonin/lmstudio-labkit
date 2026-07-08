from __future__ import annotations

from lmstudio_labkit.requests import ResponseContract
from lmstudio_labkit.validation import (
    filter_expected_terms_for_source,
    validate_response,
    validate_term_normalization,
)


def test_term_normalization_metrics_pass_when_terms_are_normalized() -> None:
    expected = (
        {"source_variants": ["джанго"], "normalized": "Django"},
        {"source_variants": ["кувен"], "normalized": "Qwen"},
    )
    result = validate_term_normalization({"clean_text": "Используем Django и Qwen."}, expected)
    assert result.status == "pass"
    assert result.metrics["term_recall"] == 1.0


def test_term_normalization_metrics_fail_on_remaining_variant() -> None:
    expected = ({"source_variants": ["джанго"], "normalized": "Django"},)
    result = validate_term_normalization({"clean_text": "Используем джанго."}, expected)
    assert result.status == "fail"
    assert result.metrics["forbidden_term_variants_remaining"] == 1


def test_expected_terms_are_filtered_to_terms_present_in_source_text() -> None:
    expected = (
        {"source_variants": ["джанго"], "normalized": "Django"},
        {"source_variants": ["кувен"], "normalized": "Qwen"},
        {"source_variants": ["лемон скай виза"], "normalized": "Lemon Squeezy"},
    )

    filtered = filter_expected_terms_for_source(expected, "Сегодня используем джанго и кувен")

    assert tuple(item["normalized"] for item in filtered) == ("Django", "Qwen")


def test_term_normalization_pipeline_uses_user_text_paths_not_metadata() -> None:
    contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="preserve_input_language",
        language_include_paths=("blocks[*].text",),
        response_schema_complexity="blocks",
        schema_family="blocks",
        task_intent="term_normalization",
        source_text="сегодня используем джанго",
        expected_terms=({"source_variants": ["джанго"], "normalized": "Django"},),
    )
    raw = '{"blocks":[{"id":0,"text":"Используем Django."}],"debug_source":"джанго"}'

    summary = validate_response(raw, contract)
    term = next(item for item in summary.results if item.name == "term_normalization_status")

    assert term.status == "pass"
    assert term.metrics["forbidden_term_variants_remaining"] == 0
