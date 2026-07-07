"""Internal-only recommendation draft built from reusable LM Studio lab registries."""

# ruff: noqa: I001

from __future__ import annotations

# fmt: off

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ..core_contracts import LabEvidenceRef, RouteMode
from .candidate_intake import (
    CURRENT_RESPONSES_LONG_CONTEXT_EVIDENCE_BUILD,
    CandidateModelIntake,
    build_candidate_model_intake_catalog,
)
from .profiles import ModelRegistryProfile, build_initial_model_registry
from .structured_matrix import build_structured_json_validation_matrix

INTERNAL_RECOMMENDATION_DRAFT_SUMMARY_PATH = (
    "experiments/lmstudio/results_summaries/l3_7e_internal_recommendation_draft.md"
)
OPENAI_RESPONSES_SMALL_CONTEXT_SCOPE = "small_context"
OPENAI_RESPONSES_CURRENT_LONG_CONTEXT_SCOPE = (
    f"long_context::{CURRENT_RESPONSES_LONG_CONTEXT_EVIDENCE_BUILD}"
)
OPENAI_RESPONSES_FUTURE_RETEST_SCOPE = "future_models_or_new_builds"


class RecommendationAudience(StrEnum):
    NOT_USER_FACING = "not_user_facing"


class InternalRecommendationStatus(StrEnum):
    INTERNAL_PRIMARY_CANDIDATE = "internal_primary_candidate"
    INTERNAL_FALLBACK = "internal_fallback"
    RESEARCH_ACCELERATOR = "research_accelerator"
    CACHE_ACCOUNTING_CANDIDATE_SMALL_CONTEXT = "cache_accounting_candidate_small_context"
    BLOCKED_CURRENT_EVIDENCE = "blocked_current_evidence"
    UNVERIFIED_CANDIDATE = "unverified_candidate"
    NEEDS_NO_LIVE_FEASIBILITY = "needs_no_live_feasibility"
    NEEDS_LOAD_ONLY = "needs_load_only"
    NEEDS_LIVE_SMOKE = "needs_live_smoke"
    NEEDS_STRUCTURED_JSON = "needs_structured_json"
    RECOVERY_EXPERIMENTAL_ONLY = "recovery_experimental_only"


_PENDING_GATE_ORDER = {
    InternalRecommendationStatus.NEEDS_NO_LIVE_FEASIBILITY: 0,
    InternalRecommendationStatus.NEEDS_LOAD_ONLY: 1,
    InternalRecommendationStatus.NEEDS_LIVE_SMOKE: 2,
    InternalRecommendationStatus.NEEDS_STRUCTURED_JSON: 3,
}
_ROUTE_ORDER = {
    RouteMode.COMPACT_MEMORY: 0,
    RouteMode.NATIVE_CHAT_STATEFUL: 1,
    RouteMode.STATELESS_FULL_PREFIX: 2,
    RouteMode.OPENAI_RESPONSES: 3,
    RouteMode.STRICT_JSON_CHAT_COMPLETIONS: 4,
}


def _sorted_evidence_refs(evidence_refs: Iterable[LabEvidenceRef]) -> tuple[LabEvidenceRef, ...]:
    return tuple(
        sorted(
            set(evidence_refs),
            key=lambda ref: (ref.summary_ref, ref.experiment_id, ref.status.value),
        )
    )


def _sorted_pending_gates(
    pending_gates: Iterable[InternalRecommendationStatus],
) -> tuple[InternalRecommendationStatus, ...]:
    return tuple(
        sorted(
            set(pending_gates),
            key=lambda status: (_PENDING_GATE_ORDER.get(status, 99), status.value),
        )
    )


def _sorted_routes(routes: Iterable[InternalRouteGuidance]) -> tuple[InternalRouteGuidance, ...]:
    by_route: dict[RouteMode, InternalRouteGuidance] = {}
    for route_guidance in routes:
        if route_guidance.route in by_route:
            raise ValueError(f"Duplicate route guidance for {route_guidance.route.value}")
        by_route[route_guidance.route] = route_guidance
    return tuple(sorted(by_route.values(), key=lambda item: _ROUTE_ORDER[item.route]))


def _sorted_scopes(
    scopes: Iterable[RecommendationScopeGuidance],
) -> tuple[RecommendationScopeGuidance, ...]:
    by_scope: dict[str, RecommendationScopeGuidance] = {}
    for scope_guidance in scopes:
        if scope_guidance.scope_key in by_scope:
            raise ValueError(f"Duplicate scope guidance for {scope_guidance.scope_key}")
        by_scope[scope_guidance.scope_key] = scope_guidance
    return tuple(by_scope[scope_key] for scope_key in sorted(by_scope))


def _summary_ref(filename: str) -> str:
    return f"experiments/lmstudio/results_summaries/{filename}"


@dataclass(frozen=True, slots=True)
class RecommendationScopeGuidance:
    scope_key: str
    status: InternalRecommendationStatus
    rationale_refs: tuple[LabEvidenceRef, ...] = ()
    pending_gates: tuple[InternalRecommendationStatus, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rationale_refs", _sorted_evidence_refs(self.rationale_refs))
        object.__setattr__(self, "pending_gates", _sorted_pending_gates(self.pending_gates))


@dataclass(frozen=True, slots=True)
class InternalRouteGuidance:
    model_key: str
    model_id: str
    route: RouteMode
    status: InternalRecommendationStatus
    rationale_refs: tuple[LabEvidenceRef, ...] = ()
    scoped_guidance: tuple[RecommendationScopeGuidance, ...] = ()
    pending_gates: tuple[InternalRecommendationStatus, ...] = ()
    audience: RecommendationAudience = RecommendationAudience.NOT_USER_FACING
    production_default: bool = False
    wvm_runtime_integration: bool = False
    kv_reuse_proven: bool = False
    final_user_facing_recommendation: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.production_default:
            raise ValueError("Internal route guidance cannot imply production_default=true")
        if self.wvm_runtime_integration:
            raise ValueError("Internal route guidance cannot imply wvm_runtime_integration=true")
        if self.kv_reuse_proven:
            raise ValueError("Internal route guidance cannot imply kv_reuse_proven=true")
        if self.final_user_facing_recommendation:
            raise ValueError(
                "Internal route guidance cannot imply final_user_facing_recommendation=true"
            )
        object.__setattr__(self, "rationale_refs", _sorted_evidence_refs(self.rationale_refs))
        object.__setattr__(self, "scoped_guidance", _sorted_scopes(self.scoped_guidance))
        object.__setattr__(self, "pending_gates", _sorted_pending_gates(self.pending_gates))

    @property
    def is_safe_for_user_facing_recommendation(self) -> bool:
        return (
            self.production_default
            and self.wvm_runtime_integration
            and self.kv_reuse_proven
            and self.final_user_facing_recommendation
            and self.audience is not RecommendationAudience.NOT_USER_FACING
        )


@dataclass(frozen=True, slots=True)
class InternalModelRecommendation:
    model_key: str
    model_id: str
    status: InternalRecommendationStatus
    route_guidance: tuple[InternalRouteGuidance, ...] = ()
    rationale_refs: tuple[LabEvidenceRef, ...] = ()
    audience: RecommendationAudience = RecommendationAudience.NOT_USER_FACING
    production_default: bool = False
    wvm_runtime_integration: bool = False
    kv_reuse_proven: bool = False
    final_user_facing_recommendation: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.production_default:
            raise ValueError("Internal model guidance cannot imply production_default=true")
        if self.wvm_runtime_integration:
            raise ValueError("Internal model guidance cannot imply wvm_runtime_integration=true")
        if self.kv_reuse_proven:
            raise ValueError("Internal model guidance cannot imply kv_reuse_proven=true")
        if self.final_user_facing_recommendation:
            raise ValueError(
                "Internal model guidance cannot imply final_user_facing_recommendation=true"
            )
        object.__setattr__(self, "route_guidance", _sorted_routes(self.route_guidance))
        object.__setattr__(self, "rationale_refs", _sorted_evidence_refs(self.rationale_refs))

    @property
    def routes_by_mode(self) -> Mapping[RouteMode, InternalRouteGuidance]:
        return MappingProxyType({item.route: item for item in self.route_guidance})

    @property
    def is_safe_for_user_facing_recommendation(self) -> bool:
        return (
            self.production_default
            and self.wvm_runtime_integration
            and self.kv_reuse_proven
            and self.final_user_facing_recommendation
            and self.audience is not RecommendationAudience.NOT_USER_FACING
            and all(route.is_safe_for_user_facing_recommendation for route in self.route_guidance)
        )

    def route_for(self, route: RouteMode) -> InternalRouteGuidance | None:
        return self.routes_by_mode.get(route)


@dataclass(frozen=True, slots=True)
class InternalRecommendationDraft:
    models_by_key: Mapping[str, InternalModelRecommendation]
    rationale_refs: tuple[LabEvidenceRef, ...] = ()
    audience: RecommendationAudience = RecommendationAudience.NOT_USER_FACING
    production_default: bool = False
    wvm_runtime_integration: bool = False
    kv_reuse_proven: bool = False
    final_user_facing_recommendation: bool = False

    def __post_init__(self) -> None:
        if self.production_default:
            raise ValueError("Internal recommendation draft cannot imply production_default=true")
        if self.wvm_runtime_integration:
            raise ValueError(
                "Internal recommendation draft cannot imply wvm_runtime_integration=true"
            )
        if self.kv_reuse_proven:
            raise ValueError("Internal recommendation draft cannot imply kv_reuse_proven=true")
        if self.final_user_facing_recommendation:
            raise ValueError(
                "Internal recommendation draft cannot imply final_user_facing_recommendation=true"
            )

        normalized = dict(sorted(self.models_by_key.items()))
        for model_key, recommendation in normalized.items():
            if model_key != recommendation.model_key:
                raise ValueError(
                    f"Draft key '{model_key}' does not match recommendation key '{recommendation.model_key}'"
                )
        object.__setattr__(self, "models_by_key", MappingProxyType(normalized))
        object.__setattr__(self, "rationale_refs", _sorted_evidence_refs(self.rationale_refs))

    @property
    def model_keys(self) -> tuple[str, ...]:
        return tuple(self.models_by_key)

    @property
    def models(self) -> tuple[InternalModelRecommendation, ...]:
        return tuple(self.models_by_key.values())

    def get(self, model_key: str) -> InternalModelRecommendation | None:
        return self.models_by_key.get(model_key)

    def require(self, model_key: str) -> InternalModelRecommendation:
        recommendation = self.get(model_key)
        if recommendation is None:
            raise KeyError(model_key)
        return recommendation

    def recommendation_for_model(self, model_key: str) -> InternalModelRecommendation | None:
        return self.get(model_key)

    def route_guidance_for(
        self,
        model_key: str,
        route: RouteMode,
    ) -> InternalRouteGuidance | None:
        recommendation = self.get(model_key)
        if recommendation is None:
            return None
        return recommendation.route_for(route)

    def is_safe_for_user_facing_recommendation(self) -> bool:
        return (
            self.production_default
            and self.wvm_runtime_integration
            and self.kv_reuse_proven
            and self.final_user_facing_recommendation
            and self.audience is not RecommendationAudience.NOT_USER_FACING
            and all(model.is_safe_for_user_facing_recommendation for model in self.models)
        )


def _gemma_registry_summary_ref() -> LabEvidenceRef:
    return LabEvidenceRef(
        experiment_id="l3_7b_model_registry_profile_map",
        summary_ref=_summary_ref("l3_7b_model_registry_profile_map.md"),
        notes="Registry summary preserved the internal-only route map.",
    )


def _candidate_intake_summary_ref() -> LabEvidenceRef:
    return LabEvidenceRef(
        experiment_id="l3_7c_candidate_model_intake",
        summary_ref=_summary_ref("l3_7c_candidate_model_intake_and_hardware_feasibility.md"),
        notes="Candidate intake summary preserved no-live planning gates.",
    )


def _structured_matrix_summary_ref() -> LabEvidenceRef:
    return LabEvidenceRef(
        experiment_id="l3_7d_structured_json_validation_matrix",
        summary_ref=_summary_ref("l3_7d_structured_json_validation_matrix.md"),
        notes="Structured JSON matrix preserved the controlled Gemma E2B strict JSON pass.",
    )


def _current_pending_candidate_gates() -> tuple[InternalRecommendationStatus, ...]:
    return (
        InternalRecommendationStatus.NEEDS_NO_LIVE_FEASIBILITY,
        InternalRecommendationStatus.NEEDS_LOAD_ONLY,
        InternalRecommendationStatus.NEEDS_LIVE_SMOKE,
        InternalRecommendationStatus.NEEDS_STRUCTURED_JSON,
    )


def _build_gemma_recommendation(profile: ModelRegistryProfile) -> InternalModelRecommendation:
    base_refs = profile.evidence_refs + (_gemma_registry_summary_ref(), _structured_matrix_summary_ref())
    responses_refs = profile.evidence_refs + (_gemma_registry_summary_ref(), _candidate_intake_summary_ref())
    return InternalModelRecommendation(
        model_key=profile.model_key,
        model_id=profile.model_id,
        status=InternalRecommendationStatus.INTERNAL_PRIMARY_CANDIDATE,
        rationale_refs=base_refs,
        route_guidance=(
            InternalRouteGuidance(
                model_key=profile.model_key,
                model_id=profile.model_id,
                route=RouteMode.COMPACT_MEMORY,
                status=InternalRecommendationStatus.INTERNAL_PRIMARY_CANDIDATE,
                rationale_refs=base_refs,
                notes="Primary internal route for compact-memory reuse in the current lab draft.",
            ),
            InternalRouteGuidance(
                model_key=profile.model_key,
                model_id=profile.model_id,
                route=RouteMode.NATIVE_CHAT_STATEFUL,
                status=InternalRecommendationStatus.RESEARCH_ACCELERATOR,
                rationale_refs=base_refs,
                notes="Research accelerator only for one-root-many-branches experiments.",
            ),
            InternalRouteGuidance(
                model_key=profile.model_key,
                model_id=profile.model_id,
                route=RouteMode.STATELESS_FULL_PREFIX,
                status=InternalRecommendationStatus.INTERNAL_FALLBACK,
                rationale_refs=base_refs,
                notes="Baseline fallback route kept for deterministic comparison and recovery.",
            ),
            InternalRouteGuidance(
                model_key=profile.model_key,
                model_id=profile.model_id,
                route=RouteMode.OPENAI_RESPONSES,
                status=InternalRecommendationStatus.CACHE_ACCOUNTING_CANDIDATE_SMALL_CONTEXT,
                rationale_refs=responses_refs,
                scoped_guidance=(
                    RecommendationScopeGuidance(
                        scope_key=OPENAI_RESPONSES_SMALL_CONTEXT_SCOPE,
                        status=InternalRecommendationStatus.CACHE_ACCOUNTING_CANDIDATE_SMALL_CONTEXT,
                        rationale_refs=responses_refs,
                        notes="Small-context responses work remains lab-only cache-accounting research.",
                    ),
                    RecommendationScopeGuidance(
                        scope_key=OPENAI_RESPONSES_CURRENT_LONG_CONTEXT_SCOPE,
                        status=InternalRecommendationStatus.BLOCKED_CURRENT_EVIDENCE,
                        rationale_refs=responses_refs,
                        notes=(
                            "Current Gemma E2B long-context responses evidence stays blocked only "
                            "for the exact current model/build scope."
                        ),
                    ),
                    RecommendationScopeGuidance(
                        scope_key=OPENAI_RESPONSES_FUTURE_RETEST_SCOPE,
                        status=InternalRecommendationStatus.NEEDS_LIVE_SMOKE,
                        rationale_refs=responses_refs,
                        pending_gates=(InternalRecommendationStatus.NEEDS_LIVE_SMOKE,),
                        notes=(
                            "Future models or newer LM Studio builds remain unverified and require "
                            "fresh retest evidence."
                        ),
                    ),
                ),
                notes=(
                    "Scoped only: small-context cache-accounting candidate, current exact-build "
                    "long-context block, future retest still lab-only."
                ),
            ),
            InternalRouteGuidance(
                model_key=profile.model_key,
                model_id=profile.model_id,
                route=RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
                status=InternalRecommendationStatus.INTERNAL_PRIMARY_CANDIDATE,
                rationale_refs=base_refs,
                notes=(
                    "Current internal strict JSON draft candidate after the L3.7d Gemma E2B pass; "
                    "still lab-only and not a user-facing recommendation."
                ),
            ),
        ),
        notes=(
            "Internal primary draft only: no production default, no WVM runtime integration, "
            "no KV reuse proof, and no final user-facing recommendation."
        ),
    )


def _build_qwen4b_recommendation(profile: ModelRegistryProfile) -> InternalModelRecommendation:
    refs = profile.evidence_refs + (_gemma_registry_summary_ref(), _structured_matrix_summary_ref())
    return InternalModelRecommendation(
        model_key=profile.model_key,
        model_id=profile.model_id,
        status=InternalRecommendationStatus.BLOCKED_CURRENT_EVIDENCE,
        rationale_refs=refs,
        route_guidance=(
            InternalRouteGuidance(
                model_key=profile.model_key,
                model_id=profile.model_id,
                route=RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
                status=InternalRecommendationStatus.BLOCKED_CURRENT_EVIDENCE,
                rationale_refs=refs,
                notes=(
                    "Strict JSON remains blocked because public assistant content stayed empty while "
                    "reasoning-only JSON appeared under current evidence."
                ),
            ),
        ),
        notes="Blocked current-evidence recovery note only; not eligible for promotion or user-facing advice.",
    )


def _build_qwen9b_recommendation(profile: ModelRegistryProfile) -> InternalModelRecommendation:
    refs = profile.evidence_refs + (_gemma_registry_summary_ref(), _structured_matrix_summary_ref())
    return InternalModelRecommendation(
        model_key=profile.model_key,
        model_id=profile.model_id,
        status=InternalRecommendationStatus.RECOVERY_EXPERIMENTAL_ONLY,
        rationale_refs=refs,
        route_guidance=(
            InternalRouteGuidance(
                model_key=profile.model_key,
                model_id=profile.model_id,
                route=RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
                status=InternalRecommendationStatus.RECOVERY_EXPERIMENTAL_ONLY,
                rationale_refs=refs,
                notes=(
                    "Recovery/experimental only. Exact-build and long-context gaps keep this route "
                    "out of any promotion path."
                ),
            ),
        ),
        notes="Recovery/experimental only; keep separated from internal-primary and user-facing guidance.",
    )


def _build_candidate_recommendation(candidate: CandidateModelIntake) -> InternalModelRecommendation:
    pending_gates = _current_pending_candidate_gates()
    refs = (_candidate_intake_summary_ref(),)
    return InternalModelRecommendation(
        model_key=candidate.model_key,
        model_id=candidate.model_id,
        status=InternalRecommendationStatus.UNVERIFIED_CANDIDATE,
        rationale_refs=refs,
        route_guidance=(
            InternalRouteGuidance(
                model_key=candidate.model_key,
                model_id=candidate.model_id,
                route=RouteMode.COMPACT_MEMORY,
                status=InternalRecommendationStatus.NEEDS_LOAD_ONLY,
                rationale_refs=refs,
                pending_gates=pending_gates,
                notes="Unverified candidate route; staged gates must pass before any compact-memory recommendation.",
            ),
            InternalRouteGuidance(
                model_key=candidate.model_key,
                model_id=candidate.model_id,
                route=RouteMode.NATIVE_CHAT_STATEFUL,
                status=InternalRecommendationStatus.NEEDS_LOAD_ONLY,
                rationale_refs=refs,
                pending_gates=pending_gates,
                notes="Unverified candidate route; stateful research routing stays blocked pending staged gates.",
            ),
            InternalRouteGuidance(
                model_key=candidate.model_key,
                model_id=candidate.model_id,
                route=RouteMode.STATELESS_FULL_PREFIX,
                status=InternalRecommendationStatus.NEEDS_LOAD_ONLY,
                rationale_refs=refs,
                pending_gates=pending_gates,
                notes="Unverified candidate route; baseline/fallback comparison waits on staged gates.",
            ),
            InternalRouteGuidance(
                model_key=candidate.model_key,
                model_id=candidate.model_id,
                route=RouteMode.OPENAI_RESPONSES,
                status=InternalRecommendationStatus.NEEDS_LIVE_SMOKE,
                rationale_refs=refs,
                pending_gates=pending_gates,
                notes=(
                    "Responses route remains unverified for this candidate and requires staged no-live, "
                    "load-only, live-smoke, and structured-json closure before recommendation."
                ),
            ),
            InternalRouteGuidance(
                model_key=candidate.model_key,
                model_id=candidate.model_id,
                route=RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
                status=InternalRecommendationStatus.NEEDS_STRUCTURED_JSON,
                rationale_refs=refs,
                pending_gates=pending_gates,
                notes="Strict JSON route stays pending until the staged candidate matrix completes.",
            ),
        ),
        notes=(
            "Unverified candidate only; requires no-live, load-only, live-smoke, and structured-json "
            "gates before any route recommendation."
        ),
    )


def build_internal_recommendation_draft() -> InternalRecommendationDraft:
    registry = build_initial_model_registry()
    matrix = build_structured_json_validation_matrix()
    candidates = build_candidate_model_intake_catalog()

    gemma = _build_gemma_recommendation(registry.require("gemma4_e2b_q4km"))
    qwen4b = _build_qwen4b_recommendation(registry.require("qwen35_4b"))
    qwen9b = _build_qwen9b_recommendation(registry.require("qwen35_9b"))
    candidate_models = tuple(_build_candidate_recommendation(candidate) for candidate in candidates.candidates)

    rationale_refs = (
        gemma.rationale_refs
        + qwen4b.rationale_refs
        + qwen9b.rationale_refs
        + tuple(ref for candidate in candidate_models for ref in candidate.rationale_refs)
        + (_structured_matrix_summary_ref(),)
    )

    draft = InternalRecommendationDraft(
        models_by_key={
            recommendation.model_key: recommendation
            for recommendation in (gemma, qwen4b, qwen9b, *candidate_models)
        },
        rationale_refs=rationale_refs,
    )

    strict_json_guidance = draft.route_guidance_for(
        "gemma4_e2b_q4km",
        RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
    )
    if strict_json_guidance is None:
        raise ValueError("Gemma E2B strict JSON guidance missing from internal draft")

    gemma_matrix_row = matrix.require("gemma4_e2b_q4km")
    if not gemma_matrix_row.current_primary_live_smoke_candidate:
        raise ValueError("Gemma E2B strict JSON draft must align with the L3.7d primary live row")

    return draft


def recommendation_for_model(
    model_key: str,
    draft: InternalRecommendationDraft | None = None,
) -> InternalModelRecommendation | None:
    active_draft = build_internal_recommendation_draft() if draft is None else draft
    return active_draft.recommendation_for_model(model_key)


def route_guidance_for(
    model_key: str,
    route: RouteMode,
    draft: InternalRecommendationDraft | None = None,
) -> InternalRouteGuidance | None:
    active_draft = build_internal_recommendation_draft() if draft is None else draft
    return active_draft.route_guidance_for(model_key, route)


def is_safe_for_user_facing_recommendation(
    draft: InternalRecommendationDraft | None = None,
) -> bool:
    active_draft = build_internal_recommendation_draft() if draft is None else draft
    return active_draft.is_safe_for_user_facing_recommendation()


def render_internal_recommendation_draft_report(
    draft: InternalRecommendationDraft,
) -> str:
    report_order = (
        "gemma4_e2b_q4km",
        "qwen35_4b",
        "qwen35_9b",
        "gemma4_e4b_q4km",
        "gemma4_12b_qat",
        "gemma4_26b_a4b_qat",
        "qwen3_6_35b_a3b",
    )
    lines = [
        "# LM Studio Lab L3.7e Internal Recommendation Draft",
        "",
        "Status: internal-only lab draft built from L3.7b registry, L3.7c candidate intake, and L3.7d structured JSON evidence with no new live work.",
        "",
        "## Guardrails",
        "",
        "- Internal only.",
        "- No production/default/runtime/UI implication.",
        "- No final user-facing recommendation.",
        "- `production_default=false`.",
        "- `wvm_runtime_integration=false`.",
        "- `kv_reuse_proven=false`.",
        "- Audience stays `not_user_facing`.",
        "",
        "## Evidence used from L3.6 and L3.7",
        "",
        "- `experiments/lmstudio/results_summaries/run_l3-6c-compact-memory-live-smoke-20260706-r2_l3_6c_25k_compact_memory_live_smoke_gemma4_e2b/report.md`",
        "- `experiments/lmstudio/results_summaries/run_l3-6d-mode-comparison-20260706_l3_6d_25k_mode_comparison_gemma4_e2b/report.md`",
        "- `experiments/lmstudio/results_summaries/l3_6e_decision_record.md`",
        "- `experiments/lmstudio/results_summaries/l3_7b_model_registry_profile_map.md`",
        "- `experiments/lmstudio/results_summaries/l3_7c_candidate_model_intake_and_hardware_feasibility.md`",
        "- `experiments/lmstudio/results_summaries/l3_7d_structured_json_validation_matrix.md`",
        "",
        "## Draft model status",
        "",
        "| Model key | Model id | Overall status | Notes |",
        "| --- | --- | --- | --- |",
    ]
    for model_key in report_order:
        recommendation = draft.require(model_key)
        lines.append(
            "| "
            f"`{recommendation.model_key}` | `{recommendation.model_id}` | "
            f"`{recommendation.status.value}` | {recommendation.notes or ''} |"
        )

    lines.extend(
        (
            "",
            "## Route guidance",
            "",
            "| Model key | Route | Draft status | Pending gates | Notes |",
            "| --- | --- | --- | --- | --- |",
        )
    )
    for model_key in report_order:
        recommendation = draft.require(model_key)
        for route_guidance in recommendation.route_guidance:
            pending = ", ".join(status.value for status in route_guidance.pending_gates) or "-"
            lines.append(
                "| "
                f"`{recommendation.model_key}` | `{route_guidance.route.value}` | "
                f"`{route_guidance.status.value}` | `{pending}` | {route_guidance.notes or ''} |"
            )

    gemma_responses = draft.route_guidance_for("gemma4_e2b_q4km", RouteMode.OPENAI_RESPONSES)
    if gemma_responses is None:
        raise ValueError("Gemma E2B openai_responses guidance missing from draft")

    lines.extend(
        (
            "",
            "## Scoped `openai_responses` policy",
            "",
            "This route is not globally blocked:",
        )
    )
    for scope_guidance in gemma_responses.scoped_guidance:
        pending = ", ".join(status.value for status in scope_guidance.pending_gates)
        if pending:
            pending_suffix = f"; pending gates: `{pending}`"
        else:
            pending_suffix = ""
        lines.append(
            f"- `{scope_guidance.scope_key}` -> `{scope_guidance.status.value}`{pending_suffix}."
        )

    lines.extend(
        (
            "",
            "## Current internal draft conclusions",
            "",
            "- `gemma4_e2b_q4km` is the internal primary candidate for `compact_memory` and `strict_json_chat_completions`, but it remains lab-only.",
            "- `native_chat_stateful` remains a research accelerator only.",
            "- `stateless_full_prefix` remains the internal fallback/baseline.",
            "- `qwen35_4b` remains blocked for strict JSON under current evidence.",
            "- `qwen35_9b` remains recovery/experimental only.",
            "- L3.7c future candidates remain unverified and need staged no-live/load-only/live-smoke/structured-json gates before any route recommendation.",
            "",
            "## Next L3.7f decision record",
            "",
            "L3.7f should record whether this internal draft stays lab-only, what exact evidence is still missing for any promotion discussion, and why no user-facing recommendation is emitted yet.",
        )
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "INTERNAL_RECOMMENDATION_DRAFT_SUMMARY_PATH",
    "OPENAI_RESPONSES_CURRENT_LONG_CONTEXT_SCOPE",
    "OPENAI_RESPONSES_FUTURE_RETEST_SCOPE",
    "OPENAI_RESPONSES_SMALL_CONTEXT_SCOPE",
    "InternalModelRecommendation",
    "InternalRecommendationDraft",
    "InternalRecommendationStatus",
    "InternalRouteGuidance",
    "RecommendationAudience",
    "RecommendationScopeGuidance",
    "build_internal_recommendation_draft",
    "is_safe_for_user_facing_recommendation",
    "recommendation_for_model",
    "render_internal_recommendation_draft_report",
    "route_guidance_for",
]

# fmt: on
