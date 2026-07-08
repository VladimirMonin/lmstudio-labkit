from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def summarize_run(run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir)
    planner = _read_json(path / "planner_summary.json")
    rows = _read_jsonl(path / "cell_results.jsonl")
    passed = sum(1 for row in rows if row.get("status") == "pass")
    failed = len(rows) - passed
    return {
        "run_id": planner.get("run_id"),
        "cell_count": planner.get("cell_count", len(rows)),
        "attempt_count": len(rows),
        "pass_count": passed,
        "fail_count": failed,
        "pass_rate": round(passed / len(rows), 4) if rows else 0.0,
        "privacy_mode": planner.get("privacy_mode"),
    }


def compare_runs(left_run_dir: str | Path, right_run_dir: str | Path) -> dict[str, Any]:
    left = summarize_run(left_run_dir)
    right = summarize_run(right_run_dir)
    return {
        "left": left,
        "right": right,
        "delta": {
            "attempt_count": right["attempt_count"] - left["attempt_count"],
            "pass_count": right["pass_count"] - left["pass_count"],
            "fail_count": right["fail_count"] - left["fail_count"],
            "pass_rate": round(right["pass_rate"] - left["pass_rate"], 4),
        },
    }


def write_summary_csv(summary: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted(summary))
        writer.writeheader()
        writer.writerow(summary)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
