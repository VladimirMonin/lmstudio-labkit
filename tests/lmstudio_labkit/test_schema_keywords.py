from __future__ import annotations

import json

from lmstudio_labkit.requests import ResponseContract
from lmstudio_labkit.schema_builders import build_blocks_schema, build_image_medium_schema
from lmstudio_labkit.validation import validate_json_schema, validate_response


def test_schema_keywords_reject_additional_properties_and_lengths() -> None:
    schema = {
        "type": "object",
        "required": ["name", "items", "code"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "minLength": 2, "maxLength": 4},
            "code": {"type": "string", "pattern": "^[A-Z]{2}$"},
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "uniqueItems": True,
                "items": {"type": "integer", "minimum": 1, "maximum": 3},
            },
        },
    }

    assert (
        validate_json_schema({"name": "abc", "code": "AB", "items": [1, 3]}, schema).status
        == "pass"
    )
    assert validate_json_schema({"name": "a", "code": "AB", "items": [1]}, schema).status == "fail"
    assert (
        validate_json_schema({"name": "abcde", "code": "AB", "items": [1]}, schema).status == "fail"
    )
    assert (
        validate_json_schema({"name": "abc", "code": "ab", "items": [1]}, schema).status == "fail"
    )
    assert validate_json_schema({"name": "abc", "code": "AB", "items": []}, schema).status == "fail"
    assert (
        validate_json_schema({"name": "abc", "code": "AB", "items": [1, 2, 3]}, schema).status
        == "fail"
    )
    assert (
        validate_json_schema({"name": "abc", "code": "AB", "items": [1, 1]}, schema).status
        == "fail"
    )
    assert (
        validate_json_schema({"name": "abc", "code": "AB", "items": [4]}, schema).status == "fail"
    )
    assert (
        validate_json_schema(
            {"name": "abc", "code": "AB", "items": [1], "extra": True}, schema
        ).status
        == "fail"
    )


def test_blocks_schema_prefix_items_const_order() -> None:
    schema = build_blocks_schema([0, 1], "hardened_const")

    assert (
        validate_json_schema(
            {"blocks": [{"id": 0, "text": "aa"}, {"id": 1, "text": "bb"}]}, schema
        ).status
        == "pass"
    )
    assert (
        validate_json_schema(
            {"blocks": [{"id": 1, "text": "aa"}, {"id": 0, "text": "bb"}]}, schema
        ).status
        == "fail"
    )
    assert validate_json_schema({"blocks": [{"id": 0, "text": "aa"}]}, schema).status == "fail"


def test_image_schema_builder_has_label_bounds() -> None:
    schema = build_image_medium_schema()
    assert (
        validate_json_schema({"description": "ok", "labels": ["button", "table"]}, schema).status
        == "pass"
    )
    assert (
        validate_json_schema({"description": "ok", "labels": ["button"]}, schema).status == "fail"
    )


def test_validate_response_flags_markdown_fence_and_finish_length() -> None:
    summary = validate_response(
        "```json\n{}\n```",
        ResponseContract(mode="json", schema={"type": "object"}),
        finish_reason="length",
        input_char_count=10,
    )

    failures = {item.name for item in summary.results if item.status == "fail"}
    assert "markdown_fence_leak" in failures
    assert "finish_reason_length" in failures


def test_validate_response_detects_empty_output_for_non_empty_input() -> None:
    summary = validate_response("", ResponseContract(mode="text"), input_char_count=12)
    assert summary.status == "fail"
    assert any(item.name == "empty_text_for_non_empty_input" for item in summary.results)


def test_validate_response_flags_reasoning_leak() -> None:
    text_summary = validate_response(
        "<think>hidden scratchpad</think> final", ResponseContract(mode="text")
    )
    json_summary = validate_response(
        json.dumps({"answer": "final", "chain_of_thought": "hidden"}),
        ResponseContract(mode="json", schema={"type": "object"}),
    )

    assert text_summary.status == "fail"
    assert json_summary.status == "fail"
    assert any(item.name == "no_reasoning_leak" for item in text_summary.results)
    assert any(item.name == "no_reasoning_leak" for item in json_summary.results)


def test_json_schema_serializable() -> None:
    json.dumps(build_blocks_schema(["a", "b"], "baseline_loose"), sort_keys=True)
