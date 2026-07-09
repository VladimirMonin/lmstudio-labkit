from __future__ import annotations

import json

from lmstudio_labkit.requests import ResponseContract
from lmstudio_labkit.validation import validate_response


def _result(summary, name: str):
    return next(item for item in summary.results if item.name == name)


def test_near_identity_warning_for_noisy_identity_cleanup() -> None:
    source = "ну сегодня мы как бы поговорим про django и миграции"
    raw = json.dumps({"clean_text": source}, ensure_ascii=False)
    contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="preserve_input_language",
        response_schema_complexity="simple",
        source_text=source,
        task_intent="transcript_cleanup",
        near_identity_policy="warning",
    )

    summary = validate_response(raw, contract)
    result = _result(summary, "cleanup_noop_diagnostics")

    assert result.status == "warning"
    assert result.category == "cleanup_noop_when_noise_present"
    assert result.metrics["near_identity_warning"] is True
    assert result.metrics["identity_similarity"] == 1.0
    assert result.metrics["changed_char_ratio"] == 0.0
    assert result.metrics["punctuation_delta"] == 0
    assert result.metrics["capitalization_delta"] == 0
    assert result.metrics["asr_noise_reduction_delta"] == 0


def test_near_identity_not_warning_when_punctuation_and_capitalization_improve() -> None:
    source = "сегодня мы поговорим про django и миграции"
    raw = json.dumps(
        {"clean_text": "Сегодня мы поговорим про Django и миграции."},
        ensure_ascii=False,
    )
    contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="preserve_input_language",
        response_schema_complexity="simple",
        source_text=source,
        task_intent="transcript_cleanup",
        near_identity_policy="warning",
    )

    summary = validate_response(raw, contract)
    result = _result(summary, "cleanup_noop_diagnostics")

    assert result.status == "pass"
    assert result.metrics["near_identity_warning"] is False
    assert result.metrics["identity_similarity"] >= 0.8
    assert result.metrics["punctuation_delta"] > 0
    assert result.metrics["capitalization_delta"] > 0
    assert result.metrics["asr_noise_reduction_delta"] > 0


def test_near_identity_hard_policy_can_fail_for_canary_stop_condition() -> None:
    source = "ну сегодня мы как бы поговорим про django"
    raw = json.dumps({"clean_text": source}, ensure_ascii=False)
    contract = ResponseContract(
        mode="json",
        response_schema_complexity="simple",
        source_text=source,
        task_intent="transcript_cleanup",
        near_identity_policy="hard",
    )

    summary = validate_response(raw, contract)

    assert _result(summary, "cleanup_noop_diagnostics").status == "fail"
    assert summary.status == "fail"
