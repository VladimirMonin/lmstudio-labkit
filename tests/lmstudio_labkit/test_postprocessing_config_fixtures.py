from __future__ import annotations

import json
from pathlib import Path

from lmstudio_labkit.benchmarks import BenchmarkConfig, plan_matrix

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (
    ROOT
    / "experiments/lmstudio/structured_matrix/configs/matrix.l3_20_postprocessing_tiny.offline.yaml"
)


def test_l3_20_tiny_config_uses_source_fixtures_and_prompt_templates() -> None:
    config = BenchmarkConfig.from_file(CONFIG)
    assert all(task.source_fixture for task in config.tasks)
    assert all(task.prompt_template for task in config.tasks)
    assert all(task.source_text for task in config.tasks)
    assert all(task.prompt_template_hash for task in config.tasks)
    assert all(task.fixture_text_hash for task in config.tasks)
    assert "Synthetic fixture task" not in config.tasks[0].prompt
    assert "Input transcript:" in config.tasks[0].prompt


def test_safe_request_metadata_does_not_store_raw_source_or_prompt_template() -> None:
    config = BenchmarkConfig.from_file(CONFIG)
    plan = plan_matrix(config)
    request_metadata = plan.cells[0].to_request_plan().envelope.safe_metadata()
    encoded = json.dumps(request_metadata, ensure_ascii=False)

    assert "сегодня мы поговорим" not in encoded
    assert "Return JSON only" not in encoded
    assert request_metadata["metadata"]["source_fixture_id"]
    assert request_metadata["metadata"]["fixture_text_hash"]
    assert request_metadata["metadata"]["prompt_template_hash"]
    assert request_metadata["response_contract"]["source_text_hash"]
