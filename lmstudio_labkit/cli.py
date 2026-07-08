from __future__ import annotations

import argparse
import json
from typing import Any

from .benchmarks import BenchmarkConfig, run_matrix, write_matrix_plan
from .reports import compare_runs, summarize_run, write_summary_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lmstudio-benchmark")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", aliases=["plan-matrix"], help="Write an offline matrix plan")
    plan.add_argument("--config", required=True)
    plan.add_argument("--output-root", required=True)

    run = sub.add_parser("run", aliases=["run-matrix"], help="Run offline/fake matrix execution")
    run.add_argument("--config", required=True)
    run.add_argument("--output-root", required=True)
    run.add_argument("--profile", default="offline-fake")
    run.add_argument(
        "--live", action="store_true", help="Rejected unless a future live runner is installed"
    )

    summarize = sub.add_parser("summarize", help="Summarize a run directory")
    summarize.add_argument("--run-dir", required=True)
    summarize.add_argument("--output-csv")

    compare = sub.add_parser("compare", help="Compare two run directories")
    compare.add_argument("--left-run-dir", required=True)
    compare.add_argument("--right-run-dir", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {"plan", "plan-matrix"}:
        config = BenchmarkConfig.from_file(args.config)
        artifacts = write_matrix_plan(config, args.output_root)
        _print_json({"status": "ok", "mode": "plan", "artifacts": artifacts.as_dict()})
        return 0
    if args.command in {"run", "run-matrix"}:
        if args.live:
            raise SystemExit("live execution is intentionally disabled in the safe default CLI")
        if args.profile not in {"offline-fake", "offline", "fake"}:
            raise SystemExit(f"unsupported safe-default profile: {args.profile}")
        config = BenchmarkConfig.from_file(args.config)
        artifacts = run_matrix(config, args.output_root, live=False)
        _print_json({"status": "ok", "mode": "run", "artifacts": artifacts.as_dict()})
        return 0
    if args.command == "summarize":
        summary = summarize_run(args.run_dir)
        if args.output_csv:
            write_summary_csv(summary, args.output_csv)
        _print_json({"status": "ok", "summary": summary})
        return 0
    if args.command == "compare":
        comparison = compare_runs(args.left_run_dir, args.right_run_dir)
        _print_json({"status": "ok", "comparison": comparison})
        return 0
    raise AssertionError(f"Unhandled command {args.command}")


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
