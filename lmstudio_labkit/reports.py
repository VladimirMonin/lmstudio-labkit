from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .privacy import assert_privacy_scan_passed, scan_artifact_files

SUMMARY_SIDECAR_NAMES = (
    "summary.json",
    "summary.csv",
    "axis_summary.csv",
    "failure_summary.csv",
    "retry_impact.csv",
)

COMPARE_SIDECAR_NAMES = (
    "compare_summary.json",
    "compare_summary.md",
)


def summarize_run(run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir)
    planner = _read_json(path / "planner_summary.json")
    rows = _read_jsonl(path / "cell_results.jsonl")
    passed = sum(1 for row in rows if row.get("status") == "pass")
    failed = len(rows) - passed
    summary = {
        "run_id": planner.get("run_id"),
        "cell_count": planner.get("cell_count", len(rows)),
        "attempt_count": len(rows),
        "pass_count": passed,
        "fail_count": failed,
        "pass_rate": round(passed / len(rows), 4) if rows else 0.0,
        "privacy_mode": planner.get("privacy_mode"),
        "raw_cartesian_cell_count": planner.get("raw_cartesian_cell_count"),
        "filtered_cell_count": planner.get("filtered_cell_count"),
        "skipped_cell_count": planner.get("skipped_cell_count", 0),
        "skip_reasons": planner.get("skip_reasons", {}),
        "safety_budget": planner.get("safety_budget", {}),
        "live_screening_readiness": _live_screening_readiness(planner),
        "per_model": _group_counts(rows, "model_key"),
        "per_axis": _axis_counts(rows),
        "per_language": _axis_counts(rows, axis="language"),
        "per_modality": _axis_counts(rows, axis="modality"),
        "per_complexity": _axis_counts(rows, axis="structure_complexity"),
        "per_schema_variant": _axis_counts(rows, axis="schema_variant"),
        "per_retry_policy": _axis_counts(rows, axis="retry_policy"),
        "failure_taxonomy": _failure_taxonomy(rows),
        "retry_impact": _retry_impact(rows),
    }
    _write_summary_sidecars(path, summary)
    _scan_generated_sidecars(path, SUMMARY_SIDECAR_NAMES)
    return summary


def compare_runs(left_run_dir: str | Path, right_run_dir: str | Path) -> dict[str, Any]:
    left = summarize_run(left_run_dir)
    right = summarize_run(right_run_dir)
    comparison = {
        "left": left,
        "right": right,
        "delta": {
            "attempt_count": right["attempt_count"] - left["attempt_count"],
            "pass_count": right["pass_count"] - left["pass_count"],
            "fail_count": right["fail_count"] - left["fail_count"],
            "pass_rate": round(right["pass_rate"] - left["pass_rate"], 4),
        },
    }
    right_path = Path(right_run_dir)
    (right_path / "compare_summary.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (right_path / "compare_summary.md").write_text(
        _render_compare_markdown(comparison), encoding="utf-8"
    )
    _scan_generated_sidecars(right_path, (*SUMMARY_SIDECAR_NAMES, *COMPARE_SIDECAR_NAMES))
    return comparison


def write_summary_csv(summary: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    flat = {key: value for key, value in summary.items() if not isinstance(value, dict)}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted(flat))
        writer.writeheader()
        writer.writerow(flat)


def _write_summary_sidecars(path: Path, summary: dict[str, Any]) -> None:
    (path / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_summary_csv(summary, path / "summary.csv")
    _write_mapping_csv(path / "axis_summary.csv", summary["per_axis"], ["axis", "value"])
    _write_mapping_csv(
        path / "failure_summary.csv", summary["failure_taxonomy"], ["error_category"]
    )
    _write_mapping_csv(path / "retry_impact.csv", summary["retry_impact"], ["retry_policy"])


def _scan_generated_sidecars(path: Path, names: tuple[str, ...]) -> None:
    scan = scan_artifact_files(tuple(path / name for name in names))
    (path / "privacy_scan.json").write_text(
        json.dumps(scan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert_privacy_scan_passed(scan)


def _group_counts(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[str(row.get(key, "unknown"))][str(row.get("status", "unknown"))] += 1
    return _counter_payload(grouped)


def _axis_counts(rows: list[dict[str, Any]], axis: str | None = None) -> dict[str, dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        axes = row.get("axes") if isinstance(row.get("axes"), dict) else {}
        for name, value in axes.items():
            if axis is not None and name != axis:
                continue
            grouped[f"{name}={value}"][str(row.get("status", "unknown"))] += 1
    return _counter_payload(grouped)


def _failure_taxonomy(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.get("status") != "fail":
            continue
        grouped[str(row.get("error_category") or "unknown")][
            str(row.get("model_key", "unknown"))
        ] += 1
    return {
        category: {"count": sum(counter.values()), "affected_models": sorted(counter)}
        for category, counter in sorted(grouped.items())
    }


def _retry_impact(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        axes = row.get("axes") if isinstance(row.get("axes"), dict) else {}
        grouped[str(axes.get("retry_policy", "off"))].append(row)
    return {
        policy: {
            "attempt_count": len(policy_rows),
            "retry_attempted_count": sum(
                int(row.get("retry_count") or 0) > 0 for row in policy_rows
            ),
            "recovered_count": sum(row.get("retry_recovered") is True for row in policy_rows),
        }
        for policy, policy_rows in sorted(grouped.items())
    }


def _counter_payload(grouped: dict[str, Counter[str]]) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for key, counts in sorted(grouped.items()):
        total = sum(counts.values())
        pass_count = counts.get("pass", 0)
        payload[key] = {
            "attempt_count": total,
            "pass_count": pass_count,
            "fail_count": counts.get("fail", 0),
            "pass_rate": round(pass_count / total, 4) if total else 0.0,
        }
    return payload


def _write_mapping_csv(
    path: Path, mapping: dict[str, dict[str, Any]], split_names: list[str]
) -> None:
    fieldnames = [
        *split_names,
        "attempt_count",
        "pass_count",
        "fail_count",
        "pass_rate",
        "count",
        "affected_models",
        "retry_attempted_count",
        "recovered_count",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for key, value in mapping.items():
            row = dict(value)
            if len(split_names) == 2 and "=" in key:
                row[split_names[0]], row[split_names[1]] = key.split("=", 1)
            else:
                row[split_names[0]] = key
            if isinstance(row.get("affected_models"), list):
                row["affected_models"] = ";".join(row["affected_models"])
            writer.writerow(row)


def _render_compare_markdown(comparison: dict[str, Any]) -> str:
    delta = comparison["delta"]
    return "\n".join(
        [
            "# LabKit compare summary",
            "",
            f"- attempt_count_delta: `{delta['attempt_count']}`",
            f"- pass_count_delta: `{delta['pass_count']}`",
            f"- fail_count_delta: `{delta['fail_count']}`",
            f"- pass_rate_delta: `{delta['pass_rate']}`",
            "",
        ]
    )


def _live_screening_readiness(planner: dict[str, Any]) -> str:
    budget = planner.get("safety_budget")
    safety_live = isinstance(budget, dict) and budget.get("live") is True
    if planner.get("live") is True and planner.get("live_bridge"):
        return "guarded-live-screening-artifacts"
    if safety_live:
        return "host-managed-executor-required"
    return "offline-default-live-screening-not-enabled"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
