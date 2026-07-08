from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (
    ROOT
    / "experiments/lmstudio/structured_matrix/configs/matrix.l3_20_postprocessing_screening.offline.yaml"
)


def test_task_intent_taxonomy_contains_required_values() -> None:
    payload = yaml.safe_load(CONFIG.read_text())
    intents = set(payload["axes"]["task_intent"])
    assert {
        "punctuation_restore",
        "paragraphing",
        "filler_cleanup",
        "term_normalization",
        "transcript_cleanup",
        "translation",
        "summary",
        "action_items",
        "mixed_postprocess",
    } >= intents
    assert {
        "punctuation_restore",
        "term_normalization",
        "transcript_cleanup",
        "paragraphing",
    } <= intents
