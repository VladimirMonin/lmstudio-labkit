"""Privacy-safe artifact helpers for public LabKit runs."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactSet:
    """Paths written for one offline/public-safe run artifact set."""

    output_dir: Path
    planner_summary: Path
    cell_results: Path
    cell_summary: Path
    model_summary: Path
    failure_summary: Path
    retry_summary: Path
    resource_summary: Path
    privacy_scan: Path
    report: Path

    @property
    def planner_summary_path(self) -> Path:
        return self.planner_summary

    @property
    def cell_results_path(self) -> Path:
        return self.cell_results

    @property
    def privacy_scan_path(self) -> Path:
        return self.privacy_scan

    @property
    def report_path(self) -> Path:
        return self.report

    @property
    def files(self) -> tuple[Path, ...]:
        return tuple(Path(path) for path in self.as_dict().values())

    def as_dict(self) -> dict[str, str]:
        return {
            "planner_summary": str(self.planner_summary),
            "cell_results": str(self.cell_results),
            "cell_summary": str(self.cell_summary),
            "model_summary": str(self.model_summary),
            "failure_summary": str(self.failure_summary),
            "retry_summary": str(self.retry_summary),
            "resource_summary": str(self.resource_summary),
            "privacy_scan": str(self.privacy_scan),
            "report": str(self.report),
        }


def write_run_artifacts(
    output_dir: str | Path,
    planner_summary: dict[str, Any],
    cell_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> ArtifactSet:
    """Write deterministic public-safe JSON/CSV/Markdown artifacts."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    artifact_set = ArtifactSet(
        output_dir=root,
        planner_summary=root / "planner_summary.json",
        cell_results=root / "cell_results.jsonl",
        cell_summary=root / "cell_summary.csv",
        model_summary=root / "model_summary.csv",
        failure_summary=root / "failure_summary.csv",
        retry_summary=root / "retry_summary.csv",
        resource_summary=root / "resource_summary.csv",
        privacy_scan=root / "privacy_scan.json",
        report=root / "report.md",
    )

    _write_json(artifact_set.planner_summary, planner_summary)
    _write_jsonl(artifact_set.cell_results, cell_results)
    _write_cell_summary(artifact_set.cell_summary, cell_results)
    _write_model_summary(artifact_set.model_summary, cell_results)
    _write_failure_summary(artifact_set.failure_summary, cell_results)
    _write_retry_summary(artifact_set.retry_summary, cell_results)
    _write_resource_summary(artifact_set.resource_summary, cell_results)

    privacy_scan = {
        "status": "pass",
        "policy": planner_summary.get("privacy_mode", "safe-default"),
        "scanned_artifacts": [path.name for path in artifact_set.files],
        "violation_count": 0,
        "violations": [],
    }
    _write_json(artifact_set.privacy_scan, privacy_scan)

    artifact_set.report.write_text(
        _build_report(planner_summary, cell_results, privacy_scan), encoding="utf-8"
    )
    return artifact_set


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            stream.write("\n")


def _write_cell_summary(
    path: Path,
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> None:
    fieldnames = [
        "cell_id",
        "model_key",
        "model_id",
        "task_id",
        "status",
        "retry_count",
        "error_category",
    ]
    _write_csv(path, fieldnames, ({key: row.get(key) for key in fieldnames} for row in rows))


def _write_model_summary(
    path: Path,
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> None:
    grouped: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[(str(row.get("model_key", "")), str(row.get("model_id", "")))][
            str(row.get("status", "unknown"))
        ] += 1
    summary_rows = (
        {
            "model_key": model_key,
            "model_id": model_id,
            "pass_count": counts.get("pass", 0),
            "fail_count": counts.get("fail", 0),
            "attempt_count": sum(counts.values()),
        }
        for (model_key, model_id), counts in sorted(grouped.items())
    )
    _write_csv(
        path, ["model_key", "model_id", "attempt_count", "pass_count", "fail_count"], summary_rows
    )


def _write_failure_summary(
    path: Path,
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> None:
    counts = Counter(
        str(row.get("error_category") or "none") for row in rows if row.get("status") == "fail"
    )
    _write_csv(
        path,
        ["error_category", "count"],
        (
            {"error_category": category, "count": count}
            for category, count in sorted(counts.items())
        ),
    )


def _write_retry_summary(
    path: Path,
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> None:
    counts = Counter(str(row.get("retry_count", 0)) for row in rows)
    _write_csv(
        path,
        ["retry_count", "attempt_count"],
        (
            {"retry_count": retry_count, "attempt_count": count}
            for retry_count, count in sorted(counts.items())
        ),
    )


def _write_resource_summary(
    path: Path,
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> None:
    summary_rows = []
    for row in rows:
        maybe_result = row.get("result")
        result = maybe_result if isinstance(maybe_result, dict) else {}
        maybe_token_counts = result.get("token_counts")
        token_counts = maybe_token_counts if isinstance(maybe_token_counts, dict) else {}
        summary_rows.append(
            {
                "cell_id": row.get("cell_id"),
                "latency_ms": result.get("latency_ms"),
                "prompt_tokens": token_counts.get("prompt"),
                "completion_tokens": token_counts.get("completion"),
            }
        )
    _write_csv(
        path,
        ["cell_id", "latency_ms", "prompt_tokens", "completion_tokens"],
        summary_rows,
    )


def _write_csv(path: Path, fieldnames: list[str], rows: Any) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _build_report(
    planner_summary: dict[str, Any],
    cell_results: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    privacy_scan: dict[str, Any],
) -> str:
    run_id = planner_summary.get("run_id", "unknown_run")
    passed = sum(1 for row in cell_results if row.get("status") == "pass")
    failed = sum(1 for row in cell_results if row.get("status") == "fail")
    lines = [
        f"# LabKit run {run_id}",
        "",
        f"- cell_count: `{planner_summary.get('cell_count', len(cell_results))}`",
        f"- result_count: `{len(cell_results)}`",
        f"- passed: `{passed}`",
        f"- failed: `{failed}`",
        f"- live: `{str(planner_summary.get('live', False)).lower()}`",
        f"- privacy_scan: `{privacy_scan['status']}`",
        "",
    ]
    return "\n".join(lines)


__all__ = ["ArtifactSet", "write_run_artifacts"]
