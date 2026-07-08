from __future__ import annotations

from lmstudio_labkit.validation import validate_punctuation_metrics


def test_punctuation_metrics_are_diagnostic_by_default() -> None:
    result = validate_punctuation_metrics("сегодня проверим django", "Сегодня проверим Django.")
    assert result.status == "warning"
    assert result.metrics["punctuation_count_after"] > result.metrics["punctuation_count_before"]


def test_punctuation_hard_policy_can_fail() -> None:
    result = validate_punctuation_metrics("сегодня проверим", "сегодня проверим", policy="hard")
    assert result.status == "fail"
