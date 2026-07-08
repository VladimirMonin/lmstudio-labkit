from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGE_ROOT = ROOT / "experiments" / "lmstudio" / "structured_matrix" / "datasets" / "image"
MANIFEST = IMAGE_ROOT / "manifest.yaml"
EXPECTED_TYPES = {
    "ui_screenshot",
    "code_screenshot",
    "document_table",
    "chart_graph",
    "people_scene",
    "mixed_text_image",
}


def load_manifest() -> dict[str, Any]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for key, item in value.items():
            strings.extend(all_strings(key))
            strings.extend(all_strings(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(all_strings(item))
        return strings
    return []


def test_image_manifest_points_to_deterministic_synthetic_pngs() -> None:
    manifest = load_manifest()
    fixtures = manifest["fixtures"]

    assert manifest["asset_status"] == "synthetic_public_safe"
    assert manifest["fixture_generator"] == "fixtures/generate_synthetic_fixtures.py"
    assert (IMAGE_ROOT / manifest["fixture_generator"]).is_file()
    assert {fixture["image_type"] for fixture in fixtures} == EXPECTED_TYPES
    assert {fixture["image_id"] for fixture in fixtures} == EXPECTED_TYPES

    for fixture in fixtures:
        path = IMAGE_ROOT / fixture["file_name"]
        assert path.is_file(), fixture["image_id"]
        assert path.suffix == ".png"
        assert not Path(fixture["file_name"]).is_absolute()
        assert ".." not in Path(fixture["file_name"]).parts
        assert fixture["status"] == "ready"
        assert fixture["synthetic"] is True
        assert png_size(path) == (fixture["original_width"], fixture["original_height"])
        assert (fixture["resized_width"], fixture["resized_height"]) == (
            fixture["original_width"],
            fixture["original_height"],
        )
        assert fixture["image_bytes_before"] == path.stat().st_size
        assert fixture["image_bytes_after"] == path.stat().st_size
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert fixture["image_hash"] == f"sha256:{digest}"


def test_image_manifest_records_resize_and_privacy_metadata_without_raw_paths() -> None:
    manifest = load_manifest()

    assert manifest["resize_policy"] == {
        "mode": "fit_max_side",
        "crop": False,
        "default_max_side": 1024,
        "fallback_max_side": 512,
        "jpeg_quality": 85,
        "hash_algorithm": "sha256",
        "path_policy": "store_repo_relative_paths_only",
    }
    assert manifest["privacy"] == {
        "synthetic": True,
        "raw_public_safe": True,
        "private_paths_stored": False,
        "real_people_stored": False,
        "source_application_screenshots_stored": False,
    }
    assert "image_hash" in manifest["report_fields"]

    strings = all_strings(manifest)
    assert not any("/home/" in item or "C:\\" in item or "\\Users\\" in item for item in strings)
    assert not any(
        Path(item).is_absolute() for item in strings if item.endswith((".png", ".yaml", ".py"))
    )
