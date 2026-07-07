"""Generic validation result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GenerationFailureKind(StrEnum):
    EMPTY_CONTENT = "empty_content"
    REASONING_CONTENT_ONLY = "reasoning_content_only"
    FINISH_LENGTH = "finish_length"
    JSON_DECODE_ERROR = "json_decode_error"
    SCHEMA_ERROR = "schema_error"
    BUSINESS_ERROR = "business_error"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    UNKNOWN = "unknown"


class ReasoningRoutingStatus(StrEnum):
    NONE_DETECTED = "none_detected"
    CONTENT_AND_REASONING = "content_and_reasoning"
    REASONING_ONLY = "reasoning_only"
    CONTENT_ONLY = "content_only"
    UNKNOWN = "unknown"


class StructuredValidationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"


@dataclass(frozen=True, slots=True)
class StructuredValidationResult:
    json_parse_pass: bool
    schema_pass: bool
    business_pass: bool
    finish_reason: str | None = None
    failure_kind: GenerationFailureKind | None = None
    reasoning_routing: ReasoningRoutingStatus = ReasoningRoutingStatus.UNKNOWN
    expected_count: int | None = None
    observed_count: int | None = None

    @property
    def passed(self) -> bool:
        return (
            self.json_parse_pass
            and self.schema_pass
            and self.business_pass
            and self.failure_kind is None
        )


@dataclass(frozen=True, slots=True)
class PlainTextValidationResult:
    non_empty_text_pass: bool
    finish_reason: str | None = None
    failure_kind: GenerationFailureKind | None = None
    reasoning_routing: ReasoningRoutingStatus = ReasoningRoutingStatus.UNKNOWN
    word_count: int | None = None

    @property
    def passed(self) -> bool:
        return self.non_empty_text_pass and self.failure_kind is None


def failure_kind_from_lab_category(
    category: str | None,
    *,
    content_empty: bool | None = None,
    reasoning_content_present: bool | None = None,
    finish_reason: str | None = None,
) -> GenerationFailureKind | None:
    if finish_reason and finish_reason.lower() == "length":
        return GenerationFailureKind.FINISH_LENGTH

    if category is None:
        return None

    normalized = category.strip().lower()
    if normalized == "empty":
        if content_empty and reasoning_content_present:
            return GenerationFailureKind.REASONING_CONTENT_ONLY
        return GenerationFailureKind.EMPTY_CONTENT
    if normalized in {"finish", "finish_reason", "length"}:
        return GenerationFailureKind.FINISH_LENGTH
    if normalized == "timeout":
        return GenerationFailureKind.TIMEOUT
    if normalized in {"json", "json_decode", "json_decode_error"}:
        return GenerationFailureKind.JSON_DECODE_ERROR
    if normalized == "schema":
        return GenerationFailureKind.SCHEMA_ERROR
    if normalized == "business":
        return GenerationFailureKind.BUSINESS_ERROR
    if normalized == "http":
        return GenerationFailureKind.HTTP_ERROR
    if normalized == "unknown":
        return GenerationFailureKind.UNKNOWN
    return GenerationFailureKind.UNKNOWN


__all__ = [
    "GenerationFailureKind",
    "PlainTextValidationResult",
    "ReasoningRoutingStatus",
    "StructuredValidationResult",
    "StructuredValidationStatus",
    "failure_kind_from_lab_category",
]
