from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tools.lmstudio_lab.private_benchmark_pack import (
    PLACEHOLDER_RE,
    _validate_schema,
    canonical_json,
    public_structure_sha256,
    public_tree_sha256,
    score_normalization_output,
    validate_pack,
    validate_scorecard_consistency,
)

PACK_ROOT = (
    Path(__file__).resolve().parents[2]
    / "experiments"
    / "lmstudio"
    / "private_benchmark_pack"
    / "v1"
)


def _copy_pack(tmp_path: Path) -> Path:
    target = tmp_path / "pack"
    shutil.copytree(PACK_ROOT, target)
    return target


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _refresh_tree_digest(root: Path) -> None:
    pack_path = root / "pack.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    pack["public_tree_sha256"] = public_tree_sha256(root)
    _write_json(pack_path, pack)


def test_checked_in_pack_passes_all_offline_validators() -> None:
    assert validate_pack(PACK_ROOT) == []


def test_canonical_json_and_structure_digest_are_order_stable() -> None:
    units = [{"text": "ENTITY_001", "unit_index": 0}]
    reordered_keys = [{"unit_index": 0, "text": "ENTITY_001"}]
    assert canonical_json(units) == canonical_json(reordered_keys)
    assert public_structure_sha256(units) == public_structure_sha256(reordered_keys)


def test_schema_validator_rejects_missing_and_additional_properties() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["value"],
        "properties": {"value": {"type": "integer", "minimum": 0}},
    }
    assert _validate_schema({}, schema) == ["$: missing required key value"]
    assert _validate_schema({"value": 1, "extra": True}, schema) == ["$: additional key extra"]


def test_schema_validator_does_not_treat_boolean_as_number() -> None:
    assert _validate_schema(True, {"type": "integer"}) == ["$: expected integer"]
    assert _validate_schema(False, {"type": "number"}) == ["$: expected number"]


def test_schema_validator_enforces_closed_draft_keywords_used_by_pack() -> None:
    schema = {
        "type": "array",
        "minItems": 2,
        "maxItems": 2,
        "uniqueItems": True,
        "items": {"type": "integer", "minimum": 0, "maximum": 2},
    }
    assert _validate_schema([0, 2], schema) == []
    assert _validate_schema([3], schema)
    assert _validate_schema([1, 1], schema)
    assert _validate_schema("wrong", {"type": ["string", "null"], "const": "right"})


@pytest.mark.parametrize(
    ("schema_name", "valid", "invalid"),
    [
        (
            "normalization_output_v1.schema.json",
            {
                "schema_version": "normalization-v1",
                "normalized_text": "ENTITY_001",
                "preserved_placeholders": ["ENTITY_001"],
                "uncertain_spans": [],
                "input_digest": "0" * 64,
            },
            {"schema_version": "normalization-v1"},
        ),
        (
            "blocks_output_v1.schema.json",
            {
                "schema_version": "blocks-v1",
                "blocks": [],
                "warnings": [],
                "input_digest": "0" * 64,
                "output_digest": "1" * 64,
            },
            {"schema_version": "blocks-v1", "blocks": [], "warnings": []},
        ),
        (
            "stitch_output_v1.schema.json",
            {
                "schema_version": "stitch-v1",
                "stitched_text": "text",
                "duplicate_ranges": [],
                "missing_ranges": [],
                "order_errors": [],
                "structure_digest": "0" * 64,
            },
            {"schema_version": "stitch-v1", "stitched_text": "text"},
        ),
        (
            "probe_output_v1.schema.json",
            {
                "schema_version": "probe-v1",
                "probe_id": "probe-001",
                "answer": "unknown",
                "cited_unit_ranges": [],
                "unknown": True,
            },
            {"schema_version": "probe-v1", "probe_id": "probe-001"},
        ),
        (
            "scorecard_v1.schema.json",
            {
                "schema_version": "scorecard-v1",
                "view_label": "M01",
                "task_family": "normalization",
                "raw_json_valid": True,
                "transport_normalized_json_valid": True,
                "exact_schema_valid": True,
                "hard_failures": [],
                "metrics": {},
                "ordinal_scores": {"punctuation_casing": 2, "disfluency_handling": 2},
                "gold_basis": "semantic",
                "scoring_tier": "semantic_gold",
                "acceptance_scope": "semantic_normalization",
                "accepted": True,
            },
            {"schema_version": "scorecard-v1", "view_label": "M01"},
        ),
    ],
)
def test_model_output_schemas_accept_minimal_valid_and_reject_incomplete_documents(
    schema_name: str, valid: dict[str, object], invalid: dict[str, object]
) -> None:
    schema = json.loads((PACK_ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    assert _validate_schema(valid, schema) == []
    assert _validate_schema(invalid, schema)


@pytest.mark.parametrize(
    ("relative_path", "mutate", "expected_code"),
    [
        (
            "views/M01/fixture.json",
            lambda value: value["ordered_units"].__setitem__(
                1, {**value["ordered_units"][1], "unit_index": 7}
            ),
            "unit_order",
        ),
        (
            "views/M01/chunk_map.json",
            lambda value: value["chunks"][0].__setitem__("source_unit_end", 2),
            "chunk_coverage",
        ),
        (
            "views/M01/rubric.json",
            lambda value: value["thresholds"].pop("placeholder_preservation"),
            "rubric_completeness",
        ),
        (
            "views/M01/fixture.json",
            lambda value: value.__setitem__("semantic_gold_status", "reference_candidate"),
            "expected_output_status",
        ),
        (
            "views/M01/semantic_gold.json",
            lambda value: value.__setitem__("status", "single_reviewed"),
            "expected_output_status",
        ),
        (
            "views/M01/semantic_gold.json",
            lambda value: value["blocks"][0].__setitem__("source_unit_end", 0),
            "semantic_range",
        ),
        (
            "views/M01/semantic_gold.json",
            lambda value: value["blocks"][1].__setitem__("source_unit_start", 2),
            "semantic_range",
        ),
        (
            "views/M01/fixture.json",
            lambda value: value["provenance_claims"].append("AUDIO_TRUTH_EXACT"),
            "provenance_class",
        ),
        (
            "views/M01/fixture.json",
            lambda value: value.__setitem__("source_locator", "/private/source"),
            "private_key",
        ),
    ],
)
def test_validator_fails_closed_on_cross_asset_mutations(
    tmp_path: Path, relative_path: str, mutate: object, expected_code: str
) -> None:
    root = _copy_pack(tmp_path)
    path = root / relative_path
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)  # type: ignore[operator]
    _write_json(path, value)
    _refresh_tree_digest(root)
    assert expected_code in {issue.code for issue in validate_pack(root)}


def test_placeholder_inventory_is_closed_and_atomic() -> None:
    texts = []
    for fixture_path in sorted((PACK_ROOT / "views").glob("*/fixture.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        texts.extend(unit["text"] for unit in fixture["ordered_units"])
    placeholders = [token for text in texts for token in PLACEHOLDER_RE.findall(text)]
    assert placeholders
    assert all(token == token.strip() for token in placeholders)


def test_prompt_binding_digest_and_inventory_fail_closed(tmp_path: Path) -> None:
    root = _copy_pack(tmp_path)
    prompt = root / "prompts" / "normalization-v1.txt"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "changed", encoding="utf-8")
    _refresh_tree_digest(root)
    assert "prompt_digest" in {issue.code for issue in validate_pack(root)}


def _m01_scoring_inputs() -> tuple[dict, dict, dict, dict]:
    view = PACK_ROOT / "views" / "M01"
    fixture = json.loads((view / "fixture.json").read_text(encoding="utf-8"))
    rubric = json.loads((view / "rubric.json").read_text(encoding="utf-8"))
    gold = json.loads((view / "semantic_gold.json").read_text(encoding="utf-8"))
    output_schema = json.loads(
        (PACK_ROOT / "schemas" / "normalization_output_v1.schema.json").read_text(encoding="utf-8")
    )
    return fixture, rubric, gold, output_schema


def test_deterministic_scorer_accepts_exact_semantic_output() -> None:
    fixture, rubric, gold, output_schema = _m01_scoring_inputs()
    output = {
        "schema_version": "normalization-v1",
        "normalized_text": gold["normalized_text"],
        "preserved_placeholders": gold["preserved_placeholders"],
        "uncertain_spans": [],
        "input_digest": fixture["public_structure_sha256"],
    }
    scorecard = score_normalization_output(
        json.dumps(output, ensure_ascii=False), fixture, rubric, output_schema, gold
    )
    assert scorecard["accepted"] is True
    assert scorecard["metrics"] == {
        "placeholder_preservation": 1.0,
        "text_token_precision": 1.0,
        "text_token_recall": 1.0,
        "exact_text_match": 1.0,
    }
    assert validate_scorecard_consistency(scorecard, rubric) == []


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        (lambda output: output.update(extra="invented"), "schema_invalid"),
        (lambda output: output.__setitem__("input_digest", "0" * 64), "input_digest_mismatch"),
        (lambda output: output.__setitem__("preserved_placeholders", []), "placeholder_corruption"),
        (
            lambda output: output.__setitem__(
                "normalized_text", output["normalized_text"].replace("ENTITY_001", "ENTITY_999", 1)
            ),
            "placeholder_corruption",
        ),
    ],
)
def test_deterministic_scorer_rejects_adversarial_outputs(mutation: object, failure: str) -> None:
    fixture, rubric, gold, output_schema = _m01_scoring_inputs()
    output = {
        "schema_version": "normalization-v1",
        "normalized_text": gold["normalized_text"],
        "preserved_placeholders": gold["preserved_placeholders"],
        "uncertain_spans": [],
        "input_digest": fixture["public_structure_sha256"],
    }
    mutation(output)  # type: ignore[operator]
    scorecard = score_normalization_output(
        json.dumps(output, ensure_ascii=False), fixture, rubric, output_schema, gold
    )
    assert scorecard["accepted"] is False
    assert failure in scorecard["hard_failures"]


def test_deterministic_scorer_records_fenced_json_but_rejects_admission() -> None:
    fixture, rubric, gold, output_schema = _m01_scoring_inputs()
    output = {
        "schema_version": "normalization-v1",
        "normalized_text": gold["normalized_text"],
        "preserved_placeholders": gold["preserved_placeholders"],
        "uncertain_spans": [],
        "input_digest": fixture["public_structure_sha256"],
    }
    raw = f"```json\n{json.dumps(output, ensure_ascii=False)}\n```"
    scorecard = score_normalization_output(raw, fixture, rubric, output_schema, gold)
    assert scorecard["raw_json_valid"] is False
    assert scorecard["transport_normalized_json_valid"] is True
    assert scorecard["accepted"] is False
    assert "json_invalid" in scorecard["hard_failures"]


def test_scorecard_schema_and_consistency_reject_invented_metrics_and_false_acceptance() -> None:
    fixture, rubric, _, _ = _m01_scoring_inputs()
    schema = json.loads(
        (PACK_ROOT / "schemas" / "scorecard_v1.schema.json").read_text(encoding="utf-8")
    )
    scorecard = {
        "schema_version": "scorecard-v1",
        "view_label": fixture["view_label"],
        "task_family": "normalization",
        "raw_json_valid": False,
        "transport_normalized_json_valid": False,
        "exact_schema_valid": False,
        "hard_failures": [],
        "metrics": {"invented_metric": "perfect"},
        "ordinal_scores": {"punctuation_casing": 999, "disfluency_handling": 999},
        "gold_basis": "semantic",
        "scoring_tier": "semantic_gold",
        "acceptance_scope": "semantic_normalization",
        "accepted": True,
    }
    assert _validate_schema(scorecard, schema)
    assert validate_scorecard_consistency(scorecard, rubric)


def _reference_scoring_inputs(label: str = "M02") -> tuple[dict, dict, dict, dict]:
    view = PACK_ROOT / "views" / label
    fixture = json.loads((view / "fixture.json").read_text(encoding="utf-8"))
    rubric = json.loads((view / "rubric.json").read_text(encoding="utf-8"))
    reference = json.loads((view / "reference_candidate.json").read_text(encoding="utf-8"))
    output_schema = json.loads(
        (PACK_ROOT / "schemas" / "normalization_output_v1.schema.json").read_text(encoding="utf-8")
    )
    return fixture, rubric, reference, output_schema


def _target_output(fixture: dict, target_text: str) -> dict:
    return {
        "schema_version": "normalization-v1",
        "normalized_text": target_text,
        "preserved_placeholders": PLACEHOLDER_RE.findall(target_text),
        "uncertain_spans": [],
        "input_digest": fixture["public_structure_sha256"],
    }


def test_reference_relative_scorer_consumes_reference_and_accepts_exact_output() -> None:
    fixture, rubric, reference, output_schema = _reference_scoring_inputs()
    output = _target_output(fixture, reference["text"])
    scorecard = score_normalization_output(
        json.dumps(output, ensure_ascii=False), fixture, rubric, output_schema, reference
    )
    assert scorecard["accepted"] is True
    assert scorecard["scoring_tier"] == "reference_relative"
    assert scorecard["gold_basis"] == "reference_only"


@pytest.mark.parametrize("mutation", ["corrupt", "omit", "add", "placeholder"])
def test_reference_relative_scorer_rejects_any_target_damage(mutation: str) -> None:
    fixture, rubric, reference, output_schema = _reference_scoring_inputs()
    output = _target_output(fixture, reference["text"])
    if mutation == "corrupt":
        output["normalized_text"] = output["normalized_text"].replace("Итак", "Иначе", 1)
    elif mutation == "omit":
        output["normalized_text"] = output["normalized_text"][1:]
    elif mutation == "add":
        output["normalized_text"] += " invented"
    else:
        token = output["preserved_placeholders"][0]
        output["normalized_text"] = output["normalized_text"].replace(token, "ENTITY_999", 1)
    scorecard = score_normalization_output(
        json.dumps(output, ensure_ascii=False), fixture, rubric, output_schema, reference
    )
    assert scorecard["accepted"] is False
    assert "target_text_mismatch" in scorecard["hard_failures"]


def test_scorer_fails_closed_on_tier_confusion_and_structural_only_view() -> None:
    fixture, rubric, reference, output_schema = _reference_scoring_inputs()
    semantic = json.loads(
        (PACK_ROOT / "views" / "M01" / "semantic_gold.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ValueError, match="requires reference-candidate-v1"):
        score_normalization_output("{}", fixture, rubric, output_schema, semantic)

    fixture, rubric, _, output_schema = _reference_scoring_inputs("L02-L")
    with pytest.raises(ValueError, match="unavailable for structural-only"):
        score_normalization_output("{}", fixture, rubric, output_schema, reference)

    fixture, rubric, absent_reference, output_schema = _reference_scoring_inputs("M11")
    assert rubric["task_family"] == "structural_context_retention"
    assert rubric["acceptance_scope"] == "structural_context_retention"
    with pytest.raises(ValueError, match="unavailable for structural-only"):
        score_normalization_output("{}", fixture, rubric, output_schema, absent_reference)


def test_task_inventory_rejects_structural_view_normalization_acceptance(tmp_path: Path) -> None:
    root = _copy_pack(tmp_path)
    path = root / "task_bindings.json"
    bindings = json.loads(path.read_text(encoding="utf-8"))
    row = next(item for item in bindings["bindings"] if item["view_label"] == "L02-L")
    row["normalization_acceptance"] = True
    _write_json(path, bindings)
    _refresh_tree_digest(root)
    assert "tier_confusion" in {issue.code for issue in validate_pack(root)}


def test_task_inventory_has_exact_executable_tiers_and_structural_context_tasks() -> None:
    bindings = json.loads((PACK_ROOT / "task_bindings.json").read_text(encoding="utf-8"))[
        "bindings"
    ]
    tiers = {
        tier: [row for row in bindings if row["scoring_tier"] == tier]
        for tier in {"semantic_gold", "reference_relative", "structural_only"}
    }
    assert [row["view_label"] for row in tiers["semantic_gold"]] == ["M01"]
    assert len(tiers["reference_relative"]) == 11
    assert {row["view_label"] for row in tiers["structural_only"]} == {
        "M11",
        "L02-E",
        "L02-M",
        "L02-L",
    }
    assert all(
        row["task_family"] == "structural_context_retention"
        and row["capabilities"] == ["structure", "context", "retention"]
        and row["normalization_acceptance"] is False
        for row in tiers["structural_only"]
    )


@pytest.mark.parametrize("missing_value", [None, ""])
def test_absent_or_null_reference_cannot_be_promoted_to_reference_relative(
    tmp_path: Path, missing_value: str | None
) -> None:
    root = _copy_pack(tmp_path)
    bindings_path = root / "task_bindings.json"
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    row = next(item for item in bindings["bindings"] if item["view_label"] == "M11")
    row.update(
        task_family="normalization",
        prompt_version="normalization-v1",
        prompt_path="prompts/normalization-v1.txt",
        prompt_sha256="7014ea67b519241ceb5136aba510be6edf0a5d8f397de4671a878c2a06bf5f1e",
        output_schema_version="normalization-v1",
        scoring_tier="reference_relative",
        target_path="views/M11/reference_candidate.json",
        normalization_acceptance=True,
        capabilities=["normalization"],
    )
    _write_json(bindings_path, bindings)
    reference_path = root / "views" / "M11" / "reference_candidate.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference["text"] = missing_value
    _write_json(reference_path, reference)
    _refresh_tree_digest(root)
    assert "scoring_target_unavailable" in {issue.code for issue in validate_pack(root)}
