"""Candidate execution-gate records for staged LM Studio lab promotion work."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from .profiles import ParameterClass

L3_8A_GEMMA4_E4B_NO_LIVE_FEASIBILITY_SUMMARY_PATH = (
    "experiments/lmstudio/results_summaries/l3_8a_gemma4_e4b_no_live_feasibility.md"
)
L3_8B_GEMMA4_E4B_LOAD_ONLY_R2_ARTIFACT_DIR = (
    "experiments/lmstudio/results_summaries/"
    "run_l3-8b-gemma4-e4b-load-only-20260707-r2_l3_8b_gemma4_e4b_load_only_16k_32k"
)
L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ARTIFACT_DIR = (
    "experiments/lmstudio/results_summaries/"
    "run_l3-8c-gemma4-e4b-tiny-live-smoke-20260707_l3_8c_gemma4_e4b_tiny_live_smoke"
)
L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ARTIFACT_DIR = (
    "experiments/lmstudio/results_summaries/"
    "run_l3-8d-gemma4-e4b-strict-json-smoke-20260707_l3_8d_gemma4_e4b_strict_json_smoke"
)
L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_PLAN_PATH = (
    "experiments/lmstudio/results_summaries/l3_8d_gemma4_e4b_strict_json_smoke_plan.md"
)


class CandidateExecutionGateStatus(StrEnum):
    NO_LIVE_FEASIBILITY_PASSED = "no_live_feasibility_passed"
    LOAD_ONLY_PENDING = "load_only_pending"
    LOAD_ONLY_PASSED = "load_only_passed"
    LOAD_ONLY_FAILED = "load_only_failed"
    LIVE_SMOKE_PENDING = "live_smoke_pending"
    TINY_LIVE_SMOKE_PASSED = "tiny_live_smoke_passed"
    STRUCTURED_JSON_PENDING = "structured_json_pending"
    STRUCTURED_JSON_PASSED = "structured_json_passed"
    ROUTE_MATRIX_BLOCKED_UNTIL_PREREQUISITES = "route_matrix_blocked_until_prerequisites"


@dataclass(frozen=True, slots=True)
class CandidateExecutionRecord:
    model_key: str
    model_id: str
    family: str
    size_class: ParameterClass
    profile_type: str | None
    no_live_feasibility_status: CandidateExecutionGateStatus
    load_only_16k_32k_status: CandidateExecutionGateStatus
    tiny_live_smoke_status: CandidateExecutionGateStatus
    structured_json_status: CandidateExecutionGateStatus
    route_matrix_status: CandidateExecutionGateStatus
    load_only_context_tiers: tuple[int, ...] = (16_384, 32_768)
    production_default: bool = False
    wvm_runtime_integration: bool = False
    kv_reuse_proven: bool = False
    final_user_facing_recommendation: bool = False
    summary_ref: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.production_default:
            raise ValueError("Candidate execution records cannot imply production_default=true")
        if self.wvm_runtime_integration:
            raise ValueError(
                "Candidate execution records cannot imply wvm_runtime_integration=true"
            )
        if self.kv_reuse_proven:
            raise ValueError("Candidate execution records cannot imply kv_reuse_proven=true")
        if self.final_user_facing_recommendation:
            raise ValueError(
                "Candidate execution records cannot imply final_user_facing_recommendation=true"
            )
        if self.load_only_context_tiers != (16_384, 32_768):
            raise ValueError(
                "Candidate execution records require exact load_only_context_tiers=(16384, 32768)"
            )

    @property
    def route_matrix_blocked(self) -> bool:
        return (
            self.route_matrix_status
            is CandidateExecutionGateStatus.ROUTE_MATRIX_BLOCKED_UNTIL_PREREQUISITES
        )


@dataclass(frozen=True, slots=True)
class CandidateExecutionCatalog:
    records_by_key: Mapping[str, CandidateExecutionRecord]

    def __post_init__(self) -> None:
        normalized = dict(sorted(self.records_by_key.items()))
        for model_key, record in normalized.items():
            if model_key != record.model_key:
                raise ValueError(
                    f"Candidate execution key '{model_key}' does not match record key '{record.model_key}'"
                )
        object.__setattr__(self, "records_by_key", MappingProxyType(normalized))

    @property
    def model_keys(self) -> tuple[str, ...]:
        return tuple(self.records_by_key)

    @property
    def records(self) -> tuple[CandidateExecutionRecord, ...]:
        return tuple(self.records_by_key.values())

    def get(self, model_key: str) -> CandidateExecutionRecord | None:
        return self.records_by_key.get(model_key)

    def require(self, model_key: str) -> CandidateExecutionRecord:
        record = self.get(model_key)
        if record is None:
            raise KeyError(model_key)
        return record


def build_candidate_execution_catalog() -> CandidateExecutionCatalog:
    record = CandidateExecutionRecord(
        model_key="gemma4_e4b_q4km",
        model_id="google/gemma-4-e4b",
        family="gemma4",
        size_class=ParameterClass.MEDIUM,
        profile_type="q4_k_m",
        no_live_feasibility_status=CandidateExecutionGateStatus.NO_LIVE_FEASIBILITY_PASSED,
        load_only_16k_32k_status=CandidateExecutionGateStatus.LOAD_ONLY_PASSED,
        tiny_live_smoke_status=CandidateExecutionGateStatus.TINY_LIVE_SMOKE_PASSED,
        structured_json_status=CandidateExecutionGateStatus.STRUCTURED_JSON_PASSED,
        route_matrix_status=(CandidateExecutionGateStatus.ROUTE_MATRIX_BLOCKED_UNTIL_PREREQUISITES),
        summary_ref=L3_8A_GEMMA4_E4B_NO_LIVE_FEASIBILITY_SUMMARY_PATH,
        notes=(
            "L3.8a no-live feasibility is accepted. L3.8b load-only 16k/32k passed with "
            f"artifact dir '{L3_8B_GEMMA4_E4B_LOAD_ONLY_R2_ARTIFACT_DIR}'. L3.8c tiny live "
            "smoke passed with artifact dir "
            f"'{L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ARTIFACT_DIR}'. L3.8d strict JSON passed "
            "with artifact dir "
            f"'{L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ARTIFACT_DIR}' and accepted result plan "
            f"'{L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_PLAN_PATH}'. Gemma4 E4B is eligible for "
            "L3.9 product-shaped viability gates, but route matrix expansion remains "
            "blocked/deferred until L3.9a Blocks JSON functional viability closes and no "
            "production promotion guardrail is lifted by these passes."
        ),
    )
    return CandidateExecutionCatalog({record.model_key: record})


def render_candidate_execution_report(catalog: CandidateExecutionCatalog) -> str:
    record = catalog.require("gemma4_e4b_q4km")
    lines = [
        "# LM Studio Lab L3.8 Gemma4 E4B Candidate Execution Status",
        "",
        "Status: no-live feasibility, load-only 16k/32k, tiny live smoke, and L3.8d strict JSON are accepted; route matrix expansion remains blocked/deferred while Gemma4 E4B advances only to L3.9 product-shaped viability gates.",
        "",
        "## Candidate",
        "",
        f"- model_key: `{record.model_key}`",
        f"- model_id: `{record.model_id}`",
        f"- family: `{record.family}`",
        f"- size_class: `{record.size_class.value}`",
        f"- profile_type: `{record.profile_type}`",
        f"- load_only_context_tiers: `{', '.join(str(value) for value in record.load_only_context_tiers)}`",
        "",
        "## Execution-gate status",
        "",
        f"- no_live_feasibility: `{record.no_live_feasibility_status.value}`",
        f"- load_only_16k_32k: `{record.load_only_16k_32k_status.value}`",
        f"- tiny_live_smoke: `{record.tiny_live_smoke_status.value}`",
        f"- structured_json: `{record.structured_json_status.value}`",
        f"- route_matrix: `{record.route_matrix_status.value}`",
        "",
        "Route matrix remains blocked/deferred: the next gate is L3.9a Blocks JSON functional viability, not route-matrix expansion.",
        "",
        "## Promotion guardrails",
        "",
        f"- production_default: `{str(record.production_default).lower()}`",
        f"- wvm_runtime_integration: `{str(record.wvm_runtime_integration).lower()}`",
        f"- kv_reuse_proven: `{str(record.kv_reuse_proven).lower()}`",
        f"- final_user_facing_recommendation: `{str(record.final_user_facing_recommendation).lower()}`",
        "",
        "## Notes",
        "",
        "- Older Gemma E4B lab observations are not promoted here as current reusable-core evidence.",
        "- L3.8a is a policy/report slice only and does not perform model load, generation, or localhost endpoint calls.",
        f"- Accepted L3.8b artifact dir: `{L3_8B_GEMMA4_E4B_LOAD_ONLY_R2_ARTIFACT_DIR}`.",
        f"- Accepted L3.8c artifact dir: `{L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ARTIFACT_DIR}`.",
        f"- Accepted L3.8d artifact dir: `{L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ARTIFACT_DIR}`.",
        f"- Accepted L3.8d result plan: `{L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_PLAN_PATH}`.",
        "- Gemma4 E4B is eligible for L3.9 product-shaped viability gates only; this is not production, not host application runtime integration, not route-matrix approval, and not a final user-facing recommendation.",
        "- Next gate: L3.9a Blocks JSON functional viability.",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "CandidateExecutionCatalog",
    "CandidateExecutionGateStatus",
    "CandidateExecutionRecord",
    "L3_8A_GEMMA4_E4B_NO_LIVE_FEASIBILITY_SUMMARY_PATH",
    "L3_8B_GEMMA4_E4B_LOAD_ONLY_R2_ARTIFACT_DIR",
    "L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ARTIFACT_DIR",
    "L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ARTIFACT_DIR",
    "L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_PLAN_PATH",
    "build_candidate_execution_catalog",
    "render_candidate_execution_report",
]
