from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
VISION_SCHEMA_DIR = ROOT / "experiments/lmstudio/structured_matrix/schemas/vision"
VALIDATORS_PATH = VISION_SCHEMA_DIR / "vision_validator_contracts.yaml"
COMPAT_PATH = VISION_SCHEMA_DIR / "vision_task_intent_compatibility.yaml"

EXPECTED_VALIDATORS = {
    "visible_text_recall",
    "visible_text_precision",
    "object_label_recall",
    "table_cell_accuracy",
    "chart_value_accuracy",
    "code_identifier_recall",
    "ui_control_recall",
    "person_count_accuracy",
    "forbidden_claims_check",
    "language_compliance",
    "json_schema",
}

EXPECTED_INTENTS = {
    "image_description",
    "ocr_visible_text",
    "ui_understanding",
    "table_extraction",
    "chart_extraction",
    "code_understanding",
    "scene_understanding",
    "slide_extraction",
}


def test_vision_validator_contracts_cover_required_validators_and_severity() -> None:
    payload = yaml.safe_load(VALIDATORS_PATH.read_text(encoding="utf-8"))

    assert set(payload["validator_contracts"]) == EXPECTED_VALIDATORS
    assert payload["severity"]["simple_description"] == {
        "visible_text_recall": "warning",
        "forbidden_claims": "hard",
        "json_schema": "hard",
    }
    assert payload["severity"]["medium_objects_text"] == {
        "visible_text_recall": "warning",
        "object_label_recall": "warning",
        "forbidden_claims": "hard",
        "json_schema": "hard",
    }
    assert payload["severity"]["complex_layout_extraction"] == {"prepared_only": True}


def test_vision_task_intents_are_separate_from_json_complexity() -> None:
    payload = yaml.safe_load(COMPAT_PATH.read_text(encoding="utf-8"))

    assert set(payload["task_intents"]) == EXPECTED_INTENTS
    assert set(payload["allowed_task_intents_by_image_type"]["document_table"]) == {
        "image_description",
        "ocr_visible_text",
        "table_extraction",
    }
    assert set(payload["allowed_task_intents_by_image_type"]["chart_graph"]) == {
        "image_description",
        "ocr_visible_text",
        "chart_extraction",
    }
    assert set(payload["allowed_task_intents_by_image_type"]["people_scene"]) == {
        "image_description",
        "scene_understanding",
    }


def test_vision_task_image_compatibility_records_missing_coverage() -> None:
    payload = yaml.safe_load(COMPAT_PATH.read_text(encoding="utf-8"))
    coverage = payload["image_type_compatibility"]

    assert coverage["screencast_frame"] == []
    assert coverage["ui_screenshot"]
    assert coverage["dense_text_screen"]
