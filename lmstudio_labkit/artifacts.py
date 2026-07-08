"""Privacy-safe artifact helpers for public LabKit runs."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .privacy import assert_privacy_scan_passed, scan_artifact_files


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
    axis_summary: Path
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
            "axis_summary": str(self.axis_summary),
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
        axis_summary=root / "axis_summary.csv",
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
    _write_axis_summary(artifact_set.axis_summary, cell_results)

    draft_report = _build_report(planner_summary, cell_results, {"status": "pending"})
    artifact_set.report.write_text(draft_report, encoding="utf-8")
    scan_targets = tuple(path for path in artifact_set.files if path != artifact_set.privacy_scan)
    privacy_scan = scan_artifact_files(scan_targets)
    _write_json(artifact_set.privacy_scan, privacy_scan)
    assert_privacy_scan_passed(privacy_scan)
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
        "retry_recovered",
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
            "attempt_count": sum(counts.values()),
            "pass_count": counts.get("pass", 0),
            "fail_count": counts.get("fail", 0),
            "pass_rate": _rate(counts.get("pass", 0), sum(counts.values())),
        }
        for (model_key, model_id), counts in sorted(grouped.items())
    )
    _write_csv(
        path,
        ["model_key", "model_id", "attempt_count", "pass_count", "fail_count", "pass_rate"],
        summary_rows,
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
    by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        axes = row.get("axes") if isinstance(row.get("axes"), dict) else {}
        by_policy[str(axes.get("retry_policy", row.get("retry_count", 0)))].append(row)
    summary_rows = []
    for policy, policy_rows in sorted(by_policy.items()):
        recovered = sum(1 for row in policy_rows if row.get("retry_recovered") is True)
        attempted = sum(1 for row in policy_rows if int(row.get("retry_count") or 0) > 0)
        summary_rows.append(
            {
                "retry_policy": policy,
                "attempt_count": len(policy_rows),
                "retry_attempted_count": attempted,
                "recovered_count": recovered,
                "recovery_rate": _rate(recovered, attempted),
            }
        )
    _write_csv(
        path,
        [
            "retry_policy",
            "attempt_count",
            "retry_attempted_count",
            "recovered_count",
            "recovery_rate",
        ],
        summary_rows,
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


def _write_axis_summary(
    path: Path, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]
) -> None:
    grouped: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in rows:
        axes = row.get("axes") if isinstance(row.get("axes"), dict) else {}
        for axis_name, axis_value in axes.items():
            grouped[(str(axis_name), str(axis_value))][str(row.get("status", "unknown"))] += 1
    summary_rows = []
    for (axis_name, axis_value), counts in sorted(grouped.items()):
        total = sum(counts.values())
        summary_rows.append(
            {
                "axis": axis_name,
                "value": axis_value,
                "attempt_count": total,
                "pass_count": counts.get("pass", 0),
                "fail_count": counts.get("fail", 0),
                "pass_rate": _rate(counts.get("pass", 0), total),
            }
        )
    _write_csv(
        path,
        ["axis", "value", "attempt_count", "pass_count", "fail_count", "pass_rate"],
        summary_rows,
    )


def _write_csv(path: Path, fieldnames: list[str], rows: Any) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _rate(part: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(part / total, 4)


def _build_report(
    planner_summary: dict[str, Any],
    cell_results: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    privacy_scan: dict[str, Any],
) -> str:
    run_id = planner_summary.get("run_id", "unknown_run")
    passed = sum(1 for row in cell_results if row.get("status") == "pass")
    failed = sum(1 for row in cell_results if row.get("status") == "fail")
    model_counts: dict[str, Counter[str]] = defaultdict(Counter)
    axis_counts: dict[str, Counter[str]] = defaultdict(Counter)
    retry_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in cell_results:
        status = str(row.get("status", "unknown"))
        model_counts[str(row.get("model_key", "unknown"))][status] += 1
        axes = row.get("axes") if isinstance(row.get("axes"), dict) else {}
        for axis_name, axis_value in axes.items():
            axis_counts[f"{axis_name}={axis_value}"][status] += 1
        retry_policy = str(axes.get("retry_policy", "off"))
        retry_counts[retry_policy][status] += 1
        if int(row.get("retry_count") or 0) > 0:
            retry_counts[retry_policy]["retry_attempted"] += 1
        if row.get("retry_recovered") is True:
            retry_counts[retry_policy]["recovered"] += 1

    lines = [
        f"# LabKit run {run_id}",
        "",
        f"- cell_count: `{planner_summary.get('cell_count', len(cell_results))}`",
        f"- raw_cartesian_cell_count: `{planner_summary.get('raw_cartesian_cell_count', len(cell_results))}`",
        f"- filtered_cell_count: `{planner_summary.get('filtered_cell_count', len(cell_results))}`",
        f"- skipped_cell_count: `{planner_summary.get('skipped_cell_count', 0)}`",
        f"- result_count: `{len(cell_results)}`",
        f"- passed: `{passed}`",
        f"- failed: `{failed}`",
        f"- live: `{str(planner_summary.get('live', False)).lower()}`",
        f"- privacy_scan: `{privacy_scan['status']}`",
        "",
        "## Model summary",
        "",
        *_status_lines(model_counts, empty="- no completed model cells"),
        "",
        "## Required axis summaries",
        "",
        "### Language",
        "",
        *_axis_lines(axis_counts, "language"),
        "",
        "### Complexity",
        "",
        *_axis_lines(axis_counts, "structure_complexity"),
        "",
        "### Schema variant",
        "",
        *_axis_lines(axis_counts, "schema_variant"),
        "",
        "### Retry",
        "",
        *_retry_lines(retry_counts),
        "",
        "## Skipped cells",
        "",
        *_skip_reason_lines(planner_summary),
        "",
        "## Safety budget",
        "",
        *_safety_budget_lines(planner_summary),
        "",
        "## Live-screening readiness",
        "",
        f"- status: `{_live_screening_readiness(planner_summary)}`",
        "- note: `live execution is host-managed and never runs from the default offline CLI path`",
        "",
    ]
    return "\n".join(lines)


def _status_lines(grouped: dict[str, Counter[str]], *, empty: str) -> list[str]:
    if not grouped:
        return [empty]
    lines = []
    for key, counts in sorted(grouped.items()):
        total = sum(value for name, value in counts.items() if name in {"pass", "fail", "unknown"})
        pass_count = counts.get("pass", 0)
        fail_count = counts.get("fail", 0)
        pass_rate = _rate(pass_count, total)
        lines.append(
            f"- {key}: attempts `{total}`, pass `{pass_count}`, fail `{fail_count}`, pass_rate `{pass_rate}`"
        )
    return lines


def _axis_lines(axis_counts: dict[str, Counter[str]], axis_name: str) -> list[str]:
    filtered = {
        key.split("=", 1)[1]: counts
        for key, counts in axis_counts.items()
        if key.startswith(f"{axis_name}=")
    }
    return _status_lines(filtered, empty=f"- no `{axis_name}` cells")


def _retry_lines(retry_counts: dict[str, Counter[str]]) -> list[str]:
    if not retry_counts:
        return ["- no retry cells"]
    lines = []
    for policy, counts in sorted(retry_counts.items()):
        total = counts.get("pass", 0) + counts.get("fail", 0) + counts.get("unknown", 0)
        recovered = counts.get("recovered", 0)
        attempted = counts.get("retry_attempted", 0)
        lines.append(
            f"- {policy}: attempts `{total}`, retry_attempted `{attempted}`, recovered `{recovered}`, pass `{counts.get('pass', 0)}`, fail `{counts.get('fail', 0)}`"
        )
    return lines


def _skip_reason_lines(planner_summary: dict[str, Any]) -> list[str]:
    reasons = planner_summary.get("skip_reasons")
    if not isinstance(reasons, dict) or not reasons:
        return ["- none"]
    return [f"- {reason}: `{count}`" for reason, count in sorted(reasons.items())]


def _safety_budget_lines(planner_summary: dict[str, Any]) -> list[str]:
    budget = planner_summary.get("safety_budget")
    if not isinstance(budget, dict) or not budget:
        return ["- not recorded"]
    return [f"- {key}: `{value}`" for key, value in sorted(budget.items())]


def _live_screening_readiness(planner_summary: dict[str, Any]) -> str:
    budget = planner_summary.get("safety_budget")
    safety_live = isinstance(budget, dict) and budget.get("live") is True
    if planner_summary.get("live") is True and planner_summary.get("live_bridge"):
        return "guarded-live-screening-artifacts"
    if safety_live:
        return "host-managed-executor-required"
    return "offline-default-live-screening-not-enabled"


__all__ = ["ArtifactSet", "write_run_artifacts"]
