from __future__ import annotations

# ruff: noqa: I001

from pathlib import Path

from libs import lmstudio_managed
from libs.lmstudio_managed.registry.candidate_execution import (
    CandidateExecutionCatalog,
    CandidateExecutionGateStatus,
    CandidateExecutionRecord,
    L3_8A_GEMMA4_E4B_NO_LIVE_FEASIBILITY_SUMMARY_PATH,
    L3_8B_GEMMA4_E4B_LOAD_ONLY_R2_ARTIFACT_DIR,
    L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ARTIFACT_DIR,
    L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ARTIFACT_DIR,
    L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_PLAN_PATH,
    build_candidate_execution_catalog,
    render_candidate_execution_report,
)
from libs.lmstudio_managed.registry.profiles import ParameterClass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = PROJECT_ROOT / L3_8A_GEMMA4_E4B_NO_LIVE_FEASIBILITY_SUMMARY_PATH
TINY_LIVE_PLAN_PATH = (
    PROJECT_ROOT
    / "experiments"
    / "lmstudio"
    / "results_summaries"
    / "l3_8c_gemma4_e4b_tiny_live_smoke_plan.md"
)
STRICT_JSON_PLAN_PATH = PROJECT_ROOT / L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_PLAN_PATH


def test_l3_8_candidate_execution_catalog_has_gemma4_e4b_execution_record() -> None:
    catalog = build_candidate_execution_catalog()

    assert isinstance(catalog, CandidateExecutionCatalog)
    assert catalog.model_keys == ("gemma4_e4b_q4km",)
    assert lmstudio_managed.CandidateExecutionCatalog is CandidateExecutionCatalog
    assert lmstudio_managed.CandidateExecutionGateStatus is CandidateExecutionGateStatus
    assert lmstudio_managed.CandidateExecutionRecord is CandidateExecutionRecord
    assert lmstudio_managed.build_candidate_execution_catalog is build_candidate_execution_catalog
    assert lmstudio_managed.render_candidate_execution_report is render_candidate_execution_report

    record = catalog.require("gemma4_e4b_q4km")
    assert record.model_id == "google/gemma-4-e4b"
    assert record.family == "gemma4"
    assert record.size_class == ParameterClass.MEDIUM
    assert record.profile_type == "q4_k_m"
    assert record.no_live_feasibility_status == (
        CandidateExecutionGateStatus.NO_LIVE_FEASIBILITY_PASSED
    )
    assert record.load_only_16k_32k_status == CandidateExecutionGateStatus.LOAD_ONLY_PASSED
    assert record.tiny_live_smoke_status == (CandidateExecutionGateStatus.TINY_LIVE_SMOKE_PASSED)
    assert record.structured_json_status == CandidateExecutionGateStatus.STRUCTURED_JSON_PASSED
    assert record.route_matrix_status == (
        CandidateExecutionGateStatus.ROUTE_MATRIX_BLOCKED_UNTIL_PREREQUISITES
    )
    assert record.load_only_context_tiers == (16_384, 32_768)
    assert record.route_matrix_blocked is True
    assert record.production_default is False
    assert record.wvm_runtime_integration is False
    assert record.kv_reuse_proven is False
    assert record.final_user_facing_recommendation is False
    assert record.summary_ref == L3_8A_GEMMA4_E4B_NO_LIVE_FEASIBILITY_SUMMARY_PATH
    assert L3_8B_GEMMA4_E4B_LOAD_ONLY_R2_ARTIFACT_DIR in (record.notes or "")
    assert L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ARTIFACT_DIR in (record.notes or "")
    assert L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ARTIFACT_DIR in (record.notes or "")
    assert L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_PLAN_PATH in (record.notes or "")
    assert "eligible for L3.9 product-shaped viability gates" in (record.notes or "")
    assert "route matrix expansion remains blocked/deferred" in (record.notes or "")


def test_l3_8_candidate_execution_report_render_mentions_blocked_route_matrix() -> None:
    report_text = render_candidate_execution_report(build_candidate_execution_catalog())

    assert "no_live_feasibility_passed" in report_text
    assert "load_only_passed" in report_text
    assert "tiny_live_smoke_passed" in report_text
    assert "structured_json_passed" in report_text
    assert "route_matrix_blocked_until_prerequisites" in report_text
    assert "production_default: `false`" in report_text
    assert L3_8B_GEMMA4_E4B_LOAD_ONLY_R2_ARTIFACT_DIR in report_text
    assert L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ARTIFACT_DIR in report_text
    assert L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ARTIFACT_DIR in report_text
    assert L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_PLAN_PATH in report_text
    assert "eligible for L3.9 product-shaped viability gates only" in report_text
    assert "Next gate: L3.9a Blocks JSON functional viability." in report_text
    assert "/api/v1/chat" not in report_text
    assert "/v1/responses" not in report_text
    assert "/v1/chat/completions" not in report_text


def test_l3_8_no_live_feasibility_summary_exists_and_stays_no_live_only() -> None:
    assert SUMMARY_PATH.exists()

    summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
    assert "gemma4_e4b_q4km" in summary_text
    assert "google/gemma-4-e4b" in summary_text
    assert "no_live_feasibility_passed" in summary_text
    assert "load_only_pending" in summary_text
    assert "route_matrix_blocked_until_prerequisites" in summary_text
    assert "production_default: `false`" in summary_text
    assert "wvm_runtime_integration: `false`" in summary_text
    assert "kv_reuse_proven: `false`" in summary_text
    assert "final_user_facing_recommendation: `false`" in summary_text
    assert "/api/v1/chat" not in summary_text
    assert "/v1/responses" not in summary_text
    assert "/v1/chat/completions" not in summary_text


def test_l3_8c_tiny_live_plan_exists_and_stays_non_promotional() -> None:
    assert TINY_LIVE_PLAN_PATH.exists()

    plan_text = TINY_LIVE_PLAN_PATH.read_text(encoding="utf-8")
    assert "gemma4_e4b_q4km" in plan_text
    assert "google/gemma-4-e4b" in plan_text
    assert "accepted controlled live proof" in plan_text
    assert "This document preserves the pre-live plan" in plan_text
    assert "tiny_live_smoke_passed" in plan_text
    assert L3_8B_GEMMA4_E4B_LOAD_ONLY_R2_ARTIFACT_DIR in plan_text
    assert L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ARTIFACT_DIR in plan_text
    assert "production_default: `false`" in plan_text
    assert "wvm_runtime_integration: `false`" in plan_text
    assert "kv_reuse_proven: `false`" in plan_text
    assert "final_user_facing_recommendation: `false`" in plan_text
    assert "structured_json remains pending" in plan_text
    assert "route matrix remains blocked" in plan_text


def test_l3_8d_strict_json_plan_exists_and_stays_non_promotional() -> None:
    assert STRICT_JSON_PLAN_PATH.exists()

    plan_text = STRICT_JSON_PLAN_PATH.read_text(encoding="utf-8")
    assert "gemma4_e4b_q4km" in plan_text
    assert "google/gemma-4-e4b" in plan_text
    assert "structured_json_pending" in plan_text
    assert "structured_json_passed" in plan_text
    assert "L3.8d passed." in plan_text
    assert L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ARTIFACT_DIR in plan_text
    assert "eligible for L3.9 product-shaped viability gates" in plan_text
    assert "production_default: `false`" in plan_text
    assert "wvm_runtime_integration: `false`" in plan_text
    assert "kv_reuse_proven: `false`" in plan_text
    assert "final_user_facing_recommendation: `false`" in plan_text
    assert "This is not production." in plan_text
    assert "This is not host application runtime integration." in plan_text
    assert "This is not route matrix approval." in plan_text
    assert "This is not a final user-facing recommendation." in plan_text
    assert "L3.9a Blocks JSON functional viability" in plan_text


def test_l3_8_candidate_execution_record_rejects_promotion_flags() -> None:
    for extra_kwargs, message in (
        ({"production_default": True}, "production_default=true"),
        ({"wvm_runtime_integration": True}, "wvm_runtime_integration=true"),
        ({"kv_reuse_proven": True}, "kv_reuse_proven=true"),
        (
            {"final_user_facing_recommendation": True},
            "final_user_facing_recommendation=true",
        ),
    ):
        try:
            CandidateExecutionRecord(
                model_key="gemma4_e4b_q4km",
                model_id="google/gemma-4-e4b",
                family="gemma4",
                size_class=ParameterClass.MEDIUM,
                profile_type="q4_k_m",
                no_live_feasibility_status=(
                    CandidateExecutionGateStatus.NO_LIVE_FEASIBILITY_PASSED
                ),
                load_only_16k_32k_status=CandidateExecutionGateStatus.LOAD_ONLY_PASSED,
                tiny_live_smoke_status=CandidateExecutionGateStatus.TINY_LIVE_SMOKE_PASSED,
                structured_json_status=CandidateExecutionGateStatus.STRUCTURED_JSON_PASSED,
                route_matrix_status=(
                    CandidateExecutionGateStatus.ROUTE_MATRIX_BLOCKED_UNTIL_PREREQUISITES
                ),
                **extra_kwargs,
            )
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"Expected candidate execution guard for {message}")
