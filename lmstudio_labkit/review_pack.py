from __future__ import annotations

import csv
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

RUBRIC = {
    "criteria": {
        "meaning_preserved": {"scale": "0..2"},
        "asr_noise_reduced": {"scale": "0..2"},
        "no_new_facts": {"scale": "0..2"},
        "term_handling": {"scale": "0..2"},
        "naturalness": {"scale": "0..2"},
        "style_overediting": {"scale": "0..2"},
        "overall_acceptability": {"scale": "0..2"},
    },
    "thresholds": {
        "overall_acceptability_avg": ">= 1.5",
        "no_new_facts_min": ">= 1",
        "meaning_preserved_min": ">= 1",
    },
    "privacy": {
        "local_only": True,
        "raw_base_url": False,
        "private_raw_prompt_response": False,
    },
}


def export_review_pack(
    run_dir: str | Path,
    output_dir: str | Path,
    *,
    limit: int = 12,
    include_raw_outputs_local_only: bool = False,
) -> dict[str, Any]:
    """Export a local-only manual review pack from sanitized run artifacts.

    By default the pack intentionally uses metadata and validation summaries
    only. Raw outputs may be included only through an explicit local-only flag
    and only when the output directory is outside the repository or explicitly
    ignored by git.
    """

    source = Path(run_dir)
    target = Path(output_dir)
    if include_raw_outputs_local_only:
        _validate_local_only_raw_output_dir(target)
    target.mkdir(parents=True, exist_ok=True)
    rows = _load_rows(source, limit=limit)
    raw_rows = _load_raw_rows(source, limit=limit) if include_raw_outputs_local_only else []
    _write_readme(
        target,
        source,
        rows,
        include_raw_outputs_local_only=include_raw_outputs_local_only,
        raw_case_count=len(raw_rows),
    )
    _write_sampled_cases(target, rows)
    files = [
        str(target / "README.md"),
        str(target / "sampled_cases.md"),
        str(target / "rubric.yaml"),
        str(target / "reviewer_notes.md"),
    ]
    if include_raw_outputs_local_only:
        _write_raw_cases(target, raw_rows)
        files.append(str(target / "raw_outputs.local-only.jsonl"))
    (target / "rubric.yaml").write_text(_rubric_yaml(), encoding="utf-8")
    (target / "reviewer_notes.md").write_text(
        "# Reviewer Notes\n\n- Fill this file locally. Do not commit raw model outputs.\n",
        encoding="utf-8",
    )
    return {
        "status": "ok",
        "output_dir": str(target),
        "sampled_case_count": len(rows),
        "raw_case_count": len(raw_rows),
        "raw_outputs_included": include_raw_outputs_local_only,
        "files": files,
    }


def _validate_local_only_raw_output_dir(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        inside_repo = resolved.is_relative_to(repo_root)
    except ValueError:
        inside_repo = False
    if not inside_repo:
        if resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            return
        if _is_gitignored_path(resolved, repo_root=repo_root):
            return
        raise ValueError(
            "--include-raw-outputs-local-only requires an output dir under the platform temp dir "
            "or an explicitly gitignored path"
        )
    raise ValueError("raw-output review packs must not be written inside the repository")


def _is_gitignored_path(path: Path, *, repo_root: Path) -> bool:
    try:
        completed = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=repo_root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return completed.returncode == 0


def _load_rows(run_dir: Path, *, limit: int) -> list[dict[str, Any]]:
    cell_results = run_dir / "cell_results.jsonl"
    if cell_results.exists():
        rows = [
            json.loads(line)
            for line in cell_results.read_text(encoding="utf-8").splitlines()
            if line
        ]
        return rows[:limit]
    snapshot = run_dir / "latest_snapshot.csv"
    if snapshot.exists():
        with snapshot.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))[:limit]
    raise FileNotFoundError(f"No reviewable sanitized artifacts found in {run_dir}")


def _load_raw_rows(run_dir: Path, *, limit: int) -> list[dict[str, Any]]:
    raw_path = run_dir / "raw_cases.jsonl"
    if not raw_path.exists():
        return []
    rows = [
        _sanitize_raw_case(json.loads(line))
        for line in raw_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    return rows[:limit]


def _sanitize_raw_case(row: dict[str, Any]) -> dict[str, Any]:
    blocked_keys = {
        "base_url",
        "raw_base_url",
        "api_key",
        "token",
        "secret",
        "authorization",
    }
    sanitized: dict[str, Any] = {}
    for key, value in row.items():
        normalized_key = str(key).casefold()
        if any(blocked in normalized_key for blocked in blocked_keys):
            continue
        sanitized[str(key)] = value
    return sanitized


def _write_readme(
    target: Path,
    source: Path,
    rows: list[dict[str, Any]],
    *,
    include_raw_outputs_local_only: bool,
    raw_case_count: int,
) -> None:
    raw_lines = [
        "",
        "Raw-output mode:",
        f"- include_raw_outputs_local_only: {include_raw_outputs_local_only}",
        f"- raw_case_count: {raw_case_count}",
    ]
    if include_raw_outputs_local_only:
        raw_lines.extend(
            [
                "",
                "WARNING:",
                "- this pack may contain raw prompts, raw responses, or raw transcript text",
                "- keep it local-only",
                "- never commit this directory",
                "- raw base URLs, credentials, and secrets are not exported",
            ]
        )
    (target / "README.md").write_text(
        "\n".join(
            [
                "# Local-only Manual Review Pack",
                "",
                f"Source run dir: `{source}`",
                f"Sampled cases: {len(rows)}",
                "",
                "Privacy rules:",
                "- local-only; do not commit this directory unless explicitly sanitized",
                "- contains sanitized metadata only by default",
                "- must not include raw base URLs, credentials, or private prompts/responses",
                *raw_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_sampled_cases(target: Path, rows: list[dict[str, Any]]) -> None:
    lines = ["# Sampled Cases", ""]
    for index, row in enumerate(rows, start=1):
        axes = row.get("axes", {}) if isinstance(row, dict) else {}
        validation = row.get("validation", {}) if isinstance(row, dict) else {}
        lines.extend(
            [
                f"## Case {index}",
                "",
                f"- cell_id: `{row.get('cell_id', '')}`",
                f"- model_key: `{row.get('model_key', '')}`",
                f"- task_id: `{row.get('task_id', '')}`",
                f"- task_intent: `{axes.get('task_intent', '') if isinstance(axes, dict) else ''}`",
                f"- input_profile: `{axes.get('input_profile', '') if isinstance(axes, dict) else ''}`",
                f"- output_language_policy: `{axes.get('output_language_policy', '') if isinstance(axes, dict) else ''}`",
                f"- prompt_variant: `{axes.get('prompt_variant', '') if isinstance(axes, dict) else ''}`",
                f"- status: `{row.get('status', '')}`",
                "",
                "Validation summary hash/metrics only:",
                "",
                "```json",
                json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True)[:4000],
                "```",
                "",
            ]
        )
    (target / "sampled_cases.md").write_text("\n".join(lines), encoding="utf-8")


def _write_raw_cases(target: Path, rows: list[dict[str, Any]]) -> None:
    raw_path = target / "raw_outputs.local-only.jsonl"
    raw_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _rubric_yaml() -> str:
    lines = ["criteria:"]
    for name, payload in RUBRIC["criteria"].items():
        lines.append(f"  {name}:")
        lines.append(f"    scale: {payload['scale']}")
    lines.append("thresholds:")
    for name, value in RUBRIC["thresholds"].items():
        lines.append(f"  {name}: {value}")
    lines.extend(
        [
            "privacy:",
            "  local_only: true",
            "  raw_base_url: false",
            "  private_raw_prompt_response: false",
        ]
    )
    return "\n".join(lines) + "\n"
