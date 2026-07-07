"""Fake-first REST client seam with privacy-safe transport error mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .endpoint import EndpointSpec
from .errors import ApiErrorKind, SafeApiError
from .transport import TransportRequest, TransportResult

_MISSING = object()


def _build_transport_request(
    endpoint: EndpointSpec,
    *,
    payload_kind: str | None = None,
    payload_hash: str | None = None,
    timeout_s: float | None = None,
    default_timeout_s: float | None = None,
) -> TransportRequest:
    return TransportRequest(
        endpoint=endpoint,
        payload_kind=payload_kind,
        payload_hash=payload_hash,
        timeout_s=_resolve_timeout(timeout_s, default_timeout_s),
    )


def _transport_exception_result(error: Exception) -> TransportResult:
    if isinstance(error, TimeoutError):
        return _error_result(
            kind=ApiErrorKind.TIMEOUT,
            message="request_timeout",
            retryable=True,
        )
    if isinstance(error, OSError):
        return _error_result(
            kind=ApiErrorKind.NETWORK,
            message="network_error",
            retryable=True,
        )
    return _error_result(
        kind=ApiErrorKind.UNKNOWN,
        message="transport_error",
        retryable=False,
    )


def _resolve_timeout(
    timeout_s: float | None,
    default_timeout_s: float | None,
) -> float | None:
    if timeout_s is not None:
        return timeout_s
    return default_timeout_s


def _error_result(
    *,
    kind: ApiErrorKind,
    message: str,
    retryable: bool,
) -> TransportResult:
    return TransportResult(
        error=SafeApiError(
            kind=kind,
            message=message,
            retryable=retryable,
        )
    )


@dataclass(frozen=True, slots=True)
class _JsonTransportResult:
    transport_result: TransportResult
    payload: object | None = None


class _JsonTransportProtocol(Protocol):
    def __call__(self, request: TransportRequest, /) -> _JsonTransportResult | object:
        """Execute a transport request and return safe JSON envelope data."""


def _coerce_json_result(raw_result: object) -> tuple[TransportResult | None, object]:
    transport_result = getattr(raw_result, "transport_result", None)
    payload = getattr(raw_result, "payload", _MISSING)
    if not isinstance(transport_result, TransportResult) or payload is _MISSING:
        return None, _MISSING
    return transport_result, payload


class TransportProtocol(Protocol):
    def __call__(self, request: TransportRequest, /) -> TransportResult:
        """Execute a transport request and return a safe transport result."""


class RestClient:
    """Small REST client wrapper over an injected safe transport callable."""

    __slots__ = ("_transport", "_default_timeout_s")

    def __init__(
        self,
        transport: TransportProtocol,
        *,
        default_timeout_s: float | None = None,
    ) -> None:
        self._transport = transport
        self._default_timeout_s = default_timeout_s

    @property
    def default_timeout_s(self) -> float | None:
        return self._default_timeout_s

    def request(
        self,
        endpoint: EndpointSpec,
        *,
        payload_kind: str | None = None,
        payload_hash: str | None = None,
        timeout_s: float | None = None,
    ) -> TransportResult:
        request = _build_transport_request(
            endpoint,
            payload_kind=payload_kind,
            payload_hash=payload_hash,
            timeout_s=timeout_s,
            default_timeout_s=self._default_timeout_s,
        )

        try:
            result = self._transport(request)
        except Exception as error:
            return _transport_exception_result(error)

        if not isinstance(result, TransportResult):
            return _error_result(
                kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                message="transport_unexpected_schema",
                retryable=False,
            )
        return result

    def _resolve_timeout(self, timeout_s: float | None) -> float | None:
        return _resolve_timeout(timeout_s, self._default_timeout_s)

    @staticmethod
    def _error_result(
        *,
        kind: ApiErrorKind,
        message: str,
        retryable: bool,
    ) -> TransportResult:
        return _error_result(kind=kind, message=message, retryable=retryable)
