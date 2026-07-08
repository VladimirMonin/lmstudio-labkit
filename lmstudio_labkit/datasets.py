from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .benchmarks import TaskSpec
from .schema_builders import (
    build_blocks_schema,
    build_complex_nested_schema,
    build_image_complex_schema,
    build_image_medium_schema,
    build_image_simple_schema,
    build_simple_flat_schema,
)


@dataclass(frozen=True, slots=True)
class TaskManifest:
    task_id: str
    modality: str
    language: str
    structure_complexity: str
    volume: str
    schema_family: str
    schema_variant: str
    prompt_template: str
    input_ref: dict[str, Any]
    expected: dict[str, Any]
    privacy: dict[str, Any]
    fake_mode: str = "valid"
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TaskManifest:
        return cls(
            task_id=str(payload["task_id"]),
            modality=str(payload.get("modality", "text")),
            language=str(payload.get("language", "en_en")),
            structure_complexity=str(payload.get("structure_complexity", "simple")),
            volume=str(payload.get("volume", "single")),
            schema_family=str(payload.get("schema_family", "simple_flat")),
            schema_variant=str(payload.get("schema_variant", "baseline_loose")),
            prompt_template=str(payload.get("prompt_template", "default")),
            input_ref=dict(payload.get("input_ref", {})),
            expected=dict(payload.get("expected", {})),
            privacy=dict(payload.get("privacy", {})),
            fake_mode=str(payload.get("fake_mode", "valid")),
            tags=tuple(str(item) for item in payload.get("tags", [])),
        )

    def to_task_spec(self) -> TaskSpec:
        if not self.privacy.get("synthetic") or not self.privacy.get("raw_public_safe"):
            raise ValueError(f"Task manifest {self.task_id} is not public-safe")
        expected_ids = tuple(self.expected.get("ids", []))
        schema = _schema_for_manifest(self, expected_ids)
        expected_output = _expected_output_for_manifest(self, expected_ids)
        return TaskSpec(
            task_id=self.task_id,
            family=self.schema_family,
            modality=self.modality,
            language=self.language,
            structure_complexity=self.structure_complexity,
            volume=self.volume,
            prompt=f"synthetic fixture {self.task_id}",
            image_hash=self.input_ref.get("content_hash") if self.modality == "image" else None,
            schema=schema,
            schema_family=self.schema_family,
            schema_variant=self.schema_variant,
            tags=self.tags,
            expected_output=expected_output,
            expected_ids=expected_ids,
            image_ground_truth=self.expected.get("image_ground_truth"),
            fake_mode=self.fake_mode,
            min_length_ratio=self.expected.get("min_length_ratio"),
            max_length_ratio=self.expected.get("max_length_ratio"),
        )


def load_task_manifest(path: str | Path) -> TaskManifest:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Task manifest must be a mapping")
    return TaskManifest.from_dict(payload)


def load_task_manifests(root: str | Path) -> tuple[TaskManifest, ...]:
    base = Path(root)
    return tuple(load_task_manifest(path) for path in sorted(base.rglob("*.yaml")))


def load_task_specs(root: str | Path) -> tuple[TaskSpec, ...]:
    return tuple(manifest.to_task_spec() for manifest in load_task_manifests(root))


def _schema_for_manifest(manifest: TaskManifest, expected_ids: tuple[Any, ...]) -> dict[str, Any]:
    if manifest.schema_family == "blocks":
        return build_blocks_schema(expected_ids, manifest.schema_variant)
    if manifest.schema_family == "complex_nested":
        return build_complex_nested_schema(expected_ids)
    if manifest.schema_family == "image_simple":
        return build_image_simple_schema()
    if manifest.schema_family == "image_medium":
        return build_image_medium_schema()
    if manifest.schema_family == "image_complex":
        return build_image_complex_schema()
    return build_simple_flat_schema()


def _expected_output_for_manifest(
    manifest: TaskManifest, expected_ids: tuple[Any, ...]
) -> dict[str, Any]:
    if manifest.schema_family == "blocks":
        return {
            "blocks": [
                {"id": item, "text": f"Синтетический блок {item}"}
                if str(manifest.language).startswith("ru")
                else {"id": item, "text": f"Synthetic block {item}"}
                for item in expected_ids
            ]
        }
    if manifest.modality == "image":
        labels = manifest.expected.get("labels", ["synthetic"])
        return {"description": "Synthetic image fixture", "labels": labels}
    return {"id": expected_ids[0] if expected_ids else "item_0", "text": "Synthetic response"}


__all__ = ["TaskManifest", "load_task_manifest", "load_task_manifests", "load_task_specs"]
