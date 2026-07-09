from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT / "experiments/lmstudio/structured_matrix/schemas/vision/vision_schema_contracts.yaml"
)


def _schemas() -> dict:
    return yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_vision_schema_manifest_declares_three_complexity_levels() -> None:
    payload = _schemas()

    assert payload["vision_schema_complexity"] == [
        "simple_description",
        "medium_objects_text",
        "complex_layout_extraction",
    ]
    assert set(payload["schemas"]) == set(payload["vision_schema_complexity"])


def test_simple_description_schema_contract() -> None:
    schema = _schemas()["schemas"]["simple_description"]

    assert schema["required"] == ["description", "visible_text", "warnings"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["description"]["minLength"] == 1
    assert schema["properties"]["visible_text"]["items"]["type"] == "string"


def test_medium_objects_text_schema_allows_null_object_label() -> None:
    schema = _schemas()["schemas"]["medium_objects_text"]

    assert schema["required"] == ["image_type", "summary", "visible_text", "objects", "warnings"]
    assert schema["properties"]["objects"]["items"]["properties"]["label"]["type"] == [
        "string",
        "null",
    ]
    assert schema["properties"]["objects"]["items"]["required"] == ["type", "label"]


def test_complex_layout_extraction_schema_is_prepared_only() -> None:
    schema = _schemas()["schemas"]["complex_layout_extraction"]

    assert schema["prepared_only"] is True
    assert schema["required"] == ["document", "extracted_data", "warnings"]
    assert schema["properties"]["document"]["required"] == [
        "image_type",
        "language",
        "sections",
    ]
