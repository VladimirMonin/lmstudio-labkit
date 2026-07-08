from __future__ import annotations

from pathlib import Path

from lmstudio_labkit.benchmarks import BenchmarkConfig, plan_matrix, run_matrix
from lmstudio_labkit.datasets import TaskManifest


def test_task_manifest_transfers_axis_metadata_and_tags() -> None:
    manifest = TaskManifest.from_dict(
        {
            "task_id": "ru_blocks_many",
            "modality": "text",
            "language": "ru_ru",
            "structure_complexity": "medium",
            "volume": "many",
            "schema_family": "blocks",
            "schema_variant": "hardened_const",
            "tags": ["synthetic", "ci"],
            "input_ref": {},
            "expected": {"ids": [0, 1]},
            "privacy": {"synthetic": True, "raw_public_safe": True},
        }
    )

    task = manifest.to_task_spec()

    assert task.language == "ru_ru"
    assert task.structure_complexity == "medium"
    assert task.volume == "many"
    assert task.schema_family == "blocks"
    assert task.schema_variant == "hardened_const"
    assert task.tags == ("synthetic", "ci")


def test_plan_matrix_filters_incompatible_task_and_model_axes(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(
        {
            "run_id": "axis_filter",
            "models": [
                {
                    "model_key": "text_8k",
                    "model_id": "fake/text-8k",
                    "supported_modalities": ["text"],
                    "supported_context_tiers": ["8192"],
                }
            ],
            "tasks": [
                {
                    "task_id": "ru_blocks_many",
                    "family": "blocks",
                    "modality": "text",
                    "language": "ru_ru",
                    "structure_complexity": "medium",
                    "volume": "many",
                    "schema_family": "blocks",
                    "schema_variant": "hardened_const",
                    "prompt": "Synthetic fixture prompt.",
                    "expected_ids": [0, 1],
                    "expected_output": {"blocks": [{"id": 0, "text": "А"}, {"id": 1, "text": "Б"}]},
                }
            ],
            "axes": {
                "modality": ["text", "image"],
                "language": ["ru_ru", "en_en"],
                "structure_complexity": ["simple", "medium"],
                "volume": ["single", "many"],
                "context_tier": ["8192", "32768"],
                "schema_variant": ["hardened_const"],
                "retry_policy": ["off"],
            },
            "repeats": 1,
            "safety": {"max_context_tier": 32768},
        }
    )

    plan = plan_matrix(config)
    summary = plan.planner_summary()

    assert len(plan.cells) == 1
    assert {
        "modality": plan.cells[0].axes["modality"],
        "language": plan.cells[0].axes["language"],
        "structure_complexity": plan.cells[0].axes["structure_complexity"],
        "volume": plan.cells[0].axes["volume"],
        "context_tier": plan.cells[0].axes["context_tier"],
        "schema_variant": plan.cells[0].axes["schema_variant"],
        "retry_policy": plan.cells[0].axes["retry_policy"],
    } == {
        "modality": "text",
        "language": "ru_ru",
        "structure_complexity": "medium",
        "volume": "many",
        "context_tier": "8192",
        "schema_variant": "hardened_const",
        "retry_policy": "off",
    }
    assert summary["raw_cartesian_cell_count"] == 32
    assert summary["filtered_cell_count"] == 1
    assert summary["skipped_cell_count"] == 31
    assert summary["skip_reasons"]["unsupported_modality"] > 0
    assert summary["skip_reasons"]["language_mismatch"] > 0
    assert summary["skip_reasons"]["complexity_mismatch"] > 0
    assert summary["skip_reasons"]["volume_mismatch"] > 0
    assert summary["skip_reasons"]["unsupported_context_tier"] == 1

    artifacts = run_matrix(config, tmp_path)
    report = artifacts.report.read_text(encoding="utf-8")

    assert "## Skipped cells" in report
    assert "- unsupported_context_tier: `1`" in report
    assert "## Safety budget" in report


def test_experimental_task_keeps_cross_axis_cells() -> None:
    config = BenchmarkConfig.from_dict(
        {
            "run_id": "axis_experimental",
            "models": [
                {
                    "model_key": "text_8k",
                    "model_id": "fake/text-8k",
                    "supported_modalities": ["text"],
                    "supported_context_tiers": ["8192"],
                }
            ],
            "tasks": [
                {
                    "task_id": "experimental_probe",
                    "family": "blocks",
                    "modality": "text",
                    "language": "ru_ru",
                    "structure_complexity": "medium",
                    "volume": "many",
                    "schema_family": "blocks",
                    "tags": ["experimental"],
                    "prompt": "Synthetic fixture prompt.",
                    "expected_ids": [0],
                    "expected_output": {"blocks": [{"id": 0, "text": "А"}]},
                }
            ],
            "axes": {
                "modality": ["text", "image"],
                "language": ["ru_ru", "en_en"],
                "structure_complexity": ["simple", "medium"],
                "volume": ["single", "many"],
                "context_tier": ["8192", "32768"],
                "schema_variant": ["baseline_loose"],
                "retry_policy": ["off"],
            },
            "repeats": 1,
            "safety": {"max_context_tier": 32768},
        }
    )

    plan = plan_matrix(config)
    summary = plan.planner_summary()

    assert len(plan.cells) == 32
    assert summary["raw_cartesian_cell_count"] == 32
    assert summary["filtered_cell_count"] == 32
    assert summary["skipped_cell_count"] == 0
    assert summary["skip_reasons"] == {}
