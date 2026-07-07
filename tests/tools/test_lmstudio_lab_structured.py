from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools import lmstudio_lab

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRUCTURED_FIXTURES_ROOT = PROJECT_ROOT / "experiments" / "lmstudio" / "fixtures" / "structured"
EXAMPLE_CONFIG_PATH = (
    PROJECT_ROOT / "experiments" / "lmstudio" / "examples" / "dry_run_minimal.yaml"
)


def _read_structured_fixture(name: str) -> str:
    return (STRUCTURED_FIXTURES_ROOT / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    (
        "fixture_name",
        "expected_ids",
        "finish_reason",
        "expected_fields",
        "raw_markers",
    ),
    [
        pytest.param(
            "valid_blocks_response.json",
            [101, 102],
            None,
            {
                "json_parse_pass": True,
                "schema_pass": True,
                "business_pass": True,
                "ids_exact_pass": True,
                "no_duplicate_ids": True,
                "order_preserved": True,
                "non_empty_text_pass": True,
                "reasoning_leak": False,
                "returned_count": 2,
                "error_category": None,
            },
            ["Synthetic alpha fact.", "Synthetic beta fact."],
            id="valid_blocks_response",
        ),
        pytest.param(
            "invalid_json_truncated.txt",
            [101],
            None,
            {
                "json_parse_pass": False,
                "schema_pass": False,
                "business_pass": False,
                "ids_exact_pass": None,
                "no_duplicate_ids": None,
                "order_preserved": None,
                "non_empty_text_pass": None,
                "reasoning_leak": False,
                "returned_count": None,
                "error_category": "invalid_json",
            },
            ["SYNTH_TRUNCATED_FACT"],
            id="invalid_json_truncated",
        ),
        pytest.param(
            "schema_missing_blocks.json",
            [101],
            None,
            {
                "json_parse_pass": True,
                "schema_pass": False,
                "business_pass": False,
                "ids_exact_pass": None,
                "no_duplicate_ids": None,
                "order_preserved": None,
                "non_empty_text_pass": None,
                "reasoning_leak": False,
                "returned_count": None,
                "error_category": "schema",
            },
            ["Synthetic schema-miss fact."],
            id="schema_missing_blocks",
        ),
        pytest.param(
            "business_missing_id.json",
            [101, 102],
            None,
            {
                "json_parse_pass": True,
                "schema_pass": True,
                "business_pass": False,
                "ids_exact_pass": False,
                "no_duplicate_ids": True,
                "order_preserved": False,
                "non_empty_text_pass": True,
                "reasoning_leak": False,
                "returned_count": 1,
                "error_category": "ids",
            },
            ["Synthetic first fact."],
            id="business_missing_id",
        ),
        pytest.param(
            "business_duplicate_id.json",
            [101, 102],
            None,
            {
                "json_parse_pass": True,
                "schema_pass": True,
                "business_pass": False,
                "ids_exact_pass": False,
                "no_duplicate_ids": False,
                "order_preserved": False,
                "non_empty_text_pass": True,
                "reasoning_leak": False,
                "returned_count": 2,
                "error_category": "ids",
            },
            ["Synthetic duplicate fact."],
            id="business_duplicate_id",
        ),
        pytest.param(
            "business_new_id.json",
            [101, 102],
            None,
            {
                "json_parse_pass": True,
                "schema_pass": True,
                "business_pass": False,
                "ids_exact_pass": False,
                "no_duplicate_ids": True,
                "order_preserved": False,
                "non_empty_text_pass": True,
                "reasoning_leak": False,
                "returned_count": 2,
                "error_category": "ids",
            },
            ["Synthetic unexpected fact."],
            id="business_new_id",
        ),
        pytest.param(
            "business_reordered_ids.json",
            [101, 102],
            None,
            {
                "json_parse_pass": True,
                "schema_pass": True,
                "business_pass": False,
                "ids_exact_pass": True,
                "no_duplicate_ids": True,
                "order_preserved": False,
                "non_empty_text_pass": True,
                "reasoning_leak": False,
                "returned_count": 2,
                "error_category": "ids",
            },
            ["Synthetic second fact."],
            id="business_reordered_ids",
        ),
        pytest.param(
            "business_empty_text.json",
            [101],
            None,
            {
                "json_parse_pass": True,
                "schema_pass": True,
                "business_pass": False,
                "ids_exact_pass": True,
                "no_duplicate_ids": True,
                "order_preserved": True,
                "non_empty_text_pass": False,
                "reasoning_leak": False,
                "returned_count": 1,
                "error_category": "empty_text",
            },
            ['"normalized_text": "   "'],
            id="business_empty_text",
        ),
        pytest.param(
            "reasoning_leak_think_tag.json",
            [101],
            None,
            {
                "json_parse_pass": True,
                "schema_pass": True,
                "business_pass": False,
                "ids_exact_pass": True,
                "no_duplicate_ids": True,
                "order_preserved": True,
                "non_empty_text_pass": True,
                "reasoning_leak": True,
                "returned_count": 1,
                "error_category": "reasoning_leak",
            },
            ["SYNTH_HIDDEN_THINK", "<think"],
            id="reasoning_leak_think_tag",
        ),
        pytest.param(
            "reasoning_leak_reasoning_content.json",
            [101],
            None,
            {
                "json_parse_pass": True,
                "schema_pass": False,
                "business_pass": False,
                "ids_exact_pass": None,
                "no_duplicate_ids": None,
                "order_preserved": None,
                "non_empty_text_pass": None,
                "reasoning_leak": True,
                "returned_count": 1,
                "error_category": "reasoning_leak",
            },
            ["SYNTH_REASONING_CONTENT", "reasoning_content"],
            id="reasoning_leak_reasoning_content",
        ),
        pytest.param(
            "markdown_before_json.txt",
            [101],
            None,
            {
                "json_parse_pass": False,
                "schema_pass": False,
                "business_pass": False,
                "ids_exact_pass": None,
                "no_duplicate_ids": None,
                "order_preserved": None,
                "non_empty_text_pass": None,
                "reasoning_leak": False,
                "returned_count": None,
                "error_category": "invalid_json",
            },
            ["SYNTH_MARKDOWN_PREFIX", "Result preview:"],
            id="markdown_before_json",
        ),
        pytest.param(
            "finish_length_case.json",
            [101],
            "length",
            {
                "json_parse_pass": True,
                "schema_pass": True,
                "business_pass": False,
                "ids_exact_pass": True,
                "no_duplicate_ids": True,
                "order_preserved": True,
                "non_empty_text_pass": True,
                "reasoning_leak": False,
                "returned_count": 1,
                "error_category": "finish_length",
            },
            ["Synthetic finish length fact."],
            id="finish_length_case",
        ),
    ],
)
def test_validate_factual_blocks_response_matches_golden_fixture_expectations(
    fixture_name: str,
    expected_ids: list[int],
    finish_reason: str | None,
    expected_fields: dict[str, object],
    raw_markers: list[str],
) -> None:
    response_text = _read_structured_fixture(fixture_name)

    result = lmstudio_lab.validate_factual_blocks_response(
        response_text,
        expected_block_ids=expected_ids,
        finish_reason=finish_reason,
    )

    assert result.schema_name == "factual_blocks.v1"
    assert result.expected_count == len(expected_ids)
    assert result.finish_reason == finish_reason
    for field_name, expected_value in expected_fields.items():
        assert getattr(result, field_name) == expected_value

    serialized = json.dumps(result.to_dict(), sort_keys=True)
    assert result.to_dict()["schema_version"] == lmstudio_lab.SCHEMA_VERSION
    assert response_text not in serialized
    for marker in raw_markers:
        assert marker.casefold() not in serialized.casefold()


@pytest.mark.parametrize(
    "reasoning_key",
    ["reasoning_content", "reasoningContent", "ReasoningContent"],
)
def test_validate_factual_blocks_response_flags_reasoning_content_key_variants(
    reasoning_key: str,
) -> None:
    result = lmstudio_lab.validate_factual_blocks_response(
        json.dumps(
            {
                "schema_version": "factual_blocks.v1",
                "status": "success",
                "blocks": [
                    {
                        "block_id": 1,
                        "normalized_text": "Visible fact.",
                        "status": "success",
                        "warnings": [],
                        reasoning_key: "SYNTH_VARIANT_REASONING",
                    }
                ],
                "warnings": [],
            }
        ),
        expected_block_ids=[1],
    )

    assert result.schema_pass is False
    assert result.reasoning_leak is True
    assert result.business_pass is False
    assert result.error_category == "reasoning_leak"

    serialized = json.dumps(result.to_dict(), sort_keys=True)
    assert reasoning_key.casefold() not in serialized.casefold()
    assert "SYNTH_VARIANT_REASONING".casefold() not in serialized.casefold()


@pytest.mark.parametrize(
    ("payload", "expected_error_category"),
    [
        pytest.param(
            {
                "schema_version": "factual_blocks.v0",
                "status": "success",
                "blocks": [
                    {
                        "block_id": 1,
                        "normalized_text": "Visible fact.",
                        "status": "success",
                        "warnings": [],
                    }
                ],
                "warnings": [],
            },
            "schema_version",
            id="schema_version_mismatch",
        ),
        pytest.param(
            {
                "schema_version": "factual_blocks.v1",
                "status": "partial",
                "blocks": [
                    {
                        "block_id": 1,
                        "normalized_text": "Visible fact.",
                        "status": "success",
                        "warnings": [],
                    }
                ],
                "warnings": [],
            },
            "status",
            id="top_level_status_not_success",
        ),
        pytest.param(
            {
                "schema_version": "factual_blocks.v1",
                "status": "success",
                "blocks": [
                    {
                        "block_id": 1,
                        "normalized_text": "Visible fact.",
                        "status": "missing",
                        "warnings": ["synthetic placeholder"],
                    }
                ],
                "warnings": [],
            },
            "status",
            id="block_status_not_success",
        ),
    ],
)
def test_validate_factual_blocks_response_requires_canonical_status_contract(
    payload: dict[str, object],
    expected_error_category: str,
) -> None:
    result = lmstudio_lab.validate_factual_blocks_response(
        json.dumps(payload),
        expected_block_ids=[1],
    )

    assert result.json_parse_pass is True
    assert result.schema_pass is True
    assert result.business_pass is False
    assert result.ids_exact_pass is True
    assert result.no_duplicate_ids is True
    assert result.order_preserved is True
    assert result.non_empty_text_pass is True
    assert result.error_category == expected_error_category


@pytest.mark.parametrize(
    ("payload", "raw_marker"),
    [
        pytest.param(
            {
                "schema_version": "factual_blocks.v1",
                "status": "success",
                "blocks": [{"id": 1, "text": "Legacy fact."}],
                "warnings": [],
            },
            '"id": 1',
            id="legacy_id_text_fields",
        ),
        pytest.param(
            {
                "schema_version": "factual_blocks.v1",
                "status": "success",
                "blocks": [
                    {
                        "block_id": 1,
                        "normalized_text": "Visible fact.",
                        "status": "success",
                        "warnings": [],
                        "start": 0,
                        "end": 42,
                    }
                ],
                "warnings": [],
            },
            '"start": 0',
            id="extra_start_end_fields",
        ),
    ],
)
def test_validate_factual_blocks_response_rejects_legacy_or_extra_block_fields(
    payload: dict[str, object],
    raw_marker: str,
) -> None:
    response_text = json.dumps(payload)

    result = lmstudio_lab.validate_factual_blocks_response(
        response_text,
        expected_block_ids=[1],
    )

    assert result.json_parse_pass is True
    assert result.schema_pass is False
    assert result.business_pass is False
    assert result.error_category == "schema"

    serialized = json.dumps(result.to_dict(), sort_keys=True)
    assert raw_marker not in serialized


@pytest.mark.parametrize(
    "expected_ids",
    [
        [],
        [1, 1],
        [True],
        [1, "2"],
    ],
)
def test_validate_factual_blocks_response_rejects_invalid_expected_ids(
    expected_ids: object,
) -> None:
    with pytest.raises(ValueError):
        lmstudio_lab.validate_factual_blocks_response(
            json.dumps(
                {
                    "schema_version": "factual_blocks.v1",
                    "status": "success",
                    "blocks": [
                        {
                            "block_id": 1,
                            "normalized_text": "Fact.",
                            "status": "success",
                            "warnings": [],
                        }
                    ],
                    "warnings": [],
                }
            ),
            expected_block_ids=expected_ids,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("retry_count", "match"),
    [
        (True, "retry_count must be an integer"),
        (-1, "retry_count must be >= 0"),
        ("1", "retry_count must be an integer"),
    ],
)
def test_validate_factual_blocks_response_rejects_invalid_retry_count(
    retry_count: object,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        lmstudio_lab.validate_factual_blocks_response(
            json.dumps(
                {
                    "schema_version": "factual_blocks.v1",
                    "status": "success",
                    "blocks": [
                        {
                            "block_id": 1,
                            "normalized_text": "Fact.",
                            "status": "success",
                            "warnings": [],
                        }
                    ],
                    "warnings": [],
                }
            ),
            expected_block_ids=[1],
            retry_count=retry_count,  # type: ignore[arg-type]
        )


def test_validate_factual_blocks_response_rejects_invalid_finish_reason_type() -> None:
    with pytest.raises(ValueError, match="finish_reason must be a string"):
        lmstudio_lab.validate_factual_blocks_response(
            json.dumps(
                {
                    "schema_version": "factual_blocks.v1",
                    "status": "success",
                    "blocks": [
                        {
                            "block_id": 1,
                            "normalized_text": "Fact.",
                            "status": "success",
                            "warnings": [],
                        }
                    ],
                    "warnings": [],
                }
            ),
            expected_block_ids=[1],
            finish_reason=123,  # type: ignore[arg-type]
        )


def test_validate_factual_blocks_response_returns_id_diagnostics_without_text_payloads() -> None:
    response_text = json.dumps(
        {
            "schema_version": "factual_blocks.v1",
            "status": "success",
            "blocks": [
                {
                    "block_id": 10,
                    "normalized_text": "Alpha fact.",
                    "status": "success",
                    "warnings": [],
                },
                {
                    "block_id": 30,
                    "normalized_text": "Beta fact.",
                    "status": "success",
                    "warnings": [],
                },
                {
                    "block_id": 30,
                    "normalized_text": "Gamma fact.",
                    "status": "success",
                    "warnings": [],
                },
                {
                    "block_id": 50,
                    "normalized_text": "Delta fact.",
                    "status": "success",
                    "warnings": [],
                },
            ],
            "warnings": [],
        }
    )

    result = lmstudio_lab.validate_factual_blocks_response(
        response_text,
        expected_block_ids=[10, 20, 30, 40],
        finish_reason="stop",
    )

    assert result.business_pass is False
    assert result.ids_exact_pass is False
    assert result.no_duplicate_ids is False
    assert result.order_preserved is False
    assert result.expected_count == 4
    assert result.returned_count == 4
    assert result.expected_ids == (10, 20, 30, 40)
    assert result.returned_ids == (10, 30, 30, 50)
    assert result.duplicate_ids == (30,)
    assert result.missing_ids == (20, 40)
    assert result.extra_ids == (50,)
    assert result.reordered_count == 2
    assert result.reordered_positions_truncated is False
    assert result.reordered_positions == (
        {"position": 1, "expected_id": 20, "returned_id": 30},
        {"position": 3, "expected_id": 40, "returned_id": 50},
    )

    serialized = json.dumps(result.to_dict(), sort_keys=True)
    assert "Alpha fact." not in serialized
    assert "Gamma fact." not in serialized


def test_structured_validation_result_to_metrics_keeps_safe_contract() -> None:
    response_text = _read_structured_fixture("valid_blocks_response.json")

    result = lmstudio_lab.validate_factual_blocks_response(
        response_text,
        expected_block_ids=[101, 102],
        finish_reason="stop",
        retry_count=1,
    )

    assert result.to_metrics() == lmstudio_lab.ValidationMetrics(
        json_parse_pass=True,
        schema_pass=True,
        business_pass=True,
        ids_exact_pass=True,
        no_duplicate_ids=True,
        order_preserved=True,
        non_empty_text_pass=True,
        reasoning_leak=False,
        retry_count=1,
        finish_reason="stop",
        expected_count=2,
        returned_count=2,
        expected_ids=(101, 102),
        returned_ids=(101, 102),
        duplicate_ids=(),
        missing_ids=(),
        extra_ids=(),
        reordered_positions=(),
        reordered_count=0,
        reordered_positions_truncated=False,
    )


def test_summarize_structured_validation_results_counts_rates_and_safe_dict() -> None:
    results = [
        lmstudio_lab.validate_factual_blocks_response(
            _read_structured_fixture("valid_blocks_response.json"),
            expected_block_ids=[101, 102],
        ),
        lmstudio_lab.validate_factual_blocks_response(
            _read_structured_fixture("invalid_json_truncated.txt"),
            expected_block_ids=[101],
        ),
        lmstudio_lab.validate_factual_blocks_response(
            _read_structured_fixture("business_duplicate_id.json"),
            expected_block_ids=[101, 102],
        ),
        lmstudio_lab.validate_factual_blocks_response(
            _read_structured_fixture("finish_length_case.json"),
            expected_block_ids=[101],
            finish_reason="length",
        ),
        lmstudio_lab.validate_factual_blocks_response(
            _read_structured_fixture("reasoning_leak_reasoning_content.json"),
            expected_block_ids=[101],
        ),
        lmstudio_lab.validate_factual_blocks_response(
            _read_structured_fixture("schema_missing_blocks.json"),
            expected_block_ids=[101],
        ),
    ]

    summary = lmstudio_lab.summarize_structured_validation_results(results)

    assert summary.total_count == 6
    assert summary.json_parse_pass_count == 5
    assert summary.json_parse_pass_rate == pytest.approx(5 / 6)
    assert summary.schema_pass_count == 3
    assert summary.schema_pass_rate == pytest.approx(0.5)
    assert summary.business_pass_count == 1
    assert summary.business_pass_rate == pytest.approx(1 / 6)
    assert summary.ids_exact_pass_count == 2
    assert summary.ids_exact_pass_rate == pytest.approx(2 / 6)
    assert summary.reasoning_leak_count == 1
    assert summary.finish_length_count == 1
    assert summary.duplicate_id_count == 1
    assert summary.empty_text_count == 0
    assert summary.invalid_json_count == 1
    assert summary.schema_error_count == 1

    serialized = json.dumps(summary.to_dict(), sort_keys=True)
    assert summary.to_dict()["schema_version"] == lmstudio_lab.SCHEMA_VERSION
    assert "SYNTH_REASONING_CONTENT" not in serialized
    assert "Synthetic alpha fact." not in serialized


def test_summarize_structured_validation_results_returns_null_rates_for_empty_input() -> None:
    summary = lmstudio_lab.summarize_structured_validation_results([])

    assert summary.total_count == 0
    assert summary.json_parse_pass_count == 0
    assert summary.json_parse_pass_rate is None
    assert summary.schema_pass_count == 0
    assert summary.schema_pass_rate is None
    assert summary.business_pass_count == 0
    assert summary.business_pass_rate is None
    assert summary.ids_exact_pass_count == 0
    assert summary.ids_exact_pass_rate is None
    assert summary.reasoning_leak_count == 0
    assert summary.finish_length_count == 0
    assert summary.duplicate_id_count == 0
    assert summary.empty_text_count == 0
    assert summary.invalid_json_count == 0
    assert summary.schema_error_count == 0
    assert summary.to_dict()["schema_version"] == lmstudio_lab.SCHEMA_VERSION


def test_render_dry_run_report_adds_optional_structured_validation_section() -> None:
    config = lmstudio_lab.load_experiment_config(EXAMPLE_CONFIG_PATH)
    summary = lmstudio_lab.summarize_structured_validation_results(
        [
            lmstudio_lab.validate_factual_blocks_response(
                _read_structured_fixture("valid_blocks_response.json"),
                expected_block_ids=[101, 102],
            ),
            lmstudio_lab.validate_factual_blocks_response(
                _read_structured_fixture("invalid_json_truncated.txt"),
                expected_block_ids=[101],
            ),
        ]
    )

    report_text = lmstudio_lab.render_dry_run_report(
        config=config,
        environment={
            "schema_version": lmstudio_lab.SCHEMA_VERSION,
            "dry_run": True,
            "platform_system": "TestOS",
            "platform_release": "1.0",
            "platform_machine": "x86_64",
            "python_version": "3.12.0",
            "git_commit": "abc123",
            "git_branch": "main",
        },
        run_id="structured-summary",
        dataset_rows=[
            {
                "dataset_id": "blocks_json_small",
                "items_count": 1,
                "chars": 12,
                "estimated_input_tokens": 4,
                "actual_input_tokens": None,
                "estimate_error_ratio": None,
                "tokenizer": {
                    "method": "heuristic",
                    "family": "generic",
                    "version": "1.0",
                },
                "content_hash": "sha256:test-dataset",
            }
        ],
        load_config_count=1,
        request_count=2,
        structured_error_count=0,
        structured_validation_summary=summary.to_dict(),
    )

    assert "## Structured Validation" in report_text
    assert "Mode: offline structured validation" in report_text
    assert "LM Studio API: not called" in report_text
    assert (
        "schema_pass meaning: minimal schema-shape validation, not full JSON Schema Draft validation"
        in report_text
    )
    assert "json_parse_pass: count `1`, rate `0.5`" in report_text
    assert "schema_pass: count `1`, rate `0.5`" in report_text
    assert "business_pass: count `1`, rate `0.5`" in report_text
    assert "ids_exact_pass: count `1`, rate `0.5`" in report_text
    assert "reasoning_leak_count: `0`" in report_text
    assert "invalid_json_count: `1`" in report_text
    assert "SYNTH_TRUNCATED_FACT" not in report_text


def test_render_dry_run_report_keeps_existing_output_when_summary_is_not_provided() -> None:
    config = lmstudio_lab.load_experiment_config(EXAMPLE_CONFIG_PATH)

    report_text = lmstudio_lab.render_dry_run_report(
        config=config,
        environment={
            "schema_version": lmstudio_lab.SCHEMA_VERSION,
            "dry_run": True,
            "platform_system": "TestOS",
            "platform_release": "1.0",
            "platform_machine": "x86_64",
            "python_version": "3.12.0",
        },
        run_id="baseline",
        dataset_rows=[
            {
                "dataset_id": "blocks_json_small",
                "items_count": 1,
                "chars": 12,
                "estimated_input_tokens": 4,
                "actual_input_tokens": None,
                "estimate_error_ratio": None,
                "tokenizer": {
                    "method": "heuristic",
                    "family": "generic",
                    "version": "1.0",
                },
                "content_hash": "sha256:test-dataset",
            }
        ],
        load_config_count=1,
        request_count=1,
        structured_error_count=0,
    )

    assert "## Structured Validation" not in report_text
    assert "## Privacy" in report_text


def test_structured_validation_summary_csv_row_uses_empty_cells_for_none_rates(
    tmp_path: Path,
) -> None:
    summary = lmstudio_lab.summarize_structured_validation_results([])
    row = lmstudio_lab.build_structured_validation_summary_csv_row(summary.to_dict())
    target = tmp_path / "structured_summary.csv"

    lmstudio_lab.write_csv_file(
        target,
        fieldnames=lmstudio_lab.STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES,
        rows=[row],
    )

    with target.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(lmstudio_lab.STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES)
        rows = list(reader)

    assert rows == [
        {
            "experiment_id": "",
            "run_id": "",
            "mode": "",
            "dataset_id": "",
            "fixture_set_id": "",
            "status": "",
            "schema_version": "1.0",
            "total_count": "0",
            "json_parse_pass_count": "0",
            "json_parse_pass_rate": "",
            "schema_pass_count": "0",
            "schema_pass_rate": "",
            "business_pass_count": "0",
            "business_pass_rate": "",
            "ids_exact_pass_count": "0",
            "ids_exact_pass_rate": "",
            "reasoning_leak_count": "0",
            "finish_length_count": "0",
            "duplicate_id_count": "0",
            "empty_text_count": "0",
            "invalid_json_count": "0",
            "schema_error_count": "0",
        }
    ]


def test_load_structured_fixture_manifest_reads_all_synthetic_cases() -> None:
    manifest = lmstudio_lab.load_structured_fixture_manifest(STRUCTURED_FIXTURES_ROOT)

    assert manifest.fixture_set_id == "structured_synthetic_v1"
    assert manifest.schema_name == lmstudio_lab.FACTUAL_BLOCKS_SCHEMA_NAME
    assert len(manifest.cases) == 12
    assert {case.file_name for case in manifest.cases} == {
        "valid_blocks_response.json",
        "invalid_json_truncated.txt",
        "schema_missing_blocks.json",
        "business_missing_id.json",
        "business_duplicate_id.json",
        "business_new_id.json",
        "business_reordered_ids.json",
        "business_empty_text.json",
        "reasoning_leak_think_tag.json",
        "reasoning_leak_reasoning_content.json",
        "markdown_before_json.txt",
        "finish_length_case.json",
    }
    finish_length_case = next(
        case for case in manifest.cases if case.fixture_id == "finish_length_case"
    )
    assert finish_length_case.finish_reason == "length"


def test_validate_structured_fixture_manifest_returns_safe_records() -> None:
    batch = lmstudio_lab.validate_structured_fixture_manifest(STRUCTURED_FIXTURES_ROOT)

    assert batch.manifest.fixture_set_id == "structured_synthetic_v1"
    assert len(batch.results) == 12
    assert len(batch.records) == 12

    serialized = json.dumps(batch.records, sort_keys=True)
    assert "Synthetic alpha fact." not in serialized
    assert "SYNTH_TRUNCATED_FACT" not in serialized
    assert "SYNTH_REASONING_CONTENT" not in serialized
    assert '"normalized_text"' not in serialized
    assert '"content"' not in serialized
    assert '"response"' not in serialized
    assert '"file_name"' not in serialized
    assert "path" not in serialized.casefold()
    assert "C:/" not in serialized
    assert "\\\\" not in serialized


@pytest.mark.parametrize(
    ("manifest_text", "match"),
    [
        pytest.param(
            """
fixture_set_id: structured_synthetic_v1
schema_name: factual_blocks.v1
cases:
  - fixture_id: case_one
    file_name: nested/fixture.json
    expected_block_ids: [101]
""",
            "simple relative file name",
            id="unsafe_nested_file_name",
        ),
        pytest.param(
            """
fixture_set_id: structured_synthetic_v1
schema_name: factual_blocks.v1
cases:
  - fixture_id: duplicate_case
    file_name: valid_blocks_response.json
    expected_block_ids: [101, 102]
  - fixture_id: duplicate_case
    file_name: business_new_id.json
    expected_block_ids: [101, 102]
""",
            "duplicate fixture_id",
            id="duplicate_fixture_id",
        ),
    ],
)
def test_load_structured_fixture_manifest_rejects_unsafe_shape(
    tmp_path: Path,
    manifest_text: str,
    match: str,
) -> None:
    tmp_path.joinpath("manifest.yaml").write_text(manifest_text.lstrip(), encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        lmstudio_lab.load_structured_fixture_manifest(tmp_path)


def test_local_structured_schema_file_matches_contract() -> None:
    schema_path = (
        PROJECT_ROOT / "experiments" / "lmstudio" / "schemas" / "factual_blocks_v1.schema.json"
    )

    assert schema_path.exists()
    payload = json.loads(schema_path.read_text(encoding="utf-8"))

    assert payload["title"] == "factual_blocks.v1"
    assert payload["type"] == "object"
    assert payload["additionalProperties"] is False
    assert payload["required"] == ["schema_version", "status", "blocks", "warnings"]
    assert "$ref" not in json.dumps(payload, sort_keys=True)

    assert payload["properties"]["schema_version"]["type"] == "string"
    assert payload["properties"]["status"]["type"] == "string"
    assert payload["properties"]["warnings"] == {
        "type": "array",
        "items": {"type": "string"},
    }

    blocks = payload["properties"]["blocks"]
    assert blocks["type"] == "array"

    block_item = blocks["items"]
    assert block_item["type"] == "object"
    assert block_item["additionalProperties"] is False
    assert block_item["required"] == ["block_id", "normalized_text", "status", "warnings"]
    assert block_item["properties"]["block_id"]["type"] == "integer"
    assert block_item["properties"]["normalized_text"]["type"] == "string"
    assert block_item["properties"]["status"]["type"] == "string"
    assert block_item["properties"]["warnings"] == {
        "type": "array",
        "items": {"type": "string"},
    }
