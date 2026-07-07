from __future__ import annotations

from pathlib import Path

from libs import lmstudio_managed
from libs.lmstudio_managed import StructuredOutputStatus
from libs.lmstudio_managed.core_contracts import ResultClassification, RouteMode
from libs.lmstudio_managed.registry.profiles import (
    LongContextStatus,
    ModelRegistryCatalog,
    ModelRegistryProfile,
    ModelRegistryProfileStatus,
    ParameterClass,
    PrivacyStatus,
    ResponsesRouteStatus,
    build_initial_model_registry,
    get_model_profile,
    responses_long_context_status_for,
    responses_small_context_status_for,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = (
    PROJECT_ROOT
    / "experiments"
    / "lmstudio"
    / "results_summaries"
    / "l3_7b_model_registry_profile_map.md"
)


def test_initial_registry_has_stable_keys_and_guarded_defaults() -> None:
    registry = build_initial_model_registry()

    assert isinstance(registry, ModelRegistryCatalog)
    assert registry.model_keys == ("gemma4_e2b_q4km", "qwen35_4b", "qwen35_9b")
    assert registry.has_route_conflicts is False
    assert registry.is_production_promotion_guarded is True

    for profile in registry.profiles:
        assert profile.production_default is False
        assert profile.kv_reuse_proven is False
        assert profile.is_final_user_facing_recommendation is False
        assert profile.is_production_promotion_guarded is True
        assert profile.strict_json_requires_public_content is True
        assert profile.reasoning_only_json_is_failure is True


def test_gemma_profile_encodes_internal_route_policy_without_user_promotion() -> None:
    registry = build_initial_model_registry()
    profile = registry.require("gemma4_e2b_q4km")

    assert profile.family == "gemma4"
    assert profile.parameter_class == ParameterClass.MEDIUM
    assert profile.quantization == "q4_k_m"
    assert profile.status == ModelRegistryProfileStatus.PRIMARY_LAB_CANDIDATE
    assert profile.structured_output_status == StructuredOutputStatus.SUPPORTED
    assert profile.long_context_status == LongContextStatus.PASSED_32K
    assert profile.privacy_status == PrivacyStatus.PRIVACY_PASSED

    assert profile.supports_route(RouteMode.COMPACT_MEMORY) is True
    assert profile.supports_route(RouteMode.NATIVE_CHAT_STATEFUL) is True
    assert profile.supports_route(RouteMode.OPENAI_RESPONSES) is True
    assert profile.supports_route(RouteMode.STATELESS_FULL_PREFIX) is True
    assert profile.supports_route(RouteMode.STRICT_JSON_CHAT_COMPLETIONS) is True
    assert profile.blocks_route(RouteMode.OPENAI_RESPONSES) is False
    assert profile.recommends_route(RouteMode.COMPACT_MEMORY) is True
    assert profile.recommends_route(RouteMode.OPENAI_RESPONSES) is False
    assert responses_small_context_status_for(profile) == (
        ResponsesRouteStatus.CACHE_ACCOUNTING_CANDIDATE_SMALL_CONTEXT
    )
    assert responses_long_context_status_for(profile) == (
        ResponsesRouteStatus.BLOCKED_BY_CURRENT_EVIDENCE
    )
    assert profile.responses_retest_status == (
        ResponsesRouteStatus.NEEDS_RETEST_ON_NEW_MODEL_OR_BUILD
    )

    assert profile.classification_for(RouteMode.COMPACT_MEMORY) == (
        ResultClassification.PRIMARY_CANDIDATE
    )
    assert profile.classification_for(RouteMode.NATIVE_CHAT_STATEFUL) == (
        ResultClassification.RESEARCH_LATENCY_CANDIDATE
    )
    assert profile.classification_for(RouteMode.STATELESS_FULL_PREFIX) == (
        ResultClassification.BASELINE
    )
    assert profile.classification_for(RouteMode.OPENAI_RESPONSES) == (
        ResultClassification.CACHE_ACCOUNTING_CANDIDATE
    )
    assert profile.is_final_user_facing_recommendation is False


def test_qwen_profiles_preserve_blocked_and_recovery_structured_output_policy() -> None:
    registry = build_initial_model_registry()
    qwen4b = registry.require("qwen35_4b")
    qwen9b = registry.require("qwen35_9b")

    assert qwen4b.status == ModelRegistryProfileStatus.BLOCKED_STRUCTURED_OUTPUT
    assert qwen4b.structured_output_status == StructuredOutputStatus.BLOCKED
    assert qwen4b.blocks_route(RouteMode.STRICT_JSON_CHAT_COMPLETIONS) is True
    assert qwen4b.supported_routes == ()
    assert qwen4b.classification_for(RouteMode.STRICT_JSON_CHAT_COMPLETIONS) == (
        ResultClassification.BLOCKED
    )

    assert qwen9b.status == ModelRegistryProfileStatus.RECOVERY_EXPERIMENTAL
    assert qwen9b.structured_output_status == StructuredOutputStatus.SUPPORTED
    assert qwen9b.supports_route(RouteMode.STRICT_JSON_CHAT_COMPLETIONS) is True
    assert qwen9b.recommended_routes == ()
    assert qwen9b.quantization is None


def test_profile_guards_reject_route_conflicts_and_production_inference() -> None:
    try:
        ModelRegistryProfile(
            model_key="bad-conflict",
            model_id="bad/model",
            family="bad",
            parameter_class=ParameterClass.UNKNOWN,
            quantization=None,
            backend="lmstudio",
            supported_routes=(RouteMode.COMPACT_MEMORY,),
            blocked_routes=(RouteMode.COMPACT_MEMORY,),
        )
    except ValueError as exc:
        assert "Blocked routes cannot be supported or recommended" in str(exc)
    else:
        raise AssertionError("Expected route conflict guard")

    try:
        ModelRegistryProfile(
            model_key="bad-production",
            model_id="bad/model",
            family="bad",
            parameter_class=ParameterClass.UNKNOWN,
            quantization=None,
            backend="lmstudio",
            production_default=True,
        )
    except ValueError as exc:
        assert "production_default=true" in str(exc)
    else:
        raise AssertionError("Expected production inference guard")


def test_registry_helper_and_root_exports_are_available() -> None:
    registry = build_initial_model_registry()

    assert get_model_profile(registry, "gemma4_e2b_q4km") == registry.require("gemma4_e2b_q4km")
    assert get_model_profile(registry, "missing") is None
    assert responses_small_context_status_for(registry.require("gemma4_e2b_q4km")) == (
        ResponsesRouteStatus.CACHE_ACCOUNTING_CANDIDATE_SMALL_CONTEXT
    )
    assert responses_long_context_status_for(get_model_profile(registry, "missing")) == (
        ResponsesRouteStatus.UNVERIFIED_FOR_THIS_MODEL
    )

    assert lmstudio_managed.ModelRegistryCatalog is ModelRegistryCatalog
    assert lmstudio_managed.ModelRegistryProfile is ModelRegistryProfile
    assert lmstudio_managed.ResponsesRouteStatus is ResponsesRouteStatus
    assert lmstudio_managed.build_initial_model_registry is build_initial_model_registry
    assert lmstudio_managed.get_model_profile is get_model_profile
    assert lmstudio_managed.responses_long_context_status_for is responses_long_context_status_for
    assert lmstudio_managed.responses_small_context_status_for is responses_small_context_status_for


def test_l3_7b_summary_file_exists() -> None:
    assert SUMMARY_PATH.exists()


def test_l3_7b_summary_uses_scoped_responses_wording() -> None:
    summary_text = SUMMARY_PATH.read_text(encoding="utf-8")

    assert "blocked for long-context planning" not in summary_text
    assert "blocked for long-context use" not in summary_text
    assert "blocked_by_current_evidence" in summary_text
    assert "unverified_for_this_model" in summary_text
    assert "needs_retest_on_new_model_or_build" in summary_text
