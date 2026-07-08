from __future__ import annotations

import json
import re
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


def validate_response(raw_response: str, contract: ResponseContract) -> ValidationSummary:
    parsed: Any | None = None
    results: list[ValidationResult] = []

    if contract.mode == "json":
        try:
            parsed = json.loads(raw_response)
            results.append(ValidationResult("json_parse", "pass"))
        except json.JSONDecodeError:
            results.append(ValidationResult("json_parse", "fail", "invalid_json"))
            return ValidationSummary("fail", tuple(results))

        if contract.schema is not None:
            schema_result = validate_json_schema(parsed, contract.schema)
            results.append(schema_result)
        else:
            results.append(ValidationResult("json_schema", "skip"))

        if contract.expected_ids:
            results.append(validate_exact_ids(parsed, contract.expected_ids))
        else:
            results.append(ValidationResult("id_exact", "skip"))

        results.append(validate_no_placeholder_text(parsed))

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
        if contract.language:
            results.append(validate_language(raw_response, contract.language))

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
        return ValidationResult("json_schema", "fail", "schema_error", {"error_count": len(errors)})
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
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}:required")
        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                errors.extend(_schema_errors(value[key], child_schema, f"{path}.{key}"))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
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


def validate_exact_ids(value: Any, expected_ids: tuple[str, ...]) -> ValidationResult:
    seen = _collect_ids(value)
    expected = list(expected_ids)
    missing = [item for item in expected if item not in seen]
    unexpected = [item for item in seen if item not in expected]
    duplicate_count = len(seen) - len(set(seen))
    metrics = {
        "expected_count": len(expected),
        "seen_count": len(seen),
        "missing_count": len(missing),
        "unexpected_count": len(unexpected),
        "duplicate_count": duplicate_count,
    }
    if missing or unexpected or duplicate_count:
        return ValidationResult("id_exact", "fail", "id_mismatch", metrics)
    return ValidationResult("id_exact", "pass", metrics=metrics)


def _collect_ids(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        if "id" in value and isinstance(value["id"], str):
            ids.append(value["id"])
        for child in value.values():
            ids.extend(_collect_ids(child))
    elif isinstance(value, list):
        for child in value:
            ids.extend(_collect_ids(child))
    return ids


def validate_no_placeholder_text(value: Any) -> ValidationResult:
    text = _flatten_text(value).lower()
    markers = ("todo", "lorem ipsum", "placeholder", "your text here")
    hit_count = sum(text.count(marker) for marker in markers)
    if hit_count:
        return ValidationResult(
            "no_placeholder_text", "fail", "placeholder_text", {"hit_count": hit_count}
        )
    return ValidationResult("no_placeholder_text", "pass", metrics={"hit_count": 0})


def validate_language(value: Any, language: str) -> ValidationResult:
    text = _flatten_text(value)
    cyr = len(re.findall(r"[А-Яа-яЁё]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    status: ValidationStatus = "pass"
    category = None
    if language == "ru_ru" and cyr == 0:
        status, category = "fail", "language_mismatch"
    elif language == "en_en" and lat == 0:
        status, category = "fail", "language_mismatch"
    elif language == "en_ru" and cyr == 0:
        status, category = "fail", "language_mismatch"
    elif language == "ru_en_mixed" and cyr == 0 and lat == 0:
        status, category = "fail", "language_mismatch"
    return ValidationResult(
        "language_compliance",
        status,
        category,
        {"cyrillic_chars": cyr, "latin_chars": lat},
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
