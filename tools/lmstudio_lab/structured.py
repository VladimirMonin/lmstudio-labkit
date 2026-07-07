"""Offline structured validation helpers for LM Studio Lab.

In offline Lab v1, ``schema_pass`` means minimal schema-shape validation, not
full JSON Schema Draft validation. Full JSON Schema validation can be added
later as an optional adapter.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Any

import yaml

from .metrics import SCHEMA_VERSION, ValidationMetrics

FACTUAL_BLOCKS_SCHEMA_NAME = "factual_blocks.v1"
SCHEMA_PASS_MEANING = "minimal schema-shape validation, not full JSON Schema Draft validation"
STRUCTURED_FIXTURE_MANIFEST_NAME = "manifest.yaml"
_REASONING_MARKERS = ("<think", "</think>")
_FACTUAL_BLOCKS_ROOT_KEYS = frozenset({"schema_version", "status", "blocks", "warnings"})
_FACTUAL_BLOCK_KEYS = frozenset({"block_id", "normalized_text", "status", "warnings"})
_MAX_REORDERED_POSITIONS = 50


def default_structured_fixtures_root() -> Path:
    return (
        Path(__file__).resolve().parents[2] / "experiments" / "lmstudio" / "fixtures" / "structured"
    )


def _normalize_reasoning_key(key: str) -> str:
    return "".join(character for character in key.casefold() if character.isalnum())


def _require_int_sequence(value: Sequence[int], *, field_name: str) -> tuple[int, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} must be a non-empty sequence of integers")

    normalized = tuple(value)
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty sequence of integers")

    for item in normalized:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{field_name} must contain integers only")

    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicate ids")

    return normalized


def _validate_retry_count(retry_count: int | None) -> int | None:
    if retry_count is None:
        return None
    if isinstance(retry_count, bool) or not isinstance(retry_count, int):
        raise ValueError("retry_count must be an integer")
    if retry_count < 0:
        raise ValueError("retry_count must be >= 0")
    return retry_count


def _validate_finish_reason(finish_reason: str | None) -> str | None:
    if finish_reason is None:
        return None
    if not isinstance(finish_reason, str):
        raise ValueError("finish_reason must be a string")
    return finish_reason


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _validate_fixture_file_name(file_name: str, *, field_name: str) -> str:
    path = Path(file_name)
    if (
        path.is_absolute()
        or path.name != file_name
        or len(path.parts) != 1
        or "/" in file_name
        or "\\" in file_name
        or file_name in {".", ".."}
    ):
        raise ValueError(f"{field_name} must be a simple relative file name")
    return file_name


def _contains_reasoning_markers(text: str) -> bool:
    normalized = text.casefold()
    return any(marker in normalized for marker in _REASONING_MARKERS)


def _contains_reasoning_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and _normalize_reasoning_key(key).startswith("reasoning"):
                return True
            if _contains_reasoning_key(nested):
                return True
        return False

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_reasoning_key(item) for item in value)

    return False


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _build_id_diagnostics(
    *,
    expected_ids: Sequence[int],
    returned_ids: Sequence[int],
) -> dict[str, Any]:
    expected_tuple = tuple(expected_ids)
    returned_tuple = tuple(returned_ids)

    duplicate_counts: dict[int, int] = {}
    for block_id in returned_tuple:
        duplicate_counts[block_id] = duplicate_counts.get(block_id, 0) + 1
    duplicate_ids = tuple(
        sorted(block_id for block_id, count in duplicate_counts.items() if count > 1)
    )

    expected_id_set = set(expected_tuple)
    returned_id_set = set(returned_tuple)
    missing_ids = tuple(block_id for block_id in expected_tuple if block_id not in returned_id_set)
    extra_ids = tuple(block_id for block_id in returned_tuple if block_id not in expected_id_set)

    reordered_positions: list[dict[str, int | None]] = []
    reordered_count = 0
    for position, (expected_id, returned_id) in enumerate(
        zip_longest(expected_tuple, returned_tuple, fillvalue=None)
    ):
        if expected_id == returned_id:
            continue
        reordered_count += 1
        if len(reordered_positions) >= _MAX_REORDERED_POSITIONS:
            continue
        reordered_positions.append(
            {
                "position": position,
                "expected_id": expected_id,
                "returned_id": returned_id,
            }
        )

    return {
        "expected_ids": expected_tuple,
        "returned_ids": returned_tuple,
        "duplicate_ids": duplicate_ids,
        "missing_ids": missing_ids,
        "extra_ids": extra_ids,
        "reordered_positions": tuple(reordered_positions),
        "reordered_count": reordered_count,
        "reordered_positions_truncated": reordered_count > len(reordered_positions),
    }


def _validate_factual_blocks_schema(
    payload: Any,
) -> tuple[bool, dict[str, Any] | None, int | None]:
    if not isinstance(payload, dict):
        return False, None, None
    if set(payload) != _FACTUAL_BLOCKS_ROOT_KEYS or len(payload) != len(_FACTUAL_BLOCKS_ROOT_KEYS):
        return False, None, None

    schema_version = payload.get("schema_version")
    status = payload.get("status")
    blocks = payload.get("blocks")
    warnings = payload.get("warnings")
    if (
        not isinstance(schema_version, str)
        or not isinstance(status, str)
        or not isinstance(blocks, list)
        or not _is_string_list(warnings)
    ):
        return False, None, None

    normalized_blocks: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            return False, None, len(blocks)
        if set(block) != _FACTUAL_BLOCK_KEYS or len(block) != len(_FACTUAL_BLOCK_KEYS):
            return False, None, len(blocks)

        block_id = block.get("block_id")
        if isinstance(block_id, bool) or not isinstance(block_id, int):
            return False, None, len(blocks)

        normalized_text = block.get("normalized_text")
        block_status = block.get("status")
        block_warnings = block.get("warnings")
        if (
            not isinstance(normalized_text, str)
            or not isinstance(block_status, str)
            or not _is_string_list(block_warnings)
        ):
            return False, None, len(blocks)

        normalized_blocks.append(
            {
                "block_id": block_id,
                "normalized_text": normalized_text,
                "status": block_status,
                "warnings": list(block_warnings),
            }
        )

    return (
        True,
        {
            "schema_version": schema_version,
            "status": status,
            "blocks": normalized_blocks,
            "warnings": list(warnings),
        },
        len(blocks),
    )


@dataclass(frozen=True, slots=True)
class StructuredValidationResult:
    schema_name: str
    json_parse_pass: bool
    schema_pass: bool
    business_pass: bool
    ids_exact_pass: bool | None
    no_duplicate_ids: bool | None
    order_preserved: bool | None
    non_empty_text_pass: bool | None
    reasoning_leak: bool
    retry_count: int | None
    finish_reason: str | None
    expected_count: int
    returned_count: int | None
    error_category: str | None
    expected_ids: tuple[int, ...] | None = None
    returned_ids: tuple[int, ...] | None = None
    duplicate_ids: tuple[int, ...] | None = None
    missing_ids: tuple[int, ...] | None = None
    extra_ids: tuple[int, ...] | None = None
    reordered_positions: tuple[dict[str, int | None], ...] | None = None
    reordered_count: int | None = None
    reordered_positions_truncated: bool | None = None

    def to_metrics(self) -> ValidationMetrics:
        return ValidationMetrics(
            json_parse_pass=self.json_parse_pass,
            schema_pass=self.schema_pass,
            business_pass=self.business_pass,
            ids_exact_pass=self.ids_exact_pass,
            no_duplicate_ids=self.no_duplicate_ids,
            order_preserved=self.order_preserved,
            non_empty_text_pass=self.non_empty_text_pass,
            reasoning_leak=self.reasoning_leak,
            retry_count=self.retry_count,
            finish_reason=self.finish_reason,
            expected_count=self.expected_count,
            returned_count=self.returned_count,
            expected_ids=self.expected_ids,
            returned_ids=self.returned_ids,
            duplicate_ids=self.duplicate_ids,
            missing_ids=self.missing_ids,
            extra_ids=self.extra_ids,
            reordered_positions=self.reordered_positions,
            reordered_count=self.reordered_count,
            reordered_positions_truncated=self.reordered_positions_truncated,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "schema_name": self.schema_name,
            "json_parse_pass": self.json_parse_pass,
            "schema_pass": self.schema_pass,
            "business_pass": self.business_pass,
            "ids_exact_pass": self.ids_exact_pass,
            "no_duplicate_ids": self.no_duplicate_ids,
            "order_preserved": self.order_preserved,
            "non_empty_text_pass": self.non_empty_text_pass,
            "reasoning_leak": self.reasoning_leak,
            "retry_count": self.retry_count,
            "finish_reason": self.finish_reason,
            "expected_count": self.expected_count,
            "returned_count": self.returned_count,
            "error_category": self.error_category,
            "expected_ids": list(self.expected_ids) if self.expected_ids is not None else None,
            "returned_ids": list(self.returned_ids) if self.returned_ids is not None else None,
            "duplicate_ids": list(self.duplicate_ids) if self.duplicate_ids is not None else None,
            "missing_ids": list(self.missing_ids) if self.missing_ids is not None else None,
            "extra_ids": list(self.extra_ids) if self.extra_ids is not None else None,
            "reordered_positions": (
                [dict(item) for item in self.reordered_positions]
                if self.reordered_positions is not None
                else None
            ),
            "reordered_count": self.reordered_count,
            "reordered_positions_truncated": self.reordered_positions_truncated,
        }


def _rate(count: int, total: int) -> float | None:
    if total == 0:
        return None
    return count / total


@dataclass(frozen=True, slots=True)
class StructuredValidationSummary:
    total_count: int
    json_parse_pass_count: int
    json_parse_pass_rate: float | None
    schema_pass_count: int
    schema_pass_rate: float | None
    business_pass_count: int
    business_pass_rate: float | None
    ids_exact_pass_count: int
    ids_exact_pass_rate: float | None
    reasoning_leak_count: int
    finish_length_count: int
    duplicate_id_count: int
    empty_text_count: int
    invalid_json_count: int
    schema_error_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "total_count": self.total_count,
            "json_parse_pass_count": self.json_parse_pass_count,
            "json_parse_pass_rate": self.json_parse_pass_rate,
            "schema_pass_count": self.schema_pass_count,
            "schema_pass_rate": self.schema_pass_rate,
            "business_pass_count": self.business_pass_count,
            "business_pass_rate": self.business_pass_rate,
            "ids_exact_pass_count": self.ids_exact_pass_count,
            "ids_exact_pass_rate": self.ids_exact_pass_rate,
            "reasoning_leak_count": self.reasoning_leak_count,
            "finish_length_count": self.finish_length_count,
            "duplicate_id_count": self.duplicate_id_count,
            "empty_text_count": self.empty_text_count,
            "invalid_json_count": self.invalid_json_count,
            "schema_error_count": self.schema_error_count,
        }


@dataclass(frozen=True, slots=True)
class StructuredFixtureCase:
    fixture_id: str
    file_name: str
    expected_block_ids: tuple[int, ...]
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StructuredFixtureManifest:
    fixture_set_id: str
    schema_name: str
    cases: tuple[StructuredFixtureCase, ...]


@dataclass(frozen=True, slots=True)
class StructuredFixtureValidationBatch:
    manifest: StructuredFixtureManifest
    results: tuple[StructuredValidationResult, ...]
    records: tuple[dict[str, Any], ...]

    def summarize(self) -> StructuredValidationSummary:
        return summarize_structured_validation_results(self.results)


def load_structured_fixture_manifest(
    fixtures_root: str | Path | None = None,
) -> StructuredFixtureManifest:
    root = Path(fixtures_root) if fixtures_root is not None else default_structured_fixtures_root()
    manifest_path = root / STRUCTURED_FIXTURE_MANIFEST_NAME
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("structured fixture manifest must be a mapping")

    fixture_set_id = _require_non_empty_string(
        payload.get("fixture_set_id"),
        field_name="fixture_set_id",
    )
    schema_name = _require_non_empty_string(
        payload.get("schema_name"),
        field_name="schema_name",
    )
    if schema_name != FACTUAL_BLOCKS_SCHEMA_NAME:
        raise ValueError(
            f"schema_name must be {FACTUAL_BLOCKS_SCHEMA_NAME!r} for structured fixture validation"
        )

    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("cases must be a non-empty list")

    seen_fixture_ids: set[str] = set()
    cases: list[StructuredFixtureCase] = []
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, Mapping):
            raise ValueError(f"cases[{index}] must be a mapping")

        fixture_id = _require_non_empty_string(
            raw_case.get("fixture_id"),
            field_name=f"cases[{index}].fixture_id",
        )
        if fixture_id in seen_fixture_ids:
            raise ValueError(f"duplicate fixture_id: {fixture_id}")
        seen_fixture_ids.add(fixture_id)

        file_name = _validate_fixture_file_name(
            _require_non_empty_string(
                raw_case.get("file_name"),
                field_name=f"cases[{index}].file_name",
            ),
            field_name=f"cases[{index}].file_name",
        )
        expected_block_ids = _require_int_sequence(
            raw_case.get("expected_block_ids"),
            field_name=f"cases[{index}].expected_block_ids",
        )
        finish_reason = _validate_finish_reason(raw_case.get("finish_reason"))
        cases.append(
            StructuredFixtureCase(
                fixture_id=fixture_id,
                file_name=file_name,
                expected_block_ids=expected_block_ids,
                finish_reason=finish_reason,
            )
        )

    return StructuredFixtureManifest(
        fixture_set_id=fixture_set_id,
        schema_name=schema_name,
        cases=tuple(cases),
    )


def _build_structured_fixture_validation_record(
    *,
    manifest: StructuredFixtureManifest,
    case: StructuredFixtureCase,
    result: StructuredValidationResult,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "fixture_set_id": manifest.fixture_set_id,
        "fixture_id": case.fixture_id,
        "schema_name": manifest.schema_name,
        **result.to_dict(),
    }


def summarize_structured_validation_results(
    results: Sequence[StructuredValidationResult],
) -> StructuredValidationSummary:
    total_count = len(results)
    json_parse_pass_count = sum(result.json_parse_pass for result in results)
    schema_pass_count = sum(result.schema_pass for result in results)
    business_pass_count = sum(result.business_pass for result in results)
    ids_exact_pass_count = sum(result.ids_exact_pass is True for result in results)
    reasoning_leak_count = sum(result.reasoning_leak for result in results)
    finish_length_count = sum(result.finish_reason == "length" for result in results)
    duplicate_id_count = sum(result.no_duplicate_ids is False for result in results)
    empty_text_count = sum(result.non_empty_text_pass is False for result in results)
    invalid_json_count = sum(result.error_category == "invalid_json" for result in results)
    schema_error_count = sum(result.error_category == "schema" for result in results)

    return StructuredValidationSummary(
        total_count=total_count,
        json_parse_pass_count=json_parse_pass_count,
        json_parse_pass_rate=_rate(json_parse_pass_count, total_count),
        schema_pass_count=schema_pass_count,
        schema_pass_rate=_rate(schema_pass_count, total_count),
        business_pass_count=business_pass_count,
        business_pass_rate=_rate(business_pass_count, total_count),
        ids_exact_pass_count=ids_exact_pass_count,
        ids_exact_pass_rate=_rate(ids_exact_pass_count, total_count),
        reasoning_leak_count=reasoning_leak_count,
        finish_length_count=finish_length_count,
        duplicate_id_count=duplicate_id_count,
        empty_text_count=empty_text_count,
        invalid_json_count=invalid_json_count,
        schema_error_count=schema_error_count,
    )


def validate_structured_fixture_manifest(
    fixtures_root: str | Path | None = None,
) -> StructuredFixtureValidationBatch:
    root = Path(fixtures_root) if fixtures_root is not None else default_structured_fixtures_root()
    manifest = load_structured_fixture_manifest(root)
    results: list[StructuredValidationResult] = []
    records: list[dict[str, Any]] = []

    for case in manifest.cases:
        fixture_text = (root / case.file_name).read_text(encoding="utf-8")
        result = validate_factual_blocks_response(
            fixture_text,
            expected_block_ids=case.expected_block_ids,
            finish_reason=case.finish_reason,
        )
        results.append(result)
        records.append(
            _build_structured_fixture_validation_record(
                manifest=manifest,
                case=case,
                result=result,
            )
        )

    return StructuredFixtureValidationBatch(
        manifest=manifest,
        results=tuple(results),
        records=tuple(records),
    )


def validate_factual_blocks_response(
    response_text: str,
    *,
    expected_block_ids: Sequence[int],
    finish_reason: str | None = None,
    retry_count: int | None = None,
) -> StructuredValidationResult:
    if not isinstance(response_text, str):
        raise ValueError("response_text must be a string")

    expected_ids = _require_int_sequence(
        expected_block_ids,
        field_name="expected_block_ids",
    )
    validated_retry_count = _validate_retry_count(retry_count)
    validated_finish_reason = _validate_finish_reason(finish_reason)

    reasoning_leak = _contains_reasoning_markers(response_text)

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return StructuredValidationResult(
            schema_name=FACTUAL_BLOCKS_SCHEMA_NAME,
            json_parse_pass=False,
            schema_pass=False,
            business_pass=False,
            ids_exact_pass=None,
            no_duplicate_ids=None,
            order_preserved=None,
            non_empty_text_pass=None,
            reasoning_leak=reasoning_leak,
            retry_count=validated_retry_count,
            finish_reason=validated_finish_reason,
            expected_count=len(expected_ids),
            returned_count=None,
            error_category="reasoning_leak" if reasoning_leak else "invalid_json",
        )

    reasoning_leak = reasoning_leak or _contains_reasoning_key(payload)
    schema_pass, blocks, returned_count = _validate_factual_blocks_schema(payload)
    if not schema_pass:
        return StructuredValidationResult(
            schema_name=FACTUAL_BLOCKS_SCHEMA_NAME,
            json_parse_pass=True,
            schema_pass=False,
            business_pass=False,
            ids_exact_pass=None,
            no_duplicate_ids=None,
            order_preserved=None,
            non_empty_text_pass=None,
            reasoning_leak=reasoning_leak,
            retry_count=validated_retry_count,
            finish_reason=validated_finish_reason,
            expected_count=len(expected_ids),
            returned_count=returned_count,
            error_category="reasoning_leak" if reasoning_leak else "schema",
        )

    assert blocks is not None
    schema_version_pass = blocks["schema_version"] == FACTUAL_BLOCKS_SCHEMA_NAME
    top_level_status_pass = blocks["status"] == "success"
    reasoning_leak = reasoning_leak or any(
        _contains_reasoning_markers(block["normalized_text"]) for block in blocks["blocks"]
    )
    block_statuses_pass = all(block["status"] == "success" for block in blocks["blocks"])

    returned_ids = [block["block_id"] for block in blocks["blocks"]]
    id_diagnostics = _build_id_diagnostics(expected_ids=expected_ids, returned_ids=returned_ids)
    ids_exact_pass = set(returned_ids) == set(expected_ids) and len(returned_ids) == len(
        expected_ids
    )
    no_duplicate_ids = len(set(returned_ids)) == len(returned_ids)
    order_preserved = returned_ids == list(expected_ids)
    non_empty_text_pass = all(block["normalized_text"].strip() for block in blocks["blocks"])

    business_pass = (
        schema_pass
        and schema_version_pass
        and top_level_status_pass
        and block_statuses_pass
        and ids_exact_pass
        and no_duplicate_ids
        and order_preserved
        and non_empty_text_pass
        and not reasoning_leak
        and validated_finish_reason != "length"
    )

    error_category: str | None = None
    if reasoning_leak:
        error_category = "reasoning_leak"
    elif not schema_version_pass:
        error_category = "schema_version"
    elif not top_level_status_pass or not block_statuses_pass:
        error_category = "status"
    elif not ids_exact_pass or not no_duplicate_ids or not order_preserved:
        error_category = "ids"
    elif not non_empty_text_pass:
        error_category = "empty_text"
    elif validated_finish_reason == "length":
        error_category = "finish_length"

    return StructuredValidationResult(
        schema_name=FACTUAL_BLOCKS_SCHEMA_NAME,
        json_parse_pass=True,
        schema_pass=True,
        business_pass=business_pass,
        ids_exact_pass=ids_exact_pass,
        no_duplicate_ids=no_duplicate_ids,
        order_preserved=order_preserved,
        non_empty_text_pass=non_empty_text_pass,
        reasoning_leak=reasoning_leak,
        retry_count=validated_retry_count,
        finish_reason=validated_finish_reason,
        expected_count=len(expected_ids),
        returned_count=len(blocks["blocks"]),
        error_category=error_category,
        expected_ids=id_diagnostics["expected_ids"],
        returned_ids=id_diagnostics["returned_ids"],
        duplicate_ids=id_diagnostics["duplicate_ids"],
        missing_ids=id_diagnostics["missing_ids"],
        extra_ids=id_diagnostics["extra_ids"],
        reordered_positions=id_diagnostics["reordered_positions"],
        reordered_count=id_diagnostics["reordered_count"],
        reordered_positions_truncated=id_diagnostics["reordered_positions_truncated"],
    )


__all__ = [
    "FACTUAL_BLOCKS_SCHEMA_NAME",
    "SCHEMA_PASS_MEANING",
    "STRUCTURED_FIXTURE_MANIFEST_NAME",
    "StructuredFixtureCase",
    "StructuredFixtureManifest",
    "StructuredFixtureValidationBatch",
    "StructuredValidationResult",
    "StructuredValidationSummary",
    "default_structured_fixtures_root",
    "load_structured_fixture_manifest",
    "summarize_structured_validation_results",
    "validate_structured_fixture_manifest",
    "validate_factual_blocks_response",
]
