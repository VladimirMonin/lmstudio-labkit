from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGE_ROOT = ROOT / "experiments" / "lmstudio" / "structured_matrix" / "datasets" / "image"
MANIFEST = IMAGE_ROOT / "manifest.yaml"
EXPECTED_BASE_TYPES = {
    "ui_screenshot",
    "code_screenshot",
    "document_table",
    "chart_graph",
    "people_scene",
    "mixed_text_image",
}
EXPECTED_WEBP_TYPES = {
    "ui_settings_ru",
    "ui_queue_dashboard_ru",
    "code_python_editor",
    "terminal_logs",
    "slide_json_schema_ru",
    "document_table_products_ru",
    "chart_tasks_by_month_ru",
    "people_classroom_selected",
    "people_classroom_alt",
    "roadmap_timeline_2026_ru",
    "ui_style_guide_ru",
    "yoga_downward_dog",
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
    assert str(manifest["fixture_generator"]).startswith("fixtures/generate_synthetic_fixtures.py")
    assert (IMAGE_ROOT / "fixtures/generate_synthetic_fixtures.py").is_file()
    assert {
        fixture["image_type"] for fixture in fixtures
    } == EXPECTED_BASE_TYPES | EXPECTED_WEBP_TYPES
    assert {
        fixture["image_type"] for fixture in fixtures if fixture["file_name"].endswith(".png")
    } == EXPECTED_BASE_TYPES
    assert {
        fixture["image_type"] for fixture in fixtures if fixture["file_name"].endswith(".webp")
    } == EXPECTED_WEBP_TYPES

    for fixture in fixtures:
        path = IMAGE_ROOT / fixture["file_name"]
        assert path.is_file(), fixture["image_id"]
        assert path.suffix in {".png", ".webp"}
        assert not Path(fixture["file_name"]).is_absolute()
        assert ".." not in Path(fixture["file_name"]).parts
        assert fixture["status"] == "ready"
        assert fixture["synthetic"] is True
        assert (fixture["resized_width"], fixture["resized_height"]) == (
            fixture["original_width"],
            fixture["original_height"],
        )
        if path.suffix == ".png":
            assert png_size(path) == (fixture["original_width"], fixture["original_height"])
            assert fixture["image_bytes_before"] == path.stat().st_size
        else:
            assert fixture["stored_format"] == "webp"
            assert fixture["source_format"] == "png"
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
        "webp_quality": 85,
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
