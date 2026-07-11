"""Offline validation for the publishable private benchmark pack.

The validator deliberately uses only the standard library. It validates the checked-in
assets and their cross-file invariants; it never opens the private preparation tree.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_RE = re.compile(
    r"(?<!\w)(?:PERSON|CONTACT|ACCOUNT|LOCATION|ORG|PRODUCT|ENTITY|DATE|PATH|SECRET|RARE)_\d{3}(?!\w)"
)
PLACEHOLDER_LIKE_RE = re.compile(r"(?<!\w)[A-Z][A-Z0-9_]*_\d{3}(?!\w)")
PRIVATE_KEY_RE = re.compile(
    r"(?:source_locator|source_mapping|redaction_map|redaction_spans|review_ids|private_root|"
    r"manifest_sha256|source_text_sha256)$"
)
PRIVATE_VALUE_RE = re.compile(r"(?:/home/|[A-Za-z]:\\|https?://|[^\s@]+@[^\s@]+)")
REQUIRED_HARD_FAILURES = {
    "placeholder_corruption",
    "unit_order_violation",
    "unit_coverage_violation",
    "private_content_exposure",
    "schema_invalid",
}
REQUIRED_THRESHOLDS = {
    "placeholder_preservation": 1.0,
}
NORMALIZATION_HARD_FAILURES = REQUIRED_HARD_FAILURES | {
    "input_digest_mismatch",
    "target_text_mismatch",
}
SCHEMA_FILES = {
    "public-pack-v1": "public_pack_v1.schema.json",
    "public-view-v1": "public_view_v1.schema.json",
    "task-bindings-v1": "task_bindings_v1.schema.json",
    "structural-gold-v1": "structural_gold_v1.schema.json",
    "chunk-map-v1": "chunk_map_v1.schema.json",
    "sanitized-blocks-v1": "sanitized_blocks_v1.schema.json",
    "reference-candidate-v1": "reference_candidate_v1.schema.json",
    "rubric-v1": "rubric_v1.schema.json",
    "semantic-gold-v1": "semantic_gold_v1.schema.json",
    "aggregate-v1": "aggregate_v1.schema.json",
    "semantic-review-v1": "semantic_review_v1.schema.json",
    "private-replay-evidence-v1": "private_replay_evidence_v1.schema.json",
}
PROVENANCE_CLASSES = {
    "RAW_SEGMENT_EXACT",
    "RAW_BLOCK_EXACT",
    "PROCESSED_BLOCK_EXACT",
    "CHUNK_MAP_EXACT",
    "REFERENCE_ONLY",
    "RAW_ONLY",
}


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    code: str
    message: str

    def render(self) -> str:
        return f"{self.path}: {self.code}: {self.message}"


def canonical_json(value: Any) -> bytes:
    """Return the pack's deterministic UTF-8 JSON representation."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def public_structure_sha256(ordered_units: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_json(ordered_units)).hexdigest()


def public_tree_sha256(root: Path) -> str:
    payload = bytearray()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == root / "pack.json":
            continue
        payload.extend(path.relative_to(root).as_posix().encode())
        payload.append(0)
        payload.extend(path.read_bytes())
        payload.append(0)
    return hashlib.sha256(payload).hexdigest()


def _load(path: Path, issues: list[ValidationIssue], root: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        issues.append(ValidationIssue(str(path.relative_to(root)), "json_invalid", str(exc)))
        return None


def _walk(value: Any, location: str = "$") -> list[tuple[str, str, Any]]:
    found: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.append((location, key, child))
            found.extend(_walk(child, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk(child, f"{location}[{index}]"))
    return found


def _validate_schema(instance: Any, schema: dict[str, Any], location: str = "$") -> list[str]:
    """Validate every Draft 2020-12 keyword used by the pack's closed schemas."""
    errors: list[str] = []
    expected = schema.get("type")
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    if expected:
        expected_names = expected if isinstance(expected, list) else [expected]
        wrong_type = True
        for expected_name in expected_names:
            expected_type = type_map.get(expected_name)
            matches = expected_type is not None and isinstance(instance, expected_type)
            if expected_name in {"integer", "number"} and isinstance(instance, bool):
                matches = False
            wrong_type &= not matches
        if wrong_type:
            return [f"{location}: expected {expected}"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{location}: value does not equal const")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{location}: value is outside enum")
    if (
        isinstance(instance, str)
        and "pattern" in schema
        and not re.fullmatch(schema["pattern"], instance)
    ):
        errors.append(f"{location}: value does not match pattern")
    if (
        isinstance(instance, (int, float))
        and not isinstance(instance, bool)
        and instance < schema.get("minimum", instance)
    ):
        errors.append(f"{location}: value is below minimum")
    if (
        isinstance(instance, (int, float))
        and not isinstance(instance, bool)
        and instance > schema.get("maximum", instance)
    ):
        errors.append(f"{location}: value is above maximum")
    if isinstance(instance, str) and len(instance) < schema.get("minLength", 0):
        errors.append(f"{location}: string is shorter than minLength")
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{location}: missing required key {key}")
        if schema.get("additionalProperties") is False:
            for key in instance.keys() - properties.keys():
                errors.append(f"{location}: additional key {key}")
        for key, child in instance.items():
            if key in properties:
                errors.extend(_validate_schema(child, properties[key], f"{location}.{key}"))
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{location}: array is shorter than minItems")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{location}: array is longer than maxItems")
        if schema.get("uniqueItems"):
            canonical_items = [canonical_json(item) for item in instance]
            if len(canonical_items) != len(set(canonical_items)):
                errors.append(f"{location}: array items are not unique")
        if "items" in schema:
            for index, child in enumerate(instance):
                errors.extend(_validate_schema(child, schema["items"], f"{location}[{index}]"))
    return errors


def _schema_for(
    document: dict[str, Any], schemas: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    version = document.get("schema_version")
    return schemas.get(version) if isinstance(version, str) else None


TOKEN_RE = re.compile(
    r"(?:[A-Za-zА-Яа-яЁё0-9]+|(?:PERSON|CONTACT|ACCOUNT|LOCATION|ORG|PRODUCT|ENTITY|DATE|PATH|SECRET|RARE)_\d{3})"
)


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_RE.findall(text)]


def _lcs_length(left: list[str], right: list[str]) -> int:
    row = [0] * (len(right) + 1)
    for left_token in left:
        previous = 0
        for index, right_token in enumerate(right, 1):
            saved = row[index]
            row[index] = (
                previous + 1 if left_token == right_token else max(row[index], row[index - 1])
            )
            previous = saved
    return row[-1]


def _transport_json(raw_output: str) -> tuple[Any | None, bool, bool]:
    try:
        return json.loads(raw_output), True, True
    except json.JSONDecodeError:
        stripped = raw_output.strip()
        match = re.fullmatch(r"```(?:json)?\s*\n(.*)\n```", stripped, re.DOTALL | re.IGNORECASE)
        if not match:
            return None, False, False
        try:
            return json.loads(match.group(1)), False, True
        except json.JSONDecodeError:
            return None, False, False


def score_normalization_output(
    raw_output: str,
    fixture: dict[str, Any],
    rubric: dict[str, Any],
    output_schema: dict[str, Any],
    target_document: dict[str, Any] | None,
) -> dict[str, Any]:
    """Score one normalization output against its explicitly tiered frozen target."""
    scoring_tier = rubric.get("scoring_tier")
    if rubric.get("task_family") != "normalization" or scoring_tier == "structural_only":
        raise ValueError("normalization scoring is unavailable for structural-only tasks")
    if scoring_tier not in {"semantic_gold", "reference_relative"}:
        raise ValueError("unknown normalization scoring tier")
    expected_schema = (
        "semantic-gold-v1" if scoring_tier == "semantic_gold" else "reference-candidate-v1"
    )
    if (
        not isinstance(target_document, dict)
        or target_document.get("schema_version") != expected_schema
    ):
        raise ValueError(f"{scoring_tier} requires {expected_schema}")
    if target_document.get("view_label") != fixture.get("view_label"):
        raise ValueError("scoring target view does not match fixture")
    expected_text = (
        target_document.get("normalized_text")
        if scoring_tier == "semantic_gold"
        else target_document.get("text")
    )
    if not isinstance(expected_text, str) or not expected_text:
        raise ValueError("scoring target text is unavailable")
    candidate, raw_valid, transport_valid = _transport_json(raw_output)
    schema_errors = (
        _validate_schema(candidate, output_schema)
        if isinstance(candidate, dict)
        else ["not object"]
    )
    hard_failures: list[str] = []
    if not raw_valid:
        hard_failures.append("json_invalid")
    if schema_errors:
        hard_failures.append("schema_invalid")
    metrics: dict[str, float] = {}
    ordinal = {"punctuation_casing": 0, "disfluency_handling": 0}
    if isinstance(candidate, dict) and not schema_errors:
        expected_placeholders = PLACEHOLDER_RE.findall(expected_text)
        actual_placeholders = PLACEHOLDER_RE.findall(candidate["normalized_text"])
        declared_placeholders = candidate["preserved_placeholders"]
        metrics["placeholder_preservation"] = float(
            actual_placeholders == expected_placeholders == declared_placeholders
        )
        if metrics["placeholder_preservation"] != 1.0:
            hard_failures.append("placeholder_corruption")
        if candidate["input_digest"] != fixture["public_structure_sha256"]:
            hard_failures.append("input_digest_mismatch")
        expected_tokens = _tokens(expected_text)
        actual_tokens = _tokens(candidate["normalized_text"])
        shared = _lcs_length(expected_tokens, actual_tokens)
        metrics["text_token_precision"] = shared / len(actual_tokens) if actual_tokens else 0.0
        metrics["text_token_recall"] = shared / len(expected_tokens) if expected_tokens else 1.0
        metrics["exact_text_match"] = float(candidate["normalized_text"] == expected_text)
        ordinal["punctuation_casing"] = 2 if metrics["exact_text_match"] == 1.0 else 0
        ordinal["disfluency_handling"] = 2 if metrics["exact_text_match"] == 1.0 else 0
        if metrics["exact_text_match"] != 1.0:
            hard_failures.append("target_text_mismatch")
    threshold_pass = all(
        metrics.get(name, -1.0) >= value for name, value in rubric["thresholds"].items()
    )
    ordinal_pass = all(
        ordinal.get(name, -1) >= value for name, value in rubric["ordinal_thresholds"].items()
    )
    accepted = (
        not hard_failures
        and transport_valid
        and not schema_errors
        and threshold_pass
        and ordinal_pass
    )
    return {
        "schema_version": "scorecard-v1",
        "view_label": fixture["view_label"],
        "task_family": "normalization",
        "raw_json_valid": raw_valid,
        "transport_normalized_json_valid": transport_valid,
        "exact_schema_valid": not schema_errors,
        "hard_failures": sorted(set(hard_failures)),
        "metrics": metrics,
        "ordinal_scores": ordinal,
        "gold_basis": rubric["gold_basis"],
        "scoring_tier": scoring_tier,
        "acceptance_scope": rubric["acceptance_scope"],
        "accepted": accepted,
    }


def validate_scorecard_consistency(scorecard: dict[str, Any], rubric: dict[str, Any]) -> list[str]:
    """Reject scorecards whose acceptance contradicts their objective evidence."""
    failures = scorecard.get("hard_failures", [])
    metrics = scorecard.get("metrics", {})
    ordinals = scorecard.get("ordinal_scores", {})
    expected = (
        scorecard.get("transport_normalized_json_valid") is True
        and scorecard.get("exact_schema_valid") is True
        and not failures
        and all(metrics.get(name, -1) >= value for name, value in rubric["thresholds"].items())
        and all(
            ordinals.get(name, -1) >= value for name, value in rubric["ordinal_thresholds"].items()
        )
    )
    return (
        [] if scorecard.get("accepted") is expected else ["$.accepted: inconsistent with evidence"]
    )


def _check_public_boundary(
    document: Any, relative_path: str, issues: list[ValidationIssue]
) -> None:
    for location, key, value in _walk(document):
        if PRIVATE_KEY_RE.search(key):
            issues.append(ValidationIssue(relative_path, "private_key", f"{location}.{key}"))
        if isinstance(value, str) and key not in {"text", "raw_text", "normalized_text"}:
            if PRIVATE_VALUE_RE.search(value):
                issues.append(
                    ValidationIssue(relative_path, "private_locator", f"{location}.{key}")
                )


def _check_placeholders(
    texts: list[str], relative_path: str, issues: list[ValidationIssue]
) -> Counter[str]:
    inventory: Counter[str] = Counter()
    for text in texts:
        known = PLACEHOLDER_RE.findall(text)
        if known != PLACEHOLDER_LIKE_RE.findall(text):
            issues.append(
                ValidationIssue(
                    relative_path, "placeholder_unknown", "unknown placeholder-like token"
                )
            )
        inventory.update(known)
    return inventory


def validate_pack(root: Path) -> list[ValidationIssue]:
    """Return every deterministic validation issue in a public pack tree."""
    root = root.resolve()
    issues: list[ValidationIssue] = []
    pack_path = root / "pack.json"
    pack = _load(pack_path, issues, root)
    schemas: dict[str, dict[str, Any]] = {}
    for version, filename in SCHEMA_FILES.items():
        loaded_schema = _load(root / "schemas" / filename, issues, root)
        if isinstance(loaded_schema, dict):
            schemas[version] = loaded_schema
            if loaded_schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                issues.append(
                    ValidationIssue(
                        f"schemas/{filename}",
                        "schema_draft",
                        "Draft 2020-12 declaration required",
                    )
                )
    pack_schema = schemas.get("public-pack-v1")
    view_schema = schemas.get("public-view-v1")
    if (
        not isinstance(pack, dict)
        or not isinstance(pack_schema, dict)
        or not isinstance(view_schema, dict)
    ):
        return issues

    for error in _validate_schema(pack, pack_schema):
        issues.append(ValidationIssue("pack.json", "schema", error))
    _check_public_boundary(pack, "pack.json", issues)

    labels = pack.get("view_labels", [])
    if len(labels) != pack.get("view_count") or len(labels) != len(set(labels)):
        issues.append(
            ValidationIssue(
                "pack.json", "view_inventory", "view labels must be unique and match view_count"
            )
        )
    if len(set(pack.get("schema_versions", []))) != len(pack.get("schema_versions", [])):
        issues.append(
            ValidationIssue("pack.json", "schema_inventory", "schema_versions contains duplicates")
        )

    declared_schemas = set(pack.get("schema_versions", []))
    if not set(SCHEMA_FILES) <= declared_schemas or set(schemas) != set(SCHEMA_FILES):
        issues.append(
            ValidationIssue("pack.json", "schema_inventory", "declared data schemas are incomplete")
        )

    bindings = _load(root / "task_bindings.json", issues, root)
    if isinstance(bindings, dict):
        binding_schema = schemas.get("task-bindings-v1")
        if binding_schema is not None:
            for error in _validate_schema(bindings, binding_schema):
                issues.append(ValidationIssue("task_bindings.json", "schema", error))
        _check_public_boundary(bindings, "task_bindings.json", issues)
        binding_rows = bindings.get("bindings", [])
        if [row.get("view_label") for row in binding_rows] != labels:
            issues.append(
                ValidationIssue(
                    "task_bindings.json", "task_inventory", "bindings must match view inventory"
                )
            )
        for row in binding_rows:
            normalization = row.get("task_family") == "normalization"
            tier = row.get("scoring_tier")
            target_path = row.get("target_path")
            prompt_path = root / (row.get("prompt_path") or "")
            if normalization and not prompt_path.is_file():
                issues.append(
                    ValidationIssue(
                        "task_bindings.json", "prompt_inventory", "bound prompt is missing"
                    )
                )
            elif normalization and hashlib.sha256(prompt_path.read_bytes()).hexdigest() != row.get(
                "prompt_sha256"
            ):
                issues.append(
                    ValidationIssue(
                        "task_bindings.json", "prompt_digest", "bound prompt digest mismatch"
                    )
                )
            if normalization != (tier in {"semantic_gold", "reference_relative"}):
                issues.append(
                    ValidationIssue(
                        "task_bindings.json",
                        "tier_confusion",
                        "task family and scoring tier disagree",
                    )
                )
            if normalization:
                expected_target = (
                    f"views/{row['view_label']}/semantic_gold.json"
                    if tier == "semantic_gold"
                    else f"views/{row['view_label']}/reference_candidate.json"
                )
                if target_path != expected_target or not (root / expected_target).is_file():
                    issues.append(
                        ValidationIssue(
                            "task_bindings.json",
                            "scoring_target",
                            "normalization target is missing or tier-inconsistent",
                        )
                    )
                else:
                    target_document = _load(root / expected_target, issues, root)
                    target_text_key = "normalized_text" if tier == "semantic_gold" else "text"
                    expected_target_status = (
                        "approved" if tier == "semantic_gold" else "reference_candidate"
                    )
                    if (
                        not isinstance(target_document, dict)
                        or target_document.get("status") != expected_target_status
                        or not isinstance(target_document.get(target_text_key), str)
                        or not target_document[target_text_key]
                    ):
                        issues.append(
                            ValidationIssue(
                                "task_bindings.json",
                                "scoring_target_unavailable",
                                "executable normalization requires an available non-empty target",
                            )
                        )
            elif target_path is not None or row.get("normalization_acceptance") is not False:
                issues.append(
                    ValidationIssue(
                        "task_bindings.json",
                        "tier_confusion",
                        "structural-only task cannot expose normalization acceptance",
                    )
                )
        bound_versions = sorted(
            {
                row.get("prompt_version")
                for row in binding_rows
                if row.get("prompt_version") is not None
            }
        )
        if bound_versions != sorted(pack.get("prompt_versions", [])):
            issues.append(
                ValidationIssue(
                    "task_bindings.json", "prompt_inventory", "prompt versions differ from pack"
                )
            )

    actual_labels = sorted(path.name for path in (root / "views").iterdir() if path.is_dir())
    if sorted(labels) != actual_labels:
        issues.append(
            ValidationIssue("pack.json", "view_inventory", "declared and actual view labels differ")
        )

    semantic_files: set[str] = set()
    for label in labels:
        view_root = root / "views" / label
        required = {
            "fixture.json",
            "structural_gold.json",
            "chunk_map.json",
            "blocks.json",
            "reference_candidate.json",
            "rubric.json",
        }
        missing = sorted(name for name in required if not (view_root / name).is_file())
        if missing:
            issues.append(
                ValidationIssue(f"views/{label}", "asset_inventory", f"missing {missing}")
            )
            continue
        loaded_docs = {name: _load(view_root / name, issues, root) for name in required}
        if not all(isinstance(value, dict) for value in loaded_docs.values()):
            continue
        docs = cast(dict[str, dict[str, Any]], loaded_docs)
        fixture = docs["fixture.json"]
        relative = f"views/{label}/fixture.json"
        for error in _validate_schema(fixture, view_schema):
            issues.append(ValidationIssue(relative, "schema", error))
        for name, document in docs.items():
            document_path = f"views/{label}/{name}"
            _check_public_boundary(document, document_path, issues)
            document_schema = _schema_for(document, schemas)
            if document_schema is None:
                issues.append(
                    ValidationIssue(
                        document_path, "schema_inventory", "unknown document schema_version"
                    )
                )
            else:
                for error in _validate_schema(document, document_schema):
                    issues.append(ValidationIssue(document_path, "schema", error))
            if document.get("view_label") != label:
                issues.append(
                    ValidationIssue(f"views/{label}/{name}", "view_label", "label mismatch")
                )

        units = fixture["ordered_units"]
        indexes = [unit["unit_index"] for unit in units]
        if indexes != list(range(len(units))):
            issues.append(
                ValidationIssue(relative, "unit_order", "unit indexes are not contiguous")
            )
        if fixture["public_structure_sha256"] != public_structure_sha256(units):
            issues.append(
                ValidationIssue(relative, "structure_digest", "public structure digest mismatch")
            )

        structural = docs["structural_gold.json"]
        if structural.get("unit_count") != len(units) or structural.get("unit_indexes") != indexes:
            issues.append(
                ValidationIssue(
                    f"views/{label}/structural_gold.json",
                    "reconstruction",
                    "unit inventory mismatch",
                )
            )
        if structural.get("public_structure_sha256") != fixture["public_structure_sha256"]:
            issues.append(
                ValidationIssue(
                    f"views/{label}/structural_gold.json",
                    "structure_digest",
                    "fixture digest mismatch",
                )
            )
        if not all(structural.get("assertions", {}).values()):
            issues.append(
                ValidationIssue(
                    f"views/{label}/structural_gold.json",
                    "reconstruction",
                    "assertions must all pass",
                )
            )

        chunks = docs["chunk_map.json"].get("chunks", [])
        cursor = 0
        for chunk_index, chunk in enumerate(chunks):
            if chunk.get("chunk_index") != chunk_index or chunk.get("source_unit_start") != cursor:
                issues.append(
                    ValidationIssue(
                        f"views/{label}/chunk_map.json",
                        "chunk_order",
                        "chunks are not contiguous and ordered",
                    )
                )
                break
            end = chunk.get("source_unit_end")
            if not isinstance(end, int) or end <= cursor or end > len(units):
                issues.append(
                    ValidationIssue(
                        f"views/{label}/chunk_map.json", "chunk_ownership", "invalid chunk range"
                    )
                )
                break
            cursor = end
        if (
            cursor != len(units)
            or not docs["chunk_map.json"].get("coverage_exact")
            or not docs["chunk_map.json"].get("order_exact")
        ):
            issues.append(
                ValidationIssue(
                    f"views/{label}/chunk_map.json",
                    "chunk_coverage",
                    "chunk ownership is incomplete",
                )
            )

        texts = [unit["text"] for unit in units]
        blocks = docs["blocks.json"].get("blocks", [])
        texts.extend(block.get("raw_text", "") for block in blocks)
        texts.extend(
            block["reference_candidate_text"]
            for block in blocks
            if block.get("reference_candidate_text") is not None
        )
        reference = docs["reference_candidate.json"]
        if reference.get("text") is not None:
            texts.append(reference["text"])
        fixture_inventory = _check_placeholders([unit["text"] for unit in units], relative, issues)
        _check_placeholders(texts, f"views/{label}", issues)

        semantic_path = view_root / "semantic_gold.json"
        if semantic_path.is_file():
            semantic_files.add(label)
            semantic = _load(semantic_path, issues, root)
            if isinstance(semantic, dict):
                _check_public_boundary(semantic, f"views/{label}/semantic_gold.json", issues)
                semantic_schema = _schema_for(semantic, schemas)
                if semantic_schema is None:
                    issues.append(
                        ValidationIssue(
                            f"views/{label}/semantic_gold.json",
                            "schema_inventory",
                            "unknown document schema_version",
                        )
                    )
                else:
                    for error in _validate_schema(semantic, semantic_schema):
                        issues.append(
                            ValidationIssue(f"views/{label}/semantic_gold.json", "schema", error)
                        )
                if semantic.get("status") != "approved":
                    issues.append(
                        ValidationIssue(
                            f"views/{label}/semantic_gold.json",
                            "expected_output_status",
                            "semantic gold must be two-reviewer approved",
                        )
                    )
                expected = Counter(semantic.get("preserved_placeholders", []))
                actual = Counter(PLACEHOLDER_RE.findall(semantic.get("normalized_text", "")))
                if expected != actual or not set(expected) <= set(fixture_inventory):
                    issues.append(
                        ValidationIssue(
                            f"views/{label}/semantic_gold.json",
                            "placeholder_inventory",
                            "semantic placeholder inventory mismatch",
                        )
                    )
                digest = hashlib.sha256(semantic.get("normalized_text", "").encode()).hexdigest()
                if semantic.get("output_sha256") != digest:
                    issues.append(
                        ValidationIssue(
                            f"views/{label}/semantic_gold.json",
                            "output_digest",
                            "semantic output digest mismatch",
                        )
                    )

                block_cursor = 0
                for block_index, block in enumerate(semantic.get("blocks", [])):
                    start = block.get("source_unit_start")
                    end = block.get("source_unit_end")
                    valid_range = (
                        block.get("block_index") == block_index
                        and start == block_cursor
                        and isinstance(end, int)
                        and isinstance(start, int)
                        and end > start
                        and end <= len(units)
                    )
                    if not valid_range:
                        issues.append(
                            ValidationIssue(
                                f"views/{label}/semantic_gold.json",
                                "semantic_range",
                                "blocks must be ordered, non-empty, contiguous, and within fixture units",
                            )
                        )
                        break
                    block_cursor = end
                if block_cursor != len(units):
                    issues.append(
                        ValidationIssue(
                            f"views/{label}/semantic_gold.json",
                            "semantic_coverage",
                            "semantic blocks must cover every source unit exactly once",
                        )
                    )

        rubric = docs["rubric.json"]
        if not REQUIRED_HARD_FAILURES <= set(rubric.get("hard_failures", [])):
            issues.append(
                ValidationIssue(
                    f"views/{label}/rubric.json",
                    "rubric_completeness",
                    "required hard failures missing",
                )
            )
        if any(
            rubric.get("thresholds", {}).get(key) != value
            for key, value in REQUIRED_THRESHOLDS.items()
        ):
            issues.append(
                ValidationIssue(
                    f"views/{label}/rubric.json",
                    "rubric_completeness",
                    "required thresholds missing",
                )
            )
        unsupported = label in {"M11", "L02-E", "L02-M", "L02-L"}
        expected_status = "approved" if label in semantic_files else reference.get("status")
        expected_basis = (
            "semantic"
            if label in semantic_files
            else ("structural" if unsupported else "reference_only")
        )
        if fixture.get("semantic_gold_status") != expected_status:
            issues.append(
                ValidationIssue(
                    relative,
                    "expected_output_status",
                    "fixture status does not match semantic asset inventory",
                )
            )
        if rubric.get("gold_basis") != expected_basis:
            issues.append(
                ValidationIssue(
                    f"views/{label}/rubric.json",
                    "expected_output_status",
                    "rubric basis does not match semantic asset inventory",
                )
            )
        expected_tier = (
            "semantic_gold"
            if label in semantic_files
            else ("structural_only" if unsupported else "reference_relative")
        )
        if rubric.get("scoring_tier") != expected_tier:
            issues.append(
                ValidationIssue(
                    f"views/{label}/rubric.json",
                    "tier_confusion",
                    "rubric scoring tier does not match reviewed inventory",
                )
            )
        if not set(fixture.get("provenance_claims", [])) <= PROVENANCE_CLASSES:
            issues.append(ValidationIssue(relative, "provenance_class", "unknown provenance class"))
        if reference.get("status") == "reference_candidate" and "REFERENCE_ONLY" not in fixture.get(
            "provenance_claims", []
        ):
            issues.append(
                ValidationIssue(relative, "provenance_class", "REFERENCE_ONLY claim required")
            )
    review = _load(root / "reports" / "semantic_review.sanitized.json", issues, root)
    if isinstance(review, dict):
        review_schema = _schema_for(review, schemas)
        if review_schema is None:
            issues.append(
                ValidationIssue(
                    "reports/semantic_review.sanitized.json",
                    "schema_inventory",
                    "unknown document schema_version",
                )
            )
        else:
            for error in _validate_schema(review, review_schema):
                issues.append(
                    ValidationIssue("reports/semantic_review.sanitized.json", "schema", error)
                )
        _check_public_boundary(review, "reports/semantic_review.sanitized.json", issues)
        reviewed_gold = {
            row["view_label"]
            for row in review.get("verdicts", [])
            if row.get("verdict") == "approved"
        }
        if reviewed_gold != semantic_files:
            issues.append(
                ValidationIssue(
                    "reports/semantic_review.sanitized.json",
                    "expected_output_status",
                    "approved verdicts and semantic files differ",
                )
            )

    aggregate = _load(root / "reports" / "aggregate.sanitized.json", issues, root)
    if isinstance(aggregate, dict):
        aggregate_schema = _schema_for(aggregate, schemas)
        if aggregate_schema is None:
            issues.append(
                ValidationIssue(
                    "reports/aggregate.sanitized.json",
                    "schema_inventory",
                    "unknown document schema_version",
                )
            )
        else:
            for error in _validate_schema(aggregate, aggregate_schema):
                issues.append(ValidationIssue("reports/aggregate.sanitized.json", "schema", error))
        _check_public_boundary(aggregate, "reports/aggregate.sanitized.json", issues)

    replay = _load(root / "reports" / "private_replay.sanitized.json", issues, root)
    if isinstance(replay, dict):
        replay_schema = _schema_for(replay, schemas)
        if replay_schema is None:
            issues.append(
                ValidationIssue(
                    "reports/private_replay.sanitized.json",
                    "schema_inventory",
                    "unknown document schema_version",
                )
            )
        else:
            for error in _validate_schema(replay, replay_schema):
                issues.append(
                    ValidationIssue("reports/private_replay.sanitized.json", "schema", error)
                )
        _check_public_boundary(replay, "reports/private_replay.sanitized.json", issues)

    expected_tree_digest = pack.get("public_tree_sha256")
    if not isinstance(expected_tree_digest, str) or not SHA256_RE.fullmatch(expected_tree_digest):
        issues.append(ValidationIssue("pack.json", "tree_digest", "invalid public tree digest"))
    elif expected_tree_digest != public_tree_sha256(root):
        issues.append(ValidationIssue("pack.json", "tree_digest", "public tree digest mismatch"))
    return issues


def assert_valid_pack(root: Path) -> None:
    issues = validate_pack(root)
    if issues:
        raise ValueError("\n".join(issue.render() for issue in issues))
