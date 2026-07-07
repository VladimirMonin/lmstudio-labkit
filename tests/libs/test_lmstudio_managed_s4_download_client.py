from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from hashlib import sha256

import libs.lmstudio_managed.client as client_pkg
import pytest
from libs.lmstudio_managed.client import (
    ApiErrorKind,
    DownloadClient,
    EndpointKind,
    EndpointSpec,
    HttpMethod,
    SafeApiError,
    TransportRequest,
    TransportResponse,
    TransportResult,
)
from libs.lmstudio_managed.download import (
    DownloadErrorKind,
    DownloadRequest,
    DownloadStatus,
)


def _safe_hash(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class _TransportEnvelope:
    transport_result: TransportResult
    payload: object | None = None


class _CapturingJsonTransport:
    def __init__(
        self,
        *,
        result: _TransportEnvelope | object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.requests: list[TransportRequest] = []

    def __call__(self, request: TransportRequest) -> _TransportEnvelope | object:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def _endpoint(kind: EndpointKind, method: HttpMethod, privacy_label: str) -> EndpointSpec:
    return EndpointSpec(
        kind=kind,
        method=method,
        privacy_label=privacy_label,
    )


def test_start_download_sends_safe_post_request_and_parses_statuses() -> None:
    request = DownloadRequest(model_key="qwen-native", source_id="catalog")
    transport = _CapturingJsonTransport()
    client = DownloadClient(transport, default_timeout_s=3.5)

    start_endpoint = _endpoint(
        EndpointKind.NATIVE_DOWNLOAD,
        HttpMethod.POST,
        "native_download",
    )
    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=start_endpoint,
                status_code=200,
                body_hash=_safe_hash("already"),
                body_chars=32,
                schema_name="NativeDownloadResponse",
            )
        ),
        payload={"status": "already_downloaded"},
    )

    already = client.start_download(request)

    assert already.status == DownloadStatus.ALREADY_DOWNLOADED
    assert already.ready_on_disk is True
    assert already.job_ref is None
    assert len(transport.requests) == 1
    safe_request = transport.requests[0]
    assert safe_request.endpoint.kind == EndpointKind.NATIVE_DOWNLOAD
    assert safe_request.endpoint.method == HttpMethod.POST
    assert safe_request.endpoint.privacy_label == "native_download"
    assert safe_request.payload_kind == "download_request"
    assert safe_request.payload_hash == _safe_hash("qwen-native:catalog")
    assert safe_request.timeout_s == 3.5

    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=start_endpoint,
                status_code=202,
                body_hash=_safe_hash("progress"),
                body_chars=48,
                schema_name="NativeDownloadResponse",
            )
        ),
        payload={"status": "downloading", "job_id": "raw-job-1"},
    )
    downloading = client.start_download(request, timeout_s=1.25)

    assert downloading.status == DownloadStatus.IN_PROGRESS
    assert downloading.ready_on_disk is False
    assert downloading.job_ref == _safe_hash("raw-job-1")
    assert transport.requests[1].timeout_s == 1.25

    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=start_endpoint,
                status_code=202,
                body_hash=_safe_hash("paused"),
                body_chars=48,
                schema_name="NativeDownloadResponse",
            )
        ),
        payload={"status": "paused", "job_id": "raw-job-2"},
    )
    paused = client.start_download(request)

    assert paused.status == DownloadStatus.PAUSED
    assert paused.ready_on_disk is False
    assert paused.job_ref == _safe_hash("raw-job-2")

    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=start_endpoint,
                status_code=500,
                body_hash=_safe_hash("failed"),
                body_chars=40,
                schema_name="NativeDownloadResponse",
            )
        ),
        payload={"status": "failed", "error_kind": "disk_full"},
    )
    failed = client.start_download(request)

    assert failed.status == DownloadStatus.FAILED
    assert failed.ready_on_disk is False
    assert failed.error_kind == DownloadErrorKind.DISK_FULL
    for sentinel in ("raw-job-1", "raw-job-2", "job_id"):
        assert sentinel not in repr(downloading)
        assert sentinel not in repr(paused)
        assert sentinel not in repr(failed)


def test_poll_download_status_sends_safe_get_request_and_parses_progress() -> None:
    transport = _CapturingJsonTransport()
    client = DownloadClient(transport, default_timeout_s=9.0)
    endpoint = _endpoint(
        EndpointKind.NATIVE_DOWNLOAD_PROGRESS,
        HttpMethod.GET,
        "native_download_progress",
    )
    safe_job_ref = _safe_hash("raw-job-1")
    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=endpoint,
                status_code=200,
                body_hash=_safe_hash("poll"),
                body_chars=64,
                schema_name="NativeDownloadProgressResponse",
            )
        ),
        payload={
            "status": "downloading",
            "job_id": "raw-job-1",
            "downloaded_bytes": 256,
            "total_bytes": 1024,
        },
    )

    progress = client.poll_download_status(safe_job_ref)

    assert progress.status == DownloadStatus.IN_PROGRESS
    assert progress.downloaded_bytes == 256
    assert progress.total_bytes == 1024
    assert progress.progress_percent == pytest.approx(25.0)
    assert progress.ready_on_disk is False
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.endpoint.kind == EndpointKind.NATIVE_DOWNLOAD_PROGRESS
    assert request.endpoint.method == HttpMethod.GET
    assert request.endpoint.privacy_label == "native_download_progress"
    assert request.payload_kind == "download_progress"
    assert request.payload_hash == safe_job_ref
    assert request.timeout_s == 9.0
    assert "raw-job-1" not in repr(progress)


def test_ensure_downloaded_parses_terminal_success_and_failure_states() -> None:
    request = DownloadRequest(model_key="model-a", source_id="manifest")
    transport = _CapturingJsonTransport()
    client = DownloadClient(transport)
    endpoint = _endpoint(
        EndpointKind.NATIVE_DOWNLOAD,
        HttpMethod.POST,
        "native_download",
    )

    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=endpoint,
                status_code=200,
                body_hash=_safe_hash("completed"),
                body_chars=24,
                schema_name="NativeDownloadResponse",
            )
        ),
        payload={"status": "completed"},
    )
    completed = client.ensure_downloaded(request)

    assert completed.status == DownloadStatus.COMPLETED
    assert completed.ready_on_disk is True
    assert completed.error_kind is None
    assert completed.is_terminal_success is True

    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=endpoint,
                status_code=200,
                body_hash=_safe_hash("already"),
                body_chars=24,
                schema_name="NativeDownloadResponse",
            )
        ),
        payload={"status": "already_downloaded"},
    )
    already = client.ensure_downloaded(request)

    assert already.status == DownloadStatus.ALREADY_DOWNLOADED
    assert already.ready_on_disk is True
    assert already.error_kind is None
    assert already.is_terminal_success is True

    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=endpoint,
                status_code=500,
                body_hash=_safe_hash("failed"),
                body_chars=24,
                schema_name="NativeDownloadResponse",
            )
        ),
        payload={"status": "failed", "error_kind": "failed"},
    )
    failed = client.ensure_downloaded(request)

    assert failed.status == DownloadStatus.FAILED
    assert failed.ready_on_disk is False
    assert failed.error_kind == DownloadErrorKind.DOWNLOAD_FAILED
    assert failed.is_terminal_success is False


@pytest.mark.parametrize("payload", [None, [], "bad-payload"])
@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("start_download", (DownloadRequest(model_key="model-a", source_id="s1"),)),
        ("poll_download_status", (_safe_hash("raw-job"),)),
        ("ensure_downloaded", (DownloadRequest(model_key="model-b", source_id="s2"),)),
    ],
)
def test_download_client_maps_missing_or_non_mapping_payload_to_unexpected_schema(
    method_name: str,
    args: tuple[object, ...],
    payload: object,
) -> None:
    endpoint = _endpoint(
        EndpointKind.NATIVE_DOWNLOAD_PROGRESS
        if method_name == "poll_download_status"
        else EndpointKind.NATIVE_DOWNLOAD,
        HttpMethod.GET if method_name == "poll_download_status" else HttpMethod.POST,
        "native_download_progress" if method_name == "poll_download_status" else "native_download",
    )
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=endpoint,
                    status_code=200,
                    body_hash=_safe_hash("schema"),
                    body_chars=16,
                    schema_name="NativeDownloadResponse",
                )
            ),
            payload=payload,
        )
    )
    client = DownloadClient(transport)

    result = getattr(client, method_name)(*args)

    assert result.status == DownloadStatus.FAILED
    assert result.ready_on_disk is False
    assert result.error_kind == DownloadErrorKind.UNEXPECTED_SCHEMA


@pytest.mark.parametrize(
    ("transport_result", "expected_kind"),
    [
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.TIMEOUT,
                    message="request_timeout",
                    retryable=True,
                )
            ),
            DownloadErrorKind.NETWORK_ERROR,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.NETWORK,
                    message="network_error",
                    retryable=True,
                )
            ),
            DownloadErrorKind.NETWORK_ERROR,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.AUTH_REQUIRED,
                    message="auth_required",
                    retryable=False,
                )
            ),
            DownloadErrorKind.AUTH_REQUIRED,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.DISK_FULL,
                    message="disk_full",
                    retryable=False,
                )
            ),
            DownloadErrorKind.DISK_FULL,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.HTTP_STATUS,
                    message="http_status",
                    retryable=False,
                )
            ),
            DownloadErrorKind.DOWNLOAD_FAILED,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.UNKNOWN,
                    message="transport_error",
                    retryable=False,
                )
            ),
            DownloadErrorKind.UNKNOWN,
        ),
    ],
)
def test_download_client_maps_transport_errors_to_safe_failures(
    transport_result: TransportResult,
    expected_kind: DownloadErrorKind,
) -> None:
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=transport_result,
            payload={"status": "downloading", "job_id": "raw-job-1"},
        )
    )
    client = DownloadClient(transport)

    start = client.start_download(DownloadRequest(model_key="model-a", source_id="catalog"))
    progress = client.poll_download_status(_safe_hash("raw-job-1"))
    ensure = client.ensure_downloaded(DownloadRequest(model_key="model-a", source_id="catalog"))

    for result in (start, progress, ensure):
        assert result.status == DownloadStatus.FAILED
        assert result.ready_on_disk is False
        assert result.error_kind == expected_kind
        for sentinel in (
            "raw-job-1",
            "job_id",
            "payload",
            "url",
            "path",
            "body",
            "prompt",
        ):
            assert sentinel not in repr(result)


@pytest.mark.parametrize(
    ("error", "expected_kind"),
    [
        (
            TimeoutError(
                "https://localhost:1234/api/v1/download prompt secret-prompt job_id=job-123"
            ),
            DownloadErrorKind.NETWORK_ERROR,
        ),
        (
            OSError("body secret-body path /api/v1/download/raw-job-1"),
            DownloadErrorKind.NETWORK_ERROR,
        ),
        (
            RuntimeError("response_text leaked-response job_id=job-123"),
            DownloadErrorKind.UNKNOWN,
        ),
    ],
)
def test_download_client_maps_transport_exceptions_without_leaking_raw_text(
    error: Exception,
    expected_kind: DownloadErrorKind,
) -> None:
    transport = _CapturingJsonTransport(error=error)
    client = DownloadClient(transport)

    result = client.start_download(DownloadRequest(model_key="model-a", source_id="catalog"))

    assert result.status == DownloadStatus.FAILED
    assert result.ready_on_disk is False
    assert result.error_kind == expected_kind
    for sentinel in (
        "https://localhost:1234/api/v1/download",
        "secret-prompt",
        "secret-body",
        "leaked-response",
        "job-123",
        "/api/v1/download/raw-job-1",
    ):
        assert sentinel not in repr(result)


def test_public_download_client_exports_stay_safe_and_private_payload_surface_is_not_exported() -> (
    None
):
    forbidden_names = {
        "payload",
        "url",
        "path",
        "body",
        "prompt",
        "response_text",
        "instance_id",
        "job_id",
    }

    exported_names = set(client_pkg.__all__)
    exported_objects = [getattr(client_pkg, name) for name in exported_names]
    dataclass_field_names: set[str] = set()
    for exported in exported_objects:
        if is_dataclass(exported):
            dataclass_field_names.update(field.name for field in fields(exported))

    client_public_names = {name for name in dir(DownloadClient) if not name.startswith("_")}

    assert "DownloadClient" in exported_names
    assert "_JsonTransportResult" not in exported_names
    assert forbidden_names.isdisjoint(dataclass_field_names)
    assert forbidden_names.isdisjoint(client_public_names)
