from __future__ import annotations

from typing import Any, Literal

SchemaVariant = Literal["baseline_loose", "hardened_const"]


def build_simple_flat_schema(*, min_text_length: int = 1) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["id", "text"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": ["integer", "string"]},
            "text": {"type": "string", "minLength": min_text_length},
        },
    }


def build_blocks_schema(
    expected_ids: list[int | str] | tuple[int | str, ...],
    variant: str = "baseline_loose",
    *,
    min_text_length: int = 1,
    max_text_length: int | None = None,
) -> dict[str, Any]:
    text_schema: dict[str, Any] = {"type": "string", "minLength": min_text_length}
    if max_text_length is not None:
        text_schema["maxLength"] = max_text_length
    block_base = {
        "type": "object",
        "required": ["id", "text"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": ["integer", "string"]},
            "text": text_schema,
        },
    }
    if variant == "baseline_loose":
        return {
            "type": "object",
            "required": ["blocks"],
            "additionalProperties": False,
            "properties": {
                "blocks": {
                    "type": "array",
                    "minItems": len(expected_ids),
                    "items": block_base,
                }
            },
        }
    if variant == "hardened_const":
        return {
            "type": "object",
            "required": ["blocks"],
            "additionalProperties": False,
            "properties": {
                "blocks": {
                    "type": "array",
                    "minItems": len(expected_ids),
                    "maxItems": len(expected_ids),
                    "prefixItems": [
                        {
                            "type": "object",
                            "required": ["id", "text"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"const": item},
                                "text": text_schema,
                            },
                        }
                        for item in expected_ids
                    ],
                    "items": False,
                }
            },
        }
    raise ValueError(f"Unsupported blocks schema variant: {variant}")


def build_complex_nested_schema(
    expected_ids: list[int | str] | tuple[int | str, ...],
) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["document"],
        "additionalProperties": False,
        "properties": {
            "document": {
                "type": "object",
                "required": ["sections"],
                "additionalProperties": False,
                "properties": {
                    "sections": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["id", "title", "blocks"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": ["integer", "string"]},
                                "title": {"type": "string", "minLength": 1},
                                "blocks": build_blocks_schema(expected_ids, "hardened_const")[
                                    "properties"
                                ]["blocks"],
                            },
                        },
                    }
                },
            }
        },
    }


def build_image_simple_schema() -> dict[str, Any]:
    return _image_schema(required_labels_min=1, max_items=8)


def build_image_medium_schema() -> dict[str, Any]:
    return _image_schema(required_labels_min=2, max_items=16)


def build_image_complex_schema() -> dict[str, Any]:
    return _image_schema(required_labels_min=3, max_items=32)


def _image_schema(*, required_labels_min: int, max_items: int) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["description", "labels"],
        "additionalProperties": False,
        "properties": {
            "description": {"type": "string", "minLength": 1},
            "labels": {
                "type": "array",
                "minItems": required_labels_min,
                "maxItems": max_items,
                "items": {"type": "string", "minLength": 1},
            },
        },
    }


__all__ = [
    "build_blocks_schema",
    "build_complex_nested_schema",
    "build_image_complex_schema",
    "build_image_medium_schema",
    "build_image_simple_schema",
    "build_simple_flat_schema",
]
