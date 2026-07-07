"""No-live candidate intake planning for future LM Studio text models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from ..core_contracts import RouteMode
from .profiles import ParameterClass

CURRENT_RESPONSES_LONG_CONTEXT_EVIDENCE_BUILD = "l3_7b_current_gemma_e2b_evidence_build"


class CandidateModelStatus(StrEnum):
    UNVERIFIED_CANDIDATE = "unverified_candidate"
    UNVERIFIED_FOR_THIS_MODEL = "unverified_for_this_model"
    NO_LIVE_FEASIBILITY_PENDING = "no_live_feasibility_pending"
    LOAD_ONLY_PENDING = "load_only_pending"
    LIVE_SMOKE_PENDING = "live_smoke_pending"
    STRUCTURED_JSON_PENDING = "structured_json_pending"
    ROUTE_MATRIX_PENDING = "route_matrix_pending"
    NOT_APPROVED_CURRENT_EVIDENCE = "not_approved_current_evidence"
    BLOCKED_BY_CURRENT_EVIDENCE = "blocked_by_current_evidence"
    NEEDS_RETEST_ON_NEW_MODEL_OR_BUILD = "needs_retest_on_new_model_or_build"
    VISION_DEFERRED = "vision_deferred"


@dataclass(frozen=True, slots=True)
class CandidateRouteStatuses:
    compact_memory: CandidateModelStatus
    native_chat_stateful: CandidateModelStatus
    stateless_full_prefix: CandidateModelStatus
    openai_responses: CandidateModelStatus
    strict_json_chat_completions: CandidateModelStatus

    def for_route(self, route: RouteMode) -> CandidateModelStatus:
        if route is RouteMode.COMPACT_MEMORY:
            return self.compact_memory
        if route is RouteMode.NATIVE_CHAT_STATEFUL:
            return self.native_chat_stateful
        if route is RouteMode.STATELESS_FULL_PREFIX:
            return self.stateless_full_prefix
        if route is RouteMode.OPENAI_RESPONSES:
            return self.openai_responses
        if route is RouteMode.STRICT_JSON_CHAT_COMPLETIONS:
            return self.strict_json_chat_completions
        raise KeyError(route)


@dataclass(frozen=True, slots=True)
class CandidateContextTierPlan:
    context_tokens: int
    required: bool
    status: CandidateModelStatus
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateContextTestPlan:
    load_only_16k: CandidateContextTierPlan
    load_only_32k: CandidateContextTierPlan
    optional_48k: CandidateContextTierPlan
    optional_64k: CandidateContextTierPlan

    @property
    def tiers(self) -> tuple[CandidateContextTierPlan, ...]:
        return (
            self.load_only_16k,
            self.load_only_32k,
            self.optional_48k,
            self.optional_64k,
        )


@dataclass(frozen=True, slots=True)
class CandidateTestMatrixPlan:
    no_live_feasibility: CandidateModelStatus = CandidateModelStatus.NO_LIVE_FEASIBILITY_PENDING
    load_only_16k_32k: CandidateModelStatus = CandidateModelStatus.LOAD_ONLY_PENDING
    tiny_live_smoke: CandidateModelStatus = CandidateModelStatus.LIVE_SMOKE_PENDING
    structured_json_smoke: CandidateModelStatus = CandidateModelStatus.STRUCTURED_JSON_PENDING
    long_context_route_matrix: CandidateModelStatus = CandidateModelStatus.ROUTE_MATRIX_PENDING


@dataclass(frozen=True, slots=True)
class CandidateHardwareFeasibility:
    os: str
    cpu: str
    ram: str
    gpu: str
    vram: str
    cuda_notes: str | None = None
    mlx_notes: str | None = None
    backend_notes: tuple[str, ...] = ()
    allowed_context_tiers: tuple[int, ...] = ()
    load_only_required_before_live: bool = True


@dataclass(frozen=True, slots=True)
class EvidenceScopedRouteGate:
    route: RouteMode
    model_key: str
    build_scope: str
    current_status: CandidateModelStatus = CandidateModelStatus.BLOCKED_BY_CURRENT_EVIDENCE
    retest_status: CandidateModelStatus = CandidateModelStatus.NEEDS_RETEST_ON_NEW_MODEL_OR_BUILD


@dataclass(frozen=True, slots=True)
class CandidateEvidencePolicy:
    openai_responses_long_context_gates: tuple[EvidenceScopedRouteGate, ...] = ()

    def openai_responses_long_context_status(
        self,
        *,
        model_key: str,
        build_scope: str | None,
    ) -> CandidateModelStatus:
        normalized_model_key = (model_key or "").strip()
        normalized_build_scope = (build_scope or "").strip()
        for gate in self.openai_responses_long_context_gates:
            if (
                gate.model_key == normalized_model_key
                and gate.build_scope == normalized_build_scope
            ):
                return gate.current_status
        return CandidateModelStatus.UNVERIFIED_FOR_THIS_MODEL

    def openai_responses_long_context_retest_status(
        self, *, model_key: str
    ) -> CandidateModelStatus:
        normalized_model_key = (model_key or "").strip()
        for gate in self.openai_responses_long_context_gates:
            if gate.model_key == normalized_model_key:
                return gate.retest_status
        return CandidateModelStatus.NEEDS_RETEST_ON_NEW_MODEL_OR_BUILD

    def has_exact_block(self, *, model_key: str, build_scope: str | None) -> bool:
        return (
            self.openai_responses_long_context_status(
                model_key=model_key,
                build_scope=build_scope,
            )
            == CandidateModelStatus.BLOCKED_BY_CURRENT_EVIDENCE
        )


@dataclass(frozen=True, slots=True)
class DeferredModelNotice:
    model_key: str
    model_id: str
    status: CandidateModelStatus
    reason: str


@dataclass(frozen=True, slots=True)
class CandidateModelIntake:
    model_key: str
    model_id: str
    family: str
    size_class: ParameterClass
    profile_type: str | None
    expected_backend: str
    route_statuses: CandidateRouteStatuses
    context_test_plan: CandidateContextTestPlan
    test_matrix_plan: CandidateTestMatrixPlan
    current_status: CandidateModelStatus = CandidateModelStatus.UNVERIFIED_CANDIDATE
    production_default: bool = False
    final_user_facing_recommendation: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.production_default:
            raise ValueError("Candidate intake profiles cannot imply production_default=true")
        if self.final_user_facing_recommendation:
            raise ValueError(
                "Candidate intake profiles cannot be final user-facing recommendations"
            )

    @property
    def is_recommendable(self) -> bool:
        return (
            self.current_status
            not in {
                CandidateModelStatus.UNVERIFIED_CANDIDATE,
                CandidateModelStatus.UNVERIFIED_FOR_THIS_MODEL,
                CandidateModelStatus.NOT_APPROVED_CURRENT_EVIDENCE,
                CandidateModelStatus.BLOCKED_BY_CURRENT_EVIDENCE,
                CandidateModelStatus.NEEDS_RETEST_ON_NEW_MODEL_OR_BUILD,
                CandidateModelStatus.VISION_DEFERRED,
            }
            and self.production_default
            and self.final_user_facing_recommendation
        )


@dataclass(frozen=True, slots=True)
class CandidateModelIntakeCatalog:
    candidates_by_key: Mapping[str, CandidateModelIntake]
    hardware_feasibility: CandidateHardwareFeasibility
    evidence_policy: CandidateEvidencePolicy = field(default_factory=CandidateEvidencePolicy)
    deferred_models: tuple[DeferredModelNotice, ...] = ()

    def __post_init__(self) -> None:
        normalized = dict(sorted(self.candidates_by_key.items()))
        for model_key, intake in normalized.items():
            if model_key != intake.model_key:
                raise ValueError(
                    f"Candidate key '{model_key}' does not match intake key '{intake.model_key}'"
                )
        object.__setattr__(self, "candidates_by_key", MappingProxyType(normalized))

    @property
    def model_keys(self) -> tuple[str, ...]:
        return tuple(self.candidates_by_key)

    @property
    def candidates(self) -> tuple[CandidateModelIntake, ...]:
        return tuple(self.candidates_by_key.values())

    def get(self, model_key: str) -> CandidateModelIntake | None:
        return self.candidates_by_key.get(model_key)

    def require(self, model_key: str) -> CandidateModelIntake:
        intake = self.get(model_key)
        if intake is None:
            raise KeyError(model_key)
        return intake


def _default_route_statuses() -> CandidateRouteStatuses:
    return CandidateRouteStatuses(
        compact_memory=CandidateModelStatus.NO_LIVE_FEASIBILITY_PENDING,
        native_chat_stateful=CandidateModelStatus.NO_LIVE_FEASIBILITY_PENDING,
        stateless_full_prefix=CandidateModelStatus.NO_LIVE_FEASIBILITY_PENDING,
        openai_responses=CandidateModelStatus.UNVERIFIED_FOR_THIS_MODEL,
        strict_json_chat_completions=CandidateModelStatus.STRUCTURED_JSON_PENDING,
    )


def _default_context_test_plan() -> CandidateContextTestPlan:
    return CandidateContextTestPlan(
        load_only_16k=CandidateContextTierPlan(
            context_tokens=16_384,
            required=True,
            status=CandidateModelStatus.LOAD_ONLY_PENDING,
            notes="Required load-only gate before any live smoke.",
        ),
        load_only_32k=CandidateContextTierPlan(
            context_tokens=32_768,
            required=True,
            status=CandidateModelStatus.LOAD_ONLY_PENDING,
            notes="Required load-only gate before route comparison work.",
        ),
        optional_48k=CandidateContextTierPlan(
            context_tokens=49_152,
            required=False,
            status=CandidateModelStatus.LOAD_ONLY_PENDING,
            notes="Optional only after 16k and 32k stay stable.",
        ),
        optional_64k=CandidateContextTierPlan(
            context_tokens=65_536,
            required=False,
            status=CandidateModelStatus.LOAD_ONLY_PENDING,
            notes="Optional stretch tier after smaller contexts succeed.",
        ),
    )


def build_candidate_hardware_feasibility() -> CandidateHardwareFeasibility:
    return CandidateHardwareFeasibility(
        os="windows",
        cpu="not_probed_in_l3_7c",
        ram="not_probed_in_l3_7c",
        gpu="cuda_lab_gpu_present_not_reprofiled_in_l3_7c",
        vram="not_probed_in_l3_7c_use_existing_privacy_safe_summaries",
        cuda_notes=(
            "Current lab planning assumes a CUDA-backed LM Studio host, but this slice does not "
            "perform new hardware probing or live generation."
        ),
        mlx_notes="MLX feasibility is deferred in this text-core intake slice.",
        backend_notes=(
            "expected backend is lmstudio local managed text routing",
            "load-only 16k and 32k must pass before any live smoke",
            "48k and 64k remain optional follow-up tiers",
        ),
        allowed_context_tiers=(16_384, 32_768, 49_152, 65_536),
        load_only_required_before_live=True,
    )


def _build_candidate(
    *,
    model_key: str,
    model_id: str,
    family: str,
    size_class: ParameterClass,
    profile_type: str | None,
    expected_backend: str = "lmstudio",
    notes: str,
) -> CandidateModelIntake:
    return CandidateModelIntake(
        model_key=model_key,
        model_id=model_id,
        family=family,
        size_class=size_class,
        profile_type=profile_type,
        expected_backend=expected_backend,
        route_statuses=_default_route_statuses(),
        context_test_plan=_default_context_test_plan(),
        test_matrix_plan=CandidateTestMatrixPlan(),
        current_status=CandidateModelStatus.UNVERIFIED_CANDIDATE,
        notes=notes,
    )


def _build_candidate_evidence_policy() -> CandidateEvidencePolicy:
    return CandidateEvidencePolicy(
        openai_responses_long_context_gates=(
            EvidenceScopedRouteGate(
                route=RouteMode.OPENAI_RESPONSES,
                model_key="gemma4_e2b_q4km",
                build_scope=CURRENT_RESPONSES_LONG_CONTEXT_EVIDENCE_BUILD,
            ),
        )
    )


def build_candidate_model_intake_catalog() -> CandidateModelIntakeCatalog:
    candidates = (
        _build_candidate(
            model_key="gemma4_e4b_q4km",
            model_id="google/gemma-4-e4b",
            family="gemma4",
            size_class=ParameterClass.MEDIUM,
            profile_type="q4_k_m",
            notes="Heavier Gemma text candidate kept unverified until the no-live and load-only gates are replayed under the L3.7c matrix.",
        ),
        _build_candidate(
            model_key="gemma4_12b_qat",
            model_id="google/gemma-4-12b-qat",
            family="gemma4",
            size_class=ParameterClass.LARGE,
            profile_type="qat",
            notes="12B Gemma candidate enters the intake registry only; no live feasibility or promotion evidence is claimed here.",
        ),
        _build_candidate(
            model_key="gemma4_26b_a4b_qat",
            model_id="google/gemma-4-26b-a4b-qat",
            family="gemma4",
            size_class=ParameterClass.LARGE,
            profile_type="a4b_qat",
            notes="26B Gemma candidate is a heavier follow-up and remains unverified pending hardware feasibility and load-only gates.",
        ),
        _build_candidate(
            model_key="qwen3_6_35b_a3b",
            model_id="qwen/qwen3.6-35b-a3b",
            family="qwen36",
            size_class=ParameterClass.LARGE,
            profile_type="a3b",
            notes="Qwen 35B candidate stays intake-only and unverified; it is not approved for any route until the same staged matrix is executed.",
        ),
    )
    return CandidateModelIntakeCatalog(
        candidates_by_key={candidate.model_key: candidate for candidate in candidates},
        hardware_feasibility=build_candidate_hardware_feasibility(),
        evidence_policy=_build_candidate_evidence_policy(),
        deferred_models=(
            DeferredModelNotice(
                model_key="qwen3_vl_4b",
                model_id="qwen/qwen3-vl-4b",
                status=CandidateModelStatus.VISION_DEFERRED,
                reason="Vision-capable model is deferred and is not part of the text-core candidate intake path.",
            ),
        ),
    )


def get_candidate_model_intake(
    catalog: CandidateModelIntakeCatalog,
    model_key: str,
) -> CandidateModelIntake | None:
    return catalog.get(model_key)


def resolve_openai_responses_long_context_status(
    *,
    evidence_policy: CandidateEvidencePolicy,
    model_key: str,
    build_scope: str | None,
) -> CandidateModelStatus:
    return evidence_policy.openai_responses_long_context_status(
        model_key=model_key,
        build_scope=build_scope,
    )


__all__ = [
    "CURRENT_RESPONSES_LONG_CONTEXT_EVIDENCE_BUILD",
    "CandidateContextTestPlan",
    "CandidateContextTierPlan",
    "CandidateEvidencePolicy",
    "CandidateHardwareFeasibility",
    "CandidateModelIntake",
    "CandidateModelIntakeCatalog",
    "CandidateModelStatus",
    "CandidateRouteStatuses",
    "CandidateTestMatrixPlan",
    "DeferredModelNotice",
    "EvidenceScopedRouteGate",
    "build_candidate_hardware_feasibility",
    "build_candidate_model_intake_catalog",
    "get_candidate_model_intake",
    "resolve_openai_responses_long_context_status",
]
