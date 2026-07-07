"""Validation result contracts."""

from .factual_blocks import FactualBlocksValidationResult, ValidationErrorCategory
from .models import (
    GenerationFailureKind,
    PlainTextValidationResult,
    ReasoningRoutingStatus,
    StructuredValidationResult,
    StructuredValidationStatus,
    failure_kind_from_lab_category,
)

__all__ = [
    "FactualBlocksValidationResult",
    "GenerationFailureKind",
    "PlainTextValidationResult",
    "ReasoningRoutingStatus",
    "StructuredValidationResult",
    "StructuredValidationStatus",
    "ValidationErrorCategory",
    "failure_kind_from_lab_category",
]
