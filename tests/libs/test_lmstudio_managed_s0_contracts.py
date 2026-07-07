from __future__ import annotations

from dataclasses import fields

import pytest
from libs.lmstudio_managed.download import DownloadProgress, DownloadStatus
from libs.lmstudio_managed.generation import (
    GenerationProfile,
    GenerationPurpose,
    ResponseFormatKind,
)
from libs.lmstudio_managed.lifecycle import (
    LifecycleAction,
    LoadConfig,
    LoadedInstance,
    ObservedModelState,
    ParallelSemantics,
    classify_load_timeout_reconcile,
    classify_parallel_semantics,
    decide_lifecycle_action,
    decide_unload_action,
)
from libs.lmstudio_managed.metrics import (
    BatchMetrics,
    ParallelEvidence,
    ScreeningEvidence,
    SystemSummary,
)
from libs.lmstudio_managed.registry import (
    ModelCandidate,
    ModelCapability,
    ModelEvidenceRef,
    ModelIdentity,
    ModelIdentityFacts,
    ModelProfileRecommendation,
    ModelVerificationStatus,
    ProfilePurpose,
    ProfileStatus,
)
from libs.lmstudio_managed.validation import (
    GenerationFailureKind,
    PlainTextValidationResult,
    ReasoningRoutingStatus,
    StructuredValidationResult,
    StructuredValidationStatus,
    failure_kind_from_lab_category,
)


@pytest.mark.parametrize(
    ("app_concurrency", "applied_parallel", "queue_pressure_mode", "expected"),
    [
        (1, 1, False, ParallelSemantics.SEQUENTIAL),
        (4, 4, False, ParallelSemantics.TRUE_PARALLEL),
        (4, 2, True, ParallelSemantics.QUEUE_PRESSURE),
        (4, 2, False, ParallelSemantics.OVERBOOKED_STRESS),
        (None, 2, False, ParallelSemantics.UNKNOWN),
        (3, None, False, ParallelSemantics.UNKNOWN),
    ],
)
def test_classify_parallel_semantics(
    app_concurrency: int | None,
    applied_parallel: int | None,
    queue_pressure_mode: bool | None,
    expected: ParallelSemantics,
) -> None:
    assert (
        classify_parallel_semantics(
            app_concurrency=app_concurrency,
            applied_parallel=applied_parallel,
            queue_pressure_mode=queue_pressure_mode,
        )
        == expected
    )


def test_decide_lifecycle_action_reuses_compatible_loaded_instance() -> None:
    requested = LoadConfig(model_key="model-a", context_length=4096, parallel=2)
    observed = ObservedModelState(
        instances=(
            LoadedInstance(
                instance_ref="inst-1",
                model_key="model-a",
                config=LoadConfig(model_key="model-a", context_length=4096, parallel=4),
            ),
        )
    )

    decision = decide_lifecycle_action(observed, requested)

    assert decision.action == LifecycleAction.NOOP
    assert decision.reason == "reuse_loaded_instance"
    assert decision.target_instance_ref is None
    assert decision.load_config is None


def test_decide_lifecycle_action_reuses_loaded_instance_with_larger_context_and_parallel() -> None:
    requested = LoadConfig(model_key="model-a", context_length=4096, parallel=1)
    observed = ObservedModelState(
        instances=(
            LoadedInstance(
                instance_ref="inst-1",
                model_key="model-a",
                config=LoadConfig(model_key="model-a", context_length=8192, parallel=2),
            ),
        )
    )

    decision = decide_lifecycle_action(observed, requested)

    assert decision.action == LifecycleAction.NOOP
    assert decision.reason == "reuse_loaded_instance"
    assert decision.target_instance_ref is None
    assert decision.load_config is None


def test_decide_lifecycle_action_fails_on_duplicate_loaded_instances() -> None:
    requested = LoadConfig(model_key="model-a")
    observed = ObservedModelState(
        instances=(
            LoadedInstance(
                instance_ref="inst-1",
                model_key="model-a",
                config=LoadConfig(model_key="model-a"),
            ),
            LoadedInstance(
                instance_ref="inst-2",
                model_key="model-a",
                config=LoadConfig(model_key="model-a"),
            ),
        )
    )

    decision = decide_lifecycle_action(observed, requested)

    assert decision.action == LifecycleAction.FAIL_DUPLICATE
    assert decision.reason == "duplicate_loaded_instances"


def test_decide_lifecycle_action_unloads_first_instance_for_single_model_safe_swap() -> None:
    requested = LoadConfig(model_key="model-a")
    observed = ObservedModelState(
        instances=(
            LoadedInstance(
                instance_ref="inst-1",
                model_key="model-b",
                config=LoadConfig(model_key="model-b"),
            ),
        )
    )

    decision = decide_lifecycle_action(observed, requested)

    assert decision.action == LifecycleAction.UNLOAD_EXACT
    assert decision.reason == "single_model_safe_swap"
    assert decision.target_instance_ref == "inst-1"
    assert decision.load_config is None


def test_decide_lifecycle_action_loads_when_model_is_absent() -> None:
    requested = LoadConfig(model_key="model-a", context_length=8192, parallel=1)

    decision = decide_lifecycle_action(ObservedModelState(), requested)

    assert decision.action == LifecycleAction.LOAD
    assert decision.reason == "not_loaded"
    assert decision.load_config == requested


def test_decide_lifecycle_action_returns_config_insufficient_for_incompatible_loaded_instance() -> (
    None
):
    requested = LoadConfig(model_key="model-a", context_length=8192, parallel=4)
    observed = ObservedModelState(
        instances=(
            LoadedInstance(
                instance_ref="inst-1",
                model_key="model-a",
                config=LoadConfig(
                    model_key="model-a",
                    context_length=4096,
                    parallel=2,
                ),
            ),
        )
    )

    decision = decide_lifecycle_action(observed, requested)

    assert decision.action == LifecycleAction.CONFIG_INSUFFICIENT
    assert decision.reason == "loaded_config_insufficient"
    assert decision.target_instance_ref == "inst-1"


def test_decide_unload_action_returns_already_unloaded_when_missing() -> None:
    decision = decide_unload_action(ObservedModelState(), "model-a")

    assert decision.action == LifecycleAction.ALREADY_UNLOADED
    assert decision.reason == "already_unloaded"


def test_decide_unload_action_unloads_single_owned_instance() -> None:
    observed = ObservedModelState(
        instances=(
            LoadedInstance(
                instance_ref="inst-1",
                model_key="model-a",
                config=LoadConfig(model_key="model-a"),
                owned_by_us=True,
            ),
        )
    )

    decision = decide_unload_action(observed, "model-a")

    assert decision.action == LifecycleAction.UNLOAD_EXACT
    assert decision.reason == "owned_instance_present"
    assert decision.target_instance_ref == "inst-1"


def test_decide_unload_action_cleans_up_multiple_owned_instances() -> None:
    observed = ObservedModelState(
        instances=(
            LoadedInstance(
                instance_ref="inst-1",
                model_key="model-a",
                config=LoadConfig(model_key="model-a"),
                owned_by_us=True,
            ),
            LoadedInstance(
                instance_ref="inst-2",
                model_key="model-a",
                config=LoadConfig(model_key="model-a"),
                owned_by_us=True,
            ),
        )
    )

    decision = decide_unload_action(observed, "model-a")

    assert decision.action == LifecycleAction.CLEANUP_EXACT_EACH
    assert decision.reason == "multiple_owned_instances"
    assert decision.target_instance_refs == ("inst-1", "inst-2")


def test_decide_unload_action_does_not_touch_external_instance_by_default() -> None:
    observed = ObservedModelState(
        instances=(
            LoadedInstance(
                instance_ref="inst-1",
                model_key="model-a",
                config=LoadConfig(model_key="model-a"),
                owned_by_us=False,
            ),
        )
    )

    decision = decide_unload_action(observed, "model-a")

    assert decision.action == LifecycleAction.DO_NOT_TOUCH
    assert decision.reason == "external_instance_not_owned"


def test_classify_load_timeout_reconcile_returns_observed_success() -> None:
    requested = LoadConfig(model_key="model-a", context_length=4096, parallel=2)
    observed = ObservedModelState(
        instances=(
            LoadedInstance(
                instance_ref="inst-1",
                model_key="model-a",
                config=LoadConfig(
                    model_key="model-a",
                    context_length=8192,
                    parallel=2,
                ),
            ),
        )
    )

    decision = classify_load_timeout_reconcile(observed, requested)

    assert decision.action == LifecycleAction.LOAD_RECONCILE_OK
    assert decision.reason == "load_succeeded_but_response_lost"
    assert decision.target_instance_ref == "inst-1"


def test_classify_load_timeout_reconcile_returns_failed_when_absent() -> None:
    decision = classify_load_timeout_reconcile(
        ObservedModelState(),
        LoadConfig(model_key="model-a"),
    )

    assert decision.action == LifecycleAction.LOAD_RECONCILE_FAILED
    assert decision.reason == "load_unknown_or_failed"


def test_classify_load_timeout_reconcile_returns_error_when_listing_failed() -> None:
    decision = classify_load_timeout_reconcile(
        ObservedModelState(),
        LoadConfig(model_key="model-a"),
        list_error=True,
    )

    assert decision.action == LifecycleAction.LOAD_RECONCILE_ERROR
    assert decision.reason == "load_reconcile_error"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (DownloadStatus.ALREADY_DOWNLOADED, True),
        (DownloadStatus.COMPLETED, True),
        (DownloadStatus.PAUSED, False),
        (DownloadStatus.FAILED, False),
    ],
)
def test_download_progress_terminal_success(
    status: DownloadStatus,
    expected: bool,
) -> None:
    progress = DownloadProgress(
        status=status,
        ready_on_disk=expected,
        downloaded_bytes=128,
        total_bytes=256,
    )

    assert progress.is_terminal_success is expected


def test_generation_profile_defaults_and_true_parallel_candidate() -> None:
    profile = GenerationProfile(
        profile_id="factual-default",
        model_key="model-a",
        purpose=GenerationPurpose.FACTUAL_BLOCKS,
        response_format=ResponseFormatKind.JSON_SCHEMA,
        load_parallel=3,
        app_concurrency=3,
    )

    assert profile.production_default is False
    assert profile.is_true_parallel_candidate is True


def test_profile_catalog_recommendation_defaults_and_evidence_refs() -> None:
    evidence_ref = ModelEvidenceRef(
        run_id="run-001",
        summary_ref="summary-md-ref",
        notes="safe",
    )
    recommendation = ModelProfileRecommendation(
        profile_id="factual-default",
        model_key="model-a",
        purpose=ProfilePurpose.FACTUAL_BLOCKS,
        status=ProfileStatus.LAB_BASELINE,
        evidence_refs=(evidence_ref,),
        max_tokens=1024,
        load_parallel=2,
        app_concurrency=2,
    )
    candidate = ModelCandidate(
        identity=ModelIdentity(
            candidate_key="model-a",
            compat_model_id="compat-a",
            verification_status=ModelVerificationStatus.COMPAT_VERIFIED,
        ),
        capabilities=(
            ModelCapability.TEXT_GENERATION,
            ModelCapability.STRUCTURED_JSON,
        ),
        recommendations=(recommendation,),
    )

    assert recommendation.production_default is False
    assert recommendation.evidence_refs == (evidence_ref,)
    assert candidate.recommendations[0].profile_id == "factual-default"


def test_model_identity_facts_uses_candidate_key_contract() -> None:
    field_names = [field.name for field in fields(ModelIdentityFacts)]

    assert field_names[:4] == [
        "candidate_key",
        "source_id",
        "compat_model_id",
        "native_model_key",
    ]
    assert "lab_key" not in field_names


@pytest.mark.parametrize(
    ("category", "kwargs", "expected"),
    [
        (
            "empty",
            {"content_empty": True, "reasoning_content_present": True},
            GenerationFailureKind.REASONING_CONTENT_ONLY,
        ),
        (
            None,
            {"finish_reason": "length"},
            GenerationFailureKind.FINISH_LENGTH,
        ),
        ("timeout", {}, GenerationFailureKind.TIMEOUT),
        ("json", {}, GenerationFailureKind.JSON_DECODE_ERROR),
        ("http", {}, GenerationFailureKind.HTTP_ERROR),
        ("schema", {}, GenerationFailureKind.SCHEMA_ERROR),
        ("business", {}, GenerationFailureKind.BUSINESS_ERROR),
    ],
)
def test_failure_kind_from_lab_category(
    category: str | None,
    kwargs: dict[str, object],
    expected: GenerationFailureKind,
) -> None:
    assert failure_kind_from_lab_category(category, **kwargs) == expected


def test_validation_result_pass_properties() -> None:
    structured = StructuredValidationResult(
        json_parse_pass=True,
        schema_pass=True,
        business_pass=True,
        reasoning_routing=ReasoningRoutingStatus.CONTENT_ONLY,
        expected_count=2,
        observed_count=2,
    )
    plain_text = PlainTextValidationResult(
        non_empty_text_pass=True,
        reasoning_routing=ReasoningRoutingStatus.NONE_DETECTED,
        word_count=12,
    )

    assert structured.passed is True
    assert plain_text.passed is True


def test_parallel_evidence_true_parallel_property() -> None:
    evidence = ParallelEvidence(
        configured_parallel=3,
        applied_parallel=3,
        parallel_verified=True,
        app_concurrency=3,
        queue_pressure_mode=False,
        parallel_semantics=ParallelSemantics.TRUE_PARALLEL,
    )

    assert evidence.is_true_parallel is True


def test_parallel_evidence_false_when_queue_pressure_present() -> None:
    evidence = ParallelEvidence(
        configured_parallel=3,
        applied_parallel=3,
        parallel_verified=True,
        app_concurrency=3,
        queue_pressure_mode=True,
        parallel_semantics=ParallelSemantics.QUEUE_PRESSURE,
    )

    assert evidence.is_true_parallel is False


def test_parallel_evidence_false_when_not_verified() -> None:
    evidence = ParallelEvidence(
        configured_parallel=3,
        applied_parallel=3,
        parallel_verified=False,
        app_concurrency=3,
        queue_pressure_mode=False,
        parallel_semantics=ParallelSemantics.TRUE_PARALLEL,
    )

    assert evidence.is_true_parallel is False


def test_metrics_batch_rate_and_screening_evidence_storage() -> None:
    batch_metrics = BatchMetrics(
        request_count=4,
        business_pass_count=3,
        finish_length_count=1,
        structured_error_count=1,
        total_wall_time_ms=250,
        total_completion_tokens=900,
    )
    screening_evidence = ScreeningEvidence(
        model_key="model-a",
        structured_status=StructuredValidationStatus.PASSED,
        parallel_evidence=ParallelEvidence(
            configured_parallel=2,
            applied_parallel=2,
            parallel_verified=True,
            app_concurrency=2,
            queue_pressure_mode=False,
            parallel_semantics=ParallelSemantics.TRUE_PARALLEL,
        ),
        batch_metrics=batch_metrics,
        system_summary=SystemSummary(
            vram_before_mb=768,
            vram_peak_mb=1024,
            vram_after_mb=896,
            ram_before_mb=1536,
            ram_peak_mb=2048,
            ram_after_mb=1792,
            process_rss_before_mb=256,
            process_rss_peak_mb=512,
            process_rss_after_mb=384,
            gpu_util_peak_percent=80,
            gpu_memory_util_peak_percent=64,
            gpu_power_peak_watts=150,
        ),
        token_normalized_speedup=1.25,
    )

    assert batch_metrics.business_pass_rate == pytest.approx(0.75)
    assert screening_evidence.token_normalized_speedup == pytest.approx(1.25)
    assert screening_evidence.system_summary is not None
    assert screening_evidence.system_summary.process_rss_peak_mb == 512


def test_batch_metrics_business_pass_rate_returns_none_for_zero_requests() -> None:
    batch_metrics = BatchMetrics(
        request_count=0,
        business_pass_count=0,
        finish_length_count=0,
        structured_error_count=0,
    )

    assert batch_metrics.business_pass_rate is None
