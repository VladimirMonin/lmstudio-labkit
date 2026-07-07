from __future__ import annotations

from pathlib import Path

from libs import lmstudio_managed
from libs.lmstudio_managed.core_contracts import RouteMode
from libs.lmstudio_managed.registry.structured_matrix import (
    GEMMA_E2B_LIVE_ARTIFACT_DIR,
    StructuredJsonGateStatus,
    StructuredJsonValidationMatrix,
    build_structured_json_validation_matrix,
    get_structured_json_matrix_row,
    render_structured_json_validation_matrix_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = (
    PROJECT_ROOT
    / "experiments"
    / "lmstudio"
    / "results_summaries"
    / "l3_7d_structured_json_validation_matrix.md"
)


def test_l3_7d_structured_matrix_has_expected_rows_and_exports() -> None:
    matrix = build_structured_json_validation_matrix()

    assert isinstance(matrix, StructuredJsonValidationMatrix)
    assert set(matrix.model_keys) == {
        "gemma4_e2b_q4km",
        "gemma4_e4b_q4km",
        "gemma4_12b_qat",
        "gemma4_26b_a4b_qat",
        "qwen35_4b",
        "qwen35_9b",
        "qwen3_6_35b_a3b",
    }

    assert lmstudio_managed.StructuredJsonGateStatus is StructuredJsonGateStatus
    assert lmstudio_managed.StructuredJsonValidationMatrix is StructuredJsonValidationMatrix
    assert (
        lmstudio_managed.build_structured_json_validation_matrix
        is build_structured_json_validation_matrix
    )
    assert lmstudio_managed.get_structured_json_matrix_row is get_structured_json_matrix_row
    assert (
        lmstudio_managed.render_structured_json_validation_matrix_report
        is render_structured_json_validation_matrix_report
    )


def test_l3_7d_structured_matrix_keeps_lab_only_production_block() -> None:
    matrix = build_structured_json_validation_matrix()

    for row in matrix.rows:
        assert row.expected_route == RouteMode.STRICT_JSON_CHAT_COMPLETIONS
        assert row.strict_json_requires_public_content is True
        assert row.reasoning_only_json_is_failure is True
        assert row.production_default is False
        assert row.wvm_runtime_integration is False
    assert row.kv_reuse_proven is False

    gemma = matrix.require("gemma4_e2b_q4km")
    assert gemma.status == StructuredJsonGateStatus.PASSED
    assert gemma.live_allowed_in_l3_7d is True
    assert gemma.current_primary_live_smoke_candidate is True
    assert GEMMA_E2B_LIVE_ARTIFACT_DIR in (gemma.notes or "")


def test_l3_7d_qwen_rows_preserve_failure_and_recovery_policy() -> None:
    matrix = build_structured_json_validation_matrix()
    qwen4b = matrix.require("qwen35_4b")
    qwen9b = matrix.require("qwen35_9b")

    assert qwen4b.status == StructuredJsonGateStatus.BLOCKED_CURRENT_EVIDENCE
    assert qwen4b.blocked_by_current_evidence is True
    assert qwen4b.observed_failure_status == StructuredJsonGateStatus.FAILED_REASONING_ONLY_JSON
    assert qwen4b.live_allowed_in_l3_7d is False

    assert qwen9b.status == StructuredJsonGateStatus.PASSED
    assert qwen9b.recovery_experimental_only is True
    assert qwen9b.live_allowed_in_l3_7d is False


def test_l3_7d_future_candidates_remain_not_started_or_unverified() -> None:
    matrix = build_structured_json_validation_matrix()

    assert matrix.require("gemma4_e4b_q4km").status == StructuredJsonGateStatus.NOT_STARTED
    for model_key in (
        "gemma4_12b_qat",
        "gemma4_26b_a4b_qat",
        "qwen3_6_35b_a3b",
    ):
        assert matrix.require(model_key).status == StructuredJsonGateStatus.UNVERIFIED_CANDIDATE
        assert matrix.require(model_key).live_allowed_in_l3_7d is False


def test_l3_7d_summary_file_matches_rendered_matrix() -> None:
    assert SUMMARY_PATH.exists()

    expected_text = render_structured_json_validation_matrix_report(
        build_structured_json_validation_matrix()
    )
    assert GEMMA_E2B_LIVE_ARTIFACT_DIR in expected_text
    assert "structured_gate_status=passed" in expected_text
    assert SUMMARY_PATH.read_text(encoding="utf-8") == expected_text
