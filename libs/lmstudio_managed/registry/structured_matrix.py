"""Structured JSON validation matrix for LM Studio lab candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ..core_contracts import RouteMode

GEMMA_E2B_LIVE_ARTIFACT_DIR = (
    "experiments/lmstudio/results_summaries/"
    "run_l3-7d-structured-json-live-smoke-20260707_l3_7d_structured_json_live_smoke_gemma4_e2b/"
)


class StructuredJsonGateStatus(StrEnum):
    NOT_STARTED = "not_started"
    NO_LIVE_VALIDATED = "no_live_validated"
    LIVE_SMOKE_PENDING = "live_smoke_pending"
    PASSED = "passed"
    FAILED_PUBLIC_CONTENT_EMPTY = "failed_public_content_empty"
    FAILED_REASONING_ONLY_JSON = "failed_reasoning_only_json"
    BLOCKED_CURRENT_EVIDENCE = "blocked_current_evidence"
    UNVERIFIED_CANDIDATE = "unverified_candidate"


@dataclass(frozen=True, slots=True)
class StructuredJsonMatrixRow:
    model_key: str
    model_id: str
    status: StructuredJsonGateStatus
    expected_route: RouteMode = RouteMode.STRICT_JSON_CHAT_COMPLETIONS
    strict_json_requires_public_content: bool = True
    reasoning_only_json_is_failure: bool = True
    live_allowed_in_l3_7d: bool = False
    current_primary_live_smoke_candidate: bool = False
    recovery_experimental_only: bool = False
    blocked_by_current_evidence: bool = False
    observed_failure_status: StructuredJsonGateStatus | None = None
    production_default: bool = False
    wvm_runtime_integration: bool = False
    kv_reuse_proven: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.expected_route is not RouteMode.STRICT_JSON_CHAT_COMPLETIONS:
            raise ValueError("Structured JSON matrix rows must use strict_json_chat_completions")
        if self.production_default:
            raise ValueError("Structured JSON matrix rows cannot imply production_default=true")
        if self.wvm_runtime_integration:
            raise ValueError(
                "Structured JSON matrix rows cannot imply wvm_runtime_integration=true"
            )
        if self.kv_reuse_proven:
            raise ValueError("Structured JSON matrix rows cannot imply kv_reuse_proven=true")
        if self.current_primary_live_smoke_candidate and not self.live_allowed_in_l3_7d:
            raise ValueError("Primary live-smoke candidate must be explicitly allowed in L3.7d")


@dataclass(frozen=True, slots=True)
class StructuredJsonValidationMatrix:
    rows_by_key: Mapping[str, StructuredJsonMatrixRow]

    def __post_init__(self) -> None:
        normalized = dict(sorted(self.rows_by_key.items()))
        for model_key, row in normalized.items():
            if model_key != row.model_key:
                raise ValueError(
                    f"Structured JSON matrix key '{model_key}' does not match row key '{row.model_key}'"
                )
        object.__setattr__(self, "rows_by_key", MappingProxyType(normalized))

    @property
    def model_keys(self) -> tuple[str, ...]:
        return tuple(self.rows_by_key)

    @property
    def rows(self) -> tuple[StructuredJsonMatrixRow, ...]:
        return tuple(self.rows_by_key.values())

    def get(self, model_key: str) -> StructuredJsonMatrixRow | None:
        return self.rows_by_key.get(model_key)

    def require(self, model_key: str) -> StructuredJsonMatrixRow:
        row = self.get(model_key)
        if row is None:
            raise KeyError(model_key)
        return row


def build_structured_json_validation_matrix() -> StructuredJsonValidationMatrix:
    rows = (
        StructuredJsonMatrixRow(
            model_key="gemma4_e2b_q4km",
            model_id="google/gemma-4-e2b",
            status=StructuredJsonGateStatus.PASSED,
            live_allowed_in_l3_7d=True,
            current_primary_live_smoke_candidate=True,
            notes=(
                "Controlled L3.7d strict JSON chat-completions live smoke passed in artifact "
                f"`{GEMMA_E2B_LIVE_ARTIFACT_DIR}`; keep lab-only with no production promotion."
            ),
        ),
        StructuredJsonMatrixRow(
            model_key="gemma4_e4b_q4km",
            model_id="google/gemma-4-e4b",
            status=StructuredJsonGateStatus.NOT_STARTED,
            notes=(
                "Pending no-live and load-only replay first; excluded from L3.7d live work unless a "
                "separate slice explicitly authorizes it."
            ),
        ),
        StructuredJsonMatrixRow(
            model_key="gemma4_12b_qat",
            model_id="google/gemma-4-12b-qat",
            status=StructuredJsonGateStatus.UNVERIFIED_CANDIDATE,
            notes="Future intake candidate only; no structured JSON live work in L3.7d.",
        ),
        StructuredJsonMatrixRow(
            model_key="gemma4_26b_a4b_qat",
            model_id="google/gemma-4-26b-a4b-qat",
            status=StructuredJsonGateStatus.UNVERIFIED_CANDIDATE,
            notes="Future intake candidate only; no structured JSON live work in L3.7d.",
        ),
        StructuredJsonMatrixRow(
            model_key="qwen35_4b",
            model_id="qwen3.5-4b",
            status=StructuredJsonGateStatus.BLOCKED_CURRENT_EVIDENCE,
            blocked_by_current_evidence=True,
            observed_failure_status=StructuredJsonGateStatus.FAILED_REASONING_ONLY_JSON,
            notes=(
                "Blocked under current evidence: public assistant content stayed empty while JSON was "
                "observed only in reasoning fields."
            ),
        ),
        StructuredJsonMatrixRow(
            model_key="qwen35_9b",
            model_id="qwen/qwen3.5-9b",
            status=StructuredJsonGateStatus.PASSED,
            recovery_experimental_only=True,
            notes=(
                "Recovery/experimental only. Keep blocked from promotion until exact-build evidence closes "
                "the remaining gaps."
            ),
        ),
        StructuredJsonMatrixRow(
            model_key="qwen3_6_35b_a3b",
            model_id="qwen/qwen3.6-35b-a3b",
            status=StructuredJsonGateStatus.UNVERIFIED_CANDIDATE,
            notes="Future intake candidate only; no structured JSON live work in L3.7d.",
        ),
    )
    return StructuredJsonValidationMatrix({row.model_key: row for row in rows})


def get_structured_json_matrix_row(
    matrix: StructuredJsonValidationMatrix,
    model_key: str,
) -> StructuredJsonMatrixRow | None:
    return matrix.get(model_key)


def render_structured_json_validation_matrix_report(
    matrix: StructuredJsonValidationMatrix,
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
        "# LM Studio Lab L3.7d Structured JSON Validation Matrix",
        "",
        "Status: live-updated matrix with one successful controlled managed Gemma E2B live-smoke artifact.",
        "",
        "## Route policy",
        "",
        "- Strict JSON pass requires non-empty public assistant `content`.",
        "- JSON visible only in `reasoning_content` is a failure, not a pass.",
        "- Qwen 4B remains blocked for strict structured output under current evidence.",
        "- Qwen 9B remains recovery/experimental only unless exact-build evidence proves otherwise.",
        "- Gemma E2B now has a passing controlled live smoke, but it remains lab-only and is not a production promotion.",
        "",
        "## Successful live artifact",
        "",
        f"- Artifact directory: `{GEMMA_E2B_LIVE_ARTIFACT_DIR}`",
        "- Acceptance evidence: `applied_context_length=8192`, `applied_parallel=1`, `request_succeeded=true`, `public_content_pass=true`, `reasoning_content_present=false`.",
        "- Structured output gate: `json_parse_pass=true`, `schema_pass=true`, `business_pass=true`, `structured_gate_status=passed`.",
        "- Cleanup/privacy evidence: `cleanup_verified=true`, `final_loaded_instances=0`, `privacy_scan.status=pass`, `privacy_scan.violation_count=0`.",
        "- Guardrails stay false: `production_default=false`, `wvm_runtime_integration=false`, `kv_reuse_proven=false`.",
        "",
        "## Matrix",
        "",
        "| Model key | Model id | Status | Live in L3.7d | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for model_key in report_order:
        row = matrix.require(model_key)
        lines.append(
            "| "
            f"`{row.model_key}` | `{row.model_id}` | `{row.status.value}` | "
            f"`{str(row.live_allowed_in_l3_7d).lower()}` | {row.notes or ''} |"
        )
    lines.extend(
        (
            "",
            "## L3.7d live gate scope",
            "",
            "- Allowed managed live gate: `gemma4_e2b_q4km` only.",
            "- Route classification: `strict_json_chat_completions`.",
            "- Helper mode may stay `json_schema_single`, but artifacts and acceptance classify the run as strict JSON chat completions.",
            "- Owned native load/unload, cleanup verification, privacy-safe artifacts, and `production_default=false` remain mandatory.",
        )
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "StructuredJsonGateStatus",
    "StructuredJsonMatrixRow",
    "StructuredJsonValidationMatrix",
    "build_structured_json_validation_matrix",
    "get_structured_json_matrix_row",
    "render_structured_json_validation_matrix_report",
]
