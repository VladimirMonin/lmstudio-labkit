"""Build the frozen public-safe strict vision fixture and launch manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from lmstudio_labkit.strict_vision import build_strict_vision_fixture
from PIL import __version__ as pillow_version

MODELS = (
    "google/gemma-4-e2b",
    "google/gemma-4-e4b",
    "google/gemma-4-12b-qat",
    "google/gemma-4-26b-a4b-qat",
)
FIXTURE_IDS = (
    "ui_settings_ru_001",
    "document_table_products_ru_001",
    "chart_tasks_by_month_ru_001",
    "code_python_editor_001",
)
MODEL_SHORT_NAMES = ("e2b", "e4b", "12b", "26b")
FORBIDDEN_CLAIMS = (
    "real customer data",
    "private production system",
    "identified person",
)
PROMPTS = {
    "native_plain": (
        "Describe only what is visibly present in the image. "
        "Do not infer private context or identities."
    ),
    "simple_description": (
        "Return the strict schema. Describe visible content, transcribe visible text, "
        "and list uncertainty in warnings. Do not invent hidden context."
    ),
    "medium_objects_text": (
        "Return the strict schema. Describe visible content, transcribe visible text, "
        "list visible object labels, and list uncertainty in warnings. "
        "Do not invent hidden context."
    ),
    "text_preflight": (
        "Return a synthetic object conforming to the supplied schema, "
        "with no image-dependent claims."
    ),
}


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_expected(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("expected_output"), dict):
        raise ValueError(f"invalid expected fixture contract: {path}")
    expected = value["expected_output"]
    visible_text = expected.get("visible_text_examples")
    required_objects = expected.get("required_objects")
    if not isinstance(visible_text, list) or not isinstance(required_objects, list):
        raise ValueError(f"incomplete expected fixture contract: {path}")
    return {
        "expected_visible_text": visible_text,
        "supported_visible_text": visible_text,
        "expected_objects": required_objects,
        "supported_objects": required_objects,
        "forbidden_claims": list(FORBIDDEN_CLAIMS),
        "minimum_visible_text_recall": 0.5,
        "minimum_visible_text_precision": 1.0,
        "minimum_object_recall": 0.6,
        "minimum_object_precision": 1.0,
    }


def _canonical_schemas(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = (
        repo_root
        / "experiments/lmstudio/structured_matrix/schemas/vision/vision_schema_contracts.yaml"
    )
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("schemas"), dict):
        raise ValueError("invalid canonical vision schema contract")
    schemas = payload["schemas"]
    simple = schemas.get("simple_description")
    medium = schemas.get("medium_objects_text")
    if not isinstance(simple, dict) or not isinstance(medium, dict):
        raise ValueError("canonical strict vision schemas are missing")
    return simple, medium


def build_launch_manifest(repo_root: Path) -> Path:
    dataset_root = repo_root / "experiments/lmstudio/structured_matrix/datasets/image"
    launch_root = repo_root / "experiments/lmstudio/strict_vision"
    fixture_root = launch_root / "fixtures"
    simple_schema, medium_schema = _canonical_schemas(repo_root)
    fixtures: list[dict[str, object]] = []
    for fixture_id in FIXTURE_IDS:
        built = build_strict_vision_fixture(
            dataset_root / "fixtures" / f"{fixture_id}.webp",
            output_dir=fixture_root,
            fixture_id=fixture_id,
            max_side=1024,
        )
        fixtures.append(
            {
                "fixture_id": fixture_id,
                "path": f"fixtures/{built.path.name}",
                "sha256": built.sha256,
                "source_sha256": built.source_sha256,
                "width": built.width,
                "height": built.height,
                "ground_truth": _load_expected(
                    dataset_root / "expected" / f"{fixture_id}.expected.yaml"
                ),
            }
        )

    calls: list[dict[str, object]] = [
        {
            "ordinal": 1,
            "call_id": "sv-01-matrix-text-preflight",
            "model_id": MODELS[0],
            "fixture_id": None,
            "kind": "text_preflight",
            "schema_name": "simple_description",
            "condition": "always",
            "depends_on_call_ids": [],
        }
    ]
    ordinal = 2
    for model_id, short_name in zip(MODELS, MODEL_SHORT_NAMES, strict=True):
        calls.append(
            {
                "ordinal": ordinal,
                "call_id": f"sv-{ordinal:02d}-{short_name}-native-ui",
                "model_id": model_id,
                "fixture_id": FIXTURE_IDS[0],
                "kind": "native_plain",
                "schema_name": None,
                "condition": "always",
                "depends_on_call_ids": [],
            }
        )
        ordinal += 1
        simple_call_ids: list[str] = []
        for fixture_id in FIXTURE_IDS:
            call_id = f"sv-{ordinal:02d}-{short_name}-simple-{fixture_id}"
            calls.append(
                {
                    "ordinal": ordinal,
                    "call_id": call_id,
                    "model_id": model_id,
                    "fixture_id": fixture_id,
                    "kind": "simple_description",
                    "schema_name": "simple_description",
                    "condition": "always",
                    "depends_on_call_ids": [],
                }
            )
            simple_call_ids.append(call_id)
            ordinal += 1
        for fixture_id in FIXTURE_IDS:
            calls.append(
                {
                    "ordinal": ordinal,
                    "call_id": f"sv-{ordinal:02d}-{short_name}-medium-{fixture_id}",
                    "model_id": model_id,
                    "fixture_id": fixture_id,
                    "kind": "medium_objects_text",
                    "schema_name": "medium_objects_text",
                    "condition": "model_simple_schema_accepted",
                    "depends_on_call_ids": simple_call_ids,
                }
            )
            ordinal += 1
        calls.append(
            {
                "ordinal": ordinal,
                "call_id": f"sv-{ordinal:02d}-{short_name}-repeat-ui",
                "model_id": model_id,
                "fixture_id": FIXTURE_IDS[0],
                "kind": "simple_repeat",
                "schema_name": "simple_description",
                "condition": "first_three_model_simple_accepted",
                "depends_on_call_ids": simple_call_ids,
            }
        )
        ordinal += 1
    if len(calls) != 41 or ordinal != 42:
        raise ValueError("strict vision schedule must contain exactly 41 candidate rows")

    prompt_records = [
        {"name": name, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
        for name, text in PROMPTS.items()
    ]
    manifest = {
        "manifest_version": 1,
        "serial": True,
        "retry_policy": "off",
        "max_calls": 40,
        "models": list(MODELS),
        "fixture_builder": {
            "implementation": "lmstudio_labkit.strict_vision.build_strict_vision_fixture",
            "pillow_version": pillow_version,
            "max_side": 1024,
            "format": "PNG",
            "resample": "LANCZOS",
            "compress_level": 9,
        },
        "strict_request": {
            "endpoint": "/v1/chat/completions",
            "context_length": 8192,
            "max_tokens": 1024,
            "temperature": 0.0,
            "stream": False,
            "reasoning_effort": "none",
            "enable_thinking": False,
        },
        "prompts": prompt_records,
        "conditional_gates": {
            "route_rejection": "stop_all_after_first_e2b_schema_image",
            "simple_hard_failure": "block_model_medium_and_repeat",
            "semantic_failure": "block_model_admission",
            "finish_reason": "require_stop",
            "reasoning": "require_observed_zero",
            "cleanup": "require_global_zero",
        },
        "fixtures": fixtures,
        "schemas": [
            {
                "name": "simple_description",
                "sha256": _canonical_digest(simple_schema),
                "body": simple_schema,
            },
            {
                "name": "medium_objects_text",
                "sha256": _canonical_digest(medium_schema),
                "body": medium_schema,
            },
        ],
        "calls": calls,
    }
    output_path = launch_root / "launch_manifest.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    output = build_launch_manifest(repo_root)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"{output.relative_to(repo_root)} sha256:{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
