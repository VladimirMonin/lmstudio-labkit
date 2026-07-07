from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
from inspect import signature
from typing import cast

import pytest
from libs.lmstudio_managed.client import (
    ApiErrorKind,
    EndpointKind,
    EndpointSpec,
    HttpMethod,
    RestClient,
    TransportProtocol,
    TransportRequest,
    TransportResponse,
    TransportResult,
)


def _safe_hash(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


class _CapturingTransport:
    def __init__(
        self,
        *,
        result: TransportResult | object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.requests: list[TransportRequest] = []

    def __call__(self, request: TransportRequest) -> TransportResult | object:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def _endpoint() -> EndpointSpec:
    return EndpointSpec(
        kind=EndpointKind.COMPAT_MODELS,
        method=HttpMethod.GET,
        privacy_label="compat_models",
    )


def _ok_result(endpoint: EndpointSpec) -> TransportResult:
    return TransportResult(
        response=TransportResponse(
            endpoint=endpoint,
            status_code=200,
            body_hash=_safe_hash("response"),
            body_chars=8,
            schema_name="CompatModelsResponse",
        )
    )


def test_rest_client_builds_safe_request_and_returns_exact_success_result() -> None:
    endpoint = _endpoint()
    expected = _ok_result(endpoint)
    transport = _CapturingTransport(result=expected)
    client = RestClient(cast(TransportProtocol, transport), default_timeout_s=5.0)

    result = client.request(
        endpoint,
        payload_kind="model_list",
        payload_hash=_safe_hash("payload"),
    )

    assert result is expected
    assert result.ok is True
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.endpoint.kind == EndpointKind.COMPAT_MODELS
    assert request.endpoint.method == HttpMethod.GET
    assert request.endpoint.privacy_label == "compat_models"
    assert request.payload_kind == "model_list"
    assert request.payload_hash == _safe_hash("payload")
    assert request.timeout_s == 5.0


def test_rest_client_uses_default_timeout_and_allows_per_call_override() -> None:
    endpoint = _endpoint()
    transport = _CapturingTransport(result=_ok_result(endpoint))
    client = RestClient(cast(TransportProtocol, transport), default_timeout_s=7.5)

    first = client.request(endpoint)
    second = client.request(endpoint, timeout_s=1.25)

    assert first.ok is True
    assert second.ok is True
    assert transport.requests[0].timeout_s == 7.5
    assert transport.requests[1].timeout_s == 1.25


@pytest.mark.parametrize(
    ("error", "expected_kind", "expected_message", "expected_retryable"),
    [
        (
            TimeoutError("https://localhost:1234/v1/models prompt secret-prompt"),
            ApiErrorKind.TIMEOUT,
            "request_timeout",
            True,
        ),
        (
            OSError("body secret-body path /api/v1/models"),
            ApiErrorKind.NETWORK,
            "network_error",
            True,
        ),
        (
            RuntimeError("response_text leaked-response job_id=job-123"),
            ApiErrorKind.UNKNOWN,
            "transport_error",
            False,
        ),
    ],
)
def test_rest_client_maps_transport_exceptions_to_safe_errors(
    error: Exception,
    expected_kind: ApiErrorKind,
    expected_message: str,
    expected_retryable: bool,
) -> None:
    endpoint = _endpoint()
    transport = _CapturingTransport(error=error)
    client = RestClient(cast(TransportProtocol, transport))

    result = client.request(
        endpoint,
        payload_kind="sentinel_kind",
        payload_hash=_safe_hash("sentinel"),
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.kind == expected_kind
    assert result.error.message == expected_message
    assert result.error.retryable is expected_retryable
    assert len(transport.requests) == 1
    for sentinel in (
        "https://localhost:1234/v1/models",
        "secret-prompt",
        "secret-body",
        "leaked-response",
        "job-123",
        "/api/v1/models",
    ):
        assert sentinel not in result.error.message
        assert sentinel not in repr(result.error)
        assert sentinel not in repr(result)


def test_rest_client_maps_non_transport_result_return_to_unexpected_schema() -> None:
    endpoint = _endpoint()
    transport = _CapturingTransport(result={"status": 200})
    client = RestClient(cast(TransportProtocol, transport))

    result = client.request(endpoint)

    assert result.ok is False
    assert result.error is not None
    assert result.error.kind == ApiErrorKind.UNEXPECTED_SCHEMA
    assert result.error.message == "transport_unexpected_schema"
    assert result.error.retryable is False


def test_safe_public_surfaces_do_not_reintroduce_raw_transport_field_names() -> None:
    forbidden_names = {
        "url",
        "path",
        "body",
        "prompt",
        "response_text",
        "instance_id",
        "job_id",
    }

    request_field_names = {field.name for field in fields(TransportRequest)}
    response_field_names = {field.name for field in fields(TransportResponse)}
    result_field_names = {field.name for field in fields(TransportResult)}
    protocol_parameter_names = set(signature(TransportProtocol.__call__).parameters)
    client_public_names = {name for name in dir(RestClient) if not name.startswith("_")}

    assert forbidden_names.isdisjoint(request_field_names)
    assert forbidden_names.isdisjoint(response_field_names)
    assert forbidden_names.isdisjoint(result_field_names)
    assert forbidden_names.isdisjoint(protocol_parameter_names)
    assert forbidden_names.isdisjoint(client_public_names)
