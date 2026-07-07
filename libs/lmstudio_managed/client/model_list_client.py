"""Fake-first model-list client over an injected JSON transport seam."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..registry import ModelListResponse, parse_compat_model_list, parse_native_model_list
from .endpoint import EndpointKind, EndpointSpec, HttpMethod
from .errors import ApiErrorKind, SafeApiError
from .rest_client import (
    _build_transport_request,
    _coerce_json_result,
    _JsonTransportProtocol,
    _transport_exception_result,
)

_COMPAT_MODELS_ENDPOINT = EndpointSpec(
    kind=EndpointKind.COMPAT_MODELS,
    method=HttpMethod.GET,
    privacy_label="compat_models",
)
_NATIVE_MODELS_ENDPOINT = EndpointSpec(
    kind=EndpointKind.NATIVE_MODELS,
    method=HttpMethod.GET,
    privacy_label="native_models",
)


class ModelListClient:
    """Privacy-safe model-list client for compat/native LM Studio endpoints."""

    __slots__ = ("_transport", "_default_timeout_s")

    def __init__(
        self,
        transport: _JsonTransportProtocol,
        *,
        default_timeout_s: float | None = None,
    ) -> None:
        self._transport = transport
        self._default_timeout_s = default_timeout_s

    def list_compat_models(self, timeout_s: float | None = None) -> ModelListResponse:
        return self._list_models(
            endpoint=_COMPAT_MODELS_ENDPOINT,
            parser=parse_compat_model_list,
            timeout_s=timeout_s,
        )

    def list_native_models(self, timeout_s: float | None = None) -> ModelListResponse:
        return self._list_models(
            endpoint=_NATIVE_MODELS_ENDPOINT,
            parser=parse_native_model_list,
            timeout_s=timeout_s,
        )

    def _list_models(
        self,
        *,
        endpoint: EndpointSpec,
        parser: Callable[[Mapping[str, object]], ModelListResponse],
        timeout_s: float | None,
    ) -> ModelListResponse:
        request = _build_transport_request(
            endpoint,
            payload_kind="model_list",
            timeout_s=timeout_s,
            default_timeout_s=self._default_timeout_s,
        )

        try:
            raw_result = self._transport(request)
        except Exception as error:
            return self._response_from_transport_error(
                endpoint.kind,
                _transport_exception_result(error).error,
            )

        transport_result, payload = _coerce_json_result(raw_result)
        if transport_result is None:
            return self._error_response(
                endpoint.kind,
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="transport_unexpected_schema",
                retryable=False,
            )

        if not transport_result.ok:
            return self._response_from_transport_error(endpoint.kind, transport_result.error)

        if not isinstance(payload, Mapping):
            return self._error_response(
                endpoint.kind,
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="model_list_unexpected_schema",
                retryable=False,
            )

        return parser(payload)

    @classmethod
    def _response_from_transport_error(
        cls,
        endpoint_kind: EndpointKind,
        error: SafeApiError | None,
    ) -> ModelListResponse:
        if error is None:
            return cls._error_response(
                endpoint_kind,
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="transport_unexpected_schema",
                retryable=False,
            )
        return ModelListResponse(
            endpoint_kind=endpoint_kind,
            visible_models=(),
            native_models=(),
            error=SafeApiError(
                kind=error.kind,
                message=error.message,
                status_code=error.status_code,
                retryable=error.retryable,
            ),
        )

    @staticmethod
    def _error_response(
        endpoint_kind: EndpointKind,
        *,
        kind: ApiErrorKind,
        message: str,
        retryable: bool,
    ) -> ModelListResponse:
        return ModelListResponse(
            endpoint_kind=endpoint_kind,
            visible_models=(),
            native_models=(),
            error=SafeApiError(
                kind=kind,
                message=message,
                retryable=retryable,
            ),
        )
