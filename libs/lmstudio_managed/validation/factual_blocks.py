"""Safe factual-block validation summaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ValidationErrorCategory(StrEnum):
    JSON = "json"
    SCHEMA = "schema"
    BUSINESS = "business"
    REASONING = "reasoning"
    EMPTY = "empty"
    FINISH = "finish"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FactualBlocksValidationResult:
    json_parse_pass: bool
    schema_pass: bool
    business_pass: bool
    ids_exact_pass: bool
    finish_reason: str | None = None
    error_category: ValidationErrorCategory | None = None
    expected_count: int | None = None
    observed_count: int | None = None

    @property
    def passed(self) -> bool:
        return (
            self.json_parse_pass
            and self.schema_pass
            and self.business_pass
            and self.ids_exact_pass
            and self.error_category is None
        )
