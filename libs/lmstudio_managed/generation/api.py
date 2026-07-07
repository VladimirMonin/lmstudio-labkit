"""Pure generation REST contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .._safe import as_int, as_str, safe_text_hash
from ..validation.models import GenerationFailureKind, failure_kind_from_lab_category
from .contracts import ResponseFormatKind


@dataclass(frozen=True, slots=True)
class StructuredGenerationRequest:
    model_key: str
    response_format: ResponseFormatKind
    prompt_hash: str
    prompt_chars: int
    max_tokens: int | None
    profile_id: str


@dataclass(frozen=True, slots=True)
class PlainTextGenerationRequest:
    model_key: str
    prompt_hash: str
    prompt_chars: int
    max_tokens: int | None
    profile_id: str


@dataclass(frozen=True, slots=True)
class ReasoningEnvelope:
    content_empty: bool
    reasoning_content_present: bool


@dataclass(frozen=True, slots=True)
class GenerationResponseEnvelope:
    content_empty: bool
    content_chars: int
    content_hash: str | None
    reasoning_content_present: bool
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    error_kind: GenerationFailureKind | None = None


def generation_envelope_from_fake_payload(
    payload: Mapping[str, object],
) -> GenerationResponseEnvelope:
    content = _extract_content(payload)
    content_chars = len(content)
    reasoning_present = _reasoning_content_present(payload)
    reasoning = ReasoningEnvelope(
        content_empty=content_chars == 0,
        reasoning_content_present=reasoning_present,
    )
    finish_reason = _extract_finish_reason(payload)
    error_kind = _error_kind_from_payload(
        payload,
        content_empty=reasoning.content_empty,
        reasoning_content_present=reasoning.reasoning_content_present,
        finish_reason=finish_reason,
    )

    return GenerationResponseEnvelope(
        content_empty=reasoning.content_empty,
        content_chars=content_chars,
        content_hash=safe_text_hash(content) if content else None,
        reasoning_content_present=reasoning.reasoning_content_present,
        finish_reason=finish_reason,
        input_tokens=_extract_usage_token(payload, "prompt_tokens", "input_tokens"),
        output_tokens=_extract_usage_token(payload, "completion_tokens", "output_tokens"),
        error_kind=error_kind,
    )


def _extract_content(payload: Mapping[str, object]) -> str:
    direct = as_str(payload.get("content")) or as_str(payload.get("text"))
    if direct is not None:
        return direct

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, Mapping):
            message = first_choice.get("message")
            if isinstance(message, Mapping):
                return as_str(message.get("content")) or ""
            return as_str(first_choice.get("text")) or ""
    return ""


def _reasoning_content_present(payload: Mapping[str, object]) -> bool:
    if payload.get("reasoning_content_present") is True:
        return True
    if as_str(payload.get("reasoning_content")):
        return True

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, Mapping):
            message = first_choice.get("message")
            if isinstance(message, Mapping) and as_str(message.get("reasoning_content")):
                return True
    return False


def _extract_finish_reason(payload: Mapping[str, object]) -> str | None:
    finish_reason = as_str(payload.get("finish_reason"))
    if finish_reason is not None:
        return finish_reason

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, Mapping):
            return as_str(first_choice.get("finish_reason"))
    return None


def _extract_usage_token(payload: Mapping[str, object], *keys: str) -> int | None:
    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        for key in keys:
            value = as_int(usage.get(key))
            if value is not None:
                return value
    for key in keys:
        value = as_int(payload.get(key))
        if value is not None:
            return value
    return None


def _error_kind_from_payload(
    payload: Mapping[str, object],
    *,
    content_empty: bool,
    reasoning_content_present: bool,
    finish_reason: str | None,
) -> GenerationFailureKind | None:
    if payload.get("timeout") is True:
        return GenerationFailureKind.TIMEOUT
    if as_int(payload.get("http_status")) is not None:
        return GenerationFailureKind.HTTP_ERROR

    explicit = as_str(payload.get("error_kind")) or as_str(payload.get("error_category"))
    if explicit is not None:
        return failure_kind_from_lab_category(
            explicit,
            content_empty=content_empty,
            reasoning_content_present=reasoning_content_present,
            finish_reason=finish_reason,
        )

    if finish_reason is not None and finish_reason.lower() == "length":
        return GenerationFailureKind.FINISH_LENGTH
    return None
