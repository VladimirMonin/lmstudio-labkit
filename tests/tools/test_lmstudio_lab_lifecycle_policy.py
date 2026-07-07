from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from tools.lmstudio_lab.lifecycle_policy import (
    LoadConfig,
    LoadedInstanceRef,
    ObservedModelState,
    classify_load_timeout_reconcile,
    detect_duplicate_instances,
    ensure_loaded_decision,
    ensure_unloaded_decision,
)


def _instance_hash(raw_instance_id: str) -> str:
    return f"sha256:{hashlib.sha256(raw_instance_id.encode('utf-8')).hexdigest()}"


def _requested_config() -> LoadConfig:
    return LoadConfig(model_key="qwen3.5-4b", context_length=8192, parallel=1)


def _instance(
    raw_instance_id: str,
    *,
    model_key: str | None = None,
    context_length: int | None = 8192,
    parallel: int | None = 1,
    owned_by_policy: bool = False,
) -> LoadedInstanceRef:
    requested = _requested_config()
    return LoadedInstanceRef(
        instance_hash=_instance_hash(raw_instance_id),
        model_key=model_key or requested.model_key,
        context_length=context_length,
        parallel=parallel,
        owned_by_policy=owned_by_policy,
    )


def _observed(*instances: LoadedInstanceRef) -> ObservedModelState:
    return ObservedModelState.from_loaded_instances("qwen3.5-4b", instances)


def test_ensure_loaded_without_existing_instance_requires_load() -> None:
    decision = ensure_loaded_decision(_requested_config(), _observed())

    assert decision.action == "load_required"
    assert decision.status == "load_required"
    assert decision.may_load is True
    assert decision.observed_instance_count == 0


def test_ensure_loaded_with_same_config_reuses_existing_instance() -> None:
    decision = ensure_loaded_decision(
        _requested_config(),
        _observed(_instance("instance-reuse-1")),
    )

    assert decision.action == "reuse_existing"
    assert decision.status == "reuse_existing"
    assert decision.may_load is False
    assert decision.observed_instance_count == 1


def test_ensure_loaded_with_greater_context_and_parallel_reuses_existing_instance() -> None:
    decision = ensure_loaded_decision(
        _requested_config(),
        _observed(_instance("instance-reuse-2", context_length=16384, parallel=2)),
    )

    assert decision.action == "reuse_existing"
    assert decision.status == "reuse_existing"
    assert decision.may_load is False
    assert decision.observed_instance_count == 1


def test_ensure_loaded_with_different_config_returns_conflict() -> None:
    decision = ensure_loaded_decision(
        _requested_config(),
        _observed(_instance("instance-conflict-1", context_length=4096)),
    )

    assert decision.action == "config_conflict"
    assert decision.status == "config_conflict"
    assert decision.may_load is False


def test_ensure_loaded_with_other_loaded_model_returns_legacy_conflict() -> None:
    other_instance = _instance("instance-other-model-1", model_key="mistral-7b")
    decision = ensure_loaded_decision(
        _requested_config(),
        _observed(other_instance),
    )

    assert decision.action == "config_conflict"
    assert decision.status == "config_conflict"
    assert decision.reason == "loaded instance config differs from the requested config"
    assert decision.may_load is False
    assert decision.observed_instance_hashes == (other_instance.instance_hash,)
    assert decision.observed_instance_count == 1
    assert decision.requested_config == _requested_config()


def test_ensure_loaded_with_duplicate_instances_blocks_blind_load() -> None:
    decision = ensure_loaded_decision(
        _requested_config(),
        _observed(_instance("instance-dup-1"), _instance("instance-dup-2")),
    )

    assert decision.action == "duplicate_instances"
    assert decision.status == "duplicate_instances"
    assert decision.may_load is False
    assert decision.observed_instance_count == 2


def test_ensure_loaded_with_unknown_config_blocks_blind_load() -> None:
    decision = ensure_loaded_decision(
        _requested_config(),
        _observed(_instance("instance-unknown-1", context_length=None)),
    )

    assert decision.action == "config_unknown"
    assert decision.status == "config_unknown"
    assert decision.may_load is False


def test_ensure_unloaded_without_instance_is_already_unloaded() -> None:
    decision = ensure_unloaded_decision(_observed())

    assert decision.action == "already_unloaded"
    assert decision.status == "already_unloaded"
    assert decision.may_unload is False
    assert decision.target_hashes == ()


def test_ensure_unloaded_with_one_owned_instance_targets_exact_hash() -> None:
    owned_instance = _instance("instance-owned-1", owned_by_policy=True)
    decision = ensure_unloaded_decision(_observed(owned_instance))

    assert decision.action == "unload_required"
    assert decision.status == "unload_required"
    assert decision.may_unload is True
    assert decision.target_hashes == (owned_instance.instance_hash,)


def test_ensure_unloaded_with_multiple_owned_instances_requires_cleanup() -> None:
    first_owned = _instance("instance-owned-1", owned_by_policy=True)
    second_owned = _instance("instance-owned-2", owned_by_policy=True)
    decision = ensure_unloaded_decision(_observed(first_owned, second_owned))

    assert decision.action == "cleanup_required"
    assert decision.status == "cleanup_required"
    assert decision.may_unload is True
    assert decision.target_hashes == tuple(
        sorted((first_owned.instance_hash, second_owned.instance_hash))
    )


def test_ensure_unloaded_with_external_instances_does_not_unload() -> None:
    external_instance = _instance("instance-external-1", owned_by_policy=False)
    decision = ensure_unloaded_decision(_observed(external_instance))

    assert decision.action == "external_instances_present"
    assert decision.status == "external_instances_present"
    assert decision.may_unload is False
    assert decision.target_hashes == ()


def test_ensure_unloaded_with_mixed_owned_and_external_targets_only_owned_hashes() -> None:
    owned_instance = _instance("instance-owned-1", owned_by_policy=True)
    external_instance = _instance("instance-external-1", owned_by_policy=False)
    decision = ensure_unloaded_decision(_observed(owned_instance, external_instance))

    assert decision.action == "cleanup_required"
    assert decision.status == "cleanup_required"
    assert decision.may_unload is True
    assert decision.target_hashes == (owned_instance.instance_hash,)
    assert decision.external_instance_count == 1
    assert external_instance.instance_hash not in decision.target_hashes


def test_timeout_reconcile_with_matching_instance_marks_lost_response() -> None:
    decision = classify_load_timeout_reconcile(
        _requested_config(),
        _observed(_instance("instance-timeout-1")),
    )

    assert decision.action == "load_succeeded_but_response_lost"
    assert decision.status == "load_succeeded_but_response_lost"


def test_timeout_reconcile_with_greater_context_and_parallel_marks_lost_response() -> None:
    decision = classify_load_timeout_reconcile(
        _requested_config(),
        _observed(_instance("instance-timeout-2", context_length=16384, parallel=2)),
    )

    assert decision.action == "load_succeeded_but_response_lost"
    assert decision.status == "load_succeeded_but_response_lost"


def test_timeout_reconcile_without_matching_instance_marks_unknown_or_failed() -> None:
    decision = classify_load_timeout_reconcile(
        _requested_config(),
        _observed(_instance("instance-timeout-1", context_length=4096)),
    )

    assert decision.action == "load_unknown_or_failed"
    assert decision.status == "load_unknown_or_failed"


def test_timeout_reconcile_with_unknown_config_marks_unknown_or_failed() -> None:
    decision = classify_load_timeout_reconcile(
        _requested_config(),
        _observed(_instance("instance-timeout-unknown", context_length=None, parallel=None)),
    )

    assert decision.action == "load_unknown_or_failed"
    assert decision.status == "load_unknown_or_failed"


def test_timeout_reconcile_without_observed_state_marks_unknown_or_failed() -> None:
    decision = classify_load_timeout_reconcile(_requested_config(), None)

    assert decision.action == "load_unknown_or_failed"
    assert decision.status == "load_unknown_or_failed"


def test_timeout_reconcile_error_marks_reconcile_error() -> None:
    decision = classify_load_timeout_reconcile(
        _requested_config(),
        None,
        reconcile_error=True,
    )

    assert decision.action == "load_reconcile_error"
    assert decision.status == "load_reconcile_error"


def test_duplicate_detector_reports_duplicate_classification() -> None:
    duplicate_report = detect_duplicate_instances(
        _observed(_instance("instance-dup-1"), _instance("instance-dup-2"))
    )

    assert duplicate_report.status == "duplicate_instances"
    assert duplicate_report.instance_count == 2
    assert len(duplicate_report.instance_hashes) == 2


def test_privacy_serialization_contains_only_safe_hashes_and_policy_fields() -> None:
    raw_instance_id = "instance-secret-12345"
    endpoint_sentinel = "https://private.example/api/v1/models/load"
    decision = ensure_unloaded_decision(_observed(_instance(raw_instance_id, owned_by_policy=True)))
    duplicate_report = detect_duplicate_instances(_observed(_instance(raw_instance_id)))

    serialized = json.dumps(
        {
            "decision": asdict(decision),
            "duplicate_report": asdict(duplicate_report),
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    assert raw_instance_id not in serialized
    assert endpoint_sentinel not in serialized
    assert "/api/v1/models" not in serialized
    assert "sha256:" in serialized
