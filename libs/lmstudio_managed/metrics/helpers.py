"""Pure helpers aligning generation envelopes with metrics DTOs."""

from __future__ import annotations

from collections.abc import Sequence

from ..generation.api import GenerationResponseEnvelope
from ..validation.models import GenerationFailureKind, StructuredValidationStatus
from .models import (
    BatchMetrics,
    ModelScreeningVerdict,
    ParallelEvidence,
    RequestMetrics,
    ScreeningEvidence,
    SystemSummary,
)


def request_metrics_from_envelope(
    request_id: str,
    envelope: GenerationResponseEnvelope,
    *,
    total_elapsed_ms: float | None = None,
) -> RequestMetrics:
    total_tokens = None
    if envelope.input_tokens is not None or envelope.output_tokens is not None:
        total_tokens = (envelope.input_tokens or 0) + (envelope.output_tokens or 0)

    return RequestMetrics(
        request_id=request_id,
        finish_reason=envelope.finish_reason,
        error_category=envelope.error_kind.value if envelope.error_kind else None,
        failure_kind=envelope.error_kind,
        prompt_tokens=envelope.input_tokens,
        completion_tokens=envelope.output_tokens,
        total_tokens=total_tokens,
        total_elapsed_ms=total_elapsed_ms,
        response_chars=envelope.content_chars,
        raw_prompt_response_stored=False,
    )


def batch_metrics_from_request_metrics(
    request_metrics: Sequence[RequestMetrics],
    *,
    total_wall_time_ms: float | None = None,
) -> BatchMetrics:
    metrics = tuple(request_metrics)
    completion_tokens = [
        item.completion_tokens for item in metrics if item.completion_tokens is not None
    ]
    return BatchMetrics(
        request_count=len(metrics),
        business_pass_count=sum(1 for item in metrics if item.failure_kind is None),
        finish_length_count=sum(
            1 for item in metrics if item.failure_kind == GenerationFailureKind.FINISH_LENGTH
        ),
        structured_error_count=sum(
            1
            for item in metrics
            if item.failure_kind
            in {
                GenerationFailureKind.JSON_DECODE_ERROR,
                GenerationFailureKind.SCHEMA_ERROR,
                GenerationFailureKind.BUSINESS_ERROR,
            }
        ),
        total_wall_time_ms=total_wall_time_ms,
        total_completion_tokens=sum(completion_tokens) if completion_tokens else None,
    )


def build_screening_evidence(
    model_key: str,
    *,
    structured_status: StructuredValidationStatus | None = None,
    verdict: ModelScreeningVerdict | None = None,
    parallel_evidence: ParallelEvidence | None = None,
    batch_metrics: BatchMetrics | None = None,
    system_summary: SystemSummary | None = None,
    token_normalized_speedup: float | None = None,
) -> ScreeningEvidence:
    return ScreeningEvidence(
        model_key=model_key,
        structured_status=structured_status,
        verdict=verdict,
        parallel_evidence=parallel_evidence,
        batch_metrics=batch_metrics,
        system_summary=system_summary,
        token_normalized_speedup=token_normalized_speedup,
    )
