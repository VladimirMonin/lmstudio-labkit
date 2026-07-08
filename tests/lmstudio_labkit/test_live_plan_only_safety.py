from __future__ import annotations

from pathlib import Path

import pytest
from lmstudio_labkit.benchmarks import BenchmarkConfig, write_matrix_plan


def _payload(*, safety: dict[str, object]) -> dict[str, object]:
    return {
        "run_id": "live_plan_only",
        "models": [
            {"model_key": "fake", "model_id": "fake/text", "supported_modalities": ["text"]}
        ],
        "tasks": [
            {
                "task_id": "t",
                "family": "blocks",
                "modality": "text",
                "prompt": "Synthetic",
                "schema_family": "blocks",
                "expected_ids": [0],
                "expected_output": {"blocks": [{"id": 0, "text": "Synthetic"}]},
            }
        ],
        "axes": {
            "modality": ["text"],
            "language": ["en_en"],
            "structure_complexity": ["simple"],
            "volume": ["single"],
            "context_tier": ["8192"],
            "schema_variant": ["hardened_const"],
            "retry_policy": ["off"],
        },
        "safety": safety,
    }


def test_live_plan_only_allows_model_load_flag_without_running_live(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(
        _payload(safety={"live": True, "allow_model_loads": True, "max_requests": 1})
    )

    artifacts = write_matrix_plan(config, tmp_path)

    summary = artifacts.planner_summary.read_text(encoding="utf-8")
    assert '"live": true' in summary
    assert artifacts.cell_results.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    ("safety", "message"),
    [
        ({"live": True, "allow_model_downloads": True}, "model downloads"),
        ({"live": True, "allow_raw_prompt_response_artifacts": True}, "raw prompt/response"),
        ({"live": True, "allow_image_live": True}, "image live"),
        ({"live": True, "allow_stress": True}, "stress/overnight"),
    ],
)
def test_live_plan_only_rejects_unsupported_live_shapes(
    tmp_path: Path, safety: dict[str, object], message: str
) -> None:
    config = BenchmarkConfig.from_dict(_payload(safety=safety))

    with pytest.raises(ValueError, match=message):
        write_matrix_plan(config, tmp_path)
