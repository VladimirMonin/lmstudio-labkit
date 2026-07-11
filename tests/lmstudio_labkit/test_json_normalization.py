from __future__ import annotations

from lmstudio_labkit.validation import validate_response

from lmstudio_labkit import ResponseContract, observe_output_budget, parse_json_response

SCHEMA = {
    "type": "object",
    "required": ["status"],
    "additionalProperties": False,
    "properties": {"status": {"type": "string", "const": "ok"}},
}
CONTRACT = ResponseContract(mode="json", schema=SCHEMA)


def test_single_complete_json_fence_is_opt_in_and_preserves_payload_bytes() -> None:
    raw = '  \n```JSON\n{"status":"ok"}\n```\n\t'

    strict = parse_json_response(raw)
    normalized = parse_json_response(raw, policy="single_complete_json_fence")

    assert strict.parse_succeeded is False
    assert normalized.parsed == {"status": "ok"}
    assert normalized.normalized_text == '{"status":"ok"}'
    assert normalized.transformation == "single_complete_json_fence"
    assert normalized.admission_depended_on_normalization is True
    assert normalized.semantic_repair is False
    diagnostics = normalized.safe_diagnostics()
    raw_diagnostics = diagnostics["raw"]
    normalized_diagnostics = diagnostics["normalized"]
    assert isinstance(raw_diagnostics, dict)
    assert isinstance(normalized_diagnostics, dict)
    assert raw_diagnostics["sha256"] != normalized_diagnostics["sha256"]
    assert "message" not in raw_diagnostics["parse"]["error"]


def test_strict_parse_runs_first_and_no_transform_is_recorded_for_raw_json() -> None:
    result = parse_json_response('{"status":"ok"}', policy="single_complete_json_fence")

    assert result.parse_succeeded is True
    assert result.transformation == "none"
    assert result.raw_parse.status == "pass"
    assert result.normalized_parse.status == "not_attempted"


def test_normalizer_rejects_prose_multiple_fences_wrong_tags_and_incomplete_fences() -> None:
    rejected = [
        'prefix\n```json\n{"status":"ok"}\n```',
        '```json\n{"status":"ok"}\n```\n```json\n{}\n```',
        '```python\n{"status":"ok"}\n```',
        '````json\n{"status":"ok"}\n````',
        '```json {"status":"ok"}```',
        '```json\n{"status":"ok"}',
        '```json\n{"status":"ok",}\n```',
    ]

    for raw in rejected:
        result = parse_json_response(raw, policy="single_complete_json_fence")
        assert result.parse_succeeded is False
        assert result.semantic_repair is False


def test_validator_and_budget_observer_share_normalization_policy() -> None:
    raw = '```json\n{"status":"ok"}\n```'

    validation = validate_response(
        raw,
        CONTRACT,
        json_normalization_policy="single_complete_json_fence",
    )
    observation = observe_output_budget(
        raw_response=raw,
        contract=CONTRACT,
        budget=1024,
        finish_reason="stop",
        completion_tokens=12,
        json_normalization_policy="single_complete_json_fence",
    )

    assert validation.status == "pass"
    assert observation.structure_status == "valid"
