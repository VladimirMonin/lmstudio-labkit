"""Pure lifecycle REST contracts and verification helpers."""

from __future__ import annotations

from dataclasses import dataclass

from ..client.errors import ApiErrorKind, SafeApiError
from ..metrics.models import ParallelEvidence
from ..registry.api_models import LoadedInstanceRecord
from .policy import classify_parallel_semantics
from .state import LifecycleAction, LoadConfig


@dataclass(frozen=True, slots=True)
class LoadedInstanceIdentity:
    instance_ref: str
    model_key: str


@dataclass(frozen=True, slots=True)
class LoadModelRequest:
    model_key: str
    context_length: int | None
    parallel: int | None


@dataclass(frozen=True, slots=True)
class LoadConfigEcho:
    context_length: int | None
    parallel: int | None


@dataclass(frozen=True, slots=True)
class LoadModelResponse:
    status: LifecycleAction
    instance: LoadedInstanceIdentity | None
    echo: LoadConfigEcho | None
    error: SafeApiError | None = None


@dataclass(frozen=True, slots=True)
class UnloadModelRequest:
    instance_ref: str
    model_key: str

    def __post_init__(self) -> None:
        normalized_ref = self.instance_ref.strip().lower()
        if normalized_ref in {"", "*", "all"}:
            raise ValueError("UnloadModelRequest requires an exact instance_ref")


@dataclass(frozen=True, slots=True)
class UnloadModelResponse:
    status: LifecycleAction
    unloaded: bool
    error: SafeApiError | None = None


@dataclass(frozen=True, slots=True)
class ModelLoadVerification:
    requested: LoadConfig
    echo: LoadConfigEcho | None
    observed: LoadedInstanceRecord | None
    context_length_verified: bool
    parallel_verified: bool
    config_sufficient: bool
    failure_reason: str | None = None


def build_model_load_verification(
    requested: LoadConfig,
    *,
    echo: LoadConfigEcho | None = None,
    observed: LoadedInstanceRecord | None = None,
) -> ModelLoadVerification:
    applied_context = _applied_value(
        observed.context_length if observed else None,
        echo.context_length if echo else None,
    )
    applied_parallel = _applied_value(
        observed.parallel if observed else None,
        echo.parallel if echo else None,
    )

    context_verified, context_reason = _verify_dimension(
        requested.context_length,
        applied_context,
        name="context_length",
    )
    parallel_verified, parallel_reason = _verify_dimension(
        requested.parallel,
        applied_parallel,
        name="parallel",
    )
    failure_reason = _combine_failure_reasons(context_reason, parallel_reason)

    return ModelLoadVerification(
        requested=requested,
        echo=echo,
        observed=observed,
        context_length_verified=context_verified,
        parallel_verified=parallel_verified,
        config_sufficient=context_verified and parallel_verified,
        failure_reason=failure_reason,
    )


def validate_parallel_contract(
    configured_parallel: int | None,
    applied_parallel: int | None,
    app_concurrency: int | None,
    parallel_verified: bool,
    *,
    allow_queue_pressure: bool = False,
) -> ParallelEvidence | SafeApiError:
    if app_concurrency is None:
        return ParallelEvidence(
            configured_parallel=configured_parallel,
            applied_parallel=applied_parallel,
            parallel_verified=parallel_verified,
            app_concurrency=app_concurrency,
            queue_pressure_mode=None,
            parallel_semantics=classify_parallel_semantics(
                app_concurrency=app_concurrency,
                applied_parallel=applied_parallel,
                queue_pressure_mode=None,
            ),
        )

    effective_parallel = applied_parallel if applied_parallel is not None else configured_parallel
    if effective_parallel is not None and app_concurrency > effective_parallel:
        if not allow_queue_pressure:
            return SafeApiError(
                kind=ApiErrorKind.UNKNOWN,
                message="parallel_contract_queue_pressure",
                retryable=False,
            )
        return ParallelEvidence(
            configured_parallel=configured_parallel,
            applied_parallel=applied_parallel,
            parallel_verified=parallel_verified,
            app_concurrency=app_concurrency,
            queue_pressure_mode=True,
            parallel_semantics=classify_parallel_semantics(
                app_concurrency=app_concurrency,
                applied_parallel=effective_parallel,
                queue_pressure_mode=True,
            ),
        )

    return ParallelEvidence(
        configured_parallel=configured_parallel,
        applied_parallel=applied_parallel,
        parallel_verified=parallel_verified,
        app_concurrency=app_concurrency,
        queue_pressure_mode=False,
        parallel_semantics=classify_parallel_semantics(
            app_concurrency=app_concurrency,
            applied_parallel=applied_parallel,
            queue_pressure_mode=False,
        ),
    )


def _verify_dimension(
    requested: int | None,
    applied: int | None,
    *,
    name: str,
) -> tuple[bool, str | None]:
    if requested is None:
        return True, None
    if applied is None:
        return False, f"{name}_unverified"
    if applied < requested:
        return False, f"{name}_insufficient"
    return True, None


def _applied_value(primary: int | None, secondary: int | None) -> int | None:
    if primary is not None:
        return primary
    return secondary


def _combine_failure_reasons(*reasons: str | None) -> str | None:
    filtered = tuple(reason for reason in reasons if reason is not None)
    if not filtered:
        return None
    return "+".join(filtered)
