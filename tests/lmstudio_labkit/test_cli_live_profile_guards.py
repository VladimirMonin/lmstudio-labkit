from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from lmstudio_labkit.cli import main as cli_main

LIVE_CONFIG = "experiments/lmstudio/structured_matrix/configs/matrix.live_small_text.e2b_e4b.yaml"


def _write_config(path: Path, *, safety: dict[str, object]) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "run_id": "cli_live_guards",
                "models": [
                    {
                        "model_key": "fake",
                        "model_id": "fake/text",
                        "supported_modalities": ["text"],
                        "supported_context_tiers": ["8192"],
                    }
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
                "repeats": 1,
                "safety": safety,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_live_profile_requires_live_flag(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="profile live-small requires --live"):
        cli_main(
            [
                "run",
                "--config",
                LIVE_CONFIG,
                "--output-root",
                str(tmp_path),
                "--profile",
                "live-small",
            ]
        )


def test_live_profile_requires_config_live_true(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "offline.yaml",
        safety={"live": False, "allow_model_downloads": False},
    )

    with pytest.raises(SystemExit, match="safety.live=true"):
        cli_main(
            [
                "run",
                "--config",
                str(config),
                "--output-root",
                str(tmp_path),
                "--profile",
                "live-small",
                "--live",
            ]
        )


def test_live_profile_requires_allow_model_loads_when_config_allows_loads(
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit, match="CLI requires --allow-model-loads"):
        cli_main(
            [
                "run",
                "--config",
                LIVE_CONFIG,
                "--output-root",
                str(tmp_path),
                "--profile",
                "live-small",
                "--live",
            ]
        )
