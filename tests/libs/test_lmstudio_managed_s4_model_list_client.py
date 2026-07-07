from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from hashlib import sha256

import pytest

import libs.lmstudio_managed.client as client_pkg
from libs.lmstudio_managed.client import (
    ApiErrorKind,
    EndpointKind,
    EndpointSpec,
    HttpMethod,
    ModelListClient,
    SafeApiError,
    TransportRequest,
    TransportResponse,
    TransportResult,
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


def _endpoint(kind: EndpointKind, privacy_label: str) -> EndpointSpec:
    return EndpointSpec(
        kind=kind,
        method=HttpMethod.GET,
        privacy_label=privacy_label,
    )


def test_model_list_client_lists_compat_models_with_safe_get_request() -> None:
    transport = _CapturingJsonTransport()
    client = ModelListClient(transport, default_timeout_s=4.0)

    endpoint = _endpoint(EndpointKind.COMPAT_MODELS, "compat_models")
    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=endpoint,
                status_code=200,
                body_hash=_safe_hash("compat"),
                body_chars=24,
                schema_name="CompatModelsResponse",
            )
        ),
        payload={
            "data": [
                {"id": "qwen-text", "owned_by": "lm-studio"},
                {"id": "other-model", "owned_by": "external"},
            ]
        },
    )

    response = client.list_compat_models()

    assert response.error is None
    assert response.endpoint_kind == EndpointKind.COMPAT_MODELS
    assert tuple(model.model_id for model in response.visible_models) == (
        "qwen-text",
        "other-model",
    )
    assert response.native_models == ()
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.endpoint.kind == EndpointKind.COMPAT_MODELS
    assert request.endpoint.method == HttpMethod.GET
    assert request.endpoint.privacy_label == "compat_models"
    assert request.payload_kind == "model_list"
    assert request.payload_hash is None
    assert request.timeout_s == 4.0


def test_model_list_client_lists_native_models_and_keeps_raw_instance_ids_private() -> None:
    transport = _CapturingJsonTransport()
    client = ModelListClient(transport, default_timeout_s=6.0)

    endpoint = _endpoint(EndpointKind.NATIVE_MODELS, "native_models")
    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=endpoint,
                status_code=200,
                body_hash=_safe_hash("native"),
                body_chars=32,
                schema_name="NativeModelsResponse",
            )
        ),
        payload={
            "data": [
                {
                    "modelKey": "qwen-native",
                    "format": "gguf",
                    "bitsPerWeight": 4.5,
                    "sizeBytes": 1024,
                    "loadedInstances": [
                        {
                            "id": "raw-instance-1",
                            "contextLength": 8192,
                            "numParallelSequences": 2,
                        },
                        {
                            "id": "raw-instance-2",
                            "contextLength": 4096,
                            "numParallelSequences": 1,
                            "ownedByUs": False,
                        },
                    ],
                },
                {
                    "modelKey": "idle-native",
                    "format": "gguf",
                    "bitsPerWeight": 8,
                    "sizeBytes": 2048,
                    "loadedInstances": [],
                },
            ]
        },
    )

    response = client.list_native_models(timeout_s=1.5)

    assert response.error is None
    assert response.endpoint_kind == EndpointKind.NATIVE_MODELS
    assert tuple(model.model_id for model in response.visible_models) == (
        "qwen-native",
        "idle-native",
    )
    assert response.native_models[0].quantization is None
    assert response.native_models[0].loaded_instances[0].instance_ref == _safe_hash(
        "raw-instance-1"
    )
    assert response.native_models[0].loaded_instances[0].context_length == 8192
    assert response.native_models[0].loaded_instances[0].parallel == 2
    assert response.native_models[0].loaded_instances[1].owned_by_us is False
    assert response.native_models[1].loaded_instances == ()
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.endpoint.kind == EndpointKind.NATIVE_MODELS
    assert request.endpoint.method == HttpMethod.GET
    assert request.endpoint.privacy_label == "native_models"
    assert request.payload_kind == "model_list"
    assert request.timeout_s == 1.5
    for sentinel in ("raw-instance-1", "raw-instance-2", "instance_id"):
        assert sentinel not in repr(response)
        assert sentinel not in repr(response.native_models[0].loaded_instances[0])


def test_model_list_client_maps_transport_result_errors_to_safe_model_list_error() -> None:
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.NETWORK,
                    message="network_error",
                    retryable=True,
                )
            ),
            payload={"data": []},
        )
    )
    client = ModelListClient(transport)

    response = client.list_native_models()

    assert response.endpoint_kind == EndpointKind.NATIVE_MODELS
    assert response.visible_models == ()
    assert response.native_models == ()
    assert response.error is not None
    assert response.error.kind == ApiErrorKind.NETWORK
    assert response.error.message == "network_error"
    assert response.error.retryable is True


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
def test_model_list_client_maps_transport_exceptions_without_leaking_raw_text(
    error: Exception,
    expected_kind: ApiErrorKind,
    expected_message: str,
    expected_retryable: bool,
) -> None:
    transport = _CapturingJsonTransport(error=error)
    client = ModelListClient(transport)

    response = client.list_compat_models()

    assert response.endpoint_kind == EndpointKind.COMPAT_MODELS
    assert response.visible_models == ()
    assert response.native_models == ()
    assert response.error is not None
    assert response.error.kind == expected_kind
    assert response.error.message == expected_message
    assert response.error.retryable is expected_retryable
    for sentinel in (
        "https://localhost:1234/v1/models",
        "secret-prompt",
        "secret-body",
        "leaked-response",
        "job-123",
        "/api/v1/models",
    ):
        assert sentinel not in response.error.message
        assert sentinel not in repr(response.error)
        assert sentinel not in repr(response)


@pytest.mark.parametrize("payload", [None, [], "bad-payload"])
def test_model_list_client_maps_missing_or_non_mapping_payload_to_unexpected_schema(
    payload: object,
) -> None:
    endpoint = _endpoint(EndpointKind.NATIVE_MODELS, "native_models")
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=endpoint,
                    status_code=200,
                    body_hash=_safe_hash("schema"),
                    body_chars=16,
                    schema_name="NativeModelsResponse",
                )
            ),
            payload=payload,
        )
    )
    client = ModelListClient(transport)

    response = client.list_native_models()

    assert response.endpoint_kind == EndpointKind.NATIVE_MODELS
    assert response.visible_models == ()
    assert response.native_models == ()
    assert response.error is not None
    assert response.error.kind == ApiErrorKind.UNEXPECTED_SCHEMA
    assert response.error.message == "model_list_unexpected_schema"
    assert response.error.retryable is False


def test_public_model_list_client_exports_stay_safe_and_private_payload_surface_is_not_exported() -> (
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

    client_public_names = {name for name in dir(ModelListClient) if not name.startswith("_")}

    assert "_JsonTransportResult" not in exported_names
    assert forbidden_names.isdisjoint(dataclass_field_names)
    assert forbidden_names.isdisjoint(client_public_names)
