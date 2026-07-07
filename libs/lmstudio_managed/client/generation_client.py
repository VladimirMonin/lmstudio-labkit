"""Fake-first generation client over an injected JSON transport seam."""

from __future__ import annotations

from collections.abc import Mapping

from .._safe import safe_hash_ref
from ..generation import (
    GenerationResponseEnvelope,
    PlainTextGenerationRequest,
    StructuredGenerationRequest,
    generation_envelope_from_fake_payload,
)
from ..validation import GenerationFailureKind
from .endpoint import EndpointKind, EndpointSpec, HttpMethod
from .errors import ApiErrorKind, SafeApiError
from .rest_client import (
    _build_transport_request,
    _coerce_json_result,
    _JsonTransportProtocol,
    _transport_exception_result,
)

_COMPAT_CHAT_ENDPOINT = EndpointSpec(
    kind=EndpointKind.COMPAT_CHAT,
    method=HttpMethod.POST,
    privacy_label="compat_chat",
)


class GenerationClient:
    """Privacy-safe generation client for compat chat completion endpoints."""

    __slots__ = ("_transport", "_default_timeout_s")

    def __init__(
        self,
        transport: _JsonTransportProtocol,
        *,
        default_timeout_s: float | None = None,
    ) -> None:
        self._transport = transport
        self._default_timeout_s = default_timeout_s

    def complete_structured(
        self,
        request: StructuredGenerationRequest,
        timeout_s: float | None = None,
    ) -> GenerationResponseEnvelope:
        return self._complete(
            payload_kind="structured_generation",
            payload_hash=_structured_request_hash(request),
            timeout_s=timeout_s,
        )

    def complete_plain_text(
        self,
        request: PlainTextGenerationRequest,
        timeout_s: float | None = None,
    ) -> GenerationResponseEnvelope:
        return self._complete(
            payload_kind="plain_text_generation",
            payload_hash=_plain_text_request_hash(request),
            timeout_s=timeout_s,
        )

    def _complete(
        self,
        *,
        payload_kind: str,
        payload_hash: str | None,
        timeout_s: float | None,
    ) -> GenerationResponseEnvelope:
        transport_request = _build_transport_request(
            _COMPAT_CHAT_ENDPOINT,
            payload_kind=payload_kind,
            payload_hash=payload_hash,
            timeout_s=timeout_s,
            default_timeout_s=self._default_timeout_s,
        )

        try:
            raw_result = self._transport(transport_request)
        except Exception as error:
            return _failure_envelope_from_api_error(_transport_exception_result(error).error)

        transport_result, payload = _coerce_json_result(raw_result)
        if transport_result is None:
            return _failure_envelope(GenerationFailureKind.UNKNOWN)

        if not transport_result.ok:
            return _failure_envelope_from_api_error(transport_result.error)

        if not isinstance(payload, Mapping):
            return _failure_envelope(GenerationFailureKind.UNKNOWN)

        try:
            return generation_envelope_from_fake_payload(payload)
        except Exception:
            return _failure_envelope(GenerationFailureKind.UNKNOWN)


def _structured_request_hash(request: StructuredGenerationRequest) -> str | None:
    return _request_identity_hash(
        model_key=request.model_key,
        profile_id=request.profile_id,
        prompt_hash=request.prompt_hash,
        max_tokens=request.max_tokens,
        response_format=request.response_format.value,
    )


def _plain_text_request_hash(request: PlainTextGenerationRequest) -> str | None:
    return _request_identity_hash(
        model_key=request.model_key,
        profile_id=request.profile_id,
        prompt_hash=request.prompt_hash,
        max_tokens=request.max_tokens,
        response_format=None,
    )


def _request_identity_hash(
    *,
    model_key: str,
    profile_id: str,
    prompt_hash: str,
    max_tokens: int | None,
    response_format: str | None,
) -> str | None:
    return safe_hash_ref(
        "|".join(
            (
                f"model_key={model_key}",
                f"profile_id={profile_id}",
                f"prompt_hash={prompt_hash}",
                f"max_tokens={max_tokens}",
                f"response_format={response_format or ''}",
            )
        )
    )


def _failure_envelope_from_api_error(error: SafeApiError | None) -> GenerationResponseEnvelope:
    if error is None:
        return _failure_envelope(GenerationFailureKind.UNKNOWN)
    return _failure_envelope(_generation_failure_kind_from_api_error(error.kind))


def _generation_failure_kind_from_api_error(error_kind: ApiErrorKind) -> GenerationFailureKind:
    if error_kind == ApiErrorKind.TIMEOUT:
        return GenerationFailureKind.TIMEOUT
    if error_kind in {
        ApiErrorKind.HTTP_STATUS,
        ApiErrorKind.NETWORK,
        ApiErrorKind.PROVIDER_ERROR,
        ApiErrorKind.AUTH_REQUIRED,
    }:
        return GenerationFailureKind.HTTP_ERROR
    return GenerationFailureKind.UNKNOWN


def _failure_envelope(error_kind: GenerationFailureKind) -> GenerationResponseEnvelope:
    return GenerationResponseEnvelope(
        content_empty=True,
        content_chars=0,
        content_hash=None,
        reasoning_content_present=False,
        finish_reason=None,
        input_tokens=None,
        output_tokens=None,
        error_kind=error_kind,
    )
