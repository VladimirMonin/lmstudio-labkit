# ruff: noqa: I001

from __future__ import annotations

from pathlib import Path

# fmt: off

from libs import lmstudio_managed
from libs.lmstudio_managed.core_contracts import RouteMode
from libs.lmstudio_managed.registry.recommendations import (
    INTERNAL_RECOMMENDATION_DRAFT_SUMMARY_PATH,
    OPENAI_RESPONSES_CURRENT_LONG_CONTEXT_SCOPE,
    OPENAI_RESPONSES_FUTURE_RETEST_SCOPE,
    OPENAI_RESPONSES_SMALL_CONTEXT_SCOPE,
    InternalRecommendationDraft,
    InternalRecommendationStatus,
    RecommendationAudience,
    build_internal_recommendation_draft,
    is_safe_for_user_facing_recommendation,
    recommendation_for_model,
    render_internal_recommendation_draft_report,
    route_guidance_for,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = PROJECT_ROOT / INTERNAL_RECOMMENDATION_DRAFT_SUMMARY_PATH


def test_l3_7e_internal_draft_has_stable_keys_and_root_exports() -> None:
    draft = build_internal_recommendation_draft()

    assert isinstance(draft, InternalRecommendationDraft)
    assert draft.model_keys == (
        "gemma4_12b_qat",
        "gemma4_26b_a4b_qat",
        "gemma4_e2b_q4km",
        "gemma4_e4b_q4km",
        "qwen35_4b",
        "qwen35_9b",
        "qwen3_6_35b_a3b",
    )

    assert lmstudio_managed.InternalRecommendationStatus is InternalRecommendationStatus
    assert lmstudio_managed.InternalRecommendationDraft is InternalRecommendationDraft
    assert lmstudio_managed.RecommendationAudience is RecommendationAudience
    assert (
        lmstudio_managed.build_internal_recommendation_draft
        is build_internal_recommendation_draft
    )
    assert lmstudio_managed.recommendation_for_model is recommendation_for_model
    assert lmstudio_managed.route_guidance_for is route_guidance_for
    assert (
        lmstudio_managed.render_internal_recommendation_draft_report
        is render_internal_recommendation_draft_report
    )
    assert (
        lmstudio_managed.is_safe_for_user_facing_recommendation
        is is_safe_for_user_facing_recommendation
    )


def test_gemma_e2b_route_guidance_matches_internal_primary_fallback_and_research_policy() -> None:
    draft = build_internal_recommendation_draft()
    gemma = draft.require("gemma4_e2b_q4km")

    assert gemma.status == InternalRecommendationStatus.INTERNAL_PRIMARY_CANDIDATE
    assert gemma.audience == RecommendationAudience.NOT_USER_FACING

    assert (
        draft.route_guidance_for("gemma4_e2b_q4km", RouteMode.COMPACT_MEMORY).status
        == InternalRecommendationStatus.INTERNAL_PRIMARY_CANDIDATE
    )
    assert draft.route_guidance_for(
        "gemma4_e2b_q4km",
        RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
    ).status == InternalRecommendationStatus.INTERNAL_PRIMARY_CANDIDATE
    assert draft.route_guidance_for(
        "gemma4_e2b_q4km",
        RouteMode.NATIVE_CHAT_STATEFUL,
    ).status == InternalRecommendationStatus.RESEARCH_ACCELERATOR
    assert draft.route_guidance_for(
        "gemma4_e2b_q4km",
        RouteMode.STATELESS_FULL_PREFIX,
    ).status == InternalRecommendationStatus.INTERNAL_FALLBACK


def test_l3_7e_openai_responses_policy_stays_scoped_not_globally_blocked() -> None:
    draft = build_internal_recommendation_draft()
    route = draft.route_guidance_for("gemma4_e2b_q4km", RouteMode.OPENAI_RESPONSES)

    assert route is not None
    assert (
        route.status
        == InternalRecommendationStatus.CACHE_ACCOUNTING_CANDIDATE_SMALL_CONTEXT
    )

    scoped = {item.scope_key: item for item in route.scoped_guidance}
    assert scoped[OPENAI_RESPONSES_SMALL_CONTEXT_SCOPE].status == (
        InternalRecommendationStatus.CACHE_ACCOUNTING_CANDIDATE_SMALL_CONTEXT
    )
    assert scoped[OPENAI_RESPONSES_CURRENT_LONG_CONTEXT_SCOPE].status == (
        InternalRecommendationStatus.BLOCKED_CURRENT_EVIDENCE
    )
    assert scoped[OPENAI_RESPONSES_FUTURE_RETEST_SCOPE].status == (
        InternalRecommendationStatus.NEEDS_LIVE_SMOKE
    )
    assert scoped[OPENAI_RESPONSES_FUTURE_RETEST_SCOPE].pending_gates == (
        InternalRecommendationStatus.NEEDS_LIVE_SMOKE,
    )


def test_l3_7e_guardrails_keep_every_model_and_route_non_user_facing() -> None:
    draft = build_internal_recommendation_draft()

    assert draft.audience == RecommendationAudience.NOT_USER_FACING
    assert draft.production_default is False
    assert draft.wvm_runtime_integration is False
    assert draft.kv_reuse_proven is False
    assert draft.final_user_facing_recommendation is False
    assert is_safe_for_user_facing_recommendation(draft) is False
    assert draft.is_safe_for_user_facing_recommendation() is False

    for recommendation in draft.models:
        assert recommendation.audience == RecommendationAudience.NOT_USER_FACING
        assert recommendation.production_default is False
        assert recommendation.wvm_runtime_integration is False
        assert recommendation.kv_reuse_proven is False
        assert recommendation.final_user_facing_recommendation is False
        assert recommendation.is_safe_for_user_facing_recommendation is False

        for route in recommendation.route_guidance:
            assert route.audience == RecommendationAudience.NOT_USER_FACING
            assert route.production_default is False
            assert route.wvm_runtime_integration is False
            assert route.kv_reuse_proven is False
            assert route.final_user_facing_recommendation is False
            assert route.is_safe_for_user_facing_recommendation is False


def test_l3_7e_future_candidates_stay_unverified_and_need_staged_gates() -> None:
    draft = build_internal_recommendation_draft()
    expected_pending = (
        InternalRecommendationStatus.NEEDS_NO_LIVE_FEASIBILITY,
        InternalRecommendationStatus.NEEDS_LOAD_ONLY,
        InternalRecommendationStatus.NEEDS_LIVE_SMOKE,
        InternalRecommendationStatus.NEEDS_STRUCTURED_JSON,
    )

    for model_key in (
        "gemma4_e4b_q4km",
        "gemma4_12b_qat",
        "gemma4_26b_a4b_qat",
        "qwen3_6_35b_a3b",
    ):
        recommendation = draft.require(model_key)
        assert recommendation.status == InternalRecommendationStatus.UNVERIFIED_CANDIDATE
        assert (
            draft.route_guidance_for(model_key, RouteMode.COMPACT_MEMORY).status
            == InternalRecommendationStatus.NEEDS_LOAD_ONLY
        )
        assert (
            draft.route_guidance_for(model_key, RouteMode.NATIVE_CHAT_STATEFUL).status
            == InternalRecommendationStatus.NEEDS_LOAD_ONLY
        )
        assert (
            draft.route_guidance_for(model_key, RouteMode.STATELESS_FULL_PREFIX).status
            == InternalRecommendationStatus.NEEDS_LOAD_ONLY
        )
        assert (
            draft.route_guidance_for(model_key, RouteMode.OPENAI_RESPONSES).status
            == InternalRecommendationStatus.NEEDS_LIVE_SMOKE
        )
        assert draft.route_guidance_for(
            model_key,
            RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
        ).status == InternalRecommendationStatus.NEEDS_STRUCTURED_JSON
        for route in recommendation.route_guidance:
            assert route.pending_gates == expected_pending


def test_l3_7e_qwen_routes_preserve_blocked_and_recovery_policy() -> None:
    draft = build_internal_recommendation_draft()

    assert recommendation_for_model("qwen35_4b", draft).status == (
        InternalRecommendationStatus.BLOCKED_CURRENT_EVIDENCE
    )
    assert (
        route_guidance_for("qwen35_4b", RouteMode.STRICT_JSON_CHAT_COMPLETIONS, draft).status
        == InternalRecommendationStatus.BLOCKED_CURRENT_EVIDENCE
    )

    assert recommendation_for_model("qwen35_9b", draft).status == (
        InternalRecommendationStatus.RECOVERY_EXPERIMENTAL_ONLY
    )
    assert (
        route_guidance_for("qwen35_9b", RouteMode.STRICT_JSON_CHAT_COMPLETIONS, draft).status
        == InternalRecommendationStatus.RECOVERY_EXPERIMENTAL_ONLY
    )


def test_l3_7e_summary_matches_rendered_report_and_contains_guardrail_language() -> None:
    assert SUMMARY_PATH.exists()

    expected = render_internal_recommendation_draft_report(
        build_internal_recommendation_draft()
    )
    report_text = SUMMARY_PATH.read_text(encoding="utf-8")

    assert report_text == expected
    assert "Internal only." in report_text
    assert "No production/default/runtime/UI implication." in report_text
    assert "No final user-facing recommendation." in report_text
    assert "## Next L3.7f decision record" in report_text


# fmt: on
