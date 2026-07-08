from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .privacy import assert_privacy_scan_passed, scan_artifact_files

LATEST_SNAPSHOT_FILE_NAMES = (
    "latest_snapshot.json",
    "latest_snapshot.csv",
    "report.md",
    "privacy_scan.json",
)


def export_latest_text_remote_snapshot(
    run_dir: str | Path, output_dir: str | Path
) -> dict[str, Any]:
    """Export a public-safe latest snapshot for remote-link text screening."""

    source = Path(run_dir)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    planner = _read_json(source / "planner_summary.json")
    rows = _read_jsonl(source / "cell_results.jsonl")
    snapshot = _build_snapshot(planner, rows)

    json_path = target / "latest_snapshot.json"
    csv_path = target / "latest_snapshot.csv"
    report_path = target / "report.md"
    scan_path = target / "privacy_scan.json"

    json_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_snapshot_csv(csv_path, snapshot)
    report_path.write_text(_render_report(snapshot), encoding="utf-8")

    scan = scan_artifact_files((json_path, csv_path, report_path))
    scan_path.write_text(
        json.dumps(scan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert_privacy_scan_passed(scan)
    return {
        "status": "pass",
        "output_dir": str(target),
        "snapshot": str(json_path),
        "csv": str(csv_path),
        "report": str(report_path),
        "privacy_scan": str(scan_path),
    }


def _build_snapshot(planner: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("status", "unknown")) for row in rows)
    attempts = len(rows)
    pass_count = status_counts.get("pass", 0)
    axes = _axis_values(rows)
    maybe_live_bridge = planner.get("live_bridge")
    live_bridge: dict[str, Any] = maybe_live_bridge if isinstance(maybe_live_bridge, dict) else {}
    safe_live_bridge = {
        key: live_bridge[key]
        for key in (
            "live",
            "allow_model_load",
            "allow_remote",
            "allow_stress",
            "base_url_kind",
            "base_url_scheme",
            "profile",
            "max_requests",
        )
        if key in live_bridge
    }
    return {
        "schema_version": "latest-text-remote-snapshot-v1",
        "run_id": planner.get("run_id"),
        "config_hash": planner.get("config_hash"),
        "live": planner.get("live"),
        "live_bridge": safe_live_bridge,
        "execution_targets": axes.get("execution_target", []),
        "execution_modes": axes.get("execution_mode", []),
        "cache_modes": axes.get("cache_mode", []),
        "resource_telemetry_modes": axes.get("resource_telemetry_mode", []),
        "models": sorted({str(row.get("model_key")) for row in rows if row.get("model_key")}),
        "model_ids": sorted({str(row.get("model_id")) for row in rows if row.get("model_id")}),
        "attempt_count": attempts,
        "pass_count": pass_count,
        "fail_count": status_counts.get("fail", 0),
        "pass_rate": round(pass_count / attempts, 4) if attempts else 0.0,
        "cell_count": planner.get("cell_count", attempts),
        "filtered_cell_count": planner.get("filtered_cell_count"),
        "skipped_cell_count": planner.get("skipped_cell_count", 0),
        "timing": _timing_summary(rows),
        "token_counts": _token_summary(rows),
        "lifecycle": _lifecycle_summary(rows),
        "warmup": _warmup_summary(rows),
        "safety": {
            "raw_prompt_response_stored": False,
            "raw_prompt_stored": False,
            "raw_response_stored": False,
            "raw_base_url_stored": False,
            "public_safe": True,
        },
    }


def _axis_values(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    values: dict[str, set[str]] = {}
    for row in rows:
        maybe_axes = row.get("axes")
        axes: dict[str, Any] = maybe_axes if isinstance(maybe_axes, dict) else {}
        for key, value in axes.items():
            values.setdefault(str(key), set()).add(str(value))
    return {key: sorted(items) for key, items in sorted(values.items())}


def _timing_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [
        float(result["latency_ms"])
        for row in rows
        if isinstance((result := row.get("result")), dict) and result.get("latency_ms") is not None
    ]
    total_latencies = [
        float(row["total_latency_ms"]) for row in rows if row.get("total_latency_ms") is not None
    ]
    return {
        "latency_ms_min": min(latencies) if latencies else None,
        "latency_ms_max": max(latencies) if latencies else None,
        "total_latency_ms_min": min(total_latencies) if total_latencies else None,
        "total_latency_ms_max": max(total_latencies) if total_latencies else None,
    }


def _token_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = 0
    completion = 0
    for row in rows:
        maybe_result = row.get("result")
        result: dict[str, Any] = maybe_result if isinstance(maybe_result, dict) else {}
        maybe_counts = result.get("token_counts")
        counts: dict[str, Any] = maybe_counts if isinstance(maybe_counts, dict) else {}
        prompt += int(counts.get("prompt") or 0)
        completion += int(counts.get("completion") or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion}


def _lifecycle_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "session_ids": sorted(
            {str(row.get("session_id")) for row in rows if row.get("session_id")}
        ),
        "load_scopes": sorted(
            {str(row.get("load_scope")) for row in rows if row.get("load_scope")}
        ),
        "cleanup_scopes": sorted(
            {str(row.get("cleanup_scope")) for row in rows if row.get("cleanup_scope")}
        ),
        "final_loaded_instances": sorted(
            {
                int(row.get("final_loaded_instances"))
                for row in rows
                if row.get("final_loaded_instances") is not None
            }
        ),
        "session_cleanup_verified": sorted(
            {
                str(row.get("session_cleanup_verified"))
                for row in rows
                if row.get("session_cleanup_verified") is not None
            }
        ),
    }


def _warmup_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    warmup = sum(1 for row in rows if row.get("is_warmup_request") is True)
    measured = sum(1 for row in rows if row.get("is_warmup_request") is False)
    return {
        "warmup_request_count": warmup,
        "measured_request_count": measured,
        "cache_hit_reported": sorted(
            {
                str(row.get("cache_hit_reported"))
                for row in rows
                if row.get("cache_hit_reported") is not None
            }
        ),
        "kv_reuse_proven": sorted(
            {
                str(row.get("kv_reuse_proven"))
                for row in rows
                if row.get("kv_reuse_proven") is not None
            }
        ),
    }


def _write_snapshot_csv(path: Path, snapshot: dict[str, Any]) -> None:
    fieldnames = [
        "run_id",
        "live",
        "base_url_kind",
        "base_url_scheme",
        "execution_targets",
        "execution_modes",
        "cache_modes",
        "resource_telemetry_modes",
        "attempt_count",
        "pass_count",
        "fail_count",
        "pass_rate",
        "raw_prompt_response_stored",
        "raw_base_url_stored",
    ]
    maybe_live_bridge = snapshot.get("live_bridge")
    live_bridge: dict[str, Any] = maybe_live_bridge if isinstance(maybe_live_bridge, dict) else {}
    maybe_safety = snapshot.get("safety")
    safety: dict[str, Any] = maybe_safety if isinstance(maybe_safety, dict) else {}
    row = {
        "run_id": snapshot.get("run_id"),
        "live": snapshot.get("live"),
        "base_url_kind": live_bridge.get("base_url_kind"),
        "base_url_scheme": live_bridge.get("base_url_scheme"),
        "execution_targets": ";".join(snapshot.get("execution_targets", [])),
        "execution_modes": ";".join(snapshot.get("execution_modes", [])),
        "cache_modes": ";".join(snapshot.get("cache_modes", [])),
        "resource_telemetry_modes": ";".join(snapshot.get("resource_telemetry_modes", [])),
        "attempt_count": snapshot.get("attempt_count"),
        "pass_count": snapshot.get("pass_count"),
        "fail_count": snapshot.get("fail_count"),
        "pass_rate": snapshot.get("pass_rate"),
        "raw_prompt_response_stored": safety.get("raw_prompt_response_stored"),
        "raw_base_url_stored": safety.get("raw_base_url_stored"),
    }
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def _render_report(snapshot: dict[str, Any]) -> str:
    lifecycle = snapshot.get("lifecycle") if isinstance(snapshot.get("lifecycle"), dict) else {}
    warmup = snapshot.get("warmup") if isinstance(snapshot.get("warmup"), dict) else {}
    timing = snapshot.get("timing") if isinstance(snapshot.get("timing"), dict) else {}
    safety = snapshot.get("safety") if isinstance(snapshot.get("safety"), dict) else {}
    session_count = len(lifecycle.get("session_ids", [])) if lifecycle else "not exported"
    warmup_request_count = warmup.get("warmup_request_count") if warmup else "not exported"
    measured_request_count = warmup.get("measured_request_count") if warmup else "not exported"
    cache_hit_reported = (
        ", ".join(warmup.get("cache_hit_reported", [])) if warmup else "not exported"
    )
    kv_reuse_proven = ", ".join(warmup.get("kv_reuse_proven", [])) if warmup else "not exported"
    lines = [
        "# L3.16.1 latest live session warmup report",
        "",
        "## Scope",
        "",
        f"- run_id: `{snapshot.get('run_id')}`",
        f"- models: `{', '.join(snapshot.get('model_ids', []))}`",
        f"- request_count: `{snapshot.get('attempt_count')}`",
        f"- execution_modes: `{', '.join(snapshot.get('execution_modes', []))}`",
        f"- cache_modes: `{', '.join(snapshot.get('cache_modes', []))}`",
        f"- resource_telemetry_modes: `{', '.join(snapshot.get('resource_telemetry_modes', []))}`",
        "",
        "## Session lifecycle proof",
        "",
        f"- session_count: `{session_count}`",
        f"- load_scopes: `{', '.join(lifecycle.get('load_scopes', [])) if lifecycle else 'not exported'}`",
        f"- cleanup_scopes: `{', '.join(lifecycle.get('cleanup_scopes', [])) if lifecycle else 'not exported'}`",
        f"- final_loaded_instances: `{', '.join(str(x) for x in lifecycle.get('final_loaded_instances', [])) if lifecycle else 'not exported'}`",
        f"- session_cleanup_verified: `{', '.join(lifecycle.get('session_cleanup_verified', [])) if lifecycle else 'not exported'}`",
        "",
        "Expected L3.16.1 shape on newly exported runs: two model sessions, each loaded once, three requests, cleanup once, final loaded instances zero.",
        "",
        "## Warmup/measured split",
        "",
        f"- warmup_request_count: `{warmup_request_count}`",
        f"- measured_request_count: `{measured_request_count}`",
        f"- cache_hit_reported: `{cache_hit_reported}`",
        f"- kv_reuse_proven: `{kv_reuse_proven}`",
        "",
        "## Validation summary",
        "",
        f"- pass_count: `{snapshot.get('pass_count')}`",
        f"- fail_count: `{snapshot.get('fail_count')}`",
        f"- pass_rate: `{snapshot.get('pass_rate')}`",
        "",
        "## Timing summary",
        "",
        f"- latency_ms_min: `{timing.get('latency_ms_min')}`",
        f"- latency_ms_max: `{timing.get('latency_ms_max')}`",
        f"- total_latency_ms_min: `{timing.get('total_latency_ms_min')}`",
        f"- total_latency_ms_max: `{timing.get('total_latency_ms_max')}`",
        "",
        "## Privacy summary",
        "",
        f"- raw_prompt_response_stored: `{safety.get('raw_prompt_response_stored')}`",
        f"- raw_base_url_stored: `{safety.get('raw_base_url_stored')}`",
        "",
        "## Non-claims",
        "",
        "- KV-cache reuse is not proven unless LM Studio reports an explicit cache-hit signal.",
        "- RAM/VRAM telemetry is not claimed for timing-only remote-link runs.",
        "- No image, 12B, 26B, Qwen, throughput, parallel, overnight, or stress gate is covered by this snapshot.",
        "",
        "## Next allowed gate",
        "",
        "L3.17 small text quality screening only after L3.16.1 gates remain green.",
        "",
    ]
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


__all__ = ["LATEST_SNAPSHOT_FILE_NAMES", "export_latest_text_remote_snapshot"]
