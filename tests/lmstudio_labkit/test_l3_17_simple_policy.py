from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "experiments" / "lmstudio" / "structured_matrix" / "configs"
WAVE1_REMOTE_CONFIG = CONFIG_ROOT / "matrix.l3_17_text_quality_remote.e2b_e4b.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_l3_17_remote_simple_tasks_use_warning_length_ratio_policy() -> None:
    payload = _load_yaml(WAVE1_REMOTE_CONFIG)
    simple_tasks = [task for task in payload["tasks"] if task["structure_complexity"] == "simple"]

    assert simple_tasks
    for task in simple_tasks:
        assert task["length_ratio_policy"] == {"mode": "warning"}


def test_l3_17_remote_medium_and_complex_tasks_keep_hard_length_ratio_policy() -> None:
    payload = _load_yaml(WAVE1_REMOTE_CONFIG)
    hard_tasks = [task for task in payload["tasks"] if task["structure_complexity"] != "simple"]

    assert hard_tasks
    for task in hard_tasks:
        assert task["length_ratio_policy"] == {"mode": "hard"}
