from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from .requests import ResponseContract

ValidationStatus = Literal["pass", "fail", "skip"]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    name: str
    status: ValidationStatus
    category: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    status: ValidationStatus
    results: tuple[ValidationResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "results": [
                {
                    "name": item.name,
                    "status": item.status,
                    "category": item.category,
                    "metrics": item.metrics,
                }
                for item in self.results
            ],
        }


def validate_response(
    raw_response: str,
    contract: ResponseContract,
    *,
    finish_reason: str | None = None,
    input_char_count: int | None = None,
) -> ValidationSummary:
    parsed: Any | None = None
    results: list[ValidationResult] = []

    results.append(validate_finish_reason(finish_reason))
    results.append(validate_markdown_fence_leak(raw_response))

    if contract.mode == "json":
        try:
            parsed = json.loads(raw_response)
            results.append(ValidationResult("json_parse", "pass"))
        except json.JSONDecodeError:
            results.append(ValidationResult("json_parse", "fail", "invalid_json"))
            return ValidationSummary("fail", tuple(results))

        if contract.schema is not None:
            results.append(validate_json_schema(parsed, contract.schema))
        else:
            results.append(ValidationResult("json_schema", "skip"))

        if contract.expected_ids:
            results.append(
                validate_exact_ids(
                    parsed,
                    contract.expected_ids,
                    id_paths=contract.id_paths,
                    id_field_names=contract.id_field_names,
                    preserve_order=contract.preserve_order,
                )
            )
        else:
            results.append(ValidationResult("id_exact", "skip"))

        results.append(validate_no_placeholder_text(parsed))
        results.append(validate_no_reasoning_leak(parsed))
        if contract.language:
            results.append(validate_language(parsed, contract.language))
        else:
            results.append(ValidationResult("language_compliance", "skip"))

        if contract.image_ground_truth is not None:
            results.append(validate_image_ground_truth(parsed, contract.image_ground_truth))
        else:
            results.append(ValidationResult("image_ground_truth", "skip"))
    else:
        results.append(ValidationResult("json_parse", "skip"))
        results.append(validate_no_placeholder_text(raw_response))
        results.append(validate_no_reasoning_leak(raw_response))
        if contract.language:
            results.append(validate_language(raw_response, contract.language))
        else:
            results.append(ValidationResult("language_compliance", "skip"))

    if input_char_count is not None:
        results.append(validate_empty_text_for_non_empty_input(raw_response, input_char_count))
    else:
        results.append(ValidationResult("empty_text_for_non_empty_input", "skip"))

    if contract.min_length_ratio is not None or contract.max_length_ratio is not None:
        results.append(
            validate_length_ratio(
                raw_response,
                contract.expected_output,
                contract.min_length_ratio,
                contract.max_length_ratio,
            )
        )
    else:
        results.append(ValidationResult("length_ratio", "skip"))

    status: ValidationStatus = "pass"
    if any(item.status == "fail" for item in results):
        status = "fail"
    return ValidationSummary(status, tuple(results))


def validate_json_schema(value: Any, schema: dict[str, Any]) -> ValidationResult:
    errors = _schema_errors(value, schema)
    if errors:
        return ValidationResult(
            "json_schema",
            "fail",
            "schema_error",
            {"error_count": len(errors), "first_error": errors[0]},
        )
    return ValidationResult("json_schema", "pass", metrics={"error_count": 0})


def _schema_errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type and not _matches_type(value, expected_type):
        return [f"{path}:type"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}:const")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}:enum")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if min_length is not None and len(value) < int(min_length):
            errors.append(f"{path}:minLength")
        if max_length is not None and len(value) > int(max_length):
            errors.append(f"{path}:maxLength")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(str(pattern), value) is None:
            errors.append(f"{path}:pattern")

    if isinstance(value, int | float) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}:minimum")
        if maximum is not None and value > maximum:
            errors.append(f"{path}:maximum")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}:required")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, dict):
                    errors.extend(_schema_errors(value[key], child_schema, f"{path}.{key}"))
        if schema.get("additionalProperties") is False and isinstance(properties, dict):
            extra = sorted(set(value) - set(properties))
            errors.extend(f"{path}.{key}:additionalProperties" for key in extra)

    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(value) < int(min_items):
            errors.append(f"{path}:minItems")
        if max_items is not None and len(value) > int(max_items):
            errors.append(f"{path}:maxItems")
        if schema.get("uniqueItems") is True:
            serialized_items = [
                json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value
            ]
            if len(serialized_items) != len(set(serialized_items)):
                errors.append(f"{path}:uniqueItems")
        prefix_items = schema.get("prefixItems")
        if isinstance(prefix_items, list):
            for index, child_schema in enumerate(prefix_items):
                if index >= len(value):
                    errors.append(f"{path}[{index}]:prefixItems_missing")
                elif isinstance(child_schema, dict):
                    errors.extend(_schema_errors(value[index], child_schema, f"{path}[{index}]"))
        if isinstance(schema.get("items"), dict):
            start = len(prefix_items) if isinstance(prefix_items, list) else 0
            for index, item in enumerate(value[start:], start=start):
                errors.extend(_schema_errors(item, schema["items"], f"{path}[{index}]"))
    return errors


def _matches_type(value: Any, expected_type: str | list[str]) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_type(value, item) for item in expected_type)
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected_type, True)


def validate_exact_ids(
    value: Any,
    expected_ids: tuple[Any, ...],
    *,
    id_paths: tuple[str, ...] = (),
    id_field_names: tuple[str, ...] = ("id",),
    preserve_order: bool = True,
) -> ValidationResult:
    seen = _collect_ids_for_contract(value, id_paths, id_field_names)
    expected = [_normalize_id(item) for item in expected_ids]
    missing = [item for item in expected if item not in seen]
    unexpected = [item for item in seen if item not in expected]
    duplicate_count = sum(count - 1 for count in Counter(seen).values() if count > 1)
    first_mismatch_index: int | None = None
    if preserve_order:
        for index, expected_id in enumerate(expected):
            if index >= len(seen) or seen[index] != expected_id:
                first_mismatch_index = index
                break
        if first_mismatch_index is None and len(seen) != len(expected):
            first_mismatch_index = min(len(seen), len(expected))
    order_mismatch = first_mismatch_index is not None
    metrics = {
        "expected_count": len(expected),
        "seen_count": len(seen),
        "missing_count": len(missing),
        "unexpected_count": len(unexpected),
        "duplicate_count": duplicate_count,
        "order_mismatch": order_mismatch,
        "first_mismatch_index": first_mismatch_index,
    }
    if missing or unexpected or duplicate_count or order_mismatch:
        category = "id_order_mismatch" if order_mismatch else "id_mismatch"
        return ValidationResult("id_exact", "fail", category, metrics)
    return ValidationResult("id_exact", "pass", metrics=metrics)


def collect_ids_by_path(value: Any, path: str = "blocks[*].id") -> list[str]:
    ids: list[str] = []
    for item in _values_by_path(value, _parse_id_path(path)):
        if isinstance(item, str | int) and not isinstance(item, bool):
            ids.append(_normalize_id(item))
    return ids


def _collect_ids_for_contract(
    value: Any, id_paths: tuple[str, ...], id_field_names: tuple[str, ...]
) -> list[str]:
    if id_paths:
        ids: list[str] = []
        for path in id_paths:
            ids.extend(collect_ids_by_path(value, path))
        return ids
    return _collect_ids(value, id_field_names)


def _collect_ids(value: Any, id_field_names: tuple[str, ...]) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        for field_name in id_field_names:
            if (
                field_name in value
                and isinstance(value[field_name], str | int)
                and not isinstance(value[field_name], bool)
            ):
                ids.append(_normalize_id(value[field_name]))
        for child in value.values():
            ids.extend(_collect_ids(child, id_field_names))
    elif isinstance(value, list):
        for child in value:
            ids.extend(_collect_ids(child, id_field_names))
    return ids


def _parse_id_path(path: str) -> tuple[str, ...]:
    if not path or path.startswith(".") or path.endswith(".") or ".." in path:
        raise ValueError("id path must be a dotted path such as blocks[*].id")
    return tuple(path.split("."))


def _values_by_path(value: Any, segments: tuple[str, ...]) -> list[Any]:
    if not segments:
        return [value]
    head, *tail = segments
    child_segments = tuple(tail)
    if head.endswith("[*]"):
        key = head[:-3]
        if not isinstance(value, dict):
            return []
        child = value.get(key)
        if not isinstance(child, list):
            return []
        matches: list[Any] = []
        for item in child:
            matches.extend(_values_by_path(item, child_segments))
        return matches
    if isinstance(value, dict) and head in value:
        return _values_by_path(value[head], child_segments)
    return []


def _normalize_id(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return value
    return str(value)


def validate_no_placeholder_text(value: Any) -> ValidationResult:
    text = _flatten_text(value).lower()
    markers = ("todo", "lorem ipsum", "placeholder", "your text here", "tbd")
    hit_count = sum(text.count(marker) for marker in markers)
    if hit_count:
        return ValidationResult(
            "no_placeholder_text", "fail", "placeholder_text", {"hit_count": hit_count}
        )
    return ValidationResult("no_placeholder_text", "pass", metrics={"hit_count": 0})


def validate_no_reasoning_leak(value: Any) -> ValidationResult:
    text = _flatten_text(value).casefold()
    marker_leak = "<think" in text or "chain of thought" in text
    key_leak = _contains_reasoning_key(value)
    if marker_leak or key_leak:
        return ValidationResult(
            "no_reasoning_leak",
            "fail",
            "reasoning_leak",
            {"marker_leak": marker_leak, "key_leak": key_leak},
        )
    return ValidationResult(
        "no_reasoning_leak",
        "pass",
        metrics={"marker_leak": False, "key_leak": False},
    )


def _contains_reasoning_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = "".join(
                character for character in str(key).casefold() if character.isalnum()
            )
            if normalized.startswith("reasoning") or normalized in {"chainofthought", "cot"}:
                return True
            if _contains_reasoning_key(child):
                return True
    if isinstance(value, list | tuple):
        return any(_contains_reasoning_key(child) for child in value)
    return False


def validate_markdown_fence_leak(raw_response: str) -> ValidationResult:
    fence_count = raw_response.count("```")
    if fence_count:
        return ValidationResult(
            "markdown_fence_leak", "fail", "markdown_fence", {"fence_count": fence_count}
        )
    return ValidationResult("markdown_fence_leak", "pass", metrics={"fence_count": 0})


def validate_empty_text_for_non_empty_input(
    raw_response: str, input_char_count: int
) -> ValidationResult:
    is_empty = not raw_response.strip()
    if input_char_count > 0 and is_empty:
        return ValidationResult("empty_text_for_non_empty_input", "fail", "empty_output")
    return ValidationResult("empty_text_for_non_empty_input", "pass")


def validate_finish_reason(finish_reason: str | None) -> ValidationResult:
    if finish_reason is None:
        return ValidationResult("finish_reason_length", "skip")
    if finish_reason == "length":
        return ValidationResult("finish_reason_length", "fail", "finish_length")
    return ValidationResult(
        "finish_reason_length", "pass", metrics={"finish_reason": finish_reason}
    )


def validate_language(value: Any, language: str) -> ValidationResult:
    text = _flatten_text(value)
    cyr = len(re.findall(r"[А-Яа-яЁё]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    total_letters = max(1, cyr + lat)
    cyr_ratio = cyr / total_letters
    lat_ratio = lat / total_letters
    status: ValidationStatus = "pass"
    category = None
    if language == "ru_ru" and cyr_ratio < 0.5:
        status, category = "fail", "language_mismatch"
    elif language == "en_en" and lat_ratio < 0.5:
        status, category = "fail", "language_mismatch"
    elif language == "en_ru" and cyr == 0:
        status, category = "fail", "language_mismatch"
    elif language == "ru_en_mixed" and (cyr == 0 or lat == 0):
        status, category = "fail", "language_mismatch"
    return ValidationResult(
        "language_compliance",
        status,
        category,
        {"cyrillic_chars": cyr, "latin_chars": lat, "cyrillic_ratio": round(cyr_ratio, 4)},
    )


def validate_length_ratio(
    raw_response: str,
    expected_output: Any,
    min_ratio: float | None,
    max_ratio: float | None,
) -> ValidationResult:
    baseline = max(1, len(_flatten_text(expected_output)))
    ratio = len(raw_response) / baseline
    status: ValidationStatus = "pass"
    category = None
    if min_ratio is not None and ratio < min_ratio:
        status, category = "fail", "too_short"
    if max_ratio is not None and ratio > max_ratio:
        status, category = "fail", "too_long"
    return ValidationResult("length_ratio", status, category, {"ratio": round(ratio, 4)})


def validate_image_ground_truth(value: Any, ground_truth: dict[str, Any]) -> ValidationResult:
    text = _flatten_text(value).lower()
    labels = [str(item).lower() for item in ground_truth.get("labels", [])]
    missing = [label for label in labels if label not in text]
    metrics = {"expected_label_count": len(labels), "missing_label_count": len(missing)}
    if missing:
        return ValidationResult(
            "image_ground_truth", "fail", "image_ground_truth_mismatch", metrics
        )
    return ValidationResult("image_ground_truth", "pass", metrics=metrics)


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list | tuple):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)
