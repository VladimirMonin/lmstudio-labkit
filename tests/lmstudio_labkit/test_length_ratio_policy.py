from __future__ import annotations

import json

from lmstudio_labkit.requests import ResponseContract
from lmstudio_labkit.validation import validate_response

VALID_RESPONSE = json.dumps(
    {
        "id": 0,
        "title": "Заголовок",
        "summary": "Длинное русское описание",
        "tags": ["тест"],
        "language": "ru",
    },
    ensure_ascii=False,
)


def _contract(*, policy: str = "hard", max_ratio: float = 1.0) -> ResponseContract:
    return ResponseContract(
        mode="json",
        schema={
            "type": "object",
            "required": ["id", "title", "summary", "tags", "language"],
            "additionalProperties": False,
            "properties": {
                "id": {"const": 0},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "tags": {"type": "array"},
                "language": {"const": "ru"},
            },
        },
        expected_ids=(0,),
        id_paths=("id",),
        language="ru_ru",
        language_policy="strict_ru",
        expected_output={"id": 0, "summary": "Кратко", "language": "ru"},
        min_length_ratio=0.1,
        max_length_ratio=max_ratio,
        length_ratio_policy=policy,
    )


def test_simple_too_long_warning_does_not_hard_fail() -> None:
    summary = validate_response(
        VALID_RESPONSE,
        _contract(policy="warning", max_ratio=1.0),
        finish_reason="stop",
        input_char_count=20,
    )
    length_ratio = next(item for item in summary.results if item.name == "length_ratio")

    assert summary.status == "pass"
    assert length_ratio.status == "warning"
    assert length_ratio.category == "too_long"
    assert length_ratio.metrics["policy"] == "warning"


def test_medium_blocks_too_long_remains_hard_fail() -> None:
    summary = validate_response(
        VALID_RESPONSE,
        _contract(policy="hard", max_ratio=1.0),
        finish_reason="stop",
        input_char_count=20,
    )

    assert summary.status == "fail"
    length_ratio = next(item for item in summary.results if item.name == "length_ratio")
    assert length_ratio.status == "fail"
    assert length_ratio.category == "too_long"


def test_finish_reason_length_is_hard_failure_even_with_warning_policy() -> None:
    summary = validate_response(
        VALID_RESPONSE,
        _contract(policy="warning", max_ratio=100.0),
        finish_reason="length",
        input_char_count=20,
    )

    assert summary.status == "fail"
    assert (
        next(item for item in summary.results if item.name == "finish_reason_length").status
        == "fail"
    )


def test_other_hard_failures_are_not_hidden_by_length_ratio_warning() -> None:
    cases = [
        ("not json", "json_parse"),
        (json.dumps({"id": 0, "title": "ok"}, ensure_ascii=False), "json_schema"),
        (
            json.dumps(
                {
                    "id": 0,
                    "title": "TODO",
                    "summary": "Русский текст",
                    "tags": ["тест"],
                    "language": "ru",
                },
                ensure_ascii=False,
            ),
            "no_placeholder_text",
        ),
        (
            json.dumps(
                {
                    "id": 0,
                    "title": "English",
                    "summary": "English text",
                    "tags": ["test"],
                    "language": "ru",
                },
                ensure_ascii=False,
            ),
            "language_compliance",
        ),
    ]
    for raw_response, failing_check in cases:
        summary = validate_response(
            raw_response,
            _contract(policy="warning", max_ratio=1.0),
            finish_reason="stop",
            input_char_count=20,
        )
        assert summary.status == "fail"
        assert any(item.name == failing_check and item.status == "fail" for item in summary.results)
