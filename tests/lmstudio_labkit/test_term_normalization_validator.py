from __future__ import annotations

from lmstudio_labkit.validation import validate_term_normalization


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
