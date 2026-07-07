from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from hashlib import sha256

import libs.lmstudio_managed.client as client_pkg
import pytest
from libs.lmstudio_managed.client import (
    ApiErrorKind,
    EndpointKind,
    EndpointSpec,
    HttpMethod,
    LifecycleClient,
    SafeApiError,
    TransportRequest,
    TransportResponse,
    TransportResult,
)
from libs.lmstudio_managed.lifecycle import (
    LifecycleAction,
    LoadModelRequest,
    UnloadModelRequest,
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
    return EndpointSpec(kind=kind, method=method, privacy_label=privacy_label)


def test_load_model_sends_safe_post_request_and_uses_response_echo_only() -> None:
    request = LoadModelRequest(model_key="qwen-native", context_length=4096, parallel=4)
    transport = _CapturingJsonTransport()
    client = LifecycleClient(transport, default_timeout_s=8.0)
    endpoint = _endpoint(EndpointKind.NATIVE_LOAD, HttpMethod.POST, "native_load")
    raw_instance_id = "raw-instance-load-1"
    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=endpoint,
                status_code=200,
                body_hash=_safe_hash("load"),
                body_chars=64,
                schema_name="NativeLoadResponse",
            )
        ),
        payload={
            "status": "success",
            "instance": {
                "id": raw_instance_id,
                "modelKey": "qwen-native-reconciled",
            },
            "echoLoadConfig": {
                "contextLength": 8192,
                "numParallelSequences": 2,
            },
        },
    )

    response = client.load_model(request)

    assert response.status == LifecycleAction.LOAD_RECONCILE_OK
    assert response.error is None
    assert response.instance is not None
    assert response.instance.instance_ref == _safe_hash(raw_instance_id)
    assert response.instance.model_key == "qwen-native-reconciled"
    assert response.echo is not None
    assert response.echo.context_length == 8192
    assert response.echo.parallel == 2
    assert response.echo.context_length != request.context_length
    assert response.echo.parallel != request.parallel
    assert len(transport.requests) == 1
    safe_request = transport.requests[0]
    assert safe_request.endpoint.kind == EndpointKind.NATIVE_LOAD
    assert safe_request.endpoint.method == HttpMethod.POST
    assert safe_request.endpoint.privacy_label == "native_load"
    assert safe_request.payload_kind == "load_model"
    assert safe_request.payload_hash == _safe_hash("qwen-native:4096:4")
    assert safe_request.timeout_s == 8.0
    for sentinel in (raw_instance_id, "instance_id"):
        assert sentinel not in repr(response)
        assert sentinel not in repr(response.instance)


def test_load_model_does_not_infer_echo_from_request_when_response_omits_it() -> None:
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(EndpointKind.NATIVE_LOAD, HttpMethod.POST, "native_load"),
                    status_code=200,
                    body_hash=_safe_hash("load-no-echo"),
                    body_chars=24,
                    schema_name="NativeLoadResponse",
                )
            ),
            payload={"action": "loaded", "instance_id": "raw-instance-load-2"},
        )
    )
    client = LifecycleClient(transport)

    response = client.load_model(
        LoadModelRequest(model_key="qwen-native", context_length=16384, parallel=8)
    )

    assert response.status == LifecycleAction.LOAD_RECONCILE_OK
    assert response.error is None
    assert response.echo is None
    assert response.instance is not None
    assert response.instance.instance_ref == _safe_hash("raw-instance-load-2")


def test_list_loaded_instances_sends_safe_get_request_and_returns_hashed_refs() -> None:
    transport = _CapturingJsonTransport()
    client = LifecycleClient(transport, default_timeout_s=6.5)
    endpoint = _endpoint(EndpointKind.NATIVE_MODELS, HttpMethod.GET, "native_models")
    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=endpoint,
                status_code=200,
                body_hash=_safe_hash("native-models"),
                body_chars=96,
                schema_name="NativeModelsResponse",
            )
        ),
        payload={
            "data": [
                {
                    "modelKey": "qwen-native",
                    "loadedInstances": [
                        {
                            "id": "raw-instance-a",
                            "contextLength": 8192,
                            "numParallelSequences": 2,
                        }
                    ],
                }
            ]
        },
    )

    response = client.list_loaded_instances()

    assert response.error is None
    assert response.endpoint_kind == EndpointKind.NATIVE_MODELS
    assert response.native_models[0].loaded_instances[0].instance_ref == _safe_hash(
        "raw-instance-a"
    )
    assert response.native_models[0].loaded_instances[0].context_length == 8192
    assert response.native_models[0].loaded_instances[0].parallel == 2
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.endpoint.kind == EndpointKind.NATIVE_MODELS
    assert request.endpoint.method == HttpMethod.GET
    assert request.endpoint.privacy_label == "native_models"
    assert request.payload_kind == "model_list"
    assert request.payload_hash is None
    assert request.timeout_s == 6.5
    assert "raw-instance-a" not in repr(response)


def test_unload_instance_sends_safe_post_request_and_enforces_exact_instance_refs() -> None:
    safe_instance_ref = _safe_hash("raw-instance-unload")
    request = UnloadModelRequest(instance_ref=safe_instance_ref, model_key="qwen-native")
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(
                        EndpointKind.NATIVE_UNLOAD, HttpMethod.POST, "native_unload"
                    ),
                    status_code=200,
                    body_hash=_safe_hash("unload"),
                    body_chars=32,
                    schema_name="NativeUnloadResponse",
                )
            ),
            payload={"status": "success"},
        )
    )
    client = LifecycleClient(transport, default_timeout_s=2.0)

    response = client.unload_instance(request)

    assert response.status == LifecycleAction.UNLOAD_EXACT
    assert response.unloaded is True
    assert response.error is None
    assert len(transport.requests) == 1
    safe_request = transport.requests[0]
    assert safe_request.endpoint.kind == EndpointKind.NATIVE_UNLOAD
    assert safe_request.endpoint.method == HttpMethod.POST
    assert safe_request.endpoint.privacy_label == "native_unload"
    assert safe_request.payload_kind == "unload_model"
    assert safe_request.payload_hash == _safe_hash(f"unload:{safe_instance_ref}:qwen-native")
    assert safe_request.timeout_s == 2.0

    already = client.unload_instance(request, timeout_s=1.0)
    assert already.status == LifecycleAction.UNLOAD_EXACT
    assert already.unloaded is True
    assert transport.requests[1].timeout_s == 1.0

    with pytest.raises(ValueError, match="exact instance_ref"):
        UnloadModelRequest(instance_ref="*", model_key="qwen-native")


def test_unload_instance_maps_already_unloaded_and_failed_statuses() -> None:
    safe_instance_ref = _safe_hash("raw-instance-unload-2")
    request = UnloadModelRequest(instance_ref=safe_instance_ref, model_key="qwen-native")
    transport = _CapturingJsonTransport()
    client = LifecycleClient(transport)
    endpoint = _endpoint(EndpointKind.NATIVE_UNLOAD, HttpMethod.POST, "native_unload")

    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=endpoint,
                status_code=200,
                body_hash=_safe_hash("already-unloaded"),
                body_chars=24,
                schema_name="NativeUnloadResponse",
            )
        ),
        payload={"status": "already_unloaded"},
    )
    already = client.unload_instance(request)
    assert already.status == LifecycleAction.ALREADY_UNLOADED
    assert already.unloaded is True
    assert already.error is None

    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=endpoint,
                status_code=409,
                body_hash=_safe_hash("failed-unload"),
                body_chars=20,
                schema_name="NativeUnloadResponse",
            )
        ),
        payload={"status": "failed", "instance_id": "raw-instance-unload-2"},
    )
    failed = client.unload_instance(request)
    assert failed.status == LifecycleAction.DO_NOT_TOUCH
    assert failed.unloaded is False
    assert failed.error is not None
    assert failed.error.kind == ApiErrorKind.PROVIDER_ERROR
    assert failed.error.message == "unload_model_failed"
    assert "raw-instance-unload-2" not in repr(failed)


def test_unload_instance_treats_empty_mapping_payload_as_exact_success() -> None:
    safe_instance_ref = _safe_hash("raw-instance-unload-empty")
    request = UnloadModelRequest(instance_ref=safe_instance_ref, model_key="qwen-native")
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(
                        EndpointKind.NATIVE_UNLOAD, HttpMethod.POST, "native_unload"
                    ),
                    status_code=200,
                    body_hash=_safe_hash("unload-empty"),
                    body_chars=2,
                    schema_name="NativeUnloadResponse",
                )
            ),
            payload={},
        )
    )
    client = LifecycleClient(transport)

    response = client.unload_instance(request)

    assert response.status == LifecycleAction.UNLOAD_EXACT
    assert response.unloaded is True
    assert response.error is None


def test_unload_instance_treats_identifier_only_payload_as_exact_success() -> None:
    raw_instance_id = "raw-instance-unload-live"
    safe_instance_ref = _safe_hash(raw_instance_id)
    request = UnloadModelRequest(instance_ref=safe_instance_ref, model_key="qwen-native")
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(
                        EndpointKind.NATIVE_UNLOAD, HttpMethod.POST, "native_unload"
                    ),
                    status_code=200,
                    body_hash=_safe_hash("unload-identifier-only"),
                    body_chars=41,
                    schema_name="NativeUnloadResponse",
                )
            ),
            payload={"instance_id": raw_instance_id},
        )
    )
    client = LifecycleClient(transport)

    response = client.unload_instance(request)

    assert response.status == LifecycleAction.UNLOAD_EXACT
    assert response.unloaded is True
    assert response.error is None
    assert raw_instance_id not in repr(response)


def test_unload_instance_does_not_treat_identifier_plus_error_as_success() -> None:
    raw_instance_id = "raw-instance-unload-live-error"
    safe_instance_ref = _safe_hash(raw_instance_id)
    request = UnloadModelRequest(instance_ref=safe_instance_ref, model_key="qwen-native")
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(
                        EndpointKind.NATIVE_UNLOAD, HttpMethod.POST, "native_unload"
                    ),
                    status_code=200,
                    body_hash=_safe_hash("unload-identifier-with-error"),
                    body_chars=58,
                    schema_name="NativeUnloadResponse",
                )
            ),
            payload={"instance_id": raw_instance_id, "error": "boom"},
        )
    )
    client = LifecycleClient(transport)

    response = client.unload_instance(request)

    assert response.status == LifecycleAction.DO_NOT_TOUCH
    assert response.unloaded is False
    assert response.error is not None
    assert response.error.kind == ApiErrorKind.PROVIDER_ERROR
    assert response.error.message == "unload_model_failed"
    assert raw_instance_id not in repr(response)


@pytest.mark.parametrize(
    ("method_name", "args", "expected_status", "expected_error_kind", "expected_error_message"),
    [
        (
            "load_model",
            (LoadModelRequest(model_key="model-a", context_length=4096, parallel=2),),
            LifecycleAction.LOAD_RECONCILE_ERROR,
            ApiErrorKind.UNEXPECTED_SCHEMA,
            "load_model_unexpected_schema",
        ),
        (
            "unload_instance",
            (UnloadModelRequest(instance_ref=_safe_hash("raw-unload"), model_key="model-a"),),
            LifecycleAction.DO_NOT_TOUCH,
            ApiErrorKind.UNEXPECTED_SCHEMA,
            "unload_model_unexpected_schema",
        ),
        (
            "list_loaded_instances",
            (),
            None,
            ApiErrorKind.UNEXPECTED_SCHEMA,
            "model_list_unexpected_schema",
        ),
    ],
)
@pytest.mark.parametrize("payload", [None, [], "bad-payload"])
def test_lifecycle_client_maps_non_mapping_payloads_to_safe_errors(
    method_name: str,
    args: tuple[object, ...],
    expected_status: LifecycleAction | None,
    expected_error_kind: ApiErrorKind,
    expected_error_message: str,
    payload: object,
) -> None:
    endpoint_kind = {
        "load_model": EndpointKind.NATIVE_LOAD,
        "unload_instance": EndpointKind.NATIVE_UNLOAD,
        "list_loaded_instances": EndpointKind.NATIVE_MODELS,
    }[method_name]
    method = {
        "load_model": HttpMethod.POST,
        "unload_instance": HttpMethod.POST,
        "list_loaded_instances": HttpMethod.GET,
    }[method_name]
    privacy_label = {
        "load_model": "native_load",
        "unload_instance": "native_unload",
        "list_loaded_instances": "native_models",
    }[method_name]
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(endpoint_kind, method, privacy_label),
                    status_code=200,
                    body_hash=_safe_hash(f"schema-{method_name}"),
                    body_chars=16,
                    schema_name="SchemaResponse",
                )
            ),
            payload=payload,
        )
    )
    client = LifecycleClient(transport)

    result = getattr(client, method_name)(*args)

    assert result.error is not None
    assert result.error.kind == expected_error_kind
    assert result.error.message == expected_error_message
    assert result.error.retryable is False
    if expected_status is not None:
        assert result.status == expected_status
    else:
        assert result.endpoint_kind == EndpointKind.NATIVE_MODELS
        assert result.visible_models == ()
        assert result.native_models == ()


@pytest.mark.parametrize(
    ("method_name", "args", "error", "expected_kind", "expected_message", "expected_retryable"),
    [
        (
            "load_model",
            (LoadModelRequest(model_key="model-a", context_length=4096, parallel=2),),
            TimeoutError(
                "https://localhost:1234/api/v1/load prompt secret-prompt instance_id=raw-load-1"
            ),
            ApiErrorKind.TIMEOUT,
            "request_timeout",
            True,
        ),
        (
            "unload_instance",
            (UnloadModelRequest(instance_ref=_safe_hash("raw-unload-2"), model_key="model-a"),),
            OSError("body secret-body path /api/v1/unload/raw-unload-2"),
            ApiErrorKind.NETWORK,
            "network_error",
            True,
        ),
        (
            "list_loaded_instances",
            (),
            RuntimeError("response_text leaked-response instance_id=raw-list-1 job_id=job-123"),
            ApiErrorKind.UNKNOWN,
            "transport_error",
            False,
        ),
    ],
)
def test_lifecycle_client_maps_transport_exceptions_without_leaking_raw_text(
    method_name: str,
    args: tuple[object, ...],
    error: Exception,
    expected_kind: ApiErrorKind,
    expected_message: str,
    expected_retryable: bool,
) -> None:
    transport = _CapturingJsonTransport(error=error)
    client = LifecycleClient(transport)

    result = getattr(client, method_name)(*args)

    assert result.error is not None
    assert result.error.kind == expected_kind
    assert result.error.message == expected_message
    assert result.error.retryable is expected_retryable
    for sentinel in (
        "https://localhost:1234/api/v1/load",
        "secret-prompt",
        "secret-body",
        "leaked-response",
        "raw-load-1",
        "raw-unload-2",
        "raw-list-1",
        "job-123",
        "/api/v1/unload/raw-unload-2",
        "instance_id",
    ):
        assert sentinel not in result.error.message
        assert sentinel not in repr(result.error)
        assert sentinel not in repr(result)


@pytest.mark.parametrize(
    (
        "method_name",
        "args",
        "transport_result",
        "expected_kind",
        "expected_message",
        "expected_retryable",
    ),
    [
        (
            "load_model",
            (LoadModelRequest(model_key="model-a", context_length=4096, parallel=2),),
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.HTTP_STATUS,
                    message="http_status",
                    status_code=503,
                    retryable=False,
                )
            ),
            ApiErrorKind.HTTP_STATUS,
            "http_status",
            False,
        ),
        (
            "unload_instance",
            (UnloadModelRequest(instance_ref=_safe_hash("raw-unload-3"), model_key="model-a"),),
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.NETWORK,
                    message="network_error",
                    retryable=True,
                )
            ),
            ApiErrorKind.NETWORK,
            "network_error",
            True,
        ),
        (
            "list_loaded_instances",
            (),
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.TIMEOUT,
                    message="request_timeout",
                    retryable=True,
                )
            ),
            ApiErrorKind.TIMEOUT,
            "request_timeout",
            True,
        ),
    ],
)
def test_lifecycle_client_maps_transport_results_to_safe_error_dtos(
    method_name: str,
    args: tuple[object, ...],
    transport_result: TransportResult,
    expected_kind: ApiErrorKind,
    expected_message: str,
    expected_retryable: bool,
) -> None:
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=transport_result,
            payload={"status": "success", "instance_id": "raw-instance"},
        )
    )
    client = LifecycleClient(transport)

    result = getattr(client, method_name)(*args)

    assert result.error is not None
    assert result.error.kind == expected_kind
    assert result.error.message == expected_message
    assert result.error.retryable is expected_retryable
    if expected_kind == ApiErrorKind.HTTP_STATUS:
        assert result.error.status_code == 503
    assert "raw-instance" not in repr(result)


def test_public_lifecycle_client_exports_stay_safe_and_private_payload_surface_is_not_exported() -> (
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

    client_public_names = {name for name in dir(LifecycleClient) if not name.startswith("_")}

    assert "LifecycleClient" in exported_names
    assert "_JsonTransportResult" not in exported_names
    assert forbidden_names.isdisjoint(dataclass_field_names)
    assert forbidden_names.isdisjoint(client_public_names)
