from __future__ import annotations

import json

from lmstudio_labkit.benchmarks import plan_matrix
from lmstudio_labkit.requests import ResponseContract
from lmstudio_labkit.validation import collect_ids_by_path, validate_response

from lmstudio_labkit import BenchmarkConfig


def nested_document() -> dict:
    return {
        "document": {
            "sections": [
                {
                    "id": "section-a",
                    "title": "A",
                    "blocks": [
                        {"id": 1, "text": "Русский блок"},
                        {"id": "2", "text": "Русский блок"},
                    ],
                },
                {
                    "id": "section-b",
                    "title": "B",
                    "blocks": [{"id": 3, "text": "Русский блок"}],
                },
            ]
        }
    }


def id_result(summary):
    return next(item for item in summary.results if item.name == "id_exact")


def test_collect_ids_by_path_extracts_only_requested_nested_ids() -> None:
    document = nested_document()

    assert collect_ids_by_path(document, "document.sections[*].id") == [
        "section-a",
        "section-b",
    ]
    assert collect_ids_by_path(document, "document.sections[*].blocks[*].id") == ["1", "2", "3"]


def test_block_id_contract_ignores_section_ids() -> None:
    contract = ResponseContract(
        schema={"type": "object"},
        expected_ids=(1, "2", 3),
        id_paths=("document.sections[*].blocks[*].id",),
        language="ru_ru",
    )

    summary = validate_response(json.dumps(nested_document(), ensure_ascii=False), contract)

    assert summary.status == "pass"
    assert id_result(summary).metrics["seen_count"] == 3


def test_section_ids_can_be_validated_without_block_pollution() -> None:
    contract = ResponseContract(
        schema={"type": "object"},
        expected_ids=("section-a", "section-b"),
        id_paths=("document.sections[*].id",),
    )

    summary = validate_response(json.dumps(nested_document(), ensure_ascii=False), contract)

    assert summary.status == "pass"
    assert id_result(summary).metrics["seen_count"] == 2


def test_complex_contract_can_validate_section_and_block_id_paths() -> None:
    contract = ResponseContract(
        schema={"type": "object"},
        expected_ids=("section-a", "section-b", 1, "2", 3),
        id_paths=("document.sections[*].id", "document.sections[*].blocks[*].id"),
    )

    summary = validate_response(json.dumps(nested_document(), ensure_ascii=False), contract)

    assert summary.status == "pass"
    assert id_result(summary).metrics["seen_count"] == 5


def test_preserve_order_can_be_disabled_for_id_set_matching() -> None:
    contract = ResponseContract(
        schema={"type": "object"},
        expected_ids=("section-b", "section-a"),
        id_paths=("document.sections[*].id",),
        preserve_order=False,
    )

    summary = validate_response(json.dumps(nested_document(), ensure_ascii=False), contract)

    assert summary.status == "pass"
    assert id_result(summary).metrics["order_mismatch"] is False


def test_nested_block_order_mismatch_is_reported() -> None:
    contract = ResponseContract(
        schema={"type": "object"},
        expected_ids=("2", "1", "3"),
        id_paths=("document.sections[*].blocks[*].id",),
    )

    summary = validate_response(json.dumps(nested_document(), ensure_ascii=False), contract)
    result = id_result(summary)

    assert summary.status == "fail"
    assert result.category == "id_order_mismatch"
    assert result.metrics["order_mismatch"] is True
    assert result.metrics["first_mismatch_index"] == 0


def test_duplicate_nested_block_ids_are_reported() -> None:
    document = nested_document()
    document["document"]["sections"][1]["blocks"].append({"id": "2", "text": "Duplicate"})
    contract = ResponseContract(
        schema={"type": "object"},
        expected_ids=(1, "2", 3),
        id_paths=("document.sections[*].blocks[*].id",),
    )

    summary = validate_response(json.dumps(document, ensure_ascii=False), contract)
    result = id_result(summary)

    assert summary.status == "fail"
    assert result.metrics["duplicate_count"] == 1


def test_blocks_schema_family_defaults_to_block_id_path() -> None:
    config = BenchmarkConfig.from_dict(
        {
            "run_id": "block_scope",
            "models": [{"model_key": "fake", "model_id": "fake/text"}],
            "tasks": [
                {
                    "task_id": "blocks",
                    "family": "blocks",
                    "modality": "text",
                    "language": "ru_ru",
                    "structure_complexity": "medium",
                    "prompt": "Synthetic prompt",
                    "schema_family": "blocks",
                    "expected_ids": [1, 2],
                    "expected_output": {
                        "blocks": [
                            {"id": 1, "text": "Русский блок"},
                            {"id": "2", "text": "Русский блок"},
                        ],
                    },
                    "tags": ["experimental"],
                }
            ],
            "axes": {
                "modality": ["text"],
                "language": ["ru_ru"],
                "structure_complexity": ["medium"],
                "volume": ["single"],
                "context_tier": ["8192"],
                "schema_variant": ["baseline_loose"],
                "retry_policy": ["off"],
            },
        }
    )
    response_contract = plan_matrix(config).cells[0].to_request_plan().envelope.response_contract

    assert response_contract.id_paths == ("blocks[*].id",)

    summary = validate_response(
        json.dumps(config.tasks[0].expected_output, ensure_ascii=False), response_contract
    )

    assert summary.status == "pass"
    assert id_result(summary).metrics["seen_count"] == 2
