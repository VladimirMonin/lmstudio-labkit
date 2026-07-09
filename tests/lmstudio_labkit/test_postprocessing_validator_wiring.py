from __future__ import annotations

import json

from lmstudio_labkit.requests import ResponseContract
from lmstudio_labkit.validation import validate_response


def _result(summary, name: str):
    return next(item for item in summary.results if item.name == name)


def test_task_intents_invoke_expected_postprocessing_validators() -> None:
    raw = json.dumps(
        {"clean_text": "Сегодня используем Django.\n\nВторой абзац."}, ensure_ascii=False
    )
    contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="preserve_input_language",
        response_schema_complexity="simple",
        source_text="ну сегодня используем джанго",
        task_intent="mixed_postprocess",
        expected_terms=({"source_variants": ["джанго"], "normalized": "Django"},),
        term_normalization_policy="diagnostic",
        punctuation_policy="diagnostic",
        paragraphing_policy="hard",
        paragraph_count_min=2,
        filler_cleanup_policy="diagnostic",
        manual_review_policy="sampled",
        expected_output={"clean_text": "Сегодня используем Django.\n\nВторой абзац."},
    )

    summary = validate_response(raw, contract)

    assert _result(summary, "term_normalization_status").status == "pass"
    assert _result(summary, "punctuation_metrics").status == "warning"
    assert _result(summary, "paragraphing_metrics").status == "pass"
    assert _result(summary, "filler_cleanup").status == "pass"
    assert _result(summary, "no_new_facts_manual_review").status == "warning"


def test_term_normalization_hard_policy_fails_but_diagnostic_warns() -> None:
    raw = json.dumps({"clean_text": "Используем джанго."}, ensure_ascii=False)
    base = {
        "mode": "json",
        "language": "ru_ru",
        "language_policy": "preserve_input_language",
        "response_schema_complexity": "simple",
        "task_intent": "term_normalization",
        "expected_terms": ({"source_variants": ["джанго"], "normalized": "Django"},),
        "expected_output": {"clean_text": "Используем Django."},
    }

    hard = validate_response(raw, ResponseContract(**base, term_normalization_policy="hard"))
    diagnostic = validate_response(
        raw, ResponseContract(**base, term_normalization_policy="diagnostic")
    )

    assert _result(hard, "term_normalization_status").status == "fail"
    assert hard.status == "fail"
    assert _result(diagnostic, "term_normalization_status").status == "warning"
    assert diagnostic.status == "pass"


def test_transcript_cleanup_noop_warns_when_noise_is_present() -> None:
    source = "ну сегодня мы как бы поговорим про django"
    raw = json.dumps({"clean_text": source}, ensure_ascii=False)
    contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="preserve_input_language",
        response_schema_complexity="simple",
        source_text=source,
        task_intent="transcript_cleanup",
        filler_cleanup_policy="diagnostic",
        punctuation_policy="diagnostic",
    )

    summary = validate_response(raw, contract)
    noop = _result(summary, "cleanup_noop_diagnostics")

    assert noop.status == "warning"
    assert noop.category == "cleanup_noop_when_noise_present"
    assert noop.metrics["cleanup_noop"] is True
    assert noop.metrics["source_noise_present"] is True


def test_term_normalization_language_drift_is_reported_as_warning() -> None:
    source = "сегодня используем джанго и пай сайд"
    raw = json.dumps({"clean_text": "Today we use Django and PySide."}, ensure_ascii=False)
    contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="skip",
        response_schema_complexity="simple",
        source_text=source,
        task_intent="term_normalization",
        expected_terms=(
            {"source_variants": ["джанго"], "normalized": "Django"},
            {"source_variants": ["пай сайд"], "normalized": "PySide"},
        ),
        language_drift_policy="warning",
    )

    summary = validate_response(raw, contract)
    drift = _result(summary, "term_normalization_language_drift")

    assert drift.status == "warning"
    assert drift.category == "term_normalization_language_drift"
    assert drift.metrics["language_drift_detected"] is True
    assert drift.metrics["policy"] == "warning"


def test_term_normalization_language_drift_hard_policy_fails() -> None:
    source = "сегодня используем джанго и пай сайд"
    raw = json.dumps({"clean_text": "Today we use Django and PySide."}, ensure_ascii=False)
    contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="skip",
        response_schema_complexity="simple",
        source_text=source,
        task_intent="term_normalization",
        language_drift_policy="hard",
    )

    summary = validate_response(raw, contract)
    drift = _result(summary, "term_normalization_language_drift")

    assert drift.status == "fail"
    assert drift.category == "term_normalization_language_drift"
    assert summary.status == "fail"
