from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from .artifacts import ArtifactSet, write_run_artifacts
from .live_bridge import (
    LAB_ONLY_LIVE_FLAGS,
    LiveBridgeError,
    LiveBridgeOptions,
    ManagedLiveBridge,
    safe_live_metadata,
    validate_live_guardrails,
)
from .requests import (
    ChatMessage,
    ExecutionOptions,
    ImageInput,
    RequestEnvelope,
    RequestPlan,
    RequestResult,
    ResponseContract,
    TextInput,
    stable_hash,
)
from .schema_builders import build_blocks_schema
from .validation import validate_response

DEFAULT_AXES = {
    "modality": ["text"],
    "language": ["en_en"],
    "structure_complexity": ["simple"],
    "volume": ["single"],
    "context_tier": ["8192"],
    "schema_variant": ["baseline_loose"],
    "retry_policy": ["off"],
}


@dataclass(frozen=True, slots=True)
class ModelSpec:
    model_key: str
    model_id: str
    endpoint_family: str = "openai_compat"
    supported_modalities: tuple[str, ...] = ("text",)
    supported_context_tiers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    family: str
    modality: str = "text"
    language: str = "en_en"
    structure_complexity: str = "simple"
    volume: str = "single"
    prompt: str = ""
    image_hash: str | None = None
    schema: dict[str, Any] | None = None
    schema_family: str | None = None
    schema_variant: str | None = None
    tags: tuple[str, ...] = ()
    expected_output: Any | None = None
    expected_ids: tuple[Any, ...] = ()
    image_ground_truth: dict[str, Any] | None = None
    fake_mode: str = "valid"
    min_length_ratio: float | None = None
    max_length_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkSafetyConfig:
    live: bool = False
    allow_model_downloads: bool = False
    allow_model_loads: bool = False
    allow_remote_base_url: bool = False
    allow_raw_prompt_response_artifacts: bool = False
    max_requests: int = 100
    max_models: int = 5
    max_context_tier: int = 8192
    max_repeats: int = 3
    max_runtime_minutes: int | None = None
    allow_image_live: bool = False
    allow_stress: bool = False


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    run_id: str
    models: tuple[ModelSpec, ...]
    tasks: tuple[TaskSpec, ...]
    axes: dict[str, tuple[str, ...]]
    repeats: int = 1
    safety: BenchmarkSafetyConfig = field(default_factory=BenchmarkSafetyConfig)

    @classmethod
    def from_file(cls, path: str | Path) -> BenchmarkConfig:
        source = Path(path)
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Benchmark config must be a mapping")
        return cls.from_dict(payload, default_run_id=source.stem)

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any], default_run_id: str = "labkit-run"
    ) -> BenchmarkConfig:
        models = tuple(_model_from_dict(item) for item in payload.get("models", []))
        if not models:
            raise ValueError("Benchmark config requires at least one model")
        tasks = tuple(_task_from_dict(item) for item in payload.get("tasks", []))
        if not tasks:
            raise ValueError("Benchmark config requires at least one task")
        axes_payload = dict(DEFAULT_AXES)
        axes_payload.update(payload.get("axes", {}))
        axes = {
            key: tuple(_normalize_axis_value(item) for item in value)
            for key, value in axes_payload.items()
        }
        repeats = int(payload.get("repeats", 1))
        if repeats <= 0:
            raise ValueError("repeats must be positive")
        return cls(
            run_id=str(payload.get("run_id") or default_run_id),
            models=models,
            tasks=tasks,
            axes=axes,
            repeats=repeats,
            safety=_safety_from_dict(payload.get("safety", {})),
        )

    def safe_hash(self) -> str:
        return stable_hash(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "models": [asdict(model) for model in self.models],
                    "tasks": [task.task_id for task in self.tasks],
                    "axes": self.axes,
                    "repeats": self.repeats,
                    "safety": asdict(self.safety),
                },
                sort_keys=True,
                default=list,
            )
        )


@dataclass(frozen=True, slots=True)
class MatrixCell:
    cell_id: str
    model: ModelSpec
    task: TaskSpec
    axes: dict[str, str]
    repeat_index: int

    def to_request_plan(self) -> RequestPlan:
        modality = self.axes.get("modality", self.task.modality)
        schema = self.task.schema
        schema_variant = self.axes.get("schema_variant") or self.task.schema_variant
        if schema is None and self.task.schema_family == "blocks":
            schema = build_blocks_schema(self.task.expected_ids, schema_variant or "baseline_loose")
        contract = ResponseContract(
            mode="json" if schema is not None else "text",
            schema=schema,
            expected_ids=self.task.expected_ids,
            language=self.axes.get("language"),
            expected_output=self.task.expected_output,
            image_ground_truth=self.task.image_ground_truth,
            min_length_ratio=self.task.min_length_ratio,
            max_length_ratio=self.task.max_length_ratio,
        )
        text_inputs = (TextInput(self.task.prompt),) if self.task.prompt else ()
        image_inputs = (
            (ImageInput(content_hash=self.task.image_hash),) if self.task.image_hash else ()
        )
        envelope = RequestEnvelope(
            request_id=self.cell_id,
            modality="image" if modality == "image" else "text",
            text_inputs=text_inputs,
            image_inputs=image_inputs,
            chat_messages=(ChatMessage(role="user", content=self.task.prompt),)
            if self.task.prompt
            else (),
            response_contract=contract,
            metadata={
                "task_id": self.task.task_id,
                "task_family": self.task.family,
                "fake_mode": self.task.fake_mode,
            },
        )
        options = ExecutionOptions(
            model_id=self.model.model_id,
            endpoint_family=self.model.endpoint_family,
            context_tier=self.axes.get("context_tier", "8192"),
            retry_policy="retry1" if self.axes.get("retry_policy") == "retry1" else "off",
            live=False,
        )
        return RequestPlan(cell_id=self.cell_id, envelope=envelope, options=options)


@dataclass(frozen=True, slots=True)
class MatrixPlan:
    run_id: str
    config_hash: str
    cells: tuple[MatrixCell, ...]
    axes: dict[str, tuple[str, ...]]
    repeats: int
    raw_cartesian_cell_count: int
    skip_reasons: dict[str, int]
    safety_budget: dict[str, Any]

    def planner_summary(self, *, live: bool = False) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config_hash": self.config_hash,
            "axes": {key: list(value) for key, value in self.axes.items()},
            "cell_count": len(self.cells),
            "raw_cartesian_cell_count": self.raw_cartesian_cell_count,
            "filtered_cell_count": len(self.cells),
            "skipped_cell_count": self.raw_cartesian_cell_count - len(self.cells),
            "skip_reasons": dict(sorted(self.skip_reasons.items())),
            "repeats": self.repeats,
            "live": live,
            "privacy_mode": "safe-default",
            "safety_budget": dict(sorted(self.safety_budget.items())),
            "schema_version": "structured-matrix-v1",
        }


def plan_matrix(config: BenchmarkConfig) -> MatrixPlan:
    _validate_static_safety(config)
    return _build_matrix_plan(config)


def _build_matrix_plan(config: BenchmarkConfig) -> MatrixPlan:
    cells: list[MatrixCell] = []
    raw_cartesian_cell_count = 0
    skip_reasons: dict[str, int] = {}
    for model in config.models:
        for task in config.tasks:
            for modality in config.axes.get("modality", (task.modality,)):
                for language in config.axes.get("language", ("en_en",)):
                    for complexity in config.axes.get("structure_complexity", ("simple",)):
                        for volume in config.axes.get("volume", ("single",)):
                            for context_tier in config.axes.get("context_tier", ("8192",)):
                                for schema_variant in config.axes.get(
                                    "schema_variant", ("baseline_loose",)
                                ):
                                    for retry_policy in config.axes.get("retry_policy", ("off",)):
                                        for repeat_index in range(config.repeats):
                                            raw_cartesian_cell_count += 1
                                            axes = {
                                                "modality": modality,
                                                "language": language,
                                                "structure_complexity": complexity,
                                                "volume": volume,
                                                "context_tier": context_tier,
                                                "schema_variant": schema_variant,
                                                "retry_policy": retry_policy,
                                            }
                                            skip_reason = _compatibility_skip_reason(
                                                model=model,
                                                task=task,
                                                axes=axes,
                                            )
                                            if skip_reason is not None:
                                                skip_reasons[skip_reason] = (
                                                    skip_reasons.get(skip_reason, 0) + 1
                                                )
                                                continue
                                            cell_id = _cell_id(
                                                config.run_id,
                                                model.model_key,
                                                task.task_id,
                                                axes,
                                                repeat_index,
                                            )
                                            cells.append(
                                                MatrixCell(cell_id, model, task, axes, repeat_index)
                                            )
    plan = MatrixPlan(
        config.run_id,
        config.safe_hash(),
        tuple(cells),
        config.axes,
        config.repeats,
        raw_cartesian_cell_count,
        skip_reasons,
        _safe_safety_budget(config.safety),
    )
    _validate_plan_safety(config, plan)
    return plan


def _compatibility_skip_reason(
    *, model: ModelSpec, task: TaskSpec, axes: dict[str, str]
) -> str | None:
    if _is_experimental(task):
        return None
    modality = axes.get("modality", task.modality)
    if modality not in model.supported_modalities:
        return "unsupported_modality"
    if modality != task.modality:
        return "unsupported_modality"
    if axes.get("language", task.language) != task.language:
        return "language_mismatch"
    if axes.get("structure_complexity", task.structure_complexity) != task.structure_complexity:
        return "complexity_mismatch"
    if axes.get("volume", task.volume) != task.volume:
        return "volume_mismatch"
    context_tier = axes.get("context_tier")
    if model.supported_context_tiers and context_tier not in model.supported_context_tiers:
        return "unsupported_context_tier"
    return None


def _is_experimental(task: TaskSpec) -> bool:
    return "experimental" in {tag.casefold() for tag in task.tags}


class FakeTransport:
    """Deterministic offline transport for tests and default CLI runs."""

    def execute(self, plan: RequestPlan, *, attempt_index: int = 1) -> tuple[str, RequestResult]:
        started = time.monotonic()
        expected = plan.envelope.response_contract.expected_output
        if expected is None:
            expected = {"id": plan.cell_id, "text": "offline fake response"}
        mode = _metadata_mode(plan.envelope.metadata.get("fake_mode"))
        raw_response, finish_reason = self._response_for_mode(mode, expected, attempt_index)
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        result = RequestResult.from_raw_response(
            request_id=plan.envelope.request_id,
            model_id=plan.options.model_id,
            raw_response=raw_response,
            status="error" if mode == "transport_error" else "ok",
            latency_ms=elapsed_ms,
            token_counts={
                "prompt": sum(
                    item.safe_metadata()["char_count"] for item in plan.envelope.text_inputs
                ),
                "completion": len(raw_response),
            },
            error_category="transport_error" if mode == "transport_error" else None,
            finish_reason=finish_reason,
        )
        return raw_response, result

    def _response_for_mode(
        self, mode: str, expected: Any, attempt_index: int
    ) -> tuple[str, str | None]:
        if mode == "retry_recovers" and attempt_index >= 2:
            mode = "valid"
        if mode == "valid":
            return _json_or_text(expected), "stop"
        if mode in {"retry_recovers", "retry_deterministic_fail", "schema_violation"}:
            return _json_or_text(_mutate_expected(expected, "schema_violation")), "stop"
        if mode == "invalid_json":
            return "{invalid json", "stop"
        if mode == "missing_id":
            return _json_or_text(_mutate_expected(expected, "missing_id")), "stop"
        if mode == "duplicate_id":
            return _json_or_text(_mutate_expected(expected, "duplicate_id")), "stop"
        if mode == "reordered_ids":
            return _json_or_text(_mutate_expected(expected, "reordered_ids")), "stop"
        if mode == "wrong_language":
            return _json_or_text(_mutate_text(expected, "English only response")), "stop"
        if mode == "placeholder_text":
            return _json_or_text(_mutate_text(expected, "TODO placeholder")), "stop"
        if mode == "markdown_wrapped_json":
            return "```json\n" + _json_or_text(expected) + "\n```", "stop"
        if mode == "finish_length":
            return _json_or_text(expected)[: max(1, len(_json_or_text(expected)) // 2)], "length"
        if mode == "image_ground_truth_miss":
            return _json_or_text(_mutate_text(expected, "unrelated visual description")), "stop"
        if mode == "transport_error":
            return "", "error"
        raise ValueError(f"Unsupported fake mode: {mode}")


def run_matrix(
    config: BenchmarkConfig, output_root: str | Path, *, live: bool = False
) -> ArtifactSet:
    if live:
        raise ValueError(
            "Benchmark safety requires live=false in the core runner; "
            "Live LM Studio execution is not implemented"
        )
    plan = plan_matrix(config)
    rows: list[dict[str, Any]] = []
    transport = FakeTransport()
    deadline = (
        time.monotonic() + config.safety.max_runtime_minutes * 60
        if config.safety.max_runtime_minutes is not None
        else None
    )
    for cell in plan.cells:
        _raise_if_runtime_budget_exceeded(deadline)
        request_plan = cell.to_request_plan()
        raw_response, result = transport.execute(request_plan, attempt_index=1)
        input_char_count = sum(
            item.safe_metadata()["char_count"] for item in request_plan.envelope.text_inputs
        )
        validation = validate_response(
            raw_response,
            request_plan.envelope.response_contract,
            finish_reason=result.finish_reason,
            input_char_count=input_char_count,
        )
        retry_count = 0
        recovered = False
        if validation.status == "fail" and cell.axes.get("retry_policy") == "retry1":
            retry_count = 1
            raw_response, result = transport.execute(request_plan, attempt_index=2)
            validation = validate_response(
                raw_response,
                request_plan.envelope.response_contract,
                finish_reason=result.finish_reason,
                input_char_count=input_char_count,
            )
            recovered = validation.status == "pass" and result.status == "ok"
        row = {
            "run_id": config.run_id,
            "cell_id": cell.cell_id,
            "repeat_index": cell.repeat_index,
            "model_key": cell.model.model_key,
            "model_id": cell.model.model_id,
            "task_id": cell.task.task_id,
            "axes": cell.axes,
            "request": request_plan.envelope.safe_metadata(),
            "result": result.safe_metadata(),
            "validation": validation.to_dict(),
            "retry_count": retry_count,
            "retry_recovered": recovered,
            "status": "pass" if validation.status == "pass" and result.status == "ok" else "fail",
            "error_category": _first_error_category(validation),
        }
        rows.append(row)
        _raise_if_runtime_budget_exceeded(deadline)
    run_dir = Path(output_root) / config.run_id
    return write_run_artifacts(run_dir, plan.planner_summary(live=False), rows)


def run_live_small_text_screening(
    config: BenchmarkConfig,
    output_root: str | Path,
    *,
    executor: Any,
    options: LiveBridgeOptions | None = None,
) -> ArtifactSet:
    """Run guarded text-only screening through an injected managed executor.

    The public package does not own LM Studio lifecycle work. This seam accepts a
    host-managed executor, validates the run shape, and writes only lab-only,
    privacy-safe artifacts.
    """

    bridge_options = options or LiveBridgeOptions(live=True, profile="live-small")
    _validate_live_screening_safety(config, bridge_options)
    plan = _build_matrix_plan(config)
    validate_live_guardrails(bridge_options, request_count=len(plan.cells))
    bridge = ManagedLiveBridge(executor=executor, options=bridge_options)
    rows: list[dict[str, Any]] = []
    for cell in plan.cells:
        if cell.axes.get("modality", cell.task.modality) != "text" or cell.task.modality != "text":
            raise LiveBridgeError("guarded live screening supports text tasks only")
        request_plan = _with_live_execution(cell.to_request_plan())
        raw_response, result = bridge.execute(request_plan)
        input_char_count = sum(
            item.safe_metadata()["char_count"] for item in request_plan.envelope.text_inputs
        )
        validation = validate_response(
            raw_response,
            request_plan.envelope.response_contract,
            finish_reason=result.finish_reason,
            input_char_count=input_char_count,
        )
        rows.append(
            {
                "run_id": config.run_id,
                "cell_id": cell.cell_id,
                "repeat_index": cell.repeat_index,
                "model_key": cell.model.model_key,
                "model_id": cell.model.model_id,
                "task_id": cell.task.task_id,
                "axes": cell.axes,
                "request": request_plan.envelope.safe_metadata(),
                "result": result.safe_metadata(),
                "validation": validation.to_dict(),
                "retry_count": 0,
                "retry_recovered": False,
                "status": "pass"
                if validation.status == "pass" and result.status == "ok"
                else "fail",
                "error_category": _first_error_category(validation),
                "lab_only_flags": LAB_ONLY_LIVE_FLAGS.as_dict(),
            }
        )
    planner_summary = plan.planner_summary(live=True)
    planner_summary["live_bridge"] = safe_live_metadata(bridge_options)
    planner_summary["lab_only_flags"] = LAB_ONLY_LIVE_FLAGS.as_dict()
    run_dir = Path(output_root) / config.run_id
    return write_run_artifacts(run_dir, planner_summary, rows)


def write_matrix_plan(config: BenchmarkConfig, output_root: str | Path) -> ArtifactSet:
    plan = plan_matrix(config)
    run_dir = Path(output_root) / config.run_id
    return write_run_artifacts(run_dir, plan.planner_summary(live=False), [])


def _model_from_dict(payload: dict[str, Any]) -> ModelSpec:
    return ModelSpec(
        model_key=str(payload["model_key"]),
        model_id=str(payload["model_id"]),
        endpoint_family=str(payload.get("endpoint_family", "openai_compat")),
        supported_modalities=tuple(
            str(item) for item in payload.get("supported_modalities", ["text"])
        ),
        supported_context_tiers=tuple(
            str(item) for item in payload.get("supported_context_tiers", [])
        ),
    )


def _task_from_dict(payload: dict[str, Any]) -> TaskSpec:
    return TaskSpec(
        task_id=str(payload["task_id"]),
        family=str(payload.get("family", "simple_flat")),
        modality=str(payload.get("modality", "text")),
        language=str(payload.get("language", "en_en")),
        structure_complexity=str(payload.get("structure_complexity", "simple")),
        volume=str(payload.get("volume", "single")),
        prompt=str(payload.get("prompt", "")),
        image_hash=payload.get("image_hash"),
        schema=payload.get("schema"),
        schema_family=payload.get("schema_family"),
        schema_variant=payload.get("schema_variant"),
        tags=tuple(str(item) for item in payload.get("tags", [])),
        expected_output=payload.get("expected_output"),
        expected_ids=tuple(payload.get("expected_ids", [])),
        image_ground_truth=payload.get("image_ground_truth"),
        fake_mode=str(payload.get("fake_mode", "valid")),
        min_length_ratio=payload.get("min_length_ratio"),
        max_length_ratio=payload.get("max_length_ratio"),
    )


def _safety_from_dict(payload: Any) -> BenchmarkSafetyConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("safety must be a mapping")
    return BenchmarkSafetyConfig(
        live=_safety_bool(payload, "live", False),
        allow_model_downloads=_safety_bool(payload, "allow_model_downloads", False),
        allow_model_loads=_safety_bool(payload, "allow_model_loads", False),
        allow_remote_base_url=_safety_bool(payload, "allow_remote_base_url", False),
        allow_raw_prompt_response_artifacts=_safety_bool(
            payload, "allow_raw_prompt_response_artifacts", False
        ),
        allow_image_live=_safety_bool(payload, "allow_image_live", False),
        allow_stress=_safety_bool(payload, "allow_stress", False),
        max_requests=_positive_int(payload, "max_requests", 100),
        max_models=_positive_int(payload, "max_models", 5),
        max_context_tier=_positive_int(payload, "max_context_tier", 8192),
        max_repeats=_positive_int(payload, "max_repeats", 3),
        max_runtime_minutes=_optional_positive_int(payload, "max_runtime_minutes", None),
    )


def _safety_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"safety.{key} must be a boolean")
    return value


def _positive_int(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"safety.{key} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"safety.{key} must be a positive integer") from error
    if parsed <= 0:
        raise ValueError(f"safety.{key} must be a positive integer")
    return parsed


def _optional_positive_int(payload: dict[str, Any], key: str, default: int | None) -> int | None:
    if key not in payload:
        return default
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"safety.{key} must be a positive integer or null")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"safety.{key} must be a positive integer or null") from error
    if parsed <= 0:
        raise ValueError(f"safety.{key} must be a positive integer or null")
    return parsed


def _validate_static_safety(config: BenchmarkConfig) -> None:
    safety = config.safety
    if safety.live:
        raise ValueError("Benchmark safety requires live=false in the core runner")
    if safety.allow_model_downloads:
        raise ValueError("model downloads are not allowed by the core runner")
    if safety.allow_model_loads:
        raise ValueError("model loads are not allowed by the core runner")
    if safety.allow_remote_base_url:
        raise ValueError("remote base URLs are not allowed by the core runner")
    if safety.allow_raw_prompt_response_artifacts:
        raise ValueError("raw prompt/response artifacts are not allowed by the core runner")
    if safety.allow_image_live:
        raise ValueError("image live execution is not allowed by the core runner")
    if safety.allow_stress:
        raise ValueError("stress execution is not allowed by the core runner")
    if len(config.models) > safety.max_models:
        raise ValueError("model count exceeds safety.max_models")
    if config.repeats > safety.max_repeats:
        raise ValueError("repeats exceeds safety.max_repeats")
    for context_tier in config.axes.get("context_tier", ("8192",)):
        if _context_tier_int(context_tier) > safety.max_context_tier:
            raise ValueError("context_tier exceeds safety.max_context_tier")


def _safe_safety_budget(safety: BenchmarkSafetyConfig) -> dict[str, Any]:
    return {
        "live": safety.live,
        "allow_model_downloads": safety.allow_model_downloads,
        "allow_model_loads": safety.allow_model_loads,
        "allow_remote_base_url": safety.allow_remote_base_url,
        "allow_raw_prompt_response_artifacts": safety.allow_raw_prompt_response_artifacts,
        "allow_image_live": safety.allow_image_live,
        "allow_stress": safety.allow_stress,
        "max_requests": safety.max_requests,
        "max_models": safety.max_models,
        "max_context_tier": safety.max_context_tier,
        "max_repeats": safety.max_repeats,
        "max_runtime_minutes": safety.max_runtime_minutes,
    }


def _validate_plan_safety(config: BenchmarkConfig, plan: MatrixPlan) -> None:
    if len(plan.cells) > config.safety.max_requests:
        raise ValueError("planned request count exceeds safety.max_requests")


def _validate_live_screening_safety(config: BenchmarkConfig, options: LiveBridgeOptions) -> None:
    safety = config.safety
    if not safety.live:
        raise LiveBridgeError("guarded live screening requires safety.live=true")
    if safety.allow_model_downloads:
        raise LiveBridgeError("guarded live screening does not download models")
    if safety.allow_model_loads:
        raise LiveBridgeError("guarded live screening does not load models")
    if safety.allow_raw_prompt_response_artifacts:
        raise LiveBridgeError("raw prompt/response artifacts are not allowed")
    if safety.allow_image_live:
        raise LiveBridgeError("image live execution is not allowed")
    if safety.allow_stress:
        raise LiveBridgeError("stress execution is not allowed")
    if len(config.models) > safety.max_models:
        raise LiveBridgeError("model count exceeds safety.max_models")
    if config.repeats > safety.max_repeats:
        raise LiveBridgeError("repeats exceeds safety.max_repeats")
    for context_tier in config.axes.get("context_tier", ("8192",)):
        if _context_tier_int(context_tier) > safety.max_context_tier:
            raise LiveBridgeError("context_tier exceeds safety.max_context_tier")
    if options.max_requests > safety.max_requests:
        raise LiveBridgeError("bridge max_requests exceeds safety.max_requests")
    if safety.allow_remote_base_url and not options.allow_remote:
        raise LiveBridgeError("remote base URL requires bridge allow_remote=True")
    if any(task.modality != "text" for task in config.tasks):
        raise LiveBridgeError("guarded live screening supports text tasks only")
    if any(modality != "text" for modality in config.axes.get("modality", ("text",))):
        raise LiveBridgeError("guarded live screening supports text tasks only")


def _with_live_execution(plan: RequestPlan) -> RequestPlan:
    return RequestPlan(
        cell_id=plan.cell_id,
        envelope=plan.envelope,
        options=ExecutionOptions(
            model_id=plan.options.model_id,
            endpoint_family=plan.options.endpoint_family,
            context_tier=plan.options.context_tier,
            temperature=plan.options.temperature,
            timeout_s=plan.options.timeout_s,
            retry_policy=plan.options.retry_policy,
            live=True,
        ),
    )


def _raise_if_runtime_budget_exceeded(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise ValueError("run exceeded safety.max_runtime_minutes")


def _context_tier_int(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError("context_tier must be an integer safety tier") from error


def _normalize_axis_value(value: Any) -> str:
    if value is False:
        return "off"
    if value is True:
        return "on"
    return str(value)


def _metadata_mode(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value", "valid"))
    return str(value or "valid")


def _json_or_text(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        if isinstance(value, dict | list)
        else str(value)
    )


def _mutate_expected(value: Any, mode: str) -> Any:
    import copy

    mutated = copy.deepcopy(value)
    blocks = _find_first_blocks(mutated)
    if blocks is None:
        if mode == "schema_violation" and isinstance(mutated, dict):
            mutated["unexpected"] = True
        return mutated
    if mode == "missing_id" and blocks:
        blocks.pop()
    elif mode == "duplicate_id" and blocks:
        blocks.append(copy.deepcopy(blocks[-1]))
    elif mode == "reordered_ids" and len(blocks) > 1:
        blocks[0], blocks[1] = blocks[1], blocks[0]
    elif mode == "schema_violation" and blocks:
        blocks[0]["unexpected"] = True
    return mutated


def _find_first_blocks(value: Any) -> list[Any] | None:
    if isinstance(value, dict):
        blocks = value.get("blocks")
        if isinstance(blocks, list):
            return blocks
        for child in value.values():
            found = _find_first_blocks(child)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_first_blocks(child)
            if found is not None:
                return found
    return None


def _mutate_text(value: Any, replacement: str) -> Any:
    import copy

    mutated = copy.deepcopy(value)
    if _replace_first_text(mutated, replacement):
        return mutated
    if isinstance(mutated, dict):
        mutated["text"] = replacement
        return mutated
    return replacement


def _replace_first_text(value: Any, replacement: str) -> bool:
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            value["text"] = replacement
            return True
        if isinstance(value.get("normalized_text"), str):
            value["normalized_text"] = replacement
            return True
        for child in value.values():
            if _replace_first_text(child, replacement):
                return True
    elif isinstance(value, list):
        for child in value:
            if _replace_first_text(child, replacement):
                return True
    return False


def _cell_id(
    run_id: str,
    model_key: str,
    task_id: str,
    axes: dict[str, str],
    repeat_index: int,
) -> str:
    digest = sha256(
        json.dumps(
            [run_id, model_key, task_id, axes, repeat_index],
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"cell_{digest}"


def _first_error_category(validation: Any) -> str | None:
    for item in validation.results:
        if item.status == "fail":
            return item.category or item.name
    return None
