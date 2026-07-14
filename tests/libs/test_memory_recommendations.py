from __future__ import annotations

import pytest

from lmstudio_managed.metrics import (
    GpuTelemetryEvidenceLevel,
    MemoryCellObservation,
    MemoryRecommendationStatus,
    SafetyReservePolicy,
    build_memory_recommendation,
)


def _observation(
    attempt_index: int,
    *,
    peak: float = 12_000.0,
    evidence: GpuTelemetryEvidenceLevel = GpuTelemetryEvidenceLevel.NVML_PROCESS_ATTRIBUTED,
    placement_observed: bool = True,
    operation_succeeded: bool = True,
    capacity_fit: bool = True,
    identity_verified: bool = True,
    runtime_shape_verified: bool = True,
    telemetry_valid: bool = True,
    overlap_proven: bool = True,
    phase_evidence_valid: bool = True,
    independent_cycle_proven: bool = True,
    immutable_owner_evidence_bound: bool = True,
) -> MemoryCellObservation:
    return MemoryCellObservation(
        attempt_id=f"attempt-{attempt_index}",
        model_artifact="publisher/model/file.gguf",
        artifact_revision="revision-7",
        artifact_checksum="sha256:" + "a" * 64,
        quantization="Q4_K_M",
        context_tokens=8192,
        runtime_parallel=2,
        application_concurrency=2,
        workload_class="structured_text",
        placement_requirement="full_gpu_required",
        kv_placement="gpu",
        telemetry_evidence=evidence,
        clean_baseline_vram_mb=500.0,
        loaded_idle_vram_mb=10_000.0,
        measured_peak_vram_mb=peak,
        identity_verified=identity_verified,
        runtime_shape_verified=runtime_shape_verified,
        telemetry_valid=telemetry_valid,
        operation_succeeded=operation_succeeded,
        response_integrity_passed=True,
        cleanup_global_zero_passed=True,
        placement_observed=placement_observed,
        capacity_fit=capacity_fit,
        thrash_observed=False,
        overlap_proven=overlap_proven,
        phase_evidence_valid=phase_evidence_valid,
        independent_cycle_proven=independent_cycle_proven,
        immutable_owner_evidence_bound=immutable_owner_evidence_bound,
    )


def test_recommendation_keeps_fixed_and_active_costs_separate() -> None:
    recommendation = build_memory_recommendation(
        (_observation(1, peak=11_700.0), _observation(2, peak=12_200.0), _observation(3)),
        reserve_policy=SafetyReservePolicy(
            policy_id="candidate-10pct-or-512mb",
            percent=0.10,
            absolute_floor_mb=512.0,
        ),
    )

    assert recommendation.fixed_model_cost_vram_mb == 9_500.0
    assert recommendation.context_concurrency_overhead_vram_mb == 2_200.0
    assert recommendation.measured_peak_vram_mb == 12_200.0
    assert recommendation.safety_reserve_vram_mb == 1_220.0
    assert recommendation.recommended_vram_mb == 13_420.0


def test_one_successful_run_can_never_approve() -> None:
    recommendation = build_memory_recommendation((_observation(1),))

    assert recommendation.status is MemoryRecommendationStatus.INSUFFICIENT_EVIDENCE
    assert recommendation.repeat_count == 1
    assert recommendation.required_repeats == 3


def test_memory_recommendation_requires_at_least_three_repeats() -> None:
    with pytest.raises(ValueError, match="required_repeats must be an integer >= 3"):
        build_memory_recommendation(
            (_observation(1), _observation(2)),
            required_repeats=2,
        )


def test_status_policy_approves_only_repeated_attributed_placed_evidence() -> None:
    approved = build_memory_recommendation(tuple(_observation(index) for index in range(3)))
    manual = build_memory_recommendation(
        tuple(
            _observation(
                index,
                evidence=GpuTelemetryEvidenceLevel.NVML_DEVICE_ONLY,
                placement_observed=False,
            )
            for index in range(3)
        )
    )
    rejected = build_memory_recommendation((_observation(1, operation_succeeded=False),))

    assert approved.status is MemoryRecommendationStatus.APPROVED
    assert manual.status is MemoryRecommendationStatus.MANUAL_ONLY
    assert rejected.status is MemoryRecommendationStatus.REJECTED


def test_status_policy_fails_closed_when_identity_shape_or_telemetry_is_unverified() -> None:
    observations = tuple(
        _observation(
            index,
            identity_verified=False,
            runtime_shape_verified=False,
            telemetry_valid=False,
        )
        for index in range(3)
    )

    recommendation = build_memory_recommendation(observations)

    assert recommendation.status is MemoryRecommendationStatus.INSUFFICIENT_EVIDENCE
    assert recommendation.status_reasons == (
        "exact_identity_unverified",
        "runtime_shape_unverified",
        "telemetry_invalid",
    )


@pytest.mark.parametrize(
    ("override", "reason"),
    (
        ({"overlap_proven": False}, "application_overlap_unproven"),
        ({"phase_evidence_valid": False}, "phase_evidence_invalid"),
        ({"independent_cycle_proven": False}, "independent_cycle_unproven"),
        ({"immutable_owner_evidence_bound": False}, "immutable_owner_evidence_unbound"),
    ),
)
def test_status_policy_requires_runtime_evidence_proofs(
    override: dict[str, bool],
    reason: str,
) -> None:
    recommendation = build_memory_recommendation(
        tuple(_observation(index, **override) for index in range(3))
    )

    assert recommendation.status is MemoryRecommendationStatus.INSUFFICIENT_EVIDENCE
    assert reason in recommendation.status_reasons
