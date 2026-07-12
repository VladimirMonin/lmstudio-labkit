from __future__ import annotations

import json

from tools.lmstudio_lab.structured_output_correction import (
    BASE_BUDGETS,
    DEFAULT_PACK,
    build_request,
    classify_length_candidate,
    focused_content,
    m05_output_budget,
    parse_transport,
    score_output,
    summarize_rows,
)


def test_structured_request_binds_schema_and_forces_reasoning_off() -> None:
    request = build_request("google/gemma-4-e2b", "M01", DEFAULT_PACK)
    assert request["reasoning"] == {"effort": "none"}
    assert request["temperature"] == 0
    assert request["stream"] is False
    assert request["store"] is False
    assert request["max_output_tokens"] == BASE_BUDGETS["M01"]
    response_format = request["text"]["format"]
    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    assert response_format["schema"]["additionalProperties"] is False


def test_focused_content_preserves_frozen_sanitized_payload() -> None:
    content = focused_content("google/gemma-4-e2b", "M05", DEFAULT_PACK)
    stable, suffix = content.split("\n", 1)
    document = json.loads(stable)
    assert document["sanitized_input"] == json.loads(
        (DEFAULT_PACK / "views/M05/fixture.json").read_text(encoding="utf-8")
    )
    assert document["output_schema"] == json.loads(
        (DEFAULT_PACK / "schemas/normalization_output_v1.schema.json").read_text(encoding="utf-8")
    )
    assert json.loads(suffix) == {"chunk_control": "blocks_stress", "ordinal_source": 0}


def test_m05_budget_has_two_times_utf8_reference_headroom() -> None:
    budget, derivation = m05_output_budget(DEFAULT_PACK)
    assert budget == 4096
    assert budget >= derivation["reference_utf8_bytes"] * 2
    assert derivation["headroom_multiplier"] == 2


def test_transport_taxonomy_separates_raw_and_fenced_json() -> None:
    assert parse_transport('{"ok":true}') == ({"ok": True}, True, True)
    assert parse_transport('```json\n{"ok":true}\n```') == ({"ok": True}, False, True)
    assert parse_transport("not json") == (None, False, False)


def test_length_candidate_includes_exact_budget_despite_stop_reason() -> None:
    assert classify_length_candidate("stop", {"output_tokens": 4096}, 4096) is True
    assert classify_length_candidate("stop", {"output_tokens": 4095}, 4096) is False
    assert classify_length_candidate("max_output_tokens", None, 4096) is True


def test_structural_score_reports_each_capability_axis() -> None:
    text = json.dumps(
        {
            "view_label": "L02-L",
            "retained_unit_count": 428,
            "first_unit_index": 0,
            "last_unit_index": 427,
            "summary": "Retained all units.",
        }
    )
    score = score_output("L02-L", text, DEFAULT_PACK)
    assert score == {
        "raw_json": True,
        "extracted_or_fenced_json": True,
        "exact_schema": True,
        "semantic_fidelity": None,
        "placeholder_fidelity": None,
        "structural_retention": True,
        "strict_end_to_end_acceptance": True,
        "hard_failures": [],
    }


def test_summary_does_not_collapse_schema_capability_into_strict_acceptance() -> None:
    rows = [
        {
            "model_id": "google/gemma-4-e2b",
            "length_hit": False,
            "usage": {"output_tokens_details": {"reasoning_tokens": 0}},
            "scores": {
                "raw_json": True,
                "extracted_or_fenced_json": True,
                "exact_schema": True,
                "semantic_fidelity": False,
                "placeholder_fidelity": False,
                "structural_retention": None,
                "strict_end_to_end_acceptance": False,
            },
        }
    ]
    summary = summarize_rows(rows)
    e2b = summary["models"]["google/gemma-4-e2b"]
    assert e2b["exact_schema"] == 1
    assert e2b["strict_end_to_end_acceptance"] == 0
    assert summary["strictly_accepted_calls"] == 0
