"""Lab-only reusable model registry profiles."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ..core_contracts import (
    ExperimentStatus,
    LabEvidenceRef,
    ResultClassification,
    RouteMode,
    RouteRecommendation,
    StructuredOutputStatus,
)


class ParameterClass(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    UNKNOWN = "unknown"


class LongContextStatus(StrEnum):
    PASSED_32K = "passed_32k"
    BLOCKED_INTERNAL_ERROR = "blocked_internal_error"
    BLOCKED_BY_CURRENT_EVIDENCE = "blocked_by_current_evidence"
    UNVERIFIED = "unverified"
    UNVERIFIED_FOR_THIS_MODEL = "unverified_for_this_model"
    NEEDS_RETEST_ON_NEW_MODEL_OR_BUILD = "needs_retest_on_new_model_or_build"


class ResponsesRouteStatus(StrEnum):
    CACHE_ACCOUNTING_CANDIDATE_SMALL_CONTEXT = "cache_accounting_candidate_small_context"
    BLOCKED_BY_CURRENT_EVIDENCE = "blocked_by_current_evidence"
    UNVERIFIED_FOR_THIS_MODEL = "unverified_for_this_model"
    NEEDS_RETEST_ON_NEW_MODEL_OR_BUILD = "needs_retest_on_new_model_or_build"


class PrivacyStatus(StrEnum):
    PRIVACY_PASSED = "privacy_passed"
    PRIVACY_REQUIRED = "privacy_required"
    UNVERIFIED = "unverified"


class ModelRegistryProfileStatus(StrEnum):
    PRIMARY_LAB_CANDIDATE = "primary_lab_candidate"
    BLOCKED_STRUCTURED_OUTPUT = "blocked_structured_output"
    RECOVERY_EXPERIMENTAL = "recovery_experimental"


def _sorted_routes(routes: Iterable[RouteMode]) -> tuple[RouteMode, ...]:
    return tuple(sorted(set(routes), key=lambda route: route.value))


def _sorted_context_lengths(lengths: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted({int(length) for length in lengths}))


def _sorted_evidence_refs(
    evidence_refs: Iterable[LabEvidenceRef],
) -> tuple[LabEvidenceRef, ...]:
    return tuple(sorted(set(evidence_refs), key=lambda ref: (ref.experiment_id, ref.summary_ref)))


def _dedupe_route_recommendations(
    route_recommendations: Iterable[RouteRecommendation],
) -> tuple[RouteRecommendation, ...]:
    by_route: dict[RouteMode, RouteRecommendation] = {}
    for recommendation in route_recommendations:
        if recommendation.route in by_route:
            raise ValueError(f"Duplicate route recommendation for {recommendation.route.value}")
        by_route[recommendation.route] = recommendation
    return tuple(by_route[route] for route in sorted(by_route, key=lambda route: route.value))


@dataclass(frozen=True, slots=True)
class ModelRegistryProfile:
    model_key: str
    model_id: str
    family: str
    parameter_class: ParameterClass
    quantization: str | None
    backend: str
    supported_routes: tuple[RouteMode, ...] = ()
    blocked_routes: tuple[RouteMode, ...] = ()
    recommended_routes: tuple[RouteMode, ...] = ()
    recommended_context_lengths: tuple[int, ...] = ()
    structured_output_status: StructuredOutputStatus = StructuredOutputStatus.UNKNOWN
    long_context_status: LongContextStatus = LongContextStatus.UNVERIFIED
    responses_small_context_status: ResponsesRouteStatus = (
        ResponsesRouteStatus.UNVERIFIED_FOR_THIS_MODEL
    )
    responses_long_context_status: ResponsesRouteStatus = (
        ResponsesRouteStatus.UNVERIFIED_FOR_THIS_MODEL
    )
    responses_retest_status: ResponsesRouteStatus = ResponsesRouteStatus.UNVERIFIED_FOR_THIS_MODEL
    privacy_status: PrivacyStatus = PrivacyStatus.UNVERIFIED
    status: ModelRegistryProfileStatus = ModelRegistryProfileStatus.RECOVERY_EXPERIMENTAL
    evidence_refs: tuple[LabEvidenceRef, ...] = ()
    route_recommendations: tuple[RouteRecommendation, ...] = ()
    strict_json_requires_public_content: bool = True
    reasoning_only_json_is_failure: bool = True
    kv_reuse_proven: bool = False
    production_default: bool = False
    is_final_user_facing_recommendation: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        supported_routes = _sorted_routes(self.supported_routes)
        blocked_routes = _sorted_routes(self.blocked_routes)
        recommended_routes = _sorted_routes(self.recommended_routes)
        recommended_context_lengths = _sorted_context_lengths(self.recommended_context_lengths)
        evidence_refs = _sorted_evidence_refs(self.evidence_refs)
        route_recommendations = _dedupe_route_recommendations(self.route_recommendations)

        route_conflicts = set(blocked_routes) & (set(supported_routes) | set(recommended_routes))
        if route_conflicts:
            conflict_names = ", ".join(
                route.value for route in sorted(route_conflicts, key=lambda item: item.value)
            )
            raise ValueError(f"Blocked routes cannot be supported or recommended: {conflict_names}")

        if not set(recommended_routes).issubset(supported_routes):
            raise ValueError("Recommended routes must be a subset of supported routes")

        if self.production_default:
            raise ValueError("Model registry profiles cannot imply production_default=true")

        if self.is_final_user_facing_recommendation:
            raise ValueError("Lab registry profiles cannot be final user-facing recommendations")

        object.__setattr__(self, "supported_routes", supported_routes)
        object.__setattr__(self, "blocked_routes", blocked_routes)
        object.__setattr__(self, "recommended_routes", recommended_routes)
        object.__setattr__(self, "recommended_context_lengths", recommended_context_lengths)
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(self, "route_recommendations", route_recommendations)

    @property
    def route_conflicts(self) -> tuple[RouteMode, ...]:
        return _sorted_routes(
            set(self.blocked_routes) & (set(self.supported_routes) | set(self.recommended_routes))
        )

    @property
    def has_route_conflicts(self) -> bool:
        return bool(self.route_conflicts)

    @property
    def is_production_promotion_guarded(self) -> bool:
        return (
            not self.production_default
            and not self.is_final_user_facing_recommendation
            and not self.kv_reuse_proven
        )

    def supports_route(self, route: RouteMode) -> bool:
        return route in self.supported_routes

    def blocks_route(self, route: RouteMode) -> bool:
        return route in self.blocked_routes

    def recommends_route(self, route: RouteMode) -> bool:
        return route in self.recommended_routes

    def classification_for(self, route: RouteMode) -> ResultClassification | None:
        for recommendation in self.route_recommendations:
            if recommendation.route == route:
                return recommendation.classification
        return None

    def responses_status_for(self, *, long_context: bool) -> ResponsesRouteStatus:
        if long_context:
            return self.responses_long_context_status
        return self.responses_small_context_status


@dataclass(frozen=True, slots=True)
class ModelRegistryCatalog:
    profiles_by_key: Mapping[str, ModelRegistryProfile]

    def __post_init__(self) -> None:
        normalized = dict(sorted(self.profiles_by_key.items()))
        for model_key, profile in normalized.items():
            if model_key != profile.model_key:
                raise ValueError(
                    f"Registry key '{model_key}' does not match profile key '{profile.model_key}'"
                )
        object.__setattr__(self, "profiles_by_key", MappingProxyType(normalized))

    @property
    def model_keys(self) -> tuple[str, ...]:
        return tuple(self.profiles_by_key)

    @property
    def profiles(self) -> tuple[ModelRegistryProfile, ...]:
        return tuple(self.profiles_by_key.values())

    @property
    def has_route_conflicts(self) -> bool:
        return any(profile.has_route_conflicts for profile in self.profiles)

    @property
    def is_production_promotion_guarded(self) -> bool:
        return all(profile.is_production_promotion_guarded for profile in self.profiles)

    def get(self, model_key: str) -> ModelRegistryProfile | None:
        return self.profiles_by_key.get(model_key)

    def require(self, model_key: str) -> ModelRegistryProfile:
        profile = self.get(model_key)
        if profile is None:
            raise KeyError(model_key)
        return profile


def _summary_ref(filename: str) -> str:
    return f"experiments/lmstudio/results_summaries/{filename}"


def _build_gemma4_e2b_q4km_profile() -> ModelRegistryProfile:
    return ModelRegistryProfile(
        model_key="gemma4_e2b_q4km",
        model_id="google/gemma-4-e2b",
        family="gemma4",
        parameter_class=ParameterClass.MEDIUM,
        quantization="q4_k_m",
        backend="lmstudio",
        supported_routes=(
            RouteMode.COMPACT_MEMORY,
            RouteMode.NATIVE_CHAT_STATEFUL,
            RouteMode.OPENAI_RESPONSES,
            RouteMode.STATELESS_FULL_PREFIX,
            RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
        ),
        recommended_routes=(RouteMode.COMPACT_MEMORY,),
        recommended_context_lengths=(8192, 32768),
        structured_output_status=StructuredOutputStatus.SUPPORTED,
        long_context_status=LongContextStatus.PASSED_32K,
        responses_small_context_status=(
            ResponsesRouteStatus.CACHE_ACCOUNTING_CANDIDATE_SMALL_CONTEXT
        ),
        responses_long_context_status=ResponsesRouteStatus.BLOCKED_BY_CURRENT_EVIDENCE,
        responses_retest_status=ResponsesRouteStatus.NEEDS_RETEST_ON_NEW_MODEL_OR_BUILD,
        privacy_status=PrivacyStatus.PRIVACY_PASSED,
        status=ModelRegistryProfileStatus.PRIMARY_LAB_CANDIDATE,
        evidence_refs=(
            LabEvidenceRef(
                experiment_id="l3_5b_32k_load_only",
                summary_ref=_summary_ref("2026-07-06_l3_5b_32k_load_only_summary.md"),
                notes="32k lifecycle-only proof with cleanup and privacy-safe summary.",
            ),
            LabEvidenceRef(
                experiment_id="l3_5r_responses_cache_probe_2k_8k",
                summary_ref=_summary_ref("2026-07-06_l3_5r_responses_cache_probe_summary.md"),
                notes="Responses kept as small-context cache-accounting research only.",
            ),
            LabEvidenceRef(
                experiment_id="l3_5r_responses_cache_probe_16k",
                summary_ref=_summary_ref("2026-07-06_l3_5r_16k_responses_cache_probe_summary.md"),
                status=ExperimentStatus.BLOCKED_INTERNAL_ERROR,
                notes="16k responses probe blocked by internal_error; do not use for long context.",
            ),
            LabEvidenceRef(
                experiment_id="l3_6c_25k_compact_memory_live_smoke_gemma4_e2b",
                summary_ref=_summary_ref(
                    "run_l3-6c-compact-memory-live-smoke-20260706-r2_l3_6c_25k_compact_memory_live_smoke_gemma4_e2b/report.md"
                ),
                notes="Compact-memory 25k live smoke passed with cleanup and privacy-safe artifacts.",
            ),
            LabEvidenceRef(
                experiment_id="l3_6d_25k_mode_comparison_gemma4_e2b",
                summary_ref=_summary_ref(
                    "run_l3-6d-mode-comparison-20260706_l3_6d_25k_mode_comparison_gemma4_e2b/report.md"
                ),
                notes="Mode comparison established compact_memory, native_chat_stateful, and stateless roles.",
            ),
            LabEvidenceRef(
                experiment_id="l3_6e_decision_record",
                summary_ref=_summary_ref("l3_6e_decision_record.md"),
                notes="Accepted decision record preserves lab-only production block.",
            ),
        ),
        route_recommendations=(
            RouteRecommendation(
                route=RouteMode.COMPACT_MEMORY,
                status=ExperimentStatus.PASSED,
                classification=ResultClassification.PRIMARY_CANDIDATE,
                notes="Primary internal default for the current lab registry.",
            ),
            RouteRecommendation(
                route=RouteMode.NATIVE_CHAT_STATEFUL,
                status=ExperimentStatus.PASSED,
                classification=ResultClassification.RESEARCH_LATENCY_CANDIDATE,
                notes="Research latency accelerator for one-root-many-branches only.",
            ),
            RouteRecommendation(
                route=RouteMode.STATELESS_FULL_PREFIX,
                status=ExperimentStatus.PASSED,
                classification=ResultClassification.BASELINE,
                notes="Baseline fallback route.",
            ),
            RouteRecommendation(
                route=RouteMode.OPENAI_RESPONSES,
                status=ExperimentStatus.PASSED,
                classification=ResultClassification.CACHE_ACCOUNTING_CANDIDATE,
                notes=(
                    "Small-context cache-accounting candidate only; Gemma E2B 16k "
                    "current-evidence probe hit internal_error, so /v1/responses is not "
                    "approved as the current long-context route for this model/build and "
                    "needs retest on a new model or LM Studio build."
                ),
            ),
            RouteRecommendation(
                route=RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
                status=ExperimentStatus.PASSED,
                classification=ResultClassification.PASSED,
                notes=(
                    "Strict JSON route requires public content and rejects reasoning-only JSON."
                ),
            ),
        ),
        notes=(
            "Primary reusable lab candidate only; no host application runtime integration, no user-facing promotion, "
            "and no KV reuse proof."
        ),
    )


def _build_qwen35_4b_profile() -> ModelRegistryProfile:
    return ModelRegistryProfile(
        model_key="qwen35_4b",
        model_id="qwen3.5-4b",
        family="qwen35",
        parameter_class=ParameterClass.SMALL,
        quantization=None,
        backend="lmstudio",
        blocked_routes=(RouteMode.STRICT_JSON_CHAT_COMPLETIONS,),
        recommended_context_lengths=(8192,),
        structured_output_status=StructuredOutputStatus.BLOCKED,
        long_context_status=LongContextStatus.UNVERIFIED,
        privacy_status=PrivacyStatus.PRIVACY_PASSED,
        status=ModelRegistryProfileStatus.BLOCKED_STRUCTURED_OUTPUT,
        evidence_refs=(
            LabEvidenceRef(
                experiment_id="m1_1_structured_small_qwen35_4b",
                summary_ref=_summary_ref("2026-07-04_m1_1_structured_small_screening_summary.md"),
                status=ExperimentStatus.BLOCKED,
                notes=("First-pass structured-small screening failed with empty public content."),
            ),
            LabEvidenceRef(
                experiment_id="mv2_4b_qwen35_4b_structured_small_baseline",
                summary_ref=_summary_ref(
                    "2026-07-05_mv2_4b_qwen35_4b_structured_small_baseline_summary.md"
                ),
                status=ExperimentStatus.BLOCKED,
                notes="Reasoning_content present while public content stayed empty.",
            ),
            LabEvidenceRef(
                experiment_id="mv2_4b_qwen35_4b_anti_reasoning",
                summary_ref=_summary_ref("2026-07-05_mv2_4b_qwen35_4b_anti_reasoning_summary.md"),
                status=ExperimentStatus.BLOCKED,
                notes=("Anti-reasoning prompt variant did not recover strict structured output."),
            ),
        ),
        route_recommendations=(
            RouteRecommendation(
                route=RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
                status=ExperimentStatus.BLOCKED,
                classification=ResultClassification.BLOCKED,
                notes="Strict JSON blocked until public-content routing is recovered.",
            ),
        ),
        notes=(
            "Recovery note only. Strict JSON requires public content; reasoning-only JSON remains a failure "
            "for the current Qwen 4B evidence set."
        ),
    )


def _build_qwen35_9b_profile() -> ModelRegistryProfile:
    return ModelRegistryProfile(
        model_key="qwen35_9b",
        model_id="qwen/qwen3.5-9b",
        family="qwen35",
        parameter_class=ParameterClass.MEDIUM,
        quantization=None,
        backend="lmstudio",
        supported_routes=(RouteMode.STRICT_JSON_CHAT_COMPLETIONS,),
        recommended_context_lengths=(8192,),
        structured_output_status=StructuredOutputStatus.SUPPORTED,
        long_context_status=LongContextStatus.UNVERIFIED,
        privacy_status=PrivacyStatus.PRIVACY_PASSED,
        status=ModelRegistryProfileStatus.RECOVERY_EXPERIMENTAL,
        evidence_refs=(
            LabEvidenceRef(
                experiment_id="m0_6_identity_qwen35_9b",
                summary_ref=_summary_ref("2026-07-04_m0_6_qwen35_9b_identity_summary.md"),
                notes=(
                    "Identity visible in compat/native lists, but quantization and params "
                    "not verified."
                ),
            ),
            LabEvidenceRef(
                experiment_id="m0_7_policy_backed_smoke_qwen35_9b",
                summary_ref=_summary_ref("2026-07-04_m0_7_qwen35_9b_load_echo_summary.md"),
                notes="Policy-backed load echo verified 8192/1 lifecycle behavior.",
            ),
            LabEvidenceRef(
                experiment_id="m1_1_structured_small_qwen35_9b",
                summary_ref=_summary_ref("2026-07-04_m1_1_structured_small_screening_summary.md"),
                notes="Structured-small passed under current lab screening.",
            ),
            LabEvidenceRef(
                experiment_id="m1_2_structured_medium_qwen35_9b",
                summary_ref=_summary_ref("2026-07-04_m1_2_structured_medium_chunked_summary.md"),
                notes="Structured-medium sequential chunked pass exists.",
            ),
        ),
        route_recommendations=(
            RouteRecommendation(
                route=RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
                status=ExperimentStatus.PASSED,
                classification=ResultClassification.PASSED,
                notes=(
                    "Experimental structured-output pass; exact-build promotion remains blocked."
                ),
            ),
        ),
        notes=(
            "Recovery/experimental only. Exact-build quantization evidence is incomplete, "
            "and corrected true-parallel or long-context proof is absent."
        ),
    )


def build_initial_model_registry() -> ModelRegistryCatalog:
    profiles = (
        _build_gemma4_e2b_q4km_profile(),
        _build_qwen35_4b_profile(),
        _build_qwen35_9b_profile(),
    )
    return ModelRegistryCatalog({profile.model_key: profile for profile in profiles})


def get_model_profile(
    registry: ModelRegistryCatalog,
    model_key: str,
) -> ModelRegistryProfile | None:
    return registry.get(model_key)


def responses_small_context_status_for(
    profile_or_none: ModelRegistryProfile | None,
) -> ResponsesRouteStatus:
    if profile_or_none is None:
        return ResponsesRouteStatus.UNVERIFIED_FOR_THIS_MODEL
    return profile_or_none.responses_small_context_status


def responses_long_context_status_for(
    profile_or_none: ModelRegistryProfile | None,
) -> ResponsesRouteStatus:
    if profile_or_none is None:
        return ResponsesRouteStatus.UNVERIFIED_FOR_THIS_MODEL
    return profile_or_none.responses_long_context_status


__all__ = [
    "LongContextStatus",
    "ModelRegistryCatalog",
    "ModelRegistryProfile",
    "ModelRegistryProfileStatus",
    "ParameterClass",
    "PrivacyStatus",
    "ResponsesRouteStatus",
    "build_initial_model_registry",
    "get_model_profile",
    "responses_long_context_status_for",
    "responses_small_context_status_for",
]
