from __future__ import annotations

import csv
import json
import re
import socket
from pathlib import Path

import pytest
import yaml

from tools import lmstudio_benchmark, lmstudio_lab

EXPECTED_SUMMARY_HEADERS = list(lmstudio_benchmark.SUMMARY_FIELDNAMES)
FORBIDDEN_JSON_SNIPPETS = (
    '"prompt":',
    '"messages":',
    '"message":',
    '"content":',
    '"response":',
    '"transcript":',
    '"file_path":',
    '"path":',
    '"rawBody":',
    '"raw_body":',
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:[\\/][^\"\r\n]+"),
    re.compile(r"\\\\[^\"\r\n]+[\\/][^\"\r\n]+"),
    re.compile(r"/(?:Users|home)/[^\"\r\n]+"),
)


def _assert_no_private_paths(text: str, *, project_root: Path) -> None:
    known_private_values = {
        str(project_root),
        project_root.as_posix(),
        str(Path.home()),
        Path.home().as_posix(),
        str(project_root / ".venv"),
        (project_root / ".venv").as_posix(),
    }
    for value in known_private_values:
        if value:
            assert value not in text
    for pattern in ABSOLUTE_PATH_PATTERNS:
        assert pattern.search(text) is None


def _read_jsonl_objects(path: Path) -> list[dict[str, object]]:
    raw_text = path.read_text(encoding="utf-8")
    if not raw_text:
        return []

    rows: list[dict[str, object]] = []
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        for forbidden_snippet in FORBIDDEN_JSON_SNIPPETS:
            assert forbidden_snippet not in line
        for pattern in ABSOLUTE_PATH_PATTERNS:
            assert pattern.search(line) is None
        row = json.loads(line)
        assert isinstance(row, dict)
        assert row["schema_version"] == "1.0"
        assert "run_id" in row or "experiment_id" in row
        rows.append(row)
    return rows


def test_dry_run_creates_contract_output_layout(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "experiments" / "lmstudio" / "examples" / "dry_run_minimal.yaml"

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "ci-contract",
        ]
    )

    assert exit_code == 0

    run_dir = tmp_path / "run_ci-contract_dry_run_minimal"
    assert run_dir.exists()

    expected_files = {
        "environment.json",
        "experiment.yaml",
        "gpu_samples.csv",
        "load_configs.jsonl",
        "metrics.jsonl",
        "report.md",
        "requests.jsonl",
        "structured_errors.jsonl",
        "summary.csv",
    }
    assert expected_files == {path.name for path in run_dir.iterdir() if path.is_file()}

    source_text = config_path.read_text(encoding="utf-8")
    experiment_text = (run_dir / "experiment.yaml").read_text(encoding="utf-8")
    assert experiment_text == source_text

    experiment_payload = yaml.safe_load(experiment_text)
    assert experiment_payload["privacy"] == {
        "store_prompt_hash": True,
    }

    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    environment_payload = json.loads(environment_text)
    _assert_no_private_paths(environment_text, project_root=project_root)
    assert environment_payload["dry_run"] is True
    assert environment_payload["experiment_id"] == "dry_run_minimal"
    assert environment_payload["run_id"] == "ci-contract"
    assert environment_payload["schema_version"] == "1.0"
    assert environment_payload["platform_system"]
    assert environment_payload["platform_release"]
    assert environment_payload["platform_machine"]
    assert environment_payload["python_version"]
    assert "lmstudio_base_url" not in environment_payload
    assert "hardware_profile" not in environment_payload
    assert "cwd" not in environment_payload
    assert "sys_executable" not in environment_payload
    assert "env" not in environment_payload

    load_config_rows = _read_jsonl_objects(run_dir / "load_configs.jsonl")
    assert load_config_rows == [
        {
            "dry_run": True,
            "experiment_id": "dry_run_minimal",
            "load_config": {
                "context_length": 8192,
                "eval_batch_size": 512,
                "flash_attention": True,
                "parallel": 1,
            },
            "load_config_id": "load_0001",
            "model_key": "gemma4_12b_qat",
            "run_id": "ci-contract",
            "schema_version": "1.0",
        }
    ]

    request_rows = _read_jsonl_objects(run_dir / "requests.jsonl")
    assert len(request_rows) == 2
    assert request_rows[0]["phase"] == "warmup"
    assert request_rows[1]["phase"] == "measure"
    assert request_rows[0]["dataset_id"] == "blocks_json_small"
    assert request_rows[0]["dataset_chars"] == 3600
    assert request_rows[0]["dataset_hash"].startswith("sha256:")
    assert request_rows[0]["estimated_input_tokens"] == 1200
    assert request_rows[0]["actual_input_tokens"] is None
    assert request_rows[0]["estimate_error_ratio"] is None
    assert request_rows[0]["tokenizer_method"] == "heuristic"
    assert request_rows[0]["tokenizer_family"] == "generic"
    assert request_rows[0]["tokenizer_version"] == "1.0"
    assert "estimated_tokens" not in request_rows[0]

    metric_rows = _read_jsonl_objects(run_dir / "metrics.jsonl")
    assert len(metric_rows) == len(request_rows)
    assert all(row["tokens"]["actual_input_tokens"] is None for row in metric_rows)
    assert all(row["tokens"]["actual_output_tokens"] is None for row in metric_rows)
    assert all(row["endpoint_kind"] == "dry_run" for row in metric_rows)

    with (run_dir / "summary.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == EXPECTED_SUMMARY_HEADERS
        summary_rows = list(reader)
    assert len(summary_rows) == 1
    assert summary_rows[0]["dry_run"] == "True"
    assert summary_rows[0]["planned_requests"] == "2"
    assert summary_rows[0]["context_length"] == "8192"
    assert summary_rows[0]["dataset_chars"] == "3600"
    assert summary_rows[0]["estimated_input_tokens"] == "1200"
    assert summary_rows[0]["actual_input_tokens"] == ""
    assert summary_rows[0]["estimate_error_ratio"] == ""
    assert summary_rows[0]["tokenizer_method"] == "heuristic"
    assert summary_rows[0]["tokenizer_family"] == "generic"
    assert summary_rows[0]["tokenizer_version"] == "1.0"
    assert summary_rows[0]["parallel"] == "1"

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    _assert_no_private_paths(report_text, project_root=project_root)
    assert "dry_run_minimal" in report_text
    assert "ci-contract" in report_text
    assert "# LM Studio Lab Report" in report_text
    assert "## Run" in report_text
    assert "## Experiment" in report_text
    assert "## Environment" in report_text
    assert "## Datasets" in report_text
    assert "## Metrics Summary" in report_text
    assert "## Privacy" in report_text
    assert "## Notes" in report_text
    assert "Mode: dry-run" in report_text
    assert "Network: disabled" in report_text
    assert "LM Studio API: not called" in report_text
    assert "WVM runtime imports: forbidden" in report_text
    assert "store_prompt_text: `false`" in report_text
    assert "chars: `3600`" in report_text
    assert "estimated_input_tokens: `1200`" in report_text
    assert "actual_input_tokens: `null`" in report_text
    assert "estimate_error_ratio: `null`" in report_text
    assert "tokenizer: `heuristic/generic/1.0`" in report_text
    assert "metrics.jsonl" in report_text
    assert "estimated_tokens" not in report_text

    assert _read_jsonl_objects(run_dir / "structured_errors.jsonl") == []


def test_dry_run_preserves_experiment_yaml_bytes_with_crlf(tmp_path) -> None:
    config_path = tmp_path / "dry_run_crlf.yaml"
    config_bytes = (
        b"experiment_id: dry_run_crlf\r\n"
        b"models:\r\n"
        b"  - key: gemma4_12b_qat\r\n"
        b"    load:\r\n"
        b"      context_length: 8192\r\n"
        b"      eval_batch_size: 512\r\n"
        b"      flash_attention: true\r\n"
        b"      parallel: 1\r\n"
        b"modes:\r\n"
        b"  - json_schema_single\r\n"
        b"datasets:\r\n"
        b"  - blocks_json_small\r\n"
        b"repeats: 1\r\n"
        b"warmup_runs: 1\r\n"
        b"privacy:\r\n"
        b"  store_prompt_hash: true\r\n"
    )
    config_path.write_bytes(config_bytes)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "crlf-copy",
        ]
    )

    assert exit_code == 0

    run_dir = tmp_path / "run_crlf-copy_dry_run_crlf"
    assert (run_dir / "experiment.yaml").read_bytes() == config_bytes


def test_dry_run_fails_loudly_for_unsafe_experiment_copy(tmp_path) -> None:
    config_path = tmp_path / "unsafe.yaml"
    config_path.write_text(
        "\n".join(
            [
                "experiment_id: unsafe_copy",
                "models:",
                "  - key: qwen",
                "    load:",
                "      parallel:",
                "        - 1",
                "modes:",
                "  - json_schema_single",
                "datasets:",
                "  - blocks_json_small",
                "repeats: 1",
                "notes: C:/Users/tester/private/experiment.yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsafe experiment config"):
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--output-root",
                str(tmp_path),
                "--run-id",
                "unsafe-run",
            ]
        )

    run_dir = tmp_path / "run_unsafe-run_unsafe_copy"
    assert not run_dir.exists()


def test_dry_run_fails_for_duplicate_run_id_without_exposing_absolute_path(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "experiments" / "lmstudio" / "examples" / "dry_run_minimal.yaml"

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "duplicate-run",
        ]
    )
    assert exit_code == 0

    with pytest.raises(FileExistsError, match="run_id 'duplicate-run'") as exc_info:
        lmstudio_benchmark.main(
            [
                "run",
                str(config_path),
                "--output-root",
                str(tmp_path),
                "--run-id",
                "duplicate-run",
            ]
        )

    message = str(exc_info.value)
    assert "dry_run_minimal" in message
    assert str(tmp_path) not in message
    assert tmp_path.as_posix() not in message


def test_dry_run_stays_offline_when_network_calls_are_blocked(tmp_path, monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "experiments" / "lmstudio" / "examples" / "dry_run_minimal.yaml"

    def _fail_network(*args, **kwargs):
        raise AssertionError("network access forbidden in dry-run")

    monkeypatch.setattr(socket, "create_connection", _fail_network)
    monkeypatch.setattr(socket.socket, "connect", _fail_network, raising=True)
    monkeypatch.setattr(socket.socket, "connect_ex", _fail_network, raising=True)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "offline-guard",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "run_offline-guard_dry_run_minimal").exists()


def test_dry_run_with_structured_fixture_validation_writes_safe_artifacts(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "experiments" / "lmstudio" / "examples" / "dry_run_minimal.yaml"

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "structured-fixtures",
            "--validate-structured-fixtures",
        ]
    )

    assert exit_code == 0

    run_dir = tmp_path / "run_structured-fixtures_dry_run_minimal"
    assert run_dir.exists()
    assert (run_dir / "structured_validation_results.jsonl").exists()
    assert (run_dir / "structured_validation_summary.csv").exists()

    validation_batch = lmstudio_lab.validate_structured_fixture_manifest()
    validation_rows = _read_jsonl_objects(run_dir / "structured_validation_results.jsonl")
    assert len(validation_rows) == len(validation_batch.manifest.cases)
    assert {row["fixture_id"] for row in validation_rows} == {
        case.fixture_id for case in validation_batch.manifest.cases
    }

    forbidden_markers = {
        "Synthetic alpha fact.",
        "Synthetic beta fact.",
        "SYNTH_TRUNCATED_FACT",
        "SYNTH_REASONING_CONTENT",
        "SYNTH_HIDDEN_THINK",
        "Result preview:",
        '"normalized_text": "   "',
    }
    validation_text = (run_dir / "structured_validation_results.jsonl").read_text(encoding="utf-8")
    _assert_no_private_paths(validation_text, project_root=project_root)
    for marker in forbidden_markers:
        assert marker.casefold() not in validation_text.casefold()
    assert '"fixture_set_id": "structured_synthetic_v1"' in validation_text
    assert '"schema_name": "factual_blocks.v1"' in validation_text

    with (run_dir / "structured_validation_summary.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(lmstudio_lab.STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES)
        summary_rows = list(reader)

    assert summary_rows == [
        {
            "experiment_id": "dry_run_minimal",
            "run_id": "structured-fixtures",
            "mode": "offline_structured_validation",
            "dataset_id": "structured_synthetic_v1",
            "fixture_set_id": "structured_synthetic_v1",
            "status": "completed",
            "schema_version": "1.0",
            "total_count": "12",
            "json_parse_pass_count": "10",
            "json_parse_pass_rate": str(10 / 12),
            "schema_pass_count": "8",
            "schema_pass_rate": str(8 / 12),
            "business_pass_count": "1",
            "business_pass_rate": str(1 / 12),
            "ids_exact_pass_count": "5",
            "ids_exact_pass_rate": str(5 / 12),
            "reasoning_leak_count": "2",
            "finish_length_count": "1",
            "duplicate_id_count": "1",
            "empty_text_count": "1",
            "invalid_json_count": "2",
            "schema_error_count": "1",
        }
    ]

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    _assert_no_private_paths(report_text, project_root=project_root)
    assert "## Structured Validation" in report_text
    assert "Mode: offline structured validation" in report_text
    assert "LM Studio API: not called" in report_text
    assert (
        "schema_pass meaning: minimal schema-shape validation, not full JSON Schema Draft validation"
        in report_text
    )
    assert "structured_validation_results.jsonl" in report_text
    assert "structured_validation_summary.csv" in report_text
    assert "SYNTH_TRUNCATED_FACT" not in report_text
    assert "Synthetic alpha fact." not in report_text


def test_dry_run_with_structured_fixture_validation_stays_offline_when_network_calls_are_blocked(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "experiments" / "lmstudio" / "examples" / "dry_run_minimal.yaml"

    def _fail_network(*args, **kwargs):
        raise AssertionError("network access forbidden in dry-run")

    monkeypatch.setattr(socket, "create_connection", _fail_network)
    monkeypatch.setattr(socket.socket, "connect", _fail_network, raising=True)
    monkeypatch.setattr(socket.socket, "connect_ex", _fail_network, raising=True)

    exit_code = lmstudio_benchmark.main(
        [
            "run",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "offline-guard-structured",
            "--validate-structured-fixtures",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "run_offline-guard-structured_dry_run_minimal").exists()
