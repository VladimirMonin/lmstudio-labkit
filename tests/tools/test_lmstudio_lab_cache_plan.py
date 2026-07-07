from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools import lmstudio_benchmark, lmstudio_lab

FORBIDDEN_JSON_SNIPPETS = (
    '"prompt":',
    '"messages":',
    '"message":',
    '"content":',
    '"response":',
    '"transcript":',
    '"file_path":',
    '"path":',
    '"url":',
)
FORBIDDEN_REPORT_SNIPPETS = (
    "http://",
    "https://",
    "transcript",
    "messages",
    "file_path",
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:[\\/][^\"\r\n]+"),
    re.compile(r"\\\\[^\"\r\n]+[\\/][^\"\r\n]+"),
    re.compile(r"/(?:Users|home)/[^\"\r\n]+"),
)
FORBIDDEN_IMPORTS = {
    "requests",
    "httpx",
    "tools.lmstudio_lab.live_smoke",
    "tools.lmstudio_lab.managed_runner",
    "tools.lmstudio_lab.model_acquisition",
    "tools.lmstudio_lab.model_lifecycle",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sample_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_0_cache_stateful_gemma4_e2b_no_live.yaml"
    )


def _assert_no_private_paths(text: str) -> None:
    project_root = _project_root()
    known_private_values = {
        str(project_root),
        project_root.as_posix(),
        str(Path.home()),
        Path.home().as_posix(),
    }
    for value in known_private_values:
        if value:
            assert value not in text
    for pattern in ABSOLUTE_PATH_PATTERNS:
        assert pattern.search(text) is None


def _read_json(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    for forbidden_snippet in FORBIDDEN_JSON_SNIPPETS:
        assert forbidden_snippet not in text
    _assert_no_private_paths(text)
    payload = json.loads(text)
    assert isinstance(payload, dict)
    return payload


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    _assert_no_private_paths(text)
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        for forbidden_snippet in FORBIDDEN_JSON_SNIPPETS:
            assert forbidden_snippet not in line
        rows.append(json.loads(line))
    return rows


def test_load_cache_plan_config_returns_gemma_only_plan() -> None:
    config = lmstudio_lab.load_cache_plan_config(_sample_config_path())

    assert config.experiment_id == "l3_0_cache_stateful_gemma4_e2b_no_live"
    assert config.model_key == "gemma4_e2b_q4km"
    assert config.model_id == "google/gemma-4-e2b"
    assert config.context_window == 8192
    assert config.synthetic_dataset == "lecture_25k_synthetic_v1"
    assert config.root_context.estimated_tokens == 6250
    assert config.root_context.estimated_chars == 25000
    assert config.root_context.root_context_hash == "sha256:lecture_25k_synthetic_v1"
    assert config.branches == ("summary", "glossary", "timeline")
    assert config.variants == (
        "stateful_root_branch",
        "stateless_full_prefix",
        "compact_memory",
    )
    assert config.metric_fields == (
        "ttft_ms",
        "prompt_processing_ms",
        "total_latency_ms",
        "cached_tokens",
        "cache_proxy",
        "ram_peak_mb",
        "vram_peak_mb",
    )
    assert config.privacy.raw_material_storage_enabled() is False


def test_load_cache_plan_config_rejects_qwen_model_key(tmp_path: Path) -> None:
    config_path = tmp_path / "qwen_cache_plan.yaml"
    config_path.write_text(
        "\n".join(
            [
                "experiment_id: qwen_cache_plan",
                "model_key: qwen35_4b_q4km",
                "context_window: 8192",
                "synthetic_dataset: lecture_25k_synthetic_v1",
                "root_context:",
                "  estimated_tokens: 6250",
                "  estimated_chars: 25000",
                "  content_hash: sha256:test",
                "branches:",
                "  - summary",
                "  - glossary",
                "  - timeline",
                "variants:",
                "  - stateful_root_branch",
                "  - stateless_full_prefix",
                "  - compact_memory",
                "metrics:",
                "  - ttft_ms",
                "  - prompt_processing_ms",
                "  - total_latency_ms",
                "  - cached_tokens",
                "  - cache_proxy",
                "  - ram_peak_mb",
                "  - vram_peak_mb",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="model_key must be one of"):
        lmstudio_lab.load_cache_plan_config(config_path)


def test_load_cache_plan_config_accepts_16384_context_window(tmp_path: Path) -> None:
    source_text = _sample_config_path().read_text(encoding="utf-8")
    config_text = source_text.replace("context_window: 8192\n", "context_window: 16384\n")
    config_path = tmp_path / "context_window_16384.yaml"
    config_path.write_text(config_text, encoding="utf-8")

    config = lmstudio_lab.load_cache_plan_config(config_path)

    assert config.context_window == 16384


def test_load_cache_plan_config_rejects_unsupported_context_window(tmp_path: Path) -> None:
    source_text = _sample_config_path().read_text(encoding="utf-8")
    config_text = source_text.replace("context_window: 8192\n", "context_window: 65536\n")
    config_path = tmp_path / "unsupported_context_window.yaml"
    config_path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ValueError, match="context_window must be one of"):
        lmstudio_lab.load_cache_plan_config(config_path)


@pytest.mark.parametrize(
    ("field_name", "replacement_text", "error_text"),
    [
        (
            "branches",
            "branches:\n  - summary\n  - glossary\n",
            "branches must include: timeline",
        ),
        (
            "variants",
            ("variants:\n  - stateful_root_branch\n  - stateless_full_prefix\n"),
            "variants must include: compact_memory",
        ),
    ],
)
def test_load_cache_plan_config_rejects_missing_required_members(
    tmp_path: Path,
    field_name: str,
    replacement_text: str,
    error_text: str,
) -> None:
    source_text = _sample_config_path().read_text(encoding="utf-8")
    if field_name == "branches":
        original_text = "branches:\n  - summary\n  - glossary\n  - timeline\n"
    else:
        original_text = (
            "variants:\n  - stateful_root_branch\n  - stateless_full_prefix\n  - compact_memory\n"
        )
    config_text = source_text.replace(original_text, replacement_text)
    config_path = tmp_path / f"missing_{field_name}.yaml"
    config_path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ValueError, match=re.escape(error_text)):
        lmstudio_lab.load_cache_plan_config(config_path)


def test_plan_cache_creates_artifact_layout_and_preserves_yaml_bytes(tmp_path: Path) -> None:
    config_path = _sample_config_path()

    exit_code = lmstudio_benchmark.main(
        [
            "plan-cache",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "l3_0_no_live_gemma_e2b_20260705",
        ]
    )

    assert exit_code == 0

    run_dir = (
        tmp_path / "run_l3_0_no_live_gemma_e2b_20260705_l3_0_cache_stateful_gemma4_e2b_no_live"
    )
    assert run_dir.exists()
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == set(
        lmstudio_lab.CACHE_PLAN_RESULT_FILE_NAMES
    )
    assert (run_dir / "experiment.yaml").read_bytes() == config_path.read_bytes()

    environment_payload = _read_json(run_dir / "environment.json")
    assert environment_payload["dry_run"] is True
    assert environment_payload["network"] is False
    assert environment_payload["lmstudio_api_called"] is False
    assert environment_payload["measurement_status"] == "not_measured_no_live"
    assert environment_payload["production_default"] is False
    assert environment_payload["wvm_runtime_forbidden"] is True


def test_plan_cache_artifacts_are_privacy_safe(tmp_path: Path) -> None:
    config_path = _sample_config_path()
    run_id = "privacy_safe_cache_plan"

    exit_code = lmstudio_benchmark.main(
        [
            "plan-cache",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            run_id,
        ]
    )

    assert exit_code == 0

    run_dir = tmp_path / f"run_{run_id}_l3_0_cache_stateful_gemma4_e2b_no_live"
    for file_name in (
        "environment.json",
        "cache_plan.json",
        "planned_requests.jsonl",
        "metrics_schema.json",
    ):
        _assert_no_private_paths((run_dir / file_name).read_text(encoding="utf-8"))
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    _assert_no_private_paths(report_text)
    report_text_lower = report_text.lower()
    for forbidden_snippet in FORBIDDEN_REPORT_SNIPPETS:
        assert forbidden_snippet not in report_text_lower

    _read_json(run_dir / "environment.json")
    _read_json(run_dir / "cache_plan.json")
    _read_json(run_dir / "metrics_schema.json")
    _read_jsonl(run_dir / "planned_requests.jsonl")


def test_plan_cache_planned_rows_count_matches_root_plus_branch_variant_product(
    tmp_path: Path,
) -> None:
    config_path = _sample_config_path()
    run_id = "count_cache_plan"

    exit_code = lmstudio_benchmark.main(
        [
            "plan-cache",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            run_id,
        ]
    )
    assert exit_code == 0

    run_dir = tmp_path / f"run_{run_id}_l3_0_cache_stateful_gemma4_e2b_no_live"
    rows = _read_jsonl(run_dir / "planned_requests.jsonl")

    assert len(rows) == 10
    assert rows[0]["request_kind"] == "root_context"
    branch_rows = rows[1:]
    assert all(row["request_kind"] == "branch" for row in branch_rows)
    assert {row["branch_id"] for row in branch_rows} == {
        "summary",
        "glossary",
        "timeline",
    }
    assert {row["variant_id"] for row in branch_rows} == {
        "stateful_root_branch",
        "stateless_full_prefix",
        "compact_memory",
    }


def test_plan_cache_artifacts_declare_no_kv_proof_and_not_measured_no_live(
    tmp_path: Path,
) -> None:
    config_path = _sample_config_path()
    run_id = "status_cache_plan"

    exit_code = lmstudio_benchmark.main(
        [
            "plan-cache",
            str(config_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            run_id,
        ]
    )
    assert exit_code == 0

    run_dir = tmp_path / f"run_{run_id}_l3_0_cache_stateful_gemma4_e2b_no_live"
    cache_plan_payload = _read_json(run_dir / "cache_plan.json")
    metrics_schema_payload = _read_json(run_dir / "metrics_schema.json")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    assert cache_plan_payload["kv_reuse_proven"] is False
    assert cache_plan_payload["measurement_status"] == "not_measured_no_live"
    assert cache_plan_payload["production_default"] is False
    assert metrics_schema_payload["kv_reuse_proven"] is False
    assert metrics_schema_payload["measurement_status"] == "not_measured_no_live"
    assert all(
        metric_row["planned_value"] is None for metric_row in metrics_schema_payload["metrics"]
    )
    assert all(
        metric_row["measurement_source"] == "future_live_gate"
        for metric_row in metrics_schema_payload["metrics"]
    )
    assert "kv_reuse_proven: `false`" in report_text
    assert "measurement_status: `not_measured_no_live`" in report_text
    assert "stateful API contract is not proof of physical KV reuse" in report_text


def test_plan_cache_main_path_does_not_import_live_or_network_modules(tmp_path: Path) -> None:
    config_path = _sample_config_path()
    run_id = "import_isolation_cache_plan"
    output_root = tmp_path / "probe_output"
    run_dir = output_root / f"run_{run_id}_l3_0_cache_stateful_gemma4_e2b_no_live"
    script = "\n".join(
        [
            "import json",
            "import sys",
            "from pathlib import Path",
            "project_root = Path(sys.argv[1])",
            "config_path = Path(sys.argv[2])",
            "output_root = Path(sys.argv[3])",
            "run_dir = Path(sys.argv[4])",
            "sys.path.insert(0, str(project_root))",
            "from tools import lmstudio_benchmark",
            "exit_code = lmstudio_benchmark.main([",
            "    'plan-cache',",
            "    str(config_path),",
            "    '--output-root',",
            "    str(output_root),",
            "    '--run-id',",
            f"    '{run_id}',",
            "])",
            "forbidden_prefixes = ('requests', 'httpx')",
            "forbidden_exact = {",
            "    'tools.lmstudio_lab.live_smoke',",
            "    'tools.lmstudio_lab.managed_runner',",
            "    'tools.lmstudio_lab.model_lifecycle',",
            "}",
            "forbidden_loaded = sorted(",
            "    name",
            "    for name in sys.modules",
            "    if name in forbidden_exact or name.startswith(forbidden_prefixes)",
            ")",
            "print(json.dumps({",
            "    'exit_code': exit_code,",
            "    'forbidden_loaded': forbidden_loaded,",
            "    'report_exists': (run_dir / 'report.md').exists(),",
            "}))",
        ]
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(_project_root()),
            str(config_path),
            str(output_root),
            str(run_dir),
        ],
        capture_output=True,
        check=True,
        text=True,
    )

    probe_payload = json.loads(result.stdout.strip())
    assert probe_payload["exit_code"] == 0
    assert probe_payload["forbidden_loaded"] == []
    assert probe_payload["report_exists"] is True


def test_cache_plan_module_stays_offline_only_imports() -> None:
    cache_plan_path = _project_root() / "tools" / "lmstudio_lab" / "cache_plan.py"
    module = ast.parse(cache_plan_path.read_text(encoding="utf-8"))

    imported_names: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            if node.level == 0:
                imported_names.add(node.module)
                continue
            if node.level == 1:
                imported_names.add(f"tools.lmstudio_lab.{node.module}")

    assert FORBIDDEN_IMPORTS.isdisjoint(imported_names)
