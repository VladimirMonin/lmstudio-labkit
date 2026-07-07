"""Pure lifecycle state contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ParallelSemantics(StrEnum):
    SEQUENTIAL = "sequential"
    TRUE_PARALLEL = "true_parallel"
    QUEUE_PRESSURE = "queue_pressure"
    OVERBOOKED_STRESS = "overbooked_stress"
    UNKNOWN = "unknown"


class LifecycleAction(StrEnum):
    NOOP = "noop"
    LOAD = "load"
    UNLOAD_EXACT = "unload_exact"
    ALREADY_UNLOADED = "already_unloaded"
    CLEANUP_EXACT_EACH = "cleanup_exact_each"
    DO_NOT_TOUCH = "do_not_touch"
    CONFIG_INSUFFICIENT = "config_insufficient"
    LOAD_RECONCILE_OK = "load_reconcile_ok"
    LOAD_RECONCILE_FAILED = "load_reconcile_failed"
    LOAD_RECONCILE_ERROR = "load_reconcile_error"
    RECONCILE = "reconcile"
    FAIL_DUPLICATE = "fail_duplicate"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class LoadConfig:
    model_key: str
    context_length: int | None = None
    parallel: int | None = None


@dataclass(frozen=True, slots=True)
class LoadedInstance:
    instance_ref: str
    model_key: str
    config: LoadConfig
    owned_by_us: bool = True


@dataclass(frozen=True, slots=True)
class ObservedModelState:
    instances: tuple[LoadedInstance, ...] = ()

    def __iter__(self):
        return iter(self.instances)

    def __len__(self) -> int:
        return len(self.instances)

    @property
    def first_instance(self) -> LoadedInstance | None:
        if not self.instances:
            return None
        return self.instances[0]

    def instances_for_model(self, model_key: str) -> tuple[LoadedInstance, ...]:
        return tuple(instance for instance in self.instances if instance.model_key == model_key)

    def has_other_model_loaded(self, model_key: str) -> bool:
        return any(instance.model_key != model_key for instance in self.instances)


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    action: LifecycleAction
    reason: str
    target_instance_ref: str | None = None
    target_instance_refs: tuple[str, ...] = ()
    load_config: LoadConfig | None = None
