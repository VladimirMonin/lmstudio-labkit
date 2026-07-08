from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from .requests import ResponseContract

ValidationStatus = Literal["pass", "fail", "warning", "skip"]


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
    input_text: str | None = None,
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
        results.append(
            validate_language(
                parsed,
                contract.language,
                policy=contract.language_policy,
                expected_hints=contract.expected_output,
                image_ground_truth=contract.image_ground_truth,
                include_paths=contract.language_include_paths,
                ignore_paths=contract.language_ignore_paths,
            )
        )

        results.extend(_postprocessing_validation_results(parsed, contract, input_text))

        if contract.image_ground_truth is not None:
            results.append(validate_image_ground_truth(parsed, contract.image_ground_truth))
        else:
            results.append(ValidationResult("image_ground_truth", "skip"))
    else:
        results.append(ValidationResult("json_parse", "skip"))
        results.append(validate_no_placeholder_text(raw_response))
        results.append(validate_no_reasoning_leak(raw_response))
        results.append(
            validate_language(
                raw_response,
                contract.language,
                policy=contract.language_policy,
                expected_hints=contract.expected_output,
                image_ground_truth=contract.image_ground_truth,
                include_paths=contract.language_include_paths,
                ignore_paths=contract.language_ignore_paths,
            )
        )

        results.extend(_postprocessing_validation_results(raw_response, contract, input_text))

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
                policy=str(contract.length_ratio_policy),
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


def validate_language(
    value: Any,
    language: str | None,
    *,
    policy: str | None = None,
    expected_hints: Any | None = None,
    image_ground_truth: dict[str, Any] | None = None,
    include_paths: tuple[str, ...] = (),
    ignore_paths: tuple[str, ...] = (),
) -> ValidationResult:
    resolved_policy = _resolve_language_policy(language, policy)
    if resolved_policy is None or resolved_policy == "skip":
        return ValidationResult("language_compliance", "skip")

    text = _flatten_language_text_by_policy(
        value, include_paths=include_paths, ignore_paths=ignore_paths
    )
    cyr = len(re.findall(r"[А-Яа-яЁё]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    total_letters = max(1, cyr + lat)
    cyr_ratio = cyr / total_letters
    lat_ratio = lat / total_letters
    metrics = {
        "policy": resolved_policy,
        "cyrillic_chars": cyr,
        "latin_chars": lat,
        "cyrillic_ratio": round(cyr_ratio, 4),
        "latin_ratio": round(lat_ratio, 4),
    }

    if resolved_policy == "labels_only":
        return _validate_language_labels_only(text, image_ground_truth, metrics)

    status: ValidationStatus = "pass"
    category = None
    if resolved_policy == "strict_ru" and cyr_ratio < 0.5:
        status, category = "fail", "language_mismatch"
    elif resolved_policy == "strict_en" and lat_ratio < 0.5:
        status, category = "fail", "language_mismatch"
    elif resolved_policy == "allow_code_terms" and (cyr == 0 or cyr_ratio < 0.15):
        status, category = "fail", "language_mismatch"
    elif (
        resolved_policy == "mixed_ru_en"
        and cyr == 0
        and not _has_explicit_mixed_hint(expected_hints)
    ):
        status, category = "fail", "language_mismatch"
    return ValidationResult("language_compliance", status, category, metrics)


def _resolve_language_policy(language: str | None, policy: str | None) -> str | None:
    if policy == "preserve_input_language":
        return {
            "ru_ru": "allow_code_terms",
            "ru_en_mixed": "mixed_ru_en",
            "en_ru": "mixed_ru_en",
            "en_en": "strict_en",
        }.get(language or "", "skip")
    if policy == "preserve_mixed_language":
        return "mixed_ru_en"
    if policy == "translate_to_ru":
        return "allow_code_terms"
    if policy == "translate_to_en":
        return "strict_en"
    if policy:
        return policy
    return {
        "ru_ru": "strict_ru",
        "en_en": "strict_en",
        "en_ru": "mixed_ru_en",
        "ru_en_mixed": "mixed_ru_en",
    }.get(language or "")


def _has_explicit_mixed_hint(expected_hints: Any | None) -> bool:
    hint_text = _flatten_language_text(expected_hints).casefold()
    if len(re.findall(r"[А-Яа-яЁё]", hint_text)) > 0:
        return True
    return any(
        marker in hint_text for marker in ("mixed", "ru_en", "ru-en", "ru+en", "russian", "рус")
    )


def _validate_language_labels_only(
    text: str,
    image_ground_truth: dict[str, Any] | None,
    metrics: dict[str, Any],
) -> ValidationResult:
    labels = [str(item).casefold() for item in (image_ground_truth or {}).get("labels", [])]
    lowered = text.casefold()
    missing = [label for label in labels if label not in lowered]
    label_metrics = {
        **metrics,
        "expected_label_count": len(labels),
        "missing_label_count": len(missing),
    }
    if missing:
        return ValidationResult(
            "language_compliance", "fail", "language_label_mismatch", label_metrics
        )
    return ValidationResult("language_compliance", "pass", metrics=label_metrics)


def validate_length_ratio(
    raw_response: str,
    expected_output: Any,
    min_ratio: float | None,
    max_ratio: float | None,
    *,
    policy: str = "hard",
) -> ValidationResult:
    normalized_policy = _normalize_length_ratio_policy(policy)
    baseline = max(1, len(_flatten_text(expected_output)))
    ratio = len(raw_response) / baseline
    metrics = {
        "ratio": round(ratio, 4),
        "policy": normalized_policy,
        "policy_min": min_ratio,
        "policy_max": max_ratio,
        "baseline_char_count": baseline,
        "response_char_count": len(raw_response),
    }
    if normalized_policy == "off":
        return ValidationResult("length_ratio", "skip", metrics=metrics)

    category = None
    if min_ratio is not None and ratio < min_ratio:
        category = "too_short"
    if max_ratio is not None and ratio > max_ratio:
        category = "too_long"
    if category is None:
        return ValidationResult("length_ratio", "pass", metrics=metrics)
    if normalized_policy == "warning":
        metrics["warning"] = True
        return ValidationResult("length_ratio", "warning", category, metrics)
    return ValidationResult("length_ratio", "fail", category, metrics)


def _normalize_length_ratio_policy(policy: str) -> str:
    if policy == "diagnostic":
        return "warning"
    if policy in {"off", "warning", "hard"}:
        return policy
    return "hard"


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


def _postprocessing_validation_results(
    value: Any, contract: ResponseContract, input_text: str | None
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    task_intent = contract.task_intent or "generic"
    validation_policy = contract.validation_policy or "automatic"
    source_text = contract.source_text if contract.source_text is not None else input_text
    output_text = extract_user_text_for_validation(
        value,
        schema_family=contract.schema_family,
        response_schema_complexity=contract.response_schema_complexity,
        include_paths=contract.language_include_paths,
    )

    term_policy = _effective_policy(
        contract.term_normalization_policy,
        default="hard" if task_intent == "term_normalization" else "diagnostic",
    )
    if contract.expected_terms and task_intent in {
        "term_normalization",
        "transcript_cleanup",
        "mixed_postprocess",
    }:
        results.append(
            _apply_validation_policy(
                validate_term_normalization(value, contract.expected_terms), term_policy
            )
        )
    else:
        results.append(ValidationResult("term_normalization_status", "skip"))

    punctuation_policy = _effective_policy(contract.punctuation_policy, default="diagnostic")
    if (
        source_text is not None
        and punctuation_policy != "off"
        and task_intent
        in {
            "punctuation_restore",
            "transcript_cleanup",
            "mixed_postprocess",
        }
    ):
        results.append(
            validate_punctuation_metrics(source_text, output_text, policy=punctuation_policy)
        )
    else:
        results.append(ValidationResult("punctuation_metrics", "skip"))

    paragraph_policy = _effective_policy(
        contract.paragraphing_policy,
        default="hard"
        if contract.paragraph_count_min is not None or contract.paragraph_count_max is not None
        else "off",
    )
    if paragraph_policy != "off" and (
        task_intent in {"paragraphing", "transcript_cleanup", "mixed_postprocess"}
        or contract.paragraph_count_min is not None
    ):
        results.append(
            validate_paragraphing_metrics(
                output_text,
                paragraph_count_min=contract.paragraph_count_min or 1,
                paragraph_count_max=contract.paragraph_count_max,
                hard=paragraph_policy == "hard",
            )
        )
    else:
        results.append(ValidationResult("paragraphing_metrics", "skip"))

    filler_policy = _effective_policy(
        contract.filler_cleanup_policy,
        default="hard" if task_intent == "filler_cleanup" else "diagnostic",
    )
    if source_text is not None and task_intent in {
        "filler_cleanup",
        "transcript_cleanup",
        "mixed_postprocess",
    }:
        filler_terms = contract.filler_terms or DEFAULT_RU_FILLERS
        results.append(
            _apply_validation_policy(
                validate_filler_cleanup(
                    source_text,
                    output_text,
                    filler_terms=filler_terms,
                    hard=filler_policy == "hard",
                ),
                filler_policy,
            )
        )
    else:
        results.append(ValidationResult("filler_cleanup", "skip"))

    manual_policy = _effective_policy(contract.manual_review_policy, default="diagnostic")
    manual_required = manual_policy != "off" and (
        "manual" in validation_policy
        or task_intent in {"summary", "action_items", "mixed_postprocess"}
    )
    results.append(
        ValidationResult(
            "no_new_facts_manual_review",
            "warning" if manual_required else "skip",
            "manual_review_required" if manual_required else None,
            {"manual_review_required": manual_required},
        )
    )
    return results


def extract_user_text_for_validation(
    value: Any,
    *,
    schema_family: str | None = None,
    response_schema_complexity: str | None = None,
    include_paths: tuple[str, ...] = (),
) -> str:
    paths = include_paths or _default_user_text_paths(schema_family, response_schema_complexity)
    if paths:
        return " ".join(
            _flatten_language_text(item)
            for path in paths
            for item in _values_by_path(value, _parse_id_path(path))
        )
    return _flatten_language_text(value)


def _default_user_text_paths(
    schema_family: str | None, response_schema_complexity: str | None
) -> tuple[str, ...]:
    normalized = response_schema_complexity or schema_family
    if normalized == "simple":
        return ("clean_text", "summary", "title", "tags[*]")
    if normalized == "blocks" or schema_family == "blocks":
        return ("blocks[*].text",)
    if normalized == "complex":
        return (
            "document.title",
            "document.sections[*].heading",
            "document.sections[*].blocks[*].text",
            "document.sections[*].blocks[*].terms[*].normalized",
        )
    return ()


def _effective_policy(policy: str | None, *, default: str) -> str:
    if policy in {"off", "diagnostic", "warning", "hard"}:
        return str(policy)
    return default


def _apply_validation_policy(result: ValidationResult, policy: str) -> ValidationResult:
    if policy == "off":
        return ValidationResult(result.name, "skip", metrics={**result.metrics, "policy": policy})
    metrics = {**result.metrics, "policy": policy}
    if policy in {"diagnostic", "warning"} and result.status == "fail":
        return ValidationResult(result.name, "warning", result.category, metrics)
    return ValidationResult(result.name, result.status, result.category, metrics)


def _primary_user_facing_text(value: Any, contract: ResponseContract) -> str:
    return extract_user_text_for_validation(
        value,
        schema_family=contract.schema_family,
        response_schema_complexity=contract.response_schema_complexity,
        include_paths=contract.language_include_paths,
    )


def validate_term_normalization(
    value: Any,
    expected_terms: tuple[dict[str, Any], ...],
) -> ValidationResult:
    text = _flatten_text(value).casefold()
    expected_count = len(expected_terms)
    normalized_seen = 0
    forbidden_remaining = 0
    for term in expected_terms:
        normalized = str(term.get("normalized", "")).casefold()
        variants = tuple(str(item).casefold() for item in term.get("source_variants", ()))
        if normalized and normalized in text:
            normalized_seen += 1
        forbidden_remaining += sum(
            1 for variant in variants if variant and variant in text and variant != normalized
        )
    recall = normalized_seen / expected_count if expected_count else 1.0
    precision = (
        1.0
        if forbidden_remaining == 0
        else normalized_seen / max(1, normalized_seen + forbidden_remaining)
    )
    status: ValidationStatus = (
        "pass" if normalized_seen == expected_count and forbidden_remaining == 0 else "fail"
    )
    return ValidationResult(
        "term_normalization_status",
        status,
        None if status == "pass" else "term_normalization_mismatch",
        {
            "expected_terms_seen": normalized_seen,
            "expected_terms_normalized": normalized_seen,
            "forbidden_term_variants_remaining": forbidden_remaining,
            "term_recall": round(recall, 4),
            "term_precision": round(precision, 4),
        },
    )


def validate_punctuation_metrics(
    before: str,
    after: str,
    *,
    policy: str = "diagnostic",
) -> ValidationResult:
    before_count = _punctuation_count(before)
    after_count = _punctuation_count(after)
    sentence_count = len(re.findall(r"[.!?…]+", after))
    density = after_count / max(1, len(after))
    metrics = {
        "punctuation_count_before": before_count,
        "punctuation_count_after": after_count,
        "sentence_count_before": len(re.findall(r"[.!?…]+", before)),
        "sentence_count_after": sentence_count,
        "punctuation_density_after": round(density, 4),
        "policy": policy,
    }
    if policy == "hard" and after_count <= before_count:
        return ValidationResult("punctuation_metrics", "fail", "punctuation_not_restored", metrics)
    return ValidationResult(
        "punctuation_metrics", "warning" if policy == "diagnostic" else "pass", metrics=metrics
    )


def validate_paragraphing_metrics(
    text: str,
    *,
    paragraph_count_min: int = 1,
    paragraph_count_max: int | None = None,
    hard: bool = False,
) -> ValidationResult:
    paragraphs = text.split("\n\n") if text else []
    non_empty = [item for item in paragraphs if item.strip()]
    empty_count = len(paragraphs) - len(non_empty)
    count = len(non_empty)
    too_low = count < paragraph_count_min
    too_high = paragraph_count_max is not None and count > paragraph_count_max
    metrics = {
        "paragraph_count": count,
        "paragraph_count_min": paragraph_count_min,
        "paragraph_count_max": paragraph_count_max,
        "empty_paragraph_count": empty_count,
    }
    if hard and (too_low or too_high or empty_count > 0):
        return ValidationResult("paragraphing_metrics", "fail", "paragraphing_mismatch", metrics)
    return ValidationResult("paragraphing_metrics", "pass", metrics=metrics)


DEFAULT_RU_FILLERS = ("ну", "как бы", "это самое", "короче", "типа", "в общем")


def validate_filler_cleanup(
    before: str,
    after: str,
    *,
    filler_terms: tuple[str, ...] = DEFAULT_RU_FILLERS,
    hard: bool = False,
) -> ValidationResult:
    before_count = _filler_count(before, filler_terms)
    after_count = _filler_count(after, filler_terms)
    reduction = (before_count - after_count) / before_count if before_count else 1.0
    metrics = {
        "filler_terms_before": before_count,
        "filler_terms_after": after_count,
        "filler_reduction_ratio": round(reduction, 4),
    }
    if hard and before_count > 0 and after_count >= before_count:
        return ValidationResult("filler_cleanup", "fail", "filler_cleanup_mismatch", metrics)
    return ValidationResult("filler_cleanup", "pass", metrics=metrics)


def _punctuation_count(text: str) -> int:
    return len(re.findall(r"[.!?,;:—–\-…]", text))


def _filler_count(text: str, filler_terms: tuple[str, ...]) -> int:
    lowered = text.casefold()
    return sum(
        len(re.findall(rf"(?<!\w){re.escape(term.casefold())}(?!\w)", lowered))
        for term in filler_terms
    )


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


def _flatten_language_text_by_policy(
    value: Any,
    *,
    include_paths: tuple[str, ...] = (),
    ignore_paths: tuple[str, ...] = (),
) -> str:
    if include_paths:
        return " ".join(
            _flatten_language_text(item)
            for path in include_paths
            for item in _values_by_path(value, _parse_id_path(path))
        )
    if ignore_paths:
        ignored = {
            id(item)
            for path in ignore_paths
            for item in _values_by_path(value, _parse_id_path(path))
        }
        return _flatten_language_text(value, ignored_ids=ignored)
    return _flatten_language_text(value)


_LANGUAGE_METADATA_KEYS = {
    "id",
    "language",
    "schema_version",
    "status",
    "type",
    "intent",
    "task_intent",
    "input_profile",
    "output_language_policy",
    "validation_policy",
    "terms",
    "tags",
    "keywords",
}


def _flatten_language_text(value: Any, *, ignored_ids: set[int] | None = None) -> str:
    """Flatten only user-visible language-bearing payload values.

    Language validation should not be dominated by JSON bookkeeping values such
    as ``language: \"ru\"``, enum/status fields, ids, or schema metadata. It still
    validates actual content fields and intentionally keeps technical terms that
    appear inside user-visible text.
    """

    if ignored_ids is not None and id(value) in ignored_ids:
        return ""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for key, child in value.items():
            if str(key) in _LANGUAGE_METADATA_KEYS:
                continue
            parts.append(_flatten_language_text(child, ignored_ids=ignored_ids))
        return " ".join(parts)
    if isinstance(value, list | tuple):
        return " ".join(_flatten_language_text(item, ignored_ids=ignored_ids) for item in value)
    return ""
