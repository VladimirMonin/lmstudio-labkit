from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

from .benchmarks import BenchmarkConfig, run_matrix, write_matrix_plan
from .live_bridge import LiveBridgeOptions, validate_live_guardrails
from .managed_executor import (
    LocalLMStudioHostRunner,
    ManagedExecutorError,
    ManagedLMStudioExecutor,
    ManagedLMStudioTransport,
)
from .preflight import preflight_config
from .reports import compare_runs, summarize_run, write_summary_csv
from .review_pack import export_review_pack
from .snapshots import export_latest_text_remote_snapshot
from .suites import compare_suites, plan_suite, preflight_suite, run_suite, summarize_suite

_SAFE_PROFILES = {"offline-plan", "offline-fake", "offline", "fake"}
_LIVE_PROFILES = {"live-small", "live-screening", "overnight"}
_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lmstudio-benchmark")
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight", help="Validate a matrix config without generation")
    preflight.add_argument("--config", required=True)
    preflight.add_argument("--base-url")

    preflight_suite_cmd = sub.add_parser(
        "preflight-suite", help="Validate a suite without generation"
    )
    preflight_suite_cmd.add_argument("--suite", required=True)
    preflight_suite_cmd.add_argument("--base-url")

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
    run.add_argument(
        "--operator-live-managed",
        action="store_true",
        help="Execute live-small through the local managed LM Studio operator path",
    )
    run.add_argument("--base-url", default="http://127.0.0.1:1234")

    plan_suite_cmd = sub.add_parser("plan-suite", help="Write offline plans for every suite config")
    plan_suite_cmd.add_argument("--suite", required=True)
    plan_suite_cmd.add_argument("--output-root", required=True)

    run_suite_cmd = sub.add_parser("run-suite", help="Run an offline/fake suite")
    run_suite_cmd.add_argument("--suite", required=True)
    run_suite_cmd.add_argument("--output-root", required=True)
    run_suite_cmd.add_argument("--profile", default="offline-fake")
    run_suite_cmd.add_argument("--resume", action="store_true")

    summarize_suite_cmd = sub.add_parser("summarize-suite", help="Summarize a suite run directory")
    summarize_suite_cmd.add_argument("--suite-run-dir", required=True)

    compare_suite_cmd = sub.add_parser("compare-suite", help="Compare two suite run directories")
    compare_suite_cmd.add_argument("--left-suite-run-dir", required=True)
    compare_suite_cmd.add_argument("--right-suite-run-dir", required=True)

    summarize = sub.add_parser("summarize", help="Summarize a run directory")
    summarize.add_argument("--run-dir", required=True)
    summarize.add_argument("--output-csv")

    compare = sub.add_parser("compare", help="Compare two run directories")
    compare.add_argument("--left-run-dir", required=True)
    compare.add_argument("--right-run-dir", required=True)

    export_snapshot = sub.add_parser(
        "export-latest-snapshot",
        help="Export a public-safe latest remote text snapshot",
    )
    export_snapshot.add_argument("--run-dir", required=True)
    export_snapshot.add_argument(
        "--output-dir",
        default="docs/live_demo/latest_text_remote_e2b_e4b",
    )

    review_pack = sub.add_parser(
        "export-review-pack",
        help="Export a local-only manual review pack from sanitized run artifacts",
    )
    review_pack.add_argument("--run-dir", required=True)
    review_pack.add_argument("--output-dir", required=True)
    review_pack.add_argument("--limit", type=int, default=12)
    review_pack.add_argument(
        "--include-raw-outputs-local-only",
        action="store_true",
        help="Include local-only raw outputs when run_dir contains raw_cases.jsonl; output dir must be under the platform temp dir or explicitly gitignored",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "preflight":
        result = preflight_config(args.config, base_url=args.base_url).as_dict()
        _print_json({"status": result["status"], "mode": "preflight", "preflight": result})
        return 0 if result["status"] == "pass" else 2
    if args.command == "preflight-suite":
        result = preflight_suite(args.suite, base_url=args.base_url)
        _print_json({"status": result["status"], "mode": "preflight-suite", "preflight": result})
        return 0 if result["status"] == "pass" else 2
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
        if args.operator_live_managed:
            options = LiveBridgeOptions(
                live=True,
                allow_model_load=args.allow_model_loads,
                allow_remote=args.allow_remote_base_url,
                allow_stress=args.allow_stress,
                base_url=args.base_url,
                profile=str(args.profile),
                max_requests=int(config.safety.max_requests),
            )
            host_runner = LocalLMStudioHostRunner(
                base_url=args.base_url,
                allow_remote_base_url=args.allow_remote_base_url,
            )
            executor = ManagedLMStudioExecutor(
                host_runner=host_runner,
                allow_model_loads=args.allow_model_loads,
                strict_json_schema=config.structured_runtime.strict_json_schema,
            )
            try:
                artifacts = run_matrix(
                    config,
                    args.output_root,
                    transport=ManagedLMStudioTransport(executor=executor),
                    live_options=options,
                )
            except ManagedExecutorError as error:
                _print_json(
                    {
                        "status": "error",
                        "mode": "run",
                        "error_category": "managed_executor_error",
                        "message": str(error),
                    }
                )
                return 2
        else:
            artifacts = run_matrix(config, args.output_root)
        _print_json({"status": "ok", "mode": "run", "artifacts": artifacts.as_dict()})
        return 0
    if args.command == "plan-suite":
        result = plan_suite(args.suite, args.output_root)
        _print_json({"status": result["status"], "mode": "plan-suite", "suite": result})
        return 0 if result["status"] == "pass" else 2
    if args.command == "run-suite":
        result = run_suite(
            args.suite,
            args.output_root,
            profile=args.profile,
            resume=args.resume,
        )
        _print_json({"status": result["status"], "mode": "run-suite", "suite": result})
        return 0 if result["status"] == "pass" else 2
    if args.command == "summarize-suite":
        summary = summarize_suite(args.suite_run_dir)
        _print_json({"status": summary["status"], "summary": summary})
        return 0 if summary["status"] == "pass" else 2
    if args.command == "compare-suite":
        comparison = compare_suites(args.left_suite_run_dir, args.right_suite_run_dir)
        _print_json({"status": "ok", "comparison": comparison})
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
    if args.command == "export-latest-snapshot":
        result = export_latest_text_remote_snapshot(args.run_dir, args.output_dir)
        _print_json(
            {"status": result["status"], "mode": "export-latest-snapshot", "snapshot": result}
        )
        return 0 if result["status"] == "pass" else 2
    if args.command == "export-review-pack":
        result = export_review_pack(
            args.run_dir,
            args.output_dir,
            limit=args.limit,
            include_raw_outputs_local_only=args.include_raw_outputs_local_only,
        )
        _print_json(
            {"status": result["status"], "mode": "export-review-pack", "review_pack": result}
        )
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
            allow_model_load=args.allow_model_loads,
            allow_remote=args.allow_remote_base_url,
            allow_stress=args.allow_stress,
            base_url=args.base_url,
            profile=profile,
            max_requests=max_requests,
        ),
        request_count=1,
    )
    if args.operator_live_managed:
        return
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
