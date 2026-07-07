"""Safe API error contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ApiErrorKind(StrEnum):
    NETWORK = "network"
    TIMEOUT = "timeout"
    HTTP_STATUS = "http_status"
    UNEXPECTED_SCHEMA = "unexpected_schema"
    AUTH_REQUIRED = "auth_required"
    DISK_FULL = "disk_full"
    PROVIDER_ERROR = "provider_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SafeApiError:
    kind: ApiErrorKind
    message: str
    status_code: int | None = None
    retryable: bool = False
