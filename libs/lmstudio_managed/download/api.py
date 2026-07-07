"""Pure download REST contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .._safe import as_int, as_str, safe_hash_ref
from .models import DownloadStatus


class DownloadErrorKind(StrEnum):
    UNEXPECTED_SCHEMA = "unexpected_schema"
    NETWORK_ERROR = "network_error"
    DISK_FULL = "disk_full"
    AUTH_REQUIRED = "auth_required"
    DOWNLOAD_FAILED = "download_failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    model_key: str
    source_id: str
    expected_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class DownloadStartResponse:
    status: DownloadStatus
    ready_on_disk: bool
    job_ref: str | None = None
    error_kind: DownloadErrorKind | None = None


@dataclass(frozen=True, slots=True)
class DownloadProgressEvent:
    status: DownloadStatus
    downloaded_bytes: int | None
    total_bytes: int | None
    ready_on_disk: bool
    error_kind: DownloadErrorKind | None = None

    @property
    def progress_percent(self) -> float | None:
        if self.total_bytes is None or self.total_bytes <= 0:
            return None
        downloaded = self.downloaded_bytes or 0
        return max(0.0, min(100.0, (downloaded / self.total_bytes) * 100.0))


@dataclass(frozen=True, slots=True)
class DownloadResult:
    status: DownloadStatus
    ready_on_disk: bool
    error_kind: DownloadErrorKind | None = None

    @property
    def is_terminal_success(self) -> bool:
        return self.status in {
            DownloadStatus.ALREADY_DOWNLOADED,
            DownloadStatus.COMPLETED,
        }


def classify_download_payload(payload: Mapping[str, object]) -> DownloadStartResponse:
    state = as_str(payload.get("status")) or as_str(payload.get("state"))
    if state is None:
        return DownloadStartResponse(
            status=DownloadStatus.FAILED,
            ready_on_disk=False,
            error_kind=DownloadErrorKind.UNEXPECTED_SCHEMA,
        )

    normalized = state.lower()
    if normalized == "already_downloaded":
        return DownloadStartResponse(
            status=DownloadStatus.ALREADY_DOWNLOADED,
            ready_on_disk=True,
        )
    if normalized == "completed":
        return DownloadStartResponse(
            status=DownloadStatus.COMPLETED,
            ready_on_disk=True,
        )
    if normalized in {"downloading", "paused"}:
        job_ref = safe_hash_ref(payload.get("job_id"))
        if job_ref is None:
            return DownloadStartResponse(
                status=DownloadStatus.FAILED,
                ready_on_disk=False,
                error_kind=DownloadErrorKind.UNEXPECTED_SCHEMA,
            )
        return DownloadStartResponse(
            status=DownloadStatus.PAUSED if normalized == "paused" else DownloadStatus.IN_PROGRESS,
            ready_on_disk=False,
            job_ref=job_ref,
        )
    if normalized == "failed":
        return DownloadStartResponse(
            status=DownloadStatus.FAILED,
            ready_on_disk=False,
            error_kind=_error_kind_from_payload(
                payload,
                default=DownloadErrorKind.DOWNLOAD_FAILED,
            ),
        )

    return DownloadStartResponse(
        status=DownloadStatus.FAILED,
        ready_on_disk=False,
        error_kind=DownloadErrorKind.UNEXPECTED_SCHEMA,
    )


def download_progress_event_from_payload(
    payload: Mapping[str, object],
) -> DownloadProgressEvent:
    start = classify_download_payload(payload)
    return DownloadProgressEvent(
        status=start.status,
        downloaded_bytes=as_int(payload.get("downloaded_bytes"))
        or as_int(payload.get("downloadedBytes")),
        total_bytes=as_int(payload.get("total_bytes")) or as_int(payload.get("totalBytes")),
        ready_on_disk=start.ready_on_disk,
        error_kind=start.error_kind,
    )


def download_result_from_payload(payload: Mapping[str, object]) -> DownloadResult:
    start = classify_download_payload(payload)
    return DownloadResult(
        status=start.status,
        ready_on_disk=start.ready_on_disk,
        error_kind=start.error_kind,
    )


def _error_kind_from_payload(
    payload: Mapping[str, object],
    *,
    default: DownloadErrorKind,
) -> DownloadErrorKind:
    error = as_str(payload.get("error_kind")) or as_str(payload.get("error"))
    if error is None:
        return default
    normalized = error.lower()
    if normalized in {"unexpected_schema", "schema"}:
        return DownloadErrorKind.UNEXPECTED_SCHEMA
    if normalized in {"network", "network_error"}:
        return DownloadErrorKind.NETWORK_ERROR
    if normalized == "disk_full":
        return DownloadErrorKind.DISK_FULL
    if normalized in {"auth", "auth_required", "unauthorized"}:
        return DownloadErrorKind.AUTH_REQUIRED
    if normalized in {"download_failed", "failed"}:
        return DownloadErrorKind.DOWNLOAD_FAILED
    return DownloadErrorKind.UNKNOWN
