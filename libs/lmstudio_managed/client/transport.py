"""Pure transport summary DTOs with no raw request/response bodies."""

from __future__ import annotations

from dataclasses import dataclass

from .endpoint import EndpointSpec
from .errors import ApiErrorKind, SafeApiError


@dataclass(frozen=True, slots=True)
class TransportRequest:
    endpoint: EndpointSpec
    payload_kind: str | None = None
    payload_hash: str | None = None
    timeout_s: float | None = None


@dataclass(frozen=True, slots=True)
class TransportResponse:
    endpoint: EndpointSpec
    status_code: int
    body_hash: str | None
    body_chars: int | None
    schema_name: str | None = None


@dataclass(frozen=True, slots=True)
class TransportResult:
    response: TransportResponse | None = None
    error: SafeApiError | None = None

    def __post_init__(self) -> None:
        if (self.response is None) == (self.error is None):
            raise ValueError("TransportResult requires exactly one of response or error")

    @property
    def ok(self) -> bool:
        return self.response is not None

    @property
    def error_kind(self) -> ApiErrorKind | None:
        if self.error is None:
            return None
        return self.error.kind
