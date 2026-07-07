"""Fake-first lifecycle client over an injected JSON transport seam."""

from __future__ import annotations

from collections.abc import Mapping

from .._safe import as_int, as_str, safe_hash_ref
from ..lifecycle import (
    LifecycleAction,
    LoadConfigEcho,
    LoadedInstanceIdentity,
    LoadModelRequest,
    LoadModelResponse,
    UnloadModelRequest,
    UnloadModelResponse,
)
from ..registry import ModelListResponse, parse_native_model_list
from .endpoint import EndpointKind, EndpointSpec, HttpMethod
from .errors import ApiErrorKind, SafeApiError
from .rest_client import (
    _build_transport_request,
    _coerce_json_result,
    _JsonTransportProtocol,
    _transport_exception_result,
)

_NATIVE_LOAD_ENDPOINT = EndpointSpec(
    kind=EndpointKind.NATIVE_LOAD,
    method=HttpMethod.POST,
    privacy_label="native_load",
)
_NATIVE_UNLOAD_ENDPOINT = EndpointSpec(
    kind=EndpointKind.NATIVE_UNLOAD,
    method=HttpMethod.POST,
    privacy_label="native_unload",
)
_NATIVE_MODELS_ENDPOINT = EndpointSpec(
    kind=EndpointKind.NATIVE_MODELS,
    method=HttpMethod.GET,
    privacy_label="native_models",
)

_LOAD_OK_VALUES = frozenset({"loaded", "load", "ok", "success"})
_UNLOAD_OK_VALUES = frozenset({"unloaded", "unload_exact", "ok", "success"})
_UNLOAD_IDENTIFIER_ALIASES = frozenset(
    {"instance_ref", "instanceRef", "instance_id", "instanceId", "id"}
)


class LifecycleClient:
    """Privacy-safe lifecycle client for native LM Studio lifecycle endpoints."""

    __slots__ = ("_transport", "_default_timeout_s")

    def __init__(
        self,
        transport: _JsonTransportProtocol,
        *,
        default_timeout_s: float | None = None,
    ) -> None:
        self._transport = transport
        self._default_timeout_s = default_timeout_s

    def load_model(
        self,
        request: LoadModelRequest,
        timeout_s: float | None = None,
    ) -> LoadModelResponse:
        transport_request = _build_transport_request(
            _NATIVE_LOAD_ENDPOINT,
            payload_kind="load_model",
            payload_hash=_load_request_hash(request),
            timeout_s=timeout_s,
            default_timeout_s=self._default_timeout_s,
        )

        try:
            raw_result = self._transport(transport_request)
        except Exception as error:
            return self._load_response_from_transport_error(
                _transport_exception_result(error).error,
            )

        transport_result, payload = _coerce_json_result(raw_result)
        if transport_result is None:
            return self._load_error_response(
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="transport_unexpected_schema",
                retryable=False,
            )

        if not transport_result.ok:
            return self._load_response_from_transport_error(transport_result.error)

        if not isinstance(payload, Mapping):
            return self._load_error_response(
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="load_model_unexpected_schema",
                retryable=False,
            )

        return _parse_load_response(payload, request)

    def unload_instance(
        self,
        request: UnloadModelRequest,
        timeout_s: float | None = None,
    ) -> UnloadModelResponse:
        transport_request = _build_transport_request(
            _NATIVE_UNLOAD_ENDPOINT,
            payload_kind="unload_model",
            payload_hash=_unload_request_hash(request),
            timeout_s=timeout_s,
            default_timeout_s=self._default_timeout_s,
        )

        try:
            raw_result = self._transport(transport_request)
        except Exception as error:
            return self._unload_response_from_transport_error(
                _transport_exception_result(error).error,
            )

        transport_result, payload = _coerce_json_result(raw_result)
        if transport_result is None:
            return self._unload_error_response(
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="transport_unexpected_schema",
                retryable=False,
            )

        if not transport_result.ok:
            return self._unload_response_from_transport_error(transport_result.error)

        if not isinstance(payload, Mapping):
            return self._unload_error_response(
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="unload_model_unexpected_schema",
                retryable=False,
            )

        return _parse_unload_response(payload)

    def list_loaded_instances(self, timeout_s: float | None = None) -> ModelListResponse:
        transport_request = _build_transport_request(
            _NATIVE_MODELS_ENDPOINT,
            payload_kind="model_list",
            timeout_s=timeout_s,
            default_timeout_s=self._default_timeout_s,
        )

        try:
            raw_result = self._transport(transport_request)
        except Exception as error:
            return self._model_list_response_from_transport_error(
                _transport_exception_result(error).error,
            )

        transport_result, payload = _coerce_json_result(raw_result)
        if transport_result is None:
            return self._model_list_error_response(
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="transport_unexpected_schema",
                retryable=False,
            )

        if not transport_result.ok:
            return self._model_list_response_from_transport_error(transport_result.error)

        if not isinstance(payload, Mapping):
            return self._model_list_error_response(
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="model_list_unexpected_schema",
                retryable=False,
            )

        return parse_native_model_list(payload)

    @classmethod
    def _load_response_from_transport_error(
        cls,
        error: SafeApiError | None,
    ) -> LoadModelResponse:
        if error is None:
            return cls._load_error_response(
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="transport_unexpected_schema",
                retryable=False,
            )
        return cls._load_error_response(
            kind=error.kind,
            message=error.message,
            retryable=error.retryable,
            status_code=error.status_code,
        )

    @classmethod
    def _unload_response_from_transport_error(
        cls,
        error: SafeApiError | None,
    ) -> UnloadModelResponse:
        if error is None:
            return cls._unload_error_response(
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="transport_unexpected_schema",
                retryable=False,
            )
        return cls._unload_error_response(
            kind=error.kind,
            message=error.message,
            retryable=error.retryable,
            status_code=error.status_code,
        )

    @classmethod
    def _model_list_response_from_transport_error(
        cls,
        error: SafeApiError | None,
    ) -> ModelListResponse:
        if error is None:
            return cls._model_list_error_response(
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="transport_unexpected_schema",
                retryable=False,
            )
        return cls._model_list_error_response(
            kind=error.kind,
            message=error.message,
            retryable=error.retryable,
            status_code=error.status_code,
        )

    @staticmethod
    def _load_error_response(
        *,
        kind: ApiErrorKind,
        message: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> LoadModelResponse:
        return LoadModelResponse(
            status=LifecycleAction.LOAD_RECONCILE_ERROR,
            instance=None,
            echo=None,
            error=SafeApiError(
                kind=kind,
                message=message,
                status_code=status_code,
                retryable=retryable,
            ),
        )

    @staticmethod
    def _unload_error_response(
        *,
        kind: ApiErrorKind,
        message: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> UnloadModelResponse:
        return UnloadModelResponse(
            status=LifecycleAction.DO_NOT_TOUCH,
            unloaded=False,
            error=SafeApiError(
                kind=kind,
                message=message,
                status_code=status_code,
                retryable=retryable,
            ),
        )

    @staticmethod
    def _model_list_error_response(
        *,
        kind: ApiErrorKind,
        message: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> ModelListResponse:
        return ModelListResponse(
            endpoint_kind=EndpointKind.NATIVE_MODELS,
            visible_models=(),
            native_models=(),
            error=SafeApiError(
                kind=kind,
                message=message,
                status_code=status_code,
                retryable=retryable,
            ),
        )


def _parse_load_response(
    payload: Mapping[str, object],
    request: LoadModelRequest,
) -> LoadModelResponse:
    normalized_status = _normalized_status(payload)
    if normalized_status not in _LOAD_OK_VALUES:
        return LoadModelResponse(
            status=LifecycleAction.LOAD_RECONCILE_ERROR,
            instance=None,
            echo=None,
            error=SafeApiError(
                kind=ApiErrorKind.PROVIDER_ERROR,
                message="load_model_failed",
                retryable=False,
            ),
        )

    instance_mapping = _first_mapping(payload, "instance")
    raw_instance_ref = _first_str(
        instance_mapping or payload,
        "instance_ref",
        "instanceRef",
        "instance_id",
        "instanceId",
        "id",
    )
    instance_ref = safe_hash_ref(raw_instance_ref)
    model_key = (
        _first_str(
            instance_mapping or payload,
            "model_key",
            "modelKey",
        )
        or _first_str(payload, "model_key", "modelKey")
        or request.model_key
    )
    instance = None
    if instance_ref is not None:
        instance = LoadedInstanceIdentity(instance_ref=instance_ref, model_key=model_key)

    return LoadModelResponse(
        status=LifecycleAction.LOAD_RECONCILE_OK,
        instance=instance,
        echo=_parse_load_echo(payload),
    )


def _parse_unload_response(payload: Mapping[str, object]) -> UnloadModelResponse:
    if not payload:
        return UnloadModelResponse(
            status=LifecycleAction.UNLOAD_EXACT,
            unloaded=True,
        )
    normalized_status = _normalized_status(payload)
    if normalized_status in _UNLOAD_OK_VALUES:
        return UnloadModelResponse(
            status=LifecycleAction.UNLOAD_EXACT,
            unloaded=True,
        )
    if normalized_status == LifecycleAction.ALREADY_UNLOADED.value:
        return UnloadModelResponse(
            status=LifecycleAction.ALREADY_UNLOADED,
            unloaded=True,
        )
    if normalized_status is None and _is_identifier_only_unload_success_payload(payload):
        return UnloadModelResponse(
            status=LifecycleAction.UNLOAD_EXACT,
            unloaded=True,
        )
    return UnloadModelResponse(
        status=LifecycleAction.DO_NOT_TOUCH,
        unloaded=False,
        error=SafeApiError(
            kind=ApiErrorKind.PROVIDER_ERROR,
            message="unload_model_failed",
            retryable=False,
        ),
    )


def _parse_load_echo(payload: Mapping[str, object]) -> LoadConfigEcho | None:
    echo_mapping = _first_mapping(
        payload,
        "echo_load_config",
        "echoLoadConfig",
        "load_config",
    )
    mapping = echo_mapping or payload
    context_length = _first_int(
        mapping,
        "context_length",
        "contextLength",
    )
    parallel = _first_int(
        mapping,
        "parallel",
        "n_parallel",
        "numParallelSequences",
    )
    if context_length is None and parallel is None:
        return None
    return LoadConfigEcho(context_length=context_length, parallel=parallel)


def _normalized_status(payload: Mapping[str, object]) -> str | None:
    value = _first_str(payload, "status", "action")
    if value is None:
        return None
    return value.lower().strip()


def _load_request_hash(request: LoadModelRequest) -> str:
    return (
        safe_hash_ref(
            f"{request.model_key}:{request.context_length}:{request.parallel}",
        )
        or ""
    )


def _unload_request_hash(request: UnloadModelRequest) -> str:
    safe_instance_ref = safe_hash_ref(request.instance_ref) or request.instance_ref
    return safe_hash_ref(f"unload:{safe_instance_ref}:{request.model_key}") or ""


def _is_identifier_only_unload_success_payload(payload: Mapping[str, object]) -> bool:
    if not payload or not frozenset(payload).issubset(_UNLOAD_IDENTIFIER_ALIASES):
        return False
    return _first_str(payload, *_UNLOAD_IDENTIFIER_ALIASES) is not None


def _first_mapping(
    mapping: Mapping[str, object],
    *keys: str,
) -> Mapping[str, object] | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _first_str(mapping: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = as_str(mapping.get(key))
        if value is not None:
            return value
    return None


def _first_int(mapping: Mapping[str, object], *keys: str) -> int | None:
    for key in keys:
        value = as_int(mapping.get(key))
        if value is not None:
            return value
    return None
