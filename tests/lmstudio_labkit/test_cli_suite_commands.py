from __future__ import annotations

import json
from pathlib import Path

from lmstudio_labkit.cli import main


def write_config(path: Path) -> None:
    path.write_text(
        """
run_id: cli_suite_matrix
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
safety:
  max_requests: 1
""".lstrip(),
        encoding="utf-8",
    )


def write_suite(path: Path, config: Path) -> None:
    path.write_text(
        f"""
suite_id: cli_suite
configs:
  - config: {config.name}
""".lstrip(),
        encoding="utf-8",
    )


def test_cli_preflight_and_suite_commands(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config)
    write_suite(suite, config)

    assert main(["preflight", "--config", str(config)]) == 0
    preflight_payload = json.loads(capsys.readouterr().out)
    assert preflight_payload["status"] == "pass"

    assert main(["preflight-suite", "--suite", str(suite)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"

    assert main(["plan-suite", "--suite", str(suite), "--output-root", str(tmp_path / "plan")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"

    assert (
        main(
            [
                "run-suite",
                "--suite",
                str(suite),
                "--output-root",
                str(tmp_path / "run"),
                "--profile",
                "offline-fake",
                "--resume",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "pass"

    assert main(["summarize-suite", "--suite-run-dir", str(tmp_path / "run" / "cli_suite")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
