from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from hashlib import sha256

import pytest

import libs.lmstudio_managed.client as client_pkg
from libs.lmstudio_managed.client import (
    ApiErrorKind,
    EndpointKind,
    EndpointSpec,
    GenerationClient,
    HttpMethod,
    SafeApiError,
    TransportRequest,
    TransportResponse,
    TransportResult,
)
from libs.lmstudio_managed.generation import (
    GenerationResponseEnvelope,
    PlainTextGenerationRequest,
    ResponseFormatKind,
    StructuredGenerationRequest,
)
from libs.lmstudio_managed.validation import GenerationFailureKind


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


def _endpoint() -> EndpointSpec:
    return EndpointSpec(
        kind=EndpointKind.COMPAT_CHAT,
        method=HttpMethod.POST,
        privacy_label="compat_chat",
    )


def _structured_request() -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        model_key="model-structured",
        response_format=ResponseFormatKind.JSON_SCHEMA,
        prompt_hash=_safe_hash("prompt-structured"),
        prompt_chars=144,
        max_tokens=256,
        profile_id="structured-default",
    )


def _plain_request() -> PlainTextGenerationRequest:
    return PlainTextGenerationRequest(
        model_key="model-plain",
        prompt_hash=_safe_hash("prompt-plain"),
        prompt_chars=96,
        max_tokens=128,
        profile_id="plain-default",
    )


def _structured_request_hash(request: StructuredGenerationRequest) -> str:
    return _safe_hash(
        "|".join(
            (
                f"model_key={request.model_key}",
                f"profile_id={request.profile_id}",
                f"prompt_hash={request.prompt_hash}",
                f"max_tokens={request.max_tokens}",
                f"response_format={request.response_format.value}",
            )
        )
    )


def _plain_request_hash(request: PlainTextGenerationRequest) -> str:
    return _safe_hash(
        "|".join(
            (
                f"model_key={request.model_key}",
                f"profile_id={request.profile_id}",
                f"prompt_hash={request.prompt_hash}",
                f"max_tokens={request.max_tokens}",
                "response_format=",
            )
        )
    )


def _assert_no_raw_leak(envelope: GenerationResponseEnvelope, *sentinels: str) -> None:
    safe_values = [
        str(getattr(envelope, field.name)) for field in fields(GenerationResponseEnvelope)
    ]
    for sentinel in sentinels:
        assert sentinel not in repr(envelope)
        for value in safe_values:
            assert sentinel not in value


def test_complete_structured_sends_safe_post_request_and_parses_summary_envelope() -> None:
    request = _structured_request()
    transport = _CapturingJsonTransport()
    client = GenerationClient(transport, default_timeout_s=4.0)
    raw_content = '{"answer": 42}'
    raw_reasoning = "reasoning-structured-secret"
    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=_endpoint(),
                status_code=200,
                body_hash=_safe_hash("structured-body"),
                body_chars=96,
                schema_name="CompatChatResponse",
            )
        ),
        payload={
            "content": raw_content,
            "reasoning_content": raw_reasoning,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 11, "completion_tokens": 22},
            "prompt": "raw-prompt-structured",
            "messages": [
                {"role": "user", "content": "raw-message-structured"},
            ],
            "body": "raw-body-structured",
        },
    )

    envelope = client.complete_structured(request)

    assert envelope.content_empty is False
    assert envelope.content_chars == len(raw_content)
    assert envelope.content_hash == _safe_hash(raw_content)
    assert envelope.reasoning_content_present is True
    assert envelope.finish_reason == "stop"
    assert envelope.input_tokens == 11
    assert envelope.output_tokens == 22
    assert envelope.error_kind is None
    assert len(transport.requests) == 1
    safe_request = transport.requests[0]
    assert safe_request.endpoint.kind == EndpointKind.COMPAT_CHAT
    assert safe_request.endpoint.method == HttpMethod.POST
    assert safe_request.endpoint.privacy_label == "compat_chat"
    assert safe_request.payload_kind == "structured_generation"
    assert safe_request.payload_hash == _structured_request_hash(request)
    assert safe_request.timeout_s == 4.0
    _assert_no_raw_leak(
        envelope,
        raw_content,
        raw_reasoning,
        "raw-prompt-structured",
        "raw-message-structured",
        "raw-body-structured",
    )


def test_complete_plain_text_sends_safe_post_request_and_maps_reasoning_and_finish_failures() -> (
    None
):
    request = _plain_request()
    transport = _CapturingJsonTransport()
    client = GenerationClient(transport, default_timeout_s=7.0)
    raw_content = "plain answer"
    transport.result = _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=_endpoint(),
                status_code=200,
                body_hash=_safe_hash("plain-body"),
                body_chars=72,
                schema_name="CompatChatResponse",
            )
        ),
        payload={
            "choices": [
                {
                    "message": {
                        "content": raw_content,
                        "reasoning_content": "reasoning-only-secret",
                    },
                    "finish_reason": "length",
                }
            ],
            "finish_reason": "length",
            "usage": {"input_tokens": 5, "output_tokens": 8},
            "messages": ["raw-message-plain"],
            "prompt": "raw-prompt-plain",
        },
    )

    envelope = client.complete_plain_text(request, timeout_s=1.5)

    assert envelope.content_empty is False
    assert envelope.content_chars == len(raw_content)
    assert envelope.content_hash == _safe_hash(raw_content)
    assert envelope.reasoning_content_present is True
    assert envelope.finish_reason == "length"
    assert envelope.input_tokens == 5
    assert envelope.output_tokens == 8
    assert envelope.error_kind == GenerationFailureKind.FINISH_LENGTH
    assert len(transport.requests) == 1
    safe_request = transport.requests[0]
    assert safe_request.endpoint.kind == EndpointKind.COMPAT_CHAT
    assert safe_request.endpoint.method == HttpMethod.POST
    assert safe_request.endpoint.privacy_label == "compat_chat"
    assert safe_request.payload_kind == "plain_text_generation"
    assert safe_request.payload_hash == _plain_request_hash(request)
    assert safe_request.timeout_s == 1.5
    _assert_no_raw_leak(
        envelope,
        raw_content,
        "reasoning-only-secret",
        "raw-message-plain",
        "raw-prompt-plain",
    )


def test_complete_plain_text_maps_reasoning_only_empty_payload_to_safe_failure_kind() -> None:
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(),
                    status_code=200,
                    body_hash=_safe_hash("reasoning-only"),
                    body_chars=40,
                    schema_name="CompatChatResponse",
                )
            ),
            payload={
                "choices": [{"message": {"reasoning_content": "hidden-chain"}}],
                "error_category": "empty",
                "prompt": "raw-prompt-reasoning-only",
            },
        )
    )
    client = GenerationClient(transport)

    envelope = client.complete_plain_text(_plain_request())

    assert envelope.content_empty is True
    assert envelope.content_chars == 0
    assert envelope.content_hash is None
    assert envelope.reasoning_content_present is True
    assert envelope.finish_reason is None
    assert envelope.input_tokens is None
    assert envelope.output_tokens is None
    assert envelope.error_kind == GenerationFailureKind.REASONING_CONTENT_ONLY
    _assert_no_raw_leak(envelope, "hidden-chain", "raw-prompt-reasoning-only")


def test_complete_plain_text_maps_nested_finish_reason_length_without_top_level_value() -> None:
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(),
                    status_code=200,
                    body_hash=_safe_hash("nested-finish-reason"),
                    body_chars=64,
                    schema_name="CompatChatResponse",
                )
            ),
            payload={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "hidden-chain-nested",
                        },
                        "finish_reason": "length",
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 7},
                "prompt": "raw-prompt-nested-finish-reason",
            },
        )
    )
    client = GenerationClient(transport)

    envelope = client.complete_plain_text(_plain_request())

    assert envelope.content_empty is True
    assert envelope.content_chars == 0
    assert envelope.content_hash is None
    assert envelope.reasoning_content_present is True
    assert envelope.finish_reason == "length"
    assert envelope.input_tokens == 3
    assert envelope.output_tokens == 7
    assert envelope.error_kind == GenerationFailureKind.FINISH_LENGTH
    _assert_no_raw_leak(
        envelope,
        "hidden-chain-nested",
        "raw-prompt-nested-finish-reason",
    )


@pytest.mark.parametrize(
    ("transport_result", "expected_error_kind"),
    [
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.TIMEOUT,
                    message="request_timeout",
                    retryable=True,
                )
            ),
            GenerationFailureKind.TIMEOUT,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.HTTP_STATUS,
                    message="http_status",
                    status_code=503,
                    retryable=False,
                )
            ),
            GenerationFailureKind.HTTP_ERROR,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.NETWORK,
                    message="network_error",
                    retryable=True,
                )
            ),
            GenerationFailureKind.HTTP_ERROR,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.PROVIDER_ERROR,
                    message="provider_error",
                    retryable=False,
                )
            ),
            GenerationFailureKind.HTTP_ERROR,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.AUTH_REQUIRED,
                    message="auth_required",
                    retryable=False,
                )
            ),
            GenerationFailureKind.HTTP_ERROR,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.UNEXPECTED_SCHEMA,
                    message="unexpected_schema",
                    retryable=False,
                )
            ),
            GenerationFailureKind.UNKNOWN,
        ),
        (
            TransportResult(
                error=SafeApiError(
                    kind=ApiErrorKind.UNKNOWN,
                    message="transport_error",
                    retryable=False,
                )
            ),
            GenerationFailureKind.UNKNOWN,
        ),
    ],
)
def test_generation_client_maps_transport_errors_to_safe_failure_envelopes(
    transport_result: TransportResult,
    expected_error_kind: GenerationFailureKind,
) -> None:
    transport = _CapturingJsonTransport(
        result=_TransportEnvelope(
            transport_result=transport_result,
            payload={
                "content": "raw-content-should-not-leak",
                "reasoning_content": "raw-reasoning-should-not-leak",
            },
        )
    )
    client = GenerationClient(transport)

    envelope = client.complete_structured(_structured_request())

    assert envelope.content_empty is True
    assert envelope.content_chars == 0
    assert envelope.content_hash is None
    assert envelope.reasoning_content_present is False
    assert envelope.finish_reason is None
    assert envelope.input_tokens is None
    assert envelope.output_tokens is None
    assert envelope.error_kind == expected_error_kind
    _assert_no_raw_leak(
        envelope,
        "raw-content-should-not-leak",
        "raw-reasoning-should-not-leak",
        "unexpected_schema",
        "transport_error",
        "auth_required",
    )


@pytest.mark.parametrize(
    ("error", "expected_error_kind"),
    [
        (
            TimeoutError(
                "https://localhost:1234/v1/chat/completions prompt secret-prompt response_text=raw"
            ),
            GenerationFailureKind.TIMEOUT,
        ),
        (
            OSError("body secret-body path /v1/chat/completions messages raw-message"),
            GenerationFailureKind.HTTP_ERROR,
        ),
        (
            RuntimeError("response_text leaked-response job_id=job-123 instance_id=instance-7"),
            GenerationFailureKind.UNKNOWN,
        ),
    ],
)
def test_generation_client_maps_transport_exceptions_without_leaking_raw_text(
    error: Exception,
    expected_error_kind: GenerationFailureKind,
) -> None:
    transport = _CapturingJsonTransport(error=error)
    client = GenerationClient(transport)

    envelope = client.complete_plain_text(_plain_request())

    assert envelope.content_empty is True
    assert envelope.content_chars == 0
    assert envelope.content_hash is None
    assert envelope.reasoning_content_present is False
    assert envelope.finish_reason is None
    assert envelope.input_tokens is None
    assert envelope.output_tokens is None
    assert envelope.error_kind == expected_error_kind
    _assert_no_raw_leak(
        envelope,
        "https://localhost:1234/v1/chat/completions",
        "secret-prompt",
        "secret-body",
        "raw-message",
        "leaked-response",
        "job-123",
        "instance-7",
        "/v1/chat/completions",
    )


@pytest.mark.parametrize(
    "raw_result",
    [
        object(),
        _TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(),
                    status_code=200,
                    body_hash=_safe_hash("schema"),
                    body_chars=8,
                    schema_name="CompatChatResponse",
                )
            ),
            payload=None,
        ),
        _TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(),
                    status_code=200,
                    body_hash=_safe_hash("schema-list"),
                    body_chars=8,
                    schema_name="CompatChatResponse",
                )
            ),
            payload=[],
        ),
        _TransportEnvelope(
            transport_result=TransportResult(
                response=TransportResponse(
                    endpoint=_endpoint(),
                    status_code=200,
                    body_hash=_safe_hash("schema-text"),
                    body_chars=8,
                    schema_name="CompatChatResponse",
                )
            ),
            payload="bad-payload",
        ),
    ],
)
def test_generation_client_maps_bad_payloads_to_safe_unknown_failures(raw_result: object) -> None:
    transport = _CapturingJsonTransport(result=raw_result)
    client = GenerationClient(transport)

    envelope = client.complete_structured(_structured_request())

    assert envelope.content_empty is True
    assert envelope.content_chars == 0
    assert envelope.content_hash is None
    assert envelope.reasoning_content_present is False
    assert envelope.finish_reason is None
    assert envelope.input_tokens is None
    assert envelope.output_tokens is None
    assert envelope.error_kind == GenerationFailureKind.UNKNOWN


def test_public_generation_client_exports_stay_safe_and_private_payload_surface_is_not_exported() -> (
    None
):
    forbidden_names = {
        "payload",
        "url",
        "path",
        "body",
        "prompt",
        "messages",
        "content",
        "response_text",
        "instance_id",
        "job_id",
    }
    allowed_safe_names = {"content_empty", "content_chars", "content_hash"}

    exported_names = set(client_pkg.__all__)
    exported_objects = [getattr(client_pkg, name) for name in exported_names]
    dataclass_field_names: set[str] = set()
    for exported in exported_objects:
        if is_dataclass(exported):
            dataclass_field_names.update(field.name for field in fields(exported))

    generation_envelope_field_names = {field.name for field in fields(GenerationResponseEnvelope)}
    client_public_names = {name for name in dir(GenerationClient) if not name.startswith("_")}

    assert "GenerationClient" in exported_names
    assert "generation_envelope_from_fake_payload" not in exported_names
    assert "_JsonTransportResult" not in exported_names
    assert forbidden_names.isdisjoint(dataclass_field_names)
    assert forbidden_names.isdisjoint(client_public_names)
    assert forbidden_names.isdisjoint(generation_envelope_field_names - allowed_safe_names)
