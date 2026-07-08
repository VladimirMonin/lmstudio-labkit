from __future__ import annotations

import json
from pathlib import Path


def write_config(path: Path, run_id: str, *, fake_mode: str = "valid") -> None:
    path.write_text(
        f"""
run_id: {run_id}
models:
  - model_key: fake
    model_id: fake/text
    supported_modalities: [text]
    supported_context_tiers: [8192]
tasks:
  - task_id: t
    family: simple_flat
    modality: text
    language: en_en
    prompt: Synthetic prompt
    fake_mode: {fake_mode}
    expected_output:
      id: ok
      text: Synthetic response
axes:
  modality: [text]
  language: [en_en]
  structure_complexity: [simple]
  volume: [single]
  context_tier: [8192]
  schema_variant: [baseline_loose]
  retry_policy: [off]
safety:
  max_requests: 1
""".lstrip(),
        encoding="utf-8",
    )


def write_suite(path: Path, config: Path, *, entry_id: str | None = None) -> None:
    id_line = f"    id: {entry_id}\n" if entry_id else ""
    path.write_text(
        f"""
suite_id: suite_test
stop_on_failure: true
configs:
  - path: {config.name}
{id_line}    required: true
""".lstrip(),
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
