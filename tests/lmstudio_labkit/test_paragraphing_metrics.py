from __future__ import annotations

from lmstudio_labkit.validation import validate_filler_cleanup, validate_paragraphing_metrics


def test_paragraphing_metrics_hard_policy() -> None:
    result = validate_paragraphing_metrics(
        "Первый абзац.\n\nВторой абзац.", paragraph_count_min=2, hard=True
    )
    assert result.status == "pass"
    assert result.metrics["paragraph_count"] == 2


def test_filler_cleanup_metrics() -> None:
    result = validate_filler_cleanup(
        "ну сегодня как бы проверим django", "Сегодня проверим Django.", hard=True
    )
    assert result.status == "pass"
    assert result.metrics["filler_terms_after"] == 0
