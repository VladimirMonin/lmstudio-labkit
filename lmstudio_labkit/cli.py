from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

from .benchmarks import BenchmarkConfig, run_matrix, write_matrix_plan
from .live_bridge import LiveBridgeOptions, validate_live_guardrails
from .reports import compare_runs, summarize_run, write_summary_csv

_SAFE_PROFILES = {"offline-plan", "offline-fake", "offline", "fake"}
_LIVE_PROFILES = {"live-small", "live-screening", "overnight"}
_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


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
    run.add_argument("--live", action="store_true", help="Enable guarded live profile validation")
    run.add_argument("--allow-model-loads", action="store_true")
    run.add_argument("--allow-remote-base-url", action="store_true")
    run.add_argument("--allow-stress", action="store_true")
    run.add_argument("--base-url", default="http://127.0.0.1:1234")

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
        _validate_safe_run_id(config.run_id)
        _reject_existing_run_dir(args.output_root, config.run_id)
        artifacts = write_matrix_plan(config, args.output_root)
        _print_json({"status": "ok", "mode": "plan", "artifacts": artifacts.as_dict()})
        return 0
    if args.command in {"run", "run-matrix"}:
        _validate_run_profile(args)
        config = BenchmarkConfig.from_file(args.config)
        _validate_safe_run_id(config.run_id)
        _reject_existing_run_dir(args.output_root, config.run_id, allow_plan_only=True)
        artifacts = run_matrix(config, args.output_root)
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


def _validate_run_profile(args: argparse.Namespace) -> None:
    safety = _load_safety(args.config)
    profile = str(args.profile)
    if profile not in _SAFE_PROFILES | _LIVE_PROFILES:
        raise SystemExit(f"unsupported profile: {profile}")
    if profile in _SAFE_PROFILES:
        if args.live:
            raise SystemExit("safe offline profiles reject --live")
        if safety.get("live") is True:
            raise SystemExit("config safety.live=true requires a live profile")
        return
    if not args.live:
        raise SystemExit(f"profile {profile} requires --live")
    if safety.get("live") is not True:
        raise SystemExit("live CLI execution requires safety.live=true in config")
    if safety.get("allow_model_downloads") is True:
        raise SystemExit("model downloads are not supported by LabKit CLI profiles")
    if safety.get("allow_model_loads") is True and not args.allow_model_loads:
        raise SystemExit("config allows model loads, but CLI requires --allow-model-loads")
    if safety.get("allow_remote_base_url") is True and not args.allow_remote_base_url:
        raise SystemExit("remote base URL requires --allow-remote-base-url")
    max_requests = int(safety.get("max_requests", 1))
    validate_live_guardrails(
        LiveBridgeOptions(
            live=True,
            allow_model_load=False,
            allow_remote=args.allow_remote_base_url,
            allow_stress=args.allow_stress,
            base_url=args.base_url,
            profile=profile,
            max_requests=max_requests,
        ),
        request_count=1,
    )
    raise SystemExit("live profile is valid, but no host-managed executor was provided")


def _validate_safe_run_id(run_id: str) -> None:
    if not _SAFE_RUN_ID_RE.fullmatch(run_id):
        raise SystemExit("run_id must be a safe local identifier")


def _reject_existing_run_dir(
    output_root: str | Path, run_id: str, *, allow_plan_only: bool = False
) -> None:
    run_dir = Path(output_root) / run_id
    if not run_dir.exists():
        return
    if allow_plan_only and _is_plan_only_run_dir(run_dir):
        return
    raise SystemExit(f"output run directory already exists: {run_dir}")


def _is_plan_only_run_dir(run_dir: Path) -> bool:
    cell_results = run_dir / "cell_results.jsonl"
    return cell_results.exists() and cell_results.read_text(encoding="utf-8") == ""


def _load_safety(config_path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    safety = payload.get("safety", {})
    return safety if isinstance(safety, dict) else {}


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
