"""Side-effect-free lifecycle policy helpers."""

from __future__ import annotations

from .state import (
    LifecycleAction,
    LifecycleDecision,
    LoadConfig,
    LoadedInstance,
    ObservedModelState,
    ParallelSemantics,
)


def classify_parallel_semantics(
    app_concurrency: int | None,
    applied_parallel: int | None,
    queue_pressure_mode: bool | None,
) -> ParallelSemantics:
    if app_concurrency is None:
        return ParallelSemantics.UNKNOWN
    if queue_pressure_mode is True:
        return ParallelSemantics.QUEUE_PRESSURE
    if app_concurrency == 1:
        return ParallelSemantics.SEQUENTIAL
    if applied_parallel is not None and app_concurrency > applied_parallel:
        return ParallelSemantics.OVERBOOKED_STRESS
    if applied_parallel is not None and app_concurrency == applied_parallel and app_concurrency > 1:
        return ParallelSemantics.TRUE_PARALLEL
    return ParallelSemantics.UNKNOWN


def decide_lifecycle_action(
    observed: ObservedModelState,
    requested: LoadConfig,
    *,
    single_model_safe: bool = True,
) -> LifecycleDecision:
    matching_instances = observed.instances_for_model(requested.model_key)

    if len(matching_instances) > 1:
        return LifecycleDecision(
            action=LifecycleAction.FAIL_DUPLICATE,
            reason="duplicate_loaded_instances",
        )

    if matching_instances:
        matching_instance = matching_instances[0]
        if _is_compatible(matching_instance, requested):
            return LifecycleDecision(
                action=LifecycleAction.NOOP,
                reason="reuse_loaded_instance",
            )
        return LifecycleDecision(
            action=LifecycleAction.CONFIG_INSUFFICIENT,
            reason="loaded_config_insufficient",
            target_instance_ref=matching_instance.instance_ref,
        )

    first_instance = observed.first_instance
    if first_instance is None:
        return LifecycleDecision(
            action=LifecycleAction.LOAD,
            reason="not_loaded",
            load_config=requested,
        )

    if (
        single_model_safe
        and observed.has_other_model_loaded(requested.model_key)
        and first_instance
    ):
        return LifecycleDecision(
            action=LifecycleAction.UNLOAD_EXACT,
            reason="single_model_safe_swap",
            target_instance_ref=first_instance.instance_ref,
        )

    return LifecycleDecision(
        action=LifecycleAction.LOAD,
        reason="not_loaded",
        load_config=requested,
    )


def decide_unload_action(
    observed: ObservedModelState,
    model_key: str,
    *,
    owned_only: bool = True,
) -> LifecycleDecision:
    matching_instances = observed.instances_for_model(model_key)
    if not matching_instances:
        return LifecycleDecision(
            action=LifecycleAction.ALREADY_UNLOADED,
            reason="already_unloaded",
        )

    if owned_only:
        candidates = tuple(instance for instance in matching_instances if instance.owned_by_us)
        if not candidates:
            return LifecycleDecision(
                action=LifecycleAction.DO_NOT_TOUCH,
                reason="external_instance_not_owned",
            )
        if len(candidates) > 1:
            return LifecycleDecision(
                action=LifecycleAction.CLEANUP_EXACT_EACH,
                reason="multiple_owned_instances",
                target_instance_refs=tuple(instance.instance_ref for instance in candidates),
            )
        return LifecycleDecision(
            action=LifecycleAction.UNLOAD_EXACT,
            reason="owned_instance_present",
            target_instance_ref=candidates[0].instance_ref,
        )

    if len(matching_instances) > 1:
        return LifecycleDecision(
            action=LifecycleAction.CLEANUP_EXACT_EACH,
            reason="multiple_matching_instances",
            target_instance_refs=tuple(instance.instance_ref for instance in matching_instances),
        )

    return LifecycleDecision(
        action=LifecycleAction.UNLOAD_EXACT,
        reason="matching_instance_present",
        target_instance_ref=matching_instances[0].instance_ref,
    )


def classify_load_timeout_reconcile(
    observed: ObservedModelState,
    requested: LoadConfig,
    *,
    list_error: bool = False,
) -> LifecycleDecision:
    if list_error:
        return LifecycleDecision(
            action=LifecycleAction.LOAD_RECONCILE_ERROR,
            reason="load_reconcile_error",
        )

    compatible_instances = tuple(
        instance
        for instance in observed.instances_for_model(requested.model_key)
        if _is_compatible(instance, requested)
    )
    if compatible_instances:
        return LifecycleDecision(
            action=LifecycleAction.LOAD_RECONCILE_OK,
            reason="load_succeeded_but_response_lost",
            target_instance_ref=compatible_instances[0].instance_ref,
        )

    return LifecycleDecision(
        action=LifecycleAction.LOAD_RECONCILE_FAILED,
        reason="load_unknown_or_failed",
    )


def _is_compatible(instance: LoadedInstance, requested: LoadConfig) -> bool:
    return _context_length_is_compatible(
        instance.config,
        requested,
    ) and _parallel_is_compatible(
        instance.config,
        requested,
    )


def _context_length_is_compatible(loaded: LoadConfig, requested: LoadConfig) -> bool:
    if loaded.context_length is None or requested.context_length is None:
        return True
    return loaded.context_length >= requested.context_length


def _parallel_is_compatible(loaded: LoadConfig, requested: LoadConfig) -> bool:
    if loaded.parallel is None or requested.parallel is None:
        return True
    return loaded.parallel >= requested.parallel
