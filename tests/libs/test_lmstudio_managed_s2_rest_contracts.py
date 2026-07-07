from __future__ import annotations

from dataclasses import fields
from hashlib import sha256

import pytest

from libs.lmstudio_managed.client import (
    ApiErrorKind,
    EndpointKind,
    EndpointSpec,
    HttpMethod,
    SafeApiError,
    TransportRequest,
    TransportResponse,
    TransportResult,
)
from libs.lmstudio_managed.download import (
    DownloadErrorKind,
    DownloadStatus,
    classify_download_payload,
    download_progress_event_from_payload,
    download_result_from_payload,
)
from libs.lmstudio_managed.generation import (
    GenerationResponseEnvelope,
    PlainTextGenerationRequest,
    ResponseFormatKind,
    StructuredGenerationRequest,
    generation_envelope_from_fake_payload,
)
from libs.lmstudio_managed.lifecycle import (
    LoadConfig,
    LoadConfigEcho,
    UnloadModelRequest,
    build_model_load_verification,
    validate_parallel_contract,
)
from libs.lmstudio_managed.metrics import (
    ModelScreeningVerdict,
    batch_metrics_from_request_metrics,
    build_screening_evidence,
    request_metrics_from_envelope,
)
from libs.lmstudio_managed.registry import (
    parse_compat_model_list,
    parse_native_model_list,
)
from libs.lmstudio_managed.validation import (
    GenerationFailureKind,
    StructuredValidationStatus,
)


def _safe_hash(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def test_transport_contracts_keep_only_safe_summary_fields() -> None:
    endpoint = EndpointSpec(
        kind=EndpointKind.COMPAT_MODELS,
        method=HttpMethod.GET,
        privacy_label="compat_models",
    )
    request = TransportRequest(
        endpoint=endpoint,
        payload_kind="model_list",
        payload_hash=_safe_hash("payload"),
        timeout_s=5.0,
    )
    response = TransportResponse(
        endpoint=endpoint,
        status_code=200,
        body_hash=_safe_hash("body"),
        body_chars=42,
        schema_name="ModelListResponse",
    )
    ok_result = TransportResult(response=response)
    error = SafeApiError(kind=ApiErrorKind.TIMEOUT, message="request_timeout", retryable=True)
    error_result = TransportResult(error=error)

    assert ok_result.ok is True
    assert ok_result.error_kind is None
    assert error_result.ok is False
    assert error_result.error_kind == ApiErrorKind.TIMEOUT
    assert request.payload_kind == "model_list"

    request_field_names = {field.name for field in fields(TransportRequest)}
    response_field_names = {field.name for field in fields(TransportResponse)}
    assert {"url", "path", "body", "prompt"}.isdisjoint(request_field_names)
    assert {"url", "path", "body", "content", "response"}.isdisjoint(response_field_names)


def test_parse_compat_model_list_returns_visible_models_only() -> None:
    response = parse_compat_model_list(
        {
            "data": [
                {"id": "qwen-text", "owned_by": "lm-studio"},
                {"id": "other-model", "owned_by": "external"},
            ]
        }
    )

    assert response.endpoint_kind == EndpointKind.COMPAT_MODELS
    assert response.error is None
    assert response.native_models == ()
    assert response.visible_models[0].model_id == "qwen-text"
    assert response.visible_models[0].owned_by_lmstudio is True
    assert response.visible_models[1].owned_by_lmstudio is False


def test_parse_native_model_list_hashes_instance_ids_and_keeps_missing_quantization_none() -> None:
    response = parse_native_model_list(
        {
            "data": [
                {
                    "modelKey": "qwen-native",
                    "format": "gguf",
                    "bitsPerWeight": 4.5,
                    "sizeBytes": 1024,
                    "loadedInstances": [
                        {
                            "id": "raw-instance-1",
                            "contextLength": 8192,
                            "numParallelSequences": 2,
                        },
                        {
                            "id": "raw-instance-2",
                            "contextLength": 4096,
                            "numParallelSequences": 1,
                            "ownedByUs": False,
                        },
                    ],
                },
                {
                    "modelKey": "idle-native",
                    "format": "gguf",
                    "bitsPerWeight": 8,
                    "sizeBytes": 2048,
                    "loadedInstances": [],
                },
            ]
        }
    )

    assert response.error is None
    assert response.endpoint_kind == EndpointKind.NATIVE_MODELS
    assert response.visible_models[0].model_id == "qwen-native"
    assert response.native_models[0].quantization is None
    assert response.native_models[0].loaded_instances[0].instance_ref == _safe_hash(
        "raw-instance-1"
    )
    assert response.native_models[0].loaded_instances[0].context_length == 8192
    assert response.native_models[0].loaded_instances[0].parallel == 2
    assert response.native_models[0].loaded_instances[1].owned_by_us is False
    assert response.native_models[1].loaded_instances == ()
    assert "raw-instance-1" not in response.native_models[0].loaded_instances[0].instance_ref


def test_download_contracts_classify_safe_statuses_and_job_refs() -> None:
    already = classify_download_payload({"status": "already_downloaded"})
    in_progress = classify_download_payload(
        {
            "status": "downloading",
            "job_id": "job-123",
            "downloaded_bytes": 50,
            "total_bytes": 200,
        }
    )
    paused = classify_download_payload(
        {
            "status": "paused",
            "job_id": "job-456",
            "downloaded_bytes": 75,
            "total_bytes": 200,
        }
    )
    completed = download_result_from_payload({"status": "completed"})
    failed = classify_download_payload({"status": "failed", "error_kind": "disk_full"})
    missing_job = classify_download_payload({"status": "downloading"})
    progress = download_progress_event_from_payload(
        {
            "status": "downloading",
            "job_id": "job-123",
            "downloaded_bytes": 50,
            "total_bytes": 200,
        }
    )
    paused_progress = download_progress_event_from_payload(
        {
            "status": "paused",
            "job_id": "job-456",
            "downloaded_bytes": 75,
            "total_bytes": 200,
        }
    )
    paused_result = download_result_from_payload(
        {
            "status": "paused",
            "job_id": "job-456",
        }
    )

    assert already.status == DownloadStatus.ALREADY_DOWNLOADED
    assert already.ready_on_disk is True
    assert in_progress.status == DownloadStatus.IN_PROGRESS
    assert in_progress.job_ref == _safe_hash("job-123")
    assert paused.status == DownloadStatus.PAUSED
    assert paused.job_ref == _safe_hash("job-456")
    assert completed.ready_on_disk is True
    assert completed.is_terminal_success is True
    assert failed.error_kind == DownloadErrorKind.DISK_FULL
    assert missing_job.error_kind == DownloadErrorKind.UNEXPECTED_SCHEMA
    assert progress.progress_percent == pytest.approx(25.0)
    assert paused_progress.status == DownloadStatus.PAUSED
    assert paused_progress.progress_percent == pytest.approx(37.5)
    assert paused_result.status == DownloadStatus.PAUSED
    assert paused_result.is_terminal_success is False
    assert "job_id" not in {field.name for field in fields(type(in_progress))}


def test_lifecycle_load_verification_and_exact_unload_contracts() -> None:
    requested = LoadConfig(model_key="model-a", context_length=4096, parallel=2)
    sufficient = build_model_load_verification(
        requested,
        echo=LoadConfigEcho(context_length=8192, parallel=3),
    )
    insufficient = build_model_load_verification(
        requested,
        observed=parse_native_model_list(
            {
                "data": [
                    {
                        "modelKey": "model-a",
                        "loadedInstances": [
                            {
                                "id": "raw-a",
                                "contextLength": 2048,
                                "numParallelSequences": 1,
                            },
                            {
                                "id": "raw-b",
                                "contextLength": 2048,
                                "numParallelSequences": 1,
                            },
                        ],
                    }
                ]
            }
        )
        .native_models[0]
        .loaded_instances[0],
    )
    exact = UnloadModelRequest(instance_ref=_safe_hash("raw-a"), model_key="model-a")

    assert sufficient.config_sufficient is True
    assert sufficient.context_length_verified is True
    assert sufficient.parallel_verified is True
    assert insufficient.config_sufficient is False
    assert insufficient.failure_reason == "context_length_insufficient+parallel_insufficient"
    assert exact.instance_ref == _safe_hash("raw-a")
    with pytest.raises(ValueError):
        UnloadModelRequest(instance_ref="*", model_key="model-a")
    with pytest.raises(ValueError):
        UnloadModelRequest(instance_ref=" All ", model_key="model-a")


def test_generation_requests_and_response_envelope_stay_safe() -> None:
    structured = StructuredGenerationRequest(
        model_key="model-a",
        response_format=ResponseFormatKind.JSON_SCHEMA,
        prompt_hash=_safe_hash("prompt"),
        prompt_chars=123,
        max_tokens=256,
        profile_id="structured-default",
    )
    plain = PlainTextGenerationRequest(
        model_key="model-a",
        prompt_hash=_safe_hash("prompt-2"),
        prompt_chars=64,
        max_tokens=128,
        profile_id="plain-default",
    )
    envelope = generation_envelope_from_fake_payload(
        {
            "content": "final answer",
            "reasoning_content": "chain hidden",
            "finish_reason": "length",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
    )

    assert structured.prompt_hash == _safe_hash("prompt")
    assert plain.prompt_chars == 64
    assert {"prompt", "messages", "content"}.isdisjoint(
        {field.name for field in fields(StructuredGenerationRequest)}
    )
    assert envelope.content_empty is False
    assert envelope.content_chars == len("final answer")
    assert envelope.content_hash == _safe_hash("final answer")
    assert envelope.reasoning_content_present is True
    assert envelope.finish_reason == "length"
    assert envelope.input_tokens == 10
    assert envelope.output_tokens == 20
    assert envelope.error_kind == GenerationFailureKind.FINISH_LENGTH
    assert "content" not in {field.name for field in fields(GenerationResponseEnvelope)}


def test_generation_envelope_reads_nested_choice_finish_reason_when_top_level_missing() -> None:
    envelope = generation_envelope_from_fake_payload(
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "chain hidden",
                    },
                    "finish_reason": "length",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
    )

    assert envelope.content_empty is True
    assert envelope.content_chars == 0
    assert envelope.content_hash is None
    assert envelope.reasoning_content_present is True
    assert envelope.finish_reason == "length"
    assert envelope.input_tokens == 10
    assert envelope.output_tokens == 20
    assert envelope.error_kind == GenerationFailureKind.FINISH_LENGTH


def test_parallel_semantics_validation_enforces_true_parallel_rules() -> None:
    error = validate_parallel_contract(
        configured_parallel=1,
        applied_parallel=1,
        app_concurrency=2,
        parallel_verified=True,
    )
    queue_pressure = validate_parallel_contract(
        configured_parallel=1,
        applied_parallel=1,
        app_concurrency=2,
        parallel_verified=True,
        allow_queue_pressure=True,
    )
    true_parallel = validate_parallel_contract(
        configured_parallel=2,
        applied_parallel=2,
        app_concurrency=2,
        parallel_verified=True,
    )
    unknown = validate_parallel_contract(
        configured_parallel=2,
        applied_parallel=None,
        app_concurrency=2,
        parallel_verified=False,
    )

    assert isinstance(error, SafeApiError)
    assert error.kind == ApiErrorKind.UNKNOWN
    assert queue_pressure.parallel_semantics == "queue_pressure"
    assert queue_pressure.is_true_parallel is False
    assert true_parallel.is_true_parallel is True
    assert unknown.is_true_parallel is False
    assert unknown.parallel_semantics != "true_parallel"


def test_metrics_helpers_build_safe_request_and_batch_metrics() -> None:
    passed = request_metrics_from_envelope(
        request_id="req-1",
        envelope=GenerationResponseEnvelope(
            content_empty=False,
            content_chars=12,
            content_hash=_safe_hash("hello world!"),
            reasoning_content_present=False,
            finish_reason="stop",
            input_tokens=10,
            output_tokens=20,
            error_kind=None,
        ),
        total_elapsed_ms=12.5,
    )
    failed = request_metrics_from_envelope(
        request_id="req-2",
        envelope=GenerationResponseEnvelope(
            content_empty=True,
            content_chars=0,
            content_hash=None,
            reasoning_content_present=False,
            finish_reason="length",
            input_tokens=4,
            output_tokens=8,
            error_kind=GenerationFailureKind.FINISH_LENGTH,
        ),
    )
    batch = batch_metrics_from_request_metrics(
        [passed, failed],
        total_wall_time_ms=99.0,
    )
    parallel = validate_parallel_contract(
        configured_parallel=2,
        applied_parallel=2,
        app_concurrency=2,
        parallel_verified=True,
    )
    evidence = build_screening_evidence(
        model_key="model-a",
        structured_status=StructuredValidationStatus.PASSED,
        verdict=ModelScreeningVerdict.LAB_BASELINE,
        parallel_evidence=parallel,
        batch_metrics=batch,
    )

    assert passed.total_tokens == 30
    assert passed.raw_prompt_response_stored is False
    assert failed.failure_kind == GenerationFailureKind.FINISH_LENGTH
    assert batch.request_count == 2
    assert batch.business_pass_count == 1
    assert batch.business_pass_rate == pytest.approx(0.5)
    assert evidence.parallel_evidence is parallel
    assert evidence.batch_metrics is batch
    assert evidence.structured_status == StructuredValidationStatus.PASSED
