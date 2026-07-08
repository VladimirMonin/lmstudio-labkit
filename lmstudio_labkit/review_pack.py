from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

RUBRIC = {
    "criteria": {
        "meaning_preserved": {"scale": "0..2"},
        "punctuation_quality": {"scale": "0..2"},
        "paragraphing_quality": {"scale": "0..2"},
        "term_handling": {"scale": "0..2"},
        "no_new_facts": {"scale": "0..2"},
    },
    "privacy": {
        "local_only": True,
        "raw_base_url": False,
        "private_raw_prompt_response": False,
    },
}


def export_review_pack(
    run_dir: str | Path, output_dir: str | Path, *, limit: int = 12
) -> dict[str, Any]:
    """Export a local-only manual review pack from sanitized run artifacts.

    The pack intentionally uses metadata and validation summaries only. It does
    not attempt to reconstruct raw prompts or raw responses from hashes.
    """

    source = Path(run_dir)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    rows = _load_rows(source, limit=limit)
    _write_readme(target, source, rows)
    _write_sampled_cases(target, rows)
    (target / "rubric.yaml").write_text(_rubric_yaml(), encoding="utf-8")
    (target / "reviewer_notes.md").write_text(
        "# Reviewer Notes\n\n- Fill this file locally. Do not commit raw model outputs.\n",
        encoding="utf-8",
    )
    return {
        "status": "ok",
        "output_dir": str(target),
        "sampled_case_count": len(rows),
        "files": [
            str(target / "README.md"),
            str(target / "sampled_cases.md"),
            str(target / "rubric.yaml"),
            str(target / "reviewer_notes.md"),
        ],
    }


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


def _write_readme(target: Path, source: Path, rows: list[dict[str, Any]]) -> None:
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


def _rubric_yaml() -> str:
    lines = ["criteria:"]
    for name, payload in RUBRIC["criteria"].items():
        lines.append(f"  {name}:")
        lines.append(f"    scale: {payload['scale']}")
    lines.extend(
        [
            "privacy:",
            "  local_only: true",
            "  raw_base_url: false",
            "  private_raw_prompt_response: false",
        ]
    )
    return "\n".join(lines) + "\n"
