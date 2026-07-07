from __future__ import annotations

from dataclasses import fields

import pytest

from libs.lmstudio_managed import (
    CacheEvidence,
    CacheExperimentPlan,
    CacheMeasurementStatus,
    CacheReuseVerdict,
    CompactMemoryRequest,
    ContextReuseMode,
    EndpointKind,
    LMStudioEndpointFamily,
    ResponsesCacheProbeStatus,
    ResponsesUsageSummary,
    StatefulBranchRequest,
    StatefulRootRequest,
    StatelessPrefixRequest,
    cache_contracts,
    parse_responses_usage,
)

FROZEN_SLOT_DTOS = (
    StatefulRootRequest,
    StatefulBranchRequest,
    StatelessPrefixRequest,
    CompactMemoryRequest,
    CacheExperimentPlan,
    CacheEvidence,
    ResponsesUsageSummary,
)


def test_cache_enum_values_are_stable_strings() -> None:
    assert ContextReuseMode.STATEFUL_ROOT_BRANCH == "stateful_root_branch"
    assert ContextReuseMode.STATELESS_FULL_PREFIX == "stateless_full_prefix"
    assert ContextReuseMode.COMPACT_MEMORY == "compact_memory"
    assert CacheMeasurementStatus.NOT_MEASURED_NO_LIVE == "not_measured_no_live"
    assert CacheMeasurementStatus.FUNCTIONAL_STATEFUL_OK == "functional_stateful_ok"
    assert CacheMeasurementStatus.INCONCLUSIVE == "inconclusive"
    assert CacheReuseVerdict.KV_REUSE_UNPROVEN == "kv_reuse_unproven"
    assert CacheReuseVerdict.KV_REUSE_LIKELY == "kv_reuse_likely"
    assert CacheReuseVerdict.KV_REUSE_PROVEN == "kv_reuse_proven"
    assert CacheReuseVerdict.LATENCY_CANDIDATE == "latency_candidate"
    assert CacheReuseVerdict.CACHE_PROXY_SIGNAL == "cache_proxy_signal"
    assert CacheReuseVerdict.NO_REUSE_DETECTED == "no_reuse_detected"
    assert CacheReuseVerdict.INCONCLUSIVE == "inconclusive"
    assert ResponsesCacheProbeStatus.RESPONSES_UNSUPPORTED == "responses_unsupported"
    assert ResponsesCacheProbeStatus.RESPONSES_USABLE_NO_CACHE == "responses_usable_no_cache"
    assert ResponsesCacheProbeStatus.RESPONSES_USABLE_NO_CACHE_AT_16K == (
        "responses_usable_no_cache_at_16k"
    )
    assert ResponsesCacheProbeStatus.RESPONSES_CACHE_SIGNAL_PRESENT == (
        "responses_cache_signal_present"
    )
    assert ResponsesCacheProbeStatus.RESPONSES_CACHE_ACCOUNTING_CANDIDATE == (
        "responses_cache_accounting_candidate"
    )
    assert ResponsesCacheProbeStatus.RESPONSES_CACHE_ACCOUNTING_CANDIDATE_16K == (
        "responses_cache_accounting_candidate_16k"
    )
    assert ResponsesCacheProbeStatus.RESPONSES_BLOCKED == "responses_blocked"
    assert EndpointKind.OPENAI_RESPONSES == "openai_responses"
    assert LMStudioEndpointFamily.OPENAI_RESPONSES == "openai_responses"


def test_cache_evidence_defaults_to_no_live_unproven_state() -> None:
    evidence = CacheEvidence(experiment_id="exp-1", model_key="gemma-3")

    assert evidence.measurement_status == CacheMeasurementStatus.NOT_MEASURED_NO_LIVE
    assert evidence.reuse_verdict == CacheReuseVerdict.KV_REUSE_UNPROVEN
    assert evidence.kv_reuse_proven is False
    assert evidence.has_live_measurements is False
    assert evidence.raw_material_stored is False
    assert evidence.production_default is False
    assert evidence.direct_cache_hit_signal is False


def test_functional_stateful_ok_does_not_imply_kv_reuse_proven() -> None:
    evidence = CacheEvidence(
        experiment_id="exp-1",
        model_key="gemma-3",
        measurement_status=CacheMeasurementStatus.FUNCTIONAL_STATEFUL_OK,
        reuse_verdict=CacheReuseVerdict.KV_REUSE_UNPROVEN,
        successful_branch_count=3,
    )

    assert evidence.measurement_status == CacheMeasurementStatus.FUNCTIONAL_STATEFUL_OK
    assert evidence.successful_branch_count == 3
    assert evidence.kv_reuse_proven is False
    assert evidence.has_live_measurements is False


def test_only_explicit_kv_reuse_proven_verdict_sets_property_true() -> None:
    likely = CacheEvidence(
        experiment_id="exp-1",
        model_key="gemma-3",
        reuse_verdict=CacheReuseVerdict.KV_REUSE_LIKELY,
    )
    proven = CacheEvidence(
        experiment_id="exp-1",
        model_key="gemma-3",
        reuse_verdict=CacheReuseVerdict.KV_REUSE_PROVEN,
        ttft_ms=42.0,
        cached_tokens=128,
    )
    missing_telemetry = CacheEvidence(
        experiment_id="exp-1",
        model_key="gemma-3",
        reuse_verdict=CacheReuseVerdict.KV_REUSE_PROVEN,
        ttft_ms=42.0,
    )

    assert likely.kv_reuse_proven is False
    assert likely.has_live_measurements is False
    assert missing_telemetry.kv_reuse_proven is False
    assert proven.kv_reuse_proven is True
    assert proven.has_live_measurements is True


@pytest.mark.parametrize(
    "reuse_verdict",
    (
        CacheReuseVerdict.KV_REUSE_UNPROVEN,
        CacheReuseVerdict.LATENCY_CANDIDATE,
    ),
)
def test_cache_proxy_and_prompt_processing_do_not_prove_kv_reuse_without_direct_telemetry(
    reuse_verdict: CacheReuseVerdict,
) -> None:
    evidence = CacheEvidence(
        experiment_id="exp-1",
        model_key="gemma-3",
        reuse_verdict=reuse_verdict,
        cache_proxy=1.675183,
        prompt_processing_ms=10.098,
        cached_tokens=None,
        direct_cache_hit_signal=False,
    )

    assert evidence.kv_reuse_proven is False
    assert evidence.reuse_verdict in {
        CacheReuseVerdict.KV_REUSE_UNPROVEN,
        CacheReuseVerdict.LATENCY_CANDIDATE,
    }
    assert evidence.has_live_measurements is True


def test_cache_experiment_plan_counts_all_planned_requests() -> None:
    root_request = StatefulRootRequest(
        request_id="root-1",
        model_key="gemma-3",
        dataset_id="dataset-a",
        root_context_hash="hash-root",
        estimated_input_tokens=2048,
        context_window=8192,
    )
    plan = CacheExperimentPlan(
        experiment_id="exp-1",
        model_key="gemma-3",
        context_window=8192,
        root_request=root_request,
        stateful_branch_requests=(
            StatefulBranchRequest(
                request_id="branch-1",
                root_request_id="root-1",
                branch_id="b1",
                root_context_hash="hash-root",
                estimated_branch_tokens=120,
            ),
            StatefulBranchRequest(
                request_id="branch-2",
                root_request_id="root-1",
                branch_id="b2",
                root_context_hash="hash-root",
                estimated_branch_tokens=140,
            ),
        ),
        stateless_prefix_requests=(
            StatelessPrefixRequest(
                request_id="prefix-1",
                branch_id="b1",
                prefix_context_hash="hash-prefix",
                estimated_input_tokens=2168,
            ),
        ),
        compact_memory_requests=(
            CompactMemoryRequest(
                request_id="compact-1",
                branch_id="b1",
                memory_hash="hash-memory",
                estimated_memory_tokens=200,
                estimated_branch_tokens=120,
            ),
        ),
    )

    assert plan.planned_request_count == 5
    assert plan.production_default is False
    assert plan.raw_material_stored is False


def test_cache_request_dtos_carry_modes_and_privacy_defaults() -> None:
    root_request = StatefulRootRequest(
        request_id="root-1",
        model_key="gemma-3",
        dataset_id="dataset-a",
        root_context_hash="hash-root",
        estimated_input_tokens=2048,
        context_window=8192,
    )
    branch_request = StatefulBranchRequest(
        request_id="branch-1",
        root_request_id="root-1",
        branch_id="b1",
        root_context_hash="hash-root",
        estimated_branch_tokens=120,
    )
    prefix_request = StatelessPrefixRequest(
        request_id="prefix-1",
        branch_id="b1",
        prefix_context_hash="hash-prefix",
        estimated_input_tokens=2168,
    )
    compact_request = CompactMemoryRequest(
        request_id="compact-1",
        branch_id="b1",
        memory_hash="hash-memory",
        estimated_memory_tokens=200,
        estimated_branch_tokens=120,
    )

    assert root_request.mode == ContextReuseMode.STATEFUL_ROOT_BRANCH
    assert branch_request.mode == ContextReuseMode.STATEFUL_ROOT_BRANCH
    assert prefix_request.mode == ContextReuseMode.STATELESS_FULL_PREFIX
    assert compact_request.mode == ContextReuseMode.COMPACT_MEMORY
    assert root_request.raw_material_stored is False
    assert branch_request.raw_material_stored is False
    assert prefix_request.raw_material_stored is False
    assert compact_request.raw_material_stored is False


def test_root_package_exports_cache_contracts() -> None:
    root_request = StatefulRootRequest(
        request_id="root-1",
        model_key="gemma-3",
        dataset_id="dataset-a",
        root_context_hash="hash-root",
        estimated_input_tokens=2048,
        context_window=8192,
    )
    plan = CacheExperimentPlan(
        experiment_id="exp-1",
        model_key="gemma-3",
        context_window=8192,
        root_request=root_request,
    )

    assert plan.root_request == root_request
    assert CacheEvidence(experiment_id="exp-1", model_key="gemma-3").reuse_verdict == (
        CacheReuseVerdict.KV_REUSE_UNPROVEN
    )


def test_cache_contracts_package_exports_match_root_symbols() -> None:
    assert cache_contracts.ContextReuseMode is ContextReuseMode
    assert cache_contracts.CacheMeasurementStatus is CacheMeasurementStatus
    assert cache_contracts.CacheReuseVerdict is CacheReuseVerdict
    assert cache_contracts.StatefulRootRequest is StatefulRootRequest
    assert cache_contracts.StatefulBranchRequest is StatefulBranchRequest
    assert cache_contracts.StatelessPrefixRequest is StatelessPrefixRequest
    assert cache_contracts.CompactMemoryRequest is CompactMemoryRequest
    assert cache_contracts.CacheExperimentPlan is CacheExperimentPlan
    assert cache_contracts.CacheEvidence is CacheEvidence
    assert cache_contracts.ResponsesCacheProbeStatus is ResponsesCacheProbeStatus
    assert cache_contracts.ResponsesUsageSummary is ResponsesUsageSummary
    assert cache_contracts.parse_responses_usage is parse_responses_usage


def test_parse_responses_usage_reads_cached_tokens_from_nested_usage_details() -> None:
    summary = parse_responses_usage(
        {
            "usage": {
                "input_tokens": 2048,
                "output_tokens": 64,
                "total_tokens": 2112,
                "input_tokens_details": {"cached_tokens": 1536},
            }
        }
    )

    assert summary == ResponsesUsageSummary(
        input_tokens=2048,
        output_tokens=64,
        total_tokens=2112,
        cached_tokens=1536,
        cached_tokens_available=True,
        raw_usage_keys=(
            "input_tokens",
            "input_tokens_details",
            "input_tokens_details.cached_tokens",
            "output_tokens",
            "total_tokens",
        ),
    )


def test_parse_responses_usage_treats_missing_cached_tokens_as_unavailable() -> None:
    summary = parse_responses_usage(
        {
            "usage": {
                "input_tokens": 1024,
                "output_tokens": 32,
                "total_tokens": 1056,
            }
        }
    )

    assert summary.cached_tokens is None
    assert summary.cached_tokens_available is False
    assert summary.raw_usage_keys == ("input_tokens", "output_tokens", "total_tokens")


def test_cache_contract_dtos_are_frozen_slots_dataclasses() -> None:
    for dto in FROZEN_SLOT_DTOS:
        assert dto.__dataclass_params__.frozen is True
        assert hasattr(dto, "__slots__")
        assert tuple(field.name for field in fields(dto))
