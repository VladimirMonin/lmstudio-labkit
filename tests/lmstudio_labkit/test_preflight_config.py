from __future__ import annotations

from pathlib import Path

from lmstudio_labkit.preflight import preflight_config


def write_config(path: Path, *, extra_axes: str = "") -> None:
    path.write_text(
        f"""
run_id: preflight_ok
models:
  - model_key: fake
    model_id: fake/text
    supported_modalities: [text]
tasks:
  - task_id: t
    family: simple_flat
    modality: text
    language: en_en
    prompt: Synthetic prompt
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
{extra_axes}
safety:
  max_requests: 1
""".lstrip(),
        encoding="utf-8",
    )


def test_preflight_config_passes_without_network(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    write_config(config)

    result = preflight_config(config)

    assert result.status == "pass"
    assert result.run_id == "preflight_ok"
    assert result.planned_request_count == 1
    assert result.lmstudio is None
    assert result.checks["chunk_count_axis_absent"] == "pass"


def test_preflight_rejects_chunk_count_axis(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    write_config(config, extra_axes="  chunk_count: [1]\n")

    result = preflight_config(config)

    assert result.status == "fail"
    assert "chunk_count" in result.checks["error"]
