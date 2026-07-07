from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_CHARS_PER_TOKEN = 3.0


@dataclass(slots=True, frozen=True)
class TokenizerSpec:
    method: str
    family: str
    version: str


DEFAULT_TOKENIZER_SPEC = TokenizerSpec(
    method="heuristic",
    family="generic",
    version="1.0",
)


def _require_non_negative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


def _require_positive_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be > 0")
    numeric = float(value)
    if numeric <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return numeric


def estimate_input_tokens_from_chars(
    chars: int,
    *,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> int:
    normalized_chars = _require_non_negative_int(chars, field_name="chars")
    normalized_chars_per_token = _require_positive_number(
        chars_per_token,
        field_name="chars_per_token",
    )
    if normalized_chars == 0:
        return 0
    return max(1, math.ceil(normalized_chars / normalized_chars_per_token))


def calculate_estimate_error_ratio(
    estimated_input_tokens: int,
    actual_input_tokens: int | None,
) -> float | None:
    if actual_input_tokens is None:
        return None

    estimated = _require_non_negative_int(
        estimated_input_tokens,
        field_name="estimated_input_tokens",
    )
    actual = _require_non_negative_int(
        actual_input_tokens,
        field_name="actual_input_tokens",
    )
    if actual <= 0:
        raise ValueError("actual_input_tokens must be > 0")
    return abs(estimated - actual) / actual


__all__ = [
    "DEFAULT_CHARS_PER_TOKEN",
    "DEFAULT_TOKENIZER_SPEC",
    "TokenizerSpec",
    "calculate_estimate_error_ratio",
    "estimate_input_tokens_from_chars",
]
