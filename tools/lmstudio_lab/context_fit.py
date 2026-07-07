from __future__ import annotations

import math
from dataclasses import dataclass


def _require_positive_int(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return value


def _require_ratio(value: float, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a number")
    normalized = float(value)
    if not 0 < normalized <= 1:
        raise ValueError(f"{field_name} must be > 0 and <= 1")
    return normalized


@dataclass(frozen=True, slots=True)
class ContextFitResult:
    required_tokens: int
    budget_tokens: int
    fits: bool
    safety_ratio: float
    effective_context_length: int

    def to_safe_dict(self) -> dict[str, int | float | bool]:
        return {
            "required_tokens": self.required_tokens,
            "budget_tokens": self.budget_tokens,
            "fits": self.fits,
            "safety_ratio": self.safety_ratio,
            "effective_context_length": self.effective_context_length,
        }


def evaluate_context_fit(
    *,
    estimated_input_tokens: int,
    max_tokens: int,
    effective_context_length: int,
    safety_ratio: float = 0.85,
) -> ContextFitResult:
    estimated_tokens = _require_positive_int(
        estimated_input_tokens,
        field_name="estimated_input_tokens",
    )
    max_output_tokens = _require_positive_int(max_tokens, field_name="max_tokens")
    context_length = _require_positive_int(
        effective_context_length,
        field_name="effective_context_length",
    )
    normalized_ratio = _require_ratio(safety_ratio, field_name="safety_ratio")

    required_tokens = estimated_tokens + max_output_tokens
    budget_tokens = math.floor(context_length * normalized_ratio)
    return ContextFitResult(
        required_tokens=required_tokens,
        budget_tokens=budget_tokens,
        fits=required_tokens <= budget_tokens,
        safety_ratio=normalized_ratio,
        effective_context_length=context_length,
    )


__all__ = ["ContextFitResult", "evaluate_context_fit"]
