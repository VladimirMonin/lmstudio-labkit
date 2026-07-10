from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "experiments" / "lmstudio" / "results_summaries" / "l3_38_reasoning_off_followup"


def _load_json(name: str) -> dict[str, object]:
    return json.loads((PACK / name).read_text(encoding="utf-8"))


def test_l3_38_public_evidence_pack_reconciles_every_lane() -> None:
    matrix = _load_json("admission_matrix.json")
    cells = matrix["generation_cells"]
    assert isinstance(cells, dict)
    assert cells == {
        "attempted": 13,
        "http_200_terminal": 13,
        "cleanup_verified": 13,
        "final_global_loaded_count": 0,
    }
    assert matrix["strict_route_generation_cells"] == 0

    lanes = matrix["lanes"]
    assert isinstance(lanes, dict)
    assert lanes["moe_26b_native_blocks"]["schema_valid"] == 4
    assert lanes["e4b_native_vision"]["image_grounding"].startswith("blocked_")
    assert lanes["12b_native_repeated_context"]["schema_valid"] == 0
    assert lanes["12b_openai_compatible_strict_json"]["attempted"] == 0


def test_l3_38_model_cards_are_route_and_task_specific() -> None:
    matrix = _load_json("admission_matrix.json")
    cards = matrix["model_cards"]
    assert isinstance(cards, dict)
    assert set(cards) == {
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
        "google/gemma-4-12b-qat",
        "google/gemma-4-26b-a4b-qat",
    }
    assert cards["google/gemma-4-e4b"]["recommended_reasoning"] == {
        "native bounded vision diagnostic": "off"
    }
    assert (
        cards["google/gemma-4-12b-qat"]["recommended_reasoning"]["OpenAI-compatible strict JSON"]
        == "undetermined"
    )
    assert cards["google/gemma-4-26b-a4b-qat"]["recommended_reasoning"] == {
        "native bounded blocks transformation": "off"
    }


def test_l3_38_privacy_manifest_has_no_raw_or_private_tracked_claims() -> None:
    privacy = _load_json("privacy_manifest.json")
    assert privacy["status"] == "pass"
    assert privacy["private_records_verified_nonempty"] == 13
    assert privacy["private_directory_mode"] == "0700"
    assert privacy["private_record_mode"] == "0600"
    assert privacy["private_paths_exposed"] is False
    assert privacy["l3_38_live_run_files_tracked"] == 0
    for field in (
        "raw_prompts_tracked",
        "raw_responses_tracked",
        "raw_reasoning_tracked",
        "raw_images_tracked",
    ):
        assert privacy[field] is False


def test_l3_38_markdown_points_to_machine_readable_pack() -> None:
    report = (PACK / "report.md").read_text(encoding="utf-8")
    matrix = (
        ROOT
        / "experiments"
        / "lmstudio"
        / "results_summaries"
        / "l3_31_l3_36_gemma_admission_matrix.md"
    ).read_text(encoding="utf-8")
    synthesis = (
        ROOT
        / "experiments"
        / "lmstudio"
        / "results_summaries"
        / "l3_36_gemma_family_final_synthesis.md"
    ).read_text(encoding="utf-8")
    assert "Total generation cells: 13" in report
    assert "Gemma family closure remains `partial_not_green`" in report
    assert "admission_matrix.json" in report
    assert "privacy_manifest.json" in report
    assert "l3_38_reasoning_off_followup/report.md" in matrix
    assert "## L3.38 affected model cards" in synthesis
    assert "l3_38_reasoning_off_followup/report.md" in synthesis
