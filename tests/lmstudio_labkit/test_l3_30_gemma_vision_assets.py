from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / "experiments/lmstudio/structured_matrix/datasets/image/gemma_vision"
MANIFEST_PATH = ASSET_ROOT / "manifest.yaml"

FORBIDDEN_METADATA_STRINGS = (
    "/home/",
    "C:\\",
    "sk-",
    "ghp_",
    "AIza",
)


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


def _expected_payload(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_gemma_vision_manifest_has_ten_valid_public_safe_assets() -> None:
    manifest = _manifest()

    assert manifest["manifest_id"] == "gemma_vision_l3_30_asset_pack"
    assert manifest["asset_count"] == 10
    assert set(manifest["content_languages"]) == {"ru_ru", "en_en", "ru_en_mixed"}
    assert set(manifest["output_languages"]) == {"ru_ru", "en_en"}
    assert set(manifest["resize_profiles"]) == {"max_side_1024", "max_side_512"}

    for asset in manifest["assets"]:
        fixture_path = ROOT / asset["fixture_path"]
        expected_path = ROOT / asset["expected_path"]
        assert fixture_path.exists(), asset["fixture_path"]
        assert expected_path.exists(), asset["expected_path"]
        assert asset["public_safe"] is True
        assert asset["contains_real_person"] is False
        assert asset["contains_private_data"] is False
        assert asset["contains_credentials"] is False
        assert asset["source"] == {
            "owner_provided": True,
            "sanitized": True,
            "license_or_origin": "owner_public_safe",
        }
        assert asset["resize_policy"]["crop"] is False
        assert asset["resize_policy"]["primary_max_side"] == 1024
        assert asset["resize_policy"]["fallback_max_side"] == 512
        assert asset["resize_policy"]["jpeg_quality"] == 85


def test_gemma_vision_expected_yaml_contract_exists_for_every_asset() -> None:
    manifest = _manifest()
    required_forbidden = {
        "identifies_real_person",
        "invents_credentials",
        "reads_hidden_text",
        "claims_sensitive_attributes",
    }

    for asset in manifest["assets"]:
        expected = _expected_payload(ROOT / asset["expected_path"])
        assert expected["image_id"] == asset["image_id"]
        assert expected["image_type"] == asset["image_type"]
        assert expected["public_safe"] is True
        assert expected["content_language"] == asset["content_language"]
        assert expected["expected_visible_text"]
        assert expected["expected_objects"]
        assert set(expected["forbidden_claims"]) == required_forbidden
        assert expected["task_expectations"]["simple_description"]["required_fields"] == [
            "description",
            "visible_text",
            "warnings",
        ]
        assert expected["task_expectations"]["complex_layout_extraction"]["prepared_only"] is True


def test_gemma_vision_manifest_has_explicit_coverage_gaps_without_invention() -> None:
    manifest = _manifest()
    coverage = manifest["coverage"]

    assert coverage["screencast_frame"]["coverage_status"] == "missing"
    assert coverage["screencast_frame"]["image_ids"] == []
    for _image_type, payload in coverage.items():
        assert payload["coverage_status"] in {"covered", "missing"}
        if payload["coverage_status"] == "covered":
            assert payload["image_ids"]


def test_gemma_vision_metadata_has_no_private_path_or_secret_terms() -> None:
    text = MANIFEST_PATH.read_text(encoding="utf-8").casefold()
    for needle in FORBIDDEN_METADATA_STRINGS:
        assert needle.casefold() not in text
