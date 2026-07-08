from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGE_ROOT = ROOT / "experiments" / "lmstudio" / "structured_matrix" / "datasets" / "image"
MANIFEST = IMAGE_ROOT / "manifest.yaml"
REQUIRED_EXPECTED_KEYS = {
    "image_id",
    "image_type",
    "status",
    "expected_output",
    "ground_truth",
    "privacy",
}


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_each_image_fixture_has_exact_expected_yaml_contract() -> None:
    manifest = load_yaml(MANIFEST)

    for fixture in manifest["fixtures"]:
        expected_path = IMAGE_ROOT / fixture["expected_file"]
        assert expected_path.is_file(), fixture["image_id"]
        assert not Path(fixture["expected_file"]).is_absolute()
        assert ".." not in Path(fixture["expected_file"]).parts

        expected = load_yaml(expected_path)
        assert set(expected) == REQUIRED_EXPECTED_KEYS
        assert expected["image_id"] == fixture["image_id"]
        assert expected["image_type"] == fixture["image_type"]
        assert expected["status"] == "ready"

        output = expected["expected_output"]
        assert isinstance(output["summary"], str) and output["summary"]
        assert isinstance(output["labels"], list) and fixture["image_type"] in output["labels"]
        assert isinstance(output["required_objects"], list) and output["required_objects"]
        assert isinstance(output["visible_text_policy"], str) and output["visible_text_policy"]

        ground_truth = expected["ground_truth"]
        assert ground_truth["identity_expected"] is False
        assert ground_truth["sensitive_attributes_expected"] is False
        assert ground_truth["private_product_expected"] is False
        assert str(ground_truth["scene_kind"]).startswith("synthetic_")

        assert expected["privacy"] == {"synthetic": True, "raw_public_safe": True}


def test_image_manifest_files_are_repo_relative_and_present() -> None:
    manifest = load_yaml(MANIFEST)

    webp_count = 0
    for fixture in manifest["fixtures"]:
        fixture_path = IMAGE_ROOT / fixture["file_name"]
        assert fixture_path.is_file(), fixture["image_id"]
        assert not Path(fixture["file_name"]).is_absolute()
        assert ".." not in Path(fixture["file_name"]).parts
        assert fixture["image_hash"].startswith("sha256:")
        if fixture_path.suffix == ".webp":
            webp_count += 1
            assert fixture.get("stored_format") == "webp"
            assert fixture.get("source_format") == "png"

    assert len(manifest["fixtures"]) == 18
    assert webp_count == 12


def test_image_task_manifest_uses_synthetic_fixture_contract() -> None:
    task = load_yaml(IMAGE_ROOT / "task.image_placeholder.yaml")

    assert task["task_id"] == "image_synthetic_readiness"
    assert task["modality"] == "image"
    assert task["privacy"] == {"synthetic": True, "raw_public_safe": True}
    assert task["expected"]["labels"] == ["synthetic_public_safe"]
    assert task["expected"]["image_ground_truth"] == {
        "asset_status": "synthetic_public_safe",
        "fixture_count": 18,
        "identity_expected": False,
        "sensitive_attributes_expected": False,
        "webp_fixture_count": 12,
    }
    assert "pending_user_assets" not in yaml.safe_dump(task, sort_keys=True)
