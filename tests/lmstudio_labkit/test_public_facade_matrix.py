from __future__ import annotations

import json
from pathlib import Path

import yaml
from lmstudio_labkit.benchmarks import plan_matrix
from lmstudio_labkit.cli import main as cli_main
from lmstudio_labkit.validation import validate_response

from lmstudio_labkit import BenchmarkConfig, RequestEnvelope, run_matrix


def sample_config() -> dict:
    return {
        "run_id": "offline_matrix",
        "models": [
            {
                "model_key": "fake_text",
                "model_id": "fake/text",
                "supported_modalities": ["text", "image"],
            }
        ],
        "tasks": [
            {
                "task_id": "simple_flat_ru",
                "family": "simple_flat",
                "modality": "text",
                "prompt": "Extract the visible fields from this private-free fixture.",
                "schema": {
                    "type": "object",
                    "required": ["items"],
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["id", "text"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "text": {"type": "string"},
                                },
                            },
                        }
                    },
                },
                "expected_ids": ["a1"],
                "expected_output": {"items": [{"id": "a1", "text": "Русский ответ"}]},
            }
        ],
        "axes": {
            "modality": ["text"],
            "language": ["ru_ru"],
            "structure_complexity": ["simple"],
            "volume": ["single"],
            "context_tier": ["8192", "16384"],
            "schema_variant": ["baseline_loose", "hardened_const"],
            "retry_policy": ["off", "retry1"],
        },
        "repeats": 2,
    }


def test_public_facade_request_safe_metadata_excludes_raw_text() -> None:
    envelope = RequestEnvelope.text("req_1", "private prompt that must not be persisted")

    metadata = envelope.safe_metadata()

    assert "private prompt" not in json.dumps(metadata)
    assert metadata["text_inputs"][0]["char_count"] > 0
    assert len(metadata["text_inputs"][0]["text_hash"]) == 64


def test_matrix_planner_expands_config_axes() -> None:
    config = BenchmarkConfig.from_dict(sample_config())

    plan = plan_matrix(config)

    assert len(plan.cells) == 16
    assert {cell.axes["context_tier"] for cell in plan.cells} == {"8192", "16384"}
    assert {cell.axes["retry_policy"] for cell in plan.cells} == {"off", "retry1"}


def test_fake_runner_writes_privacy_safe_artifacts(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(sample_config())

    artifacts = run_matrix(config, tmp_path)

    assert artifacts.planner_summary.exists()
    assert artifacts.cell_results.exists()
    assert artifacts.cell_summary.exists()
    assert artifacts.model_summary.exists()
    assert artifacts.failure_summary.exists()
    assert artifacts.retry_summary.exists()
    assert artifacts.resource_summary.exists()
    assert artifacts.privacy_scan.exists()
    assert artifacts.report.exists()
    artifact_text = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in artifacts.as_dict().values()
        if Path(path).is_file()
    )
    assert "private-free fixture" not in artifact_text
    assert "raw_response" not in artifact_text
    privacy_scan = json.loads(artifacts.privacy_scan.read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"


def test_validators_cover_json_schema_ids_language_and_placeholders() -> None:
    config = BenchmarkConfig.from_dict(sample_config())
    contract = config.tasks[0]
    response_contract = plan_matrix(config).cells[0].to_request_plan().envelope.response_contract

    summary = validate_response(
        json.dumps(contract.expected_output, ensure_ascii=False), response_contract
    )
    bad_summary = validate_response('{"items":[{"id":"wrong","text":"TODO"}]}', response_contract)

    assert summary.status == "pass"
    assert bad_summary.status == "fail"
    assert {item.name for item in bad_summary.results if item.status == "fail"} >= {
        "id_exact",
        "no_placeholder_text",
    }


def test_cli_plan_run_summarize_compare(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(sample_config(), allow_unicode=True), encoding="utf-8")
    output_root = tmp_path / "runs"

    assert cli_main(["plan", "--config", str(config_path), "--output-root", str(output_root)]) == 0
    assert (output_root / "offline_matrix" / "planner_summary.json").exists()

    assert cli_main(["run", "--config", str(config_path), "--output-root", str(output_root)]) == 0
    assert cli_main(["summarize", "--run-dir", str(output_root / "offline_matrix")]) == 0
    printed = capsys.readouterr().out
    assert '"pass_count": 16' in printed

    assert (
        cli_main(
            [
                "compare",
                "--left-run-dir",
                str(output_root / "offline_matrix"),
                "--right-run-dir",
                str(output_root / "offline_matrix"),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert '"pass_rate": 0.0' in printed
