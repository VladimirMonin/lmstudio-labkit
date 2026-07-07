"""Fake-first download client over an injected JSON transport seam."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

from .._safe import safe_hash_ref
from ..download import (
    DownloadErrorKind,
    DownloadProgressEvent,
    DownloadRequest,
    DownloadResult,
    DownloadStartResponse,
    DownloadStatus,
    classify_download_payload,
    download_progress_event_from_payload,
    download_result_from_payload,
)
from .endpoint import EndpointKind, EndpointSpec, HttpMethod
from .errors import ApiErrorKind, SafeApiError
from .rest_client import (
    _build_transport_request,
    _coerce_json_result,
    _JsonTransportProtocol,
    _transport_exception_result,
)

_ResultT = TypeVar("_ResultT", DownloadStartResponse, DownloadProgressEvent, DownloadResult)

_NATIVE_DOWNLOAD_ENDPOINT = EndpointSpec(
    kind=EndpointKind.NATIVE_DOWNLOAD,
    method=HttpMethod.POST,
    privacy_label="native_download",
)
_NATIVE_DOWNLOAD_PROGRESS_ENDPOINT = EndpointSpec(
    kind=EndpointKind.NATIVE_DOWNLOAD_PROGRESS,
    method=HttpMethod.GET,
    privacy_label="native_download_progress",
)


class DownloadClient:
    """Privacy-safe download client for native LM Studio download endpoints."""

    __slots__ = ("_transport", "_default_timeout_s")

    def __init__(
        self,
        transport: _JsonTransportProtocol,
        *,
        default_timeout_s: float | None = None,
    ) -> None:
        self._transport = transport
        self._default_timeout_s = default_timeout_s

    def start_download(
        self,
        request: DownloadRequest,
        timeout_s: float | None = None,
    ) -> DownloadStartResponse:
        return self._call_download_endpoint(
            endpoint=_NATIVE_DOWNLOAD_ENDPOINT,
            payload_kind="download_request",
            payload_hash=_request_hash(request),
            parser=classify_download_payload,
            timeout_s=timeout_s,
            error_factory=self._start_error_response,
        )

    def poll_download_status(
        self,
        job_ref: str,
        timeout_s: float | None = None,
    ) -> DownloadProgressEvent:
        return self._call_download_endpoint(
            endpoint=_NATIVE_DOWNLOAD_PROGRESS_ENDPOINT,
            payload_kind="download_progress",
            payload_hash=safe_hash_ref(job_ref),
            parser=download_progress_event_from_payload,
            timeout_s=timeout_s,
            error_factory=self._progress_error_response,
        )

    def ensure_downloaded(
        self,
        request: DownloadRequest,
        timeout_s: float | None = None,
    ) -> DownloadResult:
        return self._call_download_endpoint(
            endpoint=_NATIVE_DOWNLOAD_ENDPOINT,
            payload_kind="download_request",
            payload_hash=_request_hash(request),
            parser=download_result_from_payload,
            timeout_s=timeout_s,
            error_factory=self._result_error_response,
        )

    def _call_download_endpoint(
        self,
        *,
        endpoint: EndpointSpec,
        payload_kind: str,
        payload_hash: str | None,
        parser: Callable[[Mapping[str, object]], _ResultT],
        timeout_s: float | None,
        error_factory: Callable[[DownloadErrorKind], _ResultT],
    ) -> _ResultT:
        transport_request = _build_transport_request(
            endpoint,
            payload_kind=payload_kind,
            payload_hash=payload_hash,
            timeout_s=timeout_s,
            default_timeout_s=self._default_timeout_s,
        )

        try:
            raw_result = self._transport(transport_request)
        except Exception as error:
            return error_factory(
                _download_error_kind_from_api_error(_transport_exception_result(error).error)
            )

        transport_result, payload = _coerce_json_result(raw_result)
        if transport_result is None:
            return error_factory(DownloadErrorKind.UNEXPECTED_SCHEMA)

        if not transport_result.ok:
            return error_factory(_download_error_kind_from_api_error(transport_result.error))

        if not isinstance(payload, Mapping):
            return error_factory(DownloadErrorKind.UNEXPECTED_SCHEMA)

        return parser(payload)

    @staticmethod
    def _start_error_response(error_kind: DownloadErrorKind) -> DownloadStartResponse:
        return DownloadStartResponse(
            status=DownloadStatus.FAILED,
            ready_on_disk=False,
            error_kind=error_kind,
        )

    @staticmethod
    def _progress_error_response(error_kind: DownloadErrorKind) -> DownloadProgressEvent:
        return DownloadProgressEvent(
            status=DownloadStatus.FAILED,
            downloaded_bytes=None,
            total_bytes=None,
            ready_on_disk=False,
            error_kind=error_kind,
        )

    @staticmethod
    def _result_error_response(error_kind: DownloadErrorKind) -> DownloadResult:
        return DownloadResult(
            status=DownloadStatus.FAILED,
            ready_on_disk=False,
            error_kind=error_kind,
        )


def _request_hash(request: DownloadRequest) -> str:
    return safe_hash_ref(f"{request.model_key}:{request.source_id}") or ""


def _download_error_kind_from_api_error(error: SafeApiError | None) -> DownloadErrorKind:
    if error is None:
        return DownloadErrorKind.UNEXPECTED_SCHEMA
    if error.kind in {ApiErrorKind.TIMEOUT, ApiErrorKind.NETWORK}:
        return DownloadErrorKind.NETWORK_ERROR
    if error.kind == ApiErrorKind.AUTH_REQUIRED:
        return DownloadErrorKind.AUTH_REQUIRED
    if error.kind == ApiErrorKind.DISK_FULL:
        return DownloadErrorKind.DISK_FULL
    if error.kind == ApiErrorKind.UNEXPECTED_SCHEMA:
        return DownloadErrorKind.UNEXPECTED_SCHEMA
    if error.kind in {ApiErrorKind.HTTP_STATUS, ApiErrorKind.PROVIDER_ERROR}:
        return DownloadErrorKind.DOWNLOAD_FAILED
    if error.kind == ApiErrorKind.UNKNOWN:
        return DownloadErrorKind.UNKNOWN
    return DownloadErrorKind.DOWNLOAD_FAILED
