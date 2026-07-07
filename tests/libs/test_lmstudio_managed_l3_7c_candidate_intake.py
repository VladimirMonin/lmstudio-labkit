from __future__ import annotations

from pathlib import Path

from libs import lmstudio_managed
from libs.lmstudio_managed.core_contracts import RouteMode
from libs.lmstudio_managed.registry.candidate_intake import (
    CURRENT_RESPONSES_LONG_CONTEXT_EVIDENCE_BUILD,
    CandidateModelIntakeCatalog,
    CandidateModelStatus,
    build_candidate_model_intake_catalog,
    get_candidate_model_intake,
    resolve_openai_responses_long_context_status,
)
from libs.lmstudio_managed.registry.profiles import ParameterClass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = (
    PROJECT_ROOT
    / "experiments"
    / "lmstudio"
    / "results_summaries"
    / "l3_7c_candidate_model_intake_and_hardware_feasibility.md"
)


def test_candidate_intake_catalog_has_stable_keys_and_root_exports() -> None:
    catalog = build_candidate_model_intake_catalog()

    assert isinstance(catalog, CandidateModelIntakeCatalog)
    assert catalog.model_keys == (
        "gemma4_12b_qat",
        "gemma4_26b_a4b_qat",
        "gemma4_e4b_q4km",
        "qwen3_6_35b_a3b",
    )

    assert lmstudio_managed.CandidateModelStatus is CandidateModelStatus
    assert lmstudio_managed.CandidateModelIntakeCatalog is CandidateModelIntakeCatalog
    assert (
        lmstudio_managed.build_candidate_model_intake_catalog
        is build_candidate_model_intake_catalog
    )
    assert lmstudio_managed.get_candidate_model_intake is get_candidate_model_intake
    assert (
        lmstudio_managed.resolve_openai_responses_long_context_status
        is resolve_openai_responses_long_context_status
    )


def test_unverified_candidates_cannot_be_recommended_or_promoted() -> None:
    catalog = build_candidate_model_intake_catalog()

    for candidate in catalog.candidates:
        assert candidate.current_status == CandidateModelStatus.UNVERIFIED_CANDIDATE
        assert candidate.production_default is False
        assert candidate.final_user_facing_recommendation is False
        assert hasattr(candidate, "wvm_runtime_integration") is False
        assert candidate.is_recommendable is False
        assert candidate.route_statuses.for_route(RouteMode.OPENAI_RESPONSES) == (
            CandidateModelStatus.UNVERIFIED_FOR_THIS_MODEL
        )
        assert candidate.route_statuses.for_route(RouteMode.STRICT_JSON_CHAT_COMPLETIONS) == (
            CandidateModelStatus.STRUCTURED_JSON_PENDING
        )


def test_candidate_profiles_encode_pending_context_and_route_matrix_plan() -> None:
    catalog = build_candidate_model_intake_catalog()
    e4b = catalog.require("gemma4_e4b_q4km")
    qwen35b = catalog.require("qwen3_6_35b_a3b")

    assert e4b.size_class == ParameterClass.MEDIUM
    assert e4b.profile_type == "q4_k_m"
    assert qwen35b.size_class == ParameterClass.LARGE
    assert qwen35b.profile_type == "a3b"

    for candidate in (e4b, qwen35b):
        assert candidate.test_matrix_plan.no_live_feasibility == (
            CandidateModelStatus.NO_LIVE_FEASIBILITY_PENDING
        )
        assert (
            candidate.test_matrix_plan.load_only_16k_32k == CandidateModelStatus.LOAD_ONLY_PENDING
        )
        assert candidate.test_matrix_plan.tiny_live_smoke == CandidateModelStatus.LIVE_SMOKE_PENDING
        assert candidate.test_matrix_plan.structured_json_smoke == (
            CandidateModelStatus.STRUCTURED_JSON_PENDING
        )
        assert candidate.test_matrix_plan.long_context_route_matrix == (
            CandidateModelStatus.ROUTE_MATRIX_PENDING
        )

        assert candidate.context_test_plan.load_only_16k.context_tokens == 16_384
        assert candidate.context_test_plan.load_only_16k.required is True
        assert candidate.context_test_plan.load_only_16k.status == (
            CandidateModelStatus.LOAD_ONLY_PENDING
        )
        assert candidate.context_test_plan.load_only_32k.context_tokens == 32_768
        assert candidate.context_test_plan.load_only_32k.required is True
        assert candidate.context_test_plan.optional_48k.context_tokens == 49_152
        assert candidate.context_test_plan.optional_48k.required is False
        assert candidate.context_test_plan.optional_64k.context_tokens == 65_536
        assert candidate.context_test_plan.optional_64k.required is False


def test_hardware_feasibility_is_policy_only_and_requires_load_only_before_live() -> None:
    catalog = build_candidate_model_intake_catalog()
    hardware = catalog.hardware_feasibility

    assert hardware.os == "windows"
    assert hardware.cpu == "not_probed_in_l3_7c"
    assert hardware.ram == "not_probed_in_l3_7c"
    assert hardware.gpu == "cuda_lab_gpu_present_not_reprofiled_in_l3_7c"
    assert hardware.vram == "not_probed_in_l3_7c_use_existing_privacy_safe_summaries"
    assert hardware.allowed_context_tiers == (16_384, 32_768, 49_152, 65_536)
    assert hardware.load_only_required_before_live is True


def test_blocked_by_current_evidence_is_exact_model_build_scoped_only() -> None:
    catalog = build_candidate_model_intake_catalog()
    evidence_policy = catalog.evidence_policy

    assert (
        resolve_openai_responses_long_context_status(
            evidence_policy=evidence_policy,
            model_key="gemma4_e2b_q4km",
            build_scope=CURRENT_RESPONSES_LONG_CONTEXT_EVIDENCE_BUILD,
        )
        == CandidateModelStatus.BLOCKED_BY_CURRENT_EVIDENCE
    )
    assert (
        evidence_policy.has_exact_block(
            model_key="gemma4_e2b_q4km",
            build_scope=CURRENT_RESPONSES_LONG_CONTEXT_EVIDENCE_BUILD,
        )
        is True
    )

    assert (
        resolve_openai_responses_long_context_status(
            evidence_policy=evidence_policy,
            model_key="gemma4_e2b_q4km",
            build_scope="future_build_under_retest",
        )
        == CandidateModelStatus.UNVERIFIED_FOR_THIS_MODEL
    )
    assert (
        evidence_policy.openai_responses_long_context_retest_status(model_key="gemma4_e2b_q4km")
        == CandidateModelStatus.NEEDS_RETEST_ON_NEW_MODEL_OR_BUILD
    )


def test_future_or_unlisted_models_remain_unverified_not_blocked() -> None:
    catalog = build_candidate_model_intake_catalog()
    evidence_policy = catalog.evidence_policy

    for model_key in ("gemma4_e4b_q4km", "future_unknown_candidate"):
        assert (
            resolve_openai_responses_long_context_status(
                evidence_policy=evidence_policy,
                model_key=model_key,
                build_scope=CURRENT_RESPONSES_LONG_CONTEXT_EVIDENCE_BUILD,
            )
            == CandidateModelStatus.UNVERIFIED_FOR_THIS_MODEL
        )
        assert (
            evidence_policy.has_exact_block(
                model_key=model_key,
                build_scope=CURRENT_RESPONSES_LONG_CONTEXT_EVIDENCE_BUILD,
            )
            is False
        )
        assert (
            evidence_policy.openai_responses_long_context_retest_status(model_key=model_key)
            == CandidateModelStatus.NEEDS_RETEST_ON_NEW_MODEL_OR_BUILD
        )


def test_vision_candidate_is_deferred_not_promoted_into_text_core_catalog() -> None:
    catalog = build_candidate_model_intake_catalog()

    assert [notice.model_key for notice in catalog.deferred_models] == ["qwen3_vl_4b"]
    assert catalog.deferred_models[0].status == CandidateModelStatus.VISION_DEFERRED
    assert get_candidate_model_intake(catalog, "qwen3_vl_4b") is None


def test_l3_7c_summary_exists_and_avoids_live_endpoint_strings() -> None:
    assert SUMMARY_PATH.exists()

    summary_text = SUMMARY_PATH.read_text(encoding="utf-8")

    assert "gemma4_e4b_q4km" in summary_text
    assert "gemma4_12b_qat" in summary_text
    assert "gemma4_26b_a4b_qat" in summary_text
    assert "qwen3_6_35b_a3b" in summary_text
    assert "vision_deferred" in summary_text
    assert "unverified_for_this_model" in summary_text
    assert "/api/v1/chat" not in summary_text
    assert "/v1/responses" not in summary_text
    assert "/v1/chat/completions" not in summary_text
