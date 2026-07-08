from __future__ import annotations

import json
from pathlib import Path

from lmstudio_labkit.benchmarks import BenchmarkConfig, run_matrix

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (
    ROOT
    / "experiments/lmstudio/structured_matrix/configs/matrix.l3_20_postprocessing_tiny.offline.yaml"
)


def test_offline_run_writes_postprocessing_metrics_to_cell_results(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_file(CONFIG)
    artifacts = run_matrix(config, tmp_path)
    rows = [json.loads(line) for line in artifacts.cell_results.read_text().splitlines()]
    names = {result["name"] for row in rows for result in row["validation"]["results"]}

    assert "term_normalization_status" in names
    assert "punctuation_metrics" in names
    assert "paragraphing_metrics" in names
    assert "filler_cleanup" in names
    assert "no_new_facts_manual_review" in names
