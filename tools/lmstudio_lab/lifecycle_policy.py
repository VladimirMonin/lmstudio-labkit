from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from libs.lmstudio_managed.lifecycle import LifecycleAction as ManagedLifecycleAction
from libs.lmstudio_managed.lifecycle import LoadConfig as ManagedLoadConfig
from libs.lmstudio_managed.lifecycle import LoadedInstance as ManagedLoadedInstance
from libs.lmstudio_managed.lifecycle import ObservedModelState as ManagedObservedModelState
from libs.lmstudio_managed.lifecycle import (
    classify_load_timeout_reconcile as managed_classify_load_timeout_reconcile,
)
from libs.lmstudio_managed.lifecycle import (
    decide_lifecycle_action as managed_decide_lifecycle_action,
)
from libs.lmstudio_managed.lifecycle import decide_unload_action as managed_decide_unload_action


@dataclass(frozen=True, slots=True)
class LoadConfig:
    model_key: str
    context_length: int
    parallel: int


@dataclass(frozen=True, slots=True)
class LoadedInstanceRef:
    instance_hash: str
    model_key: str
    context_length: int | None
    parallel: int | None
    owned_by_policy: bool = False

    def has_known_config(self) -> bool:
        return self.context_length is not None and self.parallel is not None

    def matches_config(self, requested: LoadConfig) -> bool:
        return (
            self.model_key == requested.model_key
            and self.context_length == requested.context_length
            and self.parallel == requested.parallel
        )


@dataclass(frozen=True, slots=True)
class ObservedModelState:
    model_key: str
    loaded_instances: tuple[LoadedInstanceRef, ...] = ()

    @classmethod
    def from_loaded_instances(
        cls,
        model_key: str,
        loaded_instances: Sequence[LoadedInstanceRef],
    ) -> ObservedModelState:
        return cls(model_key=model_key, loaded_instances=tuple(loaded_instances))


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    action: str
    status: str
    reason: str
    may_load: bool = False
    may_unload: bool = False
    target_hashes: tuple[str, ...] = ()
    observed_instance_hashes: tuple[str, ...] = ()
    observed_instance_count: int = 0
    owned_instance_count: int = 0
    external_instance_count: int = 0
    requested_config: LoadConfig | None = None


@dataclass(frozen=True, slots=True)
class DuplicateInstanceReport:
    status: str
    reason: str
    model_key: str
    instance_count: int
    instance_hashes: tuple[str, ...] = ()


def _require_same_model(requested_model_key: str, observed: ObservedModelState) -> None:
    if observed.model_key != requested_model_key:
        raise ValueError("requested and observed model keys must match")


def _sorted_hashes(instances: Sequence[LoadedInstanceRef]) -> tuple[str, ...]:
    return tuple(sorted(instance.instance_hash for instance in instances))


def _to_managed_load_config(config: LoadConfig) -> ManagedLoadConfig:
    return ManagedLoadConfig(
        model_key=config.model_key,
        context_length=config.context_length,
        parallel=config.parallel,
    )


def _to_managed_loaded_instance(instance: LoadedInstanceRef) -> ManagedLoadedInstance:
    return ManagedLoadedInstance(
        instance_ref=instance.instance_hash,
        model_key=instance.model_key,
        config=ManagedLoadConfig(
            model_key=instance.model_key,
            context_length=instance.context_length,
            parallel=instance.parallel,
        ),
        owned_by_us=instance.owned_by_policy,
    )


def _to_managed_observed_state(observed: ObservedModelState) -> ManagedObservedModelState:
    return ManagedObservedModelState(
        instances=tuple(
            _to_managed_loaded_instance(instance) for instance in observed.loaded_instances
        )
    )


def ensure_loaded_decision(
    requested_config: LoadConfig,
    observed_state: ObservedModelState,
) -> LifecycleDecision:
    _require_same_model(requested_config.model_key, observed_state)
    loaded_instances = observed_state.loaded_instances
    observed_hashes = _sorted_hashes(loaded_instances)

    if len(loaded_instances) == 1 and not loaded_instances[0].has_known_config():
        return LifecycleDecision(
            action="config_unknown",
            status="config_unknown",
            reason="loaded instance config is incomplete; blind native load is unsafe",
            observed_instance_hashes=observed_hashes,
            observed_instance_count=1,
            requested_config=requested_config,
        )

    managed_decision = managed_decide_lifecycle_action(
        _to_managed_observed_state(observed_state),
        _to_managed_load_config(requested_config),
    )

    if managed_decision.action == ManagedLifecycleAction.LOAD:
        return LifecycleDecision(
            action="load_required",
            status="load_required",
            reason="no loaded instance observed for requested model",
            may_load=True,
            observed_instance_count=0,
            requested_config=requested_config,
        )

    if managed_decision.action == ManagedLifecycleAction.FAIL_DUPLICATE:
        return LifecycleDecision(
            action="duplicate_instances",
            status="duplicate_instances",
            reason="multiple loaded instances observed; blind native load is unsafe",
            observed_instance_hashes=observed_hashes,
            observed_instance_count=len(loaded_instances),
            requested_config=requested_config,
        )

    if managed_decision.action == ManagedLifecycleAction.NOOP:
        return LifecycleDecision(
            action="reuse_existing",
            status="reuse_existing",
            reason="loaded instance already matches the requested config",
            observed_instance_hashes=observed_hashes,
            observed_instance_count=1,
            requested_config=requested_config,
        )

    if managed_decision.action == ManagedLifecycleAction.CONFIG_INSUFFICIENT:
        return LifecycleDecision(
            action="config_conflict",
            status="config_conflict",
            reason="loaded instance config differs from the requested config",
            observed_instance_hashes=observed_hashes,
            observed_instance_count=1,
            requested_config=requested_config,
        )

    if managed_decision.action == ManagedLifecycleAction.UNLOAD_EXACT:
        return LifecycleDecision(
            action="config_conflict",
            status="config_conflict",
            reason="loaded instance config differs from the requested config",
            observed_instance_hashes=observed_hashes,
            observed_instance_count=len(loaded_instances),
            requested_config=requested_config,
        )

    raise ValueError(
        f"unexpected managed lifecycle action for ensure_loaded_decision: {managed_decision.action}"
    )


def ensure_unloaded_decision(observed_state: ObservedModelState) -> LifecycleDecision:
    loaded_instances = observed_state.loaded_instances
    observed_hashes = _sorted_hashes(loaded_instances)
    owned_instances = tuple(instance for instance in loaded_instances if instance.owned_by_policy)
    external_instances = tuple(
        instance for instance in loaded_instances if not instance.owned_by_policy
    )
    owned_hashes = _sorted_hashes(owned_instances)

    if external_instances:
        if not owned_instances:
            return LifecycleDecision(
                action="external_instances_present",
                status="external_instances_present",
                reason="only external instances are present; do not unload without explicit policy",
                observed_instance_hashes=observed_hashes,
                observed_instance_count=len(loaded_instances),
                external_instance_count=len(external_instances),
            )

        return LifecycleDecision(
            action="cleanup_required",
            status="cleanup_required",
            reason="owned instances may be cleaned up, but external instances must remain untouched",
            may_unload=True,
            target_hashes=owned_hashes,
            observed_instance_hashes=observed_hashes,
            observed_instance_count=len(loaded_instances),
            owned_instance_count=len(owned_instances),
            external_instance_count=len(external_instances),
        )

    managed_decision = managed_decide_unload_action(
        _to_managed_observed_state(observed_state),
        observed_state.model_key,
    )

    if managed_decision.action == ManagedLifecycleAction.ALREADY_UNLOADED:
        return LifecycleDecision(
            action="already_unloaded",
            status="already_unloaded",
            reason="no loaded instance observed for requested model",
        )

    if managed_decision.action == ManagedLifecycleAction.DO_NOT_TOUCH:
        return LifecycleDecision(
            action="external_instances_present",
            status="external_instances_present",
            reason="only external instances are present; do not unload without explicit policy",
            observed_instance_hashes=observed_hashes,
            observed_instance_count=len(loaded_instances),
            external_instance_count=len(external_instances),
        )

    if managed_decision.action == ManagedLifecycleAction.UNLOAD_EXACT:
        return LifecycleDecision(
            action="unload_required",
            status="unload_required",
            reason="owned instance should be unloaded by exact hash",
            may_unload=True,
            target_hashes=owned_hashes,
            observed_instance_hashes=observed_hashes,
            observed_instance_count=len(loaded_instances),
            owned_instance_count=len(owned_instances),
        )

    if managed_decision.action == ManagedLifecycleAction.CLEANUP_EXACT_EACH:
        return LifecycleDecision(
            action="cleanup_required",
            status="cleanup_required",
            reason="multiple owned instances require exact-hash cleanup",
            may_unload=True,
            target_hashes=owned_hashes,
            observed_instance_hashes=observed_hashes,
            observed_instance_count=len(loaded_instances),
            owned_instance_count=len(owned_instances),
        )

    raise ValueError(
        f"unexpected managed unload action for ensure_unloaded_decision: {managed_decision.action}"
    )


def classify_load_timeout_reconcile(
    requested_config: LoadConfig,
    observed_state: ObservedModelState | None,
    *,
    reconcile_error: bool = False,
) -> LifecycleDecision:
    if reconcile_error:
        return LifecycleDecision(
            action="load_reconcile_error",
            status="load_reconcile_error",
            reason="load timed out and reconcile state could not be read",
            requested_config=requested_config,
        )

    if observed_state is None:
        return LifecycleDecision(
            action="load_unknown_or_failed",
            status="load_unknown_or_failed",
            reason="load timed out and no reconcile state is available",
            requested_config=requested_config,
        )

    _require_same_model(requested_config.model_key, observed_state)
    observed_hashes = _sorted_hashes(observed_state.loaded_instances)
    known_config_instances = tuple(
        instance for instance in observed_state.loaded_instances if instance.has_known_config()
    )
    managed_decision = managed_classify_load_timeout_reconcile(
        _to_managed_observed_state(
            ObservedModelState.from_loaded_instances(
                observed_state.model_key, known_config_instances
            )
        ),
        _to_managed_load_config(requested_config),
    )

    if managed_decision.action == ManagedLifecycleAction.LOAD_RECONCILE_OK:
        return LifecycleDecision(
            action="load_succeeded_but_response_lost",
            status="load_succeeded_but_response_lost",
            reason="load timed out, but reconcile saw a matching loaded instance",
            observed_instance_hashes=observed_hashes,
            observed_instance_count=len(observed_state.loaded_instances),
            requested_config=requested_config,
        )

    if managed_decision.action == ManagedLifecycleAction.LOAD_RECONCILE_FAILED:
        return LifecycleDecision(
            action="load_unknown_or_failed",
            status="load_unknown_or_failed",
            reason="load timed out and reconcile found no matching loaded instance",
            observed_instance_hashes=observed_hashes,
            observed_instance_count=len(observed_state.loaded_instances),
            requested_config=requested_config,
        )

    raise ValueError(
        "unexpected managed reconcile action for classify_load_timeout_reconcile: "
        f"{managed_decision.action}"
    )


def detect_duplicate_instances(observed_state: ObservedModelState) -> DuplicateInstanceReport:
    loaded_instances = observed_state.loaded_instances
    instance_hashes = _sorted_hashes(loaded_instances)
    instance_count = len(loaded_instances)

    if instance_count == 0:
        return DuplicateInstanceReport(
            status="none",
            reason="no loaded instances observed",
            model_key=observed_state.model_key,
            instance_count=0,
            instance_hashes=(),
        )

    if instance_count == 1:
        return DuplicateInstanceReport(
            status="single",
            reason="exactly one loaded instance observed",
            model_key=observed_state.model_key,
            instance_count=1,
            instance_hashes=instance_hashes,
        )

    return DuplicateInstanceReport(
        status="duplicate_instances",
        reason="multiple loaded instances observed for the same model",
        model_key=observed_state.model_key,
        instance_count=instance_count,
        instance_hashes=instance_hashes,
    )


__all__ = [
    "DuplicateInstanceReport",
    "LifecycleDecision",
    "LoadConfig",
    "LoadedInstanceRef",
    "ObservedModelState",
    "classify_load_timeout_reconcile",
    "detect_duplicate_instances",
    "ensure_loaded_decision",
    "ensure_unloaded_decision",
]
