from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from tools.lmstudio_lab.cache_plan import (
    create_cache_plan_artifacts,
    default_cache_plan_run_id,
    load_cache_plan_config,
)
from tools.lmstudio_lab.config import (
    load_experiment_config,
    load_raw_experiment_config,
    validate_experiment_config_payload,
)
from tools.lmstudio_lab.datasets import load_dataset_manifest
from tools.lmstudio_lab.matrix import (
    create_structured_matrix_fake_run_artifacts,
    create_structured_matrix_plan_artifacts,
)
from tools.lmstudio_lab.metrics import (
    SCHEMA_VERSION,
    LMStudioLabMetricRecord,
    TokenMetrics,
    append_jsonl_record,
)
from tools.lmstudio_lab.report import (
    RESULT_FILE_NAMES,
    STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES,
    build_structured_validation_summary_csv_row,
    render_dry_run_report,
    write_csv_file,
    write_json_file,
)
from tools.lmstudio_lab.structured import validate_structured_fixture_manifest

if TYPE_CHECKING:
    from tools.lmstudio_lab.identity_probe import IdentityProbeResult
    from tools.lmstudio_lab.model_probe import ModelProbeResult


def probe_lmstudio_models(*args, **kwargs):
    from tools.lmstudio_lab.model_probe import probe_lmstudio_models as impl

    return impl(*args, **kwargs)


def resolve_candidate_models(*args, **kwargs):
    from tools.lmstudio_lab.candidate_resolution import resolve_candidate_models as impl

    return impl(*args, **kwargs)


def probe_lmstudio_identity(*args, **kwargs):
    from tools.lmstudio_lab.identity_probe import probe_lmstudio_identity as impl

    return impl(*args, **kwargs)


def probe_lmstudio_load(*args, **kwargs):
    from tools.lmstudio_lab.load_probe import probe_lmstudio_load as impl

    return impl(*args, **kwargs)


def acquire_candidate_model(*args, **kwargs):
    from tools.lmstudio_lab.model_acquisition import acquire_candidate_model as impl

    return impl(*args, **kwargs)


def probe_model_lifecycle(*args, **kwargs):
    from tools.lmstudio_lab.model_lifecycle import probe_model_lifecycle as impl

    return impl(*args, **kwargs)


def run_live_structured_smoke(*args, **kwargs):
    from tools.lmstudio_lab.live_smoke import run_live_structured_smoke as impl

    return impl(*args, **kwargs)


def run_live_chunked_structured_smoke(*args, **kwargs):
    from tools.lmstudio_lab.live_smoke import run_live_chunked_structured_smoke as impl

    return impl(*args, **kwargs)


def run_live_concurrency_diagnostics(*args, **kwargs):
    from tools.lmstudio_lab.live_smoke import run_live_concurrency_diagnostics as impl

    return impl(*args, **kwargs)


class ManagedLabRunner:
    def __new__(cls, *args, **kwargs):
        from tools.lmstudio_lab.managed_runner import ManagedLabRunner as impl

        return impl(*args, **kwargs)


class SystemMetricsSampler:
    def __new__(cls, *args, **kwargs):
        from tools.lmstudio_lab.system_metrics import SystemMetricsSampler as impl

        return impl(*args, **kwargs)


def write_system_telemetry_artifacts(*args, **kwargs):
    from tools.lmstudio_lab.system_metrics import write_system_telemetry_artifacts as impl

    return impl(*args, **kwargs)


def is_local_lmstudio_base_url(*args, **kwargs):
    from tools.lmstudio_lab.live_config import is_local_lmstudio_base_url as impl

    return impl(*args, **kwargs)


def load_live_smoke_config(*args, **kwargs):
    from tools.lmstudio_lab.live_config import load_live_smoke_config as impl

    return impl(*args, **kwargs)


def _get_live_config_helpers():
    from tools.lmstudio_lab.live_config import is_local_lmstudio_base_url, load_live_smoke_config

    return is_local_lmstudio_base_url, load_live_smoke_config


def _get_live_smoke_helpers():
    from tools.lmstudio_lab.live_smoke import (
        run_live_chunked_structured_smoke,
        run_live_concurrency_diagnostics,
        run_live_structured_smoke,
    )

    return (
        run_live_chunked_structured_smoke,
        run_live_concurrency_diagnostics,
        run_live_structured_smoke,
    )


def _managed_lab_runner_cls():
    from tools.lmstudio_lab.managed_runner import ManagedLabRunner

    return ManagedLabRunner


def _get_system_metrics_helpers():
    from tools.lmstudio_lab.system_metrics import (
        SystemMetricsSampler,
        write_system_telemetry_artifacts,
    )

    return SystemMetricsSampler, write_system_telemetry_artifacts


EXIT_OK = 0
EXIT_PROBE_ERROR = 2
SUMMARY_FIELDNAMES = (
    "context_length",
    "dataset_id",
    "dataset_chars",
    "estimated_input_tokens",
    "actual_input_tokens",
    "estimate_error_ratio",
    "tokenizer_method",
    "tokenizer_family",
    "tokenizer_version",
    "dry_run",
    "experiment_id",
    "load_config_count",
    "mode",
    "model_key",
    "parallel",
    "planned_requests",
    "repeats",
    "run_id",
    "warmup_runs",
    "warmup_policy",
    "warmup_request_count",
    "effective_profile",
    "warmup_is_productive",
    "warmup_wall_time_ms",
    "parallel_batch_wall_time_ms",
    "total_batch_wall_time_ms",
    "avg_batch_wall_time_ms",
    "end_to_end_wall_time_ms",
    "avg_end_to_end_wall_time_ms",
    "sequential_baseline_wall_time_ms",
    "baseline_end_to_end_wall_time_ms",
    "speedup_vs_sequential_baseline",
    "speedup_excluding_warmup",
    "speedup_including_warmup",
    "effective_speedup",
)
STRUCTURED_VALIDATION_OUTPUT_FILE_NAMES = (
    "structured_validation_results.jsonl",
    "structured_validation_summary.csv",
)
_SAFE_MODEL_PROBE_RUN_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")
_SAFE_MODEL_KEY_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_results_root() -> Path:
    return _project_root() / "experiments" / "lmstudio" / "results"


def _build_parser() -> argparse.ArgumentParser:
    from tools.lmstudio_lab.live_smoke import (
        CHUNKED_WARMUP_POLICY_CHOICES,
        EFFECTIVE_PROFILE_CHOICES,
        STRUCTURED_PROMPT_VARIANT_CHOICES,
        STRUCTURED_REASONING_CONTROL_CHOICES,
    )
    from tools.lmstudio_lab.model_lifecycle import MODEL_LIFECYCLE_SCENARIO_CHOICES

    parser = argparse.ArgumentParser(description="LM Studio lab dry-run harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="create dry-run contract outputs")
    run_parser.add_argument("config_path", type=Path)
    run_parser.add_argument("--output-root", type=Path, default=_default_results_root())
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--live", action="store_true")
    run_parser.add_argument("--managed-l3-8b-gemma4-e4b-load-only", action="store_true")
    run_parser.add_argument("--managed-l3-9c-gemma4-12b-qat-load-only", action="store_true")
    run_parser.add_argument("--managed-l3-9d-gemma4-26b-a4b-load-only", action="store_true")
    run_parser.add_argument("--managed-l3-8c-gemma4-e4b-tiny-live-smoke", action="store_true")
    run_parser.add_argument("--managed-l3-8d-gemma4-e4b-strict-json-smoke", action="store_true")
    run_parser.add_argument("--managed-responses-cache-probe", action="store_true")
    run_parser.add_argument("--managed-cache-32k-load-only", action="store_true")
    run_parser.add_argument("--managed-cache-25k-prep", action="store_true")
    run_parser.add_argument("--managed-l3-6-25k-preflight", action="store_true")
    run_parser.add_argument("--managed-l3-6c-compact-memory-live-smoke", action="store_true")
    run_parser.add_argument("--managed-l3-6d-mode-comparison-live", action="store_true")
    run_parser.add_argument("--managed-l3-7d-structured-json-live-smoke", action="store_true")
    run_parser.add_argument("--managed-cache-instrument-live", action="store_true")
    run_parser.add_argument("--managed-cache-compare-live", action="store_true")
    run_parser.add_argument("--managed-cache-live-smoke", action="store_true")
    run_parser.add_argument("--managed-live", action="store_true")
    run_parser.add_argument(
        "--managed-live-true-parallel",
        action="store_true",
    )
    run_parser.add_argument("--validate-structured-fixtures", action="store_true")
    run_parser.add_argument(
        "--structured-prompt-variant",
        choices=STRUCTURED_PROMPT_VARIANT_CHOICES,
        default="baseline",
    )
    run_parser.add_argument(
        "--structured-reasoning-control",
        choices=STRUCTURED_REASONING_CONTROL_CHOICES,
        default="baseline",
    )
    run_parser.add_argument("--verified-context-length", type=int)
    run_parser.add_argument("--context-fit-safety-ratio", type=float, default=0.85)
    run_parser.add_argument("--app-concurrency", type=int)
    run_parser.add_argument("--allow-queue-pressure", action="store_true")
    run_parser.add_argument(
        "--chunked-warmup-policy",
        choices=CHUNKED_WARMUP_POLICY_CHOICES,
    )
    run_parser.add_argument("--chunked-warmup-full-batch", action="store_true")
    run_parser.add_argument(
        "--effective-profile",
        choices=EFFECTIVE_PROFILE_CHOICES,
        default="standard",
    )
    run_parser.add_argument("--sequential-baseline-wall-time-ms", type=float)
    run_parser.add_argument("--baseline-end-to-end-wall-time-ms", type=float)
    run_parser.add_argument("--system-sample-interval-s", type=float, default=1.0)

    probe_parser = subparsers.add_parser(
        "probe-models",
        help="probe LM Studio native loaded-model state",
    )
    probe_parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    probe_parser.add_argument("--model-id")
    probe_parser.add_argument("--output-root", type=Path, default=_default_results_root())
    probe_parser.add_argument("--run-id")
    probe_parser.add_argument("--allow-remote", action="store_true")
    probe_parser.add_argument("--timeout-s", type=float, default=10.0)

    resolve_candidates_parser = subparsers.add_parser(
        "resolve-candidates",
        help="resolve safe LM Studio compat candidate suggestions",
    )
    resolve_candidates_parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    resolve_candidates_parser.add_argument(
        "--registry-path",
        type=Path,
        default=_project_root() / "experiments" / "lmstudio" / "models" / "candidates.yaml",
    )
    resolve_candidates_parser.add_argument(
        "--output-root", type=Path, default=_default_results_root()
    )
    resolve_candidates_parser.add_argument("--run-id")
    resolve_candidates_parser.add_argument("--allow-remote", action="store_true")
    resolve_candidates_parser.add_argument("--timeout-s", type=float, default=10.0)

    acquire_candidate_parser = subparsers.add_parser(
        "acquire-candidate",
        help="plan or request LM Studio model download without loading it",
    )
    acquire_candidate_parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    acquire_candidate_parser.add_argument(
        "--registry-path",
        type=Path,
        default=_project_root() / "experiments" / "lmstudio" / "models" / "candidates.yaml",
    )
    acquire_candidate_parser.add_argument("--lab-key", required=True)
    acquire_candidate_parser.add_argument(
        "--output-root", type=Path, default=_default_results_root()
    )
    acquire_candidate_parser.add_argument("--run-id")
    acquire_candidate_parser.add_argument("--allow-remote", action="store_true")
    acquire_candidate_parser.add_argument("--timeout-s", type=float, default=10.0)
    acquire_candidate_parser.add_argument("--api-token-env", default="LM_API_TOKEN")
    acquire_candidate_parser.add_argument("--execute-download", action="store_true")
    acquire_candidate_parser.add_argument("--poll", action="store_true")
    acquire_candidate_parser.add_argument("--max-polls", type=int, default=60)
    acquire_candidate_parser.add_argument("--poll-interval-s", type=float, default=1.0)

    identity_probe_parser = subparsers.add_parser(
        "probe-identity",
        help="probe LM Studio compat/native model identity visibility",
    )
    identity_probe_parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    identity_probe_parser.add_argument("--model-id", required=True)
    identity_probe_parser.add_argument("--output-root", type=Path, default=_default_results_root())
    identity_probe_parser.add_argument("--run-id")
    identity_probe_parser.add_argument("--allow-remote", action="store_true")
    identity_probe_parser.add_argument("--timeout-s", type=float, default=10.0)

    load_probe_parser = subparsers.add_parser(
        "probe-load",
        help="probe LM Studio native model-load config echo",
    )
    load_probe_parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    load_probe_parser.add_argument("--model-id", required=True)
    load_probe_parser.add_argument("--context-length", type=int, default=32768)
    load_probe_parser.add_argument("--parallel", type=int, default=1)
    load_probe_parser.add_argument("--output-root", type=Path, default=_default_results_root())
    load_probe_parser.add_argument("--run-id")
    load_probe_parser.add_argument("--allow-remote", action="store_true")
    load_probe_parser.add_argument("--timeout-s", type=float, default=120.0)

    lifecycle_probe_parser = subparsers.add_parser(
        "probe-lifecycle",
        help="plan or execute lab-only LM Studio lifecycle probes",
    )
    lifecycle_probe_parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    lifecycle_probe_parser.add_argument("--model-id", required=True)
    lifecycle_probe_parser.add_argument("--secondary-model-id")
    lifecycle_probe_parser.add_argument(
        "--scenario",
        required=True,
        choices=MODEL_LIFECYCLE_SCENARIO_CHOICES,
    )
    lifecycle_probe_parser.add_argument("--context-length", type=int, default=8192)
    lifecycle_probe_parser.add_argument("--parallel", type=int, default=1)
    lifecycle_probe_parser.add_argument("--output-root", type=Path, default=_default_results_root())
    lifecycle_probe_parser.add_argument("--run-id")
    lifecycle_probe_parser.add_argument("--allow-remote", action="store_true")
    lifecycle_probe_parser.add_argument("--timeout-s", type=float, default=120.0)
    lifecycle_probe_parser.add_argument("--max-polls", type=int, default=30)
    lifecycle_probe_parser.add_argument("--poll-interval-s", type=float, default=1.0)
    lifecycle_probe_parser.add_argument("--api-token-env", default="LM_API_TOKEN")
    lifecycle_probe_parser.add_argument("--execute-lifecycle", action="store_true")

    concurrency_probe_parser = subparsers.add_parser(
        "probe-concurrency",
        help="run offline-tested LM Studio compat concurrency diagnostics",
    )
    concurrency_probe_parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    concurrency_probe_parser.add_argument("--model-id", required=True)
    concurrency_probe_parser.add_argument("--model-key")
    concurrency_probe_parser.add_argument("--kind", required=True)
    concurrency_probe_parser.add_argument("--app-concurrency", type=int, default=2)
    concurrency_probe_parser.add_argument("--loaded-parallel", type=int)
    concurrency_probe_parser.add_argument("--allow-queue-pressure", action="store_true")
    concurrency_probe_parser.add_argument(
        "--output-root", type=Path, default=_default_results_root()
    )
    concurrency_probe_parser.add_argument("--run-id")
    concurrency_probe_parser.add_argument("--timeout-s", type=float, default=30.0)
    concurrency_probe_parser.add_argument("--max-tokens", type=int)
    concurrency_probe_parser.add_argument("--verified-context-length", type=int)
    concurrency_probe_parser.add_argument("--context-fit-safety-ratio", type=float, default=0.85)
    concurrency_probe_parser.add_argument("--system-sample-interval-s", type=float, default=1.0)

    plan_cache_parser = subparsers.add_parser(
        "plan-cache",
        help="create no-live cache/stateful/prefix planning artifacts",
    )
    plan_cache_parser.add_argument("config_path", type=Path)
    plan_cache_parser.add_argument("--output-root", type=Path, default=_default_results_root())
    plan_cache_parser.add_argument("--run-id")

    plan_matrix_parser = subparsers.add_parser(
        "plan-matrix",
        help="create offline structured matrix planning artifacts",
    )
    plan_matrix_parser.add_argument("config_path", type=Path)
    plan_matrix_parser.add_argument("--output-root", type=Path, default=_default_results_root())
    plan_matrix_parser.add_argument("--run-id")

    run_matrix_parser = subparsers.add_parser(
        "run-matrix",
        help="execute the offline fake structured matrix runner",
    )
    run_matrix_parser.add_argument("config_path", type=Path)
    run_matrix_parser.add_argument("--output-root", type=Path, default=_default_results_root())
    run_matrix_parser.add_argument("--run-id")
    run_matrix_parser.add_argument(
        "--fake",
        action="store_true",
        help="required: use deterministic fake responses and no network calls",
    )
    return parser


def _build_plan_cache_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LM Studio lab cache-plan harness")
    parser.add_argument("command", choices=("plan-cache",))
    parser.add_argument("config_path", type=Path)
    parser.add_argument("--output-root", type=Path, default=_default_results_root())
    parser.add_argument("--run-id")
    return parser


def _parse_args(argv: list[str]) -> argparse.Namespace:
    if argv and argv[0] == "plan-cache":
        return _build_plan_cache_parser().parse_args(argv)
    return _build_parser().parse_args(argv)


def _default_run_id(experiment_id: str, *, live: bool = False) -> str:
    suffix = "live_smoke" if live else "dry_run"
    return f"{experiment_id}_{suffix}"


def _default_model_probe_run_id() -> str:
    return "probe_models"


def _default_candidate_resolution_run_id() -> str:
    return "resolve_candidates"


def _default_model_acquisition_run_id() -> str:
    return "acquire_candidate"


def _default_identity_probe_run_id() -> str:
    return "probe_identity"


def _default_load_probe_run_id() -> str:
    return "probe_load"


def _default_model_lifecycle_run_id(scenario: str) -> str:
    safe_scenario = _SAFE_MODEL_KEY_RE.sub("_", scenario).strip("._-") or "probe_lifecycle"
    return f"probe_lifecycle_{safe_scenario}"


def _default_concurrency_probe_run_id(diagnostic_kind: str) -> str:
    safe_kind = _SAFE_MODEL_KEY_RE.sub("_", diagnostic_kind).strip("._-") or "probe"
    return f"probe_concurrency_{safe_kind}"


def _derive_safe_model_key(model_id: str) -> str:
    safe_key = _SAFE_MODEL_KEY_RE.sub("_", model_id).strip("._-")
    return safe_key or "model"


def _validate_probe_run_id(run_id: str, *, command_name: str) -> str:
    candidate = run_id.strip()
    if candidate != run_id or not candidate:
        raise ValueError(f"{command_name} run_id must use a safe local identifier")
    if len(candidate) > 120:
        raise ValueError(f"{command_name} run_id must use a safe local identifier")
    if "://" in candidate or "/" in candidate or "\\" in candidate:
        raise ValueError(f"{command_name} run_id must use a safe local identifier")
    if len(candidate) >= 2 and candidate[1] == ":" and candidate[0].isalpha():
        raise ValueError(f"{command_name} run_id must use a safe local identifier")
    if _SAFE_MODEL_PROBE_RUN_ID_RE.fullmatch(candidate) is None:
        raise ValueError(f"{command_name} run_id must use a safe local identifier")
    return candidate


def _write_empty_jsonl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _write_exact_bytes_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _build_environment_payload(
    *,
    experiment_id: str,
    run_id: str,
    dry_run: bool,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dry_run": dry_run,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
        "python_version": platform.python_version(),
    }


def _build_system_providers(*, command_name: str) -> dict[str, str]:
    return {"lmstudio_local": command_name}


def _build_load_config_records(
    *,
    experiment_id: str,
    run_id: str,
    config,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    load_config_index = 1
    for model in config.models:
        for load_config in model.iter_load_configs():
            records.append(
                {
                    "dry_run": True,
                    "experiment_id": experiment_id,
                    "load_config": load_config,
                    "load_config_id": f"load_{load_config_index:04d}",
                    "model_key": model.key,
                    "run_id": run_id,
                    "schema_version": SCHEMA_VERSION,
                }
            )
            load_config_index += 1
    return records


def _build_request_records(
    *,
    experiment_id: str,
    run_id: str,
    config,
    load_config_records,
    dataset_manifests,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    requests: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    request_index = 1
    runs_per_combination = config.warmup_runs + config.repeats
    for load_config_record in load_config_records:
        load_config = load_config_record["load_config"]
        context_length = load_config.get("context_length")
        parallel = load_config.get("parallel")
        for mode in config.modes:
            for manifest in dataset_manifests:
                summary_rows.append(
                    {
                        "context_length": context_length,
                        "dataset_id": manifest.dataset_id,
                        "dataset_chars": manifest.chars,
                        "estimated_input_tokens": manifest.estimated_input_tokens,
                        "actual_input_tokens": manifest.actual_input_tokens,
                        "estimate_error_ratio": manifest.estimate_error_ratio,
                        "dry_run": True,
                        "experiment_id": experiment_id,
                        "load_config_count": len(load_config_records),
                        "mode": mode,
                        "model_key": load_config_record["model_key"],
                        "parallel": parallel,
                        "planned_requests": runs_per_combination,
                        "repeats": config.repeats,
                        "run_id": run_id,
                        "tokenizer_method": manifest.tokenizer.method,
                        "tokenizer_family": manifest.tokenizer.family,
                        "tokenizer_version": manifest.tokenizer.version,
                        "warmup_runs": config.warmup_runs,
                    }
                )
                for run_index in range(runs_per_combination):
                    is_warmup = run_index < config.warmup_runs
                    phase = "warmup" if is_warmup else "measure"
                    repeat_index = 0 if is_warmup else (run_index - config.warmup_runs + 1)
                    requests.append(
                        {
                            "dataset_hash": manifest.content_hash,
                            "dataset_id": manifest.dataset_id,
                            "dataset_items_count": manifest.items_count,
                            "dataset_chars": manifest.chars,
                            "dry_run": True,
                            "estimated_input_tokens": manifest.estimated_input_tokens,
                            "actual_input_tokens": manifest.actual_input_tokens,
                            "estimate_error_ratio": manifest.estimate_error_ratio,
                            "experiment_id": experiment_id,
                            "load_config": load_config,
                            "load_config_id": load_config_record["load_config_id"],
                            "mode": mode,
                            "model_key": load_config_record["model_key"],
                            "phase": phase,
                            "repeat_index": repeat_index,
                            "request_id": f"req_{request_index:05d}",
                            "run_id": run_id,
                            "schema_version": SCHEMA_VERSION,
                            "tokenizer_method": manifest.tokenizer.method,
                            "tokenizer_family": manifest.tokenizer.family,
                            "tokenizer_version": manifest.tokenizer.version,
                            "warmup": is_warmup,
                        }
                    )
                    request_index += 1
    return requests, summary_rows


def _append_records(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    for record in records:
        append_jsonl_record(path, record)


def _build_metric_records(
    *,
    experiment_id: str,
    run_id: str,
    requests,
) -> list[LMStudioLabMetricRecord]:
    records: list[LMStudioLabMetricRecord] = []
    for request in requests:
        load_config = request["load_config"]
        estimated_input_tokens = request.get("estimated_input_tokens")
        actual_input_tokens = request.get("actual_input_tokens")
        app_concurrency = load_config.get("parallel") if isinstance(load_config, dict) else None
        records.append(
            LMStudioLabMetricRecord.from_parts(
                run_id=run_id,
                experiment_id=experiment_id,
                request_id=str(request["request_id"]),
                dataset_id=str(request["dataset_id"]),
                dataset_hash=str(request["dataset_hash"]),
                model_key=str(request["model_key"]),
                endpoint_kind="dry_run",
                mode=str(request["mode"]),
                requested_context_length=load_config.get("context_length"),
                requested_parallel=load_config.get("parallel"),
                app_concurrency=app_concurrency if isinstance(app_concurrency, int) else None,
                applied_load_config=load_config,
                tokens=TokenMetrics(
                    estimated_input_tokens=(
                        int(estimated_input_tokens)
                        if isinstance(estimated_input_tokens, int)
                        else None
                    ),
                    actual_input_tokens=(
                        int(actual_input_tokens) if isinstance(actual_input_tokens, int) else None
                    ),
                ),
            )
        )
    return records


def _build_live_summary_row(*, config, metric_row, dataset_manifest) -> dict[str, object]:
    tokens = metric_row.get("tokens") if isinstance(metric_row.get("tokens"), dict) else {}
    return {
        "context_length": metric_row.get("requested_context_length"),
        "dataset_id": dataset_manifest.dataset_id,
        "dataset_chars": dataset_manifest.chars,
        "estimated_input_tokens": dataset_manifest.estimated_input_tokens,
        "actual_input_tokens": tokens.get("actual_input_tokens"),
        "estimate_error_ratio": dataset_manifest.estimate_error_ratio,
        "tokenizer_method": dataset_manifest.tokenizer.method,
        "tokenizer_family": dataset_manifest.tokenizer.family,
        "tokenizer_version": dataset_manifest.tokenizer.version,
        "dry_run": False,
        "experiment_id": config.experiment_id,
        "load_config_count": 1,
        "mode": config.modes[0],
        "model_key": config.models[0].key,
        "parallel": metric_row.get("requested_parallel"),
        "planned_requests": 1,
        "repeats": config.repeats,
        "run_id": metric_row.get("run_id"),
        "warmup_runs": config.warmup_runs,
        "warmup_policy": None,
        "warmup_request_count": None,
        "effective_profile": None,
        "warmup_is_productive": None,
        "warmup_wall_time_ms": None,
        "parallel_batch_wall_time_ms": None,
        "total_batch_wall_time_ms": None,
        "avg_batch_wall_time_ms": None,
        "end_to_end_wall_time_ms": None,
        "avg_end_to_end_wall_time_ms": None,
        "sequential_baseline_wall_time_ms": None,
        "baseline_end_to_end_wall_time_ms": None,
        "speedup_vs_sequential_baseline": None,
        "speedup_excluding_warmup": None,
        "speedup_including_warmup": None,
        "effective_speedup": None,
    }


def _build_chunked_live_summary_row(
    *, config, batch_summary, dataset_manifest
) -> dict[str, object]:
    return {
        "context_length": batch_summary.get("requested_context_length"),
        "dataset_id": dataset_manifest.dataset_id,
        "dataset_chars": dataset_manifest.chars,
        "estimated_input_tokens": dataset_manifest.estimated_input_tokens,
        "actual_input_tokens": batch_summary.get("total_prompt_tokens"),
        "estimate_error_ratio": dataset_manifest.estimate_error_ratio,
        "tokenizer_method": dataset_manifest.tokenizer.method,
        "tokenizer_family": dataset_manifest.tokenizer.family,
        "tokenizer_version": dataset_manifest.tokenizer.version,
        "dry_run": False,
        "experiment_id": config.experiment_id,
        "load_config_count": 1,
        "mode": config.modes[0],
        "model_key": config.models[0].key,
        "parallel": batch_summary.get("requested_parallel"),
        "planned_requests": batch_summary.get("planned_requests"),
        "repeats": config.repeats,
        "run_id": batch_summary.get("run_id"),
        "warmup_runs": config.warmup_runs,
        "warmup_policy": batch_summary.get("warmup_policy"),
        "warmup_request_count": batch_summary.get("warmup_request_count"),
        "effective_profile": batch_summary.get("effective_profile"),
        "warmup_is_productive": batch_summary.get("warmup_is_productive"),
        "warmup_wall_time_ms": batch_summary.get("warmup_wall_time_ms"),
        "parallel_batch_wall_time_ms": batch_summary.get("parallel_batch_wall_time_ms"),
        "total_batch_wall_time_ms": batch_summary.get("total_batch_wall_time_ms"),
        "avg_batch_wall_time_ms": batch_summary.get("avg_batch_wall_time_ms"),
        "end_to_end_wall_time_ms": batch_summary.get("end_to_end_wall_time_ms"),
        "avg_end_to_end_wall_time_ms": batch_summary.get("avg_end_to_end_wall_time_ms"),
        "sequential_baseline_wall_time_ms": batch_summary.get("sequential_baseline_wall_time_ms"),
        "baseline_end_to_end_wall_time_ms": batch_summary.get("baseline_end_to_end_wall_time_ms"),
        "speedup_vs_sequential_baseline": batch_summary.get("speedup_vs_sequential_baseline"),
        "speedup_excluding_warmup": batch_summary.get("speedup_excluding_warmup"),
        "speedup_including_warmup": batch_summary.get("speedup_including_warmup"),
        "effective_speedup": batch_summary.get("effective_speedup"),
    }


def _prepare_run_dir(*, output_root: Path, run_id: str, experiment_id: str) -> Path:
    run_dir = output_root / f"run_{run_id}_{experiment_id}"
    if run_dir.exists():
        raise FileExistsError(
            f"run output already exists for run_id {run_id!r} and experiment_id {experiment_id!r}"
        )
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _run_dry_run(args: argparse.Namespace) -> int:
    config_bytes = Path(args.config_path).read_bytes()
    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    validate_experiment_config_payload(raw_config_payload)
    config = load_experiment_config(args.config_path)
    run_id = args.run_id or _default_run_id(config.experiment_id)

    dataset_manifests = [load_dataset_manifest(dataset_id) for dataset_id in config.datasets]
    load_config_records = _build_load_config_records(
        experiment_id=config.experiment_id,
        run_id=run_id,
        config=config,
    )
    request_records, summary_rows = _build_request_records(
        experiment_id=config.experiment_id,
        run_id=run_id,
        config=config,
        load_config_records=load_config_records,
        dataset_manifests=dataset_manifests,
    )

    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=config.experiment_id,
    )
    environment_payload = _build_environment_payload(
        experiment_id=config.experiment_id,
        run_id=run_id,
        dry_run=True,
    )

    _write_exact_bytes_file(run_dir / "experiment.yaml", config_bytes)
    write_json_file(run_dir / "environment.json", environment_payload)
    _append_records(run_dir / "load_configs.jsonl", load_config_records)
    _append_records(run_dir / "requests.jsonl", request_records)

    metrics_path = run_dir / "metrics.jsonl"
    metrics_path.write_text("", encoding="utf-8")
    for metric_record in _build_metric_records(
        experiment_id=config.experiment_id,
        run_id=run_id,
        requests=request_records,
    ):
        append_jsonl_record(metrics_path, metric_record)

    write_csv_file(
        run_dir / "gpu_samples.csv",
        fieldnames=(
            "dry_run",
            "gpu_name",
            "gpu_utilization_percent",
            "gpu_vram_total_mb",
            "gpu_vram_used_mb",
            "sample_index",
            "timestamp_utc",
        ),
        rows=(
            {
                "dry_run": True,
                "gpu_name": "",
                "gpu_utilization_percent": "",
                "gpu_vram_total_mb": "",
                "gpu_vram_used_mb": "",
                "sample_index": 0,
                "timestamp_utc": "",
            },
        ),
    )
    _write_empty_jsonl(run_dir / "structured_errors.jsonl")
    write_csv_file(
        run_dir / "summary.csv",
        fieldnames=SUMMARY_FIELDNAMES,
        rows=summary_rows,
    )

    structured_validation_summary = None
    output_files = RESULT_FILE_NAMES
    if args.validate_structured_fixtures:
        structured_validation_batch = validate_structured_fixture_manifest()
        structured_validation_records = [
            {
                "experiment_id": config.experiment_id,
                "run_id": run_id,
                **record,
            }
            for record in structured_validation_batch.records
        ]
        _append_records(
            run_dir / "structured_validation_results.jsonl",
            structured_validation_records,
        )
        structured_validation_summary = structured_validation_batch.summarize().to_dict()
        write_csv_file(
            run_dir / "structured_validation_summary.csv",
            fieldnames=STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES,
            rows=[
                build_structured_validation_summary_csv_row(
                    structured_validation_summary,
                    experiment_id=config.experiment_id,
                    run_id=run_id,
                    mode="offline_structured_validation",
                    dataset_id=structured_validation_batch.manifest.fixture_set_id,
                    fixture_set_id=structured_validation_batch.manifest.fixture_set_id,
                    status="completed",
                )
            ],
        )
        output_files = RESULT_FILE_NAMES + STRUCTURED_VALIDATION_OUTPUT_FILE_NAMES

    (run_dir / "report.md").write_text(
        render_dry_run_report(
            config=config,
            environment=environment_payload,
            run_id=run_id,
            dataset_rows=[manifest.to_dict() for manifest in dataset_manifests],
            load_config_count=len(load_config_records),
            request_count=len(request_records),
            structured_error_count=0,
            structured_validation_summary=structured_validation_summary,
            output_files=output_files,
        ),
        encoding="utf-8",
    )
    return EXIT_OK


def _run_plan_cache(args: argparse.Namespace) -> int:
    config = load_cache_plan_config(args.config_path)
    run_id = args.run_id or default_cache_plan_run_id(config.experiment_id)
    _validate_probe_run_id(run_id, command_name="plan-cache")
    create_cache_plan_artifacts(
        args.config_path,
        output_root=args.output_root,
        run_id=run_id,
    )
    return EXIT_OK


def _run_plan_matrix(args: argparse.Namespace) -> int:
    create_structured_matrix_plan_artifacts(
        args.config_path,
        output_root=args.output_root,
        run_id=args.run_id,
    )
    return EXIT_OK


def _run_matrix_fake(args: argparse.Namespace) -> int:
    if not args.fake:
        raise ValueError("run-matrix is offline-only and requires --fake")
    create_structured_matrix_fake_run_artifacts(
        args.config_path,
        output_root=args.output_root,
        run_id=args.run_id,
    )
    return EXIT_OK


def _run_live_smoke(args: argparse.Namespace) -> int:
    from tools.lmstudio_lab.report import (
        LIVE_CHUNKED_RESULT_FILE_NAMES,
        LIVE_RESULT_FILE_NAMES,
        render_live_chunked_smoke_report,
        render_live_smoke_report,
    )

    if args.validate_structured_fixtures:
        raise ValueError("--validate-structured-fixtures cannot be combined with --live")
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")

    config_bytes = Path(args.config_path).read_bytes()
    config = load_live_smoke_config(args.config_path, live_enabled=True)
    chunked_only_args_used = (
        args.app_concurrency is not None
        or args.allow_queue_pressure
        or args.chunked_warmup_policy is not None
        or args.chunked_warmup_full_batch
        or args.effective_profile != "standard"
        or args.sequential_baseline_wall_time_ms is not None
        or args.baseline_end_to_end_wall_time_ms is not None
    )
    if config.datasets[0] != "blocks_json_medium_chunked" and chunked_only_args_used:
        raise ValueError(
            "--app-concurrency, --allow-queue-pressure, --chunked-warmup-policy, --chunked-warmup-full-batch, "
            "--effective-profile, --sequential-baseline-wall-time-ms, and "
            "--baseline-end-to-end-wall-time-ms require the blocks_json_medium_chunked live dataset"
        )
    structured_prompt_variant = args.structured_prompt_variant
    structured_reasoning_control = args.structured_reasoning_control
    if (
        config.datasets[0] == "blocks_json_medium_chunked"
        and structured_prompt_variant != "baseline"
    ):
        raise ValueError(
            "--structured-prompt-variant currently supports only baseline for the "
            "blocks_json_medium_chunked live dataset"
        )
    if (
        config.datasets[0] == "blocks_json_medium_chunked"
        and structured_reasoning_control != "baseline"
    ):
        raise ValueError(
            "--structured-reasoning-control currently supports only baseline for the "
            "blocks_json_medium_chunked live dataset"
        )
    run_id = args.run_id or _default_run_id(config.experiment_id, live=True)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=config.experiment_id,
    )
    environment_payload = _build_environment_payload(
        experiment_id=config.experiment_id,
        run_id=run_id,
        dry_run=False,
    )
    environment_payload["system_sample_interval_s"] = args.system_sample_interval_s
    environment_payload["structured_prompt_variant"] = structured_prompt_variant
    environment_payload["structured_reasoning_control_variant"] = structured_reasoning_control
    dataset_manifest = load_dataset_manifest(config.datasets[0])
    _write_exact_bytes_file(run_dir / "experiment.yaml", config_bytes)
    write_json_file(run_dir / "environment.json", environment_payload)

    metrics_path = run_dir / "metrics.jsonl"
    metrics_path.write_text("", encoding="utf-8")
    structured_errors_path = run_dir / "structured_errors.jsonl"
    structured_errors_path.write_text("", encoding="utf-8")
    system_sampler = SystemMetricsSampler(sample_interval_s=args.system_sample_interval_s)
    system_summary = None
    system_sampler.start(providers=_build_system_providers(command_name="live_run"))

    if config.datasets[0] == "blocks_json_medium_chunked":
        try:
            outcome = run_live_chunked_structured_smoke(
                config,
                run_id=run_id,
                verified_context_length=args.verified_context_length,
                context_fit_safety_ratio=args.context_fit_safety_ratio,
                app_concurrency=(args.app_concurrency if args.app_concurrency is not None else 1),
                warmup_policy=args.chunked_warmup_policy,
                warmup_full_batch=args.chunked_warmup_full_batch,
                effective_profile=args.effective_profile,
                sequential_baseline_wall_time_ms=args.sequential_baseline_wall_time_ms,
                baseline_end_to_end_wall_time_ms=args.baseline_end_to_end_wall_time_ms,
                allow_queue_pressure=args.allow_queue_pressure,
            )
        finally:
            system_summary = system_sampler.stop(
                providers=_build_system_providers(command_name="live_run")
            )
        for metric in outcome.metrics:
            append_jsonl_record(metrics_path, metric)
        for structured_error in outcome.structured_errors:
            append_jsonl_record(structured_errors_path, structured_error)
        if system_summary is not None:
            write_system_telemetry_artifacts(
                run_dir,
                samples=system_sampler.samples,
                summary=system_summary,
            )
        write_json_file(run_dir / "batch_summary.json", outcome.batch_summary)
        write_csv_file(
            run_dir / "summary.csv",
            fieldnames=SUMMARY_FIELDNAMES,
            rows=[
                _build_chunked_live_summary_row(
                    config=config,
                    batch_summary=outcome.batch_summary,
                    dataset_manifest=dataset_manifest,
                )
            ],
        )
        (run_dir / "report.md").write_text(
            render_live_chunked_smoke_report(
                config=config,
                environment=environment_payload,
                run_id=run_id,
                dataset_row=dataset_manifest.to_dict(),
                batch_summary=outcome.batch_summary,
                structured_error_count=len(outcome.structured_errors),
                output_files=LIVE_CHUNKED_RESULT_FILE_NAMES,
            ),
            encoding="utf-8",
        )
        return EXIT_OK

    try:
        outcome = run_live_structured_smoke(
            config,
            run_id=run_id,
            verified_context_length=args.verified_context_length,
            context_fit_safety_ratio=args.context_fit_safety_ratio,
            prompt_variant=structured_prompt_variant,
            reasoning_control_variant=structured_reasoning_control,
        )
    finally:
        system_summary = system_sampler.stop(
            providers=_build_system_providers(command_name="live_run")
        )
    metric_row = outcome.metric.to_dict()

    append_jsonl_record(metrics_path, outcome.metric)
    if outcome.structured_error is not None:
        append_jsonl_record(structured_errors_path, outcome.structured_error)
    if system_summary is not None:
        write_system_telemetry_artifacts(
            run_dir,
            samples=system_sampler.samples,
            summary=system_summary,
        )

    write_csv_file(
        run_dir / "summary.csv",
        fieldnames=SUMMARY_FIELDNAMES,
        rows=[
            _build_live_summary_row(
                config=config,
                metric_row=metric_row,
                dataset_manifest=dataset_manifest,
            )
        ],
    )
    (run_dir / "report.md").write_text(
        render_live_smoke_report(
            config=config,
            environment=environment_payload,
            run_id=run_id,
            dataset_row=dataset_manifest.to_dict(),
            metric_row=metric_row,
            structured_error_count=0 if outcome.structured_error is None else 1,
            output_files=LIVE_RESULT_FILE_NAMES,
        ),
        encoding="utf-8",
    )
    return EXIT_OK


def _run_managed_live(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_live_true_parallel
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
    ):
        raise ValueError(
            "--live, --managed-live, --managed-live-true-parallel, --managed-l3-9c-gemma4-12b-qat-load-only, --managed-l3-9d-gemma4-26b-a4b-load-only, --managed-l3-8c-gemma4-e4b-tiny-live-smoke, --managed-l3-8d-gemma4-e4b-strict-json-smoke, --managed-l3-6c-compact-memory-live-smoke, --managed-l3-6d-mode-comparison-live, and --managed-l3-7d-structured-json-live-smoke are mutually exclusive"
        )
    if args.validate_structured_fixtures:
        raise ValueError("--validate-structured-fixtures cannot be combined with --managed-live")
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError("--verified-context-length is incompatible with --managed-live")
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError("--managed-live supports only --app-concurrency 1")
    if args.allow_queue_pressure:
        raise ValueError("--allow-queue-pressure is incompatible with --managed-live")
    if args.chunked_warmup_policy is not None:
        raise ValueError("--chunked-warmup-policy is incompatible with --managed-live")
    if args.chunked_warmup_full_batch:
        raise ValueError("--chunked-warmup-full-batch is incompatible with --managed-live")
    if args.effective_profile != "standard":
        raise ValueError("--managed-live supports only --effective-profile standard")
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError("--sequential-baseline-wall-time-ms is incompatible with --managed-live")
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError("--baseline-end-to-end-wall-time-ms is incompatible with --managed-live")

    config = load_live_smoke_config(args.config_path, live_enabled=True)
    run_id = args.run_id or _default_run_id(config.experiment_id, live=True)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=config.experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_medium_chunked_sequential_live(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_live_run"),
        app_concurrency=(args.app_concurrency if args.app_concurrency is not None else 1),
        context_fit_safety_ratio=args.context_fit_safety_ratio,
    )
    return EXIT_OK


def _run_managed_cache_25k_prep(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError("--managed-cache-25k-prep is mutually exclusive with live managed runners")
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-cache-25k-prep"
        )
    if args.verified_context_length is not None:
        raise ValueError("--verified-context-length is incompatible with --managed-cache-25k-prep")
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError("--managed-cache-25k-prep supports only --app-concurrency 1")
    if args.allow_queue_pressure:
        raise ValueError("--allow-queue-pressure is incompatible with --managed-cache-25k-prep")
    if args.chunked_warmup_policy is not None:
        raise ValueError("--chunked-warmup-policy is incompatible with --managed-cache-25k-prep")
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-cache-25k-prep"
        )
    if args.effective_profile != "standard":
        raise ValueError("--managed-cache-25k-prep supports only --effective-profile standard")
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-cache-25k-prep"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-cache-25k-prep"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(lambda request: None)
    runner.run_cache_25k_no_live_prep(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_cache_25k_prep"),
    )
    return EXIT_OK


def _run_managed_l3_6_25k_preflight(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_responses_cache_probe
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_32k_load_only
        or args.managed_cache_25k_prep
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-l3-6-25k-preflight is mutually exclusive with live and other managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-l3-6-25k-preflight"
        )
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-l3-6-25k-preflight"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError("--managed-l3-6-25k-preflight supports only --app-concurrency 1")
    if args.allow_queue_pressure:
        raise ValueError("--allow-queue-pressure is incompatible with --managed-l3-6-25k-preflight")
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-l3-6-25k-preflight"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-l3-6-25k-preflight"
        )
    if args.effective_profile != "standard":
        raise ValueError("--managed-l3-6-25k-preflight supports only --effective-profile standard")
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-l3-6-25k-preflight"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-l3-6-25k-preflight"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(lambda request: None)
    runner.run_l3_6_25k_no_live_preflight(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_l3_6_25k_preflight"),
    )
    return EXIT_OK


def _run_managed_responses_cache_probe(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_32k_load_only
        or args.managed_cache_25k_prep
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-responses-cache-probe is mutually exclusive with live and other managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-responses-cache-probe"
        )
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-responses-cache-probe"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError("--managed-responses-cache-probe supports only --app-concurrency 1")
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-responses-cache-probe"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-responses-cache-probe"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-responses-cache-probe"
        )
    if args.effective_profile != "standard":
        raise ValueError(
            "--managed-responses-cache-probe supports only --effective-profile standard"
        )
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-responses-cache-probe"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-responses-cache-probe"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(lambda request: None)
    runner.run_responses_cache_probe(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_responses_cache_probe"),
        timeout_s=120.0,
    )
    return EXIT_OK


def _run_managed_cache_32k_load_only(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_25k_prep
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-cache-32k-load-only is mutually exclusive with live and managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-cache-32k-load-only"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-cache-32k-load-only"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError("--managed-cache-32k-load-only supports only --app-concurrency 1")
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-cache-32k-load-only"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-cache-32k-load-only"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-cache-32k-load-only"
        )
    if args.effective_profile != "standard":
        raise ValueError("--managed-cache-32k-load-only supports only --effective-profile standard")
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-cache-32k-load-only"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-cache-32k-load-only"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_cache_32k_load_only_smoke(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_cache_32k_load_only"),
        timeout_s=120.0,
    )
    return EXIT_OK


def _run_managed_l3_8b_gemma4_e4b_load_only(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_responses_cache_probe
        or args.managed_cache_32k_load_only
        or args.managed_cache_25k_prep
        or args.managed_l3_6_25k_preflight
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-l3-8b-gemma4-e4b-load-only is mutually exclusive with live and managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-l3-8b-gemma4-e4b-load-only"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-l3-8b-gemma4-e4b-load-only"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError("--managed-l3-8b-gemma4-e4b-load-only supports only --app-concurrency 1")
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-l3-8b-gemma4-e4b-load-only"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-l3-8b-gemma4-e4b-load-only"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-l3-8b-gemma4-e4b-load-only"
        )
    if args.effective_profile != "standard":
        raise ValueError(
            "--managed-l3-8b-gemma4-e4b-load-only supports only --effective-profile standard"
        )
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-l3-8b-gemma4-e4b-load-only"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-l3-8b-gemma4-e4b-load-only"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_l3_8b_gemma4_e4b_load_only_16k_32k(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_l3_8b_gemma4_e4b_load_only"),
        timeout_s=120.0,
    )
    return EXIT_OK


def _run_managed_l3_9c_gemma4_12b_qat_load_only(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_8b_gemma4_e4b_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_responses_cache_probe
        or args.managed_cache_32k_load_only
        or args.managed_cache_25k_prep
        or args.managed_l3_6_25k_preflight
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-l3-9c-gemma4-12b-qat-load-only is mutually exclusive with live and managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-l3-9c-gemma4-12b-qat-load-only"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-l3-9c-gemma4-12b-qat-load-only"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError(
            "--managed-l3-9c-gemma4-12b-qat-load-only supports only --app-concurrency 1"
        )
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-l3-9c-gemma4-12b-qat-load-only"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-l3-9c-gemma4-12b-qat-load-only"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-l3-9c-gemma4-12b-qat-load-only"
        )
    if args.effective_profile != "standard":
        raise ValueError(
            "--managed-l3-9c-gemma4-12b-qat-load-only supports only --effective-profile standard"
        )
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-l3-9c-gemma4-12b-qat-load-only"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-l3-9c-gemma4-12b-qat-load-only"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_l3_9c_gemma4_12b_qat_load_only_8k_16k(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_l3_9c_gemma4_12b_qat_load_only"),
        timeout_s=120.0,
    )
    return EXIT_OK


def _run_managed_l3_9d_gemma4_26b_a4b_load_only(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_8b_gemma4_e4b_load_only
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_responses_cache_probe
        or args.managed_cache_32k_load_only
        or args.managed_cache_25k_prep
        or args.managed_l3_6_25k_preflight
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-l3-9d-gemma4-26b-a4b-load-only is mutually exclusive with live and managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-l3-9d-gemma4-26b-a4b-load-only"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-l3-9d-gemma4-26b-a4b-load-only"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError(
            "--managed-l3-9d-gemma4-26b-a4b-load-only supports only --app-concurrency 1"
        )
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-l3-9d-gemma4-26b-a4b-load-only"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-l3-9d-gemma4-26b-a4b-load-only"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-l3-9d-gemma4-26b-a4b-load-only"
        )
    if args.effective_profile != "standard":
        raise ValueError(
            "--managed-l3-9d-gemma4-26b-a4b-load-only supports only --effective-profile standard"
        )
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-l3-9d-gemma4-26b-a4b-load-only"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-l3-9d-gemma4-26b-a4b-load-only"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_l3_9d_gemma4_26b_a4b_qat_load_only_8k(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_l3_9d_gemma4_26b_a4b_load_only"),
        timeout_s=120.0,
    )
    return EXIT_OK


def _run_managed_l3_8c_gemma4_e4b_tiny_live_smoke(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_8b_gemma4_e4b_load_only
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_responses_cache_probe
        or args.managed_cache_32k_load_only
        or args.managed_cache_25k_prep
        or args.managed_l3_6_25k_preflight
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-l3-8c-gemma4-e4b-tiny-live-smoke is mutually exclusive with live and managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-l3-8c-gemma4-e4b-tiny-live-smoke"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-l3-8c-gemma4-e4b-tiny-live-smoke"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError(
            "--managed-l3-8c-gemma4-e4b-tiny-live-smoke supports only --app-concurrency 1"
        )
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-l3-8c-gemma4-e4b-tiny-live-smoke"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-l3-8c-gemma4-e4b-tiny-live-smoke"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-l3-8c-gemma4-e4b-tiny-live-smoke"
        )
    if args.effective_profile != "standard":
        raise ValueError(
            "--managed-l3-8c-gemma4-e4b-tiny-live-smoke supports only --effective-profile standard"
        )
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-l3-8c-gemma4-e4b-tiny-live-smoke"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-l3-8c-gemma4-e4b-tiny-live-smoke"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_l3_8c_gemma4_e4b_tiny_live_smoke(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_l3_8c_gemma4_e4b_tiny_live_smoke"),
        timeout_s=120.0,
    )
    return EXIT_OK


def _run_managed_l3_8d_gemma4_e4b_strict_json_smoke(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_8b_gemma4_e4b_load_only
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_responses_cache_probe
        or args.managed_cache_32k_load_only
        or args.managed_cache_25k_prep
        or args.managed_l3_6_25k_preflight
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-l3-8d-gemma4-e4b-strict-json-smoke is mutually exclusive with live and managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-l3-8d-gemma4-e4b-strict-json-smoke"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-l3-8d-gemma4-e4b-strict-json-smoke"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError(
            "--managed-l3-8d-gemma4-e4b-strict-json-smoke supports only --app-concurrency 1"
        )
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-l3-8d-gemma4-e4b-strict-json-smoke"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-l3-8d-gemma4-e4b-strict-json-smoke"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-l3-8d-gemma4-e4b-strict-json-smoke"
        )
    if args.effective_profile != "standard":
        raise ValueError(
            "--managed-l3-8d-gemma4-e4b-strict-json-smoke supports only --effective-profile standard"
        )
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-l3-8d-gemma4-e4b-strict-json-smoke"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-l3-8d-gemma4-e4b-strict-json-smoke"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_l3_8d_gemma4_e4b_strict_json_smoke(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(
            command_name="managed_l3_8d_gemma4_e4b_strict_json_smoke"
        ),
        timeout_s=120.0,
    )
    return EXIT_OK


def _run_managed_l3_6c_compact_memory_live_smoke(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_responses_cache_probe
        or args.managed_cache_32k_load_only
        or args.managed_cache_25k_prep
        or args.managed_l3_6_25k_preflight
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-l3-6c-compact-memory-live-smoke is mutually exclusive with live and other managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-l3-6c-compact-memory-live-smoke"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-l3-6c-compact-memory-live-smoke"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError(
            "--managed-l3-6c-compact-memory-live-smoke supports only --app-concurrency 1"
        )
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-l3-6c-compact-memory-live-smoke"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-l3-6c-compact-memory-live-smoke"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-l3-6c-compact-memory-live-smoke"
        )
    if args.effective_profile != "standard":
        raise ValueError(
            "--managed-l3-6c-compact-memory-live-smoke supports only --effective-profile standard"
        )
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-l3-6c-compact-memory-live-smoke"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-l3-6c-compact-memory-live-smoke"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_l3_6c_25k_compact_memory_live_smoke(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_l3_6c_compact_memory_live_smoke"),
        timeout_s=120.0,
    )
    return EXIT_OK


def _run_managed_l3_6d_mode_comparison_live(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_responses_cache_probe
        or args.managed_cache_32k_load_only
        or args.managed_cache_25k_prep
        or args.managed_l3_6_25k_preflight
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-l3-6d-mode-comparison-live is mutually exclusive with live and other managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-l3-6d-mode-comparison-live"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-l3-6d-mode-comparison-live"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError("--managed-l3-6d-mode-comparison-live supports only --app-concurrency 1")
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-l3-6d-mode-comparison-live"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-l3-6d-mode-comparison-live"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-l3-6d-mode-comparison-live"
        )
    if args.effective_profile != "standard":
        raise ValueError(
            "--managed-l3-6d-mode-comparison-live supports only --effective-profile standard"
        )
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-l3-6d-mode-comparison-live"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-l3-6d-mode-comparison-live"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_l3_6d_25k_mode_comparison_live(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_l3_6d_mode_comparison_live"),
        timeout_s=120.0,
    )
    return EXIT_OK


def _run_managed_l3_7d_structured_json_live_smoke(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_responses_cache_probe
        or args.managed_cache_32k_load_only
        or args.managed_cache_25k_prep
        or args.managed_l3_6_25k_preflight
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_cache_instrument_live
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--managed-l3-7d-structured-json-live-smoke is mutually exclusive with live and other managed runner flags"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-l3-7d-structured-json-live-smoke"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-l3-7d-structured-json-live-smoke"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError(
            "--managed-l3-7d-structured-json-live-smoke supports only --app-concurrency 1"
        )
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-l3-7d-structured-json-live-smoke"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-l3-7d-structured-json-live-smoke"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-l3-7d-structured-json-live-smoke"
        )
    if args.effective_profile != "standard":
        raise ValueError(
            "--managed-l3-7d-structured-json-live-smoke supports only --effective-profile standard"
        )
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-l3-7d-structured-json-live-smoke"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-l3-7d-structured-json-live-smoke"
        )

    _, raw_config_payload = load_raw_experiment_config(args.config_path)
    experiment_id = str(raw_config_payload.get("experiment_id", "")).strip()
    run_id = args.run_id or _default_run_id(experiment_id)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_l3_7d_structured_json_live_smoke(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_l3_7d_structured_json_live_smoke"),
        timeout_s=120.0,
    )
    return EXIT_OK


def _run_managed_cache_live_smoke(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--live, --managed-cache-live-smoke, --managed-l3-9c-gemma4-12b-qat-load-only, --managed-l3-9d-gemma4-26b-a4b-load-only, --managed-l3-8c-gemma4-e4b-tiny-live-smoke, --managed-l3-8d-gemma4-e4b-strict-json-smoke, --managed-l3-6c-compact-memory-live-smoke, --managed-l3-6d-mode-comparison-live, --managed-l3-7d-structured-json-live-smoke, --managed-live, and --managed-live-true-parallel are mutually exclusive"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-cache-live-smoke"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-cache-live-smoke"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError("--managed-cache-live-smoke supports only --app-concurrency 1")
    if args.allow_queue_pressure:
        raise ValueError("--allow-queue-pressure is incompatible with --managed-cache-live-smoke")
    if args.chunked_warmup_policy is not None:
        raise ValueError("--chunked-warmup-policy is incompatible with --managed-cache-live-smoke")
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-cache-live-smoke"
        )
    if args.effective_profile != "standard":
        raise ValueError("--managed-cache-live-smoke supports only --effective-profile standard")
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-cache-live-smoke"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-cache-live-smoke"
        )

    config = load_live_smoke_config(args.config_path, live_enabled=True)
    run_id = args.run_id or _default_run_id(config.experiment_id, live=True)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=config.experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_cache_stateful_live_smoke(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_cache_live_smoke"),
        app_concurrency=(args.app_concurrency if args.app_concurrency is not None else 1),
    )
    return EXIT_OK


def _run_managed_cache_compare_live(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--live, --managed-cache-compare-live, --managed-cache-live-smoke, --managed-l3-9c-gemma4-12b-qat-load-only, --managed-l3-9d-gemma4-26b-a4b-load-only, --managed-l3-8c-gemma4-e4b-tiny-live-smoke, --managed-l3-8d-gemma4-e4b-strict-json-smoke, --managed-l3-6c-compact-memory-live-smoke, --managed-l3-6d-mode-comparison-live, --managed-l3-7d-structured-json-live-smoke, --managed-live, and --managed-live-true-parallel are mutually exclusive"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-cache-compare-live"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-cache-compare-live"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError("--managed-cache-compare-live supports only --app-concurrency 1")
    if args.allow_queue_pressure:
        raise ValueError("--allow-queue-pressure is incompatible with --managed-cache-compare-live")
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-cache-compare-live"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-cache-compare-live"
        )
    if args.effective_profile != "standard":
        raise ValueError("--managed-cache-compare-live supports only --effective-profile standard")
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-cache-compare-live"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-cache-compare-live"
        )

    config = load_live_smoke_config(args.config_path, live_enabled=True)
    run_id = args.run_id or _default_run_id(config.experiment_id, live=True)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=config.experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_cache_stateful_comparison_live(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_cache_compare_live"),
        app_concurrency=(args.app_concurrency if args.app_concurrency is not None else 1),
    )
    return EXIT_OK


def _run_managed_cache_instrument_live(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
        or args.managed_cache_compare_live
        or args.managed_cache_live_smoke
        or args.managed_live
        or args.managed_live_true_parallel
    ):
        raise ValueError(
            "--live, --managed-cache-instrument-live, --managed-cache-compare-live, --managed-cache-live-smoke, --managed-l3-9c-gemma4-12b-qat-load-only, --managed-l3-9d-gemma4-26b-a4b-load-only, --managed-l3-8c-gemma4-e4b-tiny-live-smoke, --managed-l3-8d-gemma4-e4b-strict-json-smoke, --managed-l3-6c-compact-memory-live-smoke, --managed-l3-6d-mode-comparison-live, --managed-l3-7d-structured-json-live-smoke, --managed-live, and --managed-live-true-parallel are mutually exclusive"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-cache-instrument-live"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-cache-instrument-live"
        )
    if args.app_concurrency is not None and args.app_concurrency != 1:
        raise ValueError("--managed-cache-instrument-live supports only --app-concurrency 1")
    if args.allow_queue_pressure:
        raise ValueError(
            "--allow-queue-pressure is incompatible with --managed-cache-instrument-live"
        )
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-cache-instrument-live"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-cache-instrument-live"
        )
    if args.effective_profile != "standard":
        raise ValueError(
            "--managed-cache-instrument-live supports only --effective-profile standard"
        )
    if args.sequential_baseline_wall_time_ms is not None:
        raise ValueError(
            "--sequential-baseline-wall-time-ms is incompatible with --managed-cache-instrument-live"
        )
    if args.baseline_end_to_end_wall_time_ms is not None:
        raise ValueError(
            "--baseline-end-to-end-wall-time-ms is incompatible with --managed-cache-instrument-live"
        )

    config = load_live_smoke_config(args.config_path, live_enabled=True)
    run_id = args.run_id or _default_run_id(config.experiment_id, live=True)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=config.experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_cache_stateful_instrumentation_live(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_cache_instrument_live"),
        app_concurrency=(args.app_concurrency if args.app_concurrency is not None else 1),
    )
    return EXIT_OK


def _run_managed_live_true_parallel(args: argparse.Namespace) -> int:
    if (
        args.live
        or args.managed_live
        or args.managed_l3_9c_gemma4_12b_qat_load_only
        or args.managed_l3_9d_gemma4_26b_a4b_load_only
        or args.managed_l3_8c_gemma4_e4b_tiny_live_smoke
        or args.managed_l3_8d_gemma4_e4b_strict_json_smoke
        or args.managed_l3_6c_compact_memory_live_smoke
        or args.managed_l3_6d_mode_comparison_live
        or args.managed_l3_7d_structured_json_live_smoke
    ):
        raise ValueError(
            "--live, --managed-live, --managed-live-true-parallel, --managed-l3-9c-gemma4-12b-qat-load-only, --managed-l3-9d-gemma4-26b-a4b-load-only, --managed-l3-8c-gemma4-e4b-tiny-live-smoke, --managed-l3-8d-gemma4-e4b-strict-json-smoke, --managed-l3-6c-compact-memory-live-smoke, --managed-l3-6d-mode-comparison-live, and --managed-l3-7d-structured-json-live-smoke are mutually exclusive"
        )
    if args.validate_structured_fixtures:
        raise ValueError(
            "--validate-structured-fixtures cannot be combined with --managed-live-true-parallel"
        )
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.verified_context_length is not None:
        raise ValueError(
            "--verified-context-length is incompatible with --managed-live-true-parallel"
        )
    if args.app_concurrency is not None and args.app_concurrency != 2:
        raise ValueError("--managed-live-true-parallel supports only --app-concurrency 2")
    if args.allow_queue_pressure:
        raise ValueError("--allow-queue-pressure is incompatible with --managed-live-true-parallel")
    if args.chunked_warmup_policy is not None:
        raise ValueError(
            "--chunked-warmup-policy is incompatible with --managed-live-true-parallel"
        )
    if args.chunked_warmup_full_batch:
        raise ValueError(
            "--chunked-warmup-full-batch is incompatible with --managed-live-true-parallel"
        )
    if args.effective_profile != "standard":
        raise ValueError("--managed-live-true-parallel supports only --effective-profile standard")

    config = load_live_smoke_config(args.config_path, live_enabled=True)
    run_id = args.run_id or _default_run_id(config.experiment_id, live=True)
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id=config.experiment_id,
    )

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=SystemMetricsSampler(
            sample_interval_s=args.system_sample_interval_s,
        ),
    )
    runner.run_medium_chunked_true_parallel_live(
        config_path=args.config_path,
        run_dir=run_dir,
        run_id=run_id,
        providers=_build_system_providers(command_name="managed_live_true_parallel_run"),
        app_concurrency=(args.app_concurrency if args.app_concurrency is not None else 2),
        context_fit_safety_ratio=args.context_fit_safety_ratio,
        sequential_baseline_wall_time_ms=args.sequential_baseline_wall_time_ms,
        baseline_end_to_end_wall_time_ms=args.baseline_end_to_end_wall_time_ms,
    )
    return EXIT_OK


def _build_model_probe_environment_payload(
    *,
    run_id: str,
    allow_remote: bool,
    timeout_s: float,
) -> dict[str, object]:
    payload = _build_environment_payload(
        experiment_id="model_probe",
        run_id=run_id,
        dry_run=False,
    )
    payload["command"] = "probe-models"
    payload["allow_remote"] = allow_remote
    payload["timeout_s"] = timeout_s
    return payload


def _build_candidate_resolution_environment_payload(
    *,
    run_id: str,
    allow_remote: bool,
    timeout_s: float,
) -> dict[str, object]:
    payload = _build_environment_payload(
        experiment_id="candidate_resolution",
        run_id=run_id,
        dry_run=False,
    )
    payload["command"] = "resolve-candidates"
    payload["allow_remote"] = allow_remote
    payload["timeout_s"] = timeout_s
    return payload


def _build_model_acquisition_environment_payload(
    *,
    run_id: str,
    lab_key: str,
    allow_remote: bool,
    timeout_s: float,
    execute_download: bool,
    poll_enabled: bool,
    api_token_present: bool,
    max_polls: int,
    poll_interval_s: float,
) -> dict[str, object]:
    payload = _build_environment_payload(
        experiment_id="model_acquisition",
        run_id=run_id,
        dry_run=not execute_download,
    )
    payload["command"] = "acquire-candidate"
    payload["lab_key"] = lab_key
    payload["allow_remote"] = allow_remote
    payload["timeout_s"] = timeout_s
    payload["execute_download"] = execute_download
    payload["poll_enabled"] = poll_enabled
    payload["api_token_present"] = api_token_present
    payload["max_polls"] = max_polls
    payload["poll_interval_s"] = poll_interval_s
    return payload


def _build_load_probe_environment_payload(
    *,
    run_id: str,
    model_id: str,
    requested_context_length: int,
    requested_parallel: int,
    allow_remote: bool,
    timeout_s: float,
) -> dict[str, object]:
    payload = _build_environment_payload(
        experiment_id="load_probe",
        run_id=run_id,
        dry_run=False,
    )
    payload["command"] = "probe-load"
    payload["model_id"] = model_id
    payload["requested_context_length"] = requested_context_length
    payload["requested_parallel"] = requested_parallel
    payload["allow_remote"] = allow_remote
    payload["timeout_s"] = timeout_s
    return payload


def _build_model_lifecycle_environment_payload(
    *,
    run_id: str,
    model_id: str,
    secondary_model_id: str | None,
    scenario: str,
    requested_context_length: int,
    requested_parallel: int,
    allow_remote: bool,
    timeout_s: float,
    max_polls: int,
    poll_interval_s: float,
    api_token_env: str,
    execute_lifecycle: bool,
) -> dict[str, object]:
    payload = _build_environment_payload(
        experiment_id="model_lifecycle",
        run_id=run_id,
        dry_run=not execute_lifecycle,
    )
    payload["command"] = "probe-lifecycle"
    payload["model_id"] = model_id
    payload["scenario"] = scenario
    payload["requested_context_length"] = requested_context_length
    payload["requested_parallel"] = requested_parallel
    payload["allow_remote"] = allow_remote
    payload["timeout_s"] = timeout_s
    payload["max_polls"] = max_polls
    payload["poll_interval_s"] = poll_interval_s
    payload["api_token_env"] = api_token_env
    payload["execute_lifecycle"] = execute_lifecycle
    if secondary_model_id is not None:
        payload["secondary_model_id"] = secondary_model_id
    return payload


def _build_identity_probe_environment_payload(
    *,
    run_id: str,
    allow_remote: bool,
    timeout_s: float,
    result: IdentityProbeResult,
) -> dict[str, object]:
    payload = _build_environment_payload(
        experiment_id="identity_probe",
        run_id=run_id,
        dry_run=False,
    )
    payload["command"] = "probe-identity"
    payload["allow_remote"] = allow_remote
    payload["timeout_s"] = timeout_s
    payload["target_hash"] = result.summary.get("target_hash")
    payload["target_model_id_safe"] = result.summary.get("target_model_id_safe")
    return payload


def _build_concurrency_probe_environment_payload(
    *,
    run_id: str,
    diagnostic_kind: str,
    model_id: str,
    model_key: str,
    app_concurrency: int,
    loaded_parallel: int | None,
    allow_queue_pressure: bool,
    timeout_s: float,
    max_tokens_override: int | None,
    verified_context_length: int | None,
    context_fit_safety_ratio: float,
) -> dict[str, object]:
    payload = _build_environment_payload(
        experiment_id="concurrency_diagnostics",
        run_id=run_id,
        dry_run=False,
    )
    payload["command"] = "probe-concurrency"
    payload["diagnostic_kind"] = diagnostic_kind
    payload["model_id"] = model_id
    payload["model_key"] = model_key
    payload["endpoint_kind"] = "compat_chat"
    payload["localhost_only"] = True
    payload["app_concurrency"] = app_concurrency
    payload["loaded_parallel"] = loaded_parallel
    payload["allow_queue_pressure"] = allow_queue_pressure
    payload["timeout_s"] = timeout_s
    payload["max_tokens"] = max_tokens_override
    payload["max_tokens_override"] = max_tokens_override
    payload["context_fit_safety_ratio"] = context_fit_safety_ratio
    payload["raw_prompt_response_stored"] = False
    if verified_context_length is not None:
        payload["verified_context_length"] = verified_context_length
    return payload


def _build_identity_gated_load_summary(
    *,
    model_id: str,
    allow_remote: bool,
    is_localhost: bool,
    timeout_s: float,
    requested_context_length: int,
    requested_parallel: int,
    identity_result: IdentityProbeResult,
) -> dict[str, object]:
    from tools.lmstudio_lab.load_probe import LOAD_PROBE_ENDPOINT_PATH

    summary: dict[str, object] = {
        "probe_kind": "native_model_load",
        "endpoint_path": LOAD_PROBE_ENDPOINT_PATH,
        "allow_remote": allow_remote,
        "is_localhost": is_localhost,
        "timeout_s": timeout_s,
        "model_id": model_id,
        "requested_context_length": requested_context_length,
        "requested_parallel": requested_parallel,
        "status": "model_identity_unresolved",
        "error_category": "identity",
        "identity_status": identity_result.summary.get("status"),
        "identity_error_category": identity_result.summary.get("error_category"),
        "target_found_compat": bool(identity_result.summary.get("target_found_compat")),
        "target_found_native": bool(identity_result.summary.get("target_found_native")),
        "target_hash_match": bool(identity_result.summary.get("target_hash_match")),
        "native_load_id_resolved": bool(identity_result.summary.get("native_load_id_resolved")),
    }
    if "target_hash" in identity_result.summary:
        summary["target_hash"] = identity_result.summary.get("target_hash")
    return summary


def _write_model_probe_records(
    run_dir: Path,
    result: ModelProbeResult,
    *,
    run_id: str,
) -> None:
    models_path = run_dir / "models.jsonl"
    models_path.write_text("", encoding="utf-8")
    for record in result.model_records:
        append_jsonl_record(
            models_path,
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                **record,
            },
        )


def _run_model_probe(args: argparse.Namespace) -> int:
    from tools.lmstudio_lab.model_probe import (
        MODEL_PROBE_RESULT_FILE_NAMES,
        build_model_probe_url,
        is_local_model_probe_base_url,
        render_model_probe_report,
    )

    if args.timeout_s <= 0:
        raise ValueError("--timeout-s must be > 0")
    build_model_probe_url(args.base_url)
    if not args.allow_remote and not is_local_model_probe_base_url(args.base_url):
        raise ValueError("--base-url must stay on localhost unless --allow-remote is set")

    run_id = _validate_probe_run_id(
        args.run_id or _default_model_probe_run_id(),
        command_name="probe-models",
    )
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id="model_probe",
    )
    environment_payload = _build_model_probe_environment_payload(
        run_id=run_id,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
    )
    result = probe_lmstudio_models(
        args.base_url,
        target_model_id=args.model_id,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
    )

    write_json_file(run_dir / "environment.json", environment_payload)
    write_json_file(run_dir / "model_probe.json", result.summary)
    _write_model_probe_records(run_dir, result, run_id=run_id)
    (run_dir / "report.md").write_text(
        render_model_probe_report(
            run_id=run_id,
            summary=result.summary,
            output_files=MODEL_PROBE_RESULT_FILE_NAMES,
        ),
        encoding="utf-8",
    )
    return EXIT_OK if result.summary.get("status") == "ok" else EXIT_PROBE_ERROR


def _run_candidate_resolution(args: argparse.Namespace) -> int:
    from tools.lmstudio_lab.candidate_resolution import (
        CANDIDATE_RESOLUTION_RESULT_FILE_NAMES,
        build_candidate_resolution_url,
        is_local_candidate_resolution_base_url,
        render_candidate_resolution_report,
    )

    if args.timeout_s <= 0:
        raise ValueError("--timeout-s must be > 0")
    build_candidate_resolution_url(args.base_url)
    if not args.allow_remote and not is_local_candidate_resolution_base_url(args.base_url):
        raise ValueError("--base-url must stay on localhost unless --allow-remote is set")

    run_id = _validate_probe_run_id(
        args.run_id or _default_candidate_resolution_run_id(),
        command_name="resolve-candidates",
    )
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id="candidate_resolution",
    )
    environment_payload = _build_candidate_resolution_environment_payload(
        run_id=run_id,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
    )
    result = resolve_candidate_models(
        args.base_url,
        registry_path=args.registry_path,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
    )

    write_json_file(run_dir / "environment.json", environment_payload)
    _write_exact_bytes_file(
        run_dir / "candidate_resolution.json",
        (
            json.dumps(
                {
                    "summary": result.summary,
                    "candidates": list(result.candidate_records),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )
    if result.suggestion_records:
        for record in result.suggestion_records:
            append_jsonl_record(
                run_dir / "candidate_suggestions.jsonl",
                {
                    "schema_version": SCHEMA_VERSION,
                    "run_id": run_id,
                    **record,
                },
            )
    else:
        _write_empty_jsonl(run_dir / "candidate_suggestions.jsonl")
    (run_dir / "report.md").write_text(
        render_candidate_resolution_report(
            run_id=run_id,
            summary=result.summary,
            candidate_records=result.candidate_records,
            output_files=CANDIDATE_RESOLUTION_RESULT_FILE_NAMES,
        ),
        encoding="utf-8",
    )
    return EXIT_OK if result.summary.get("status") == "ok" else EXIT_PROBE_ERROR


def _run_model_acquisition(args: argparse.Namespace) -> int:
    from tools.lmstudio_lab.model_acquisition import (
        MODEL_ACQUISITION_RESULT_FILE_NAMES,
        build_model_acquisition_url,
        is_local_model_acquisition_base_url,
        render_model_acquisition_report,
    )

    if args.timeout_s <= 0:
        raise ValueError("--timeout-s must be > 0")
    if args.poll and not args.execute_download:
        raise ValueError("--poll requires --execute-download")
    if args.max_polls <= 0:
        raise ValueError("--max-polls must be > 0")
    if args.poll_interval_s <= 0:
        raise ValueError("--poll-interval-s must be > 0")
    build_model_acquisition_url(args.base_url)
    if not args.allow_remote and not is_local_model_acquisition_base_url(args.base_url):
        raise ValueError("--base-url must stay on localhost unless --allow-remote is set")

    run_id = _validate_probe_run_id(
        args.run_id or _default_model_acquisition_run_id(),
        command_name="acquire-candidate",
    )
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id="model_acquisition",
    )
    result = acquire_candidate_model(
        args.base_url,
        registry_path=args.registry_path,
        lab_key=args.lab_key,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
        api_token_env=args.api_token_env,
        execute_download=bool(args.execute_download),
        poll=bool(args.poll),
        max_polls=args.max_polls,
        poll_interval_s=args.poll_interval_s,
    )
    environment_payload = _build_model_acquisition_environment_payload(
        run_id=run_id,
        lab_key=args.lab_key,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
        execute_download=bool(args.execute_download),
        poll_enabled=bool(args.poll),
        api_token_present=bool(result.summary.get("api_token_present")),
        max_polls=args.max_polls,
        poll_interval_s=args.poll_interval_s,
    )

    write_json_file(run_dir / "environment.json", environment_payload)
    write_json_file(run_dir / "model_acquisition.json", result.summary)
    if result.status_records:
        for record in result.status_records:
            append_jsonl_record(
                run_dir / "download_status.jsonl",
                {
                    "schema_version": SCHEMA_VERSION,
                    "run_id": run_id,
                    **record,
                },
            )
    else:
        _write_empty_jsonl(run_dir / "download_status.jsonl")
    (run_dir / "report.md").write_text(
        render_model_acquisition_report(
            run_id=run_id,
            summary=result.summary,
            output_files=MODEL_ACQUISITION_RESULT_FILE_NAMES,
        ),
        encoding="utf-8",
    )
    return EXIT_OK if result.summary.get("status") in {"planned", "ok"} else EXIT_PROBE_ERROR


def _run_identity_probe(args: argparse.Namespace) -> int:
    from tools.lmstudio_lab.identity_probe import (
        IDENTITY_PROBE_RESULT_FILE_NAMES,
        build_identity_probe_compat_url,
        is_local_identity_probe_base_url,
        render_identity_probe_report,
    )

    if args.timeout_s <= 0:
        raise ValueError("--timeout-s must be > 0")
    build_identity_probe_compat_url(args.base_url)
    if not args.allow_remote and not is_local_identity_probe_base_url(args.base_url):
        raise ValueError("--base-url must stay on localhost unless --allow-remote is set")

    run_id = _validate_probe_run_id(
        args.run_id or _default_identity_probe_run_id(),
        command_name="probe-identity",
    )
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id="identity_probe",
    )
    result = probe_lmstudio_identity(
        args.base_url,
        target_model_id=args.model_id,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
    )
    environment_payload = _build_identity_probe_environment_payload(
        run_id=run_id,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
        result=result,
    )

    write_json_file(run_dir / "environment.json", environment_payload)
    write_json_file(run_dir / "identity_probe.json", result.summary)
    (run_dir / "report.md").write_text(
        render_identity_probe_report(
            run_id=run_id,
            summary=result.summary,
            output_files=IDENTITY_PROBE_RESULT_FILE_NAMES,
        ),
        encoding="utf-8",
    )
    return EXIT_OK if result.summary.get("status") == "ok" else EXIT_PROBE_ERROR


def _run_load_probe(args: argparse.Namespace) -> int:
    from tools.lmstudio_lab.load_probe import (
        LOAD_PROBE_RESULT_FILE_NAMES,
        build_load_probe_url,
        is_local_load_probe_base_url,
        render_load_probe_report,
        validate_load_probe_model_id,
    )

    if args.timeout_s <= 0:
        raise ValueError("--timeout-s must be > 0")
    if args.context_length <= 0:
        raise ValueError("--context-length must be > 0")
    if args.parallel <= 0:
        raise ValueError("--parallel must be > 0")
    build_load_probe_url(args.base_url)
    if not args.allow_remote and not is_local_load_probe_base_url(args.base_url):
        raise ValueError("--base-url must stay on localhost unless --allow-remote is set")

    safe_model_id = validate_load_probe_model_id(args.model_id)
    run_id = _validate_probe_run_id(
        args.run_id or _default_load_probe_run_id(),
        command_name="probe-load",
    )
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id="load_probe",
    )
    environment_payload = _build_load_probe_environment_payload(
        run_id=run_id,
        model_id=safe_model_id,
        requested_context_length=args.context_length,
        requested_parallel=args.parallel,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
    )
    identity_result = probe_lmstudio_identity(
        args.base_url,
        target_model_id=safe_model_id,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
    )

    if identity_result.summary.get("status") != "ok" or identity_result.native_load_id is None:
        result_summary = _build_identity_gated_load_summary(
            model_id=safe_model_id,
            allow_remote=bool(args.allow_remote),
            is_localhost=is_local_load_probe_base_url(args.base_url),
            timeout_s=args.timeout_s,
            requested_context_length=args.context_length,
            requested_parallel=args.parallel,
            identity_result=identity_result,
        )
        write_json_file(run_dir / "environment.json", environment_payload)
        write_json_file(run_dir / "load_probe.json", result_summary)
        (run_dir / "report.md").write_text(
            render_load_probe_report(
                run_id=run_id,
                summary=result_summary,
                output_files=LOAD_PROBE_RESULT_FILE_NAMES,
            ),
            encoding="utf-8",
        )
        return EXIT_PROBE_ERROR

    result = probe_lmstudio_load(
        args.base_url,
        model_id=identity_result.native_load_id,
        context_length=args.context_length,
        parallel=args.parallel,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
        display_model_id=safe_model_id,
        resolved_native_load_id_hash=identity_result.summary.get("native_load_id_hash"),
    )

    write_json_file(run_dir / "environment.json", environment_payload)
    write_json_file(run_dir / "load_probe.json", result.summary)
    (run_dir / "report.md").write_text(
        render_load_probe_report(
            run_id=run_id,
            summary=result.summary,
            output_files=LOAD_PROBE_RESULT_FILE_NAMES,
        ),
        encoding="utf-8",
    )
    return EXIT_OK if result.summary.get("status") == "ok" else EXIT_PROBE_ERROR


def _run_probe_lifecycle(args: argparse.Namespace) -> int:
    from tools.lmstudio_lab.model_lifecycle import (
        MODEL_LIFECYCLE_RESULT_FILE_NAMES,
        build_model_lifecycle_list_url,
        is_local_model_lifecycle_base_url,
        render_model_lifecycle_report,
        validate_model_lifecycle_api_token_env,
        validate_model_lifecycle_model_id,
    )

    if args.timeout_s <= 0:
        raise ValueError("--timeout-s must be > 0")
    if args.context_length <= 0:
        raise ValueError("--context-length must be > 0")
    if args.parallel <= 0:
        raise ValueError("--parallel must be > 0")
    if args.max_polls <= 0:
        raise ValueError("--max-polls must be > 0")
    if args.poll_interval_s <= 0:
        raise ValueError("--poll-interval-s must be > 0")
    build_model_lifecycle_list_url(args.base_url)
    if not args.allow_remote and not is_local_model_lifecycle_base_url(args.base_url):
        raise ValueError("--base-url must stay on localhost unless --allow-remote is set")

    safe_model_id = validate_model_lifecycle_model_id(args.model_id)
    safe_secondary_model_id = None
    if args.secondary_model_id is not None:
        safe_secondary_model_id = validate_model_lifecycle_model_id(args.secondary_model_id)
    validate_model_lifecycle_api_token_env(args.api_token_env)
    if (
        args.scenario
        in {
            "two_model_swap_plan",
            "policy_two_model_swap",
        }
        and safe_secondary_model_id is None
    ):
        raise ValueError(f"--secondary-model-id is required for scenario {args.scenario}")

    run_id = _validate_probe_run_id(
        args.run_id or _default_model_lifecycle_run_id(args.scenario),
        command_name="probe-lifecycle",
    )
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id="model_lifecycle",
    )
    environment_payload = _build_model_lifecycle_environment_payload(
        run_id=run_id,
        model_id=safe_model_id,
        secondary_model_id=safe_secondary_model_id,
        scenario=args.scenario,
        requested_context_length=args.context_length,
        requested_parallel=args.parallel,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
        max_polls=args.max_polls,
        poll_interval_s=args.poll_interval_s,
        api_token_env=args.api_token_env,
        execute_lifecycle=bool(args.execute_lifecycle),
    )
    result = probe_model_lifecycle(
        args.base_url,
        model_id=safe_model_id,
        secondary_model_id=safe_secondary_model_id,
        scenario=args.scenario,
        context_length=args.context_length,
        parallel=args.parallel,
        allow_remote=bool(args.allow_remote),
        timeout_s=args.timeout_s,
        max_polls=args.max_polls,
        poll_interval_s=args.poll_interval_s,
        api_token_env=args.api_token_env,
        execute_lifecycle=bool(args.execute_lifecycle),
    )

    write_json_file(run_dir / "environment.json", environment_payload)
    write_json_file(run_dir / "lifecycle_summary.json", result.summary)
    events_path = run_dir / "lifecycle_events.jsonl"
    if result.event_records:
        for record in result.event_records:
            append_jsonl_record(events_path, record)
    else:
        _write_empty_jsonl(events_path)
    (run_dir / "report.md").write_text(
        render_model_lifecycle_report(
            run_id=run_id,
            summary=result.summary,
            output_files=MODEL_LIFECYCLE_RESULT_FILE_NAMES,
        ),
        encoding="utf-8",
    )
    success_statuses = {
        "planned",
        "ok",
        "already_unloaded",
        "externally_unloaded",
        "manual_unload_not_observed",
        "load_succeeded_response_lost",
        "load_succeeded_but_response_lost",
        "load_unknown_or_failed",
        "load_reconcile_error",
        "duplicate_instances",
        "duplicate_reused_or_idempotent",
        "duplicate_instances_confirmed",
        "duplicate_rejected",
        "preloaded_not_clean",
        "policy_smoke_ok",
        "policy_smoke_preloaded_not_clean",
        "policy_swap_ok",
        "policy_swap_preloaded_not_clean",
        "config_mismatch",
        "duplicate_state_ambiguous",
        "not_loaded",
        "still_loaded",
    }
    return EXIT_OK if result.summary.get("status") in success_statuses else EXIT_PROBE_ERROR


def _run_probe_concurrency(args: argparse.Namespace) -> int:
    from tools.lmstudio_lab.report import (
        CONCURRENCY_DIAGNOSTICS_RESULT_FILE_NAMES,
        render_concurrency_diagnostics_report,
    )

    if args.timeout_s <= 0:
        raise ValueError("--timeout-s must be > 0")
    if args.system_sample_interval_s < 0:
        raise ValueError("--system-sample-interval-s must be >= 0")
    if args.max_tokens is not None and (
        isinstance(args.max_tokens, bool)
        or not isinstance(args.max_tokens, int)
        or args.max_tokens <= 0
    ):
        raise ValueError("--max-tokens must be a positive integer")
    if not is_local_lmstudio_base_url(args.base_url):
        raise ValueError("--base-url must stay on localhost for probe-concurrency")
    if args.kind not in {
        "plain_text_pair",
        "plain_text_artifacts",
        "plain_text_artifacts_normalized",
        "structured_small_pair",
        "medium_pair",
    }:
        raise ValueError(
            "--kind must be one of plain_text_pair, plain_text_artifacts, "
            "plain_text_artifacts_normalized, structured_small_pair, medium_pair"
        )
    if args.app_concurrency < 1 or args.app_concurrency > 2:
        raise ValueError("--app-concurrency must be between 1 and 2")
    if args.kind == "medium_pair" and args.verified_context_length is None:
        raise ValueError("--verified-context-length is required for --kind medium_pair")
    if args.loaded_parallel is not None and (
        isinstance(args.loaded_parallel, bool)
        or not isinstance(args.loaded_parallel, int)
        or args.loaded_parallel <= 0
    ):
        raise ValueError("--loaded-parallel must be a positive integer")
    if args.app_concurrency > 1 and args.loaded_parallel is None and not args.allow_queue_pressure:
        raise ValueError(
            "--app-concurrency > 1 requires --loaded-parallel or explicit queue pressure "
            "opt-in via --allow-queue-pressure"
        )
    if (
        args.loaded_parallel is not None
        and args.app_concurrency > args.loaded_parallel
        and not args.allow_queue_pressure
    ):
        raise ValueError(
            "--app-concurrency exceeds loaded parallel; use --allow-queue-pressure only "
            "for intentional queue pressure"
        )

    model_key = args.model_key or _derive_safe_model_key(args.model_id)
    run_id = _validate_probe_run_id(
        args.run_id or _default_concurrency_probe_run_id(args.kind),
        command_name="probe-concurrency",
    )
    run_dir = _prepare_run_dir(
        output_root=args.output_root,
        run_id=run_id,
        experiment_id="concurrency_diagnostics",
    )
    environment_payload = _build_concurrency_probe_environment_payload(
        run_id=run_id,
        diagnostic_kind=args.kind,
        model_id=args.model_id,
        model_key=model_key,
        app_concurrency=args.app_concurrency,
        loaded_parallel=args.loaded_parallel,
        allow_queue_pressure=bool(args.allow_queue_pressure),
        timeout_s=args.timeout_s,
        max_tokens_override=args.max_tokens,
        verified_context_length=args.verified_context_length,
        context_fit_safety_ratio=args.context_fit_safety_ratio,
    )
    environment_payload["system_sample_interval_s"] = args.system_sample_interval_s
    system_sampler = SystemMetricsSampler(sample_interval_s=args.system_sample_interval_s)
    system_summary = None
    system_sampler.start(providers=_build_system_providers(command_name="probe_concurrency"))
    try:
        outcome = run_live_concurrency_diagnostics(
            base_url=args.base_url,
            model_id=args.model_id,
            model_key=model_key,
            run_id=run_id,
            diagnostic_kind=args.kind,
            app_concurrency=args.app_concurrency,
            loaded_parallel=args.loaded_parallel,
            allow_queue_pressure=bool(args.allow_queue_pressure),
            timeout_s=args.timeout_s,
            verified_context_length=args.verified_context_length,
            context_fit_safety_ratio=args.context_fit_safety_ratio,
            max_tokens_override=args.max_tokens,
        )
    finally:
        system_summary = system_sampler.stop(
            providers=_build_system_providers(command_name="probe_concurrency")
        )

    write_json_file(run_dir / "environment.json", environment_payload)
    metrics_path = run_dir / "metrics.jsonl"
    metrics_path.write_text("", encoding="utf-8")
    for metric in outcome.metrics:
        append_jsonl_record(metrics_path, metric)

    structured_errors_path = run_dir / "structured_errors.jsonl"
    structured_errors_path.write_text("", encoding="utf-8")
    for structured_error in outcome.structured_errors:
        append_jsonl_record(structured_errors_path, structured_error)

    if system_summary is not None:
        write_system_telemetry_artifacts(
            run_dir,
            samples=system_sampler.samples,
            summary=system_summary,
        )
    write_json_file(run_dir / "summary.json", outcome.summary)
    (run_dir / "report.md").write_text(
        render_concurrency_diagnostics_report(
            environment=environment_payload,
            summary=outcome.summary,
            output_files=CONCURRENCY_DIAGNOSTICS_RESULT_FILE_NAMES,
        ),
        encoding="utf-8",
    )
    return EXIT_OK if outcome.summary.get("all_requests_pass") else EXIT_PROBE_ERROR


def main(argv: list[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    args = _parse_args(argv_list)
    if args.command == "plan-cache":
        return _run_plan_cache(args)
    if args.command == "plan-matrix":
        return _run_plan_matrix(args)
    if args.command == "run-matrix":
        return _run_matrix_fake(args)
    if args.command == "run":
        if args.managed_l3_8b_gemma4_e4b_load_only:
            return _run_managed_l3_8b_gemma4_e4b_load_only(args)
        if args.managed_l3_9c_gemma4_12b_qat_load_only:
            return _run_managed_l3_9c_gemma4_12b_qat_load_only(args)
        if args.managed_l3_9d_gemma4_26b_a4b_load_only:
            return _run_managed_l3_9d_gemma4_26b_a4b_load_only(args)
        if args.managed_l3_8c_gemma4_e4b_tiny_live_smoke:
            return _run_managed_l3_8c_gemma4_e4b_tiny_live_smoke(args)
        if args.managed_l3_8d_gemma4_e4b_strict_json_smoke:
            return _run_managed_l3_8d_gemma4_e4b_strict_json_smoke(args)
        if args.managed_l3_6_25k_preflight:
            return _run_managed_l3_6_25k_preflight(args)
        if args.managed_responses_cache_probe:
            return _run_managed_responses_cache_probe(args)
        if args.managed_cache_32k_load_only:
            return _run_managed_cache_32k_load_only(args)
        if args.managed_l3_6c_compact_memory_live_smoke:
            return _run_managed_l3_6c_compact_memory_live_smoke(args)
        if args.managed_l3_6d_mode_comparison_live:
            return _run_managed_l3_6d_mode_comparison_live(args)
        if args.managed_l3_7d_structured_json_live_smoke:
            return _run_managed_l3_7d_structured_json_live_smoke(args)
        if args.managed_cache_25k_prep:
            return _run_managed_cache_25k_prep(args)
        if args.managed_cache_instrument_live:
            return _run_managed_cache_instrument_live(args)
        if args.managed_cache_compare_live:
            return _run_managed_cache_compare_live(args)
        if args.managed_cache_live_smoke:
            return _run_managed_cache_live_smoke(args)
        if args.managed_live_true_parallel:
            return _run_managed_live_true_parallel(args)
        if args.managed_live:
            return _run_managed_live(args)
        if args.live:
            return _run_live_smoke(args)
        return _run_dry_run(args)
    if args.command == "probe-models":
        return _run_model_probe(args)
    if args.command == "resolve-candidates":
        return _run_candidate_resolution(args)
    if args.command == "acquire-candidate":
        return _run_model_acquisition(args)
    if args.command == "probe-identity":
        return _run_identity_probe(args)
    if args.command == "probe-load":
        return _run_load_probe(args)
    if args.command == "probe-lifecycle":
        return _run_probe_lifecycle(args)
    if args.command == "probe-concurrency":
        return _run_probe_concurrency(args)
    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
