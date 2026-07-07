from __future__ import annotations

import platform
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .metrics import SCHEMA_VERSION, append_jsonl_record
from .privacy import find_privacy_violations
from .report import write_json_file

CACHE_PLAN_RESULT_FILE_NAMES = (
    "environment.json",
    "experiment.yaml",
    "cache_plan.json",
    "planned_requests.jsonl",
    "metrics_schema.json",
    "report.md",
)
CACHE_PLAN_MEASUREMENT_SOURCE = "future_live_gate"
CACHE_PLAN_MEASUREMENT_STATUS = "not_measured_no_live"
CACHE_PLAN_ALLOWED_MODEL_IDS = {
    "gemma4_e2b_q4km": "google/gemma-4-e2b",
    "gemma4_e4b_q4km": "google/gemma-4-e4b",
}
CACHE_PLAN_ALLOWED_CONTEXT_WINDOWS = (8192, 16384)
CACHE_PLAN_REQUIRED_BRANCHES = (
    "summary",
    "glossary",
    "timeline",
)
CACHE_PLAN_REQUIRED_VARIANTS = (
    "stateful_root_branch",
    "stateless_full_prefix",
    "compact_memory",
)
CACHE_PLAN_REQUIRED_METRICS = (
    "ttft_ms",
    "prompt_processing_ms",
    "total_latency_ms",
    "cached_tokens",
    "cache_proxy",
    "ram_peak_mb",
    "vram_peak_mb",
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _require_mapping(payload: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{context} must be a mapping")
    return payload


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


def _require_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return value


def _require_allowed_context_window(value: Any, *, field_name: str) -> int:
    context_window = _require_positive_int(value, field_name=field_name)
    if context_window not in CACHE_PLAN_ALLOWED_CONTEXT_WINDOWS:
        allowed_values = ", ".join(str(item) for item in CACHE_PLAN_ALLOWED_CONTEXT_WINDOWS)
        raise ValueError(f"{field_name} must be one of: {allowed_values}")
    return context_window


def _require_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _require_safe_id(value: Any, *, field_name: str) -> str:
    text = _require_non_empty_string(value, field_name=field_name)
    if _SAFE_ID_RE.fullmatch(text) is None:
        raise ValueError(f"{field_name} must use a safe identifier")
    return text


def _require_unique_safe_id_sequence(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field_name} must be a list of safe identifiers")

    items = tuple(_require_safe_id(item, field_name=f"{field_name}[]") for item in value)
    if not items:
        raise ValueError(f"{field_name} must not be empty")
    if len(set(items)) != len(items):
        raise ValueError(f"{field_name} must not contain duplicates")
    return items


def _require_only_known_keys(
    payload: Mapping[str, Any],
    *,
    field_name: str,
    allowed_keys: Iterable[str],
) -> None:
    unknown_keys = sorted(set(payload) - set(allowed_keys))
    if unknown_keys:
        raise ValueError(f"{field_name} contains unsupported keys: {', '.join(unknown_keys)}")


def _require_all_members(
    values: Sequence[str],
    *,
    field_name: str,
    required_members: Sequence[str],
) -> None:
    missing_members = [member for member in required_members if member not in values]
    if missing_members:
        raise ValueError(f"{field_name} must include: {', '.join(missing_members)}")


def default_cache_plan_run_id(experiment_id: str) -> str:
    return f"{experiment_id}_cache_plan"


def _validate_cache_plan_run_id(run_id: str) -> str:
    candidate = run_id.strip()
    if candidate != run_id or not candidate:
        raise ValueError("plan-cache run_id must use a safe local identifier")
    if len(candidate) > 120:
        raise ValueError("plan-cache run_id must use a safe local identifier")
    if "://" in candidate or "/" in candidate or "\\" in candidate:
        raise ValueError("plan-cache run_id must use a safe local identifier")
    if len(candidate) >= 2 and candidate[1] == ":" and candidate[0].isalpha():
        raise ValueError("plan-cache run_id must use a safe local identifier")
    if _SAFE_RUN_ID_RE.fullmatch(candidate) is None:
        raise ValueError("plan-cache run_id must use a safe local identifier")
    return candidate


def _prepare_run_dir(*, output_root: Path, run_id: str, experiment_id: str) -> Path:
    run_dir = output_root / f"run_{run_id}_{experiment_id}"
    if run_dir.exists():
        raise FileExistsError(
            f"run output already exists for run_id {run_id!r} and experiment_id {experiment_id!r}"
        )
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _write_exact_bytes_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@dataclass(slots=True, frozen=True)
class CachePlanPrivacy:
    store_root_material: bool = False
    store_branch_material: bool = False
    store_output_material: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> CachePlanPrivacy:
        if payload is None:
            return cls()

        raw_payload = _require_mapping(payload, context="privacy")
        _require_only_known_keys(
            raw_payload,
            field_name="privacy",
            allowed_keys=(
                "store_root_material",
                "store_branch_material",
                "store_output_material",
            ),
        )
        return cls(
            store_root_material=_require_bool(
                raw_payload.get("store_root_material", False),
                field_name="privacy.store_root_material",
            ),
            store_branch_material=_require_bool(
                raw_payload.get("store_branch_material", False),
                field_name="privacy.store_branch_material",
            ),
            store_output_material=_require_bool(
                raw_payload.get("store_output_material", False),
                field_name="privacy.store_output_material",
            ),
        )

    def raw_material_storage_enabled(self) -> bool:
        return any(
            (
                self.store_root_material,
                self.store_branch_material,
                self.store_output_material,
            )
        )

    def to_dict(self) -> dict[str, bool]:
        return {
            "store_root_material": self.store_root_material,
            "store_branch_material": self.store_branch_material,
            "store_output_material": self.store_output_material,
        }


@dataclass(slots=True, frozen=True)
class RootContextSummary:
    estimated_tokens: int
    estimated_chars: int
    root_context_hash: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> RootContextSummary:
        raw_payload = _require_mapping(payload, context="root_context")
        _require_only_known_keys(
            raw_payload,
            field_name="root_context",
            allowed_keys=("estimated_tokens", "estimated_chars", "content_hash"),
        )
        return cls(
            estimated_tokens=_require_positive_int(
                raw_payload.get("estimated_tokens"),
                field_name="root_context.estimated_tokens",
            ),
            estimated_chars=_require_positive_int(
                raw_payload.get("estimated_chars"),
                field_name="root_context.estimated_chars",
            ),
            root_context_hash=_require_non_empty_string(
                raw_payload.get("content_hash"),
                field_name="root_context.content_hash",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimated_tokens": self.estimated_tokens,
            "estimated_chars": self.estimated_chars,
            "root_context_hash": self.root_context_hash,
        }


@dataclass(slots=True, frozen=True)
class CachePlanConfig:
    experiment_id: str
    model_key: str
    model_id: str | None
    context_window: int
    synthetic_dataset: str
    root_context: RootContextSummary
    branches: tuple[str, ...]
    variants: tuple[str, ...]
    metric_fields: tuple[str, ...]
    privacy: CachePlanPrivacy = field(default_factory=CachePlanPrivacy)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> CachePlanConfig:
        raw_payload = _require_mapping(payload, context="cache plan config")
        _require_only_known_keys(
            raw_payload,
            field_name="cache plan config",
            allowed_keys=(
                "experiment_id",
                "model_key",
                "model_id",
                "context_window",
                "synthetic_dataset",
                "root_context",
                "branches",
                "variants",
                "metrics",
                "privacy",
            ),
        )

        model_key = _require_safe_id(
            raw_payload.get("model_key"),
            field_name="model_key",
        )
        if model_key not in CACHE_PLAN_ALLOWED_MODEL_IDS:
            allowed_keys = ", ".join(CACHE_PLAN_ALLOWED_MODEL_IDS)
            raise ValueError(f"model_key must be one of: {allowed_keys}")

        model_id = raw_payload.get("model_id")
        if model_id is not None:
            model_id = _require_non_empty_string(model_id, field_name="model_id")
            expected_model_id = CACHE_PLAN_ALLOWED_MODEL_IDS[model_key]
            if model_id != expected_model_id:
                raise ValueError(
                    f"model_id must match the known id for {model_key}: {expected_model_id}"
                )

        branches = _require_unique_safe_id_sequence(
            raw_payload.get("branches"),
            field_name="branches",
        )
        _require_all_members(
            branches,
            field_name="branches",
            required_members=CACHE_PLAN_REQUIRED_BRANCHES,
        )

        variants = _require_unique_safe_id_sequence(
            raw_payload.get("variants"),
            field_name="variants",
        )
        _require_all_members(
            variants,
            field_name="variants",
            required_members=CACHE_PLAN_REQUIRED_VARIANTS,
        )

        metric_fields = _require_unique_safe_id_sequence(
            raw_payload.get("metrics"),
            field_name="metrics",
        )
        _require_all_members(
            metric_fields,
            field_name="metrics",
            required_members=CACHE_PLAN_REQUIRED_METRICS,
        )

        return cls(
            experiment_id=_require_safe_id(
                raw_payload.get("experiment_id"),
                field_name="experiment_id",
            ),
            model_key=model_key,
            model_id=model_id,
            context_window=_require_allowed_context_window(
                raw_payload.get("context_window"),
                field_name="context_window",
            ),
            synthetic_dataset=_require_safe_id(
                raw_payload.get("synthetic_dataset"),
                field_name="synthetic_dataset",
            ),
            root_context=RootContextSummary.from_mapping(raw_payload.get("root_context")),
            branches=branches,
            variants=variants,
            metric_fields=metric_fields,
            privacy=CachePlanPrivacy.from_mapping(raw_payload.get("privacy")),
        )


def load_raw_cache_plan_config(path: str | Path) -> tuple[bytes, Mapping[str, Any]]:
    config_path = Path(path)
    config_bytes = config_path.read_bytes()
    payload = yaml.safe_load(config_bytes.decode("utf-8"))
    return config_bytes, _require_mapping(payload, context="cache plan config")


def validate_cache_plan_payload(payload: Mapping[str, Any]) -> None:
    violations = find_privacy_violations(payload, context="cache plan config")
    if violations:
        raise ValueError(f"unsafe cache plan config: {violations[0]}")


def load_cache_plan_config(path: str | Path) -> CachePlanConfig:
    _, raw_payload = load_raw_cache_plan_config(path)
    validate_cache_plan_payload(raw_payload)
    return CachePlanConfig.from_mapping(raw_payload)


def _build_environment_payload(*, experiment_id: str, run_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dry_run": True,
        "network": False,
        "lmstudio_api_called": False,
        "measurement_status": CACHE_PLAN_MEASUREMENT_STATUS,
        "production_default": False,
        "wvm_runtime_forbidden": True,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
        "python_version": platform.python_version(),
    }


def _build_cache_plan_payload(config: CachePlanConfig, *, run_id: str) -> dict[str, Any]:
    planned_request_count = 1 + (len(config.branches) * len(config.variants))
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": config.experiment_id,
        "run_id": run_id,
        "model_key": config.model_key,
        "model_id": config.model_id,
        "context_window": config.context_window,
        "synthetic_dataset": config.synthetic_dataset,
        "root_estimated_tokens": config.root_context.estimated_tokens,
        "root_estimated_chars": config.root_context.estimated_chars,
        "root_context_hash": config.root_context.root_context_hash,
        "branches": list(config.branches),
        "variants": list(config.variants),
        "metric_fields": list(config.metric_fields),
        "planned_request_count": planned_request_count,
        "kv_reuse_proven": False,
        "measurement_status": CACHE_PLAN_MEASUREMENT_STATUS,
        "measurement_source": CACHE_PLAN_MEASUREMENT_SOURCE,
        "production_default": False,
        "raw_material_storage_enabled": config.privacy.raw_material_storage_enabled(),
    }


def _iter_planned_requests(
    config: CachePlanConfig,
    *,
    run_id: str,
) -> Iterable[dict[str, Any]]:
    root_request_id = "root_context_plan"
    base_row = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": config.experiment_id,
        "run_id": run_id,
        "model_key": config.model_key,
        "model_id": config.model_id,
        "context_window": config.context_window,
        "synthetic_dataset": config.synthetic_dataset,
        "root_context_hash": config.root_context.root_context_hash,
        "root_estimated_tokens": config.root_context.estimated_tokens,
        "root_estimated_chars": config.root_context.estimated_chars,
        "metric_fields": list(config.metric_fields),
        "measurement_status": CACHE_PLAN_MEASUREMENT_STATUS,
        "measurement_source": CACHE_PLAN_MEASUREMENT_SOURCE,
        "kv_reuse_proven": False,
        "production_default": False,
    }
    yield {
        **base_row,
        "request_id": root_request_id,
        "request_kind": "root_context",
        "branch_ids": list(config.branches),
        "variant_ids": list(config.variants),
    }
    for branch_id in config.branches:
        for variant_id in config.variants:
            yield {
                **base_row,
                "request_id": f"branch_{branch_id}_{variant_id}",
                "request_kind": "branch",
                "root_request_id": root_request_id,
                "branch_id": branch_id,
                "variant_id": variant_id,
            }


def _build_metrics_schema_payload(config: CachePlanConfig, *, run_id: str) -> dict[str, Any]:
    metrics = [
        {
            "metric_id": metric_field,
            "planned_value": None,
            "measurement_source": CACHE_PLAN_MEASUREMENT_SOURCE,
            "measurement_status": CACHE_PLAN_MEASUREMENT_STATUS,
            "kv_reuse_proven": False,
        }
        for metric_field in config.metric_fields
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": config.experiment_id,
        "run_id": run_id,
        "metric_fields": list(config.metric_fields),
        "measurement_source": CACHE_PLAN_MEASUREMENT_SOURCE,
        "measurement_status": CACHE_PLAN_MEASUREMENT_STATUS,
        "kv_reuse_proven": False,
        "production_default": False,
        "metrics": metrics,
    }


def render_cache_plan_report(
    *,
    config: CachePlanConfig,
    run_id: str,
    output_files: Sequence[str] = CACHE_PLAN_RESULT_FILE_NAMES,
) -> str:
    output_lines = "\n".join(f"- `{file_name}`" for file_name in output_files)
    return "\n".join(
        [
            "# LM Studio Lab Cache Plan",
            "",
            "## Run",
            "",
            f"- experiment_id: `{config.experiment_id}`",
            f"- run_id: `{run_id}`",
            "- Mode: no-live cache/stateful/prefix preparation",
            "- Network: disabled",
            "- LM Studio API: not called",
            "- WVM runtime: forbidden",
            f"- measurement_status: `{CACHE_PLAN_MEASUREMENT_STATUS}`",
            "- kv_reuse_proven: `false`",
            "- production_default: `false`",
            "",
            "## Plan",
            "",
            f"- model_key: `{config.model_key}`",
            f"- model_id: `{config.model_id or 'null'}`",
            f"- context_window: `{config.context_window}`",
            f"- synthetic_dataset: `{config.synthetic_dataset}`",
            f"- root hash: `{config.root_context.root_context_hash}`",
            f"- root estimated tokens: `{config.root_context.estimated_tokens}`",
            f"- root estimated chars: `{config.root_context.estimated_chars}`",
            f"- branches: `{', '.join(config.branches)}`",
            f"- variants: `{', '.join(config.variants)}`",
            f"- metric fields: `{', '.join(config.metric_fields)}`",
            f"- planned rows: `{1 + (len(config.branches) * len(config.variants))}`",
            "",
            "## Safety",
            "",
            (
                "- raw material storage enabled: "
                f"`{str(config.privacy.raw_material_storage_enabled()).lower()}`"
            ),
            "- stored values are limited to hashes, counts, ids, and planned metric names",
            "- this artifact is a future live-gate preparation only",
            "- stateful API contract is not proof of physical KV reuse",
            "- large-root savings remain unmeasured in no-live mode",
            "",
            "## Notes",
            "",
            "- Qwen structured recovery stays out of scope for this slice.",
            "- No network, GPU execution, live LM Studio, or WVM runtime work occurred.",
            "- Output files:",
            output_lines,
            "",
        ]
    )


def create_cache_plan_artifacts(
    config_path: str | Path,
    *,
    output_root: Path,
    run_id: str | None = None,
) -> Path:
    config_bytes, raw_payload = load_raw_cache_plan_config(config_path)
    validate_cache_plan_payload(raw_payload)
    config = CachePlanConfig.from_mapping(raw_payload)
    final_run_id = _validate_cache_plan_run_id(
        run_id or default_cache_plan_run_id(config.experiment_id)
    )

    run_dir = _prepare_run_dir(
        output_root=output_root,
        run_id=final_run_id,
        experiment_id=config.experiment_id,
    )
    _write_exact_bytes_file(run_dir / "experiment.yaml", config_bytes)
    write_json_file(
        run_dir / "environment.json",
        _build_environment_payload(
            experiment_id=config.experiment_id,
            run_id=final_run_id,
        ),
    )
    write_json_file(
        run_dir / "cache_plan.json",
        _build_cache_plan_payload(config, run_id=final_run_id),
    )

    planned_requests_path = run_dir / "planned_requests.jsonl"
    planned_requests_path.write_text("", encoding="utf-8")
    for row in _iter_planned_requests(config, run_id=final_run_id):
        append_jsonl_record(planned_requests_path, row)

    write_json_file(
        run_dir / "metrics_schema.json",
        _build_metrics_schema_payload(config, run_id=final_run_id),
    )
    (run_dir / "report.md").write_text(
        render_cache_plan_report(config=config, run_id=final_run_id),
        encoding="utf-8",
    )
    return run_dir


__all__ = [
    "CACHE_PLAN_ALLOWED_MODEL_IDS",
    "CACHE_PLAN_MEASUREMENT_SOURCE",
    "CACHE_PLAN_MEASUREMENT_STATUS",
    "CACHE_PLAN_REQUIRED_BRANCHES",
    "CACHE_PLAN_REQUIRED_METRICS",
    "CACHE_PLAN_REQUIRED_VARIANTS",
    "CACHE_PLAN_RESULT_FILE_NAMES",
    "CachePlanConfig",
    "CachePlanPrivacy",
    "RootContextSummary",
    "create_cache_plan_artifacts",
    "default_cache_plan_run_id",
    "load_cache_plan_config",
    "load_raw_cache_plan_config",
    "render_cache_plan_report",
    "validate_cache_plan_payload",
]
