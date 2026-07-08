from __future__ import annotations

import csv
import json
import re
import socket
from pathlib import Path

import pytest
import yaml

from tools import lmstudio_benchmark, lmstudio_lab

FORBIDDEN_SNIPPETS = (
    '"prompt":',
    '"messages":',
    '"message":',
    '"content":',
    '"response":',
    '"response_text":',
    '"text":',
    '"file_path":',
    '"path":',
    "Synthetic normalized block",
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:[\\/][^\"\r\n]+"),
    re.compile(r"\\\\[^\"\r\n]+[\\/][^\"\r\n]+"),
    re.compile(r"/(?:Users|home)/[^\"\r\n]+"),
)


def _write_matrix_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "structured_matrix.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "structured_matrix_ci",
                "hardware_profile": "synthetic_ci",
                "models": [
                    {
                        "key": "gemma4_e2b_q4km",
                        "load": {"context_length": [8192], "parallel": [1]},
                    }
                ],
                "modes": ["json_schema_single"],
                "datasets": ["blocks_json_small"],
                "repeats": 1,
                "warmup_runs": 0,
                "matrix": {
                    "modality": ["text"],
                    "language": ["en_en", "ru_ru"],
                    "structure_complexity": ["simple"],
                    "volume": ["single"],
                    "schema_variant": ["baseline_loose"],
                    "retry_policy": ["off"],
                },
                "privacy": {
                    "store_prompt_text": False,
                    "store_response_text": False,
                    "store_prompt_hash": True,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path


def _assert_public_safe(text: str, *, project_root: Path) -> None:
    for snippet in FORBIDDEN_SNIPPETS:
        assert snippet.casefold() not in text.casefold()
    for value in (
        str(project_root),
        project_root.as_posix(),
        str(Path.home()),
        Path.home().as_posix(),
    ):
        if value:
            assert value not in text
    for pattern in ABSOLUTE_PATH_PATTERNS:
        assert pattern.search(text) is None


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _assert_public_safe(line, project_root=Path(__file__).resolve().parents[2])
        row = json.loads(line)
        assert isinstance(row, dict)
        assert row["schema_version"] == lmstudio_lab.SCHEMA_VERSION
        rows.append(row)
    return rows


def test_build_structured_matrix_plan_expands_config_axes() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "experiments" / "lmstudio" / "examples" / "dry_run_minimal.yaml"

    plan = lmstudio_lab.build_structured_matrix_plan(config_path, run_id="matrix-plan")

    assert isinstance(plan, lmstudio_lab.StructuredMatrixPlan)
    assert plan.planner_summary()["cell_count"] == 1
    assert plan.cells[0]["cell_id"] == "cell_00001"
    assert plan.cells[0]["model_key"] == "gemma4_12b_qat"
    assert plan.cells[0]["dataset_id"] == "blocks_json_small"
    assert plan.cells[0]["context_tier"] == "8192"
    assert plan.cells[0]["raw_prompt_response_stored"] is False
    assert "request_metadata_hash" in plan.cells[0]
    serialized_cell = json.dumps(plan.cells[0], sort_keys=True).casefold()
    assert '"prompt":' not in serialized_cell
    assert '"response":' not in serialized_cell


def test_plan_matrix_cli_writes_privacy_safe_artifacts(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = _write_matrix_config(tmp_path)

    exit_code = lmstudio_benchmark.main(
        [
            "plan-matrix",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "matrix-plan-ci",
        ]
    )

    assert exit_code == 0
    run_dir = tmp_path / "run_matrix-plan-ci_structured_matrix_ci"
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == set(
        lmstudio_lab.MATRIX_PLAN_OUTPUT_FILE_NAMES
    )

    planner_summary = json.loads((run_dir / "planner_summary.json").read_text(encoding="utf-8"))
    assert planner_summary["cell_count"] == 2
    assert planner_summary["offline_mode"] is True
    assert planner_summary["fake_runner"] is False
    assert planner_summary["raw_prompt_response_stored"] is False

    cells = _read_jsonl(run_dir / "matrix_cells.jsonl")
    assert len(cells) == 2
    assert {cell["language"] for cell in cells} == {"en_en", "ru_ru"}
    assert all(cell["status"] == "planned" for cell in cells)

    with (run_dir / "cell_summary.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(lmstudio_lab.MATRIX_CELL_FIELDNAMES)
        summary_rows = list(reader)
    assert len(summary_rows) == 2
    assert {row["status"] for row in summary_rows} == {"planned"}

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["violation_count"] == 0
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    _assert_public_safe(report_text, project_root=project_root)
    assert "LM Studio API: not called" in report_text
    assert "raw prompts: not stored" in report_text


def test_run_matrix_fake_cli_writes_validation_and_summary_artifacts(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_path = _write_matrix_config(tmp_path)

    exit_code = lmstudio_benchmark.main(
        [
            "run-matrix",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "matrix-fake-ci",
            "--fake",
        ]
    )

    assert exit_code == 0
    run_dir = tmp_path / "run_matrix-fake-ci_structured_matrix_ci"
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == set(
        lmstudio_lab.MATRIX_FAKE_RUN_OUTPUT_FILE_NAMES
    )

    records = _read_jsonl(run_dir / "cell_results.jsonl")
    assert len(records) == 2
    assert all(record["fake_runner"] is True for record in records)
    assert all(record["offline_mode"] is True for record in records)
    assert all(record["raw_prompt_response_stored"] is False for record in records)
    assert all(record["json_parse_pass"] is True for record in records)
    assert all(record["schema_pass"] is True for record in records)
    assert all(record["business_pass"] is True for record in records)
    assert all(str(record["output_hash"]).startswith("sha256:") for record in records)
    assert "Synthetic normalized block" not in (run_dir / "cell_results.jsonl").read_text(
        encoding="utf-8"
    )

    with (run_dir / "model_summary.csv").open(encoding="utf-8", newline="") as handle:
        model_rows = list(csv.DictReader(handle))
    assert model_rows == [
        {
            "run_id": "matrix-fake-ci",
            "model_key": "gemma4_e2b_q4km",
            "planned_cells": "2",
            "completed_cells": "2",
            "business_pass_count": "2",
            "business_pass_rate": "1.0",
        }
    ]

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["violation_count"] == 0
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    _assert_public_safe(report_text, project_root=project_root)
    assert "# LM Studio Lab Structured Matrix Fake Run" in report_text
    assert "completed_cells: `2`" in report_text


def test_run_matrix_requires_fake_mode(tmp_path: Path) -> None:
    config_path = _write_matrix_config(tmp_path)

    with pytest.raises(ValueError, match="requires --fake"):
        lmstudio_benchmark.main(
            [
                "run-matrix",
                str(config_path),
                "--output-root",
                str(tmp_path),
                "--run-id",
                "matrix-real-blocked",
            ]
        )

    assert not (tmp_path / "run_matrix-real-blocked_structured_matrix_ci").exists()


def test_matrix_plan_and_fake_run_stay_offline_when_network_calls_are_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_matrix_config(tmp_path)

    def _fail_network(*args, **kwargs):
        raise AssertionError("network access forbidden in matrix harness")

    monkeypatch.setattr(socket, "create_connection", _fail_network)
    monkeypatch.setattr(socket.socket, "connect", _fail_network, raising=True)
    monkeypatch.setattr(socket.socket, "connect_ex", _fail_network, raising=True)

    assert (
        lmstudio_benchmark.main(
            [
                "plan-matrix",
                str(config_path),
                "--output-root",
                str(tmp_path),
                "--run-id",
                "matrix-offline-plan",
            ]
        )
        == 0
    )
    assert (
        lmstudio_benchmark.main(
            [
                "run-matrix",
                str(config_path),
                "--output-root",
                str(tmp_path),
                "--run-id",
                "matrix-offline-fake",
                "--fake",
            ]
        )
        == 0
    )
