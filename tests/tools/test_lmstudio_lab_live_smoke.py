from __future__ import annotations

import csv
import json
import re
import threading
from dataclasses import fields
from pathlib import Path
from urllib import error as urllib_error

import pytest
import yaml
from libs.lmstudio_managed.generation import GenerationResponseEnvelope
from libs.lmstudio_managed.metrics import batch_metrics_from_request_metrics
from libs.lmstudio_managed.validation import (
    GenerationFailureKind,
    failure_kind_from_lab_category,
)
from tools.lmstudio_lab import live_smoke as lmstudio_live_smoke

from tools import lmstudio_benchmark, lmstudio_lab

ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:[\\/][^\"\r\n]+"),
    re.compile(r"\\\\[^\"\r\n]+[\\/][^\"\r\n]+"),
    re.compile(r"/(?:Users|home)/[^\"\r\n]+"),
)


def _assert_no_private_paths(text: str, *, project_root: Path) -> None:
    known_private_values = {
        str(project_root),
        project_root.as_posix(),
        str(Path.home()),
        Path.home().as_posix(),
    }
    for value in known_private_values:
        if value:
            assert value not in text
    for pattern in ABSOLUTE_PATH_PATTERNS:
        assert pattern.search(text) is None


def _live_config(
    *,
    dataset_id: str = "blocks_json_small",
    parallel: int = 1,
    structured_prompt_variant: str = "baseline",
    structured_schema_variant: str = "baseline",
    business_failure_retry_limit: int = 0,
) -> lmstudio_lab.LiveSmokeConfig:
    return lmstudio_lab.LiveSmokeConfig(
        experiment_id="live_json_smoke",
        models=(
            lmstudio_lab.LiveModelConfig(
                key="local_placeholder",
                model_id="placeholder/local-model",
                load={
                    "context_length": (8192,),
                    "parallel": (parallel,),
                },
            ),
        ),
        modes=("json_schema_single",),
        datasets=(dataset_id,),
        repeats=1,
        lmstudio_base_url="http://127.0.0.1:1234",
        allow_remote=False,
        hardware_profile="local_manual",
        warmup_runs=0,
        structured_prompt_variant=structured_prompt_variant,
        structured_schema_variant=structured_schema_variant,
        business_failure_retry_limit=business_failure_retry_limit,
        privacy=lmstudio_lab.LivePrivacyConfig(
            store_prompt_text=False,
            store_response_text=False,
            store_prompt_hash=True,
        ),
    )


def _write_live_config(tmp_path: Path) -> Path:
    return _write_parametrized_live_config(tmp_path)


def _write_parametrized_live_config(
    tmp_path: Path,
    *,
    dataset_id: str = "blocks_json_small",
    warmup_runs: int = 0,
    parallel: int = 1,
    structured_prompt_variant: str | None = None,
    structured_schema_variant: str | None = None,
    business_failure_retry_limit: int | None = None,
) -> Path:
    path = tmp_path / "live.yaml"
    payload = {
        "experiment_id": "live_json_smoke",
        "hardware_profile": "local_manual",
        "lmstudio_base_url": "http://127.0.0.1:1234",
        "allow_remote": False,
        "models": [
            {
                "key": "local_placeholder",
                "model_id": "placeholder/local-model",
                "load": {
                    "context_length": [8192],
                    "parallel": [parallel],
                },
            }
        ],
        "modes": ["json_schema_single"],
        "datasets": [dataset_id],
        "repeats": 1,
        "warmup_runs": warmup_runs,
        "privacy": {
            "store_prompt_text": False,
            "store_response_text": False,
            "store_prompt_hash": True,
        },
    }
    if structured_prompt_variant is not None:
        payload["structured_prompt_variant"] = structured_prompt_variant
    if structured_schema_variant is not None:
        payload["structured_schema_variant"] = structured_schema_variant
    if business_failure_retry_limit is not None:
        payload["business_failure_retry_limit"] = business_failure_retry_limit
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _valid_blocks_json(expected_ids: tuple[int, ...] = (101, 102)) -> str:
    return json.dumps(
        {
            "schema_version": "factual_blocks.v1",
            "status": "success",
            "blocks": [
                {
                    "block_id": block_id,
                    "normalized_text": f"Normalized block {block_id}.",
                    "status": "success",
                    "warnings": [],
                }
                for block_id in expected_ids
            ],
            "warnings": [],
        }
    )


def _business_failure_json() -> str:
    return json.dumps(
        {
            "schema_version": "factual_blocks.v1",
            "status": "success",
            "blocks": [
                {
                    "block_id": 101,
                    "normalized_text": "Only one block.",
                    "status": "success",
                    "warnings": [],
                }
            ],
            "warnings": [],
        }
    )


def _id_diagnostics_failure_json() -> str:
    return json.dumps(
        {
            "schema_version": "factual_blocks.v1",
            "status": "success",
            "blocks": [
                {
                    "block_id": 101,
                    "normalized_text": "Only first block.",
                    "status": "success",
                    "warnings": [],
                },
                {
                    "block_id": 103,
                    "normalized_text": "Wrong second block.",
                    "status": "success",
                    "warnings": [],
                },
                {
                    "block_id": 103,
                    "normalized_text": "Duplicate third block.",
                    "status": "success",
                    "warnings": [],
                },
            ],
            "warnings": [],
        }
    )


def _schema_failure_json() -> str:
    return json.dumps(
        {
            "schema_version": "factual_blocks.v1",
            "status": "success",
            "blocks": "not-a-list",
            "warnings": [],
        }
    )


def _chunk_id_diagnostics_failure_json(
    expected_ids: tuple[int, ...],
    *,
    text_sentinel: str | None = None,
) -> str:
    returned_ids = list(expected_ids)
    returned_ids[1] = expected_ids[2]
    returned_ids[-1] = 999
    return json.dumps(
        {
            "schema_version": "factual_blocks.v1",
            "status": "success",
            "blocks": [
                {
                    "block_id": block_id,
                    "normalized_text": (
                        text_sentinel
                        if text_sentinel is not None
                        else f"Normalized block {block_id}."
                    ),
                    "status": "success",
                    "warnings": [],
                }
                for block_id in returned_ids
            ],
            "warnings": [],
        }
    )


def _metric_strings(*payloads: object) -> str:
    return "\n".join(
        json.dumps(payload, sort_keys=True) for payload in payloads if payload is not None
    )


def _lab_metric(
    *,
    request_id: str,
    finish_reason: str = "stop",
    error_category: str | None = None,
    business_pass: bool = True,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    total_tokens: int | None = None,
    total_elapsed_ms: float = 100.0,
    response_chars: int = 42,
    content_empty: bool = False,
    reasoning_content_present: bool = False,
) -> lmstudio_lab.LMStudioLabMetricRecord:
    resolved_total_tokens = total_tokens
    if resolved_total_tokens is None:
        resolved_total_tokens = prompt_tokens + completion_tokens

    return lmstudio_lab.LMStudioLabMetricRecord.from_parts(
        run_id="live-run-001",
        experiment_id="live_json_smoke",
        request_id=request_id,
        dataset_id="blocks_json_medium_chunked",
        dataset_hash="sha256:dataset",
        model_key="local_placeholder",
        model_id="placeholder/local-model",
        endpoint_kind="compat_chat",
        mode="json_schema_single",
        requested_context_length=8192,
        requested_parallel=1,
        app_concurrency=2,
        configured_parallel=1,
        applied_parallel=1,
        parallel_verified=None,
        queue_pressure_mode=True,
        parallel_semantics="queue_pressure",
        prompt_hash="sha256:prompt",
        response_hash="sha256:response",
        response_chars=response_chars,
        content_empty=content_empty,
        reasoning_content_present=reasoning_content_present,
        tokens=lmstudio_lab.TokenMetrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=resolved_total_tokens,
        ),
        timing=lmstudio_lab.TimingMetrics(total_elapsed_ms=total_elapsed_ms),
        validation=lmstudio_lab.ValidationMetrics(
            json_parse_pass=business_pass,
            schema_pass=business_pass,
            business_pass=business_pass,
            non_empty_text_pass=business_pass,
            reasoning_leak=False,
            finish_reason=finish_reason,
        ),
        error_category=error_category,
        error_status="ok" if error_category is None else "failed",
    )


@pytest.mark.parametrize(
    ("error_category", "json_parse_pass", "finish_reason", "expected"),
    [
        ("reasoning_leak", True, None, "reasoning"),
        (None, True, "length", "finish"),
        ("finish_length", True, None, "finish"),
        (None, False, None, "json"),
        ("schema_version", True, None, "schema"),
        ("unexpected_validation_category", True, None, "business"),
    ],
)
def test_map_validation_error_category_preserves_legacy_lab_strings(
    error_category: str | None,
    json_parse_pass: bool,
    finish_reason: str | None,
    expected: str,
) -> None:
    assert (
        lmstudio_live_smoke._map_validation_error_category(
            error_category,
            json_parse_pass=json_parse_pass,
            finish_reason=finish_reason,
        )
        == expected
    )


def test_lab_error_category_bridge_keeps_reasoning_only_failure_as_empty() -> None:
    failure_kind = failure_kind_from_lab_category(
        "empty",
        content_empty=True,
        reasoning_content_present=True,
    )

    assert failure_kind == GenerationFailureKind.REASONING_CONTENT_ONLY
    assert lmstudio_live_smoke._lab_error_category_from_failure_kind(failure_kind) == "empty"


def test_managed_generation_envelope_from_lab_response_keeps_safe_summary_only() -> None:
    response_text = _valid_blocks_json()
    envelope = lmstudio_live_smoke._managed_generation_envelope_from_lab_response(
        envelope=lmstudio_live_smoke._ResponseEnvelopeSummary(
            content_text=response_text,
            finish_reason="stop",
            content_empty=False,
            reasoning_content_present=False,
        ),
        tokens=lmstudio_lab.TokenMetrics(
            prompt_tokens=44,
            completion_tokens=22,
            actual_input_tokens=44,
            actual_output_tokens=22,
        ),
    )
    envelope_field_names = {field.name for field in fields(type(envelope))}

    assert isinstance(envelope, GenerationResponseEnvelope)
    assert envelope.content_empty is False
    assert envelope.content_chars == len(response_text)
    assert envelope.content_hash == lmstudio_live_smoke._sha256_text(response_text)
    assert envelope.reasoning_content_present is False
    assert envelope.finish_reason == "stop"
    assert envelope.input_tokens == 44
    assert envelope.output_tokens == 22
    assert envelope.error_kind is None
    assert {
        "content",
        "content_text",
        "response_text",
        "reasoning_content",
    }.isdisjoint(envelope_field_names)


def test_managed_generation_envelope_from_lab_response_marks_reasoning_only_empty() -> None:
    envelope = lmstudio_live_smoke._managed_generation_envelope_from_lab_response(
        envelope=lmstudio_live_smoke._ResponseEnvelopeSummary(
            content_text="",
            finish_reason="stop",
            content_empty=True,
            reasoning_content_present=True,
        ),
        tokens=lmstudio_lab.TokenMetrics(
            prompt_tokens=10,
            completion_tokens=0,
            actual_input_tokens=10,
            actual_output_tokens=0,
        ),
        error_kind=GenerationFailureKind.REASONING_CONTENT_ONLY,
    )

    assert envelope.content_empty is True
    assert envelope.content_chars == 0
    assert envelope.content_hash == lmstudio_live_smoke._sha256_text("")
    assert envelope.reasoning_content_present is True
    assert envelope.input_tokens == 10
    assert envelope.output_tokens == 0
    assert envelope.error_kind == GenerationFailureKind.REASONING_CONTENT_ONLY


def test_managed_generation_envelope_from_lab_response_normalizes_missing_reasoning_to_false() -> (
    None
):
    envelope = lmstudio_live_smoke._managed_generation_envelope_from_lab_response(
        envelope=lmstudio_live_smoke._ResponseEnvelopeSummary(
            content_text=None,
            finish_reason="stop",
            content_empty=True,
            reasoning_content_present=None,
        ),
        tokens=lmstudio_lab.TokenMetrics(
            prompt_tokens=10,
            completion_tokens=0,
            actual_input_tokens=10,
            actual_output_tokens=0,
        ),
    )

    assert envelope.content_empty is True
    assert envelope.content_chars == 0
    assert envelope.content_hash is None
    assert envelope.reasoning_content_present is False


def test_lab_metric_converts_to_managed_request_metrics_without_raw_prompt_response_fields() -> (
    None
):
    metric = _lab_metric(
        request_id="req-123",
        error_category="empty",
        business_pass=False,
        response_chars=0,
        content_empty=True,
        reasoning_content_present=True,
    )

    managed = metric.to_managed_request_metrics()
    managed_field_names = {field.name for field in fields(type(managed))}

    assert managed.request_id == "req-123"
    assert managed.finish_reason == "stop"
    assert managed.error_category == "empty"
    assert managed.failure_kind == GenerationFailureKind.REASONING_CONTENT_ONLY
    assert managed.prompt_tokens == 10
    assert managed.completion_tokens == 5
    assert managed.total_tokens == 15
    assert managed.total_elapsed_ms == 100.0
    assert managed.response_chars == 0
    assert managed.raw_prompt_response_stored is False
    assert {
        "prompt_hash",
        "response_hash",
        "prompt_text",
        "response_text",
        "messages",
        "content",
    }.isdisjoint(managed_field_names)


def test_build_chunked_batch_summary_preserves_json_fields_with_managed_batch_bridge() -> None:
    config = _live_config(dataset_id="blocks_json_medium_chunked", parallel=1)
    metrics = (
        _lab_metric(
            request_id="chunk-1", prompt_tokens=10, completion_tokens=5, total_elapsed_ms=90.0
        ),
        _lab_metric(
            request_id="chunk-2",
            finish_reason="length",
            error_category="finish",
            business_pass=False,
            prompt_tokens=12,
            completion_tokens=10,
            total_elapsed_ms=150.0,
        ),
    )
    managed_batch = batch_metrics_from_request_metrics(
        [metric.to_managed_request_metrics() for metric in metrics],
        total_wall_time_ms=30.0,
    )

    summary = lmstudio_live_smoke._build_chunked_batch_summary(
        config=config,
        run_id="batch-run-001",
        load_config={"context_length": 8192, "parallel": 1},
        dataset_hash="sha256:chunked",
        chunks_count=2,
        chunk_size_blocks=25,
        app_concurrency=2,
        effective_profile="standard",
        warmup_is_productive=False,
        warmup_policy="none",
        warmup_request_count=0,
        metrics=metrics,
        structured_errors=({"error_category": "transport"},),
        failed_chunk_ids=(2,),
        warmup_wall_time_ms=None,
        batch_wall_times_ms=(30.0,),
        sequential_baseline_wall_time_ms=60.0,
        end_to_end_batch_wall_times_ms=(35.0,),
        baseline_end_to_end_wall_time_ms=70.0,
    )

    assert summary["measured_request_count"] == managed_batch.request_count == 2
    assert summary["business_pass_count"] == managed_batch.business_pass_count == 1
    assert summary["finish_length_count"] == managed_batch.finish_length_count == 1
    assert summary["total_completion_tokens"] == managed_batch.total_completion_tokens == 15
    assert summary["structured_error_count"] == 1
    assert summary["failed_chunk_ids"] == [2]
    assert summary["business_failure_retry_limit"] == 0
    assert summary["retry_attempt_count"] == 0
    assert summary["retry_recovered_count"] == 0
    assert summary["retry_failed_count"] == 0
    assert summary["configured_parallel"] == 1
    assert summary["applied_parallel"] == 1
    assert summary["parallel_verified"] is None
    assert summary["queue_pressure_mode"] is True
    assert summary["parallel_semantics"] == "queue_pressure"
    assert summary["raw_prompt_response_stored"] is False


def test_build_live_concurrency_summary_preserves_parallel_and_token_fields_with_managed_bridge() -> (
    None
):
    metrics = (
        _lab_metric(
            request_id="diag-1", prompt_tokens=9, completion_tokens=4, total_elapsed_ms=40.0
        ),
        _lab_metric(
            request_id="diag-2",
            finish_reason="length",
            error_category="finish",
            business_pass=False,
            prompt_tokens=11,
            completion_tokens=6,
            total_elapsed_ms=70.0,
        ),
    )
    managed_batch = batch_metrics_from_request_metrics(
        [metric.to_managed_request_metrics() for metric in metrics],
        total_wall_time_ms=20.0,
    )
    prompt_meta = lmstudio_live_smoke.LivePromptMetadata(
        prompt_hash="sha256:prompt",
        prompt_chars=10,
        expected_block_ids=(),
    )
    request_specs = (
        lmstudio_live_smoke._ConcurrencyRequestSpec(
            request_id="diag-1",
            dataset_id="structured_small_pair",
            dataset_hash="sha256:diag-1",
            messages=[{"role": "user", "content": "one"}],
            prompt_meta=prompt_meta,
            response_format=None,
            max_tokens=128,
            estimated_input_tokens=3,
            requested_context_length=1024,
            validator_kind="plain_text",
        ),
        lmstudio_live_smoke._ConcurrencyRequestSpec(
            request_id="diag-2",
            dataset_id="structured_small_pair",
            dataset_hash="sha256:diag-2",
            messages=[{"role": "user", "content": "two"}],
            prompt_meta=prompt_meta,
            response_format=None,
            max_tokens=128,
            estimated_input_tokens=4,
            requested_context_length=1024,
            validator_kind="plain_text",
        ),
    )

    summary = lmstudio_live_smoke._build_live_concurrency_diagnostics_summary(
        run_id="diag-run-001",
        diagnostic_kind="structured_small_pair",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        request_count=2,
        app_concurrency=3,
        loaded_parallel=2,
        queue_pressure_mode=True,
        request_specs=request_specs,
        metrics=metrics,
        structured_errors=({"error_category": "finish", "error_status": "failed"},),
        total_wall_time_ms=20.0,
        max_tokens_override=256,
    )

    assert summary["request_count"] == managed_batch.request_count == 2
    assert summary["business_pass_count"] == managed_batch.business_pass_count == 1
    assert summary["finish_length_count"] == managed_batch.finish_length_count == 1
    assert summary["total_completion_tokens"] == managed_batch.total_completion_tokens == 10
    assert summary["structured_error_count"] == 1
    assert summary["configured_parallel"] is None
    assert summary["applied_parallel"] == 2
    assert summary["parallel_verified"] is None
    assert summary["queue_pressure_mode"] is True
    assert summary["parallel_semantics"] == "queue_pressure"
    assert summary["max_tokens"] == 128
    assert summary["max_tokens_override"] == 256
    assert summary["raw_prompt_response_stored"] is False


@pytest.mark.parametrize(
    ("kwargs", "expected_semantics", "expected_verified"),
    [
        (
            {
                "app_concurrency": 1,
                "configured_parallel": 1,
                "applied_parallel": 1,
                "queue_pressure_mode": False,
                "explicit_parallel_metadata": False,
            },
            "sequential",
            None,
        ),
        (
            {
                "app_concurrency": 2,
                "configured_parallel": 2,
                "applied_parallel": 2,
                "queue_pressure_mode": False,
                "explicit_parallel_metadata": True,
            },
            "true_parallel",
            True,
        ),
        (
            {
                "app_concurrency": 2,
                "configured_parallel": 1,
                "applied_parallel": 1,
                "queue_pressure_mode": True,
                "explicit_parallel_metadata": True,
            },
            "queue_pressure",
            None,
        ),
        (
            {
                "app_concurrency": 2,
                "configured_parallel": 1,
                "applied_parallel": 1,
                "queue_pressure_mode": False,
                "explicit_parallel_metadata": True,
            },
            "overbooked_stress",
            False,
        ),
        (
            {
                "app_concurrency": 2,
                "configured_parallel": 2,
                "applied_parallel": None,
                "queue_pressure_mode": False,
                "explicit_parallel_metadata": False,
            },
            "true_parallel",
            None,
        ),
    ],
)
def test_build_parallel_semantics_fields_preserves_lab_artifact_contract(
    kwargs: dict[str, int | bool | None],
    expected_semantics: str,
    expected_verified: bool | None,
) -> None:
    fields = lmstudio_live_smoke._build_parallel_semantics_fields(**kwargs)

    assert fields["parallel_semantics"] == expected_semantics
    assert fields["parallel_verified"] is expected_verified


def test_build_parallel_semantics_fields_keeps_none_when_app_concurrency_unknown() -> None:
    fields = lmstudio_live_smoke._build_parallel_semantics_fields(
        app_concurrency=None,
        configured_parallel=2,
        applied_parallel=2,
        queue_pressure_mode=False,
        explicit_parallel_metadata=True,
    )

    assert fields["parallel_semantics"] is None
    assert fields["parallel_verified"] is True


class _ManualClock:
    def __init__(self) -> None:
        self._value = 0.0
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self._value

    def advance_ms(self, delta_ms: float) -> None:
        with self._lock:
            self._value += delta_ms / 1000.0


def _payload_chunk_ids(payload: dict[str, object]) -> tuple[int, ...]:
    messages = payload.get("messages")
    assert isinstance(messages, list)
    combined = "\n".join(
        message["content"]
        for message in messages
        if isinstance(message, dict) and isinstance(message.get("content"), str)
    )
    return tuple(int(match) for match in re.findall(r"block_id=(\d+):", combined))


def _with_warmup_runs(
    config: lmstudio_lab.LiveSmokeConfig,
    *,
    warmup_runs: int,
) -> lmstudio_lab.LiveSmokeConfig:
    return lmstudio_lab.LiveSmokeConfig(
        experiment_id=config.experiment_id,
        models=config.models,
        modes=config.modes,
        datasets=config.datasets,
        repeats=config.repeats,
        lmstudio_base_url=config.lmstudio_base_url,
        allow_remote=config.allow_remote,
        hardware_profile=config.hardware_profile,
        warmup_runs=warmup_runs,
        structured_prompt_variant=config.structured_prompt_variant,
        structured_schema_variant=config.structured_schema_variant,
        business_failure_retry_limit=config.business_failure_retry_limit,
        privacy=config.privacy,
    )


def test_build_live_structured_messages_baseline_matches_default_prompt_metadata() -> None:
    default_messages, default_meta = lmstudio_live_smoke.build_live_structured_messages()
    baseline_messages, baseline_meta = lmstudio_live_smoke.build_live_structured_messages(
        prompt_variant="baseline"
    )

    assert default_messages == baseline_messages
    assert default_meta == baseline_meta
    assert default_messages[0]["role"] == "system"
    assert default_messages[0]["content"] == (
        "Return JSON only. Follow the factual_blocks.v1 schema exactly. "
        "Do not add prose, markdown, or reasoning."
    )
    assert default_meta.expected_block_ids == (101, 102)


def test_build_live_structured_messages_anti_reasoning_changes_system_prompt_safely() -> None:
    baseline_messages, baseline_meta = lmstudio_live_smoke.build_live_structured_messages(
        prompt_variant="baseline"
    )
    anti_messages, anti_meta = lmstudio_live_smoke.build_live_structured_messages(
        prompt_variant="anti_reasoning"
    )

    assert anti_messages[0]["role"] == "system"
    assert anti_messages[0]["content"] != baseline_messages[0]["content"]
    assert "public assistant content" in anti_messages[0]["content"]
    assert "hidden reasoning" in anti_messages[0]["content"]
    assert anti_messages[1] == baseline_messages[1]
    assert anti_meta.expected_block_ids == baseline_meta.expected_block_ids == (101, 102)
    assert anti_meta.prompt_hash != baseline_meta.prompt_hash
    assert anti_meta.prompt_chars > baseline_meta.prompt_chars

    with pytest.raises(ValueError, match="supported only for blocks_json_small"):
        lmstudio_live_smoke.build_live_structured_messages(
            dataset_id="blocks_json_medium",
            prompt_variant="anti_reasoning",
        )


def test_build_medium_chunk_live_structured_messages_prompt_variants_change_hashes_safely() -> None:
    baseline_messages, baseline_meta = (
        lmstudio_live_smoke._build_medium_chunk_live_structured_messages(
            (0, 1, 2),
            prompt_variant="baseline",
        )
    )
    strict_messages, strict_meta = lmstudio_live_smoke._build_medium_chunk_live_structured_messages(
        (0, 1, 2),
        prompt_variant="strict_id_contract",
    )
    ultra_messages, ultra_meta = lmstudio_live_smoke._build_medium_chunk_live_structured_messages(
        (0, 1, 2),
        prompt_variant="ultra_minimal_transform",
    )

    assert (
        baseline_meta.expected_block_ids
        == strict_meta.expected_block_ids
        == ultra_meta.expected_block_ids
        == (
            0,
            1,
            2,
        )
    )
    assert baseline_meta.prompt_variant == "baseline"
    assert strict_meta.prompt_variant == "strict_id_contract"
    assert ultra_meta.prompt_variant == "ultra_minimal_transform"
    assert len({baseline_meta.prompt_hash, strict_meta.prompt_hash, ultra_meta.prompt_hash}) == 3
    assert strict_meta.prompt_chars > baseline_meta.prompt_chars
    assert ultra_meta.prompt_chars > baseline_meta.prompt_chars
    assert baseline_messages[0] == strict_messages[0] == ultra_messages[0]
    assert strict_messages[1]["content"] != baseline_messages[1]["content"]
    assert ultra_messages[1]["content"] != baseline_messages[1]["content"]
    assert "never change, duplicate, omit" in strict_messages[1]["content"]
    assert "Do not summarize, merge, split, reorder" in ultra_messages[1]["content"]

    strict_meta_payload = {
        field.name: getattr(strict_meta, field.name)
        for field in fields(lmstudio_live_smoke.LivePromptMetadata)
    }
    assert strict_meta_payload == {
        "prompt_hash": strict_meta.prompt_hash,
        "prompt_chars": strict_meta.prompt_chars,
        "expected_block_ids": (0, 1, 2),
        "prompt_variant": "strict_id_contract",
    }


def test_run_live_structured_smoke_builds_canonical_request_and_safe_metric() -> None:
    captured: dict[str, object] = {}
    response_text = _valid_blocks_json()

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout_s"] = timeout_s
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": response_text},
                }
            ],
            "usage": {
                "prompt_tokens": 44,
                "completion_tokens": 22,
                "total_tokens": 66,
            },
            "stats": {
                "tokens_per_second": 12.5,
                "time_to_first_token": 0.25,
                "generation_time": 0.75,
            },
        }

    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-run-001",
        transport=fake_transport,
    )

    assert outcome.structured_error is None
    assert captured["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert captured["timeout_s"] == 30.0

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "placeholder/local-model"
    assert "chat_template_kwargs" not in payload
    assert payload["temperature"] == 0
    assert payload["max_tokens"] == 512
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["name"] == "factual_blocks_v1"
    assert payload["response_format"]["json_schema"]["strict"] is True

    metric_row = outcome.metric.to_dict()
    assert metric_row["endpoint_kind"] == "compat_chat"
    assert metric_row["mode"] == "json_schema_single"
    assert metric_row["validation"]["json_parse_pass"] is True
    assert metric_row["validation"]["schema_pass"] is True
    assert metric_row["validation"]["business_pass"] is True
    assert metric_row["validation"]["finish_reason"] == "stop"
    assert metric_row["error_category"] is None
    assert metric_row["prompt_hash"].startswith("sha256:")
    assert metric_row["prompt_chars"] > 0
    assert metric_row["response_hash"] == lmstudio_live_smoke._sha256_text(response_text)
    assert metric_row["response_chars"] == len(response_text)
    assert metric_row["tokens"]["prompt_tokens"] == 44
    assert metric_row["tokens"]["completion_tokens"] == 22
    assert metric_row["tokens"]["total_tokens"] == 66
    assert metric_row["tokens"]["estimate_scope"] == "dataset_only"
    assert metric_row["timing"]["time_to_first_token_ms"] == 250.0
    assert metric_row["timing"]["generation_time_ms"] == 750.0
    assert metric_row["content_empty"] is False
    assert metric_row["reasoning_content_present"] is False

    serialized = json.dumps(metric_row, sort_keys=True)
    assert "Synthetic alpha fact." not in serialized
    assert "Synthetic beta fact." not in serialized
    assert '"messages"' not in serialized
    assert '"content"' not in serialized


def test_run_live_structured_smoke_forwards_anti_reasoning_prompt_variant_only() -> None:
    captured: dict[str, object] = {}
    baseline_messages, _ = lmstudio_live_smoke.build_live_structured_messages()
    anti_messages, anti_meta = lmstudio_live_smoke.build_live_structured_messages(
        prompt_variant="anti_reasoning"
    )

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout_s"] = timeout_s
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json()},
                }
            ],
            "usage": {
                "prompt_tokens": 44,
                "completion_tokens": 22,
                "total_tokens": 66,
            },
        }

    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-run-anti-reasoning",
        transport=fake_transport,
        prompt_variant="anti_reasoning",
    )

    assert outcome.structured_error is None
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["messages"] == anti_messages
    assert payload["messages"][0]["content"] == anti_messages[0]["content"]
    assert payload["messages"][0]["content"] != baseline_messages[0]["content"]
    assert "chat_template_kwargs" not in payload
    assert outcome.metric.prompt_hash == anti_meta.prompt_hash


def test_run_live_structured_smoke_supports_medium_dataset_with_scaled_max_tokens() -> None:
    captured: dict[str, object] = {}
    expected_ids = tuple(range(100))

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout_s"] = timeout_s
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(expected_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 6700,
                "completion_tokens": 500,
                "total_tokens": 7200,
            },
            "stats": {
                "tokens_per_second": 25.0,
                "time_to_first_token": 0.2,
                "generation_time": 1.0,
            },
        }

    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(dataset_id="blocks_json_medium"),
        run_id="live-medium-001",
        transport=fake_transport,
        verified_context_length=32768,
    )

    assert outcome.structured_error is None
    assert captured["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert captured["timeout_s"] == 30.0

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "placeholder/local-model"
    assert payload["temperature"] == 0
    assert payload["max_tokens"] == 7500
    assert payload["response_format"]["type"] == "json_schema"

    messages = payload["messages"]
    assert isinstance(messages, list)
    combined_content = "\n".join(
        message["content"]
        for message in messages
        if isinstance(message, dict) and isinstance(message.get("content"), str)
    )
    assert "block_id=0:" in combined_content
    assert "block_id=99:" in combined_content
    assert (
        'set normalized_text to a concise phrase like "medium block <block_id> validated"'
        in combined_content
    )
    assert "Do not copy the source paragraph into normalized_text." in combined_content

    metric_row = outcome.metric.to_dict()
    assert metric_row["dataset_id"] == "blocks_json_medium"
    assert metric_row["max_tokens"] == 7500
    assert metric_row["error_status"] == "ok"
    assert metric_row["error_category"] is None
    assert metric_row["validation"]["json_parse_pass"] is True
    assert metric_row["validation"]["schema_pass"] is True
    assert metric_row["validation"]["business_pass"] is True
    assert metric_row["validation"]["ids_exact_pass"] is True
    assert metric_row["validation"]["order_preserved"] is True
    assert metric_row["validation"]["no_duplicate_ids"] is True
    assert metric_row["validation"]["non_empty_text_pass"] is True
    assert metric_row["prompt_hash"].startswith("sha256:")
    assert metric_row["response_hash"].startswith("sha256:")
    assert metric_row["tokens"]["estimate_scope"] == "dataset_only"

    serialized = json.dumps(metric_row, sort_keys=True)
    assert "Synthetic block 00 records neutral benchmark notes" not in serialized
    assert '"messages"' not in serialized
    assert '"content"' not in serialized


def test_run_live_structured_smoke_adds_chat_template_kwargs_reasoning_control_only() -> None:
    captured: dict[str, object] = {}
    baseline_messages, _ = lmstudio_live_smoke.build_live_structured_messages()
    baseline_response_format = lmstudio_live_smoke.build_factual_blocks_response_format()

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout_s"] = timeout_s
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json()},
                }
            ],
            "usage": {
                "prompt_tokens": 44,
                "completion_tokens": 22,
                "total_tokens": 66,
            },
        }

    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-run-reasoning-control",
        transport=fake_transport,
        reasoning_control_variant="chat_template_kwargs_enable_thinking_false",
    )

    assert outcome.structured_error is None
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["messages"] == baseline_messages
    assert payload["response_format"] == baseline_response_format


def test_build_factual_blocks_response_format_baseline_stays_generic() -> None:
    response_format = lmstudio_lab.build_factual_blocks_response_format()

    assert response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "factual_blocks_v1",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "status", "blocks", "warnings"],
                "properties": {
                    "schema_version": {"type": "string", "const": "factual_blocks.v1"},
                    "status": {"type": "string", "const": "success"},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                    "blocks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "block_id",
                                "normalized_text",
                                "status",
                                "warnings",
                            ],
                            "properties": {
                                "block_id": {"type": "integer"},
                                "normalized_text": {"type": "string"},
                                "status": {"type": "string", "const": "success"},
                                "warnings": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def test_build_factual_blocks_response_format_per_position_id_const_is_exact_and_safe() -> None:
    response_format = lmstudio_lab.build_factual_blocks_response_format(
        expected_block_ids=(11, 22, 33),
        schema_variant="per_position_id_const",
    )

    json_schema = response_format["json_schema"]
    schema = json_schema["schema"]
    blocks = schema["properties"]["blocks"]
    prefix_items = blocks["prefixItems"]

    assert json_schema["name"] == "factual_blocks_v1_per_position_id_const"
    assert json_schema["strict"] is True
    assert blocks["type"] == "array"
    assert blocks["minItems"] == 3
    assert blocks["maxItems"] == 3
    assert len(prefix_items) == 3
    assert [item["properties"]["block_id"]["const"] for item in prefix_items] == [11, 22, 33]
    assert all(item["additionalProperties"] is False for item in prefix_items)
    assert all(item["properties"]["status"]["const"] == "success" for item in prefix_items)
    assert all(
        item["properties"]["warnings"]["items"] == {"type": "string"} for item in prefix_items
    )

    serialized = json.dumps(response_format, sort_keys=True)
    assert "Synthetic alpha fact." not in serialized
    assert "Synthetic block 00 records neutral benchmark notes" not in serialized


def test_medium_live_requires_verified_context_before_transport() -> None:
    def forbidden_transport(*_args, **_kwargs):
        raise AssertionError("transport should not be called without verified context")

    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(dataset_id="blocks_json_medium"),
        run_id="live-medium-missing-context",
        transport=forbidden_transport,
    )

    metric_row = outcome.metric.to_dict()
    assert outcome.metric.error_category == "context_fit_failed"
    assert outcome.metric.error_status == "missing_verified_context"
    assert metric_row["max_tokens"] == 7500
    assert metric_row["tokens"]["estimated_input_tokens"] == 6700
    assert metric_row["tokens"]["estimate_scope"] == "dataset_only"
    assert metric_row["tokens"]["prompt_tokens"] is None
    assert metric_row["validation"] == {
        "json_parse_pass": False,
        "schema_pass": False,
        "business_pass": False,
        "ids_exact_pass": False,
        "no_duplicate_ids": False,
        "order_preserved": False,
        "non_empty_text_pass": False,
        "reasoning_leak": False,
        "retry_count": None,
        "finish_reason": None,
        "expected_count": None,
        "returned_count": None,
        "expected_ids": None,
        "returned_ids": None,
        "duplicate_ids": None,
        "missing_ids": None,
        "extra_ids": None,
        "reordered_positions": None,
        "reordered_count": None,
        "reordered_positions_truncated": None,
    }
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "context_fit_failed"
    assert outcome.structured_error["error_status"] == "missing_verified_context"


def test_run_live_structured_smoke_id_diagnostics_propagate_to_structured_error() -> None:
    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _id_diagnostics_failure_json()},
                }
            ],
            "usage": {
                "prompt_tokens": 44,
                "completion_tokens": 22,
                "total_tokens": 66,
            },
        }

    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-id-diagnostics",
        transport=fake_transport,
    )

    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "business"
    assert outcome.structured_error["expected_count"] == 2
    assert outcome.structured_error["returned_count"] == 3
    assert outcome.structured_error["expected_ids"] == [101, 102]
    assert outcome.structured_error["returned_ids"] == [101, 103, 103]
    assert outcome.structured_error["duplicate_ids"] == [103]
    assert outcome.structured_error["missing_ids"] == [102]
    assert outcome.structured_error["extra_ids"] == [103, 103]
    assert outcome.structured_error["reordered_positions"] == [
        {"position": 1, "expected_id": 102, "returned_id": 103},
        {"position": 2, "expected_id": None, "returned_id": 103},
    ]
    assert outcome.structured_error["reordered_count"] == 2
    assert outcome.structured_error["reordered_positions_truncated"] is False

    metric_row = outcome.metric.to_dict()
    assert metric_row["validation"]["expected_ids"] == [101, 102]
    assert metric_row["validation"]["returned_ids"] == [101, 103, 103]

    serialized = json.dumps(outcome.structured_error, sort_keys=True)
    assert "Only first block." not in serialized
    assert "Wrong second block." not in serialized


def test_medium_live_rejects_reasoning_control_variant_before_transport() -> None:
    transport_called = False

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called for unsupported reasoning control")

    with pytest.raises(
        ValueError,
        match="supported only for blocks_json_small",
    ):
        lmstudio_lab.run_live_structured_smoke(
            _live_config(dataset_id="blocks_json_medium"),
            run_id="live-medium-unsupported-reasoning-control",
            transport=forbidden_transport,
            verified_context_length=32768,
            reasoning_control_variant="chat_template_kwargs_enable_thinking_false",
        )

    assert transport_called is False


def test_medium_live_rejects_prompt_variant_before_transport() -> None:
    transport_called = False

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called for unsupported prompt variant")

    with pytest.raises(
        ValueError,
        match="supported only for blocks_json_small",
    ):
        lmstudio_lab.run_live_structured_smoke(
            _live_config(dataset_id="blocks_json_medium"),
            run_id="live-medium-unsupported-prompt-variant",
            transport=forbidden_transport,
            verified_context_length=32768,
            prompt_variant="anti_reasoning",
        )

    assert transport_called is False


def test_run_live_chunked_structured_smoke_uses_configured_prompt_variant() -> None:
    captured_payloads: list[dict[str, object]] = []
    chunked_view = lmstudio_lab.load_chunked_dataset_view("blocks_json_medium_chunked")
    first_chunk = chunked_view.chunks[0]
    expected_messages, expected_meta = (
        lmstudio_live_smoke._build_medium_chunk_live_structured_messages(
            first_chunk.expected_ids,
            prompt_variant="strict_id_contract",
        )
    )

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        captured_payloads.append(payload)
        chunk_ids = _payload_chunk_ids(payload)
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(
            dataset_id="blocks_json_medium_chunked",
            structured_prompt_variant="strict_id_contract",
        ),
        run_id="chunked-strict-id-contract",
        transport=fake_transport,
        verified_context_length=8192,
    )

    assert len(captured_payloads) == 4
    assert captured_payloads[0]["messages"] == expected_messages
    assert outcome.metrics[0].prompt_hash == expected_meta.prompt_hash
    assert outcome.batch_summary["structured_prompt_variant"] == "strict_id_contract"


@pytest.mark.parametrize(
    ("dataset_id", "chunk_size_blocks"),
    [
        ("blocks_json_medium_chunked", 25),
        ("blocks_json_medium_chunked_10", 10),
        ("blocks_json_medium_chunked_5", 5),
    ],
)
def test_run_live_chunked_structured_smoke_uses_configured_schema_variant_per_chunk(
    dataset_id: str,
    chunk_size_blocks: int,
) -> None:
    captured_payloads: list[dict[str, object]] = []
    chunked_view = lmstudio_lab.load_chunked_dataset_view(dataset_id)

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        captured_payloads.append(payload)
        chunk_ids = _payload_chunk_ids(payload)
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(
            dataset_id=dataset_id,
            structured_schema_variant="per_position_id_const",
        ),
        run_id="chunked-per-position-id-const",
        transport=fake_transport,
        verified_context_length=8192,
    )

    assert len(captured_payloads) == chunked_view.chunks_count
    first_response_format = captured_payloads[0]["response_format"]
    second_response_format = captured_payloads[1]["response_format"]
    assert isinstance(first_response_format, dict)
    assert isinstance(second_response_format, dict)
    assert first_response_format["json_schema"]["name"] == "factual_blocks_v1_per_position_id_const"
    assert (
        second_response_format["json_schema"]["name"] == "factual_blocks_v1_per_position_id_const"
    )

    first_blocks = first_response_format["json_schema"]["schema"]["properties"]["blocks"]
    second_blocks = second_response_format["json_schema"]["schema"]["properties"]["blocks"]
    assert first_blocks["minItems"] == chunk_size_blocks
    assert first_blocks["maxItems"] == chunk_size_blocks
    assert [
        item["properties"]["block_id"]["const"] for item in first_blocks["prefixItems"]
    ] == list(chunked_view.chunks[0].expected_ids)
    assert [
        item["properties"]["block_id"]["const"] for item in second_blocks["prefixItems"]
    ] == list(chunked_view.chunks[1].expected_ids)

    first_metric_row = outcome.metrics[0].to_dict()
    assert first_metric_row["structured_schema_variant"] == "per_position_id_const"
    assert (
        first_metric_row["response_format"]["schema_name"]
        == "factual_blocks_v1_per_position_id_const"
    )
    assert outcome.batch_summary["structured_schema_variant"] == "per_position_id_const"

    serialized = json.dumps(first_response_format, sort_keys=True)
    assert "Synthetic block 00 records neutral benchmark notes" not in serialized


@pytest.mark.parametrize(
    ("dataset_id", "chunk_size_blocks", "chunks_count"),
    [
        ("blocks_json_medium_chunked", 25, 4),
        ("blocks_json_medium_chunked_10", 10, 10),
        ("blocks_json_medium_chunked_5", 5, 20),
    ],
)
def test_run_live_chunked_structured_smoke_accepts_l3_10e_dataset_variants_and_reports_batch_shape(
    dataset_id: str,
    chunk_size_blocks: int,
    chunks_count: int,
) -> None:
    captured_chunk_ids: list[tuple[int, ...]] = []
    chunked_view = lmstudio_lab.load_chunked_dataset_view(dataset_id)

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        chunk_ids = _payload_chunk_ids(payload)
        captured_chunk_ids.append(chunk_ids)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(dataset_id=dataset_id),
        run_id=f"live-{dataset_id}-shape",
        transport=fake_transport,
        verified_context_length=8192,
    )

    assert len(captured_chunk_ids) == chunks_count
    assert captured_chunk_ids[0] == tuple(chunked_view.chunks[0].expected_ids)
    assert captured_chunk_ids[-1] == tuple(chunked_view.chunks[-1].expected_ids)
    assert len(outcome.metrics) == chunks_count
    assert {metric.dataset_id for metric in outcome.metrics} == {dataset_id}
    assert outcome.batch_summary["dataset_id"] == dataset_id
    assert outcome.batch_summary["chunk_size_blocks"] == chunk_size_blocks
    assert outcome.batch_summary["chunks_count"] == chunks_count
    assert outcome.batch_summary["structured_schema_variant"] == "baseline"
    assert outcome.batch_summary["all_chunks_pass"] is True


def test_medium_live_aborts_when_context_fit_fails_before_transport() -> None:
    def forbidden_transport(*_args, **_kwargs):
        raise AssertionError("transport should not be called when context fit fails")

    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(dataset_id="blocks_json_medium"),
        run_id="live-medium-context-fit-failed",
        transport=forbidden_transport,
        verified_context_length=8192,
        context_fit_safety_ratio=0.85,
    )

    assert outcome.metric.error_category == "context_fit_failed"
    assert outcome.metric.error_status == "insufficient_context"
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "context_fit_failed"
    assert outcome.structured_error["error_status"] == "insufficient_context"
    assert outcome.structured_error["required_tokens"] == 14200
    assert outcome.structured_error["budget_tokens"] == 6963
    assert outcome.structured_error["effective_context_length"] == 8192
    assert outcome.structured_error["safety_ratio"] == 0.85
    assert outcome.structured_error["fits"] is False


def test_medium_live_allows_request_when_context_fit_passes() -> None:
    transport_called = False

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        nonlocal transport_called
        transport_called = True
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        assert payload["max_tokens"] == 7500
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(tuple(range(100)))},
                }
            ],
            "usage": {
                "prompt_tokens": 6700,
                "completion_tokens": 500,
                "total_tokens": 7200,
            },
        }

    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(dataset_id="blocks_json_medium"),
        run_id="live-medium-context-fit-passes",
        transport=fake_transport,
        verified_context_length=32768,
    )

    assert transport_called is True
    assert outcome.structured_error is None
    assert outcome.metric.error_category is None


def test_run_live_chunked_structured_smoke_executes_sequential_chunks_with_warmup() -> None:
    captured_calls: list[dict[str, object]] = []
    chunked_view = lmstudio_lab.load_chunked_dataset_view("blocks_json_medium_chunked")
    clock = _ManualClock()

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        clock.advance_ms(5.0)
        chunk_ids = _payload_chunk_ids(payload)
        captured_calls.append(
            {
                "url": url,
                "timeout_s": timeout_s,
                "payload": payload,
                "chunk_ids": chunk_ids,
            }
        )
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200 + len(captured_calls),
                "completion_tokens": 200,
                "total_tokens": 1400 + len(captured_calls),
            },
        }

    config = _with_warmup_runs(
        _live_config(dataset_id="blocks_json_medium_chunked"),
        warmup_runs=1,
    )

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        config,
        run_id="live-chunked-001",
        transport=fake_transport,
        verified_context_length=8192,
        _clock=clock.now,
    )

    assert len(captured_calls) == 5
    assert len(outcome.metrics) == 4
    assert outcome.structured_errors == ()
    assert captured_calls[0]["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert captured_calls[0]["timeout_s"] == 30.0
    assert captured_calls[0]["chunk_ids"] == tuple(range(25))
    assert captured_calls[1]["chunk_ids"] == tuple(range(25))
    assert captured_calls[4]["chunk_ids"] == tuple(range(75, 100))

    for index, chunk in enumerate(chunked_view.chunks):
        payload = captured_calls[index + 1]["payload"]
        assert isinstance(payload, dict)
        assert payload["max_tokens"] == chunk.estimated_input_tokens + chunk.items_count * 8
        assert payload["max_tokens"] <= int(8192 * 0.85)
        metric_row = outcome.metrics[index].to_dict()
        assert metric_row["request_id"] == f"batch_0001_chunk_{chunk.chunk_id:04d}"
        assert metric_row["dataset_id"] == "blocks_json_medium_chunked"
        assert metric_row["endpoint_kind"] == "compat_chat"
        assert metric_row["mode"] == "json_schema_single"
        assert metric_row["requested_parallel"] == 1
        assert metric_row["app_concurrency"] == 1
        assert metric_row["validation"]["business_pass"] is True

    summary = outcome.batch_summary
    assert summary["planned_requests"] == 5
    assert summary["measured_request_count"] == 4
    assert summary["app_concurrency"] == 1
    assert summary["effective_profile"] == "standard"
    assert summary["warmup_is_productive"] is False
    assert summary["warmup_policy"] == "sequential_chunk_0"
    assert summary["warmup_request_count"] == 1
    assert summary["all_chunks_pass"] is True
    assert summary["batch_business_pass"] is True
    assert summary["all_ids_covered"] is True
    assert summary["missing_id_count"] == 0
    assert summary["duplicate_id_count"] == 0
    assert summary["warmup_wall_time_ms"] == pytest.approx(5.0)
    assert summary["total_batch_wall_time_ms"] is not None
    assert summary["avg_batch_wall_time_ms"] is not None
    assert summary["max_batch_wall_time_ms"] is not None
    assert summary["parallel_batch_wall_time_ms"] == pytest.approx(20.0)
    assert summary["total_batch_wall_time_ms"] == pytest.approx(20.0)
    assert summary["avg_batch_wall_time_ms"] == pytest.approx(20.0)
    assert summary["end_to_end_wall_time_ms"] > summary["total_batch_wall_time_ms"]
    assert summary["end_to_end_wall_time_ms"] == pytest.approx(25.0)
    assert summary["sequential_baseline_wall_time_ms"] is None
    assert summary["speedup_vs_sequential_baseline"] is None


def test_run_live_chunked_structured_smoke_supports_explicit_none_warmup_policy() -> None:
    captured_chunk_ids: list[tuple[int, ...]] = []

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        chunk_ids = _payload_chunk_ids(payload)
        captured_chunk_ids.append(chunk_ids)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(dataset_id="blocks_json_medium_chunked"),
        run_id="live-chunked-no-warmup",
        transport=fake_transport,
        verified_context_length=8192,
        warmup_policy="none",
    )

    assert captured_chunk_ids == [
        tuple(range(25)),
        tuple(range(25, 50)),
        tuple(range(50, 75)),
        tuple(range(75, 100)),
    ]
    assert [metric.request_id for metric in outcome.metrics] == [
        "batch_0001_chunk_0000",
        "batch_0001_chunk_0001",
        "batch_0001_chunk_0002",
        "batch_0001_chunk_0003",
    ]
    assert outcome.batch_summary["warmup_policy"] == "none"
    assert outcome.batch_summary["warmup_request_count"] == 0
    assert outcome.batch_summary["planned_requests"] == 4


def test_run_live_chunked_structured_smoke_supports_explicit_sequential_chunk_0_warmup_policy() -> (
    None
):
    captured_chunk_ids: list[tuple[int, ...]] = []

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        chunk_ids = _payload_chunk_ids(payload)
        captured_chunk_ids.append(chunk_ids)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _with_warmup_runs(
            _live_config(dataset_id="blocks_json_medium_chunked"),
            warmup_runs=1,
        ),
        run_id="live-chunked-explicit-chunk0",
        transport=fake_transport,
        verified_context_length=8192,
        warmup_policy="sequential_chunk_0",
    )

    assert captured_chunk_ids[0] == tuple(range(25))
    assert captured_chunk_ids[1:] == [
        tuple(range(25)),
        tuple(range(25, 50)),
        tuple(range(50, 75)),
        tuple(range(75, 100)),
    ]
    assert len(outcome.metrics) == 4
    assert outcome.batch_summary["warmup_policy"] == "sequential_chunk_0"
    assert outcome.batch_summary["warmup_request_count"] == 1


def test_run_live_chunked_structured_smoke_supports_app_concurrency_with_stable_metric_order() -> (
    None
):
    barrier = threading.Barrier(2)
    chunk_1_recorded = threading.Event()
    chunk_0_recorded = threading.Event()
    lock = threading.Lock()
    completion_order: list[int] = []
    in_flight = 0
    max_in_flight = 0

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        nonlocal in_flight, max_in_flight
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        chunk_ids = _payload_chunk_ids(payload)
        chunk_index = chunk_ids[0] // 25
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        try:
            if chunk_index in {0, 1}:
                barrier.wait(timeout=5.0)
                if chunk_index == 0:
                    assert chunk_1_recorded.wait(timeout=5.0) is True
            elif chunk_index >= 2:
                assert chunk_0_recorded.wait(timeout=5.0) is True
            with lock:
                completion_order.append(chunk_index)
                if chunk_index == 1:
                    chunk_1_recorded.set()
                if chunk_index == 0:
                    chunk_0_recorded.set()
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": _valid_blocks_json(chunk_ids)},
                    }
                ],
                "usage": {
                    "prompt_tokens": 1200 + chunk_index,
                    "completion_tokens": 200,
                    "total_tokens": 1400 + chunk_index,
                },
            }
        finally:
            with lock:
                in_flight -= 1

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(dataset_id="blocks_json_medium_chunked", parallel=2),
        run_id="live-chunked-concurrency-2",
        transport=fake_transport,
        verified_context_length=8192,
        app_concurrency=2,
        sequential_baseline_wall_time_ms=300.0,
    )

    assert outcome.structured_errors == ()
    assert max_in_flight == 2
    assert completion_order[:2] == [1, 0]
    assert [metric.request_id for metric in outcome.metrics] == [
        "batch_0001_chunk_0000",
        "batch_0001_chunk_0001",
        "batch_0001_chunk_0002",
        "batch_0001_chunk_0003",
    ]
    for metric in outcome.metrics:
        metric_row = metric.to_dict()
        assert metric_row["requested_parallel"] == 2
        assert metric_row["configured_parallel"] == 2
        assert metric_row["applied_parallel"] == 2
        assert metric_row["parallel_verified"] is None
        assert metric_row["app_concurrency"] == 2
        assert metric_row["queue_pressure_mode"] is False
        assert metric_row["parallel_semantics"] == "true_parallel"

    summary = outcome.batch_summary
    assert summary["requested_parallel"] == 2
    assert summary["configured_parallel"] == 2
    assert summary["applied_parallel"] == 2
    assert summary["parallel_verified"] is None
    assert summary["app_concurrency"] == 2
    assert summary["queue_pressure_mode"] is False
    assert summary["parallel_semantics"] == "true_parallel"
    assert summary["warmup_policy"] == "none"
    assert summary["warmup_request_count"] == 0
    assert summary["total_batch_wall_time_ms"] is not None
    assert summary["avg_batch_wall_time_ms"] is not None
    assert summary["max_batch_wall_time_ms"] is not None
    assert summary["sequential_baseline_wall_time_ms"] == 300.0
    assert summary["baseline_end_to_end_wall_time_ms"] == 300.0
    expected_speedup = (
        pytest.approx(300.0 / summary["avg_batch_wall_time_ms"])
        if summary["avg_batch_wall_time_ms"] > 0
        else None
    )
    assert summary["speedup_vs_sequential_baseline"] == expected_speedup
    assert summary["speedup_excluding_warmup"] == expected_speedup
    assert summary["speedup_including_warmup"] == expected_speedup
    assert summary["effective_speedup"] == expected_speedup


def test_run_live_chunked_structured_smoke_supports_productive_first_chunk_effective_profile() -> (
    None
):
    chunk0_completed = threading.Event()
    remaining_pair_barrier = threading.Barrier(2)
    remaining_pair_timed = threading.Event()
    lock = threading.Lock()
    clock = _ManualClock()
    started_chunk_indices: list[int] = []
    in_flight = 0
    max_in_flight = 0

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        nonlocal in_flight, max_in_flight
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        chunk_ids = _payload_chunk_ids(payload)
        chunk_index = chunk_ids[0] // 25
        with lock:
            started_chunk_indices.append(chunk_index)
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        try:
            if chunk_index == 0:
                assert max_in_flight == 1
                clock.advance_ms(7.0)
            else:
                assert chunk0_completed.wait(timeout=5.0) is True
                if chunk_index in {1, 2}:
                    remaining_pair_barrier.wait(timeout=5.0)
                    if chunk_index == 1:
                        clock.advance_ms(11.0)
                        remaining_pair_timed.set()
                    else:
                        assert remaining_pair_timed.wait(timeout=5.0) is True
                else:
                    assert remaining_pair_timed.wait(timeout=5.0) is True
                    clock.advance_ms(5.0)
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": _valid_blocks_json(chunk_ids)},
                    }
                ],
                "usage": {
                    "prompt_tokens": 1200 + chunk_index,
                    "completion_tokens": 200,
                    "total_tokens": 1400 + chunk_index,
                },
            }
        finally:
            if chunk_index == 0:
                chunk0_completed.set()
            with lock:
                in_flight -= 1

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(dataset_id="blocks_json_medium_chunked", parallel=2),
        run_id="live-chunked-productive-first",
        transport=fake_transport,
        verified_context_length=8192,
        app_concurrency=2,
        effective_profile="productive_first_chunk",
        sequential_baseline_wall_time_ms=120.0,
        baseline_end_to_end_wall_time_ms=150.0,
        _clock=clock.now,
    )

    assert outcome.structured_errors == ()
    assert len(outcome.metrics) == 4
    assert started_chunk_indices[0] == 0
    assert set(started_chunk_indices[1:]) == {1, 2, 3}
    assert max_in_flight == 2
    assert [metric.request_id for metric in outcome.metrics] == [
        "batch_0001_chunk_0000",
        "batch_0001_chunk_0001",
        "batch_0001_chunk_0002",
        "batch_0001_chunk_0003",
    ]
    assert outcome.metrics[0].validation.business_pass is True

    summary = outcome.batch_summary
    assert summary["requested_parallel"] == 2
    assert summary["configured_parallel"] == 2
    assert summary["queue_pressure_mode"] is False
    assert summary["effective_profile"] == "productive_first_chunk"
    assert summary["warmup_is_productive"] is True
    assert summary["warmup_policy"] == "none"
    assert summary["warmup_request_count"] == 0
    assert summary["warmup_wall_time_ms"] is None
    assert summary["measured_request_count"] == 4
    assert summary["business_pass_count"] == 4
    assert summary["all_chunks_pass"] is True
    assert summary["all_ids_covered"] is True
    assert summary["missing_id_count"] == 0
    assert summary["duplicate_id_count"] == 0
    assert summary["parallel_batch_wall_time_ms"] == pytest.approx(16.0)
    assert summary["total_batch_wall_time_ms"] == pytest.approx(16.0)
    assert summary["avg_batch_wall_time_ms"] == pytest.approx(16.0)
    assert summary["end_to_end_wall_time_ms"] == pytest.approx(23.0)
    assert summary["end_to_end_wall_time_ms"] > summary["total_batch_wall_time_ms"]
    assert summary["avg_end_to_end_wall_time_ms"] == summary["end_to_end_wall_time_ms"]
    assert summary["baseline_end_to_end_wall_time_ms"] == 150.0
    expected_excluding = pytest.approx(120.0 / summary["avg_batch_wall_time_ms"])
    expected_including = pytest.approx(150.0 / summary["avg_end_to_end_wall_time_ms"])
    assert summary["speedup_vs_sequential_baseline"] == expected_excluding
    assert summary["speedup_excluding_warmup"] == expected_excluding
    assert summary["speedup_including_warmup"] == expected_including
    assert summary["effective_speedup"] == expected_including


def test_run_live_chunked_structured_smoke_rejects_queue_pressure_by_default_before_transport() -> (
    None
):
    transport_called = False

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called when queue pressure is blocked")

    with pytest.raises(
        ValueError,
        match="app_concurrency exceeds configured load parallel.*queue pressure",
    ):
        lmstudio_lab.run_live_chunked_structured_smoke(
            _live_config(dataset_id="blocks_json_medium_chunked"),
            run_id="live-chunked-queue-pressure-blocked",
            transport=forbidden_transport,
            verified_context_length=8192,
            app_concurrency=2,
        )

    assert transport_called is False


def test_run_live_chunked_structured_smoke_allows_queue_pressure_when_opted_in() -> None:
    transport_calls = 0

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        nonlocal transport_calls
        transport_calls += 1
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        chunk_ids = _payload_chunk_ids(payload)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(dataset_id="blocks_json_medium_chunked"),
        run_id="live-chunked-queue-pressure-allowed",
        transport=fake_transport,
        verified_context_length=8192,
        app_concurrency=2,
        allow_queue_pressure=True,
    )

    assert transport_calls == 4
    assert outcome.structured_errors == ()
    assert len(outcome.metrics) == 4
    metric_row = outcome.metrics[0].to_dict()
    assert metric_row["configured_parallel"] == 1
    assert metric_row["applied_parallel"] == 1
    assert metric_row["parallel_verified"] is None
    assert metric_row["queue_pressure_mode"] is True
    assert metric_row["parallel_semantics"] == "queue_pressure"
    assert outcome.batch_summary["requested_parallel"] == 1
    assert outcome.batch_summary["configured_parallel"] == 1
    assert outcome.batch_summary["applied_parallel"] == 1
    assert outcome.batch_summary["parallel_verified"] is None
    assert outcome.batch_summary["app_concurrency"] == 2
    assert outcome.batch_summary["queue_pressure_mode"] is True
    assert outcome.batch_summary["parallel_semantics"] == "queue_pressure"


def test_run_live_chunked_structured_smoke_rejects_productive_first_chunk_warmup_runs_before_transport() -> (
    None
):
    transport_called = False

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called for productive warmup mismatch")

    with pytest.raises(ValueError, match="productive_first_chunk.*warmup_runs=0"):
        lmstudio_lab.run_live_chunked_structured_smoke(
            _with_warmup_runs(
                _live_config(dataset_id="blocks_json_medium_chunked"),
                warmup_runs=1,
            ),
            run_id="live-chunked-productive-invalid-warmup",
            transport=forbidden_transport,
            verified_context_length=8192,
            effective_profile="productive_first_chunk",
        )

    assert transport_called is False


def test_run_live_chunked_structured_smoke_supports_full_batch_warmup_without_storing_metrics() -> (
    None
):
    captured_chunk_ids: list[tuple[int, ...]] = []

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        chunk_ids = _payload_chunk_ids(payload)
        captured_chunk_ids.append(chunk_ids)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _with_warmup_runs(
            _live_config(dataset_id="blocks_json_medium_chunked"),
            warmup_runs=1,
        ),
        run_id="live-chunked-full-warmup",
        transport=fake_transport,
        verified_context_length=8192,
        warmup_full_batch=True,
    )

    assert len(captured_chunk_ids) == 8
    assert captured_chunk_ids.count(tuple(range(25))) == 2
    assert captured_chunk_ids.count(tuple(range(25, 50))) == 2
    assert captured_chunk_ids.count(tuple(range(50, 75))) == 2
    assert captured_chunk_ids.count(tuple(range(75, 100))) == 2
    assert len(outcome.metrics) == 4
    assert [metric.request_id for metric in outcome.metrics] == [
        "batch_0001_chunk_0000",
        "batch_0001_chunk_0001",
        "batch_0001_chunk_0002",
        "batch_0001_chunk_0003",
    ]
    assert outcome.batch_summary["planned_requests"] == 8
    assert outcome.batch_summary["measured_request_count"] == 4
    assert outcome.batch_summary["warmup_policy"] == "concurrent_full_batch"
    assert outcome.batch_summary["warmup_request_count"] == 4


def test_run_live_chunked_structured_smoke_supports_explicit_concurrent_full_batch_policy() -> None:
    captured_chunk_ids: list[tuple[int, ...]] = []

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        chunk_ids = _payload_chunk_ids(payload)
        captured_chunk_ids.append(chunk_ids)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _with_warmup_runs(
            _live_config(dataset_id="blocks_json_medium_chunked"),
            warmup_runs=1,
        ),
        run_id="live-chunked-explicit-concurrent-full-warmup",
        transport=fake_transport,
        verified_context_length=8192,
        warmup_policy="concurrent_full_batch",
    )

    assert len(captured_chunk_ids) == 8
    assert len(outcome.metrics) == 4
    assert outcome.batch_summary["warmup_policy"] == "concurrent_full_batch"
    assert outcome.batch_summary["warmup_request_count"] == 4


def test_run_live_chunked_structured_smoke_supports_small_structured_warmup_policy() -> None:
    captured_payloads: list[dict[str, object]] = []

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        captured_payloads.append(payload)
        chunk_ids = _payload_chunk_ids(payload)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _with_warmup_runs(
            _live_config(dataset_id="blocks_json_medium_chunked"),
            warmup_runs=1,
        ),
        run_id="live-chunked-small-warmup",
        transport=fake_transport,
        verified_context_length=8192,
        warmup_policy="sequential_small_structured",
    )

    assert len(captured_payloads) == 5
    assert _payload_chunk_ids(captured_payloads[0]) == (101, 102)
    assert captured_payloads[0]["max_tokens"] == 512
    assert (
        captured_payloads[0]["response_format"]
        == lmstudio_lab.build_factual_blocks_response_format()
    )
    assert [metric.request_id for metric in outcome.metrics] == [
        "batch_0001_chunk_0000",
        "batch_0001_chunk_0001",
        "batch_0001_chunk_0002",
        "batch_0001_chunk_0003",
    ]
    assert all(metric.dataset_id == "blocks_json_medium_chunked" for metric in outcome.metrics)
    assert outcome.batch_summary["warmup_policy"] == "sequential_small_structured"
    assert outcome.batch_summary["warmup_request_count"] == 1
    assert outcome.batch_summary["planned_requests"] == 5


def test_run_live_chunked_structured_smoke_supports_sequential_full_batch_warmup_policy() -> None:
    captured_request_ids: list[str] = []

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        messages = payload.get("messages")
        assert isinstance(messages, list)
        captured_request_ids.append(
            f"{_payload_chunk_ids(payload)[0] // 25}:{payload['max_tokens']}"
        )
        chunk_ids = _payload_chunk_ids(payload)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _with_warmup_runs(
            _live_config(dataset_id="blocks_json_medium_chunked"),
            warmup_runs=1,
        ),
        run_id="live-chunked-sequential-full-warmup",
        transport=fake_transport,
        verified_context_length=8192,
        warmup_policy="sequential_full_batch",
    )

    assert captured_request_ids == [
        "0:1875",
        "1:1875",
        "2:1875",
        "3:1875",
        "0:1875",
        "1:1875",
        "2:1875",
        "3:1875",
    ]
    assert len(outcome.metrics) == 4
    assert outcome.batch_summary["warmup_policy"] == "sequential_full_batch"
    assert outcome.batch_summary["warmup_request_count"] == 4
    assert outcome.batch_summary["planned_requests"] == 8


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        pytest.param({"app_concurrency": 0}, "app_concurrency must be between", id="zero"),
        pytest.param(
            {"app_concurrency": 5},
            "app_concurrency must be between",
            id="above_chunks_count",
        ),
        pytest.param(
            {"app_concurrency": True},
            "app_concurrency must be an integer",
            id="bool",
        ),
        pytest.param(
            {"sequential_baseline_wall_time_ms": 0.0},
            "sequential_baseline_wall_time_ms must be positive",
            id="baseline_zero",
        ),
        pytest.param(
            {"sequential_baseline_wall_time_ms": -1.0},
            "sequential_baseline_wall_time_ms must be positive",
            id="baseline_negative",
        ),
    ],
)
def test_run_live_chunked_structured_smoke_rejects_invalid_concurrency_inputs_before_transport(
    kwargs: dict[str, object],
    match: str,
) -> None:
    def forbidden_transport(*_args, **_kwargs):
        raise AssertionError("transport should not be called for invalid chunked arguments")

    with pytest.raises(ValueError, match=match):
        lmstudio_lab.run_live_chunked_structured_smoke(
            _live_config(dataset_id="blocks_json_medium_chunked"),
            run_id="live-chunked-invalid-args",
            transport=forbidden_transport,
            verified_context_length=8192,
            **kwargs,
        )


@pytest.mark.parametrize(
    ("config", "kwargs", "match"),
    [
        pytest.param(
            _live_config(dataset_id="blocks_json_medium_chunked"),
            {"warmup_policy": "unsupported"},
            "warmup_policy must be one of",
            id="unsupported_policy",
        ),
        pytest.param(
            _live_config(dataset_id="blocks_json_medium_chunked"),
            {"warmup_policy": "sequential_chunk_0"},
            "requires warmup_runs=1",
            id="chunk0_requires_one_run",
        ),
        pytest.param(
            _with_warmup_runs(
                _live_config(dataset_id="blocks_json_medium_chunked"),
                warmup_runs=1,
            ),
            {"warmup_policy": "none"},
            "requires warmup_runs=0",
            id="none_requires_zero_runs",
        ),
        pytest.param(
            _with_warmup_runs(
                _live_config(dataset_id="blocks_json_medium_chunked"),
                warmup_runs=1,
            ),
            {
                "warmup_policy": "sequential_full_batch",
                "warmup_full_batch": True,
            },
            "incompatible with warmup_full_batch",
            id="policy_flag_conflict",
        ),
    ],
)
def test_run_live_chunked_structured_smoke_rejects_invalid_warmup_policy_inputs_before_transport(
    config: lmstudio_lab.LiveSmokeConfig,
    kwargs: dict[str, object],
    match: str,
) -> None:
    def forbidden_transport(*_args, **_kwargs):
        raise AssertionError("transport should not be called for invalid warmup policy inputs")

    with pytest.raises(ValueError, match=match):
        lmstudio_lab.run_live_chunked_structured_smoke(
            config,
            run_id="live-chunked-invalid-warmup-policy",
            transport=forbidden_transport,
            verified_context_length=8192,
            **kwargs,
        )


def test_run_live_chunked_structured_smoke_requires_verified_context_before_transport() -> None:
    transport_called = False

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called without verified context")

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _with_warmup_runs(
            _live_config(dataset_id="blocks_json_medium_chunked"),
            warmup_runs=1,
        ),
        run_id="live-chunked-missing-context",
        transport=forbidden_transport,
    )

    assert transport_called is False
    assert outcome.metrics == ()
    assert len(outcome.structured_errors) == 1
    assert outcome.structured_errors[0]["error_category"] == "context_fit_failed"
    assert outcome.structured_errors[0]["error_status"] == "missing_verified_context"
    assert outcome.batch_summary["error_category"] == "context_fit_failed"
    assert outcome.batch_summary["all_chunks_pass"] is False
    assert outcome.batch_summary["measured_request_count"] == 0


def test_run_live_chunked_structured_smoke_requires_exactly_one_model() -> None:
    config = lmstudio_lab.LiveSmokeConfig(
        experiment_id="live_json_smoke",
        models=(),
        modes=("json_schema_single",),
        datasets=("blocks_json_medium_chunked",),
        repeats=1,
        lmstudio_base_url="http://127.0.0.1:1234",
        allow_remote=False,
        hardware_profile="local_manual",
        warmup_runs=0,
        privacy=lmstudio_lab.LivePrivacyConfig(
            store_prompt_text=False,
            store_response_text=False,
            store_prompt_hash=True,
        ),
    )

    with pytest.raises(
        ValueError,
        match="live chunked structured smoke requires exactly one model",
    ):
        lmstudio_lab.run_live_chunked_structured_smoke(
            config,
            run_id="live-chunked-no-model",
            verified_context_length=8192,
        )


def test_run_live_chunked_structured_smoke_records_finish_length_failure_safely() -> None:
    call_index = 0

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        nonlocal call_index
        call_index += 1
        chunk_ids = _payload_chunk_ids(payload)
        finish_reason = "length" if chunk_ids and chunk_ids[0] == 50 else "stop"
        return {
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1000 + call_index,
                "completion_tokens": 150,
                "total_tokens": 1150 + call_index,
            },
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(dataset_id="blocks_json_medium_chunked"),
        run_id="live-chunked-finish-length",
        transport=fake_transport,
        verified_context_length=8192,
    )

    assert len(outcome.metrics) == 4
    assert len(outcome.structured_errors) == 1
    assert outcome.structured_errors[0]["error_category"] == "finish"
    assert outcome.batch_summary["batch_business_pass"] is False
    assert outcome.batch_summary["failed_chunk_ids"] == [2]
    assert outcome.batch_summary["finish_length_count"] == 1


def test_run_live_chunked_structured_smoke_retries_once_on_business_failure_and_recovers() -> None:
    request_payloads: list[dict[str, object]] = []
    attempts_by_chunk_ids: dict[tuple[int, ...], int] = {}
    response_sentinel = "SENTINEL_RETRY_SOURCE_RESPONSE"

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        request_payloads.append(json.loads(json.dumps(payload)))
        chunk_ids = _payload_chunk_ids(payload)
        attempt_index = attempts_by_chunk_ids.get(chunk_ids, 0)
        attempts_by_chunk_ids[chunk_ids] = attempt_index + 1
        if chunk_ids[0] == 0 and attempt_index == 0:
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": _chunk_id_diagnostics_failure_json(
                                chunk_ids,
                                text_sentinel=response_sentinel,
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            }
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(
            dataset_id="blocks_json_medium_chunked",
            business_failure_retry_limit=1,
        ),
        run_id="live-chunked-retry-recovered",
        transport=fake_transport,
        verified_context_length=8192,
    )

    assert len(outcome.metrics) == 4
    assert outcome.structured_errors == ()
    assert len(request_payloads) == 5
    assert attempts_by_chunk_ids[tuple(range(25))] == 2

    retried_metric = next(
        metric for metric in outcome.metrics if metric.request_id == "batch_0001_chunk_0000"
    )
    assert retried_metric.validation.business_pass is True
    assert retried_metric.validation.retry_count == 1
    assert retried_metric.error_category is None
    assert retried_metric.validation.expected_ids == tuple(range(25))
    assert retried_metric.validation.returned_ids == tuple(range(25))

    retry_messages = request_payloads[1]["messages"]
    assert isinstance(retry_messages, list)
    retry_messages_text = "\n".join(
        message["content"]
        for message in retry_messages
        if isinstance(message, dict) and isinstance(message.get("content"), str)
    )
    assert response_sentinel not in retry_messages_text
    assert "expected_ids" in retry_messages_text
    assert "returned_ids" in retry_messages_text
    assert "missing_ids" in retry_messages_text
    assert "duplicate_ids" in retry_messages_text
    assert "extra_ids" in retry_messages_text
    assert "reordered_count" in retry_messages_text
    assert "do not merge, split, omit, duplicate, or reorder blocks" in retry_messages_text.lower()

    assert outcome.batch_summary["business_failure_retry_limit"] == 1
    assert outcome.batch_summary["retry_attempt_count"] == 1
    assert outcome.batch_summary["retry_recovered_count"] == 1
    assert outcome.batch_summary["retry_failed_count"] == 0


def test_run_live_chunked_structured_smoke_retry_failure_keeps_final_retry_error() -> None:
    attempts_by_chunk_ids: dict[tuple[int, ...], int] = {}

    def fake_transport(
        _url: str,
        payload: dict[str, object],
        _timeout_s: float,
    ) -> dict[str, object]:
        chunk_ids = _payload_chunk_ids(payload)
        attempts_by_chunk_ids[chunk_ids] = attempts_by_chunk_ids.get(chunk_ids, 0) + 1
        if chunk_ids[0] == 0:
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": _chunk_id_diagnostics_failure_json(chunk_ids)},
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            }
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(
            dataset_id="blocks_json_medium_chunked",
            business_failure_retry_limit=1,
        ),
        run_id="live-chunked-retry-failed",
        transport=fake_transport,
        verified_context_length=8192,
    )

    assert len(outcome.metrics) == 4
    assert len(outcome.structured_errors) == 1
    assert attempts_by_chunk_ids[tuple(range(25))] == 2

    retried_metric = next(
        metric for metric in outcome.metrics if metric.request_id == "batch_0001_chunk_0000"
    )
    assert retried_metric.validation.business_pass is False
    assert retried_metric.validation.retry_count == 1
    assert retried_metric.error_category == "business"

    structured_error = outcome.structured_errors[0]
    assert structured_error["request_id"] == "batch_0001_chunk_0000"
    assert structured_error["error_category"] == "business"
    assert structured_error["retry_count"] == 1
    assert structured_error["expected_ids"] == list(range(25))
    assert structured_error["missing_ids"] == [1, 24]
    assert structured_error["extra_ids"] == [999]

    assert outcome.batch_summary["retry_attempt_count"] == 1
    assert outcome.batch_summary["retry_recovered_count"] == 0
    assert outcome.batch_summary["retry_failed_count"] == 1


@pytest.mark.parametrize(
    ("response_text", "expected_error_category"),
    [
        pytest.param('{"schema_version":', "json", id="invalid_json"),
        pytest.param(_schema_failure_json(), "schema", id="schema_failure"),
    ],
)
def test_run_live_chunked_structured_smoke_does_not_retry_json_or_schema_failures(
    response_text: str,
    expected_error_category: str,
) -> None:
    request_count = 0

    def fake_transport(
        _url: str,
        payload: dict[str, object],
        _timeout_s: float,
    ) -> dict[str, object]:
        nonlocal request_count
        request_count += 1
        chunk_ids = _payload_chunk_ids(payload)
        if chunk_ids[0] == 0:
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": response_text},
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            }
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
        }

    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(
            dataset_id="blocks_json_medium_chunked",
            business_failure_retry_limit=1,
        ),
        run_id=f"live-chunked-no-retry-{expected_error_category}",
        transport=fake_transport,
        verified_context_length=8192,
    )

    assert request_count == 4
    assert len(outcome.structured_errors) == 1
    assert outcome.structured_errors[0]["error_category"] == expected_error_category
    assert outcome.structured_errors[0]["retry_count"] is None
    assert outcome.batch_summary["retry_attempt_count"] == 0
    assert outcome.batch_summary["retry_recovered_count"] == 0
    assert outcome.batch_summary["retry_failed_count"] == 0


def test_run_live_chunked_structured_smoke_keeps_artifacts_privacy_safe() -> None:
    outcome = lmstudio_lab.run_live_chunked_structured_smoke(
        _live_config(dataset_id="blocks_json_medium_chunked"),
        run_id="live-chunked-privacy",
        transport=lambda _url, payload, _timeout_s: {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(_payload_chunk_ids(payload))},
                }
            ],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 150,
                "total_tokens": 1150,
            },
        },
        verified_context_length=8192,
    )

    serialized = _metric_strings(
        outcome.batch_summary,
        *(metric.to_dict() for metric in outcome.metrics),
        *outcome.structured_errors,
    )
    assert "Synthetic block 00 records neutral benchmark notes" not in serialized
    assert '"messages"' not in serialized
    assert '"content"' not in serialized
    assert "http://127.0.0.1:1234" not in serialized
    assert "input_blocks.json" not in serialized
    assert '"warmup_policy": "none"' in serialized
    assert '"warmup_request_count": 0' in serialized


def test_run_live_structured_smoke_maps_empty_content_safely() -> None:
    reasoning_text = "Private reasoning should never be stored."

    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-empty",
        transport=lambda *_args: {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "",
                        "reasoning_content": reasoning_text,
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
        },
    )

    assert outcome.metric.error_category == "empty"
    assert outcome.metric.content_empty is True
    assert outcome.metric.reasoning_content_present is True
    assert outcome.metric.validation.business_pass is False
    assert outcome.metric.validation.json_parse_pass is False
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "empty"
    assert outcome.structured_error["content_empty"] is True
    assert outcome.structured_error["reasoning_content_present"] is True

    serialized = _metric_strings(outcome.metric.to_dict(), outcome.structured_error)
    assert reasoning_text not in serialized
    assert '"reasoning_content":' not in serialized


def test_run_live_structured_smoke_preserves_missing_reasoning_state_for_no_message_payload() -> (
    None
):
    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-no-message",
        transport=lambda *_args: {
            "choices": [{"finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
        },
    )

    assert outcome.metric.error_category == "empty"
    assert outcome.metric.content_empty is True
    assert outcome.metric.reasoning_content_present is None
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "empty"
    assert outcome.structured_error["reasoning_content_present"] is None


def test_run_live_structured_smoke_maps_invalid_json_to_safe_category() -> None:
    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-invalid-json",
        transport=lambda *_args: {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"schema_version":'},
                }
            ]
        },
    )

    assert outcome.metric.error_category == "json"
    assert outcome.metric.validation.json_parse_pass is False
    assert outcome.metric.validation.schema_pass is False
    assert outcome.metric.validation.business_pass is False
    assert outcome.metric.response_hash is not None
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "json"


def test_run_live_structured_smoke_prioritizes_finish_length_over_truncated_json() -> None:
    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(dataset_id="blocks_json_medium"),
        run_id="live-medium-truncated-json-length",
        transport=lambda *_args: {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": '{"schema_version":'},
                }
            ]
        },
        verified_context_length=32768,
    )

    assert outcome.metric.error_category == "finish"
    assert outcome.metric.validation.finish_reason == "length"
    assert outcome.metric.validation.json_parse_pass is False
    assert outcome.metric.validation.schema_pass is False
    assert outcome.metric.validation.business_pass is False
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "finish"


def test_run_live_structured_smoke_maps_business_failure_safely() -> None:
    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-business-failure",
        transport=lambda *_args: {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _business_failure_json()},
                }
            ]
        },
    )

    assert outcome.metric.error_category == "business"
    assert outcome.metric.validation.schema_pass is True
    assert outcome.metric.validation.business_pass is False
    assert outcome.metric.validation.ids_exact_pass is False
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "business"


def test_run_live_structured_smoke_maps_finish_length_safely() -> None:
    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-finish-length",
        transport=lambda *_args: {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": _valid_blocks_json()},
                }
            ]
        },
    )

    assert outcome.metric.error_category == "finish"
    assert outcome.metric.validation.finish_reason == "length"
    assert outcome.metric.validation.business_pass is False
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "finish"


def test_run_live_structured_smoke_maps_medium_finish_length_safely() -> None:
    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(dataset_id="blocks_json_medium"),
        run_id="live-medium-finish-length",
        transport=lambda *_args: {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": _valid_blocks_json(tuple(range(100)))},
                }
            ]
        },
        verified_context_length=32768,
    )

    assert outcome.metric.error_category == "finish"
    assert outcome.metric.validation.finish_reason == "length"
    assert outcome.metric.validation.business_pass is False
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "finish"


def test_run_live_structured_smoke_maps_reasoning_leak_safely() -> None:
    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-reasoning-leak",
        transport=lambda *_args: {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "<think>hidden chain of thought</think>"},
                }
            ]
        },
    )

    assert outcome.metric.error_category == "reasoning"
    assert outcome.metric.validation.reasoning_leak is True
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == "reasoning"


@pytest.mark.parametrize(
    ("raised_error", "expected_category", "expected_status"),
    [
        pytest.param(TimeoutError("timed out"), "timeout", "timeout", id="timeout"),
        pytest.param(
            urllib_error.URLError(ConnectionRefusedError("refused")),
            "lmstudio_unavailable",
            "unavailable",
            id="connection_refused",
        ),
        pytest.param(
            urllib_error.URLError(OSError("network down")),
            "network",
            "failed",
            id="network",
        ),
        pytest.param(
            urllib_error.HTTPError(
                "http://127.0.0.1:1234/v1/chat/completions",
                404,
                "Not Found",
                hdrs=None,
                fp=None,
            ),
            "http_error",
            "http_404",
            id="http_error",
        ),
    ],
)
def test_run_live_structured_smoke_maps_transport_failures_without_leaking_url(
    raised_error: Exception,
    expected_category: str,
    expected_status: str,
) -> None:
    def fake_transport(*_args, **_kwargs):
        raise raised_error

    outcome = lmstudio_lab.run_live_structured_smoke(
        _live_config(),
        run_id="live-transport-error",
        transport=fake_transport,
    )

    assert outcome.metric.error_category == expected_category
    assert outcome.metric.error_status == expected_status
    assert outcome.structured_error is not None
    assert outcome.structured_error["error_category"] == expected_category

    serialized = _metric_strings(outcome.metric.to_dict(), outcome.structured_error)
    assert "http://127.0.0.1:1234/v1/chat/completions" not in serialized
    assert '"messages"' not in serialized
    assert '"content"' not in serialized


def test_run_live_structured_smoke_rejects_unsupported_dataset_without_leaking_paths() -> None:
    project_root = Path(__file__).resolve().parents[2]

    with pytest.raises(ValueError, match="supports only") as exc_info:
        lmstudio_lab.run_live_structured_smoke(
            _live_config(dataset_id="blocks_json_large"),
            run_id="live-unsupported-dataset",
            transport=lambda *_args: {},
        )

    _assert_no_private_paths(str(exc_info.value), project_root=project_root)
    assert "input_blocks.json" not in str(exc_info.value)
    assert "expected_ids.json" not in str(exc_info.value)


def test_cli_run_without_live_keeps_existing_dry_run_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "experiments" / "lmstudio" / "examples" / "dry_run_minimal.yaml"

    def _forbidden_live_runner(*args, **kwargs):
        raise AssertionError("live runner should not be used without --live")

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", _forbidden_live_runner)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "dry-path-still-default",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "run_dry-path-still-default_dry_run_minimal").exists()


def test_cli_managed_cache_compare_live_dispatches_without_real_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_4_cache_stateful_vs_prefix_gemma4_e2b_live.yaml"
    )
    call_args: dict[str, object] = {}

    def fake_runner(args) -> int:
        call_args["config_path"] = args.config_path
        call_args["output_root"] = args.output_root
        call_args["run_id"] = args.run_id
        call_args["managed_cache_compare_live"] = args.managed_cache_compare_live
        call_args["managed_cache_live_smoke"] = args.managed_cache_live_smoke
        call_args["live"] = args.live
        return 0

    monkeypatch.setattr(lmstudio_benchmark, "_run_managed_cache_compare_live", fake_runner)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-cache-compare-live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-cache-compare-cli",
        ]
    )

    assert exit_code == 0
    assert call_args == {
        "config_path": config_path,
        "output_root": tmp_path / "results",
        "run_id": "managed-cache-compare-cli",
        "managed_cache_compare_live": True,
        "managed_cache_live_smoke": False,
        "live": False,
    }


def test_cli_managed_cache_instrument_live_dispatches_without_real_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_4b_cache_stateful_instrumentation_gemma4_e2b_live.yaml"
    )
    call_args: dict[str, object] = {}

    def fake_runner(args) -> int:
        call_args["config_path"] = args.config_path
        call_args["output_root"] = args.output_root
        call_args["run_id"] = args.run_id
        call_args["managed_cache_instrument_live"] = args.managed_cache_instrument_live
        call_args["managed_cache_compare_live"] = args.managed_cache_compare_live
        call_args["live"] = args.live
        return 0

    monkeypatch.setattr(lmstudio_benchmark, "_run_managed_cache_instrument_live", fake_runner)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-cache-instrument-live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-cache-instrument-cli",
        ]
    )

    assert exit_code == 0
    assert call_args == {
        "config_path": config_path,
        "output_root": tmp_path / "results",
        "run_id": "managed-cache-instrument-cli",
        "managed_cache_instrument_live": True,
        "managed_cache_compare_live": False,
        "live": False,
    }


def test_cli_managed_cache_25k_prep_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root / "experiments" / "lmstudio" / "configs" / "l3_5_cache_25k_no_live_prep.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_cache_25k_no_live_prep(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            return {"measurement_status": "not_measured_no_live"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_live_smoke",
        lambda args: (_ for _ in ()).throw(
            AssertionError("cache live smoke runner must not be used")
        ),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-cache-25k-prep",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-cache-25k-prep-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert call_args["system_sampler"] is None
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-cache-25k-prep-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_cache_25k_prep"}
    assert call_args["run_dir"] == (
        tmp_path / "results" / "run_managed-cache-25k-prep-cli_l3_5_cache_25k_no_live_prep"
    )


def test_cli_managed_l3_6_25k_no_live_preflight_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_6_25k_no_live_preflight_gemma4_e2b.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_l3_6_25k_no_live_preflight(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            return {"measurement_status": "not_measured_no_live"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_responses_cache_probe",
        lambda args: (_ for _ in ()).throw(
            AssertionError("responses probe runner must not be used")
        ),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_32k_load_only",
        lambda args: (_ for _ in ()).throw(AssertionError("32k load-only runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_25k_prep",
        lambda args: (_ for _ in ()).throw(AssertionError("25k prep runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_live_smoke",
        lambda args: (_ for _ in ()).throw(
            AssertionError("cache live smoke runner must not be used")
        ),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-l3-6-25k-preflight",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-l3-6-25k-preflight-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert call_args["system_sampler"] is None
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-l3-6-25k-preflight-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_l3_6_25k_preflight"}
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-l3-6-25k-preflight-cli_l3_6_25k_no_live_preflight_gemma4_e2b"
    )


def test_cli_managed_cache_32k_load_only_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_5b_32k_load_only_smoke_gemma4_e2b.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_cache_32k_load_only_smoke(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
            timeout_s=120.0,
            native_transport=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            call_args["timeout_s"] = timeout_s
            call_args["native_transport"] = native_transport
            return {"decision": "load_only_pass"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_live_smoke",
        lambda args: (_ for _ in ()).throw(
            AssertionError("cache live smoke runner must not be used")
        ),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-cache-32k-load-only",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-cache-32k-load-only-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-cache-32k-load-only-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_cache_32k_load_only"}
    assert call_args["timeout_s"] == 120.0
    assert call_args["native_transport"] is None
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-cache-32k-load-only-cli_l3_5b_32k_load_only_smoke_gemma4_e2b"
    )


def test_cli_managed_cache_32k_load_only_rejects_l3_6c_conflict_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_5b_32k_load_only_smoke_gemma4_e2b.yaml"
    )
    config_load_called = False
    runner_called = False

    def forbidden_load(*_args, **_kwargs):
        nonlocal config_load_called
        config_load_called = True
        raise AssertionError("32k load-only config load should not run for rejected CLI args")

    class _ForbiddenManagedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal runner_called
            runner_called = True
            raise AssertionError(
                "32k load-only runner should not be constructed for rejected CLI args"
            )

    monkeypatch.setattr(lmstudio_benchmark, "load_raw_experiment_config", forbidden_load)
    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _ForbiddenManagedRunner)

    with pytest.raises(ValueError, match="mutually exclusive"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--managed-cache-32k-load-only",
                "--managed-l3-6c-compact-memory-live-smoke",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "managed-cache-32k-load-only-conflict",
            ]
        )

    assert config_load_called is False
    assert runner_called is False


def test_cli_l3_8b_gemma4_e4b_load_only_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_8b_gemma4_e4b_load_only_16k_32k.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_l3_8b_gemma4_e4b_load_only_16k_32k(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
            timeout_s=120.0,
            native_transport=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            call_args["timeout_s"] = timeout_s
            call_args["native_transport"] = native_transport
            return {"decision": "load_only_passed"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_32k_load_only",
        lambda args: (_ for _ in ()).throw(
            AssertionError("32k load-only runner must not be used for L3.8b dispatch")
        ),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-l3-8b-gemma4-e4b-load-only",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-l3-8b-gemma4-e4b-load-only-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-l3-8b-gemma4-e4b-load-only-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_l3_8b_gemma4_e4b_load_only"}
    assert call_args["timeout_s"] == 120.0
    assert call_args["native_transport"] is None
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-l3-8b-gemma4-e4b-load-only-cli_l3_8b_gemma4_e4b_load_only_16k_32k"
    )


def test_cli_l3_8b_gemma4_e4b_load_only_rejects_live_conflict_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_8b_gemma4_e4b_load_only_16k_32k.yaml"
    )
    config_load_called = False
    runner_called = False

    def forbidden_load(*_args, **_kwargs):
        nonlocal config_load_called
        config_load_called = True
        raise AssertionError("L3.8b config load should not run for rejected CLI args")

    class _ForbiddenManagedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal runner_called
            runner_called = True
            raise AssertionError("L3.8b runner should not be constructed for rejected CLI args")

    monkeypatch.setattr(lmstudio_benchmark, "load_raw_experiment_config", forbidden_load)
    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _ForbiddenManagedRunner)

    with pytest.raises(ValueError, match="mutually exclusive"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--managed-l3-8b-gemma4-e4b-load-only",
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "managed-l3-8b-gemma4-e4b-load-only-conflict",
            ]
        )

    assert config_load_called is False
    assert runner_called is False


def test_cli_l3_9c_gemma4_12b_qat_load_only_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_9c_gemma4_12b_qat_load_only_8k_16k.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_l3_9c_gemma4_12b_qat_load_only_8k_16k(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
            timeout_s=120.0,
            native_transport=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            call_args["timeout_s"] = timeout_s
            call_args["native_transport"] = native_transport
            return {"decision": "load_only_passed"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-l3-9c-gemma4-12b-qat-load-only",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-l3-9c-gemma4-12b-qat-load-only-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-l3-9c-gemma4-12b-qat-load-only-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_l3_9c_gemma4_12b_qat_load_only"}
    assert call_args["timeout_s"] == 120.0
    assert call_args["native_transport"] is None
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-l3-9c-gemma4-12b-qat-load-only-cli_l3_9c_gemma4_12b_qat_load_only_8k_16k"
    )


def test_cli_l3_9c_gemma4_12b_qat_load_only_rejects_managed_live_conflict_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_9c_gemma4_12b_qat_load_only_8k_16k.yaml"
    )
    config_load_called = False
    runner_called = False

    def forbidden_load(*_args, **_kwargs):
        nonlocal config_load_called
        config_load_called = True
        raise AssertionError("L3.9c config load should not run for rejected CLI args")

    class _ForbiddenManagedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal runner_called
            runner_called = True
            raise AssertionError("L3.9c runner should not be constructed for rejected CLI args")

    monkeypatch.setattr(lmstudio_benchmark, "load_raw_experiment_config", forbidden_load)
    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _ForbiddenManagedRunner)

    with pytest.raises(ValueError, match="mutually exclusive"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--managed-l3-9c-gemma4-12b-qat-load-only",
                "--managed-live",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "managed-l3-9c-gemma4-12b-qat-load-only-conflict",
            ]
        )

    assert config_load_called is False
    assert runner_called is False


def test_cli_l3_9d_gemma4_26b_a4b_load_only_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_9d_gemma4_26b_a4b_qat_load_only_8k.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_l3_9d_gemma4_26b_a4b_qat_load_only_8k(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
            timeout_s=120.0,
            native_transport=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            call_args["timeout_s"] = timeout_s
            call_args["native_transport"] = native_transport
            return {"decision": "load_only_passed"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_l3_8b_gemma4_e4b_load_only",
        lambda args: (_ for _ in ()).throw(AssertionError("L3.8b runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-l3-9d-gemma4-26b-a4b-load-only",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-l3-9d-gemma4-26b-a4b-load-only-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-l3-9d-gemma4-26b-a4b-load-only-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_l3_9d_gemma4_26b_a4b_load_only"}
    assert call_args["timeout_s"] == 120.0
    assert call_args["native_transport"] is None
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-l3-9d-gemma4-26b-a4b-load-only-cli_l3_9d_gemma4_26b_a4b_qat_load_only_8k"
    )


def test_cli_l3_9d_gemma4_26b_a4b_load_only_rejects_l3_8b_conflict_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_9d_gemma4_26b_a4b_qat_load_only_8k.yaml"
    )
    config_load_called = False
    runner_called = False

    def forbidden_load(*_args, **_kwargs):
        nonlocal config_load_called
        config_load_called = True
        raise AssertionError("L3.9d config load should not run for rejected CLI args")

    class _ForbiddenManagedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal runner_called
            runner_called = True
            raise AssertionError("L3.9d runner should not be constructed for rejected CLI args")

    monkeypatch.setattr(lmstudio_benchmark, "load_raw_experiment_config", forbidden_load)
    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _ForbiddenManagedRunner)

    with pytest.raises(ValueError, match="mutually exclusive"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--managed-l3-9d-gemma4-26b-a4b-load-only",
                "--managed-l3-8b-gemma4-e4b-load-only",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "managed-l3-9d-gemma4-26b-a4b-load-only-conflict",
            ]
        )

    assert config_load_called is False
    assert runner_called is False


def test_cli_l3_8c_gemma4_e4b_tiny_live_smoke_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_8c_gemma4_e4b_tiny_live_smoke.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_l3_8c_gemma4_e4b_tiny_live_smoke(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
            timeout_s=120.0,
            native_transport=None,
            chat_transport=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            call_args["timeout_s"] = timeout_s
            call_args["native_transport"] = native_transport
            call_args["chat_transport"] = chat_transport
            return {"decision": "candidate_tiny_live_smoke_pass"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_l3_8b_gemma4_e4b_load_only",
        lambda args: (_ for _ in ()).throw(AssertionError("L3.8b runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_l3_6c_compact_memory_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("L3.6c runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-l3-8c-gemma4-e4b-tiny-live-smoke",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-l3-8c-gemma4-e4b-tiny-live-smoke-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-l3-8c-gemma4-e4b-tiny-live-smoke-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_l3_8c_gemma4_e4b_tiny_live_smoke"}
    assert call_args["timeout_s"] == 120.0
    assert call_args["native_transport"] is None
    assert call_args["chat_transport"] is None
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-l3-8c-gemma4-e4b-tiny-live-smoke-cli_l3_8c_gemma4_e4b_tiny_live_smoke"
    )


def test_cli_l3_8c_gemma4_e4b_tiny_live_smoke_rejects_live_conflict_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_8c_gemma4_e4b_tiny_live_smoke.yaml"
    )
    config_load_called = False
    runner_called = False

    def forbidden_load(*_args, **_kwargs):
        nonlocal config_load_called
        config_load_called = True
        raise AssertionError("L3.8c config load should not run for rejected CLI args")

    class _ForbiddenManagedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal runner_called
            runner_called = True
            raise AssertionError("L3.8c runner should not be constructed for rejected CLI args")

    monkeypatch.setattr(lmstudio_benchmark, "load_raw_experiment_config", forbidden_load)
    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _ForbiddenManagedRunner)

    with pytest.raises(ValueError, match="mutually exclusive"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--managed-l3-8c-gemma4-e4b-tiny-live-smoke",
                "--managed-l3-6c-compact-memory-live-smoke",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "managed-l3-8c-gemma4-e4b-tiny-live-smoke-conflict",
            ]
        )

    assert config_load_called is False
    assert runner_called is False


def test_cli_l3_8d_gemma4_e4b_strict_json_smoke_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_8d_gemma4_e4b_strict_json_smoke.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_l3_8d_gemma4_e4b_strict_json_smoke(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
            timeout_s=120.0,
            native_transport=None,
            chat_transport=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            call_args["timeout_s"] = timeout_s
            call_args["native_transport"] = native_transport
            call_args["chat_transport"] = chat_transport
            return {"decision": "l3_8d_strict_json_smoke_pass"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_l3_8c_gemma4_e4b_tiny_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("L3.8c runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-l3-8d-gemma4-e4b-strict-json-smoke",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-l3-8d-gemma4-e4b-strict-json-smoke-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-l3-8d-gemma4-e4b-strict-json-smoke-cli"
    assert call_args["providers"] == {
        "lmstudio_local": "managed_l3_8d_gemma4_e4b_strict_json_smoke"
    }
    assert call_args["timeout_s"] == 120.0
    assert call_args["native_transport"] is None
    assert call_args["chat_transport"] is None
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-l3-8d-gemma4-e4b-strict-json-smoke-cli_l3_8d_gemma4_e4b_strict_json_smoke"
    )


def test_cli_l3_8d_gemma4_e4b_strict_json_smoke_rejects_live_conflict_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_8d_gemma4_e4b_strict_json_smoke.yaml"
    )
    config_load_called = False
    runner_called = False

    def forbidden_load(*_args, **_kwargs):
        nonlocal config_load_called
        config_load_called = True
        raise AssertionError("L3.8d config load should not run for rejected CLI args")

    class _ForbiddenManagedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal runner_called
            runner_called = True
            raise AssertionError("L3.8d runner should not be constructed for rejected CLI args")

    monkeypatch.setattr(lmstudio_benchmark, "load_raw_experiment_config", forbidden_load)
    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _ForbiddenManagedRunner)

    with pytest.raises(ValueError, match="mutually exclusive"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--managed-l3-8d-gemma4-e4b-strict-json-smoke",
                "--managed-l3-7d-structured-json-live-smoke",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "managed-l3-8d-gemma4-e4b-strict-json-smoke-conflict",
            ]
        )

    assert config_load_called is False
    assert runner_called is False


@pytest.mark.parametrize(
    ("config_name", "experiment_id", "model_key", "model_id"),
    [
        pytest.param(
            "l3_9b_gemma_family_blocks_json_gemma4_e2b.yaml",
            "l3_9b_gemma_family_blocks_json_gemma4_e2b",
            "gemma4_e2b_q4km",
            "google/gemma-4-e2b",
            id="gemma4_e2b",
        ),
        pytest.param(
            "l3_9b_gemma_family_blocks_json_gemma4_e4b.yaml",
            "l3_9b_gemma_family_blocks_json_gemma4_e4b",
            "gemma4_e4b_q4km",
            "google/gemma-4-e4b",
            id="gemma4_e4b",
        ),
        pytest.param(
            "l3_9c_gemma_family_blocks_json_gemma4_12b_qat.yaml",
            "l3_9c_gemma_family_blocks_json_gemma4_12b_qat",
            "gemma4_12b_qat",
            "google/gemma-4-12b-qat",
            id="gemma4_12b_qat",
        ),
    ],
)
def test_l3_9_blocks_json_managed_live_configs_load_with_guardrails(
    config_name: str,
    experiment_id: str,
    model_key: str,
    model_id: str,
) -> None:
    config_path = (
        Path(__file__).resolve().parents[2] / "experiments" / "lmstudio" / "configs" / config_name
    )

    config = lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)

    assert config.experiment_id == experiment_id
    assert config.hardware_profile == "local_manual"
    assert config.lmstudio_base_url == "http://127.0.0.1:1234"
    assert config.allow_remote is False
    assert config.modes == ("json_schema_single",)
    assert config.datasets == ("blocks_json_medium_chunked",)
    assert config.repeats == 1
    assert config.warmup_runs == 0
    assert config.structured_prompt_variant == "baseline"
    assert config.structured_schema_variant == "baseline"
    assert config.business_failure_retry_limit == 0
    assert config.privacy == lmstudio_lab.LivePrivacyConfig(
        store_prompt_text=False,
        store_response_text=False,
        store_prompt_hash=True,
    )
    assert config.models == (
        lmstudio_lab.LiveModelConfig(
            key=model_key,
            model_id=model_id,
            load={
                "context_length": (8192,),
                "parallel": (1,),
            },
        ),
    )


@pytest.mark.parametrize(
    ("config_name", "experiment_id", "prompt_variant"),
    [
        pytest.param(
            "l3_10c_gemma4_12b_qat_prompt_strict_id_contract.yaml",
            "l3_10c_gemma4_12b_qat_prompt_strict_id_contract",
            "strict_id_contract",
            id="strict_id_contract",
        ),
        pytest.param(
            "l3_10c_gemma4_12b_qat_prompt_ultra_minimal_transform.yaml",
            "l3_10c_gemma4_12b_qat_prompt_ultra_minimal_transform",
            "ultra_minimal_transform",
            id="ultra_minimal_transform",
        ),
    ],
)
def test_l3_10c_prompt_variant_configs_load_with_guardrails(
    config_name: str,
    experiment_id: str,
    prompt_variant: str,
) -> None:
    config_path = (
        Path(__file__).resolve().parents[2] / "experiments" / "lmstudio" / "configs" / config_name
    )

    config = lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)

    assert config.experiment_id == experiment_id
    assert config.models[0].key == "gemma4_12b_qat"
    assert config.models[0].model_id == "google/gemma-4-12b-qat"
    assert config.datasets == ("blocks_json_medium_chunked",)
    assert config.modes == ("json_schema_single",)
    assert config.repeats == 1
    assert config.warmup_runs == 0
    assert config.structured_prompt_variant == prompt_variant
    assert config.structured_schema_variant == "baseline"
    assert config.business_failure_retry_limit == 0
    assert config.privacy == lmstudio_lab.LivePrivacyConfig(
        store_prompt_text=False,
        store_response_text=False,
        store_prompt_hash=True,
    )


def test_load_live_smoke_config_rejects_invalid_structured_prompt_variant(tmp_path: Path) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        structured_prompt_variant="unsupported_variant",
    )

    with pytest.raises(ValueError, match="structured_prompt_variant must be one of"):
        lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)


def test_load_live_smoke_config_defaults_structured_schema_variant_to_baseline(
    tmp_path: Path,
) -> None:
    config_path = _write_parametrized_live_config(tmp_path)

    config = lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)

    assert config.structured_schema_variant == "baseline"


def test_load_live_smoke_config_accepts_per_position_id_const_structured_schema_variant(
    tmp_path: Path,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        structured_schema_variant="per_position_id_const",
    )

    config = lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)

    assert config.structured_schema_variant == "per_position_id_const"


@pytest.mark.parametrize("retry_limit", [0, 1])
def test_load_live_smoke_config_accepts_business_failure_retry_limit(
    tmp_path: Path,
    retry_limit: int,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        business_failure_retry_limit=retry_limit,
    )

    config = lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)

    assert config.business_failure_retry_limit == retry_limit


def test_load_live_smoke_config_rejects_invalid_business_failure_retry_limit(
    tmp_path: Path,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        business_failure_retry_limit=2,
    )

    with pytest.raises(ValueError, match="business_failure_retry_limit must be 0 or 1"):
        lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)


def test_load_live_smoke_config_rejects_invalid_structured_schema_variant(tmp_path: Path) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        structured_schema_variant="unsupported_schema_variant",
    )

    with pytest.raises(ValueError, match="structured_schema_variant must be one of"):
        lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)


def test_cli_managed_l3_6c_compact_memory_live_smoke_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_6c_25k_compact_memory_live_smoke_gemma4_e2b.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_l3_6c_25k_compact_memory_live_smoke(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
            timeout_s=120.0,
            native_transport=None,
            chat_transport=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            call_args["timeout_s"] = timeout_s
            call_args["native_transport"] = native_transport
            call_args["chat_transport"] = chat_transport
            return {"decision": "compact_memory_live_smoke_pass"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_32k_load_only",
        lambda args: (_ for _ in ()).throw(AssertionError("32k load-only runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_25k_prep",
        lambda args: (_ for _ in ()).throw(AssertionError("25k prep runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_live_smoke",
        lambda args: (_ for _ in ()).throw(
            AssertionError("cache live smoke runner must not be used")
        ),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-l3-6c-compact-memory-live-smoke",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-l3-6c-compact-memory-live-smoke-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-l3-6c-compact-memory-live-smoke-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_l3_6c_compact_memory_live_smoke"}
    assert call_args["timeout_s"] == 120.0
    assert call_args["native_transport"] is None
    assert call_args["chat_transport"] is None
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-l3-6c-compact-memory-live-smoke-cli_l3_6c_25k_compact_memory_live_smoke_gemma4_e2b"
    )


def test_cli_managed_l3_6d_mode_comparison_live_rejects_l3_6c_conflict_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_6d_25k_mode_comparison_gemma4_e2b.yaml"
    )
    config_load_called = False
    runner_called = False

    def forbidden_load(*_args, **_kwargs):
        nonlocal config_load_called
        config_load_called = True
        raise AssertionError("L3.6d config load should not run for rejected CLI args")

    class _ForbiddenManagedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal runner_called
            runner_called = True
            raise AssertionError("L3.6d runner should not be constructed for rejected CLI args")

    monkeypatch.setattr(lmstudio_benchmark, "load_raw_experiment_config", forbidden_load)
    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _ForbiddenManagedRunner)

    with pytest.raises(ValueError, match="mutually exclusive"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--managed-l3-6d-mode-comparison-live",
                "--managed-l3-6c-compact-memory-live-smoke",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "managed-l3-6d-conflict",
            ]
        )

    assert config_load_called is False
    assert runner_called is False


def test_cli_managed_l3_6d_mode_comparison_live_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_6d_25k_mode_comparison_gemma4_e2b.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_l3_6d_25k_mode_comparison_live(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
            timeout_s=120.0,
            native_transport=None,
            chat_transport=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            call_args["timeout_s"] = timeout_s
            call_args["native_transport"] = native_transport
            call_args["chat_transport"] = chat_transport
            return {"decision": "mode_comparison_live_pass"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_l3_6c_compact_memory_live_smoke",
        lambda args: (_ for _ in ()).throw(
            AssertionError("L3.6c runner must not be used for L3.6d dispatch")
        ),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_32k_load_only",
        lambda args: (_ for _ in ()).throw(AssertionError("32k load-only runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_25k_prep",
        lambda args: (_ for _ in ()).throw(AssertionError("25k prep runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-l3-6d-mode-comparison-live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-l3-6d-mode-comparison-live-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-l3-6d-mode-comparison-live-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_l3_6d_mode_comparison_live"}
    assert call_args["timeout_s"] == 120.0
    assert call_args["native_transport"] is None
    assert call_args["chat_transport"] is None
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-l3-6d-mode-comparison-live-cli_l3_6d_25k_mode_comparison_gemma4_e2b"
    )


def test_cli_managed_l3_7d_structured_json_live_smoke_rejects_conflict_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_7d_structured_json_live_smoke_gemma4_e2b.yaml"
    )
    config_load_called = False
    runner_called = False

    def forbidden_load(*_args, **_kwargs):
        nonlocal config_load_called
        config_load_called = True
        raise AssertionError("L3.7d config load should not run for rejected CLI args")

    class _ForbiddenManagedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal runner_called
            runner_called = True
            raise AssertionError("L3.7d runner should not be constructed for rejected CLI args")

    monkeypatch.setattr(lmstudio_benchmark, "load_raw_experiment_config", forbidden_load)
    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _ForbiddenManagedRunner)

    with pytest.raises(ValueError, match="mutually exclusive"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--managed-l3-7d-structured-json-live-smoke",
                "--managed-l3-6c-compact-memory-live-smoke",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "managed-l3-7d-conflict",
            ]
        )

    assert config_load_called is False
    assert runner_called is False


def test_cli_managed_l3_7d_structured_json_live_smoke_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_7d_structured_json_live_smoke_gemma4_e2b.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_l3_7d_structured_json_live_smoke(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
            timeout_s=120.0,
            native_transport=None,
            chat_transport=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            call_args["timeout_s"] = timeout_s
            call_args["native_transport"] = native_transport
            call_args["chat_transport"] = chat_transport
            return {"decision": "structured_json_live_smoke_pass"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_l3_6d_mode_comparison_live",
        lambda args: (_ for _ in ()).throw(
            AssertionError("L3.6d runner must not be used for L3.7d dispatch")
        ),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_l3_6c_compact_memory_live_smoke",
        lambda args: (_ for _ in ()).throw(
            AssertionError("L3.6c runner must not be used for L3.7d dispatch")
        ),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-l3-7d-structured-json-live-smoke",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-l3-7d-structured-json-live-smoke-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-l3-7d-structured-json-live-smoke-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_l3_7d_structured_json_live_smoke"}
    assert call_args["timeout_s"] == 120.0
    assert call_args["native_transport"] is None
    assert call_args["chat_transport"] is None
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-l3-7d-structured-json-live-smoke-cli_l3_7d_structured_json_live_smoke_gemma4_e2b"
    )


def test_cli_managed_responses_cache_probe_dispatches_without_live_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = (
        project_root
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_5r_responses_cache_probe_gemma4_e2b.yaml"
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(self, transport, *, system_sampler=None) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_responses_cache_probe(
            self,
            *,
            config_path,
            run_dir,
            run_id,
            providers=None,
            timeout_s=120.0,
            responses_transport=None,
        ) -> dict[str, object]:
            call_args["config_path"] = config_path
            call_args["run_dir"] = run_dir
            call_args["run_id"] = run_id
            call_args["providers"] = providers
            call_args["timeout_s"] = timeout_s
            call_args["responses_transport"] = responses_transport
            return {"responses_cache_probe_status": "responses_usable_no_cache"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_live",
        lambda args: (_ for _ in ()).throw(AssertionError("managed live runner must not be used")),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_managed_cache_live_smoke",
        lambda args: (_ for _ in ()).throw(
            AssertionError("cache live smoke runner must not be used")
        ),
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "_run_live_smoke",
        lambda args: (_ for _ in ()).throw(AssertionError("live smoke runner must not be used")),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-responses-cache-probe",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-responses-cache-probe-cli",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert call_args["system_sampler"] is None
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-responses-cache-probe-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_responses_cache_probe"}
    assert call_args["timeout_s"] == 120.0
    assert call_args["responses_transport"] is None
    assert call_args["run_dir"] == (
        tmp_path
        / "results"
        / "run_managed-responses-cache-probe-cli_l3_5r_responses_cache_probe_gemma4_e2b"
    )


def test_cli_managed_live_run_invokes_managed_runner_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
        warmup_runs=0,
        parallel=1,
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(
            self,
            transport,
            *,
            default_timeout_s=None,
            system_sampler=None,
        ) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_medium_chunked_sequential_live(self, **kwargs) -> dict[str, object]:
            call_args.update(kwargs)
            run_dir = Path(kwargs["run_dir"])
            assert not (run_dir / "environment.json").exists()
            assert not (run_dir / "experiment.yaml").exists()
            (run_dir / "metrics.jsonl").write_text("", encoding="utf-8")
            (run_dir / "structured_errors.jsonl").write_text("", encoding="utf-8")
            (run_dir / "system_samples.jsonl").write_text("", encoding="utf-8")
            (run_dir / "environment.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "run_id": "managed-live-cli",
                        "experiment_id": "live_json_smoke",
                        "mode": "managed_runner_medium_chunked_sequential_live",
                        "managed_live": True,
                        "dry_run": False,
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "experiment.yaml").write_text(
                "experiment_id: live_json_smoke\n"
                "lmstudio_base_url: redacted_local_lmstudio_url\n"
                "managed_live: true\n",
                encoding="utf-8",
            )
            (run_dir / "structured_validation_summary.csv").write_text(
                "run_id,status\nmanaged-live-cli,completed\n",
                encoding="utf-8",
            )
            for file_name, payload in {
                "run_config.json": {"managed_live": True},
                "batch_summary.json": {"managed_live": True},
                "structured_validation_summary.json": {"json_parse_pass_count": 4},
                "privacy_scan.json": {"status": "pass"},
                "system_summary.json": {"sample_count": 0},
            }.items():
                (run_dir / file_name).write_text(json.dumps(payload), encoding="utf-8")
            (run_dir / "report.md").write_text(
                "managed live report",
                encoding="utf-8",
            )
            return {"managed_live": True}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-live-cli",
            "--context-fit-safety-ratio",
            "0.9",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-live-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_live_run"}
    assert call_args["app_concurrency"] == 1
    assert call_args["context_fit_safety_ratio"] == 0.9

    run_dir = tmp_path / "results" / "run_managed-live-cli_live_json_smoke"
    assert run_dir.exists()
    assert (run_dir / "environment.json").exists()
    assert (run_dir / "experiment.yaml").exists()
    environment_payload = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    assert environment_payload["managed_live"] is True
    assert environment_payload["dry_run"] is False
    assert "lmstudio_base_url" not in environment_payload
    assert "http://127.0.0.1:1234" not in (run_dir / "experiment.yaml").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("extra_args", "match"),
    [
        pytest.param(["--live"], "mutually exclusive", id="live_conflict"),
        pytest.param(
            ["--verified-context-length", "8192"],
            "--verified-context-length is incompatible with --managed-live",
            id="verified_context_length",
        ),
        pytest.param(
            ["--app-concurrency", "2"],
            "supports only --app-concurrency 1",
            id="app_concurrency",
        ),
        pytest.param(
            ["--allow-queue-pressure"],
            "--allow-queue-pressure is incompatible with --managed-live",
            id="queue_pressure",
        ),
        pytest.param(
            ["--chunked-warmup-policy", "sequential_small_structured"],
            "--chunked-warmup-policy is incompatible with --managed-live",
            id="warmup_policy",
        ),
        pytest.param(
            ["--chunked-warmup-full-batch"],
            "--chunked-warmup-full-batch is incompatible with --managed-live",
            id="warmup_full_batch",
        ),
        pytest.param(
            ["--effective-profile", "productive_first_chunk"],
            "supports only --effective-profile standard",
            id="effective_profile",
        ),
        pytest.param(
            ["--sequential-baseline-wall-time-ms", "16"],
            "--sequential-baseline-wall-time-ms is incompatible with --managed-live",
            id="sequential_baseline",
        ),
        pytest.param(
            ["--baseline-end-to-end-wall-time-ms", "30"],
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-live",
            id="baseline_end_to_end",
        ),
    ],
)
def test_cli_managed_live_rejects_incompatible_args_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
    match: str,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
        warmup_runs=0,
        parallel=1,
    )
    load_called = False
    runner_called = False

    def forbidden_load(*_args, **_kwargs):
        nonlocal load_called
        load_called = True
        raise AssertionError("managed-live config load should not run for rejected CLI args")

    class _ForbiddenManagedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal runner_called
            runner_called = True
            raise AssertionError(
                "managed-live runner should not be constructed for rejected CLI args"
            )

    monkeypatch.setattr(
        lmstudio_benchmark,
        "load_live_smoke_config",
        forbidden_load,
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "ManagedLabRunner",
        _ForbiddenManagedRunner,
    )

    argv = [
        "run",
        str(config_path),
        "--managed-live",
        "--output-root",
        str(tmp_path / "results"),
        "--run-id",
        "managed-live-rejected",
        *extra_args,
    ]

    with pytest.raises(ValueError, match=match):
        lmstudio_benchmark.main(argv)

    assert load_called is False
    assert runner_called is False


def test_cli_managed_live_true_parallel_run_invokes_managed_runner_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
        warmup_runs=1,
        parallel=2,
    )
    call_args: dict[str, object] = {}

    class _FakeManagedRunner:
        def __init__(
            self,
            transport,
            *,
            default_timeout_s=None,
            system_sampler=None,
        ) -> None:
            call_args["transport"] = transport
            call_args["system_sampler"] = system_sampler

        def run_medium_chunked_true_parallel_live(self, **kwargs) -> dict[str, object]:
            call_args.update(kwargs)
            run_dir = Path(kwargs["run_dir"])
            assert not (run_dir / "environment.json").exists()
            assert not (run_dir / "experiment.yaml").exists()
            (run_dir / "metrics.jsonl").write_text("", encoding="utf-8")
            (run_dir / "structured_errors.jsonl").write_text("", encoding="utf-8")
            (run_dir / "system_samples.jsonl").write_text("", encoding="utf-8")
            (run_dir / "environment.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "run_id": "managed-live-tp-cli",
                        "experiment_id": "live_json_smoke",
                        "mode": "managed_runner_medium_chunked_true_parallel_live",
                        "managed_live": True,
                        "dry_run": False,
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "experiment.yaml").write_text(
                "experiment_id: live_json_smoke\n"
                "lmstudio_base_url: redacted_local_lmstudio_url\n"
                "managed_live: true\n",
                encoding="utf-8",
            )
            (run_dir / "structured_validation_summary.csv").write_text(
                "run_id,status\nmanaged-live-tp-cli,completed\n",
                encoding="utf-8",
            )
            for file_name, payload in {
                "run_config.json": {"managed_live": True, "parallel_semantics": "true_parallel"},
                "batch_summary.json": {"managed_live": True, "parallel_semantics": "true_parallel"},
                "structured_validation_summary.json": {"json_parse_pass_count": 4},
                "privacy_scan.json": {"status": "pass"},
                "system_summary.json": {"sample_count": 0},
            }.items():
                (run_dir / file_name).write_text(json.dumps(payload), encoding="utf-8")
            (run_dir / "report.md").write_text(
                "managed true parallel live report",
                encoding="utf-8",
            )
            return {"managed_live": True, "parallel_semantics": "true_parallel"}

    monkeypatch.setattr(lmstudio_benchmark, "ManagedLabRunner", _FakeManagedRunner)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--managed-live-true-parallel",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "managed-live-tp-cli",
            "--context-fit-safety-ratio",
            "0.91",
            "--sequential-baseline-wall-time-ms",
            "88",
            "--baseline-end-to-end-wall-time-ms",
            "99",
        ]
    )

    assert exit_code == 0
    assert callable(call_args["transport"])
    assert isinstance(call_args["system_sampler"], lmstudio_lab.SystemMetricsSampler)
    assert call_args["config_path"] == config_path
    assert call_args["run_id"] == "managed-live-tp-cli"
    assert call_args["providers"] == {"lmstudio_local": "managed_live_true_parallel_run"}
    assert call_args["app_concurrency"] == 2
    assert call_args["context_fit_safety_ratio"] == 0.91
    assert call_args["sequential_baseline_wall_time_ms"] == 88.0
    assert call_args["baseline_end_to_end_wall_time_ms"] == 99.0

    run_dir = tmp_path / "results" / "run_managed-live-tp-cli_live_json_smoke"
    assert run_dir.exists()
    environment_payload = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    assert environment_payload["managed_live"] is True
    assert environment_payload["dry_run"] is False
    assert environment_payload["mode"] == "managed_runner_medium_chunked_true_parallel_live"
    assert "lmstudio_base_url" not in environment_payload
    assert "http://127.0.0.1:1234" not in (run_dir / "experiment.yaml").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("extra_args", "match"),
    [
        pytest.param(["--live"], "mutually exclusive", id="live_conflict"),
        pytest.param(["--managed-live"], "mutually exclusive", id="managed_live_conflict"),
        pytest.param(
            ["--managed-l3-8d-gemma4-e4b-strict-json-smoke"],
            "--managed-l3-8d-gemma4-e4b-strict-json-smoke.*mutually exclusive",
            id="strict_json_smoke_conflict",
        ),
        pytest.param(
            ["--verified-context-length", "8192"],
            "--verified-context-length is incompatible with --managed-live-true-parallel",
            id="verified_context_length",
        ),
        pytest.param(
            ["--app-concurrency", "1"],
            "supports only --app-concurrency 2",
            id="app_concurrency_low",
        ),
        pytest.param(
            ["--app-concurrency", "3"],
            "supports only --app-concurrency 2",
            id="app_concurrency_high",
        ),
        pytest.param(
            ["--allow-queue-pressure"],
            "--allow-queue-pressure is incompatible with --managed-live-true-parallel",
            id="queue_pressure",
        ),
        pytest.param(
            ["--chunked-warmup-policy", "sequential_small_structured"],
            "--chunked-warmup-policy is incompatible with --managed-live-true-parallel",
            id="warmup_policy",
        ),
        pytest.param(
            ["--chunked-warmup-full-batch"],
            "--chunked-warmup-full-batch is incompatible with --managed-live-true-parallel",
            id="warmup_full_batch",
        ),
        pytest.param(
            ["--effective-profile", "productive_first_chunk"],
            "supports only --effective-profile standard",
            id="effective_profile",
        ),
    ],
)
def test_cli_managed_live_true_parallel_rejects_incompatible_args_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
    match: str,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
        warmup_runs=0,
        parallel=2,
    )
    load_called = False
    runner_called = False

    def forbidden_load(*_args, **_kwargs):
        nonlocal load_called
        load_called = True
        raise AssertionError(
            "managed-live-true-parallel config load should not run for rejected CLI args"
        )

    class _ForbiddenManagedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal runner_called
            runner_called = True
            raise AssertionError(
                "managed-live-true-parallel runner should not be constructed for rejected CLI args"
            )

    monkeypatch.setattr(
        lmstudio_benchmark,
        "load_live_smoke_config",
        forbidden_load,
    )
    monkeypatch.setattr(
        lmstudio_benchmark,
        "ManagedLabRunner",
        _ForbiddenManagedRunner,
    )

    argv = [
        "run",
        str(config_path),
        "--managed-live-true-parallel",
        "--output-root",
        str(tmp_path / "results"),
        "--run-id",
        "managed-live-tp-rejected",
        *extra_args,
    ]

    with pytest.raises(ValueError, match=match):
        lmstudio_benchmark.main(argv)

    assert load_called is False
    assert runner_called is False


def test_cli_live_run_writes_safe_live_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = _write_live_config(tmp_path)
    runner_calls: dict[str, object] = {}

    def fake_runner(
        config: lmstudio_lab.LiveSmokeConfig,
        *,
        run_id: str,
        timeout_s: float = 30.0,
        transport=None,
        verified_context_length: int | None = None,
        context_fit_safety_ratio: float = 0.85,
        prompt_variant: str = "baseline",
        reasoning_control_variant: str = "baseline",
    ):
        runner_calls["config"] = config
        runner_calls["run_id"] = run_id
        runner_calls["timeout_s"] = timeout_s
        runner_calls["transport"] = transport
        runner_calls["verified_context_length"] = verified_context_length
        runner_calls["context_fit_safety_ratio"] = context_fit_safety_ratio
        runner_calls["prompt_variant"] = prompt_variant
        runner_calls["reasoning_control_variant"] = reasoning_control_variant
        return lmstudio_lab.LiveSmokeOutcome(
            metric=lmstudio_lab.LMStudioLabMetricRecord.from_parts(
                run_id=run_id,
                experiment_id=config.experiment_id,
                request_id="req_00001",
                dataset_id="blocks_json_small",
                dataset_hash="sha256:blocks-json-small-v1",
                model_key="local_placeholder",
                model_id="placeholder/local-model",
                endpoint_kind="compat_chat",
                mode="json_schema_single",
                requested_context_length=8192,
                requested_parallel=1,
                app_concurrency=1,
                max_tokens=512,
                temperature=0.0,
                prompt_hash="sha256:prompt-live",
                prompt_chars=222,
                response_hash="sha256:response-live",
                response_chars=144,
                response_format=lmstudio_lab.build_factual_blocks_response_format(),
                applied_load_config={"context_length": 8192, "parallel": 1},
                tokens=lmstudio_lab.TokenMetrics(
                    estimated_input_tokens=1200,
                    actual_input_tokens=40,
                    prompt_tokens=40,
                    completion_tokens=20,
                    total_tokens=60,
                    actual_output_tokens=20,
                ),
                validation=lmstudio_lab.ValidationMetrics(
                    json_parse_pass=True,
                    schema_pass=True,
                    business_pass=True,
                    ids_exact_pass=True,
                    no_duplicate_ids=True,
                    order_preserved=True,
                    non_empty_text_pass=True,
                    reasoning_leak=False,
                    finish_reason="stop",
                ),
            ),
            structured_error=None,
        )

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", fake_runner)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "live-cli",
        ]
    )

    assert exit_code == 0
    assert isinstance(runner_calls["config"], lmstudio_lab.LiveSmokeConfig)
    assert runner_calls["run_id"] == "live-cli"
    assert runner_calls["transport"] is None
    assert runner_calls["verified_context_length"] is None
    assert runner_calls["context_fit_safety_ratio"] == 0.85
    assert runner_calls["prompt_variant"] == "baseline"
    assert runner_calls["reasoning_control_variant"] == "baseline"

    run_dir = tmp_path / "results" / "run_live-cli_live_json_smoke"
    assert run_dir.exists()
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == {
        "environment.json",
        "experiment.yaml",
        "metrics.jsonl",
        "report.md",
        "structured_errors.jsonl",
        "summary.csv",
        "system_samples.jsonl",
        "system_summary.json",
    }

    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    environment_payload = json.loads(environment_text)
    _assert_no_private_paths(environment_text, project_root=project_root)
    assert environment_payload["dry_run"] is False
    assert environment_payload["experiment_id"] == "live_json_smoke"
    assert environment_payload["run_id"] == "live-cli"
    assert environment_payload["structured_prompt_variant"] == "baseline"
    assert environment_payload["structured_reasoning_control_variant"] == "baseline"
    assert "lmstudio_base_url" not in environment_payload
    assert "hardware_profile" not in environment_payload
    assert "cwd" not in environment_payload
    assert "env" not in environment_payload

    metrics_text = (run_dir / "metrics.jsonl").read_text(encoding="utf-8")
    _assert_no_private_paths(metrics_text, project_root=project_root)
    assert "Synthetic alpha fact." not in metrics_text
    assert '"messages"' not in metrics_text
    metric_row = json.loads(metrics_text.strip())
    assert metric_row["endpoint_kind"] == "compat_chat"
    assert metric_row["mode"] == "json_schema_single"
    assert metric_row["prompt_hash"] == "sha256:prompt-live"
    assert metric_row["response_hash"] == "sha256:response-live"

    assert (run_dir / "structured_errors.jsonl").read_text(encoding="utf-8") == ""
    assert (run_dir / "experiment.yaml").read_text(encoding="utf-8") == config_path.read_text(
        encoding="utf-8"
    )

    system_samples_text = (run_dir / "system_samples.jsonl").read_text(encoding="utf-8")
    system_summary_text = (run_dir / "system_summary.json").read_text(encoding="utf-8")
    _assert_no_private_paths(system_samples_text, project_root=project_root)
    _assert_no_private_paths(system_summary_text, project_root=project_root)
    assert '"cmdline"' not in system_samples_text
    assert '"username"' not in system_samples_text
    assert '"env"' not in system_samples_text

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    _assert_no_private_paths(report_text, project_root=project_root)
    assert "Mode: live structured smoke" in report_text
    assert "Network: enabled by --live" in report_text
    assert "LM Studio API: called" in report_text
    assert "raw prompts/transcripts/responses/paths: not stored" in report_text
    assert "metrics.jsonl" in report_text
    assert "system_samples.jsonl" in report_text
    assert "system_summary.json" in report_text

    with (run_dir / "summary.csv").open(encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    assert len(summary_rows) == 1
    assert summary_rows[0]["dry_run"] == "False"
    assert summary_rows[0]["model_key"] == "local_placeholder"
    assert summary_rows[0]["planned_requests"] == "1"


def test_cli_live_chunked_run_writes_safe_batch_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
        warmup_runs=1,
        parallel=2,
    )
    runner_calls: dict[str, object] = {}

    def forbidden_single_runner(*_args, **_kwargs):
        raise AssertionError("single live runner should not be used for chunked dataset")

    def fake_chunked_runner(
        config: lmstudio_lab.LiveSmokeConfig,
        *,
        run_id: str,
        timeout_s: float = 30.0,
        transport=None,
        verified_context_length: int | None = None,
        context_fit_safety_ratio: float = 0.85,
        app_concurrency: int = 1,
        warmup_policy: str | None = None,
        warmup_full_batch: bool = False,
        effective_profile: str | None = None,
        sequential_baseline_wall_time_ms: float | None = None,
        baseline_end_to_end_wall_time_ms: float | None = None,
        allow_queue_pressure: bool = False,
    ) -> lmstudio_lab.LiveChunkedSmokeOutcome:
        runner_calls["config"] = config
        runner_calls["run_id"] = run_id
        runner_calls["timeout_s"] = timeout_s
        runner_calls["transport"] = transport
        runner_calls["verified_context_length"] = verified_context_length
        runner_calls["context_fit_safety_ratio"] = context_fit_safety_ratio
        runner_calls["app_concurrency"] = app_concurrency
        runner_calls["warmup_policy"] = warmup_policy
        runner_calls["warmup_full_batch"] = warmup_full_batch
        runner_calls["effective_profile"] = effective_profile
        runner_calls["sequential_baseline_wall_time_ms"] = sequential_baseline_wall_time_ms
        runner_calls["baseline_end_to_end_wall_time_ms"] = baseline_end_to_end_wall_time_ms
        runner_calls["allow_queue_pressure"] = allow_queue_pressure
        metrics = tuple(
            lmstudio_lab.LMStudioLabMetricRecord.from_parts(
                run_id=run_id,
                experiment_id=config.experiment_id,
                request_id=f"batch_0001_chunk_{chunk_id:04d}",
                dataset_id="blocks_json_medium_chunked",
                dataset_hash="sha256:blocks-json-medium-chunked-v1",
                model_key="local_placeholder",
                model_id="placeholder/local-model",
                endpoint_kind="compat_chat",
                mode="json_schema_single",
                requested_context_length=8192,
                requested_parallel=2,
                app_concurrency=2,
                max_tokens=1875,
                temperature=0.0,
                prompt_hash=f"sha256:prompt-chunk-{chunk_id}",
                prompt_chars=300,
                response_hash=f"sha256:response-chunk-{chunk_id}",
                response_chars=200,
                response_format=lmstudio_lab.build_factual_blocks_response_format(),
                applied_load_config={"context_length": 8192, "parallel": 2},
                tokens=lmstudio_lab.TokenMetrics(
                    estimated_input_tokens=1675,
                    actual_input_tokens=300,
                    prompt_tokens=300,
                    completion_tokens=120,
                    total_tokens=420,
                    actual_output_tokens=120,
                ),
                validation=lmstudio_lab.ValidationMetrics(
                    json_parse_pass=True,
                    schema_pass=True,
                    business_pass=True,
                    ids_exact_pass=True,
                    no_duplicate_ids=True,
                    order_preserved=True,
                    non_empty_text_pass=True,
                    reasoning_leak=False,
                    finish_reason="stop",
                ),
            )
            for chunk_id in range(4)
        )
        return lmstudio_lab.LiveChunkedSmokeOutcome(
            metrics=metrics,
            structured_errors=(),
            batch_summary={
                "schema_version": lmstudio_lab.SCHEMA_VERSION,
                "run_id": run_id,
                "experiment_id": config.experiment_id,
                "dataset_id": "blocks_json_medium_chunked",
                "model_key": "local_placeholder",
                "model_id": "placeholder/local-model",
                "endpoint_kind": "compat_chat",
                "mode": "json_schema_single",
                "requested_context_length": 8192,
                "requested_parallel": 2,
                "configured_parallel": 2,
                "applied_parallel": 2,
                "parallel_verified": None,
                "app_concurrency": 2,
                "queue_pressure_mode": False,
                "parallel_semantics": "true_parallel",
                "effective_profile": "standard",
                "chunks_count": 4,
                "chunk_size_blocks": 25,
                "warmup_runs": 1,
                "warmup_is_productive": False,
                "warmup_policy": "concurrent_full_batch",
                "warmup_request_count": 4,
                "measured_batches": 1,
                "measured_request_count": 4,
                "planned_requests": 8,
                "all_chunks_pass": True,
                "batch_business_pass": True,
                "all_ids_covered": True,
                "missing_id_count": 0,
                "duplicate_id_count": 0,
                "failed_chunk_ids": [],
                "json_parse_pass_count": 4,
                "schema_pass_count": 4,
                "business_pass_count": 4,
                "reasoning_leak_count": 0,
                "finish_length_count": 0,
                "total_latency_ms": 40.0,
                "avg_chunk_latency_ms": 10.0,
                "max_chunk_latency_ms": 12.0,
                "warmup_wall_time_ms": 18.0,
                "parallel_batch_wall_time_ms": 24.0,
                "total_batch_wall_time_ms": 24.0,
                "avg_batch_wall_time_ms": 24.0,
                "max_batch_wall_time_ms": 24.0,
                "end_to_end_wall_time_ms": 42.0,
                "avg_end_to_end_wall_time_ms": 42.0,
                "sequential_baseline_wall_time_ms": 48.0,
                "baseline_end_to_end_wall_time_ms": 60.0,
                "speedup_vs_sequential_baseline": 2.0,
                "speedup_excluding_warmup": 2.0,
                "speedup_including_warmup": 60.0 / 42.0,
                "effective_speedup": 60.0 / 42.0,
                "total_prompt_tokens": 1200,
                "total_completion_tokens": 480,
                "total_tokens": 1680,
                "raw_prompt_response_stored": False,
            },
        )

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", forbidden_single_runner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "run_live_chunked_structured_smoke",
        fake_chunked_runner,
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "live-cli-chunked",
            "--verified-context-length",
            "8192",
            "--context-fit-safety-ratio",
            "0.9",
            "--app-concurrency",
            "2",
            "--chunked-warmup-policy",
            "concurrent_full_batch",
            "--chunked-warmup-full-batch",
            "--effective-profile",
            "standard",
            "--sequential-baseline-wall-time-ms",
            "48",
            "--baseline-end-to-end-wall-time-ms",
            "60",
        ]
    )

    assert exit_code == 0
    assert isinstance(runner_calls["config"], lmstudio_lab.LiveSmokeConfig)
    assert runner_calls["run_id"] == "live-cli-chunked"
    assert runner_calls["transport"] is None
    assert runner_calls["verified_context_length"] == 8192
    assert runner_calls["context_fit_safety_ratio"] == 0.9
    assert runner_calls["app_concurrency"] == 2
    assert runner_calls["warmup_policy"] == "concurrent_full_batch"
    assert runner_calls["warmup_full_batch"] is True
    assert runner_calls["effective_profile"] == "standard"
    assert runner_calls["sequential_baseline_wall_time_ms"] == 48.0
    assert runner_calls["baseline_end_to_end_wall_time_ms"] == 60.0
    assert runner_calls["allow_queue_pressure"] is False

    run_dir = tmp_path / "results" / "run_live-cli-chunked_live_json_smoke"
    assert run_dir.exists()
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == {
        "batch_summary.json",
        "environment.json",
        "experiment.yaml",
        "metrics.jsonl",
        "report.md",
        "structured_errors.jsonl",
        "summary.csv",
        "system_samples.jsonl",
        "system_summary.json",
    }

    environment_payload = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    assert environment_payload["structured_reasoning_control_variant"] == "baseline"
    assert environment_payload["structured_prompt_variant"] == "baseline"

    metrics_lines = [
        line
        for line in (run_dir / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(metrics_lines) == 4
    first_metric = json.loads(metrics_lines[0])
    assert first_metric["request_id"] == "batch_0001_chunk_0000"

    batch_summary_text = (run_dir / "batch_summary.json").read_text(encoding="utf-8")
    _assert_no_private_paths(batch_summary_text, project_root=project_root)
    batch_summary = json.loads(batch_summary_text)
    assert batch_summary["planned_requests"] == 8
    assert batch_summary["all_chunks_pass"] is True
    assert batch_summary["configured_parallel"] == 2
    assert batch_summary["applied_parallel"] == 2
    assert batch_summary["parallel_verified"] is None
    assert batch_summary["app_concurrency"] == 2
    assert batch_summary["queue_pressure_mode"] is False
    assert batch_summary["parallel_semantics"] == "true_parallel"
    assert batch_summary["effective_profile"] == "standard"
    assert batch_summary["warmup_policy"] == "concurrent_full_batch"
    assert batch_summary["warmup_request_count"] == 4
    assert batch_summary["warmup_wall_time_ms"] == 18.0
    assert batch_summary["parallel_batch_wall_time_ms"] == 24.0
    assert batch_summary["end_to_end_wall_time_ms"] == 42.0
    assert batch_summary["baseline_end_to_end_wall_time_ms"] == 60.0
    assert batch_summary["speedup_vs_sequential_baseline"] == 2.0
    assert batch_summary["speedup_excluding_warmup"] == 2.0
    assert batch_summary["effective_speedup"] == pytest.approx(60.0 / 42.0)

    system_samples_text = (run_dir / "system_samples.jsonl").read_text(encoding="utf-8")
    system_summary_text = (run_dir / "system_summary.json").read_text(encoding="utf-8")
    _assert_no_private_paths(system_samples_text, project_root=project_root)
    _assert_no_private_paths(system_summary_text, project_root=project_root)
    assert '"cmdline"' not in system_samples_text
    assert '"username"' not in system_samples_text
    assert '"env"' not in system_samples_text

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "Mode: live structured smoke (chunked)" in report_text
    assert "app_concurrency: `2`" in report_text
    assert "effective_profile: `standard`" in report_text
    assert "warmup_policy: `concurrent_full_batch`" in report_text
    assert "warmup_request_count: `4`" in report_text
    assert "warmup_wall_time_ms: `18.0`" in report_text
    assert "parallel_batch_wall_time_ms: `24.0`" in report_text
    assert "end_to_end_wall_time_ms: `42.0`" in report_text
    assert "baseline_end_to_end_wall_time_ms: `60.0`" in report_text
    assert "speedup_vs_sequential_baseline: `2.0`" in report_text
    assert "effective_speedup:" in report_text
    assert "batch_summary.json" in report_text
    assert "system_samples.jsonl" in report_text
    assert "system_summary.json" in report_text
    assert "No native load/unload/download endpoints are called by this run." in report_text

    with (run_dir / "summary.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames is not None
        assert "warmup_policy" in reader.fieldnames
        assert "warmup_request_count" in reader.fieldnames
        assert "effective_profile" in reader.fieldnames
        assert "effective_speedup" in reader.fieldnames
        summary_rows = list(reader)
    assert len(summary_rows) == 1
    assert summary_rows[0]["planned_requests"] == "8"
    assert summary_rows[0]["warmup_policy"] == "concurrent_full_batch"
    assert summary_rows[0]["warmup_request_count"] == "4"
    assert summary_rows[0]["effective_profile"] == "standard"
    assert summary_rows[0]["baseline_end_to_end_wall_time_ms"] == "60.0"


def test_cli_live_chunked_forwards_productive_first_chunk_effective_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
        warmup_runs=0,
        parallel=2,
    )
    runner_calls: dict[str, object] = {}

    def fake_chunked_runner(
        config: lmstudio_lab.LiveSmokeConfig,
        *,
        run_id: str,
        timeout_s: float = 30.0,
        transport=None,
        verified_context_length: int | None = None,
        context_fit_safety_ratio: float = 0.85,
        app_concurrency: int = 1,
        warmup_policy: str | None = None,
        warmup_full_batch: bool = False,
        effective_profile: str | None = None,
        sequential_baseline_wall_time_ms: float | None = None,
        baseline_end_to_end_wall_time_ms: float | None = None,
        allow_queue_pressure: bool = False,
    ) -> lmstudio_lab.LiveChunkedSmokeOutcome:
        runner_calls.update(
            {
                "config": config,
                "run_id": run_id,
                "verified_context_length": verified_context_length,
                "context_fit_safety_ratio": context_fit_safety_ratio,
                "app_concurrency": app_concurrency,
                "warmup_policy": warmup_policy,
                "warmup_full_batch": warmup_full_batch,
                "effective_profile": effective_profile,
                "sequential_baseline_wall_time_ms": sequential_baseline_wall_time_ms,
                "baseline_end_to_end_wall_time_ms": baseline_end_to_end_wall_time_ms,
                "allow_queue_pressure": allow_queue_pressure,
                "transport": transport,
                "timeout_s": timeout_s,
            }
        )
        metric = lmstudio_lab.LMStudioLabMetricRecord.from_parts(run_id=run_id)
        return lmstudio_lab.LiveChunkedSmokeOutcome(
            metrics=(metric,),
            structured_errors=(),
            batch_summary={
                "schema_version": lmstudio_lab.SCHEMA_VERSION,
                "run_id": run_id,
                "experiment_id": config.experiment_id,
                "dataset_id": "blocks_json_medium_chunked",
                "model_key": config.models[0].key,
                "model_id": config.models[0].model_id,
                "endpoint_kind": "compat_chat",
                "mode": config.modes[0],
                "requested_context_length": 8192,
                "requested_parallel": 2,
                "configured_parallel": 2,
                "applied_parallel": 2,
                "parallel_verified": None,
                "app_concurrency": app_concurrency,
                "queue_pressure_mode": False,
                "parallel_semantics": "true_parallel",
                "effective_profile": effective_profile,
                "chunks_count": 4,
                "chunk_size_blocks": 25,
                "warmup_runs": config.warmup_runs,
                "warmup_is_productive": True,
                "warmup_policy": "none",
                "warmup_request_count": 0,
                "measured_batches": 1,
                "measured_request_count": 1,
                "planned_requests": 1,
                "all_chunks_pass": True,
                "batch_business_pass": True,
                "all_ids_covered": True,
                "missing_id_count": 0,
                "duplicate_id_count": 0,
                "failed_chunk_ids": [],
                "structured_error_count": 0,
                "json_parse_pass_count": 1,
                "schema_pass_count": 1,
                "business_pass_count": 1,
                "reasoning_leak_count": 0,
                "finish_length_count": 0,
                "total_latency_ms": 10.0,
                "avg_chunk_latency_ms": 10.0,
                "max_chunk_latency_ms": 10.0,
                "warmup_wall_time_ms": 0.0,
                "parallel_batch_wall_time_ms": 8.0,
                "total_batch_wall_time_ms": 8.0,
                "avg_batch_wall_time_ms": 8.0,
                "max_batch_wall_time_ms": 8.0,
                "end_to_end_wall_time_ms": 12.0,
                "avg_end_to_end_wall_time_ms": 12.0,
                "sequential_baseline_wall_time_ms": sequential_baseline_wall_time_ms,
                "baseline_end_to_end_wall_time_ms": baseline_end_to_end_wall_time_ms,
                "speedup_vs_sequential_baseline": 2.0,
                "speedup_excluding_warmup": 2.0,
                "speedup_including_warmup": 2.5,
                "effective_speedup": 2.5,
                "total_prompt_tokens": 100,
                "total_completion_tokens": 50,
                "total_tokens": 150,
                "raw_prompt_response_stored": False,
            },
        )

    monkeypatch.setattr(
        lmstudio_benchmark,
        "run_live_chunked_structured_smoke",
        fake_chunked_runner,
    )

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "live-cli-productive-profile",
            "--verified-context-length",
            "8192",
            "--app-concurrency",
            "2",
            "--effective-profile",
            "productive_first_chunk",
            "--sequential-baseline-wall-time-ms",
            "16",
            "--baseline-end-to-end-wall-time-ms",
            "30",
        ]
    )

    assert exit_code == 0
    assert isinstance(runner_calls["config"], lmstudio_lab.LiveSmokeConfig)
    assert runner_calls["run_id"] == "live-cli-productive-profile"
    assert runner_calls["verified_context_length"] == 8192
    assert runner_calls["app_concurrency"] == 2
    assert runner_calls["allow_queue_pressure"] is False
    assert runner_calls["effective_profile"] == "productive_first_chunk"
    assert runner_calls["sequential_baseline_wall_time_ms"] == 16.0
    assert runner_calls["baseline_end_to_end_wall_time_ms"] == 30.0


def test_cli_live_chunked_rejects_zero_app_concurrency_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
    )
    transport_called = False

    def forbidden_single_runner(*_args, **_kwargs):
        raise AssertionError("single live runner should not be used for chunked dataset")

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called for invalid CLI chunked concurrency")

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", forbidden_single_runner)
    monkeypatch.setattr(lmstudio_live_smoke, "_default_transport", forbidden_transport)

    with pytest.raises(ValueError, match="app_concurrency must be between"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "live-cli-chunked-zero-concurrency",
                "--verified-context-length",
                "8192",
                "--app-concurrency",
                "0",
            ]
        )

    assert transport_called is False


def test_cli_live_chunked_rejects_queue_pressure_without_opt_in_and_allows_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
    )
    transport_calls = 0

    def forbidden_single_runner(*_args, **_kwargs):
        raise AssertionError("single live runner should not be used for chunked dataset")

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        nonlocal transport_calls
        transport_calls += 1
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        chunk_ids = _payload_chunk_ids(payload)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 200,
                "total_tokens": 1400,
            },
        }

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", forbidden_single_runner)
    monkeypatch.setattr(lmstudio_live_smoke, "_default_transport", fake_transport)

    with pytest.raises(
        ValueError,
        match="app_concurrency exceeds configured load parallel.*queue pressure",
    ):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "live-cli-queue-pressure-blocked",
                "--verified-context-length",
                "8192",
                "--app-concurrency",
                "2",
            ]
        )

    assert transport_calls == 0

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "live-cli-queue-pressure-allowed",
            "--verified-context-length",
            "8192",
            "--app-concurrency",
            "2",
            "--allow-queue-pressure",
        ]
    )

    assert exit_code == 0
    assert transport_calls == 4
    run_dir = tmp_path / "results" / "run_live-cli-queue-pressure-allowed_live_json_smoke"
    batch_summary = json.loads((run_dir / "batch_summary.json").read_text(encoding="utf-8"))
    assert batch_summary["requested_parallel"] == 1
    assert batch_summary["configured_parallel"] == 1
    assert batch_summary["app_concurrency"] == 2
    assert batch_summary["queue_pressure_mode"] is True


def test_cli_live_chunked_rejects_incompatible_warmup_policy_combo_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
        warmup_runs=1,
    )
    transport_called = False

    def forbidden_single_runner(*_args, **_kwargs):
        raise AssertionError("single live runner should not be used for chunked dataset")

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called for invalid CLI warmup policy")

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", forbidden_single_runner)
    monkeypatch.setattr(lmstudio_live_smoke, "_default_transport", forbidden_transport)

    with pytest.raises(ValueError, match="incompatible with warmup_full_batch"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--run-id",
                "live-cli-chunked-warmup-conflict",
                "--verified-context-length",
                "8192",
                "--chunked-warmup-policy",
                "sequential_full_batch",
                "--chunked-warmup-full-batch",
            ]
        )

    assert transport_called is False


def test_cli_live_rejects_structured_fixture_flag_combo(tmp_path: Path) -> None:
    config_path = _write_live_config(tmp_path)

    with pytest.raises(ValueError, match="cannot be combined") as exc_info:
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--validate-structured-fixtures",
                "--output-root",
                str(tmp_path / "results"),
            ]
        )

    assert str(config_path) not in str(exc_info.value)


def test_cli_live_rejects_chunked_only_args_for_non_chunked_dataset(tmp_path: Path) -> None:
    config_path = _write_live_config(tmp_path)

    with pytest.raises(ValueError, match="require the blocks_json_medium_chunked"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--effective-profile",
                "productive_first_chunk",
            ]
        )

    with pytest.raises(ValueError, match="require the blocks_json_medium_chunked"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--app-concurrency",
                "1",
            ]
        )

    with pytest.raises(ValueError, match="require the blocks_json_medium_chunked"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--allow-queue-pressure",
            ]
        )

    with pytest.raises(ValueError, match="require the blocks_json_medium_chunked"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--app-concurrency",
                "2",
                "--chunked-warmup-full-batch",
                "--sequential-baseline-wall-time-ms",
                "48",
            ]
        )

    with pytest.raises(ValueError, match="require the blocks_json_medium_chunked"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--baseline-end-to-end-wall-time-ms",
                "60",
            ]
        )


def test_cli_live_forwards_context_fit_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_live_config(tmp_path)
    runner_calls: dict[str, object] = {}

    def fake_runner(
        config: lmstudio_lab.LiveSmokeConfig,
        *,
        run_id: str,
        timeout_s: float = 30.0,
        transport=None,
        verified_context_length: int | None = None,
        context_fit_safety_ratio: float = 0.85,
        prompt_variant: str = "baseline",
        reasoning_control_variant: str = "baseline",
    ):
        runner_calls["config"] = config
        runner_calls["run_id"] = run_id
        runner_calls["verified_context_length"] = verified_context_length
        runner_calls["context_fit_safety_ratio"] = context_fit_safety_ratio
        runner_calls["prompt_variant"] = prompt_variant
        runner_calls["reasoning_control_variant"] = reasoning_control_variant
        return lmstudio_lab.LiveSmokeOutcome(
            metric=lmstudio_lab.LMStudioLabMetricRecord.from_parts(run_id=run_id),
            structured_error=None,
        )

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", fake_runner)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "live-cli-context-fit",
            "--verified-context-length",
            "32768",
            "--context-fit-safety-ratio",
            "0.9",
        ]
    )

    assert exit_code == 0
    assert isinstance(runner_calls["config"], lmstudio_lab.LiveSmokeConfig)
    assert runner_calls["run_id"] == "live-cli-context-fit"
    assert runner_calls["verified_context_length"] == 32768
    assert runner_calls["context_fit_safety_ratio"] == 0.9
    assert runner_calls["prompt_variant"] == "baseline"
    assert runner_calls["reasoning_control_variant"] == "baseline"


def test_cli_live_forwards_structured_prompt_variant_for_small_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_live_config(tmp_path)
    runner_calls: dict[str, object] = {}

    def fake_runner(
        config: lmstudio_lab.LiveSmokeConfig,
        *,
        run_id: str,
        timeout_s: float = 30.0,
        transport=None,
        verified_context_length: int | None = None,
        context_fit_safety_ratio: float = 0.85,
        prompt_variant: str = "baseline",
        reasoning_control_variant: str = "baseline",
    ):
        runner_calls["config"] = config
        runner_calls["run_id"] = run_id
        runner_calls["prompt_variant"] = prompt_variant
        runner_calls["reasoning_control_variant"] = reasoning_control_variant
        return lmstudio_lab.LiveSmokeOutcome(
            metric=lmstudio_lab.LMStudioLabMetricRecord.from_parts(run_id=run_id),
            structured_error=None,
        )

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", fake_runner)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "live-cli-prompt-variant",
            "--structured-prompt-variant",
            "anti_reasoning",
        ]
    )

    assert exit_code == 0
    assert isinstance(runner_calls["config"], lmstudio_lab.LiveSmokeConfig)
    assert runner_calls["run_id"] == "live-cli-prompt-variant"
    assert runner_calls["prompt_variant"] == "anti_reasoning"
    assert runner_calls["reasoning_control_variant"] == "baseline"
    environment_payload = json.loads(
        (
            tmp_path
            / "results"
            / "run_live-cli-prompt-variant_live_json_smoke"
            / "environment.json"
        ).read_text(encoding="utf-8")
    )
    assert environment_payload["structured_prompt_variant"] == "anti_reasoning"
    assert environment_payload["structured_reasoning_control_variant"] == "baseline"


def test_cli_live_forwards_structured_reasoning_control_for_small_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_live_config(tmp_path)
    runner_calls: dict[str, object] = {}

    def fake_runner(
        config: lmstudio_lab.LiveSmokeConfig,
        *,
        run_id: str,
        timeout_s: float = 30.0,
        transport=None,
        verified_context_length: int | None = None,
        context_fit_safety_ratio: float = 0.85,
        prompt_variant: str = "baseline",
        reasoning_control_variant: str = "baseline",
    ):
        runner_calls["config"] = config
        runner_calls["run_id"] = run_id
        runner_calls["prompt_variant"] = prompt_variant
        runner_calls["reasoning_control_variant"] = reasoning_control_variant
        return lmstudio_lab.LiveSmokeOutcome(
            metric=lmstudio_lab.LMStudioLabMetricRecord.from_parts(run_id=run_id),
            structured_error=None,
        )

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", fake_runner)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--live",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "live-cli-reasoning-control",
            "--structured-reasoning-control",
            "chat_template_kwargs_enable_thinking_false",
        ]
    )

    assert exit_code == 0
    assert isinstance(runner_calls["config"], lmstudio_lab.LiveSmokeConfig)
    assert runner_calls["run_id"] == "live-cli-reasoning-control"
    assert runner_calls["prompt_variant"] == "baseline"
    assert runner_calls["reasoning_control_variant"] == "chat_template_kwargs_enable_thinking_false"
    environment_payload = json.loads(
        (
            tmp_path
            / "results"
            / "run_live-cli-reasoning-control_live_json_smoke"
            / "environment.json"
        ).read_text(encoding="utf-8")
    )
    assert environment_payload["structured_prompt_variant"] == "baseline"
    assert (
        environment_payload["structured_reasoning_control_variant"]
        == "chat_template_kwargs_enable_thinking_false"
    )


def test_cli_live_chunked_rejects_non_baseline_structured_prompt_variant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
    )

    def forbidden_single_runner(*_args, **_kwargs):
        raise AssertionError("single live runner should not be used for chunked dataset")

    def forbidden_chunked_runner(*_args, **_kwargs):
        raise AssertionError("chunked live runner should not be used for rejected prompt variant")

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", forbidden_single_runner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "run_live_chunked_structured_smoke",
        forbidden_chunked_runner,
    )

    with pytest.raises(ValueError, match="supports only baseline"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--structured-prompt-variant",
                "anti_reasoning",
            ]
        )


def test_cli_live_chunked_rejects_non_baseline_structured_reasoning_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_parametrized_live_config(
        tmp_path,
        dataset_id="blocks_json_medium_chunked",
    )

    def forbidden_single_runner(*_args, **_kwargs):
        raise AssertionError("single live runner should not be used for chunked dataset")

    def forbidden_chunked_runner(*_args, **_kwargs):
        raise AssertionError(
            "chunked live runner should not be used for rejected reasoning control"
        )

    monkeypatch.setattr(lmstudio_benchmark, "run_live_structured_smoke", forbidden_single_runner)
    monkeypatch.setattr(
        lmstudio_benchmark,
        "run_live_chunked_structured_smoke",
        forbidden_chunked_runner,
    )

    with pytest.raises(ValueError, match="supports only baseline"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--live",
                "--output-root",
                str(tmp_path / "results"),
                "--structured-reasoning-control",
                "chat_template_kwargs_enable_thinking_false",
            ]
        )


def test_run_live_concurrency_diagnostics_rejects_invalid_kind_before_transport() -> None:
    transport_called = False

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called for invalid diagnostic kind")

    with pytest.raises(
        ValueError,
        match=(
            "diagnostic_kind must be one of plain_text_pair, plain_text_artifacts, "
            "plain_text_artifacts_normalized, structured_small_pair, medium_pair"
        ),
    ):
        lmstudio_lab.run_live_concurrency_diagnostics(
            base_url="http://127.0.0.1:1234",
            model_id="placeholder/local-model",
            model_key="local_placeholder",
            run_id="diag-invalid-kind",
            diagnostic_kind="unsupported_pair",
            transport=forbidden_transport,
        )

    assert transport_called is False


def test_run_live_concurrency_diagnostics_rejects_missing_loaded_parallel_before_transport() -> (
    None
):
    transport_called = False

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called when loaded parallel is missing")

    with pytest.raises(ValueError, match="--loaded-parallel.*queue pressure"):
        lmstudio_lab.run_live_concurrency_diagnostics(
            base_url="http://127.0.0.1:1234",
            model_id="placeholder/local-model",
            model_key="local_placeholder",
            run_id="diag-missing-loaded-parallel",
            diagnostic_kind="plain_text_pair",
            app_concurrency=2,
            transport=forbidden_transport,
        )

    assert transport_called is False


def test_run_live_concurrency_diagnostics_rejects_loaded_parallel_mismatch_before_transport() -> (
    None
):
    transport_called = False

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called for loaded parallel mismatch")

    with pytest.raises(ValueError, match="app_concurrency exceeds loaded parallel"):
        lmstudio_lab.run_live_concurrency_diagnostics(
            base_url="http://127.0.0.1:1234",
            model_id="placeholder/local-model",
            model_key="local_placeholder",
            run_id="diag-loaded-parallel-mismatch",
            diagnostic_kind="plain_text_pair",
            app_concurrency=2,
            loaded_parallel=1,
            transport=forbidden_transport,
        )

    assert transport_called is False


def test_run_live_concurrency_diagnostics_plain_text_pair_uses_compat_only_safe_payloads() -> None:
    barrier = threading.Barrier(2)
    captured_payloads: list[dict[str, object]] = []
    response_text = "Plain-text diagnostic acknowledgement."
    max_in_flight = 0
    in_flight = 0
    lock = threading.Lock()

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        nonlocal in_flight, max_in_flight
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            captured_payloads.append(payload)
        try:
            barrier.wait(timeout=5.0)
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": response_text},
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 6,
                    "total_tokens": 18,
                },
            }
        finally:
            with lock:
                in_flight -= 1

    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-plain-pair",
        diagnostic_kind="plain_text_pair",
        app_concurrency=2,
        loaded_parallel=2,
        transport=fake_transport,
    )

    assert max_in_flight == 2
    assert len(captured_payloads) == 2
    assert lmstudio_live_smoke._PLAIN_TEXT_MAX_TOKENS == 128
    assert all(
        payload["max_tokens"] == lmstudio_live_smoke._PLAIN_TEXT_MAX_TOKENS
        for payload in captured_payloads
    )
    assert all("response_format" not in payload for payload in captured_payloads)
    assert [metric.request_id for metric in outcome.metrics] == [
        "plain_text_0001",
        "plain_text_0002",
    ]
    assert all(metric.content_empty is False for metric in outcome.metrics)
    assert all(metric.reasoning_content_present is False for metric in outcome.metrics)
    assert outcome.structured_errors == ()
    assert outcome.summary["all_requests_pass"] is True
    assert outcome.summary["structured_error_count"] == 0
    assert outcome.summary["business_pass_count"] == 2
    assert outcome.summary["json_parse_pass_count"] == 0
    assert outcome.summary["loaded_parallel"] == 2
    assert outcome.summary["configured_parallel"] is None
    assert outcome.summary["applied_parallel"] == 2
    assert outcome.summary["parallel_verified"] is True
    assert outcome.summary["queue_pressure_mode"] is False
    assert outcome.summary["parallel_semantics"] == "true_parallel"
    assert outcome.summary["raw_prompt_response_stored"] is False
    metric_row = outcome.metrics[0].to_dict()
    assert metric_row["configured_parallel"] is None
    assert metric_row["applied_parallel"] == 2
    assert metric_row["parallel_verified"] is True
    assert metric_row["queue_pressure_mode"] is False
    assert metric_row["parallel_semantics"] == "true_parallel"
    assert metric_row["response_hash"] == lmstudio_live_smoke._sha256_text(response_text)
    assert metric_row["response_chars"] == len(response_text)

    serialized = _metric_strings(
        outcome.summary,
        *(metric.to_dict() for metric in outcome.metrics),
        *outcome.structured_errors,
    )
    assert response_text not in serialized
    assert '"messages"' not in serialized
    assert '"content"' not in serialized


def test_run_live_concurrency_diagnostics_plain_text_artifacts_sends_four_safe_requests() -> None:
    barrier = threading.Barrier(2)
    first_done = threading.Event()
    completion_order: list[int] = []
    payloads: list[dict[str, object]] = []
    lock = threading.Lock()

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        assert payload["temperature"] == 0
        with lock:
            payloads.append(payload)
            payload_index = len(payloads) - 1
        if payload_index < 2:
            barrier.wait(timeout=5.0)
            if payload_index == 0:
                assert first_done.wait(timeout=5.0) is True
            else:
                first_done.set()
        completion_order.append(payload_index)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": f"Synthetic artifact reply {payload_index}."},
                }
            ],
            "usage": {
                "prompt_tokens": 20 + payload_index,
                "completion_tokens": 8,
                "total_tokens": 28 + payload_index,
            },
        }

    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-plain-artifacts",
        diagnostic_kind="plain_text_artifacts",
        app_concurrency=2,
        loaded_parallel=2,
        transport=fake_transport,
    )

    assert completion_order.index(1) < completion_order.index(0)
    assert len(payloads) == 4
    assert lmstudio_live_smoke._PLAIN_TEXT_ARTIFACT_MAX_TOKENS == 512
    assert all(
        payload["max_tokens"] == lmstudio_live_smoke._PLAIN_TEXT_ARTIFACT_MAX_TOKENS
        for payload in payloads
    )
    assert all("response_format" not in payload for payload in payloads)
    assert all(payload["temperature"] == 0 for payload in payloads)
    assert all(
        payload["messages"][0]["content"]
        == "Return the final answer immediately as one short plain-text sentence. "
        "No reasoning, JSON, markdown, or bullets."
        for payload in payloads
    )
    assert [metric.request_id for metric in outcome.metrics] == [
        "plain_text_artifact_summary_short",
        "plain_text_artifact_lecture_notes",
        "plain_text_artifact_mic_command_answer",
        "plain_text_artifact_freeform_rewrite",
    ]
    assert all(metric.validation.business_pass is True for metric in outcome.metrics)
    assert outcome.structured_errors == ()
    assert outcome.summary["request_count"] == 4
    assert outcome.summary["all_requests_pass"] is True
    assert outcome.summary["business_pass_count"] == 4
    assert outcome.summary["structured_error_count"] == 0

    serialized = _metric_strings(
        outcome.summary,
        *(metric.to_dict() for metric in outcome.metrics),
        *outcome.structured_errors,
    )
    assert "Synthetic artifact reply" not in serialized
    assert "queue warmup, pause-resume checks, and export verification" not in serialized
    assert "start recording after a three second countdown" not in serialized
    assert '"messages"' not in serialized
    assert '"content"' not in serialized


def test_run_live_concurrency_diagnostics_plain_text_artifacts_normalized_sends_four_safe_requests() -> (
    None
):
    barrier = threading.Barrier(2)
    first_done = threading.Event()
    completion_order: list[int] = []
    payloads: list[dict[str, object]] = []
    lock = threading.Lock()

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        assert payload["temperature"] == 0
        with lock:
            payloads.append(payload)
            payload_index = len(payloads) - 1
        if payload_index < 2:
            barrier.wait(timeout=5.0)
            if payload_index == 0:
                assert first_done.wait(timeout=5.0) is True
            else:
                first_done.set()
        completion_order.append(payload_index)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": f"Normalized synthetic artifact reply {payload_index}."},
                }
            ],
            "usage": {
                "prompt_tokens": 32 + payload_index,
                "completion_tokens": 40,
                "total_tokens": 72 + payload_index,
            },
        }

    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-plain-artifacts-normalized",
        diagnostic_kind="plain_text_artifacts_normalized",
        app_concurrency=2,
        loaded_parallel=2,
        transport=fake_transport,
    )

    assert completion_order.index(1) < completion_order.index(0)
    assert len(payloads) == 4
    assert lmstudio_live_smoke._PLAIN_TEXT_ARTIFACT_MAX_TOKENS == 512
    assert all(
        payload["max_tokens"] == lmstudio_live_smoke._PLAIN_TEXT_ARTIFACT_MAX_TOKENS
        for payload in payloads
    )
    assert all("response_format" not in payload for payload in payloads)
    assert all(payload["temperature"] == 0 for payload in payloads)
    assert all(
        payload["messages"][0]["content"]
        == "Answer in 120-160 words, plain text only, no JSON, markdown, reasoning, or introduction."
        for payload in payloads
    )
    assert [metric.request_id for metric in outcome.metrics] == [
        "plain_text_artifact_normalized_summary_short",
        "plain_text_artifact_normalized_lecture_notes",
        "plain_text_artifact_normalized_mic_command_answer",
        "plain_text_artifact_normalized_freeform_rewrite",
    ]
    assert all(metric.validation.business_pass is True for metric in outcome.metrics)
    assert outcome.structured_errors == ()
    assert outcome.summary["request_count"] == 4
    assert outcome.summary["all_requests_pass"] is True
    assert outcome.summary["business_pass_count"] == 4
    assert outcome.summary["structured_error_count"] == 0

    serialized = _metric_strings(
        outcome.summary,
        *(metric.to_dict() for metric in outcome.metrics),
        *outcome.structured_errors,
    )
    assert "Normalized synthetic artifact reply" not in serialized
    assert "queue warmup completion" not in serialized
    assert "three second countdown" not in serialized
    assert '"messages"' not in serialized
    assert '"content"' not in serialized


def test_run_live_concurrency_diagnostics_plain_text_override_updates_metrics_and_summary() -> None:
    payloads: list[dict[str, object]] = []

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        payloads.append(payload)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "Normalized synthetic artifact reply."},
                }
            ],
            "usage": {
                "prompt_tokens": 32,
                "completion_tokens": 40,
                "total_tokens": 72,
            },
        }

    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-plain-artifacts-normalized-override",
        diagnostic_kind="plain_text_artifacts_normalized",
        app_concurrency=2,
        loaded_parallel=2,
        transport=fake_transport,
        max_tokens_override=768,
    )

    assert len(payloads) == 4
    assert all(payload["max_tokens"] == 768 for payload in payloads)
    assert all(metric.max_tokens == 768 for metric in outcome.metrics)
    assert outcome.summary["max_tokens"] == 768
    assert outcome.summary["max_tokens_override"] == 768


def test_run_live_concurrency_diagnostics_structured_small_pair_keeps_metric_order() -> None:
    barrier = threading.Barrier(2)
    first_done = threading.Event()
    completion_order: list[int] = []
    payloads: list[dict[str, object]] = []
    lock = threading.Lock()

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        with lock:
            payloads.append(payload)
            payload_index = len(payloads) - 1
        barrier.wait(timeout=5.0)
        if payload_index == 0:
            assert first_done.wait(timeout=5.0) is True
        else:
            first_done.set()
        completion_order.append(payload_index)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json()},
                }
            ],
            "usage": {
                "prompt_tokens": 44 + payload_index,
                "completion_tokens": 22,
                "total_tokens": 66 + payload_index,
            },
        }

    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-structured-small",
        diagnostic_kind="structured_small_pair",
        app_concurrency=2,
        loaded_parallel=2,
        transport=fake_transport,
    )

    assert completion_order == [1, 0]
    assert len(payloads) == 2
    assert all(payload["response_format"]["type"] == "json_schema" for payload in payloads)
    assert [metric.request_id for metric in outcome.metrics] == [
        "structured_small_0001",
        "structured_small_0002",
    ]
    assert all(metric.validation.business_pass is True for metric in outcome.metrics)
    assert outcome.summary["all_requests_pass"] is True
    assert outcome.summary["json_parse_pass_count"] == 2
    assert outcome.summary["schema_pass_count"] == 2
    assert outcome.summary["business_pass_count"] == 2


def test_run_live_concurrency_diagnostics_preserves_missing_reasoning_state_for_no_message_payload() -> (
    None
):
    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-structured-small-no-message",
        diagnostic_kind="structured_small_pair",
        app_concurrency=1,
        loaded_parallel=1,
        transport=lambda *_args: {
            "choices": [{"finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
        },
    )

    assert len(outcome.metrics) == 2
    assert all(metric.error_category == "empty" for metric in outcome.metrics)
    assert all(metric.content_empty is True for metric in outcome.metrics)
    assert all(metric.reasoning_content_present is None for metric in outcome.metrics)
    assert len(outcome.structured_errors) == 2
    assert all(error["error_category"] == "empty" for error in outcome.structured_errors)
    assert all(error["reasoning_content_present"] is None for error in outcome.structured_errors)


def test_run_live_concurrency_diagnostics_medium_pair_uses_first_two_chunks_only() -> None:
    captured_chunk_ids: list[tuple[int, ...]] = []

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        chunk_ids = _payload_chunk_ids(payload)
        captured_chunk_ids.append(chunk_ids)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json(chunk_ids)},
                }
            ],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 180,
                "total_tokens": 1380,
            },
        }

    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-medium-pair",
        diagnostic_kind="medium_pair",
        app_concurrency=2,
        loaded_parallel=2,
        transport=fake_transport,
        verified_context_length=8192,
    )

    assert captured_chunk_ids == [tuple(range(25)), tuple(range(25, 50))]
    assert len(outcome.metrics) == 2
    assert [metric.request_id for metric in outcome.metrics] == [
        "medium_pair_chunk_0000",
        "medium_pair_chunk_0001",
    ]
    assert outcome.summary["request_count"] == 2
    assert outcome.summary["all_requests_pass"] is True


def test_run_live_concurrency_diagnostics_medium_pair_requires_verified_context() -> None:
    transport_called = False

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called without verified context")

    with pytest.raises(ValueError, match="verified_context_length must be a positive integer"):
        lmstudio_lab.run_live_concurrency_diagnostics(
            base_url="http://127.0.0.1:1234",
            model_id="placeholder/local-model",
            model_key="local_placeholder",
            run_id="diag-medium-missing-context",
            diagnostic_kind="medium_pair",
            app_concurrency=1,
            transport=forbidden_transport,
        )

    assert transport_called is False


def test_run_live_concurrency_diagnostics_medium_pair_aborts_on_context_fit_failure() -> None:
    transport_called = False

    def forbidden_transport(*_args, **_kwargs):
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport should not be called when context fit fails")

    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-medium-context-fit-failed",
        diagnostic_kind="medium_pair",
        app_concurrency=1,
        transport=forbidden_transport,
        verified_context_length=1024,
    )

    assert transport_called is False
    assert outcome.metrics == ()
    assert len(outcome.structured_errors) == 1
    assert outcome.structured_errors[0]["error_category"] == "context_fit_failed"
    assert outcome.summary["all_requests_pass"] is False
    assert outcome.summary["structured_error_count"] == 1


def test_run_live_concurrency_diagnostics_structured_small_pair_allows_max_tokens_override() -> (
    None
):
    payloads: list[dict[str, object]] = []

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        payloads.append(payload)
        return {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": _valid_blocks_json()},
                }
            ],
            "usage": {"prompt_tokens": 44, "completion_tokens": 1024, "total_tokens": 1068},
        }

    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-structured-small-max-tokens",
        diagnostic_kind="structured_small_pair",
        app_concurrency=1,
        loaded_parallel=1,
        transport=fake_transport,
        max_tokens_override=1024,
    )

    assert len(payloads) == 2
    assert all(payload["max_tokens"] == 1024 for payload in payloads)
    assert all(metric.max_tokens == 1024 for metric in outcome.metrics)
    assert all(metric.validation.finish_reason == "length" for metric in outcome.metrics)
    assert outcome.summary["max_tokens"] == 1024
    assert outcome.summary["max_tokens_override"] == 1024


def test_run_live_concurrency_diagnostics_medium_pair_uses_override_for_context_fit_and_payload() -> (
    None
):
    payloads: list[dict[str, object]] = []

    def fake_transport(
        _url: str,
        payload: dict[str, object],
        _timeout_s: float,
    ) -> dict[str, object]:
        payloads.append(payload)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json()},
                }
            ],
            "usage": {"prompt_tokens": 64, "completion_tokens": 20, "total_tokens": 84},
        }

    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-medium-pair-max-tokens",
        diagnostic_kind="medium_pair",
        app_concurrency=1,
        loaded_parallel=1,
        verified_context_length=8192,
        transport=fake_transport,
        max_tokens_override=1024,
    )

    assert len(payloads) == 2
    assert all(payload["max_tokens"] == 1024 for payload in payloads)
    assert all(metric.max_tokens == 1024 for metric in outcome.metrics)
    assert outcome.summary["max_tokens"] == 1024
    assert outcome.summary["max_tokens_override"] == 1024


def test_run_live_concurrency_diagnostics_marks_queue_pressure_mode_when_opted_in() -> None:
    barrier = threading.Barrier(2)

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 30.0
        barrier.wait(timeout=5.0)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "Plain-text diagnostic acknowledgement."},
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 6,
                "total_tokens": 18,
            },
        }

    outcome = lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-plain-pair-queue-pressure",
        diagnostic_kind="plain_text_pair",
        app_concurrency=2,
        loaded_parallel=1,
        allow_queue_pressure=True,
        transport=fake_transport,
    )

    assert outcome.summary["loaded_parallel"] == 1
    assert outcome.summary["configured_parallel"] is None
    assert outcome.summary["applied_parallel"] == 1
    assert outcome.summary["parallel_verified"] is None
    assert outcome.summary["queue_pressure_mode"] is True
    assert outcome.summary["parallel_semantics"] == "queue_pressure"
    assert outcome.summary["all_requests_pass"] is True
    metric_row = outcome.metrics[0].to_dict()
    assert metric_row["configured_parallel"] is None
    assert metric_row["applied_parallel"] == 1
    assert metric_row["parallel_verified"] is None
    assert metric_row["queue_pressure_mode"] is True
    assert metric_row["parallel_semantics"] == "queue_pressure"


def test_run_live_concurrency_diagnostics_uses_fresh_mutable_payload_objects() -> None:
    object_ids: list[dict[str, object]] = []
    retained_objects: list[tuple[object, ...]] = []

    def fake_transport(
        _url: str,
        payload: dict[str, object],
        _timeout_s: float,
    ) -> dict[str, object]:
        response_format = payload.get("response_format")
        assert isinstance(response_format, dict)
        json_schema = response_format.get("json_schema")
        assert isinstance(json_schema, dict)
        schema = json_schema.get("schema")
        assert isinstance(schema, dict)
        messages = payload.get("messages")
        assert isinstance(messages, list)
        retained_objects.append(
            (payload, messages, *messages, response_format, json_schema, schema)
        )
        object_ids.append(
            {
                "payload_id": id(payload),
                "messages_id": id(messages),
                "message_ids": tuple(id(message) for message in messages),
                "response_format_id": id(response_format),
                "json_schema_id": id(json_schema),
                "schema_id": id(schema),
            }
        )
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": _valid_blocks_json()},
                }
            ]
        }

    lmstudio_lab.run_live_concurrency_diagnostics(
        base_url="http://127.0.0.1:1234",
        model_id="placeholder/local-model",
        model_key="local_placeholder",
        run_id="diag-immutability",
        diagnostic_kind="structured_small_pair",
        app_concurrency=2,
        loaded_parallel=2,
        transport=fake_transport,
    )

    assert len(object_ids) == 2
    assert len(retained_objects) == 2
    assert object_ids[0]["payload_id"] != object_ids[1]["payload_id"]
    assert object_ids[0]["messages_id"] != object_ids[1]["messages_id"]
    assert set(object_ids[0]["message_ids"]).isdisjoint(set(object_ids[1]["message_ids"]))
    assert object_ids[0]["response_format_id"] != object_ids[1]["response_format_id"]
    assert object_ids[0]["json_schema_id"] != object_ids[1]["json_schema_id"]
    assert object_ids[0]["schema_id"] != object_ids[1]["schema_id"]


def test_cli_probe_concurrency_writes_safe_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    runner_calls: dict[str, object] = {}

    def fake_runner(
        *,
        base_url: str,
        model_id: str,
        model_key: str,
        run_id: str,
        diagnostic_kind: str,
        app_concurrency: int = 2,
        loaded_parallel: int | None = None,
        allow_queue_pressure: bool = False,
        timeout_s: float = 30.0,
        transport=None,
        verified_context_length: int | None = None,
        context_fit_safety_ratio: float = 0.85,
        max_tokens_override: int | None = None,
    ) -> lmstudio_lab.LiveConcurrencyDiagnosticsOutcome:
        runner_calls.update(
            {
                "base_url": base_url,
                "model_id": model_id,
                "model_key": model_key,
                "run_id": run_id,
                "diagnostic_kind": diagnostic_kind,
                "app_concurrency": app_concurrency,
                "loaded_parallel": loaded_parallel,
                "allow_queue_pressure": allow_queue_pressure,
                "timeout_s": timeout_s,
                "transport": transport,
                "verified_context_length": verified_context_length,
                "context_fit_safety_ratio": context_fit_safety_ratio,
                "max_tokens_override": max_tokens_override,
            }
        )
        metric = lmstudio_lab.LMStudioLabMetricRecord.from_parts(
            run_id=run_id,
            experiment_id="concurrency_diagnostics",
            request_id="structured_small_0001",
            dataset_id="blocks_json_small",
            dataset_hash="sha256:blocks-json-small-v1",
            model_key=model_key,
            model_id=model_id,
            endpoint_kind="compat_chat",
            mode=diagnostic_kind,
            app_concurrency=app_concurrency,
            max_tokens=max_tokens_override or 512,
            prompt_hash="sha256:prompt-diag",
            prompt_chars=128,
            response_hash="sha256:response-diag",
            response_chars=96,
            response_format=lmstudio_lab.build_factual_blocks_response_format(),
            tokens=lmstudio_lab.TokenMetrics(
                prompt_tokens=40,
                completion_tokens=20,
                total_tokens=60,
            ),
            timing=lmstudio_lab.TimingMetrics(total_elapsed_ms=15.0),
            validation=lmstudio_lab.ValidationMetrics(
                json_parse_pass=True,
                schema_pass=True,
                business_pass=True,
                non_empty_text_pass=True,
                reasoning_leak=False,
                finish_reason="stop",
            ),
        )
        return lmstudio_lab.LiveConcurrencyDiagnosticsOutcome(
            metrics=(metric,),
            structured_errors=(),
            summary={
                "schema_version": lmstudio_lab.SCHEMA_VERSION,
                "run_id": run_id,
                "diagnostic_kind": diagnostic_kind,
                "model_key": model_key,
                "model_id": model_id,
                "endpoint_kind": "compat_chat",
                "app_concurrency": app_concurrency,
                "configured_parallel": None,
                "applied_parallel": loaded_parallel,
                "parallel_verified": True,
                "parallel_semantics": "true_parallel",
                "loaded_parallel": loaded_parallel,
                "queue_pressure_mode": False,
                "request_count": 2,
                "all_requests_pass": True,
                "json_parse_pass_count": 2,
                "schema_pass_count": 2,
                "business_pass_count": 2,
                "finish_length_count": 0,
                "reasoning_leak_count": 0,
                "structured_error_count": 0,
                "total_prompt_tokens": 80,
                "total_completion_tokens": 40,
                "total_tokens": 120,
                "total_wall_time_ms": 24.0,
                "avg_request_latency_ms": 12.0,
                "max_request_latency_ms": 15.0,
                "raw_prompt_response_stored": False,
                "max_tokens": 768,
                "max_tokens_override": 768,
            },
        )

    monkeypatch.setattr(lmstudio_benchmark, "run_live_concurrency_diagnostics", fake_runner)

    exit_code = lmstudio_benchmark.main(
        [
            "probe-concurrency",
            "--base-url",
            "http://127.0.0.1:1234",
            "--model-id",
            "placeholder/local-model",
            "--kind",
            "plain_text_artifacts",
            "--output-root",
            str(tmp_path / "results"),
            "--run-id",
            "probe-concurrency-cli",
            "--app-concurrency",
            "2",
            "--loaded-parallel",
            "2",
            "--max-tokens",
            "768",
        ]
    )

    assert exit_code == 0
    assert runner_calls == {
        "base_url": "http://127.0.0.1:1234",
        "model_id": "placeholder/local-model",
        "model_key": "placeholder_local-model",
        "run_id": "probe-concurrency-cli",
        "diagnostic_kind": "plain_text_artifacts",
        "app_concurrency": 2,
        "loaded_parallel": 2,
        "allow_queue_pressure": False,
        "timeout_s": 30.0,
        "transport": None,
        "verified_context_length": None,
        "context_fit_safety_ratio": 0.85,
        "max_tokens_override": 768,
    }

    run_dir = tmp_path / "results" / "run_probe-concurrency-cli_concurrency_diagnostics"
    assert run_dir.exists()
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == {
        "environment.json",
        "metrics.jsonl",
        "report.md",
        "structured_errors.jsonl",
        "summary.json",
        "system_samples.jsonl",
        "system_summary.json",
    }

    machine_artifact_names = [
        "environment.json",
        "metrics.jsonl",
        "structured_errors.jsonl",
        "summary.json",
        "system_samples.jsonl",
        "system_summary.json",
    ]
    machine_artifacts_text = "\n".join(
        (run_dir / file_name).read_text(encoding="utf-8") for file_name in machine_artifact_names
    )
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    combined_text = "\n".join((machine_artifacts_text, report_text))
    _assert_no_private_paths(combined_text, project_root=project_root)
    assert "Plain-text diagnostic acknowledgement." not in combined_text
    assert '"messages"' not in combined_text
    assert '"content"' not in combined_text
    assert "/api/v1/models/load" not in machine_artifacts_text
    assert "No native `/api/v1/models/load`, unload, download" in report_text
    summary_payload = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary_payload["loaded_parallel"] == 2
    assert summary_payload["configured_parallel"] is None
    assert summary_payload["applied_parallel"] == 2
    assert summary_payload["parallel_verified"] is True
    assert summary_payload["queue_pressure_mode"] is False
    assert summary_payload["parallel_semantics"] == "true_parallel"
    assert summary_payload["max_tokens"] == 768
    assert summary_payload["max_tokens_override"] == 768
    environment_payload = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    assert environment_payload["loaded_parallel"] == 2
    assert environment_payload["allow_queue_pressure"] is False
    assert environment_payload["max_tokens"] == 768
    assert environment_payload["max_tokens_override"] == 768


@pytest.mark.parametrize(
    ("argv", "match"),
    [
        pytest.param(
            [
                "probe-concurrency",
                "--model-id",
                "placeholder/local-model",
                "--kind",
                "plain_text_pair",
                "--app-concurrency",
                "2",
            ],
            "--loaded-parallel.*queue pressure",
            id="missing_loaded_parallel",
        ),
        pytest.param(
            [
                "probe-concurrency",
                "--model-id",
                "placeholder/local-model",
                "--kind",
                "structured_small_pair",
                "--app-concurrency",
                "0",
            ],
            "--app-concurrency must be between 1 and 2",
            id="app_concurrency_zero",
        ),
        pytest.param(
            [
                "probe-concurrency",
                "--model-id",
                "placeholder/local-model",
                "--kind",
                "medium_pair",
                "--app-concurrency",
                "1",
            ],
            "--verified-context-length is required",
            id="missing_verified_context_length",
        ),
        pytest.param(
            [
                "probe-concurrency",
                "--model-id",
                "placeholder/local-model",
                "--kind",
                "unsupported_pair",
            ],
            "--kind must be one of plain_text_pair, plain_text_artifacts, plain_text_artifacts_normalized, structured_small_pair, medium_pair",
            id="invalid_kind",
        ),
        pytest.param(
            [
                "probe-concurrency",
                "--model-id",
                "placeholder/local-model",
                "--kind",
                "plain_text_pair",
                "--loaded-parallel",
                "1",
                "--max-tokens",
                "0",
            ],
            "--max-tokens must be a positive integer",
            id="non_positive_max_tokens",
        ),
    ],
)
def test_cli_probe_concurrency_rejects_invalid_inputs_before_runner(
    argv: list[str],
    match: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_called = False

    def forbidden_runner(**_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("diagnostics runner should not be called for invalid CLI inputs")

    monkeypatch.setattr(lmstudio_benchmark, "run_live_concurrency_diagnostics", forbidden_runner)

    with pytest.raises(ValueError, match=match):
        lmstudio_benchmark.main(argv)

    assert runner_called is False


def test_cli_probe_concurrency_rejects_non_integer_max_tokens_before_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_called = False

    def forbidden_runner(**_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("diagnostics runner should not be called for invalid CLI inputs")

    monkeypatch.setattr(lmstudio_benchmark, "run_live_concurrency_diagnostics", forbidden_runner)

    with pytest.raises(SystemExit):
        lmstudio_benchmark.main(
            [
                "probe-concurrency",
                "--model-id",
                "placeholder/local-model",
                "--kind",
                "plain_text_pair",
                "--loaded-parallel",
                "1",
                "--max-tokens",
                "invalid",
            ]
        )

    assert runner_called is False
