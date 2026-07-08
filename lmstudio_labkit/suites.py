from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .benchmarks import BenchmarkConfig, run_matrix, write_matrix_plan
from .preflight import preflight_config
from .privacy import assert_privacy_scan_passed
from .reports import summarize_run

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


@dataclass(frozen=True, slots=True)
class SuiteEntry:
    entry_id: str | None
    config: Path
    required: bool = True
    run_after: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SuiteConfig:
    suite_id: str
    entries: tuple[SuiteEntry, ...]
    stop_on_failure: bool = True

    @classmethod
    def from_file(cls, path: str | Path) -> SuiteConfig:
        source = Path(path)
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("suite config must be a mapping")
        raw_entries = payload.get("configs", [])
        if not isinstance(raw_entries, list) or not raw_entries:
            raise ValueError("suite config requires non-empty configs list")
        entries: list[SuiteEntry] = []
        for item in raw_entries:
            if isinstance(item, str):
                entries.append(SuiteEntry(entry_id=None, config=_resolve_suite_path(source, item)))
                continue
            if not isinstance(item, dict):
                raise ValueError("suite configs entries must be strings or mappings")
            config_value = item.get("config", item.get("path"))
            if config_value is None:
                raise ValueError("suite config entries require config or path")
            entries.append(
                SuiteEntry(
                    entry_id=str(item["id"]) if item.get("id") is not None else None,
                    config=_resolve_suite_path(source, str(config_value)),
                    required=bool(item.get("required", True)),
                    run_after=tuple(str(dep) for dep in item.get("run_after", [])),
                )
            )
        return cls(
            suite_id=str(payload.get("suite_id") or source.stem),
            entries=tuple(entries),
            stop_on_failure=bool(payload.get("stop_on_failure", True)),
        )


def preflight_suite(suite_path: str | Path, *, base_url: str | None = None) -> dict[str, Any]:
    suite = SuiteConfig.from_file(suite_path)
    results = [
        preflight_config(entry.config, base_url=base_url).as_dict() for entry in suite.entries
    ]
    return {
        "suite_id": suite.suite_id,
        "status": "pass" if all(item["status"] == "pass" for item in results) else "fail",
        "config_count": len(results),
        "results": results,
    }


def plan_suite(suite_path: str | Path, output_root: str | Path) -> dict[str, Any]:
    suite = SuiteConfig.from_file(suite_path)
    suite_dir = _prepare_suite_dir(suite, output_root, resume=False)
    _copy_suite_config(suite_path, suite_dir)
    _write_json(suite_dir / "suite_preflight.json", preflight_suite(suite_path))
    records = []
    for entry in _ordered_entries(suite):
        config = BenchmarkConfig.from_file(entry.config)
        _validate_safe_local_id(config.run_id, field="run_id")
        artifacts = write_matrix_plan(config, suite_dir / "runs")
        records.append(_record(entry, config, "planned", artifacts.as_dict()))
    return _write_suite_artifacts(suite_dir, suite, records, mode="plan")


def run_suite(
    suite_path: str | Path,
    output_root: str | Path,
    *,
    profile: str = "offline-fake",
    resume: bool = False,
) -> dict[str, Any]:
    if profile not in {"offline-fake", "offline", "fake"}:
        raise ValueError("run-suite supports offline/fake profiles only")
    suite = SuiteConfig.from_file(suite_path)
    suite_dir = _prepare_suite_dir(suite, output_root, resume=resume)
    _copy_suite_config(suite_path, suite_dir)
    _write_json(suite_dir / "suite_preflight.json", preflight_suite(suite_path))
    records: list[dict[str, Any]] = []
    for entry in _ordered_entries(suite):
        config = BenchmarkConfig.from_file(entry.config)
        _validate_safe_local_id(config.run_id, field="run_id")
        run_dir = suite_dir / "runs" / config.run_id
        if resume and _run_complete(run_dir, config):
            records.append(_record(entry, config, "skipped", {"output_dir": str(run_dir)}))
            continue
        if run_dir.exists():
            _assert_inside_suite_runs(run_dir, suite_dir)
            shutil.rmtree(run_dir)
        artifacts = run_matrix(config, suite_dir / "runs")
        summary = summarize_run(artifacts.output_dir)
        status = "passed" if summary.get("fail_count") == 0 else "failed"
        records.append(_record(entry, config, status, artifacts.as_dict()))
        if status == "failed" and entry.required and suite.stop_on_failure:
            break
    return _write_suite_artifacts(suite_dir, suite, records, mode="run")


def summarize_suite(suite_run_dir: str | Path) -> dict[str, Any]:
    suite_dir = Path(suite_run_dir)
    run_dirs = sorted(path for path in (suite_dir / "runs").iterdir() if path.is_dir())
    summaries = [summarize_run(path) for path in run_dirs]
    payload = {
        "suite_id": suite_dir.name,
        "run_count": len(summaries),
        "attempt_count": sum(int(item.get("attempt_count", 0)) for item in summaries),
        "pass_count": sum(int(item.get("pass_count", 0)) for item in summaries),
        "fail_count": sum(int(item.get("fail_count", 0)) for item in summaries),
        "runs": summaries,
    }
    payload["status"] = "pass" if payload["fail_count"] == 0 else "fail"
    _write_json(suite_dir / "suite_summary.json", payload)
    (suite_dir / "suite_report.md").write_text(_suite_report(payload), encoding="utf-8")
    _write_decision_record(suite_dir, payload)
    return payload


def compare_suites(
    left_suite_run_dir: str | Path, right_suite_run_dir: str | Path
) -> dict[str, Any]:
    left = summarize_suite(left_suite_run_dir)
    right = summarize_suite(right_suite_run_dir)
    payload = {
        "left": left,
        "right": right,
        "delta": {
            "attempt_count": right["attempt_count"] - left["attempt_count"],
            "pass_count": right["pass_count"] - left["pass_count"],
            "fail_count": right["fail_count"] - left["fail_count"],
        },
    }
    _write_json(Path(right_suite_run_dir) / "suite_compare.json", payload)
    return payload


def _resolve_suite_path(source: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = (source.parent / path).resolve()
    if candidate.exists():
        return candidate
    return (Path.cwd() / path).resolve()


def _prepare_suite_dir(suite: SuiteConfig, output_root: str | Path, *, resume: bool) -> Path:
    _validate_safe_local_id(suite.suite_id, field="suite_id")
    suite_dir = Path(output_root) / suite.suite_id
    if suite_dir.exists() and not resume:
        raise FileExistsError(f"suite output directory already exists: {suite_dir}")
    (suite_dir / "runs").mkdir(parents=True, exist_ok=True)
    return suite_dir


def _copy_suite_config(suite_path: str | Path, suite_dir: Path) -> None:
    shutil.copyfile(suite_path, suite_dir / "suite_config.yaml")


def _ordered_entries(suite: SuiteConfig) -> tuple[SuiteEntry, ...]:
    # Minimal deterministic order. run_after is validated for known run_ids and otherwise kept declarative.
    known = {
        _entry_identifier(entry, BenchmarkConfig.from_file(entry.config)) for entry in suite.entries
    }
    for entry in suite.entries:
        missing = set(entry.run_after) - known
        if missing:
            raise ValueError(f"suite entry has unknown run_after dependencies: {sorted(missing)}")
    return suite.entries


def _run_complete(run_dir: Path, config: BenchmarkConfig) -> bool:
    required = [
        run_dir / "privacy_scan.json",
        run_dir / "report.md",
        run_dir / "cell_results.jsonl",
        run_dir / "planner_summary.json",
    ]
    if not all(path.exists() for path in required):
        return False
    privacy = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    try:
        assert_privacy_scan_passed(privacy)
    except Exception:
        return False
    planner = json.loads((run_dir / "planner_summary.json").read_text(encoding="utf-8"))
    if planner.get("config_hash") != config.safe_hash():
        return False
    rows = _read_jsonl(run_dir / "cell_results.jsonl")
    return len(rows) == int(planner.get("cell_count", 0))


def _record(
    entry: SuiteEntry, config: BenchmarkConfig, status: str, artifacts: dict[str, str]
) -> dict[str, Any]:
    return {
        "config_id": _entry_identifier(entry, config),
        "config": str(entry.config),
        "run_id": config.run_id,
        "config_hash": config.safe_hash(),
        "required": entry.required,
        "status": status,
        "artifacts": artifacts,
    }


def _write_suite_artifacts(
    suite_dir: Path,
    suite: SuiteConfig,
    records: list[dict[str, Any]],
    *,
    mode: str,
) -> dict[str, Any]:
    payload = {
        "suite_id": suite.suite_id,
        "mode": mode,
        "status": "pass"
        if all(item["status"] in {"planned", "passed", "skipped"} for item in records)
        else "fail",
        "records": records,
    }
    summary = _suite_summary_payload(suite.suite_id, records, mode=mode)
    _write_json(
        suite_dir / "suite_plan.json",
        payload if mode == "plan" else {"suite_id": suite.suite_id, "records": records},
    )
    _write_jsonl(suite_dir / "suite_results.jsonl", _dedupe_suite_results(suite_dir, records))
    _write_json(suite_dir / "suite_summary.json", summary)
    (suite_dir / "suite_report.md").write_text(_suite_report(summary), encoding="utf-8")
    _write_decision_record(suite_dir, summary)
    if mode == "run":
        summarize_suite(suite_dir)
    return payload


def _entry_identifier(entry: SuiteEntry, config: BenchmarkConfig) -> str:
    return entry.entry_id or config.run_id


def _suite_summary_payload(
    suite_id: str, records: list[dict[str, Any]], *, mode: str
) -> dict[str, Any]:
    passed = sum(1 for item in records if item.get("status") in {"planned", "passed", "skipped"})
    failed = len(records) - passed
    return {
        "suite_id": suite_id,
        "mode": mode,
        "status": "pass" if failed == 0 else "fail",
        "run_count": len(records),
        "attempt_count": len(records),
        "pass_count": passed,
        "fail_count": failed,
        "records": records,
    }


def _dedupe_suite_results(suite_dir: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_jsonl(suite_dir / "suite_results.jsonl"):
        key = (str(row.get("config_id") or row.get("run_id")), str(row.get("config_hash")))
        keyed[key] = row
    for row in records:
        key = (str(row.get("config_id") or row.get("run_id")), str(row.get("config_hash")))
        keyed[key] = row
    return [keyed[key] for key in sorted(keyed)]


def _write_decision_record(suite_dir: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# LabKit suite decision record",
        "",
        f"- suite_id: `{payload['suite_id']}`",
        f"- status: `{payload['status']}`",
        f"- run_count: `{payload['run_count']}`",
        f"- pass_count: `{payload['pass_count']}`",
        f"- fail_count: `{payload['fail_count']}`",
        "",
        "## Decision",
        "",
        "Review the suite artifacts before any later live execution window.",
        "",
        "## Non-claims",
        "",
        "- No live inference is proven by offline suite artifacts.",
        "- No model load or model download is proven by offline suite artifacts.",
        "- KV reuse, throughput, and image-live readiness require separate explicit live approval.",
        "",
    ]
    (suite_dir / "suite_decision_record.md").write_text("\n".join(lines), encoding="utf-8")


def _suite_report(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# LabKit suite report",
            "",
            f"- suite_id: `{payload['suite_id']}`",
            f"- status: `{payload['status']}`",
            f"- run_count: `{payload['run_count']}`",
            f"- attempt_count: `{payload['attempt_count']}`",
            f"- pass_count: `{payload['pass_count']}`",
            f"- fail_count: `{payload['fail_count']}`",
            "",
            "## Non-claims",
            "",
            "- No live inference was executed by suite offline commands.",
            "- No model load or model download is performed by suite offline commands.",
            "- Image live remains out of scope.",
            "",
        ]
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _assert_inside_suite_runs(run_dir: Path, suite_dir: Path) -> None:
    resolved = run_dir.resolve()
    runs_root = (suite_dir / "runs").resolve()
    if not resolved.is_relative_to(runs_root):
        raise ValueError(f"refusing to rerun outside suite output root: {run_dir}")


def _validate_safe_local_id(value: str, *, field: str) -> None:
    if not _SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"{field} must be a safe local identifier")
