from __future__ import annotations

import hashlib
import json
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlsplit, urlunsplit

from libs.lmstudio_managed.generation import GenerationResponseEnvelope
from libs.lmstudio_managed.lifecycle import (
    ParallelSemantics,
    classify_parallel_semantics,
)
from libs.lmstudio_managed.metrics import (
    ParallelEvidence,
    batch_metrics_from_request_metrics,
)
from libs.lmstudio_managed.validation import (
    GenerationFailureKind,
    failure_kind_from_lab_category,
)

from .context_fit import ContextFitResult, evaluate_context_fit
from .datasets import default_datasets_root, load_chunked_dataset_view, load_dataset_manifest
from .live_config import (
    STRUCTURED_PROMPT_VARIANT_CHOICES,
    STRUCTURED_SCHEMA_VARIANT_CHOICES,
    LiveLoadScalar,
    LiveSmokeConfig,
    is_local_lmstudio_base_url,
)
from .metrics import (
    SCHEMA_VERSION,
    LMStudioLabMetricRecord,
    TimingMetrics,
    TokenMetrics,
    ValidationMetrics,
)
from .privacy import normalize_metric_key
from .structured import (
    FACTUAL_BLOCKS_SCHEMA_NAME,
    StructuredValidationResult,
    validate_factual_blocks_response,
)

type LiveTransport = Callable[
    [str, Mapping[str, Any], float],
    Mapping[str, Any],
]

_LIVE_SMALL_DATASET_ID = "blocks_json_small"
_LIVE_MEDIUM_DATASET_ID = "blocks_json_medium"
_LIVE_MEDIUM_CHUNKED_DATASET_ID = "blocks_json_medium_chunked"
_LIVE_MEDIUM_CHUNKED_10_DATASET_ID = "blocks_json_medium_chunked_10"
_LIVE_MEDIUM_CHUNKED_5_DATASET_ID = "blocks_json_medium_chunked_5"
STRUCTURED_REASONING_CONTROL_CHOICES = (
    "baseline",
    "chat_template_kwargs_enable_thinking_false",
)
CHUNKED_WARMUP_POLICY_CHOICES = (
    "none",
    "sequential_chunk_0",
    "sequential_small_structured",
    "sequential_full_batch",
    "concurrent_full_batch",
)
EFFECTIVE_PROFILE_CHOICES = (
    "standard",
    "productive_first_chunk",
)
_SUPPORTED_LIVE_DATASET_IDS = frozenset({_LIVE_SMALL_DATASET_ID, _LIVE_MEDIUM_DATASET_ID})
_SUPPORTED_LIVE_CHUNKED_DATASET_IDS = frozenset(
    {
        _LIVE_MEDIUM_CHUNKED_DATASET_ID,
        _LIVE_MEDIUM_CHUNKED_10_DATASET_ID,
        _LIVE_MEDIUM_CHUNKED_5_DATASET_ID,
    }
)
_SUPPORTED_LIVE_CONCURRENCY_DIAGNOSTIC_KINDS = frozenset(
    {
        "plain_text_pair",
        "plain_text_artifacts",
        "plain_text_artifacts_normalized",
        "structured_small_pair",
        "medium_pair",
    }
)
_PLAIN_TEXT_CONCURRENCY_DIAGNOSTIC_KINDS = frozenset(
    {
        "plain_text_pair",
        "plain_text_artifacts",
        "plain_text_artifacts_normalized",
    }
)
_LIVE_ENDPOINT_KIND = "compat_chat"
_LIVE_MODE = "json_schema_single"
_LIVE_REQUEST_ID = "req_00001"
_LIVE_SMALL_MAX_TOKENS = 512
_PLAIN_TEXT_MAX_TOKENS = 128
_PLAIN_TEXT_ARTIFACT_MAX_TOKENS = 512
_PLAIN_TEXT_ARTIFACT_TASK_IDS = (
    "summary_short",
    "lecture_notes",
    "mic_command_answer",
    "freeform_rewrite",
)
_SYNTHETIC_BLOCKS = (
    (101, "Synthetic alpha fact."),
    (102, "Synthetic beta fact."),
)
_REASONING_MARKERS = ("<think", "</think>")
_SMALL_STRUCTURED_PROMPT_VARIANT_CHOICES = ("baseline", "anti_reasoning")
_MEDIUM_STRUCTURED_PROMPT_VARIANT_CHOICES = (
    "baseline",
    "strict_id_contract",
    "ultra_minimal_transform",
)
_BASELINE_SMALL_STRUCTURED_SYSTEM_PROMPT = (
    "Return JSON only. Follow the factual_blocks.v1 schema exactly. "
    "Do not add prose, markdown, or reasoning."
)
_ANTI_REASONING_SMALL_STRUCTURED_SYSTEM_PROMPT = (
    "Return JSON only. Follow the factual_blocks.v1 schema exactly. "
    "Put the final JSON in the public assistant content, not in hidden reasoning. "
    "If you reason internally, keep it hidden and still return only the final JSON in assistant content. "
    "Do not add prose, markdown, or reasoning."
)
_MEDIUM_STRUCTURED_SYSTEM_PROMPT = (
    "Return JSON only. Follow the factual_blocks.v1 schema exactly. "
    "Do not add prose, markdown, or reasoning."
)
_BASELINE_MEDIUM_STRUCTURED_USER_PROMPT = (
    "Normalize the source blocks below. Keep the same block ids, "
    "return each id exactly once in the same order, and use status=success. "
    'For each block, set normalized_text to a concise phrase like "medium block <block_id> validated". '
    "Do not copy the source paragraph into normalized_text."
)
_STRICT_ID_CONTRACT_MEDIUM_STRUCTURED_USER_PROMPT = (
    "Normalize the source blocks below. ID contract is strict: never change, duplicate, omit, merge, split, "
    "or reorder ids. Return one output object for every input block, preserve the exact input id sequence, and "
    "use status=success. If a block text is empty or nearly empty, keep the same id and return an allowed empty "
    "or minimal corrected normalized_text instead of dropping the block. Only normalize the text field."
)
_ULTRA_MINIMAL_TRANSFORM_MEDIUM_STRUCTURED_USER_PROMPT = (
    "Normalize the source blocks below with ultra-minimal transform rules. Do not summarize, merge, split, "
    "reorder, add, or remove blocks. Keep every id exactly once in the original order. Only correct or normalize "
    "the normalized_text field for the matching block. If a block text is empty, keep the id and return an allowed "
    "empty or minimal corrected normalized_text. Use status=success."
)


@dataclass(frozen=True, slots=True)
class LivePromptMetadata:
    prompt_hash: str
    prompt_chars: int
    expected_block_ids: tuple[int, ...]
    prompt_variant: str = "baseline"


@dataclass(frozen=True, slots=True)
class LiveSmokeOutcome:
    metric: LMStudioLabMetricRecord
    structured_error: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class LiveChunkedSmokeOutcome:
    metrics: tuple[LMStudioLabMetricRecord, ...]
    structured_errors: tuple[dict[str, object], ...]
    batch_summary: dict[str, object]


@dataclass(frozen=True, slots=True)
class LiveConcurrencyDiagnosticsOutcome:
    metrics: tuple[LMStudioLabMetricRecord, ...]
    structured_errors: tuple[dict[str, object], ...]
    summary: dict[str, object]


@dataclass(frozen=True, slots=True)
class _ConcurrencyRequestSpec:
    request_id: str
    dataset_id: str
    dataset_hash: str | None
    messages: list[dict[str, str]]
    prompt_meta: LivePromptMetadata
    response_format: dict[str, Any] | None
    max_tokens: int
    estimated_input_tokens: int | None
    requested_context_length: int | None
    validator_kind: str


@dataclass(frozen=True, slots=True)
class _ResponseEnvelopeSummary:
    content_text: str | None
    finish_reason: str | None
    content_empty: bool | None
    reasoning_content_present: bool | None


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _contains_reasoning_markers(text: str) -> bool:
    normalized = text.casefold()
    return any(marker in normalized for marker in _REASONING_MARKERS)


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _sequence_or_none(value: Any) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return None


def _seconds_to_ms(value: Any) -> float | None:
    seconds = _coerce_float(value)
    if seconds is None:
        return None
    return seconds * 1000.0


def _has_non_empty_reasoning_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    nested_mapping = _mapping_or_none(value)
    if nested_mapping is not None:
        return any(_has_non_empty_reasoning_value(item) for item in nested_mapping.values())
    nested_sequence = _sequence_or_none(value)
    if nested_sequence is not None:
        return any(_has_non_empty_reasoning_value(item) for item in nested_sequence)
    return True


def _has_non_empty_reasoning_field(value: Any) -> bool:
    nested_mapping = _mapping_or_none(value)
    if nested_mapping is not None:
        for key, nested in nested_mapping.items():
            if isinstance(key, str) and normalize_metric_key(key).startswith("reasoning"):
                if _has_non_empty_reasoning_value(nested):
                    return True
            if _has_non_empty_reasoning_field(nested):
                return True
        return False

    nested_sequence = _sequence_or_none(value)
    if nested_sequence is not None:
        return any(_has_non_empty_reasoning_field(item) for item in nested_sequence)

    return False


def _elapsed_ms(started_at: float, *, clock: Callable[[], float]) -> float:
    return (clock() - started_at) * 1000.0


def build_factual_blocks_response_format(
    *,
    expected_block_ids: Sequence[int] | None = None,
    schema_variant: str = "baseline",
) -> dict[str, Any]:
    normalized_schema_variant = _validate_structured_schema_variant(schema_variant)

    if normalized_schema_variant == "per_position_id_const":
        if expected_block_ids is None:
            raise ValueError(
                "expected_block_ids must be non-empty when schema_variant is per_position_id_const"
            )
        normalized_expected_ids = tuple(int(block_id) for block_id in expected_block_ids)
        if not normalized_expected_ids:
            raise ValueError(
                "expected_block_ids must be non-empty when schema_variant is per_position_id_const"
            )
        blocks_schema: dict[str, Any] = {
            "type": "array",
            "minItems": len(normalized_expected_ids),
            "maxItems": len(normalized_expected_ids),
            "prefixItems": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["block_id", "normalized_text", "status", "warnings"],
                    "properties": {
                        "block_id": {"type": "integer", "const": block_id},
                        "normalized_text": {"type": "string"},
                        "status": {"type": "string", "const": "success"},
                        "warnings": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                }
                for block_id in normalized_expected_ids
            ],
        }
        schema_name = "factual_blocks_v1_per_position_id_const"
    else:
        blocks_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["block_id", "normalized_text", "status", "warnings"],
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
        }
        schema_name = "factual_blocks_v1"

    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "status", "blocks", "warnings"],
                "properties": {
                    "schema_version": {"type": "string", "const": FACTUAL_BLOCKS_SCHEMA_NAME},
                    "status": {"type": "string", "const": "success"},
                    "warnings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "blocks": blocks_schema,
                },
            },
        },
    }


def _safe_live_dataset_error() -> ValueError:
    return ValueError(
        "live structured smoke supports only blocks_json_small and blocks_json_medium"
    )


def _safe_chunked_live_dataset_error() -> ValueError:
    return ValueError(
        "live chunked structured smoke supports only "
        "blocks_json_medium_chunked, blocks_json_medium_chunked_10, or "
        "blocks_json_medium_chunked_5"
    )


def _validate_live_chunked_dataset_id(dataset_id: str) -> str:
    normalized = str(dataset_id).strip()
    if normalized not in _SUPPORTED_LIVE_CHUNKED_DATASET_IDS:
        raise _safe_chunked_live_dataset_error()
    return normalized


def _build_prompt_metadata(
    messages: list[dict[str, str]],
    *,
    expected_block_ids: tuple[int, ...],
    prompt_variant: str = "baseline",
) -> LivePromptMetadata:
    prompt_source = json.dumps(
        messages,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return LivePromptMetadata(
        prompt_hash=_sha256_text(prompt_source),
        prompt_chars=len(prompt_source),
        expected_block_ids=expected_block_ids,
        prompt_variant=prompt_variant,
    )


def _build_business_failure_retry_message(
    validation_result: StructuredValidationResult,
) -> str:
    reordered_positions = (
        [dict(position) for position in validation_result.reordered_positions]
        if validation_result.reordered_positions is not None
        else None
    )
    lines = [
        "Business validation failed on the previous attempt.",
        "Return a full corrected JSON response for the original input.",
        "Preserve exactly the expected IDs and order.",
        "Do not merge, split, omit, duplicate, or reorder blocks.",
        "Sanitized diagnostics:",
        f"- expected_count: {validation_result.expected_count}",
        f"- returned_count: {validation_result.returned_count}",
    ]
    if validation_result.expected_ids is not None:
        lines.append(
            "- expected_ids: "
            + json.dumps(list(validation_result.expected_ids), separators=(",", ":"))
        )
    if validation_result.returned_ids is not None:
        lines.append(
            "- returned_ids: "
            + json.dumps(list(validation_result.returned_ids), separators=(",", ":"))
        )
    if validation_result.missing_ids is not None:
        lines.append(
            "- missing_ids: "
            + json.dumps(list(validation_result.missing_ids), separators=(",", ":"))
        )
    if validation_result.duplicate_ids is not None:
        lines.append(
            "- duplicate_ids: "
            + json.dumps(list(validation_result.duplicate_ids), separators=(",", ":"))
        )
    if validation_result.extra_ids is not None:
        lines.append(
            "- extra_ids: " + json.dumps(list(validation_result.extra_ids), separators=(",", ":"))
        )
    if validation_result.reordered_count is not None:
        lines.append(f"- reordered_count: {validation_result.reordered_count}")
    if reordered_positions is not None:
        lines.append(
            "- reordered_positions: "
            + json.dumps(reordered_positions, separators=(",", ":"), sort_keys=True)
        )
    if validation_result.reordered_positions_truncated is not None:
        lines.append(
            "- reordered_positions_truncated: "
            + json.dumps(validation_result.reordered_positions_truncated)
        )
    if validation_result.finish_reason is not None:
        lines.append(f"- finish_reason: {validation_result.finish_reason}")
    if validation_result.error_category is not None:
        lines.append(f"- error_category: {validation_result.error_category}")
    return "\n".join(lines)


def _build_business_failure_retry_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    validation_result: StructuredValidationResult,
) -> list[dict[str, str]]:
    retry_messages = [
        {
            "role": str(message.get("role", "")),
            "content": str(message.get("content", "")),
        }
        for message in messages
    ]
    retry_messages.append(
        {
            "role": "user",
            "content": _build_business_failure_retry_message(validation_result),
        }
    )
    return retry_messages


def _should_retry_business_failure(
    validation_result: StructuredValidationResult | None,
    *,
    retry_limit: int,
) -> bool:
    return (
        retry_limit == 1
        and validation_result is not None
        and validation_result.json_parse_pass is True
        and validation_result.schema_pass is True
        and validation_result.business_pass is False
    )


def _validate_structured_prompt_variant(prompt_variant: str) -> str:
    if prompt_variant not in STRUCTURED_PROMPT_VARIANT_CHOICES:
        supported = ", ".join(STRUCTURED_PROMPT_VARIANT_CHOICES)
        raise ValueError(
            f"unsupported structured prompt variant {prompt_variant!r}; expected one of: {supported}"
        )
    return prompt_variant


def _validate_structured_schema_variant(schema_variant: str) -> str:
    if schema_variant not in STRUCTURED_SCHEMA_VARIANT_CHOICES:
        supported = ", ".join(STRUCTURED_SCHEMA_VARIANT_CHOICES)
        raise ValueError(
            f"unsupported structured schema variant {schema_variant!r}; expected one of: {supported}"
        )
    return schema_variant


def _validate_small_structured_prompt_variant(prompt_variant: str) -> str:
    normalized_variant = _validate_structured_prompt_variant(prompt_variant)
    if normalized_variant not in _SMALL_STRUCTURED_PROMPT_VARIANT_CHOICES:
        supported = ", ".join(_SMALL_STRUCTURED_PROMPT_VARIANT_CHOICES)
        raise ValueError(
            f"structured prompt variant {normalized_variant!r} is unsupported for {_LIVE_SMALL_DATASET_ID}; "
            f"expected one of: {supported}"
        )
    return normalized_variant


def _validate_medium_structured_prompt_variant(prompt_variant: str) -> str:
    normalized_variant = _validate_structured_prompt_variant(prompt_variant)
    if normalized_variant == "anti_reasoning":
        raise ValueError(
            f"structured prompt variant {normalized_variant!r} is supported only for "
            f"{_LIVE_SMALL_DATASET_ID} live dataset"
        )
    if normalized_variant not in _MEDIUM_STRUCTURED_PROMPT_VARIANT_CHOICES:
        supported = ", ".join(_MEDIUM_STRUCTURED_PROMPT_VARIANT_CHOICES)
        raise ValueError(
            f"structured prompt variant {normalized_variant!r} is unsupported for "
            f"{_LIVE_MEDIUM_DATASET_ID} live dataset; expected one of: {supported}"
        )
    return normalized_variant


def _validate_structured_reasoning_control_variant(
    reasoning_control_variant: str,
) -> str:
    if reasoning_control_variant not in STRUCTURED_REASONING_CONTROL_CHOICES:
        supported = ", ".join(STRUCTURED_REASONING_CONTROL_CHOICES)
        raise ValueError(
            "unsupported structured reasoning control "
            f"{reasoning_control_variant!r}; expected one of: {supported}"
        )
    return reasoning_control_variant


def _resolve_small_live_structured_system_prompt(prompt_variant: str) -> str:
    normalized_variant = _validate_small_structured_prompt_variant(prompt_variant)
    if normalized_variant == "baseline":
        return _BASELINE_SMALL_STRUCTURED_SYSTEM_PROMPT
    return _ANTI_REASONING_SMALL_STRUCTURED_SYSTEM_PROMPT


def _resolve_medium_live_structured_user_prompt(prompt_variant: str) -> str:
    normalized_variant = _validate_medium_structured_prompt_variant(prompt_variant)
    if normalized_variant == "strict_id_contract":
        return _STRICT_ID_CONTRACT_MEDIUM_STRUCTURED_USER_PROMPT
    if normalized_variant == "ultra_minimal_transform":
        return _ULTRA_MINIMAL_TRANSFORM_MEDIUM_STRUCTURED_USER_PROMPT
    return _BASELINE_MEDIUM_STRUCTURED_USER_PROMPT


def _build_small_live_structured_messages(
    *,
    prompt_variant: str = "baseline",
) -> tuple[list[dict[str, str]], LivePromptMetadata]:
    normalized_variant = _validate_small_structured_prompt_variant(prompt_variant)
    expected_block_ids = tuple(block_id for block_id, _ in _SYNTHETIC_BLOCKS)
    source_lines = "\n".join(
        f"- block_id={block_id}: {text}" for block_id, text in _SYNTHETIC_BLOCKS
    )
    messages = [
        {
            "role": "system",
            "content": _resolve_small_live_structured_system_prompt(normalized_variant),
        },
        {
            "role": "user",
            "content": (
                "Normalize the synthetic source blocks below. Keep the same block ids, "
                "return both ids exactly once in the same order, and use status=success.\n"
                f"{source_lines}"
            ),
        },
    ]
    return messages, _build_prompt_metadata(
        messages,
        expected_block_ids=expected_block_ids,
        prompt_variant=normalized_variant,
    )


def _load_required_json_list(path: Path, *, context: str) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{context} must be a JSON array")
    return payload


@lru_cache(maxsize=1)
def _load_medium_live_blocks() -> tuple[tuple[tuple[int, str], ...], tuple[int, ...]]:
    dataset_dir = default_datasets_root() / _LIVE_MEDIUM_DATASET_ID
    raw_blocks = _load_required_json_list(
        dataset_dir / "input_blocks.json",
        context="blocks_json_medium input_blocks",
    )
    raw_expected_ids = _load_required_json_list(
        dataset_dir / "expected_ids.json",
        context="blocks_json_medium expected_ids",
    )

    blocks: list[tuple[int, str]] = []
    for index, raw_block in enumerate(raw_blocks):
        block = _mapping_or_none(raw_block)
        if block is None:
            raise ValueError(f"blocks_json_medium input_blocks[{index}] must be an object")
        block_id = _coerce_int(block.get("id"))
        if block_id is None:
            raise ValueError(f"blocks_json_medium input_blocks[{index}].id must be an integer")
        text = _coerce_str(block.get("text"))
        if text is None:
            raise ValueError(
                f"blocks_json_medium input_blocks[{index}].text must be a non-empty string"
            )
        blocks.append((block_id, text))

    expected_ids: list[int] = []
    for index, raw_id in enumerate(raw_expected_ids):
        block_id = _coerce_int(raw_id)
        if block_id is None:
            raise ValueError(f"blocks_json_medium expected_ids[{index}] must be an integer")
        expected_ids.append(block_id)

    block_ids = tuple(block_id for block_id, _ in blocks)
    expected_block_ids = tuple(expected_ids)
    if block_ids != expected_block_ids:
        raise ValueError("blocks_json_medium expected_ids must match input_blocks order exactly")

    return tuple(blocks), expected_block_ids


def _build_medium_live_structured_messages(
    *,
    prompt_variant: str = "baseline",
) -> tuple[list[dict[str, str]], LivePromptMetadata]:
    blocks, expected_block_ids = _load_medium_live_blocks()
    source_lines = "\n".join(f"- block_id={block_id}: {text}" for block_id, text in blocks)
    return _build_medium_live_structured_messages_from_lines(
        source_lines,
        expected_block_ids=expected_block_ids,
        prompt_variant=prompt_variant,
    )


def _build_medium_live_structured_messages_from_lines(
    source_lines: str,
    *,
    expected_block_ids: tuple[int, ...],
    prompt_variant: str = "baseline",
) -> tuple[list[dict[str, str]], LivePromptMetadata]:
    normalized_variant = _validate_medium_structured_prompt_variant(prompt_variant)
    messages = [
        {
            "role": "system",
            "content": _MEDIUM_STRUCTURED_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": f"{_resolve_medium_live_structured_user_prompt(normalized_variant)}\n{source_lines}",
        },
    ]
    return messages, _build_prompt_metadata(
        messages,
        expected_block_ids=expected_block_ids,
        prompt_variant=normalized_variant,
    )


def _build_medium_chunk_live_structured_messages(
    expected_block_ids: Sequence[int],
    *,
    prompt_variant: str = "baseline",
) -> tuple[list[dict[str, str]], LivePromptMetadata]:
    blocks, _ = _load_medium_live_blocks()
    blocks_by_id = dict(blocks)
    normalized_expected_ids = tuple(int(block_id) for block_id in expected_block_ids)
    source_lines = "\n".join(
        f"- block_id={block_id}: {blocks_by_id[block_id]}" for block_id in normalized_expected_ids
    )
    return _build_medium_live_structured_messages_from_lines(
        source_lines,
        expected_block_ids=normalized_expected_ids,
        prompt_variant=prompt_variant,
    )


def build_live_structured_messages(
    dataset_id: str = _LIVE_SMALL_DATASET_ID,
    *,
    prompt_variant: str = "baseline",
) -> tuple[list[dict[str, str]], LivePromptMetadata]:
    if dataset_id == _LIVE_SMALL_DATASET_ID:
        return _build_small_live_structured_messages(prompt_variant=prompt_variant)
    if dataset_id == _LIVE_MEDIUM_DATASET_ID:
        return _build_medium_live_structured_messages(prompt_variant=prompt_variant)
    raise _safe_live_dataset_error()


def _normalize_single_load_config(
    config: LiveSmokeConfig,
) -> dict[str, LiveLoadScalar]:
    model = config.models[0]
    normalized: dict[str, LiveLoadScalar] = {}
    for key, value in model.load.items():
        if isinstance(value, tuple):
            if len(value) != 1:
                raise ValueError(f"models[0].load.{key} must contain exactly one value")
            normalized[key] = value[0]
            continue
        normalized[key] = value
    return normalized


def _validate_live_request_shape(config: LiveSmokeConfig) -> dict[str, LiveLoadScalar]:
    if len(config.models) != 1:
        raise ValueError("live structured smoke requires exactly one model")
    if len(config.modes) != 1:
        raise ValueError("live structured smoke requires exactly one mode")
    if len(config.datasets) != 1:
        raise ValueError("live structured smoke requires exactly one dataset")
    if config.datasets[0] not in _SUPPORTED_LIVE_DATASET_IDS:
        raise _safe_live_dataset_error()
    if config.modes[0] != _LIVE_MODE:
        raise ValueError("live structured smoke supports only json_schema_single")
    if config.repeats != 1:
        raise ValueError("live structured smoke requires repeats=1")
    if config.warmup_runs != 0:
        raise ValueError("live structured smoke requires warmup_runs=0")
    return _normalize_single_load_config(config)


def _chat_completions_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        endpoint_path = f"{path}/chat/completions"
    elif path:
        endpoint_path = f"{path}/v1/chat/completions"
    else:
        endpoint_path = "/v1/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, endpoint_path, "", ""))


def _default_transport(
    url: str,
    payload: Mapping[str, Any],
    timeout_s: float,
) -> Mapping[str, Any]:
    request = urllib_request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib_request.urlopen(request, timeout=timeout_s) as response:
        body = response.read().decode("utf-8")
    decoded = json.loads(body)
    if not isinstance(decoded, Mapping):
        raise ValueError("LM Studio response must be a JSON object")
    return decoded


def _extract_response_envelope(
    response_payload: Mapping[str, Any],
) -> _ResponseEnvelopeSummary:
    choices = _sequence_or_none(response_payload.get("choices"))
    if not choices:
        return _ResponseEnvelopeSummary(
            content_text=None,
            finish_reason=None,
            content_empty=True,
            reasoning_content_present=None,
        )
    choice = _mapping_or_none(choices[0])
    if choice is None:
        return _ResponseEnvelopeSummary(
            content_text=None,
            finish_reason=None,
            content_empty=True,
            reasoning_content_present=None,
        )
    finish_reason = _coerce_str(choice.get("finish_reason"))
    message = _mapping_or_none(choice.get("message"))
    if message is None:
        return _ResponseEnvelopeSummary(
            content_text=None,
            finish_reason=finish_reason,
            content_empty=True,
            reasoning_content_present=None,
        )
    reasoning_content_present = _has_non_empty_reasoning_field(message)
    content = message.get("content")
    if not isinstance(content, str):
        return _ResponseEnvelopeSummary(
            content_text=None,
            finish_reason=finish_reason,
            content_empty=True,
            reasoning_content_present=reasoning_content_present,
        )
    return _ResponseEnvelopeSummary(
        content_text=content,
        finish_reason=finish_reason,
        content_empty=not bool(content.strip()),
        reasoning_content_present=reasoning_content_present,
    )


def _live_max_tokens(dataset_id: str) -> int:
    if dataset_id == _LIVE_SMALL_DATASET_ID:
        return _LIVE_SMALL_MAX_TOKENS

    dataset_manifest = load_dataset_manifest(dataset_id)
    return _scaled_live_max_tokens(
        estimated_input_tokens=dataset_manifest.estimated_input_tokens,
        items_count=dataset_manifest.items_count,
    )


def _scaled_live_max_tokens(*, estimated_input_tokens: int, items_count: int) -> int:
    scaled_max_tokens = estimated_input_tokens + items_count * 8
    return min(8192, max(512, scaled_max_tokens))


def _build_tokens(
    *,
    estimated_input_tokens: int,
    response_payload: Mapping[str, Any],
) -> TokenMetrics:
    usage = _mapping_or_none(response_payload.get("usage")) or {}
    prompt_tokens = _coerce_int(usage.get("prompt_tokens"))
    completion_tokens = _coerce_int(usage.get("completion_tokens"))
    total_tokens = _coerce_int(usage.get("total_tokens"))
    return TokenMetrics(
        estimated_input_tokens=estimated_input_tokens,
        estimate_scope="dataset_only",
        actual_input_tokens=prompt_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        total_output_tokens=completion_tokens,
        actual_output_tokens=completion_tokens,
    )


def _managed_generation_envelope_from_lab_response(
    *,
    envelope: _ResponseEnvelopeSummary,
    tokens: TokenMetrics,
    error_kind: GenerationFailureKind | None = None,
) -> GenerationResponseEnvelope:
    content_text = envelope.content_text
    has_content_text = isinstance(content_text, str)
    return GenerationResponseEnvelope(
        content_empty=bool(envelope.content_empty),
        content_chars=len(content_text) if has_content_text else 0,
        content_hash=_sha256_text(content_text) if has_content_text else None,
        reasoning_content_present=bool(envelope.reasoning_content_present),
        finish_reason=envelope.finish_reason,
        input_tokens=(
            tokens.prompt_tokens if tokens.prompt_tokens is not None else tokens.actual_input_tokens
        ),
        output_tokens=(
            tokens.completion_tokens
            if tokens.completion_tokens is not None
            else tokens.actual_output_tokens
        ),
        error_kind=error_kind,
    )


def _build_timing(response_payload: Mapping[str, Any], *, elapsed_ms: float) -> TimingMetrics:
    stats = _mapping_or_none(response_payload.get("stats")) or {}
    return TimingMetrics(
        total_elapsed_ms=elapsed_ms,
        time_to_first_token_ms=_seconds_to_ms(stats.get("time_to_first_token")),
        generation_time_ms=_seconds_to_ms(stats.get("generation_time")),
        tokens_per_second=_coerce_float(stats.get("tokens_per_second")),
    )


def _lab_error_category_from_failure_kind(
    failure_kind: GenerationFailureKind | None,
) -> str | None:
    if failure_kind is None:
        return None
    if failure_kind == GenerationFailureKind.FINISH_LENGTH:
        return "finish"
    if failure_kind == GenerationFailureKind.JSON_DECODE_ERROR:
        return "json"
    if failure_kind == GenerationFailureKind.SCHEMA_ERROR:
        return "schema"
    if failure_kind == GenerationFailureKind.BUSINESS_ERROR:
        return "business"
    if failure_kind in {
        GenerationFailureKind.EMPTY_CONTENT,
        GenerationFailureKind.REASONING_CONTENT_ONLY,
    }:
        return "empty"
    if failure_kind == GenerationFailureKind.TIMEOUT:
        return "timeout"
    if failure_kind == GenerationFailureKind.HTTP_ERROR:
        return "http"
    if failure_kind == GenerationFailureKind.UNKNOWN:
        return "business"
    return None


def _map_validation_error_category(
    error_category: str | None,
    *,
    json_parse_pass: bool,
    finish_reason: str | None,
) -> str | None:
    if error_category == "reasoning_leak":
        return "reasoning"
    if finish_reason == "length":
        return _lab_error_category_from_failure_kind(
            failure_kind_from_lab_category(None, finish_reason=finish_reason)
        )
    if error_category == "finish_length":
        return _lab_error_category_from_failure_kind(failure_kind_from_lab_category("finish"))
    if not json_parse_pass:
        return _lab_error_category_from_failure_kind(failure_kind_from_lab_category("json"))
    if error_category in {"schema", "schema_version"}:
        return _lab_error_category_from_failure_kind(failure_kind_from_lab_category("schema"))
    if error_category is not None:
        return _lab_error_category_from_failure_kind(failure_kind_from_lab_category("business"))
    return None


def _build_error_payload(metric: LMStudioLabMetricRecord) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": metric.run_id,
        "experiment_id": metric.experiment_id,
        "request_id": metric.request_id,
        "dataset_id": metric.dataset_id,
        "model_key": metric.model_key,
        "model_id": metric.model_id,
        "endpoint_kind": metric.endpoint_kind,
        "mode": metric.mode,
        "error_category": metric.error_category,
        "error_status": metric.error_status,
        "finish_reason": metric.validation.finish_reason,
        "json_parse_pass": metric.validation.json_parse_pass,
        "schema_pass": metric.validation.schema_pass,
        "business_pass": metric.validation.business_pass,
        "ids_exact_pass": metric.validation.ids_exact_pass,
        "no_duplicate_ids": metric.validation.no_duplicate_ids,
        "order_preserved": metric.validation.order_preserved,
        "non_empty_text_pass": metric.validation.non_empty_text_pass,
        "reasoning_leak": metric.validation.reasoning_leak,
        "retry_count": metric.validation.retry_count,
        "expected_count": metric.validation.expected_count,
        "returned_count": metric.validation.returned_count,
        "expected_ids": (
            list(metric.validation.expected_ids)
            if metric.validation.expected_ids is not None
            else None
        ),
        "returned_ids": (
            list(metric.validation.returned_ids)
            if metric.validation.returned_ids is not None
            else None
        ),
        "duplicate_ids": (
            list(metric.validation.duplicate_ids)
            if metric.validation.duplicate_ids is not None
            else None
        ),
        "missing_ids": (
            list(metric.validation.missing_ids)
            if metric.validation.missing_ids is not None
            else None
        ),
        "extra_ids": (
            list(metric.validation.extra_ids) if metric.validation.extra_ids is not None else None
        ),
        "reordered_positions": (
            [dict(item) for item in metric.validation.reordered_positions]
            if metric.validation.reordered_positions is not None
            else None
        ),
        "reordered_count": metric.validation.reordered_count,
        "reordered_positions_truncated": metric.validation.reordered_positions_truncated,
        "prompt_hash": metric.prompt_hash,
        "prompt_chars": metric.prompt_chars,
        "response_hash": metric.response_hash,
        "response_chars": metric.response_chars,
        "content_empty": metric.content_empty,
        "reasoning_content_present": metric.reasoning_content_present,
        "configured_parallel": metric.configured_parallel,
        "applied_parallel": metric.applied_parallel,
        "parallel_verified": metric.parallel_verified,
        "queue_pressure_mode": metric.queue_pressure_mode,
        "parallel_semantics": metric.parallel_semantics,
    }


def _build_error_payload_with_extra(
    metric: LMStudioLabMetricRecord,
    *,
    extra_fields: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload = _build_error_payload(metric)
    if extra_fields:
        payload.update(extra_fields)
    return payload


def _preflight_validation_metrics() -> ValidationMetrics:
    return ValidationMetrics(
        json_parse_pass=False,
        schema_pass=False,
        business_pass=False,
        ids_exact_pass=False,
        no_duplicate_ids=False,
        order_preserved=False,
        non_empty_text_pass=False,
        reasoning_leak=False,
    )


def _build_context_fit_extra_fields(
    *,
    estimated_input_tokens: int,
    max_tokens: int,
    context_fit: ContextFitResult | None = None,
) -> dict[str, object]:
    extra_fields: dict[str, object] = {
        "estimated_input_tokens": estimated_input_tokens,
        "max_tokens": max_tokens,
    }
    if context_fit is not None:
        extra_fields.update(context_fit.to_safe_dict())
    return extra_fields


def _build_context_fit_failed_outcome(
    *,
    config: LiveSmokeConfig,
    run_id: str,
    load_config: Mapping[str, LiveLoadScalar],
    prompt_meta: LivePromptMetadata,
    response_format: Mapping[str, Any],
    max_tokens: int,
    estimated_input_tokens: int,
    error_status: str,
    context_fit: ContextFitResult | None = None,
    request_id: str = _LIVE_REQUEST_ID,
    dataset_id: str | None = None,
    dataset_hash: str | None = None,
    app_concurrency: int | None = None,
) -> LiveSmokeOutcome:
    metric = _build_metric(
        config=config,
        run_id=run_id,
        load_config=load_config,
        prompt_meta=prompt_meta,
        response_format=response_format,
        response_hash=None,
        response_chars=0,
        content_empty=None,
        reasoning_content_present=None,
        tokens=TokenMetrics(
            estimated_input_tokens=estimated_input_tokens,
            estimate_scope="dataset_only",
        ),
        timing=TimingMetrics(total_elapsed_ms=0.0),
        validation=_preflight_validation_metrics(),
        error_category="context_fit_failed",
        error_status=error_status,
        max_tokens=max_tokens,
        request_id=request_id,
        dataset_id=dataset_id,
        dataset_hash=dataset_hash,
        estimated_input_tokens=estimated_input_tokens,
        app_concurrency=app_concurrency,
    )
    return LiveSmokeOutcome(
        metric=metric,
        structured_error=_build_error_payload_with_extra(
            metric,
            extra_fields=_build_context_fit_extra_fields(
                estimated_input_tokens=estimated_input_tokens,
                max_tokens=max_tokens,
                context_fit=context_fit,
            ),
        ),
    )


def _classify_transport_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, urllib_error.HTTPError):
        return "http_error", f"http_{error.code}"
    if isinstance(error, json.JSONDecodeError):
        return "json", "failed"
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "timeout", "timeout"
    if isinstance(error, urllib_error.URLError):
        reason = error.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return "timeout", "timeout"
        if isinstance(reason, ConnectionRefusedError):
            return "lmstudio_unavailable", "unavailable"
        return "network", "failed"
    if isinstance(error, ConnectionRefusedError):
        return "lmstudio_unavailable", "unavailable"
    if isinstance(error, OSError):
        return "network", "failed"
    return "unknown", "failed"


def _build_metric(
    *,
    config: LiveSmokeConfig,
    run_id: str,
    load_config: Mapping[str, LiveLoadScalar],
    prompt_meta: LivePromptMetadata,
    response_format: Mapping[str, Any],
    tokens: TokenMetrics,
    timing: TimingMetrics,
    validation: ValidationMetrics,
    error_category: str | None,
    error_status: str,
    max_tokens: int,
    response_hash: str | None,
    response_chars: int,
    content_empty: bool | None,
    reasoning_content_present: bool | None,
    request_id: str = _LIVE_REQUEST_ID,
    dataset_id: str | None = None,
    dataset_hash: str | None = None,
    estimated_input_tokens: int | None = None,
    app_concurrency: int | None = None,
) -> LMStudioLabMetricRecord:
    model = config.models[0]
    requested_parallel = _coerce_int(load_config.get("parallel", load_config.get("n_parallel")))
    resolved_app_concurrency = requested_parallel if app_concurrency is None else app_concurrency
    queue_pressure_mode = (
        requested_parallel is not None
        and resolved_app_concurrency is not None
        and resolved_app_concurrency > requested_parallel
    )
    parallel_fields = _build_parallel_semantics_fields(
        app_concurrency=resolved_app_concurrency,
        configured_parallel=requested_parallel,
        applied_parallel=requested_parallel,
        queue_pressure_mode=queue_pressure_mode,
        explicit_parallel_metadata=False,
    )
    resolved_dataset_id = dataset_id or config.datasets[0]
    resolved_dataset_hash = dataset_hash or load_dataset_manifest(resolved_dataset_id).content_hash
    resolved_estimated_input_tokens = estimated_input_tokens
    if resolved_estimated_input_tokens is None:
        resolved_estimated_input_tokens = load_dataset_manifest(
            resolved_dataset_id
        ).estimated_input_tokens
    return LMStudioLabMetricRecord.from_parts(
        run_id=run_id,
        experiment_id=config.experiment_id,
        request_id=request_id,
        dataset_id=resolved_dataset_id,
        dataset_hash=resolved_dataset_hash,
        model_key=model.key,
        model_id=model.model_id,
        endpoint_kind=_LIVE_ENDPOINT_KIND,
        mode=config.modes[0],
        requested_context_length=_coerce_int(load_config.get("context_length")),
        requested_parallel=requested_parallel,
        app_concurrency=resolved_app_concurrency,
        configured_parallel=parallel_fields["configured_parallel"],
        applied_parallel=parallel_fields["applied_parallel"],
        parallel_verified=parallel_fields["parallel_verified"],
        queue_pressure_mode=parallel_fields["queue_pressure_mode"],
        parallel_semantics=parallel_fields["parallel_semantics"],
        structured_schema_variant=config.structured_schema_variant,
        max_tokens=max_tokens,
        temperature=0.0,
        response_format=response_format,
        applied_load_config=load_config,
        prompt_hash=prompt_meta.prompt_hash,
        prompt_chars=prompt_meta.prompt_chars,
        response_hash=response_hash,
        response_chars=response_chars,
        content_empty=content_empty,
        reasoning_content_present=reasoning_content_present,
        tokens=TokenMetrics(
            estimated_input_tokens=resolved_estimated_input_tokens,
            estimate_scope=tokens.estimate_scope,
            actual_input_tokens=tokens.actual_input_tokens,
            prompt_tokens=tokens.prompt_tokens,
            completion_tokens=tokens.completion_tokens,
            total_tokens=tokens.total_tokens,
            total_output_tokens=tokens.total_output_tokens,
            actual_output_tokens=tokens.actual_output_tokens,
        ),
        timing=timing,
        validation=validation,
        error_category=error_category,
        error_status=error_status,
    )


def _resolve_chunked_warmup_policy(
    *,
    warmup_runs: int,
    warmup_policy: str | None,
    warmup_full_batch: bool,
) -> str:
    if warmup_policy is None:
        if warmup_runs == 0:
            return "none"
        if warmup_full_batch:
            return "concurrent_full_batch"
        return "sequential_chunk_0"

    if warmup_policy not in CHUNKED_WARMUP_POLICY_CHOICES:
        raise ValueError(
            "warmup_policy must be one of: " + ", ".join(CHUNKED_WARMUP_POLICY_CHOICES)
        )
    if warmup_full_batch and warmup_policy != "concurrent_full_batch":
        raise ValueError(
            "warmup_policy is incompatible with warmup_full_batch unless set to concurrent_full_batch"
        )
    return warmup_policy


def _validate_chunked_warmup_runs(*, warmup_runs: int, warmup_policy: str) -> None:
    if warmup_policy == "none":
        if warmup_runs != 0:
            raise ValueError("warmup_policy 'none' requires warmup_runs=0")
        return
    if warmup_runs != 1:
        raise ValueError(f"warmup_policy '{warmup_policy}' requires warmup_runs=1")


def _chunked_warmup_request_count(*, warmup_policy: str, chunks_count: int) -> int:
    if warmup_policy == "none":
        return 0
    if warmup_policy in {"sequential_chunk_0", "sequential_small_structured"}:
        return 1
    return chunks_count


def _resolve_effective_profile(effective_profile: str | None) -> str:
    if effective_profile is None:
        return "standard"
    if effective_profile not in EFFECTIVE_PROFILE_CHOICES:
        raise ValueError(
            "effective_profile must be one of: " + ", ".join(EFFECTIVE_PROFILE_CHOICES)
        )
    return effective_profile


def _calculate_speedup(
    *,
    baseline_wall_time_ms: float | None,
    measured_wall_time_ms: float | None,
) -> float | None:
    if baseline_wall_time_ms is None or measured_wall_time_ms is None or measured_wall_time_ms <= 0:
        return None
    return baseline_wall_time_ms / measured_wall_time_ms


def _classify_parallel_semantics(
    *,
    app_concurrency: int | None,
    known_parallel: int | None,
    queue_pressure_mode: bool | None,
) -> ParallelSemantics | None:
    if app_concurrency is None:
        return None
    return classify_parallel_semantics(
        app_concurrency=app_concurrency,
        applied_parallel=known_parallel,
        queue_pressure_mode=queue_pressure_mode,
    )


def _build_parallel_semantics_fields(
    *,
    app_concurrency: int | None,
    configured_parallel: int | None,
    applied_parallel: int | None,
    queue_pressure_mode: bool | None,
    explicit_parallel_metadata: bool,
) -> dict[str, int | bool | str | None]:
    known_parallel = applied_parallel if applied_parallel is not None else configured_parallel
    parallel_semantics = _classify_parallel_semantics(
        app_concurrency=app_concurrency,
        known_parallel=known_parallel,
        queue_pressure_mode=queue_pressure_mode,
    )
    parallel_verified: bool | None = None
    if explicit_parallel_metadata and applied_parallel is not None:
        if parallel_semantics == ParallelSemantics.OVERBOOKED_STRESS:
            parallel_verified = False
        elif queue_pressure_mode:
            parallel_verified = None
        else:
            parallel_verified = True
    elif parallel_semantics == ParallelSemantics.OVERBOOKED_STRESS:
        parallel_verified = False

    if parallel_semantics is None or parallel_verified is None:
        return {
            "configured_parallel": configured_parallel,
            "applied_parallel": applied_parallel,
            "parallel_verified": parallel_verified,
            "queue_pressure_mode": queue_pressure_mode,
            "parallel_semantics": (
                parallel_semantics.value if parallel_semantics is not None else None
            ),
        }

    evidence = ParallelEvidence(
        configured_parallel=configured_parallel,
        applied_parallel=applied_parallel,
        parallel_verified=parallel_verified,
        app_concurrency=app_concurrency,
        queue_pressure_mode=queue_pressure_mode,
        parallel_semantics=parallel_semantics,
    )
    return {
        "configured_parallel": evidence.configured_parallel,
        "applied_parallel": evidence.applied_parallel,
        "parallel_verified": evidence.parallel_verified,
        "queue_pressure_mode": evidence.queue_pressure_mode,
        "parallel_semantics": evidence.parallel_semantics.value,
    }


def _execute_live_structured_request(
    *,
    config: LiveSmokeConfig,
    run_id: str,
    timeout_s: float,
    transport: LiveTransport,
    endpoint_url: str,
    request_payload: Mapping[str, Any],
    load_config: Mapping[str, LiveLoadScalar],
    request_id: str,
    dataset_id: str,
    dataset_hash: str,
    prompt_meta: LivePromptMetadata,
    response_format: Mapping[str, Any],
    max_tokens: int,
    estimated_input_tokens: int,
    app_concurrency: int,
    business_failure_retry_limit: int = 0,
) -> LiveSmokeOutcome:
    if (
        isinstance(business_failure_retry_limit, bool)
        or not isinstance(business_failure_retry_limit, int)
        or business_failure_retry_limit not in {0, 1}
    ):
        raise ValueError("business_failure_retry_limit must be 0 or 1")

    def _execute_attempt(
        *,
        attempt_request_payload: Mapping[str, Any],
        attempt_prompt_meta: LivePromptMetadata,
        retry_count: int | None,
    ) -> tuple[LiveSmokeOutcome, StructuredValidationResult | None]:
        started_at = time.monotonic()
        try:
            response_payload = transport(endpoint_url, attempt_request_payload, timeout_s)
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            if not isinstance(response_payload, Mapping):
                raise ValueError("LM Studio response must be a mapping")

            envelope = _extract_response_envelope(response_payload)
            lab_reasoning_content_present = envelope.reasoning_content_present
            response_text = envelope.content_text
            tokens = _build_tokens(
                estimated_input_tokens=estimated_input_tokens,
                response_payload=response_payload,
            )
            managed_envelope = _managed_generation_envelope_from_lab_response(
                envelope=envelope,
                tokens=tokens,
            )
            timing = _build_timing(response_payload, elapsed_ms=elapsed_ms)

            if managed_envelope.content_empty is True:
                failure_kind = failure_kind_from_lab_category(
                    "empty",
                    content_empty=managed_envelope.content_empty,
                    reasoning_content_present=lab_reasoning_content_present,
                )
                managed_envelope = replace(managed_envelope, error_kind=failure_kind)
                metric = _build_metric(
                    config=config,
                    run_id=run_id,
                    load_config=load_config,
                    prompt_meta=attempt_prompt_meta,
                    response_format=response_format,
                    response_hash=managed_envelope.content_hash,
                    response_chars=managed_envelope.content_chars,
                    tokens=tokens,
                    timing=timing,
                    max_tokens=max_tokens,
                    validation=ValidationMetrics(
                        json_parse_pass=False,
                        schema_pass=False,
                        business_pass=False,
                        retry_count=retry_count,
                        finish_reason=managed_envelope.finish_reason,
                    ),
                    error_category=_lab_error_category_from_failure_kind(
                        managed_envelope.error_kind
                    ),
                    error_status="failed",
                    request_id=request_id,
                    dataset_id=dataset_id,
                    dataset_hash=dataset_hash,
                    estimated_input_tokens=estimated_input_tokens,
                    app_concurrency=app_concurrency,
                    content_empty=managed_envelope.content_empty,
                    reasoning_content_present=lab_reasoning_content_present,
                )
                return (
                    LiveSmokeOutcome(
                        metric=metric,
                        structured_error=_build_error_payload(metric),
                    ),
                    None,
                )

            validation_result = validate_factual_blocks_response(
                response_text,
                expected_block_ids=attempt_prompt_meta.expected_block_ids,
                finish_reason=managed_envelope.finish_reason,
                retry_count=retry_count,
            )
            error_category = _map_validation_error_category(
                validation_result.error_category,
                json_parse_pass=validation_result.json_parse_pass,
                finish_reason=validation_result.finish_reason,
            )
            managed_envelope = replace(
                managed_envelope,
                error_kind=(
                    None
                    if error_category == "reasoning"
                    else failure_kind_from_lab_category(
                        error_category,
                        content_empty=managed_envelope.content_empty,
                        reasoning_content_present=lab_reasoning_content_present,
                        finish_reason=managed_envelope.finish_reason,
                    )
                ),
            )
            metric = _build_metric(
                config=config,
                run_id=run_id,
                load_config=load_config,
                prompt_meta=attempt_prompt_meta,
                response_format=response_format,
                response_hash=managed_envelope.content_hash,
                response_chars=managed_envelope.content_chars,
                tokens=tokens,
                timing=timing,
                validation=validation_result.to_metrics(),
                error_category=error_category,
                error_status="ok" if error_category is None else "failed",
                max_tokens=max_tokens,
                request_id=request_id,
                dataset_id=dataset_id,
                dataset_hash=dataset_hash,
                estimated_input_tokens=estimated_input_tokens,
                app_concurrency=app_concurrency,
                content_empty=managed_envelope.content_empty,
                reasoning_content_present=lab_reasoning_content_present,
            )
            return (
                LiveSmokeOutcome(
                    metric=metric,
                    structured_error=None
                    if error_category is None
                    else _build_error_payload(metric),
                ),
                validation_result,
            )
        except Exception as error:
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            error_category, error_status = _classify_transport_error(error)
            metric = _build_metric(
                config=config,
                run_id=run_id,
                load_config=load_config,
                prompt_meta=attempt_prompt_meta,
                response_format=response_format,
                response_hash=None,
                response_chars=0,
                tokens=TokenMetrics(
                    estimated_input_tokens=estimated_input_tokens,
                    estimate_scope="dataset_only",
                ),
                timing=TimingMetrics(total_elapsed_ms=elapsed_ms),
                validation=ValidationMetrics(retry_count=retry_count),
                error_category=error_category,
                error_status=error_status,
                max_tokens=max_tokens,
                request_id=request_id,
                dataset_id=dataset_id,
                dataset_hash=dataset_hash,
                estimated_input_tokens=estimated_input_tokens,
                app_concurrency=app_concurrency,
                content_empty=None,
                reasoning_content_present=None,
            )
            return (
                LiveSmokeOutcome(
                    metric=metric,
                    structured_error=_build_error_payload(metric),
                ),
                None,
            )

    first_outcome, first_validation_result = _execute_attempt(
        attempt_request_payload=request_payload,
        attempt_prompt_meta=prompt_meta,
        retry_count=None,
    )
    if not _should_retry_business_failure(
        first_validation_result,
        retry_limit=business_failure_retry_limit,
    ):
        return first_outcome

    retry_messages = _build_business_failure_retry_messages(
        request_payload.get("messages", ()),
        validation_result=first_validation_result,
    )
    retry_prompt_meta = _build_prompt_metadata(
        retry_messages,
        expected_block_ids=prompt_meta.expected_block_ids,
        prompt_variant=prompt_meta.prompt_variant,
    )
    retry_request_payload = dict(request_payload)
    retry_request_payload["messages"] = retry_messages
    retry_outcome, _retry_validation_result = _execute_attempt(
        attempt_request_payload=retry_request_payload,
        attempt_prompt_meta=retry_prompt_meta,
        retry_count=1,
    )
    return retry_outcome


def _count_true(values: Sequence[bool | None]) -> int:
    return sum(value is True for value in values)


def _sum_optional_int(values: Sequence[int | None]) -> int | None:
    present_values = [value for value in values if isinstance(value, int)]
    if not present_values:
        return None
    return sum(present_values)


def _build_managed_batch_metrics(
    metrics: Sequence[LMStudioLabMetricRecord],
    *,
    total_wall_time_ms: float | None = None,
):
    request_metrics = tuple(metric.to_managed_request_metrics() for metric in metrics)
    return batch_metrics_from_request_metrics(
        request_metrics,
        total_wall_time_ms=total_wall_time_ms,
    )


def _build_chunked_batch_summary(
    *,
    config: LiveSmokeConfig,
    run_id: str,
    load_config: Mapping[str, LiveLoadScalar],
    dataset_hash: str,
    chunks_count: int,
    chunk_size_blocks: int,
    app_concurrency: int,
    effective_profile: str,
    warmup_is_productive: bool,
    warmup_policy: str,
    warmup_request_count: int,
    metrics: Sequence[LMStudioLabMetricRecord],
    structured_errors: Sequence[Mapping[str, object]],
    failed_chunk_ids: Sequence[int],
    warmup_wall_time_ms: float | None,
    batch_wall_times_ms: Sequence[float],
    sequential_baseline_wall_time_ms: float | None,
    end_to_end_batch_wall_times_ms: Sequence[float],
    baseline_end_to_end_wall_time_ms: float | None,
) -> dict[str, object]:
    model = config.models[0]
    configured_parallel = _coerce_int(load_config.get("parallel", load_config.get("n_parallel")))
    queue_pressure_mode = configured_parallel is not None and app_concurrency > configured_parallel
    parallel_fields = _build_parallel_semantics_fields(
        app_concurrency=app_concurrency,
        configured_parallel=configured_parallel,
        applied_parallel=configured_parallel,
        queue_pressure_mode=queue_pressure_mode,
        explicit_parallel_metadata=False,
    )
    metric_list = list(metrics)
    validation_list = [metric.validation for metric in metric_list]
    token_list = [metric.tokens for metric in metric_list]
    timing_list = [metric.timing for metric in metric_list]
    expected_measured_request_count = config.repeats * chunks_count
    all_ids_covered = len(metric_list) == expected_measured_request_count and all(
        validation.ids_exact_pass is True for validation in validation_list
    )
    no_duplicate_ids = (
        all(validation.no_duplicate_ids is True for validation in validation_list)
        and len(metric_list) == expected_measured_request_count
    )
    all_chunks_pass = (
        len(metric_list) == expected_measured_request_count
        and all(metric.error_category is None for metric in metric_list)
        and all(validation.business_pass is True for validation in validation_list)
    )
    retry_attempt_count = sum(validation.retry_count == 1 for validation in validation_list)
    retry_recovered_count = sum(
        validation.retry_count == 1 and validation.business_pass is True
        for validation in validation_list
    )
    retry_failed_count = sum(
        validation.retry_count == 1 and validation.business_pass is False
        for validation in validation_list
    )
    total_latency_ms = sum(
        timing.total_elapsed_ms or 0.0
        for timing in timing_list
        if timing.total_elapsed_ms is not None
    )
    batch_wall_time_values = [float(value) for value in batch_wall_times_ms]
    end_to_end_wall_time_values = [float(value) for value in end_to_end_batch_wall_times_ms]
    total_batch_wall_time_ms = sum(batch_wall_time_values) if batch_wall_time_values else None
    avg_batch_wall_time_ms = (
        total_batch_wall_time_ms / len(batch_wall_time_values)
        if total_batch_wall_time_ms is not None and batch_wall_time_values
        else None
    )
    max_batch_wall_time_ms = max(batch_wall_time_values, default=None)
    total_end_to_end_wall_time_ms = (
        sum(end_to_end_wall_time_values) if end_to_end_wall_time_values else None
    )
    avg_end_to_end_wall_time_ms = (
        total_end_to_end_wall_time_ms / len(end_to_end_wall_time_values)
        if total_end_to_end_wall_time_ms is not None and end_to_end_wall_time_values
        else None
    )
    managed_batch_metrics = _build_managed_batch_metrics(
        metric_list,
        total_wall_time_ms=total_batch_wall_time_ms,
    )
    measured_request_count = managed_batch_metrics.request_count
    prompt_tokens = _sum_optional_int([tokens.prompt_tokens for tokens in token_list])
    completion_tokens = managed_batch_metrics.total_completion_tokens
    total_tokens = _sum_optional_int([tokens.total_tokens for tokens in token_list])
    resolved_warmup_wall_time_ms = (
        float(warmup_wall_time_ms) if warmup_wall_time_ms is not None else None
    )
    resolved_baseline_end_to_end_wall_time_ms = (
        baseline_end_to_end_wall_time_ms
        if baseline_end_to_end_wall_time_ms is not None
        else sequential_baseline_wall_time_ms
    )
    speedup_excluding_warmup = _calculate_speedup(
        baseline_wall_time_ms=sequential_baseline_wall_time_ms,
        measured_wall_time_ms=avg_batch_wall_time_ms,
    )
    speedup_including_warmup = _calculate_speedup(
        baseline_wall_time_ms=resolved_baseline_end_to_end_wall_time_ms,
        measured_wall_time_ms=avg_end_to_end_wall_time_ms,
    )
    summary: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "dataset_id": config.datasets[0],
        "dataset_hash": dataset_hash,
        "structured_prompt_variant": config.structured_prompt_variant,
        "structured_schema_variant": config.structured_schema_variant,
        "business_failure_retry_limit": config.business_failure_retry_limit,
        "model_key": model.key,
        "model_id": model.model_id,
        "endpoint_kind": _LIVE_ENDPOINT_KIND,
        "mode": config.modes[0],
        "requested_context_length": _coerce_int(load_config.get("context_length")),
        "requested_parallel": configured_parallel,
        "configured_parallel": parallel_fields["configured_parallel"],
        "applied_parallel": parallel_fields["applied_parallel"],
        "parallel_verified": parallel_fields["parallel_verified"],
        "app_concurrency": app_concurrency,
        "queue_pressure_mode": parallel_fields["queue_pressure_mode"],
        "parallel_semantics": parallel_fields["parallel_semantics"],
        "effective_profile": effective_profile,
        "chunks_count": chunks_count,
        "chunk_size_blocks": chunk_size_blocks,
        "warmup_runs": config.warmup_runs,
        "warmup_is_productive": warmup_is_productive,
        "warmup_policy": warmup_policy,
        "warmup_request_count": warmup_request_count,
        "measured_batches": config.repeats,
        "measured_request_count": measured_request_count,
        "planned_requests": warmup_request_count + expected_measured_request_count,
        "all_chunks_pass": all_chunks_pass,
        "batch_business_pass": all_chunks_pass,
        "all_ids_covered": all_ids_covered,
        "missing_id_count": 0 if all_ids_covered else None,
        "duplicate_id_count": 0 if no_duplicate_ids else None,
        "failed_chunk_ids": sorted(set(failed_chunk_ids)),
        "structured_error_count": len(structured_errors),
        "json_parse_pass_count": _count_true(
            [validation.json_parse_pass for validation in validation_list]
        ),
        "schema_pass_count": _count_true(
            [validation.schema_pass for validation in validation_list]
        ),
        "business_pass_count": managed_batch_metrics.business_pass_count,
        "retry_attempt_count": retry_attempt_count,
        "retry_recovered_count": retry_recovered_count,
        "retry_failed_count": retry_failed_count,
        "reasoning_leak_count": _count_true(
            [validation.reasoning_leak for validation in validation_list]
        ),
        "finish_length_count": managed_batch_metrics.finish_length_count,
        "total_latency_ms": total_latency_ms,
        "avg_chunk_latency_ms": (
            total_latency_ms / measured_request_count if measured_request_count else None
        ),
        "max_chunk_latency_ms": max(
            (
                timing.total_elapsed_ms
                for timing in timing_list
                if timing.total_elapsed_ms is not None
            ),
            default=None,
        ),
        "total_batch_wall_time_ms": total_batch_wall_time_ms,
        "parallel_batch_wall_time_ms": total_batch_wall_time_ms,
        "avg_batch_wall_time_ms": avg_batch_wall_time_ms,
        "max_batch_wall_time_ms": max_batch_wall_time_ms,
        "warmup_wall_time_ms": resolved_warmup_wall_time_ms,
        "end_to_end_wall_time_ms": total_end_to_end_wall_time_ms,
        "avg_end_to_end_wall_time_ms": avg_end_to_end_wall_time_ms,
        "sequential_baseline_wall_time_ms": sequential_baseline_wall_time_ms,
        "baseline_end_to_end_wall_time_ms": resolved_baseline_end_to_end_wall_time_ms,
        "speedup_vs_sequential_baseline": speedup_excluding_warmup,
        "speedup_excluding_warmup": speedup_excluding_warmup,
        "speedup_including_warmup": speedup_including_warmup,
        "effective_speedup": speedup_including_warmup,
        "total_prompt_tokens": prompt_tokens,
        "total_completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "raw_prompt_response_stored": False,
    }
    if structured_errors and not metric_list:
        first_error = structured_errors[0]
        summary["error_category"] = first_error.get("error_category")
        summary["error_status"] = first_error.get("error_status")
    return summary


def run_live_chunked_structured_smoke(
    config: LiveSmokeConfig,
    *,
    run_id: str,
    timeout_s: float = 30.0,
    transport: LiveTransport | None = None,
    verified_context_length: int | None = None,
    context_fit_safety_ratio: float = 0.85,
    app_concurrency: int = 1,
    warmup_policy: str | None = None,
    warmup_full_batch: bool = False,
    effective_profile: str | None = None,
    sequential_baseline_wall_time_ms: float | None = None,
    baseline_end_to_end_wall_time_ms: float | None = None,
    allow_queue_pressure: bool = False,
    _clock: Callable[[], float] | None = None,
) -> LiveChunkedSmokeOutcome:
    if len(config.models) != 1:
        raise ValueError("live chunked structured smoke requires exactly one model")
    if len(config.modes) != 1:
        raise ValueError("live chunked structured smoke requires exactly one mode")
    if len(config.datasets) != 1:
        raise ValueError("live chunked structured smoke requires exactly one dataset")
    dataset_id = _validate_live_chunked_dataset_id(config.datasets[0])
    if config.modes[0] != _LIVE_MODE:
        raise ValueError("live chunked structured smoke supports only json_schema_single")
    if config.repeats < 1:
        raise ValueError("live chunked structured smoke requires repeats>=1")
    if config.warmup_runs not in {0, 1}:
        raise ValueError("live chunked structured smoke supports only warmup_runs 0 or 1")
    structured_prompt_variant = _validate_medium_structured_prompt_variant(
        config.structured_prompt_variant
    )
    structured_schema_variant = _validate_structured_schema_variant(
        config.structured_schema_variant
    )
    resolved_effective_profile = _resolve_effective_profile(effective_profile)
    if resolved_effective_profile == "productive_first_chunk" and config.warmup_runs != 0:
        raise ValueError("effective_profile 'productive_first_chunk' requires warmup_runs=0")
    effective_warmup_policy = _resolve_chunked_warmup_policy(
        warmup_runs=config.warmup_runs,
        warmup_policy=warmup_policy,
        warmup_full_batch=warmup_full_batch,
    )
    _validate_chunked_warmup_runs(
        warmup_runs=config.warmup_runs,
        warmup_policy=effective_warmup_policy,
    )
    load_config = _normalize_single_load_config(config)

    chunked_view = load_chunked_dataset_view(dataset_id)
    if isinstance(app_concurrency, bool) or not isinstance(app_concurrency, int):
        raise ValueError("app_concurrency must be an integer between 1 and chunks_count")
    if app_concurrency < 1 or app_concurrency > chunked_view.chunks_count:
        raise ValueError("app_concurrency must be between 1 and chunks_count")
    configured_parallel = _coerce_int(load_config.get("parallel", load_config.get("n_parallel")))
    if (
        configured_parallel is not None
        and app_concurrency > configured_parallel
        and not allow_queue_pressure
    ):
        raise ValueError(
            "app_concurrency exceeds configured load parallel; "
            "this would create queue pressure instead of true parallel"
        )
    if sequential_baseline_wall_time_ms is not None and (
        isinstance(sequential_baseline_wall_time_ms, bool)
        or not isinstance(sequential_baseline_wall_time_ms, (int, float))
        or sequential_baseline_wall_time_ms <= 0
    ):
        raise ValueError("sequential_baseline_wall_time_ms must be positive")
    if baseline_end_to_end_wall_time_ms is not None and (
        isinstance(baseline_end_to_end_wall_time_ms, bool)
        or not isinstance(baseline_end_to_end_wall_time_ms, (int, float))
        or baseline_end_to_end_wall_time_ms <= 0
    ):
        raise ValueError("baseline_end_to_end_wall_time_ms must be positive")
    dataset_manifest = load_dataset_manifest(dataset_id)
    request_transport = transport or _default_transport
    clock = _clock or time.monotonic
    endpoint_url = _chat_completions_url(config.lmstudio_base_url)
    warmup_request_count = _chunked_warmup_request_count(
        warmup_policy=effective_warmup_policy,
        chunks_count=chunked_view.chunks_count,
    )

    if verified_context_length is None:
        first_chunk = chunked_view.chunks[0]
        first_messages, first_prompt_meta = _build_medium_chunk_live_structured_messages(
            first_chunk.expected_ids,
            prompt_variant=structured_prompt_variant,
        )
        first_response_format = build_factual_blocks_response_format(
            expected_block_ids=first_chunk.expected_ids,
            schema_variant=structured_schema_variant,
        )
        first_max_tokens = _scaled_live_max_tokens(
            estimated_input_tokens=first_chunk.estimated_input_tokens,
            items_count=first_chunk.items_count,
        )
        preflight_outcome = _build_context_fit_failed_outcome(
            config=config,
            run_id=run_id,
            load_config=load_config,
            prompt_meta=first_prompt_meta,
            response_format=first_response_format,
            max_tokens=first_max_tokens,
            estimated_input_tokens=first_chunk.estimated_input_tokens,
            error_status="missing_verified_context",
            request_id="batch_0001_chunk_0000",
            dataset_id=dataset_id,
            dataset_hash=dataset_manifest.content_hash,
            app_concurrency=app_concurrency,
        )
        structured_errors = (
            (preflight_outcome.structured_error,) if preflight_outcome.structured_error else ()
        )
        return LiveChunkedSmokeOutcome(
            metrics=(),
            structured_errors=structured_errors,
            batch_summary=_build_chunked_batch_summary(
                config=config,
                run_id=run_id,
                load_config=load_config,
                dataset_hash=dataset_manifest.content_hash,
                chunks_count=chunked_view.chunks_count,
                chunk_size_blocks=chunked_view.chunk_size_blocks,
                app_concurrency=app_concurrency,
                effective_profile=resolved_effective_profile,
                warmup_is_productive=resolved_effective_profile == "productive_first_chunk",
                warmup_policy=effective_warmup_policy,
                warmup_request_count=warmup_request_count,
                metrics=(),
                structured_errors=structured_errors,
                failed_chunk_ids=(),
                warmup_wall_time_ms=None,
                batch_wall_times_ms=(),
                sequential_baseline_wall_time_ms=sequential_baseline_wall_time_ms,
                end_to_end_batch_wall_times_ms=(),
                baseline_end_to_end_wall_time_ms=baseline_end_to_end_wall_time_ms,
            ),
        )

    prebuilt_chunks: list[
        tuple[object, list[dict[str, str]], LivePromptMetadata, int, dict[str, Any]]
    ] = []
    for chunk in chunked_view.chunks:
        messages, prompt_meta = _build_medium_chunk_live_structured_messages(
            chunk.expected_ids,
            prompt_variant=structured_prompt_variant,
        )
        response_format = build_factual_blocks_response_format(
            expected_block_ids=chunk.expected_ids,
            schema_variant=structured_schema_variant,
        )
        max_tokens = _scaled_live_max_tokens(
            estimated_input_tokens=chunk.estimated_input_tokens,
            items_count=chunk.items_count,
        )
        context_fit = evaluate_context_fit(
            estimated_input_tokens=chunk.estimated_input_tokens,
            max_tokens=max_tokens,
            effective_context_length=verified_context_length,
            safety_ratio=context_fit_safety_ratio,
        )
        if not context_fit.fits:
            preflight_outcome = _build_context_fit_failed_outcome(
                config=config,
                run_id=run_id,
                load_config=load_config,
                prompt_meta=prompt_meta,
                response_format=response_format,
                max_tokens=max_tokens,
                estimated_input_tokens=chunk.estimated_input_tokens,
                error_status="insufficient_context",
                context_fit=context_fit,
                request_id=f"batch_0001_chunk_{chunk.chunk_id:04d}",
                dataset_id=dataset_id,
                dataset_hash=dataset_manifest.content_hash,
                app_concurrency=app_concurrency,
            )
            structured_errors = (
                (preflight_outcome.structured_error,) if preflight_outcome.structured_error else ()
            )
            return LiveChunkedSmokeOutcome(
                metrics=(),
                structured_errors=structured_errors,
                batch_summary=_build_chunked_batch_summary(
                    config=config,
                    run_id=run_id,
                    load_config=load_config,
                    dataset_hash=dataset_manifest.content_hash,
                    chunks_count=chunked_view.chunks_count,
                    chunk_size_blocks=chunked_view.chunk_size_blocks,
                    app_concurrency=app_concurrency,
                    effective_profile=resolved_effective_profile,
                    warmup_is_productive=resolved_effective_profile == "productive_first_chunk",
                    warmup_policy=effective_warmup_policy,
                    warmup_request_count=warmup_request_count,
                    metrics=(),
                    structured_errors=structured_errors,
                    failed_chunk_ids=(chunk.chunk_id,),
                    warmup_wall_time_ms=None,
                    batch_wall_times_ms=(),
                    sequential_baseline_wall_time_ms=sequential_baseline_wall_time_ms,
                    end_to_end_batch_wall_times_ms=(),
                    baseline_end_to_end_wall_time_ms=baseline_end_to_end_wall_time_ms,
                ),
            )
        prebuilt_chunks.append((chunk, messages, prompt_meta, max_tokens, response_format))

    def _execute_chunk_request(
        *,
        chunk: object,
        messages: list[dict[str, str]],
        prompt_meta: LivePromptMetadata,
        max_tokens: int,
        response_format: dict[str, Any],
        request_id: str,
    ) -> LiveSmokeOutcome:
        return _execute_live_structured_request(
            config=config,
            run_id=run_id,
            timeout_s=timeout_s,
            transport=request_transport,
            endpoint_url=endpoint_url,
            request_payload={
                "model": config.models[0].model_id,
                "messages": messages,
                "response_format": response_format,
                "temperature": 0,
                "max_tokens": max_tokens,
            },
            load_config=load_config,
            request_id=request_id,
            dataset_id=dataset_id,
            dataset_hash=dataset_manifest.content_hash,
            prompt_meta=prompt_meta,
            response_format=response_format,
            max_tokens=max_tokens,
            estimated_input_tokens=chunk.estimated_input_tokens,
            app_concurrency=app_concurrency,
            business_failure_retry_limit=config.business_failure_retry_limit,
        )

    def _execute_chunk_batch(
        *,
        chunk_specs: Sequence[
            tuple[object, list[dict[str, str]], LivePromptMetadata, int, dict[str, Any]]
        ],
        request_id_builder: Callable[[int], str],
        effective_app_concurrency: int = app_concurrency,
    ) -> tuple[list[tuple[int, LiveSmokeOutcome]], float]:
        started_at = clock()
        if effective_app_concurrency == 1:
            ordered_outcomes: list[tuple[int, LiveSmokeOutcome]] = []
            for chunk, messages, prompt_meta, max_tokens, response_format in chunk_specs:
                ordered_outcomes.append(
                    (
                        chunk.chunk_id,
                        _execute_chunk_request(
                            chunk=chunk,
                            messages=messages,
                            prompt_meta=prompt_meta,
                            max_tokens=max_tokens,
                            response_format=response_format,
                            request_id=request_id_builder(chunk.chunk_id),
                        ),
                    )
                )
            return ordered_outcomes, _elapsed_ms(started_at, clock=clock)

        future_by_chunk_id: dict[int, Future[LiveSmokeOutcome]] = {}
        with ThreadPoolExecutor(max_workers=effective_app_concurrency) as executor:
            for chunk, messages, prompt_meta, max_tokens, response_format in chunk_specs:
                future_by_chunk_id[chunk.chunk_id] = executor.submit(
                    _execute_chunk_request,
                    chunk=chunk,
                    messages=messages,
                    prompt_meta=prompt_meta,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    request_id=request_id_builder(chunk.chunk_id),
                )
            ordered_outcomes = [
                (chunk.chunk_id, future_by_chunk_id[chunk.chunk_id].result())
                for chunk, _messages, _prompt_meta, _max_tokens, _response_format in chunk_specs
            ]
        return ordered_outcomes, _elapsed_ms(started_at, clock=clock)

    warmup_wall_time_ms: float | None = None
    if effective_warmup_policy != "none":
        warmup_results: list[tuple[int | None, LiveSmokeOutcome]] = []
        if effective_warmup_policy == "concurrent_full_batch":
            measured_warmup_results, warmup_wall_time_ms = _execute_chunk_batch(
                chunk_specs=prebuilt_chunks,
                request_id_builder=lambda chunk_id: f"warmup_chunk_{chunk_id:04d}",
            )
            warmup_results = [(chunk_id, outcome) for chunk_id, outcome in measured_warmup_results]
        elif effective_warmup_policy == "sequential_full_batch":
            measured_warmup_results, warmup_wall_time_ms = _execute_chunk_batch(
                chunk_specs=prebuilt_chunks,
                request_id_builder=lambda chunk_id: f"warmup_chunk_{chunk_id:04d}",
                effective_app_concurrency=1,
            )
            warmup_results = [(chunk_id, outcome) for chunk_id, outcome in measured_warmup_results]
        elif effective_warmup_policy == "sequential_chunk_0":
            (
                warmup_chunk,
                warmup_messages,
                warmup_prompt_meta,
                warmup_max_tokens,
                warmup_response_format,
            ) = prebuilt_chunks[0]
            warmup_started_at = clock()
            warmup_results = [
                (
                    warmup_chunk.chunk_id,
                    _execute_chunk_request(
                        chunk=warmup_chunk,
                        messages=warmup_messages,
                        prompt_meta=warmup_prompt_meta,
                        max_tokens=warmup_max_tokens,
                        response_format=warmup_response_format,
                        request_id=f"warmup_chunk_{warmup_chunk.chunk_id:04d}",
                    ),
                )
            ]
            warmup_wall_time_ms = _elapsed_ms(warmup_started_at, clock=clock)
        else:
            warmup_messages, warmup_prompt_meta = _build_small_live_structured_messages()
            warmup_dataset_manifest = load_dataset_manifest(_LIVE_SMALL_DATASET_ID)
            warmup_max_tokens = _live_max_tokens(_LIVE_SMALL_DATASET_ID)
            warmup_response_format = build_factual_blocks_response_format()
            warmup_started_at = clock()
            warmup_results = [
                (
                    None,
                    _execute_live_structured_request(
                        config=config,
                        run_id=run_id,
                        timeout_s=timeout_s,
                        transport=request_transport,
                        endpoint_url=endpoint_url,
                        request_payload={
                            "model": config.models[0].model_id,
                            "messages": warmup_messages,
                            "response_format": warmup_response_format,
                            "temperature": 0,
                            "max_tokens": warmup_max_tokens,
                        },
                        load_config=load_config,
                        request_id="warmup_small_structured_0001",
                        dataset_id=_LIVE_SMALL_DATASET_ID,
                        dataset_hash=warmup_dataset_manifest.content_hash,
                        prompt_meta=warmup_prompt_meta,
                        response_format=warmup_response_format,
                        max_tokens=warmup_max_tokens,
                        estimated_input_tokens=warmup_dataset_manifest.estimated_input_tokens,
                        app_concurrency=1,
                    ),
                )
            ]
            warmup_wall_time_ms = _elapsed_ms(warmup_started_at, clock=clock)
        warmup_structured_errors = tuple(
            outcome.structured_error
            for _chunk_id, outcome in warmup_results
            if outcome.structured_error is not None
        )
        if warmup_structured_errors:
            failed_warmup_chunk_ids = [
                chunk_id
                for chunk_id, outcome in warmup_results
                if chunk_id is not None and outcome.structured_error is not None
            ]
            return LiveChunkedSmokeOutcome(
                metrics=(),
                structured_errors=warmup_structured_errors,
                batch_summary=_build_chunked_batch_summary(
                    config=config,
                    run_id=run_id,
                    load_config=load_config,
                    dataset_hash=dataset_manifest.content_hash,
                    chunks_count=chunked_view.chunks_count,
                    chunk_size_blocks=chunked_view.chunk_size_blocks,
                    app_concurrency=app_concurrency,
                    effective_profile=resolved_effective_profile,
                    warmup_is_productive=resolved_effective_profile == "productive_first_chunk",
                    warmup_policy=effective_warmup_policy,
                    warmup_request_count=warmup_request_count,
                    metrics=(),
                    structured_errors=warmup_structured_errors,
                    failed_chunk_ids=failed_warmup_chunk_ids,
                    warmup_wall_time_ms=warmup_wall_time_ms,
                    batch_wall_times_ms=(),
                    sequential_baseline_wall_time_ms=sequential_baseline_wall_time_ms,
                    end_to_end_batch_wall_times_ms=(),
                    baseline_end_to_end_wall_time_ms=baseline_end_to_end_wall_time_ms,
                ),
            )

    metrics: list[LMStudioLabMetricRecord] = []
    structured_errors: list[dict[str, object]] = []
    failed_chunk_ids: list[int] = []
    batch_wall_times_ms: list[float] = []
    end_to_end_batch_wall_times_ms: list[float] = []
    for batch_index in range(1, config.repeats + 1):
        if resolved_effective_profile == "productive_first_chunk":
            (
                first_chunk,
                first_messages,
                first_prompt_meta,
                first_max_tokens,
                first_response_format,
            ) = prebuilt_chunks[0]
            remaining_chunk_specs = prebuilt_chunks[1:]
            first_chunk_started_at = clock()
            first_chunk_outcome = _execute_chunk_request(
                chunk=first_chunk,
                messages=first_messages,
                prompt_meta=first_prompt_meta,
                max_tokens=first_max_tokens,
                response_format=first_response_format,
                request_id=f"batch_{batch_index:04d}_chunk_{first_chunk.chunk_id:04d}",
            )
            first_chunk_wall_time_ms = _elapsed_ms(first_chunk_started_at, clock=clock)
            batch_results = [(first_chunk.chunk_id, first_chunk_outcome)]
            remaining_results: list[tuple[int, LiveSmokeOutcome]] = []
            parallel_batch_wall_time_ms = 0.0
            if remaining_chunk_specs:
                remaining_results, parallel_batch_wall_time_ms = _execute_chunk_batch(
                    chunk_specs=remaining_chunk_specs,
                    request_id_builder=lambda chunk_id, batch_index=batch_index: (
                        f"batch_{batch_index:04d}_chunk_{chunk_id:04d}"
                    ),
                    effective_app_concurrency=min(app_concurrency, len(remaining_chunk_specs)),
                )
            batch_results.extend(remaining_results)
            batch_wall_time_ms = parallel_batch_wall_time_ms
            end_to_end_batch_wall_time_ms = first_chunk_wall_time_ms + parallel_batch_wall_time_ms
        else:
            batch_results, batch_wall_time_ms = _execute_chunk_batch(
                chunk_specs=prebuilt_chunks,
                request_id_builder=lambda chunk_id, batch_index=batch_index: (
                    f"batch_{batch_index:04d}_chunk_{chunk_id:04d}"
                ),
            )
            end_to_end_batch_wall_time_ms = batch_wall_time_ms + (
                warmup_wall_time_ms if batch_index == 1 and warmup_wall_time_ms is not None else 0.0
            )
        batch_wall_times_ms.append(batch_wall_time_ms)
        end_to_end_batch_wall_times_ms.append(end_to_end_batch_wall_time_ms)
        for chunk_id, outcome in batch_results:
            metrics.append(outcome.metric)
            if outcome.structured_error is not None:
                failed_chunk_ids.append(chunk_id)
                structured_errors.append(outcome.structured_error)

    return LiveChunkedSmokeOutcome(
        metrics=tuple(metrics),
        structured_errors=tuple(structured_errors),
        batch_summary=_build_chunked_batch_summary(
            config=config,
            run_id=run_id,
            load_config=load_config,
            dataset_hash=dataset_manifest.content_hash,
            chunks_count=chunked_view.chunks_count,
            chunk_size_blocks=chunked_view.chunk_size_blocks,
            app_concurrency=app_concurrency,
            effective_profile=resolved_effective_profile,
            warmup_is_productive=resolved_effective_profile == "productive_first_chunk",
            warmup_policy=effective_warmup_policy,
            warmup_request_count=warmup_request_count,
            metrics=metrics,
            structured_errors=structured_errors,
            failed_chunk_ids=failed_chunk_ids,
            warmup_wall_time_ms=warmup_wall_time_ms,
            batch_wall_times_ms=batch_wall_times_ms,
            sequential_baseline_wall_time_ms=sequential_baseline_wall_time_ms,
            end_to_end_batch_wall_times_ms=end_to_end_batch_wall_times_ms,
            baseline_end_to_end_wall_time_ms=baseline_end_to_end_wall_time_ms,
        ),
    )


def run_live_structured_smoke(
    config: LiveSmokeConfig,
    *,
    run_id: str,
    timeout_s: float = 30.0,
    transport: LiveTransport | None = None,
    verified_context_length: int | None = None,
    context_fit_safety_ratio: float = 0.85,
    prompt_variant: str = "baseline",
    reasoning_control_variant: str = "baseline",
) -> LiveSmokeOutcome:
    load_config = _validate_live_request_shape(config)
    dataset_id = config.datasets[0]
    normalized_reasoning_control = _validate_structured_reasoning_control_variant(
        reasoning_control_variant
    )
    if dataset_id != _LIVE_SMALL_DATASET_ID and normalized_reasoning_control != "baseline":
        raise ValueError(
            "structured reasoning control "
            f"{normalized_reasoning_control!r} is supported only for "
            f"{_LIVE_SMALL_DATASET_ID} live dataset"
        )
    dataset_manifest = load_dataset_manifest(dataset_id)
    response_format = build_factual_blocks_response_format()
    messages, prompt_meta = build_live_structured_messages(
        dataset_id,
        prompt_variant=prompt_variant,
    )
    max_tokens = _live_max_tokens(dataset_id)
    estimated_input_tokens = dataset_manifest.estimated_input_tokens

    if dataset_id == _LIVE_MEDIUM_DATASET_ID and verified_context_length is None:
        return _build_context_fit_failed_outcome(
            config=config,
            run_id=run_id,
            load_config=load_config,
            prompt_meta=prompt_meta,
            response_format=response_format,
            max_tokens=max_tokens,
            estimated_input_tokens=estimated_input_tokens,
            error_status="missing_verified_context",
        )

    if verified_context_length is not None:
        context_fit = evaluate_context_fit(
            estimated_input_tokens=estimated_input_tokens,
            max_tokens=max_tokens,
            effective_context_length=verified_context_length,
            safety_ratio=context_fit_safety_ratio,
        )
        if not context_fit.fits:
            return _build_context_fit_failed_outcome(
                config=config,
                run_id=run_id,
                load_config=load_config,
                prompt_meta=prompt_meta,
                response_format=response_format,
                max_tokens=max_tokens,
                estimated_input_tokens=estimated_input_tokens,
                error_status="insufficient_context",
                context_fit=context_fit,
            )

    request_payload = {
        "model": config.models[0].model_id,
        "messages": messages,
        "response_format": response_format,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if normalized_reasoning_control == "chat_template_kwargs_enable_thinking_false":
        request_payload["chat_template_kwargs"] = {"enable_thinking": False}
    request_transport = transport or _default_transport
    endpoint_url = _chat_completions_url(config.lmstudio_base_url)
    return _execute_live_structured_request(
        config=config,
        run_id=run_id,
        timeout_s=timeout_s,
        transport=request_transport,
        endpoint_url=endpoint_url,
        request_payload=request_payload,
        load_config=load_config,
        request_id=_LIVE_REQUEST_ID,
        dataset_id=dataset_id,
        dataset_hash=dataset_manifest.content_hash,
        prompt_meta=prompt_meta,
        response_format=response_format,
        max_tokens=max_tokens,
        estimated_input_tokens=estimated_input_tokens,
        app_concurrency=_coerce_int(load_config.get("parallel", load_config.get("n_parallel")))
        or 1,
    )


def _validate_concurrency_diagnostic_kind(diagnostic_kind: str) -> str:
    normalized = _coerce_str(diagnostic_kind)
    if normalized not in _SUPPORTED_LIVE_CONCURRENCY_DIAGNOSTIC_KINDS:
        raise ValueError(
            "diagnostic_kind must be one of plain_text_pair, plain_text_artifacts, "
            "plain_text_artifacts_normalized, structured_small_pair, medium_pair"
        )
    return normalized


def _validate_concurrency_timeout(timeout_s: float) -> float:
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        raise ValueError("timeout_s must be > 0")
    return float(timeout_s)


def _validate_context_fit_ratio(context_fit_safety_ratio: float) -> float:
    if (
        isinstance(context_fit_safety_ratio, bool)
        or not isinstance(context_fit_safety_ratio, (int, float))
        or context_fit_safety_ratio <= 0
        or context_fit_safety_ratio > 1
    ):
        raise ValueError("context_fit_safety_ratio must be between 0 and 1")
    return float(context_fit_safety_ratio)


def _validate_verified_context_length(verified_context_length: int | None) -> int:
    if (
        isinstance(verified_context_length, bool)
        or not isinstance(verified_context_length, int)
        or verified_context_length <= 0
    ):
        raise ValueError("verified_context_length must be a positive integer")
    return verified_context_length


def _validate_concurrency_request_count(app_concurrency: int, *, request_count: int) -> int:
    if isinstance(app_concurrency, bool) or not isinstance(app_concurrency, int):
        raise ValueError("app_concurrency must be an integer between 1 and request_count")
    if app_concurrency < 1 or app_concurrency > request_count:
        raise ValueError("app_concurrency must be between 1 and request_count")
    return app_concurrency


def _validate_loaded_parallel(loaded_parallel: int | None) -> int | None:
    if loaded_parallel is None:
        return None
    if (
        isinstance(loaded_parallel, bool)
        or not isinstance(loaded_parallel, int)
        or loaded_parallel <= 0
    ):
        raise ValueError("loaded_parallel must be a positive integer")
    return loaded_parallel


def _resolve_concurrency_queue_pressure_mode(
    *,
    app_concurrency: int,
    loaded_parallel: int | None,
    allow_queue_pressure: bool,
) -> tuple[int | None, bool]:
    resolved_loaded_parallel = _validate_loaded_parallel(loaded_parallel)
    if app_concurrency > 1 and resolved_loaded_parallel is None:
        if not allow_queue_pressure:
            raise ValueError(
                "app_concurrency > 1 requires --loaded-parallel or explicit queue pressure opt-in "
                "via --allow-queue-pressure"
            )
        return None, True
    if resolved_loaded_parallel is not None and app_concurrency > resolved_loaded_parallel:
        if not allow_queue_pressure:
            raise ValueError(
                "app_concurrency exceeds loaded parallel; use --allow-queue-pressure only "
                "for intentional queue pressure"
            )
        return resolved_loaded_parallel, True
    return resolved_loaded_parallel, False


def _validate_concurrency_base_url(base_url: str) -> str:
    if not is_local_lmstudio_base_url(base_url):
        raise ValueError("base_url must stay on localhost for concurrency diagnostics")
    return base_url


def _resolve_concurrency_max_tokens_override(
    diagnostic_kind: str,
    max_tokens_override: int | None,
) -> int | None:
    if max_tokens_override is None:
        return None
    if diagnostic_kind not in _PLAIN_TEXT_CONCURRENCY_DIAGNOSTIC_KINDS:
        raise ValueError(
            "max_tokens_override is supported only for plain-text concurrency diagnostics"
        )
    if (
        isinstance(max_tokens_override, bool)
        or not isinstance(max_tokens_override, int)
        or max_tokens_override <= 0
    ):
        raise ValueError("max_tokens_override must be a positive integer")
    return max_tokens_override


def _apply_concurrency_max_tokens_override(
    request_specs: Sequence[_ConcurrencyRequestSpec],
    *,
    max_tokens_override: int | None,
) -> tuple[_ConcurrencyRequestSpec, ...]:
    if max_tokens_override is None:
        return tuple(request_specs)
    return tuple(replace(spec, max_tokens=max_tokens_override) for spec in request_specs)


def _shared_concurrency_max_tokens(
    request_specs: Sequence[_ConcurrencyRequestSpec],
) -> int | None:
    if not request_specs:
        return None
    max_tokens = request_specs[0].max_tokens
    if all(spec.max_tokens == max_tokens for spec in request_specs):
        return max_tokens
    return None


def _build_plain_text_messages(
    request_label: str,
) -> tuple[list[dict[str, str]], LivePromptMetadata]:
    messages = [
        {
            "role": "system",
            "content": (
                "Reply with one short plain-text sentence only. "
                "Do not return JSON, markdown, or reasoning."
            ),
        },
        {
            "role": "user",
            "content": f"Return a plain-text acknowledgement for diagnostic slot {request_label}.",
        },
    ]
    return messages, _build_prompt_metadata(messages, expected_block_ids=())


def _build_plain_text_artifact_messages(
    task_id: str,
) -> tuple[list[dict[str, str]], LivePromptMetadata]:
    task_prompts = {
        "summary_short": (
            "Create a short, plain-text summary of this synthetic lab note: "
            "A sample session covered queue warmup, pause-resume checks, and export verification."
        ),
        "lecture_notes": (
            "Turn this synthetic workshop outline into four compact lecture notes in plain text only: "
            "input capture, transcript cleanup, validation pass, final review."
        ),
        "mic_command_answer": (
            "Provide a plain-text assistant reply to this synthetic microphone command: "
            "start recording after a three second countdown and confirm hotkey readiness."
        ),
        "freeform_rewrite": (
            "Rewrite this synthetic reminder into natural plain text: "
            "check the device, record a short sample, stop safely, and save the result."
        ),
    }
    user_content = task_prompts[task_id]
    messages = [
        {
            "role": "system",
            "content": (
                "Return the final answer immediately as one short plain-text sentence. "
                "No reasoning, JSON, markdown, or bullets."
            ),
        },
        {"role": "user", "content": user_content},
    ]
    return messages, _build_prompt_metadata(messages, expected_block_ids=())


def _build_plain_text_artifact_normalized_messages(
    task_id: str,
) -> tuple[list[dict[str, str]], LivePromptMetadata]:
    task_prompts = {
        "summary_short": (
            "Write a synthetic lab recap that covers queue warmup completion, a passed pause-resume "
            "check, one export verification, and a short final review before archive. Keep the answer "
            "self-contained and concrete."
        ),
        "lecture_notes": (
            "Convert this synthetic training outline into a compact teaching note: input capture setup, "
            "transcript cleanup, validation review, operator sign-off, and a saved follow-up checklist."
        ),
        "mic_command_answer": (
            "Respond to this synthetic microphone workflow request: begin after a three second countdown, "
            "confirm the hotkey is ready, remind the operator to watch levels, and explain how to stop "
            "cleanly."
        ),
        "freeform_rewrite": (
            "Rewrite this synthetic reminder into a smooth operational note: inspect the device, record a "
            "brief sample, pause once to confirm monitoring, stop safely, review the text, and save the "
            "result."
        ),
    }
    user_content = task_prompts[task_id]
    messages = [
        {
            "role": "system",
            "content": (
                "Answer in 120-160 words, plain text only, no JSON, markdown, reasoning, or introduction."
            ),
        },
        {"role": "user", "content": user_content},
    ]
    return messages, _build_prompt_metadata(messages, expected_block_ids=())


def _build_concurrency_metric(
    *,
    run_id: str,
    diagnostic_kind: str,
    model_id: str,
    model_key: str,
    request_id: str,
    dataset_id: str,
    dataset_hash: str | None,
    prompt_meta: LivePromptMetadata,
    response_format: Mapping[str, Any] | None,
    max_tokens: int,
    requested_context_length: int | None,
    app_concurrency: int,
    loaded_parallel: int | None,
    queue_pressure_mode: bool,
    tokens: TokenMetrics,
    timing: TimingMetrics,
    validation: ValidationMetrics,
    error_category: str | None,
    error_status: str,
    response_hash: str | None,
    response_chars: int,
    content_empty: bool | None,
    reasoning_content_present: bool | None,
) -> LMStudioLabMetricRecord:
    parallel_fields = _build_parallel_semantics_fields(
        app_concurrency=app_concurrency,
        configured_parallel=None,
        applied_parallel=loaded_parallel,
        queue_pressure_mode=queue_pressure_mode,
        explicit_parallel_metadata=loaded_parallel is not None,
    )
    applied_load_config: dict[str, object] = {}
    if requested_context_length is not None:
        applied_load_config["context_length"] = requested_context_length
    if loaded_parallel is not None:
        applied_load_config["parallel"] = loaded_parallel
    return LMStudioLabMetricRecord.from_parts(
        run_id=run_id,
        experiment_id="concurrency_diagnostics",
        request_id=request_id,
        dataset_id=dataset_id,
        dataset_hash=dataset_hash,
        model_key=model_key,
        model_id=model_id,
        endpoint_kind=_LIVE_ENDPOINT_KIND,
        mode=diagnostic_kind,
        requested_context_length=requested_context_length,
        app_concurrency=app_concurrency,
        configured_parallel=parallel_fields["configured_parallel"],
        applied_parallel=parallel_fields["applied_parallel"],
        parallel_verified=parallel_fields["parallel_verified"],
        queue_pressure_mode=parallel_fields["queue_pressure_mode"],
        parallel_semantics=parallel_fields["parallel_semantics"],
        max_tokens=max_tokens,
        temperature=0.0,
        response_format=response_format,
        applied_load_config=applied_load_config or None,
        prompt_hash=prompt_meta.prompt_hash,
        prompt_chars=prompt_meta.prompt_chars,
        response_hash=response_hash,
        response_chars=response_chars,
        content_empty=content_empty,
        reasoning_content_present=reasoning_content_present,
        tokens=tokens,
        timing=timing,
        validation=validation,
        error_category=error_category,
        error_status=error_status,
    )


def _execute_concurrency_request(
    *,
    run_id: str,
    diagnostic_kind: str,
    model_id: str,
    model_key: str,
    timeout_s: float,
    transport: LiveTransport,
    endpoint_url: str,
    request_payload: Mapping[str, Any],
    request_spec: _ConcurrencyRequestSpec,
    app_concurrency: int,
    loaded_parallel: int | None,
    queue_pressure_mode: bool,
) -> LiveSmokeOutcome:
    started_at = time.monotonic()
    try:
        response_payload = transport(endpoint_url, request_payload, timeout_s)
        elapsed_ms = (time.monotonic() - started_at) * 1000.0
        if not isinstance(response_payload, Mapping):
            raise ValueError("LM Studio response must be a mapping")

        envelope = _extract_response_envelope(response_payload)
        lab_reasoning_content_present = envelope.reasoning_content_present
        response_text = envelope.content_text
        tokens = _build_tokens(
            estimated_input_tokens=request_spec.estimated_input_tokens or 0,
            response_payload=response_payload,
        )
        if request_spec.estimated_input_tokens is None:
            tokens.estimated_input_tokens = None
        managed_envelope = _managed_generation_envelope_from_lab_response(
            envelope=envelope,
            tokens=tokens,
        )
        timing = _build_timing(response_payload, elapsed_ms=elapsed_ms)

        if request_spec.validator_kind == "plain_text":
            non_empty_text_pass = not managed_envelope.content_empty
            reasoning_leak = bool(response_text and _contains_reasoning_markers(response_text))
            business_pass = (
                non_empty_text_pass
                and managed_envelope.finish_reason != "length"
                and not reasoning_leak
            )
            validation = ValidationMetrics(
                business_pass=business_pass,
                non_empty_text_pass=non_empty_text_pass,
                reasoning_leak=reasoning_leak,
                finish_reason=managed_envelope.finish_reason,
            )
            if reasoning_leak:
                error_category = "reasoning"
            else:
                failure_kind = None
                if managed_envelope.finish_reason == "length":
                    failure_kind = failure_kind_from_lab_category(
                        "finish",
                        finish_reason=managed_envelope.finish_reason,
                    )
                elif not non_empty_text_pass:
                    failure_kind = failure_kind_from_lab_category(
                        "empty",
                        content_empty=True,
                        reasoning_content_present=lab_reasoning_content_present,
                    )
                managed_envelope = replace(managed_envelope, error_kind=failure_kind)
                error_category = _lab_error_category_from_failure_kind(failure_kind)
        else:
            if managed_envelope.content_empty is True:
                failure_kind = failure_kind_from_lab_category(
                    "empty",
                    content_empty=managed_envelope.content_empty,
                    reasoning_content_present=lab_reasoning_content_present,
                )
                managed_envelope = replace(managed_envelope, error_kind=failure_kind)
                validation = ValidationMetrics(
                    json_parse_pass=False,
                    schema_pass=False,
                    business_pass=False,
                    finish_reason=managed_envelope.finish_reason,
                )
                error_category = _lab_error_category_from_failure_kind(managed_envelope.error_kind)
            else:
                validation_result = validate_factual_blocks_response(
                    response_text,
                    expected_block_ids=request_spec.prompt_meta.expected_block_ids,
                    finish_reason=managed_envelope.finish_reason,
                )
                validation = validation_result.to_metrics()
                error_category = _map_validation_error_category(
                    validation_result.error_category,
                    json_parse_pass=validation_result.json_parse_pass,
                    finish_reason=validation_result.finish_reason,
                )
                managed_envelope = replace(
                    managed_envelope,
                    error_kind=(
                        None
                        if error_category == "reasoning"
                        else failure_kind_from_lab_category(
                            error_category,
                            content_empty=managed_envelope.content_empty,
                            reasoning_content_present=lab_reasoning_content_present,
                            finish_reason=managed_envelope.finish_reason,
                        )
                    ),
                )

        metric = _build_concurrency_metric(
            run_id=run_id,
            diagnostic_kind=diagnostic_kind,
            model_id=model_id,
            model_key=model_key,
            request_id=request_spec.request_id,
            dataset_id=request_spec.dataset_id,
            dataset_hash=request_spec.dataset_hash,
            prompt_meta=request_spec.prompt_meta,
            response_format=request_spec.response_format,
            max_tokens=request_spec.max_tokens,
            requested_context_length=request_spec.requested_context_length,
            app_concurrency=app_concurrency,
            loaded_parallel=loaded_parallel,
            queue_pressure_mode=queue_pressure_mode,
            tokens=tokens,
            timing=timing,
            validation=validation,
            error_category=error_category,
            error_status="ok" if error_category is None else "failed",
            response_hash=managed_envelope.content_hash,
            response_chars=managed_envelope.content_chars,
            content_empty=managed_envelope.content_empty,
            reasoning_content_present=lab_reasoning_content_present,
        )
        return LiveSmokeOutcome(
            metric=metric,
            structured_error=None if error_category is None else _build_error_payload(metric),
        )
    except Exception as error:
        elapsed_ms = (time.monotonic() - started_at) * 1000.0
        error_category, error_status = _classify_transport_error(error)
        metric = _build_concurrency_metric(
            run_id=run_id,
            diagnostic_kind=diagnostic_kind,
            model_id=model_id,
            model_key=model_key,
            request_id=request_spec.request_id,
            dataset_id=request_spec.dataset_id,
            dataset_hash=request_spec.dataset_hash,
            prompt_meta=request_spec.prompt_meta,
            response_format=request_spec.response_format,
            max_tokens=request_spec.max_tokens,
            requested_context_length=request_spec.requested_context_length,
            app_concurrency=app_concurrency,
            loaded_parallel=loaded_parallel,
            queue_pressure_mode=queue_pressure_mode,
            tokens=TokenMetrics(
                estimated_input_tokens=request_spec.estimated_input_tokens,
                estimate_scope="dataset_only",
            ),
            timing=TimingMetrics(total_elapsed_ms=elapsed_ms),
            validation=ValidationMetrics(),
            error_category=error_category,
            error_status=error_status,
            response_hash=None,
            response_chars=0,
            content_empty=None,
            reasoning_content_present=None,
        )
        return LiveSmokeOutcome(metric=metric, structured_error=_build_error_payload(metric))


def _build_plain_text_pair_specs() -> tuple[_ConcurrencyRequestSpec, ...]:
    specs: list[_ConcurrencyRequestSpec] = []
    for index, request_label in enumerate(("alpha", "beta"), start=1):
        messages, prompt_meta = _build_plain_text_messages(request_label)
        specs.append(
            _ConcurrencyRequestSpec(
                request_id=f"plain_text_{index:04d}",
                dataset_id="plain_text_pair",
                dataset_hash=None,
                messages=messages,
                prompt_meta=prompt_meta,
                response_format=None,
                max_tokens=_PLAIN_TEXT_MAX_TOKENS,
                estimated_input_tokens=None,
                requested_context_length=None,
                validator_kind="plain_text",
            )
        )
    return tuple(specs)


def _build_plain_text_artifact_specs() -> tuple[_ConcurrencyRequestSpec, ...]:
    specs: list[_ConcurrencyRequestSpec] = []
    for task_id in _PLAIN_TEXT_ARTIFACT_TASK_IDS:
        messages, prompt_meta = _build_plain_text_artifact_messages(task_id)
        specs.append(
            _ConcurrencyRequestSpec(
                request_id=f"plain_text_artifact_{task_id}",
                dataset_id=f"plain_text_artifacts_{task_id}",
                dataset_hash=None,
                messages=messages,
                prompt_meta=prompt_meta,
                response_format=None,
                max_tokens=_PLAIN_TEXT_ARTIFACT_MAX_TOKENS,
                estimated_input_tokens=None,
                requested_context_length=None,
                validator_kind="plain_text",
            )
        )
    return tuple(specs)


def _build_plain_text_artifact_normalized_specs() -> tuple[_ConcurrencyRequestSpec, ...]:
    specs: list[_ConcurrencyRequestSpec] = []
    for task_id in _PLAIN_TEXT_ARTIFACT_TASK_IDS:
        messages, prompt_meta = _build_plain_text_artifact_normalized_messages(task_id)
        specs.append(
            _ConcurrencyRequestSpec(
                request_id=f"plain_text_artifact_normalized_{task_id}",
                dataset_id=f"plain_text_artifacts_normalized_{task_id}",
                dataset_hash=None,
                messages=messages,
                prompt_meta=prompt_meta,
                response_format=None,
                max_tokens=_PLAIN_TEXT_ARTIFACT_MAX_TOKENS,
                estimated_input_tokens=None,
                requested_context_length=None,
                validator_kind="plain_text",
            )
        )
    return tuple(specs)


def _build_structured_small_pair_specs() -> tuple[_ConcurrencyRequestSpec, ...]:
    dataset_manifest = load_dataset_manifest(_LIVE_SMALL_DATASET_ID)
    max_tokens = _live_max_tokens(_LIVE_SMALL_DATASET_ID)
    specs: list[_ConcurrencyRequestSpec] = []
    for index in range(1, 3):
        messages, prompt_meta = build_live_structured_messages(_LIVE_SMALL_DATASET_ID)
        specs.append(
            _ConcurrencyRequestSpec(
                request_id=f"structured_small_{index:04d}",
                dataset_id=_LIVE_SMALL_DATASET_ID,
                dataset_hash=dataset_manifest.content_hash,
                messages=messages,
                prompt_meta=prompt_meta,
                response_format=build_factual_blocks_response_format(),
                max_tokens=max_tokens,
                estimated_input_tokens=dataset_manifest.estimated_input_tokens,
                requested_context_length=None,
                validator_kind="structured",
            )
        )
    return tuple(specs)


def _build_concurrency_preflight_failure(
    *,
    run_id: str,
    diagnostic_kind: str,
    model_id: str,
    model_key: str,
    request_count: int,
    app_concurrency: int,
    loaded_parallel: int | None,
    queue_pressure_mode: bool,
    request_spec: _ConcurrencyRequestSpec,
    context_fit: ContextFitResult,
) -> LiveConcurrencyDiagnosticsOutcome:
    metric = _build_concurrency_metric(
        run_id=run_id,
        diagnostic_kind=diagnostic_kind,
        model_id=model_id,
        model_key=model_key,
        request_id=request_spec.request_id,
        dataset_id=request_spec.dataset_id,
        dataset_hash=request_spec.dataset_hash,
        prompt_meta=request_spec.prompt_meta,
        response_format=request_spec.response_format,
        max_tokens=request_spec.max_tokens,
        requested_context_length=request_spec.requested_context_length,
        app_concurrency=app_concurrency,
        loaded_parallel=loaded_parallel,
        queue_pressure_mode=queue_pressure_mode,
        tokens=TokenMetrics(
            estimated_input_tokens=request_spec.estimated_input_tokens,
            estimate_scope="dataset_only",
        ),
        timing=TimingMetrics(total_elapsed_ms=0.0),
        validation=_preflight_validation_metrics(),
        error_category="context_fit_failed",
        error_status="insufficient_context",
        response_hash=None,
        response_chars=0,
        content_empty=None,
        reasoning_content_present=None,
    )
    structured_error = _build_error_payload_with_extra(
        metric,
        extra_fields=_build_context_fit_extra_fields(
            estimated_input_tokens=request_spec.estimated_input_tokens or 0,
            max_tokens=request_spec.max_tokens,
            context_fit=context_fit,
        ),
    )
    summary = _build_live_concurrency_diagnostics_summary(
        run_id=run_id,
        diagnostic_kind=diagnostic_kind,
        model_id=model_id,
        model_key=model_key,
        request_count=request_count,
        app_concurrency=app_concurrency,
        loaded_parallel=loaded_parallel,
        queue_pressure_mode=queue_pressure_mode,
        request_specs=(request_spec,),
        metrics=(),
        structured_errors=(structured_error,),
        total_wall_time_ms=0.0,
    )
    return LiveConcurrencyDiagnosticsOutcome(
        metrics=(),
        structured_errors=(structured_error,),
        summary=summary,
    )


def _build_medium_pair_specs(
    *,
    run_id: str,
    model_id: str,
    model_key: str,
    app_concurrency: int,
    loaded_parallel: int | None,
    queue_pressure_mode: bool,
    verified_context_length: int,
    context_fit_safety_ratio: float,
) -> tuple[tuple[_ConcurrencyRequestSpec, ...] | None, LiveConcurrencyDiagnosticsOutcome | None]:
    chunked_view = load_chunked_dataset_view(_LIVE_MEDIUM_CHUNKED_DATASET_ID)
    dataset_manifest = load_dataset_manifest(_LIVE_MEDIUM_CHUNKED_DATASET_ID)
    specs: list[_ConcurrencyRequestSpec] = []
    for chunk in chunked_view.chunks[:2]:
        messages, prompt_meta = _build_medium_chunk_live_structured_messages(chunk.expected_ids)
        max_tokens = _scaled_live_max_tokens(
            estimated_input_tokens=chunk.estimated_input_tokens,
            items_count=chunk.items_count,
        )
        context_fit = evaluate_context_fit(
            estimated_input_tokens=chunk.estimated_input_tokens,
            max_tokens=max_tokens,
            effective_context_length=verified_context_length,
            safety_ratio=context_fit_safety_ratio,
        )
        request_spec = _ConcurrencyRequestSpec(
            request_id=f"medium_pair_chunk_{chunk.chunk_id:04d}",
            dataset_id=_LIVE_MEDIUM_CHUNKED_DATASET_ID,
            dataset_hash=dataset_manifest.content_hash,
            messages=messages,
            prompt_meta=prompt_meta,
            response_format=build_factual_blocks_response_format(),
            max_tokens=max_tokens,
            estimated_input_tokens=chunk.estimated_input_tokens,
            requested_context_length=verified_context_length,
            validator_kind="structured",
        )
        if not context_fit.fits:
            return None, _build_concurrency_preflight_failure(
                run_id=run_id,
                diagnostic_kind="medium_pair",
                model_id=model_id,
                model_key=model_key,
                request_count=2,
                app_concurrency=app_concurrency,
                loaded_parallel=loaded_parallel,
                queue_pressure_mode=queue_pressure_mode,
                request_spec=request_spec,
                context_fit=context_fit,
            )
        specs.append(request_spec)
    return tuple(specs), None


def _build_live_concurrency_diagnostics_summary(
    *,
    run_id: str,
    diagnostic_kind: str,
    model_id: str,
    model_key: str,
    request_count: int,
    app_concurrency: int,
    loaded_parallel: int | None,
    queue_pressure_mode: bool,
    request_specs: Sequence[_ConcurrencyRequestSpec],
    metrics: Sequence[LMStudioLabMetricRecord],
    structured_errors: Sequence[Mapping[str, object]],
    total_wall_time_ms: float,
    max_tokens_override: int | None = None,
) -> dict[str, object]:
    timing_values = [metric.timing.total_elapsed_ms for metric in metrics]
    latency_values = [value for value in timing_values if value is not None]
    managed_batch_metrics = _build_managed_batch_metrics(
        metrics,
        total_wall_time_ms=total_wall_time_ms,
    )
    parallel_fields = _build_parallel_semantics_fields(
        app_concurrency=app_concurrency,
        configured_parallel=None,
        applied_parallel=loaded_parallel,
        queue_pressure_mode=queue_pressure_mode,
        explicit_parallel_metadata=loaded_parallel is not None,
    )
    summary: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "diagnostic_kind": diagnostic_kind,
        "model_key": model_key,
        "model_id": model_id,
        "endpoint_kind": _LIVE_ENDPOINT_KIND,
        "app_concurrency": app_concurrency,
        "configured_parallel": parallel_fields["configured_parallel"],
        "applied_parallel": parallel_fields["applied_parallel"],
        "parallel_verified": parallel_fields["parallel_verified"],
        "parallel_semantics": parallel_fields["parallel_semantics"],
        "loaded_parallel": loaded_parallel,
        "queue_pressure_mode": parallel_fields["queue_pressure_mode"],
        "request_count": request_count,
        "all_requests_pass": managed_batch_metrics.request_count == request_count
        and all(
            metric.error_category is None and metric.validation.business_pass is True
            for metric in metrics
        ),
        "json_parse_pass_count": _count_true(
            [metric.validation.json_parse_pass for metric in metrics]
        ),
        "schema_pass_count": _count_true([metric.validation.schema_pass for metric in metrics]),
        "business_pass_count": managed_batch_metrics.business_pass_count,
        "finish_length_count": managed_batch_metrics.finish_length_count,
        "reasoning_leak_count": _count_true(
            [metric.validation.reasoning_leak for metric in metrics]
        ),
        "structured_error_count": len(structured_errors),
        "total_prompt_tokens": _sum_optional_int(
            [metric.tokens.prompt_tokens for metric in metrics]
        ),
        "total_completion_tokens": managed_batch_metrics.total_completion_tokens,
        "total_tokens": _sum_optional_int([metric.tokens.total_tokens for metric in metrics]),
        "total_wall_time_ms": total_wall_time_ms,
        "avg_request_latency_ms": (
            sum(latency_values) / len(latency_values) if latency_values else None
        ),
        "max_request_latency_ms": max(latency_values, default=None),
        "raw_prompt_response_stored": False,
    }
    summary_max_tokens = _shared_concurrency_max_tokens(request_specs)
    if summary_max_tokens is not None:
        summary["max_tokens"] = summary_max_tokens
    if max_tokens_override is not None:
        summary["max_tokens_override"] = max_tokens_override
    if structured_errors:
        summary["error_category"] = structured_errors[0].get("error_category")
        summary["error_status"] = structured_errors[0].get("error_status")
    return summary


def run_live_concurrency_diagnostics(
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
    transport: LiveTransport | None = None,
    verified_context_length: int | None = None,
    context_fit_safety_ratio: float = 0.85,
    max_tokens_override: int | None = None,
) -> LiveConcurrencyDiagnosticsOutcome:
    resolved_kind = _validate_concurrency_diagnostic_kind(diagnostic_kind)
    resolved_max_tokens_override = _resolve_concurrency_max_tokens_override(
        resolved_kind,
        max_tokens_override,
    )
    _validate_concurrency_base_url(base_url)
    resolved_timeout_s = _validate_concurrency_timeout(timeout_s)
    resolved_context_fit_ratio = _validate_context_fit_ratio(context_fit_safety_ratio)
    resolved_app_concurrency = _validate_concurrency_request_count(
        app_concurrency,
        request_count=2,
    )
    resolved_loaded_parallel, queue_pressure_mode = _resolve_concurrency_queue_pressure_mode(
        app_concurrency=resolved_app_concurrency,
        loaded_parallel=loaded_parallel,
        allow_queue_pressure=allow_queue_pressure,
    )
    request_transport = transport or _default_transport
    endpoint_url = _chat_completions_url(base_url)

    if resolved_kind == "plain_text_pair":
        request_specs = _build_plain_text_pair_specs()
    elif resolved_kind == "plain_text_artifacts":
        request_specs = _build_plain_text_artifact_specs()
    elif resolved_kind == "plain_text_artifacts_normalized":
        request_specs = _build_plain_text_artifact_normalized_specs()
    elif resolved_kind == "structured_small_pair":
        request_specs = _build_structured_small_pair_specs()
    else:
        resolved_context_length = _validate_verified_context_length(verified_context_length)
        request_specs, preflight_outcome = _build_medium_pair_specs(
            run_id=run_id,
            model_id=model_id,
            model_key=model_key,
            app_concurrency=resolved_app_concurrency,
            loaded_parallel=resolved_loaded_parallel,
            queue_pressure_mode=queue_pressure_mode,
            verified_context_length=resolved_context_length,
            context_fit_safety_ratio=resolved_context_fit_ratio,
        )
        if preflight_outcome is not None:
            return preflight_outcome
        assert request_specs is not None
    request_specs = _apply_concurrency_max_tokens_override(
        request_specs,
        max_tokens_override=resolved_max_tokens_override,
    )

    def _submit_request(spec: _ConcurrencyRequestSpec) -> LiveSmokeOutcome:
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": spec.messages,
            "temperature": 0,
            "max_tokens": spec.max_tokens,
        }
        if spec.response_format is not None:
            payload["response_format"] = spec.response_format
        return _execute_concurrency_request(
            run_id=run_id,
            diagnostic_kind=resolved_kind,
            model_id=model_id,
            model_key=model_key,
            timeout_s=resolved_timeout_s,
            transport=request_transport,
            endpoint_url=endpoint_url,
            request_payload=payload,
            request_spec=spec,
            app_concurrency=resolved_app_concurrency,
            loaded_parallel=resolved_loaded_parallel,
            queue_pressure_mode=queue_pressure_mode,
        )

    started_at = time.monotonic()
    if resolved_app_concurrency == 1:
        ordered_outcomes = [_submit_request(spec) for spec in request_specs]
    else:
        with ThreadPoolExecutor(max_workers=resolved_app_concurrency) as executor:
            futures = [executor.submit(_submit_request, spec) for spec in request_specs]
            ordered_outcomes = [future.result() for future in futures]
    total_wall_time_ms = (time.monotonic() - started_at) * 1000.0

    metrics = tuple(outcome.metric for outcome in ordered_outcomes)
    structured_errors = tuple(
        outcome.structured_error
        for outcome in ordered_outcomes
        if outcome.structured_error is not None
    )
    summary = _build_live_concurrency_diagnostics_summary(
        run_id=run_id,
        diagnostic_kind=resolved_kind,
        model_id=model_id,
        model_key=model_key,
        request_count=len(request_specs),
        app_concurrency=resolved_app_concurrency,
        loaded_parallel=resolved_loaded_parallel,
        queue_pressure_mode=queue_pressure_mode,
        request_specs=request_specs,
        metrics=metrics,
        structured_errors=structured_errors,
        total_wall_time_ms=total_wall_time_ms,
        max_tokens_override=resolved_max_tokens_override,
    )
    return LiveConcurrencyDiagnosticsOutcome(
        metrics=metrics,
        structured_errors=structured_errors,
        summary=summary,
    )


__all__ = [
    "CHUNKED_WARMUP_POLICY_CHOICES",
    "EFFECTIVE_PROFILE_CHOICES",
    "STRUCTURED_PROMPT_VARIANT_CHOICES",
    "STRUCTURED_REASONING_CONTROL_CHOICES",
    "LiveConcurrencyDiagnosticsOutcome",
    "LiveChunkedSmokeOutcome",
    "LivePromptMetadata",
    "LiveSmokeOutcome",
    "LiveTransport",
    "build_factual_blocks_response_format",
    "build_live_structured_messages",
    "run_live_concurrency_diagnostics",
    "run_live_chunked_structured_smoke",
    "run_live_structured_smoke",
]
