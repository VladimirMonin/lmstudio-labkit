from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from libs.lmstudio_managed import core_contracts
from libs.lmstudio_managed.core_contracts import (
    EXACT_PUBLIC_MARKER_FIELDS,
    EXPECTED_LAB_ARTIFACT_FILENAMES,
    LAB_ARTIFACT_SCHEMA,
    ArtifactBundleSummary,
    EvidenceKind,
    ExperimentIdentity,
    ExperimentStatus,
    LabEvidenceRef,
    ManagedCoreContract,
    PrivacyScanStatus,
    PrivacyValidationPolicy,
    RecommendationDraft,
    ResultClassification,
    RouteMode,
    SafetyFlags,
    build_artifact_bundle_summary,
    build_l3_7a_recommendation_draft,
    validate_required_artifact_set,
)

from libs import lmstudio_managed

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = PROJECT_ROOT / "experiments" / "lmstudio" / "results_summaries"
L3_6C_R2_DIR = (
    RESULTS_ROOT
    / "run_l3-6c-compact-memory-live-smoke-20260706-r2_l3_6c_25k_compact_memory_live_smoke_gemma4_e2b"
)
L3_6D_DIR = RESULTS_ROOT / "run_l3-6d-mode-comparison-20260706_l3_6d_25k_mode_comparison_gemma4_e2b"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_route_and_result_enum_values_are_stable_strings() -> None:
    assert RouteMode.COMPACT_MEMORY == "compact_memory"
    assert RouteMode.NATIVE_CHAT_STATEFUL == "native_chat_stateful"
    assert RouteMode.STATELESS_FULL_PREFIX == "stateless_full_prefix"
    assert RouteMode.OPENAI_RESPONSES == "openai_responses"
    assert RouteMode.STRICT_JSON_CHAT_COMPLETIONS == "strict_json_chat_completions"

    assert ExperimentStatus.PASSED == "passed"
    assert ExperimentStatus.BLOCKED == "blocked"
    assert ExperimentStatus.BLOCKED_INTERNAL_ERROR == "blocked_internal_error"

    assert ResultClassification.PASSED == "passed"
    assert ResultClassification.BLOCKED == "blocked"
    assert ResultClassification.BLOCKED_INTERNAL_ERROR == "blocked_internal_error"
    assert ResultClassification.PRIMARY_CANDIDATE == "primary_candidate"
    assert ResultClassification.RESEARCH_LATENCY_CANDIDATE == "research_latency_candidate"
    assert ResultClassification.BASELINE == "baseline"
    assert ResultClassification.CACHE_ACCOUNTING_CANDIDATE == "cache_accounting_candidate"
    assert ResultClassification.PRODUCTION_BLOCKED == "production_blocked"


def test_core_contract_dataclass_defaults_are_lab_safe_and_privacy_safe() -> None:
    identity = ExperimentIdentity(experiment_id="exp-l3-7a", run_id="run-l3-7a")
    safety = SafetyFlags()
    contract = ManagedCoreContract(identity=identity)

    assert identity.is_lab_only is True
    assert identity.production_default is False
    assert identity.wvm_runtime_integration is False
    assert safety.generation_allowed is False
    assert safety.live_25k_authorized is False
    assert safety.kv_reuse_proven is False
    assert safety.is_privacy_safe is True
    assert contract.is_production_promotable is False


def test_artifact_schema_lists_expected_ten_filenames() -> None:
    assert LAB_ARTIFACT_SCHEMA["artifact_filenames"] == EXPECTED_LAB_ARTIFACT_FILENAMES
    assert len(EXPECTED_LAB_ARTIFACT_FILENAMES) == 10

    validation = validate_required_artifact_set(EXPECTED_LAB_ARTIFACT_FILENAMES)

    assert validation.is_valid is True
    assert validation.missing_required_artifacts == ()
    assert validation.missing_optional_artifacts == ()


def test_existing_l3_6c_r2_artifacts_fit_bundle_summary_contract() -> None:
    summary = build_artifact_bundle_summary(
        _read_json(L3_6C_R2_DIR / "environment.json"),
        _read_json(L3_6C_R2_DIR / "run_config.json"),
        _read_json(L3_6C_R2_DIR / "privacy_scan.json"),
    )

    assert summary.identity.experiment_id == "l3_6c_25k_compact_memory_live_smoke_gemma4_e2b"
    assert summary.identity.run_id == "l3-6c-compact-memory-live-smoke-20260706-r2"
    assert summary.identity.is_lab_only is True
    assert summary.safety.kv_reuse_proven is False
    assert summary.safety.is_privacy_safe is True
    assert summary.privacy_scan_status == PrivacyScanStatus.PASS
    assert summary.artifact_validation is not None
    assert summary.artifact_validation.is_valid is True
    assert summary.artifact_validation.missing_optional_artifacts == ("comparison_summary.json",)
    assert summary.route_results[0].route == RouteMode.COMPACT_MEMORY
    assert summary.route_results[0].classification is None
    assert summary.comparison_available is False
    assert summary.privacy_policy.public_model_id == "google/gemma-4-e2b"
    assert summary.privacy_policy.public_model_key == "gemma4_e2b_q4km"
    assert summary.privacy_policy.is_exact_public_marker_exempt("model_id", "google/gemma-4-e2b")
    assert summary.privacy_policy.is_exact_public_marker_exempt("model_key", "gemma4_e2b_q4km")


def test_existing_l3_6d_artifacts_preserve_mode_classifications() -> None:
    summary = build_artifact_bundle_summary(
        _read_json(L3_6D_DIR / "environment.json"),
        _read_json(L3_6D_DIR / "run_config.json"),
        _read_json(L3_6D_DIR / "privacy_scan.json"),
        _read_json(L3_6D_DIR / "comparison_summary.json"),
    )

    assert summary.artifact_validation is not None
    assert summary.artifact_validation.is_valid is True
    assert summary.comparison_available is True
    assert summary.classification_for(RouteMode.COMPACT_MEMORY) == (
        ResultClassification.PRIMARY_CANDIDATE
    )
    assert summary.classification_for(RouteMode.NATIVE_CHAT_STATEFUL) == (
        ResultClassification.RESEARCH_LATENCY_CANDIDATE
    )
    assert summary.classification_for(RouteMode.STATELESS_FULL_PREFIX) == (
        ResultClassification.BASELINE
    )


def test_l3_5_summary_markdown_can_be_represented_as_evidence_ref() -> None:
    evidence_ref = LabEvidenceRef(
        experiment_id="l3_5b_32k_load_only",
        summary_ref=(
            "experiments/lmstudio/results_summaries/2026-07-06_l3_5b_32k_load_only_summary.md"
        ),
        notes="Lifecycle-only closure; no generation and no production promotion.",
    )

    assert evidence_ref.kind == EvidenceKind.MARKDOWN_SUMMARY
    assert evidence_ref.status == ExperimentStatus.PASSED
    assert evidence_ref.has_artifact_bundle is False
    assert evidence_ref.summary_ref.endswith("2026-07-06_l3_5b_32k_load_only_summary.md")


def test_privacy_policy_defaults_do_not_exempt_arbitrary_values() -> None:
    policy = PrivacyValidationPolicy()

    assert EXACT_PUBLIC_MARKER_FIELDS == ("model_id", "model_key")
    assert policy.is_exact_public_marker_exempt("model_id", "google/gemma-4-e2b") is False
    assert policy.is_exact_public_marker_exempt("model_key", "gemma4_e2b_q4km") is False
    assert policy.is_exact_public_marker_exempt("state_id", "raw-state-id") is False
    assert (
        policy.is_exact_public_marker_exempt(
            "local_url", "http://127.0.0.1:1234/v1/chat/completions"
        )
        is False
    )
    assert policy.is_exact_public_marker_exempt("prompt", "raw prompt text") is False


def test_privacy_policy_exempts_only_exact_configured_public_model_markers() -> None:
    policy = PrivacyValidationPolicy(
        public_model_id="google/gemma-4-e2b",
        public_model_key="gemma4_e2b_q4km",
    )

    assert policy.is_exact_public_marker_exempt("model_id", "google/gemma-4-e2b")
    assert policy.is_exact_public_marker_exempt("model_key", "gemma4_e2b_q4km")
    assert policy.is_exact_public_marker_exempt("model_id", "google/gemma-4-e2") is False
    assert policy.is_exact_public_marker_exempt("model_id", "prefix/google/gemma-4-e2b") is False
    assert policy.is_exact_public_marker_exempt("model_key", "gemma4_e2b_q4km_local") is False
    assert (
        policy.is_exact_public_marker_exempt(
            "model_id", "http://127.0.0.1:1234/v1/chat/completions"
        )
        is False
    )
    assert policy.is_exact_public_marker_exempt("model_key", "raw-state-id") is False
    assert policy.is_exact_public_marker_exempt("model_id", "raw prompt text") is False
    assert policy.is_exact_public_marker_exempt("state_id", "google/gemma-4-e2b") is False


def test_recommendation_draft_is_conservative_internal_only_policy() -> None:
    draft = build_l3_7a_recommendation_draft()

    assert isinstance(draft, RecommendationDraft)
    assert draft.final_user_facing is False
    assert draft.classification_for(RouteMode.COMPACT_MEMORY) == (
        ResultClassification.PRIMARY_CANDIDATE
    )
    assert draft.classification_for(RouteMode.NATIVE_CHAT_STATEFUL) == (
        ResultClassification.RESEARCH_LATENCY_CANDIDATE
    )
    assert draft.classification_for(RouteMode.STATELESS_FULL_PREFIX) == (
        ResultClassification.BASELINE
    )
    assert draft.classification_for(RouteMode.OPENAI_RESPONSES) == (
        ResultClassification.PRODUCTION_BLOCKED
    )


def test_root_package_exports_key_core_contracts() -> None:
    assert lmstudio_managed.ManagedCoreContract is ManagedCoreContract
    assert lmstudio_managed.ArtifactBundleSummary is ArtifactBundleSummary
    assert lmstudio_managed.RouteMode is RouteMode
    assert lmstudio_managed.ResultClassification is ResultClassification
    assert lmstudio_managed.validate_required_artifact_set is validate_required_artifact_set
    assert lmstudio_managed.build_artifact_bundle_summary is build_artifact_bundle_summary
    assert core_contracts.ManagedCoreContract is ManagedCoreContract


def test_new_core_contract_dtos_are_frozen_slots_dataclasses() -> None:
    for dto in (
        ExperimentIdentity,
        SafetyFlags,
        PrivacyValidationPolicy,
        ArtifactBundleSummary,
        ManagedCoreContract,
    ):
        assert dto.__dataclass_params__.frozen is True
        assert hasattr(dto, "__slots__")
        assert tuple(field.name for field in fields(dto))
