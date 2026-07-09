from __future__ import annotations

import itertools
import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

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
    "execution_mode": ["cold_per_request"],
    "cache_mode": ["none"],
    "lmstudio_parallel": ["1"],
    "app_concurrency": ["1"],
    "queue_pressure_mode": ["off"],
    "text_interaction_mode": ["single_question"],
    "image_interaction_mode": ["single_question"],
    "image_type": ["none"],
    "output_language": ["none"],
    "task_intent": ["generic"],
    "input_profile": ["clean"],
    "output_language_policy": ["preserve_input_language"],
    "validation_policy": ["automatic"],
    "prompt_variant": ["baseline"],
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
    language_policy: str | None = None
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
    id_paths: tuple[str, ...] = ()
    id_field_names: tuple[str, ...] = ("id",)
    preserve_order: bool = True
    image_ground_truth: dict[str, Any] | None = None
    fake_mode: str = "valid"
    min_length_ratio: float | None = None
    max_length_ratio: float | None = None
    length_ratio_policy: str | dict[str, Any] = "hard"
    task_intent: str = "generic"
    input_profile: str = "clean"
    output_language_policy: str = "preserve_input_language"
    validation_policy: str = "automatic"
    prompt_variant: str = "baseline"
    response_schema_complexity: str | None = None
    source_text: str | None = None
    source_fixture: str | None = None
    source_fixture_id: str | None = None
    prompt_template: str | None = None
    prompt_template_hash: str | None = None
    fixture_text_hash: str | None = None
    glossary_hash: str | None = None
    language_include_paths: tuple[str, ...] = ()
    language_ignore_paths: tuple[str, ...] = ()
    expected_terms: tuple[dict[str, Any], ...] = ()
    punctuation_policy: str | None = "diagnostic"
    paragraphing_policy: str | None = None
    paragraph_count_min: int | None = None
    paragraph_count_max: int | None = None
    filler_terms: tuple[str, ...] = ()
    filler_cleanup_policy: str | None = None
    term_normalization_policy: str | None = None
    near_identity_policy: str | None = None
    language_drift_policy: str | None = None
    term_language_preservation_policy: str | None = None
    manual_review_policy: str | None = None


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
class StructuredRuntimeConfig:
    strict_json_schema: bool = True


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    run_id: str
    models: tuple[ModelSpec, ...]
    tasks: tuple[TaskSpec, ...]
    axes: dict[str, tuple[str, ...]]
    repeats: int = 1
    safety: BenchmarkSafetyConfig = field(default_factory=BenchmarkSafetyConfig)
    structured_runtime: StructuredRuntimeConfig = field(default_factory=StructuredRuntimeConfig)

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
            structured_runtime=_structured_runtime_from_dict(payload.get("structured_runtime", {})),
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
                    "structured_runtime": asdict(self.structured_runtime),
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
        id_paths = self.task.id_paths
        if not id_paths and self.task.schema_family == "blocks":
            id_paths = ("blocks[*].id",)
        contract = ResponseContract(
            mode="json" if schema is not None else "text",
            schema=schema,
            expected_ids=self.task.expected_ids,
            id_paths=id_paths,
            id_field_names=self.task.id_field_names,
            preserve_order=self.task.preserve_order,
            language=self.axes.get("language"),
            language_policy=self.task.language_policy
            or self.axes.get("output_language_policy")
            or self.task.output_language_policy,
            expected_output=self.task.expected_output,
            image_ground_truth=self.task.image_ground_truth,
            source_text=self.task.source_text,
            min_length_ratio=self.task.min_length_ratio,
            max_length_ratio=self.task.max_length_ratio,
            length_ratio_policy=self.task.length_ratio_policy,
            language_include_paths=self.task.language_include_paths,
            language_ignore_paths=self.task.language_ignore_paths,
            task_intent=self.task.task_intent,
            validation_policy=self.task.validation_policy,
            expected_terms=self.task.expected_terms,
            punctuation_policy=self.task.punctuation_policy,
            paragraphing_policy=self.task.paragraphing_policy,
            paragraph_count_min=self.task.paragraph_count_min,
            paragraph_count_max=self.task.paragraph_count_max,
            filler_terms=self.task.filler_terms,
            filler_cleanup_policy=self.task.filler_cleanup_policy,
            term_normalization_policy=self.task.term_normalization_policy,
            near_identity_policy=self.task.near_identity_policy,
            language_drift_policy=self.task.language_drift_policy,
            term_language_preservation_policy=self.task.term_language_preservation_policy,
            manual_review_policy=self.task.manual_review_policy,
            schema_family=self.task.schema_family,
            response_schema_complexity=self.task.response_schema_complexity,
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
                "cache_mode": self.axes.get("cache_mode", "none"),
                "is_warmup_request": _is_warmup_first_request(self),
                "source_fixture_id": self.task.source_fixture_id,
                "source_fixture_hash": stable_hash(self.task.source_fixture)
                if self.task.source_fixture
                else None,
                "fixture_text_hash": self.task.fixture_text_hash,
                "prompt_template_hash": self.task.prompt_template_hash,
                "glossary_hash": self.task.glossary_hash,
                "manual_review_policy": self.task.manual_review_policy,
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
    structured_runtime: StructuredRuntimeConfig

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
            "structured_runtime": asdict(self.structured_runtime),
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
    axis_specs = (
        ("modality", lambda task: (task.modality,)),
        ("language", lambda task: ("en_en",)),
        ("structure_complexity", lambda task: ("simple",)),
        ("volume", lambda task: ("single",)),
        ("context_tier", lambda task: ("8192",)),
        ("schema_variant", lambda task: ("baseline_loose",)),
        ("retry_policy", lambda task: ("off",)),
        ("execution_mode", lambda task: ("cold_per_request",)),
        ("cache_mode", lambda task: ("none",)),
        ("lmstudio_parallel", lambda task: ("1",)),
        ("app_concurrency", lambda task: ("1",)),
        ("queue_pressure_mode", lambda task: ("off",)),
        ("text_interaction_mode", lambda task: ("single_question",)),
        ("image_interaction_mode", lambda task: ("single_question",)),
        ("image_type", lambda task: ("none",)),
        ("output_language", lambda task: ("none",)),
        ("task_intent", lambda task: (task.task_intent,)),
        ("input_profile", lambda task: (task.input_profile,)),
        ("output_language_policy", lambda task: (task.output_language_policy,)),
        ("validation_policy", lambda task: (task.validation_policy,)),
        ("prompt_variant", lambda task: (task.prompt_variant,)),
        (
            "response_schema_complexity",
            lambda task: (task.response_schema_complexity or task.structure_complexity,),
        ),
        ("execution_target", lambda task: ("local_managed",)),
        ("resource_telemetry_mode", lambda task: ("full",)),
    )
    for model in config.models:
        for task in config.tasks:
            axis_names = tuple(name for name, _default in axis_specs)
            axis_values = tuple(
                config.axes.get(name, default(task)) for name, default in axis_specs
            )
            for axis_tuple in itertools.product(*axis_values, range(config.repeats)):
                *axis_value_items, repeat_index = axis_tuple
                raw_cartesian_cell_count += 1
                axes = dict(zip(axis_names, axis_value_items, strict=True))
                skip_reason = _compatibility_skip_reason(
                    model=model,
                    task=task,
                    axes=axes,
                )
                if skip_reason is not None:
                    skip_reasons[skip_reason] = skip_reasons.get(skip_reason, 0) + 1
                    continue
                cell_id = _cell_id(
                    config.run_id,
                    model.model_key,
                    task.task_id,
                    axes,
                    repeat_index,
                )
                cells.append(
                    MatrixCell(
                        cell_id,
                        model,
                        task,
                        axes,
                        repeat_index,
                    )
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
        config.structured_runtime,
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
    if axes.get("task_intent", task.task_intent) != task.task_intent:
        return "task_intent_mismatch"
    if axes.get("input_profile", task.input_profile) != task.input_profile:
        return "input_profile_mismatch"
    if (
        axes.get("output_language_policy", task.output_language_policy)
        != task.output_language_policy
    ):
        return "output_language_policy_mismatch"
    if axes.get("validation_policy", task.validation_policy) != task.validation_policy:
        return "validation_policy_mismatch"
    if axes.get("prompt_variant", task.prompt_variant) != task.prompt_variant:
        return "prompt_variant_mismatch"
    expected_schema_complexity = task.response_schema_complexity or task.structure_complexity
    if (
        axes.get("response_schema_complexity", expected_schema_complexity)
        != expected_schema_complexity
    ):
        return "response_schema_complexity_mismatch"
    context_tier = axes.get("context_tier")
    if model.supported_context_tiers and context_tier not in model.supported_context_tiers:
        return "unsupported_context_tier"
    return None


def _is_experimental(task: TaskSpec) -> bool:
    return "experimental" in {tag.casefold() for tag in task.tags}


class MatrixTransport(Protocol):
    """Execution seam for matrix cells.

    Implementations return raw response text in memory plus privacy-safe request
    result metadata. The raw text is validated and then discarded by the runner.
    """

    def execute(
        self, plan: RequestPlan, *, attempt_index: int = 1
    ) -> tuple[str, RequestResult]: ...


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
    config: BenchmarkConfig,
    output_root: str | Path,
    *,
    live: bool = False,
    transport: MatrixTransport | None = None,
    live_options: LiveBridgeOptions | None = None,
) -> ArtifactSet:
    live_requested = live_options is not None
    if live and not live_requested:
        raise ValueError(
            "Benchmark safety requires live=false; Live LM Studio execution is not implemented unless live_options and injected transport are provided"
        )
    if live_requested:
        if transport is None:
            raise LiveBridgeError("live transport requires an injected executor or bridge")
        assert live_options is not None
        _validate_live_transport_safety(config, live_options)
        plan = _build_matrix_plan(config)
        _validate_live_warmup_session_support(plan.cells)
        validate_live_guardrails(live_options, request_count=len(plan.cells))
        transport_to_use = transport
    else:
        if config.safety.live:
            raise ValueError(
                "Benchmark safety requires live=false; Live LM Studio execution is not implemented unless live_options and injected transport are provided"
            )
        plan = plan_matrix(config)
        transport_to_use = transport or FakeTransport()

    rows: list[dict[str, Any]] = []
    deadline = (
        time.monotonic() + config.safety.max_runtime_minutes * 60
        if config.safety.max_runtime_minutes is not None
        else None
    )
    for batch in _execution_batches(plan.cells, live_requested=live_requested):
        _raise_if_runtime_budget_exceeded(deadline)
        if live_requested and _is_session_loaded_batch(batch):
            request_plans = tuple(_live_request_plan_for_cell(cell) for cell in batch)
            session_results = _execute_transport_session(transport_to_use, request_plans)
            for cell, request_plan, (raw_response, result) in zip(
                batch, request_plans, session_results, strict=True
            ):
                rows.append(
                    _row_from_execution(
                        config=config,
                        cell=cell,
                        request_plan=request_plan,
                        raw_response=raw_response,
                        result=result,
                        retry_count=0,
                        recovered=False,
                        live_requested=live_requested,
                    )
                )
                _raise_if_runtime_budget_exceeded(deadline)
            continue
        for cell in batch:
            _raise_if_runtime_budget_exceeded(deadline)
            request_plan = cell.to_request_plan()
            if live_requested:
                request_plan = _live_request_plan_for_cell(cell)
            raw_response, result = transport_to_use.execute(request_plan, attempt_index=1)
            input_char_count = sum(
                item.safe_metadata()["char_count"] for item in request_plan.envelope.text_inputs
            )
            validation = validate_response(
                raw_response,
                request_plan.envelope.response_contract,
                finish_reason=result.finish_reason,
                input_char_count=input_char_count,
                input_text=_input_text_for_validation(request_plan),
            )
            retry_count = 0
            recovered = False
            if validation.status == "fail" and cell.axes.get("retry_policy") == "retry1":
                retry_count = 1
                raw_response, result = transport_to_use.execute(request_plan, attempt_index=2)
                validation = validate_response(
                    raw_response,
                    request_plan.envelope.response_contract,
                    finish_reason=result.finish_reason,
                    input_char_count=input_char_count,
                    input_text=_input_text_for_validation(request_plan),
                )
                recovered = validation.status == "pass" and result.status == "ok"
            rows.append(
                _row_from_execution(
                    config=config,
                    cell=cell,
                    request_plan=request_plan,
                    raw_response=raw_response,
                    result=result,
                    retry_count=retry_count,
                    recovered=recovered,
                    live_requested=live_requested,
                    validation=validation,
                )
            )
            _raise_if_runtime_budget_exceeded(deadline)
    run_dir = Path(output_root) / config.run_id
    planner_summary = plan.planner_summary(live=live_requested)
    if live_requested:
        planner_summary["live_bridge"] = safe_live_metadata(live_options)
        planner_summary["lab_only_flags"] = LAB_ONLY_LIVE_FLAGS.as_dict()
    return write_run_artifacts(run_dir, planner_summary, rows)


def _input_text_for_validation(request_plan: RequestPlan) -> str:
    return "\n".join(item.text for item in request_plan.envelope.text_inputs)


def _live_request_plan_for_cell(cell: MatrixCell) -> RequestPlan:
    request_plan = cell.to_request_plan()
    if request_plan.envelope.modality == "image":
        raise NotImplementedError("image live execution is not implemented")
    return _with_live_execution(request_plan)


def _validate_live_warmup_session_support(cells: Sequence[MatrixCell]) -> None:
    for cell in cells:
        if (
            cell.axes.get("cache_mode") == "warmup_first"
            and cell.axes.get("execution_mode") != "session_loaded"
        ):
            raise LiveBridgeError("warmup_first requires execution_mode=session_loaded")


def _execution_batches(
    cells: Sequence[MatrixCell], *, live_requested: bool
) -> tuple[tuple[MatrixCell, ...], ...]:
    batches: list[tuple[MatrixCell, ...]] = []
    index = 0
    while index < len(cells):
        cell = cells[index]
        if not live_requested or cell.axes.get("execution_mode") != "session_loaded":
            batches.append((cell,))
            index += 1
            continue
        if cell.axes.get("retry_policy") != "off":
            raise LiveBridgeError("session_loaded execution does not support retry_policy")
        key = _session_batch_key(cell)
        group = [cell]
        index += 1
        while index < len(cells) and _session_batch_key(cells[index]) == key:
            if cells[index].axes.get("retry_policy") != "off":
                raise LiveBridgeError("session_loaded execution does not support retry_policy")
            group.append(cells[index])
            index += 1
        batches.append(tuple(group))
    return tuple(batches)


def _session_batch_key(cell: MatrixCell) -> tuple[object, ...]:
    session_axes = {key: value for key, value in cell.axes.items() if key not in {"repeat_index"}}
    return (
        cell.model.model_id,
        cell.options.context_tier if hasattr(cell, "options") else cell.axes.get("context_tier"),
        cell.model.endpoint_family,
        session_axes.get("lmstudio_parallel"),
        session_axes.get("execution_target"),
        session_axes.get("schema_variant"),
        cell.task.task_id,
        tuple(sorted(session_axes.items())),
    )


def _is_session_loaded_batch(batch: Sequence[MatrixCell]) -> bool:
    return bool(batch) and batch[0].axes.get("execution_mode") == "session_loaded"


def _execute_transport_session(
    transport: MatrixTransport, request_plans: Sequence[RequestPlan]
) -> tuple[tuple[str, RequestResult], ...]:
    execute_session = getattr(transport, "execute_session", None)
    if not callable(execute_session):
        raise LiveBridgeError("session_loaded execution requires transport.execute_session")
    result = execute_session(tuple(request_plans), attempt_index=1)
    if not isinstance(result, tuple) or len(result) != len(request_plans):
        raise LiveBridgeError("transport.execute_session returned an invalid result set")
    return result


def _row_from_execution(
    *,
    config: BenchmarkConfig,
    cell: MatrixCell,
    request_plan: RequestPlan,
    raw_response: str,
    result: RequestResult,
    retry_count: int,
    recovered: bool,
    live_requested: bool,
    validation: Any | None = None,
) -> dict[str, Any]:
    input_char_count = sum(
        item.safe_metadata()["char_count"] for item in request_plan.envelope.text_inputs
    )
    if validation is None:
        validation = validate_response(
            raw_response,
            request_plan.envelope.response_contract,
            finish_reason=result.finish_reason,
            input_char_count=input_char_count,
            input_text=_input_text_for_validation(request_plan),
        )
    cache_telemetry = _cache_telemetry_fields(cell, request_plan)
    timing_telemetry = _timing_telemetry_fields(result)
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
        "input_char_count": input_char_count,
        "retry_count": retry_count,
        "retry_recovered": recovered,
        "status": "pass" if validation.status == "pass" and result.status == "ok" else "fail",
        "error_category": _first_error_category(validation),
        "warning_category": _first_warning_category(validation),
        "hard_fail": validation.status == "fail" or result.status != "ok",
        "warning_count": _warning_count(validation),
        **_lifecycle_telemetry_fields(result),
        **cache_telemetry,
        **timing_telemetry,
        **_resource_telemetry_fields(cell),
    }
    if live_requested:
        row["lab_only_flags"] = LAB_ONLY_LIVE_FLAGS.as_dict()
    return row


def _lifecycle_telemetry_fields(result: RequestResult) -> dict[str, Any]:
    metadata = result.lifecycle_metadata
    return {
        "session_id": metadata.get("session_id"),
        "session_request_index": metadata.get("session_request_index"),
        "session_request_count": metadata.get("session_request_count"),
        "load_scope": metadata.get("load_scope"),
        "cleanup_scope": metadata.get("cleanup_scope"),
        "loaded_before_session": metadata.get("loaded_before_session"),
        "loaded_after_session_load": metadata.get("loaded_after_session_load"),
        "final_loaded_instances": metadata.get("final_loaded_instances"),
        "session_cleanup_verified": metadata.get("session_cleanup_verified"),
    }


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
            input_text=_input_text_for_validation(request_plan),
        )
        cache_telemetry = _cache_telemetry_fields(cell, request_plan)
        timing_telemetry = _timing_telemetry_fields(result)
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
                "input_char_count": input_char_count,
                "retry_count": 0,
                "retry_recovered": False,
                "status": "pass"
                if validation.status == "pass" and result.status == "ok"
                else "fail",
                "error_category": _first_error_category(validation),
                "warning_category": _first_warning_category(validation),
                "hard_fail": validation.status == "fail" or result.status != "ok",
                "warning_count": _warning_count(validation),
                "lab_only_flags": LAB_ONLY_LIVE_FLAGS.as_dict(),
                **cache_telemetry,
                **timing_telemetry,
                **_resource_telemetry_fields(cell),
            }
        )
    planner_summary = plan.planner_summary(live=True)
    planner_summary["live_bridge"] = safe_live_metadata(bridge_options)
    planner_summary["lab_only_flags"] = LAB_ONLY_LIVE_FLAGS.as_dict()
    run_dir = Path(output_root) / config.run_id
    return write_run_artifacts(run_dir, planner_summary, rows)


def write_matrix_plan(config: BenchmarkConfig, output_root: str | Path) -> ArtifactSet:
    if config.safety.live:
        _validate_live_plan_only_safety(config)
        plan = _build_matrix_plan(config)
    else:
        plan = plan_matrix(config)
    run_dir = Path(output_root) / config.run_id
    return write_run_artifacts(run_dir, plan.planner_summary(live=False), [])


def _validate_live_plan_only_safety(config: BenchmarkConfig) -> None:
    safety = config.safety
    requested_modalities = {
        *(config.axes.get("modality", ())),
        *(task.modality for task in config.tasks),
    }
    requested_volumes = {
        *(config.axes.get("volume", ())),
        *(task.volume for task in config.tasks),
    }
    if safety.allow_model_downloads:
        raise ValueError("model downloads are not supported by live planning")
    if safety.allow_raw_prompt_response_artifacts:
        raise ValueError("raw prompt/response artifacts are not allowed")
    if "image" in requested_modalities or safety.allow_image_live:
        raise ValueError("image live execution is not implemented")
    if "stress" in requested_volumes or safety.allow_stress:
        raise ValueError("stress/overnight live planning requires a separate profile")
    if len(config.models) > safety.max_models:
        raise ValueError("model count exceeds safety.max_models")
    if config.repeats > safety.max_repeats:
        raise ValueError("repeats exceeds safety.max_repeats")
    for context_tier in config.axes.get("context_tier", ("8192",)):
        if _context_tier_int(context_tier) > safety.max_context_tier:
            raise ValueError("context_tier exceeds safety.max_context_tier")


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
    enriched = _enrich_task_payload(payload)
    return TaskSpec(
        task_id=str(enriched["task_id"]),
        family=str(enriched.get("family", "simple_flat")),
        modality=str(enriched.get("modality", "text")),
        language=str(enriched.get("language", "en_en")),
        language_policy=enriched.get("language_policy"),
        structure_complexity=str(enriched.get("structure_complexity", "simple")),
        volume=str(enriched.get("volume", "single")),
        prompt=str(enriched.get("prompt", "")),
        image_hash=enriched.get("image_hash"),
        schema=enriched.get("schema"),
        schema_family=enriched.get("schema_family"),
        schema_variant=enriched.get("schema_variant"),
        tags=tuple(str(item) for item in enriched.get("tags", [])),
        expected_output=enriched.get("expected_output"),
        expected_ids=tuple(enriched.get("expected_ids", [])),
        id_paths=tuple(str(item) for item in enriched.get("id_paths", [])),
        id_field_names=tuple(str(item) for item in enriched.get("id_field_names", ["id"])),
        preserve_order=bool(enriched.get("preserve_order", True)),
        image_ground_truth=enriched.get("image_ground_truth"),
        fake_mode=str(enriched.get("fake_mode", "valid")),
        min_length_ratio=enriched.get("min_length_ratio"),
        max_length_ratio=enriched.get("max_length_ratio"),
        length_ratio_policy=_length_ratio_policy_from_dict(
            enriched.get("length_ratio_policy", "hard")
        ),
        task_intent=str(enriched.get("task_intent", "generic")),
        input_profile=str(enriched.get("input_profile", "clean")),
        output_language_policy=str(
            enriched.get("output_language_policy", "preserve_input_language")
        ),
        validation_policy=str(enriched.get("validation_policy", "automatic")),
        prompt_variant=str(enriched.get("prompt_variant", "baseline")),
        response_schema_complexity=enriched.get("response_schema_complexity"),
        source_text=enriched.get("source_text"),
        source_fixture=enriched.get("source_fixture"),
        source_fixture_id=enriched.get("source_fixture_id"),
        prompt_template=enriched.get("prompt_template"),
        prompt_template_hash=enriched.get("prompt_template_hash"),
        fixture_text_hash=enriched.get("fixture_text_hash"),
        glossary_hash=enriched.get("glossary_hash"),
        language_include_paths=tuple(
            str(item) for item in enriched.get("language_include_paths", [])
        ),
        language_ignore_paths=tuple(
            str(item) for item in enriched.get("language_ignore_paths", [])
        ),
        expected_terms=tuple(
            item for item in enriched.get("expected_terms", []) if isinstance(item, dict)
        ),
        punctuation_policy=str(enriched.get("punctuation_policy", "diagnostic")),
        paragraphing_policy=enriched.get("paragraphing_policy"),
        paragraph_count_min=enriched.get("paragraph_count_min"),
        paragraph_count_max=enriched.get("paragraph_count_max"),
        filler_terms=tuple(str(item) for item in enriched.get("filler_terms", [])),
        filler_cleanup_policy=enriched.get("filler_cleanup_policy"),
        term_normalization_policy=enriched.get("term_normalization_policy"),
        near_identity_policy=enriched.get("near_identity_policy"),
        language_drift_policy=enriched.get("language_drift_policy"),
        term_language_preservation_policy=enriched.get("term_language_preservation_policy"),
        manual_review_policy=enriched.get("manual_review_policy"),
    )


def _enrich_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(payload)
    fixture_payload = _load_source_fixture(enriched.get("source_fixture"))
    template_text = _load_prompt_template(enriched.get("prompt_template"))
    source_text = enriched.get("source_text") or fixture_payload.get("text")
    metadata = (
        fixture_payload.get("metadata") if isinstance(fixture_payload.get("metadata"), dict) else {}
    )

    if source_text is not None:
        enriched["source_text"] = str(source_text)
        enriched.setdefault("fixture_text_hash", stable_hash(str(source_text)))
    if fixture_payload.get("fixture_id") is not None:
        enriched.setdefault("source_fixture_id", str(fixture_payload["fixture_id"]))
    if template_text is not None:
        enriched.setdefault("prompt_template_hash", stable_hash(template_text))
        enriched["prompt"] = render_postprocessing_prompt(
            template_text=template_text,
            source_text=str(source_text or ""),
            task_intent=str(enriched.get("task_intent", "generic")),
            response_schema_complexity=str(
                enriched.get("response_schema_complexity")
                or enriched.get("structure_complexity", "simple")
            ),
            expected_terms=tuple(
                item
                for item in enriched.get("expected_terms") or metadata.get("expected_terms", [])
                if isinstance(item, dict)
            ),
        )
    if "expected_terms" not in enriched and "expected_terms" in metadata:
        enriched["expected_terms"] = metadata["expected_terms"]
    if "filler_terms" not in enriched and "filler_terms" in metadata:
        enriched["filler_terms"] = metadata["filler_terms"]
    if enriched.get("expected_terms"):
        enriched.setdefault("glossary_hash", stable_hash(_stable_json(enriched["expected_terms"])))
    return enriched


def _load_source_fixture(path_value: Any) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(str(path_value))
    if not path.is_absolute():
        path = _repo_root() / path
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_prompt_template(path_value: Any) -> str | None:
    if not path_value:
        return None
    path = Path(str(path_value))
    if not path.is_absolute():
        path = _repo_root() / path
    return path.read_text(encoding="utf-8")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def render_postprocessing_prompt(
    *,
    template_text: str,
    source_text: str,
    task_intent: str,
    response_schema_complexity: str,
    expected_terms: tuple[dict[str, Any], ...] = (),
) -> str:
    glossary = ""
    if expected_terms:
        glossary_lines = []
        for term in expected_terms:
            variants = ", ".join(str(item) for item in term.get("source_variants", ()))
            glossary_lines.append(f"- {variants} -> {term.get('normalized', '')}")
        glossary = "\nGlossary:\n" + "\n".join(glossary_lines)
    return (
        "Return JSON only. Do not use Markdown. Follow the provided JSON schema. "
        "Do not add new facts. Preserve the input language unless the task explicitly asks for translation. "
        "Preserve English technical terms when they are technical names.\n"
        f"Task intent: {task_intent}.\n"
        f"Response schema complexity: {response_schema_complexity}.\n"
        f"Instructions:\n{template_text.strip()}"
        f"{glossary}\n"
        f"Input transcript:\n{source_text.strip()}"
    )


def _length_ratio_policy_from_dict(payload: Any) -> str:
    if isinstance(payload, dict):
        value = payload.get("mode", "hard")
    else:
        value = payload
    if value == "diagnostic":
        return "warning"
    if value in {"off", "warning", "hard"}:
        return str(value)
    return "hard"


def _structured_runtime_from_dict(payload: Any) -> StructuredRuntimeConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("structured_runtime must be a mapping")
    value = payload.get("strict_json_schema", True)
    if not isinstance(value, bool):
        raise ValueError("structured_runtime.strict_json_schema must be a boolean")
    return StructuredRuntimeConfig(strict_json_schema=value)


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
    requested_modalities = {
        *(config.axes.get("modality", ())),
        *(task.modality for task in config.tasks),
    }
    requested_volumes = {
        *(config.axes.get("volume", ())),
        *(task.volume for task in config.tasks),
    }
    if "stress" in requested_volumes and not safety.allow_stress:
        raise ValueError("volume=stress requires safety.allow_stress=true")
    if safety.live and "image" in requested_modalities and not safety.allow_image_live:
        raise ValueError("image live execution requires safety.allow_image_live=true")
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
    if safety.live:
        raise ValueError("Benchmark safety requires live=false in the core runner")
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


def _validate_live_transport_safety(config: BenchmarkConfig, options: LiveBridgeOptions) -> None:
    safety = config.safety
    if not safety.live:
        raise LiveBridgeError("live transport requires safety.live=true")
    if safety.allow_model_downloads:
        raise LiveBridgeError("live transport does not download models")
    if safety.allow_model_loads and not options.allow_model_load:
        raise LiveBridgeError("model loads require bridge allow_model_load=True")
    if safety.allow_raw_prompt_response_artifacts:
        raise LiveBridgeError("raw prompt/response artifacts are not allowed")
    if safety.allow_image_live:
        raise LiveBridgeError("image live execution is not implemented")
    if "stress" in set(config.axes.get("volume", ())) and not safety.allow_stress:
        raise LiveBridgeError("volume=stress requires safety.allow_stress=true")
    if safety.allow_stress and not options.allow_stress:
        raise LiveBridgeError("stress/overnight requires bridge allow_stress=True")
    if len(config.models) > safety.max_models:
        raise LiveBridgeError("model count exceeds safety.max_models")
    if config.repeats > safety.max_repeats:
        raise LiveBridgeError("repeats exceeds safety.max_repeats")
    for context_tier in config.axes.get("context_tier", ("8192",)):
        if _context_tier_int(context_tier) > safety.max_context_tier:
            raise LiveBridgeError("context_tier exceeds safety.max_context_tier")
    if options.max_requests > safety.max_requests:
        raise LiveBridgeError("bridge max_requests exceeds safety.max_requests")


def _validate_live_screening_safety(config: BenchmarkConfig, options: LiveBridgeOptions) -> None:
    safety = config.safety
    if not safety.live:
        raise LiveBridgeError("guarded live screening requires safety.live=true")
    if safety.allow_model_downloads:
        raise LiveBridgeError("guarded live screening does not download models")
    if safety.allow_model_loads and not options.allow_model_load:
        raise LiveBridgeError("model loads require bridge allow_model_load=True")
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
    replaced = False
    if isinstance(value, dict):
        for key in ("text", "normalized_text", "clean_text", "summary", "title"):
            if isinstance(value.get(key), str):
                value[key] = replacement
                replaced = True
        for child in value.values():
            replaced = _replace_first_text(child, replacement) or replaced
    elif isinstance(value, list):
        for child in value:
            replaced = _replace_first_text(child, replacement) or replaced
    return replaced


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


def _is_warmup_first_request(cell: MatrixCell) -> bool:
    return cell.axes.get("cache_mode", "none") == "warmup_first" and cell.repeat_index == 0


def _cache_telemetry_fields(cell: MatrixCell, request_plan: RequestPlan) -> dict[str, Any]:
    cache_mode = cell.axes.get("cache_mode", "none")
    request_metadata = request_plan.envelope.safe_metadata()
    response_contract = request_metadata.get("response_contract")
    schema_hash = (
        response_contract.get("schema_hash") if isinstance(response_contract, dict) else None
    )
    prompt_template_hash = stable_hash(cell.task.prompt) if cell.task.prompt else None
    text_inputs = request_metadata.get("text_inputs")
    image_inputs = request_metadata.get("image_inputs")
    dynamic_input_hash = _hash_json_payload(
        {
            "task_id": cell.task.task_id,
            "text_inputs": text_inputs if isinstance(text_inputs, list) else [],
            "image_inputs": image_inputs if isinstance(image_inputs, list) else [],
        }
    )
    stable_prefix_hash = _hash_json_payload(
        {
            "endpoint_family": request_plan.options.endpoint_family,
            "model_id": request_plan.options.model_id,
            "prompt_template_hash": prompt_template_hash,
            "schema_hash": schema_hash,
        }
    )
    repeat_group_id = (
        "repeat_"
        + _hash_json_payload(
            {
                "model_key": cell.model.model_key,
                "task_id": cell.task.task_id,
                "axes": cell.axes,
            }
        )[:16]
    )
    cache_group_id = (
        "cache_"
        + _hash_json_payload(
            {
                "cache_mode": cache_mode,
                "model_key": cell.model.model_key,
                "stable_prefix_hash": stable_prefix_hash,
                "task_id": cell.task.task_id,
            }
        )[:16]
    )
    return {
        "cache_mode": cache_mode,
        "cache_group_id": cache_group_id,
        "warmup_request_index": cell.repeat_index + 1 if cache_mode == "warmup_first" else None,
        "is_warmup_request": _is_warmup_first_request(cell),
        "stable_prefix_hash": stable_prefix_hash,
        "schema_hash": schema_hash,
        "prompt_template_hash": prompt_template_hash,
        "dynamic_input_hash": dynamic_input_hash,
        "repeat_group_id": repeat_group_id,
        "same_input_hash": _hash_json_payload(
            {
                "dynamic_input_hash": dynamic_input_hash,
                "schema_hash": schema_hash,
                "prompt_template_hash": prompt_template_hash,
            }
        ),
        "cache_hit_inferred": "unknown",
        "cache_hit_reported": "unknown",
        "kv_reuse_proven": False,
    }


def _timing_telemetry_fields(result: RequestResult) -> dict[str, Any]:
    latency_ms = result.latency_ms
    completion_tokens = result.token_counts.get("completion")
    tokens_per_sec = None
    if completion_tokens is not None and latency_ms > 0:
        tokens_per_sec = round(completion_tokens / (latency_ms / 1000), 4)
    return {
        "ttft_ms": None,
        "prompt_processing_ms": None,
        "total_latency_ms": latency_ms,
        "tokens_per_sec": tokens_per_sec,
    }


def _resource_telemetry_fields(cell: MatrixCell) -> dict[str, Any]:
    mode = cell.axes.get("resource_telemetry_mode", "full")
    execution_target = cell.axes.get("execution_target", "local_managed")
    missing_allowed = mode == "timing_only" or execution_target == "remote_link"
    return {
        "execution_target": execution_target,
        "resource_telemetry_mode": mode,
        "resource_telemetry_status": "timing_only" if missing_allowed else "not_collected",
        "resource_ram_required": not missing_allowed,
        "resource_vram_required": not missing_allowed,
        "ram_before_mb": None,
        "ram_peak_mb": None,
        "ram_after_mb": None,
        "vram_before_mb": None,
        "vram_peak_mb": None,
        "vram_after_mb": None,
    }


def _hash_json_payload(payload: dict[str, Any]) -> str:
    return stable_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _first_error_category(validation: Any) -> str | None:
    for item in validation.results:
        if item.status == "fail":
            return item.category or item.name
    return None


def _first_warning_category(validation: Any) -> str | None:
    for item in validation.results:
        if item.status == "warning":
            return item.category or item.name
    return None


def _warning_count(validation: Any) -> int:
    return sum(1 for item in validation.results if item.status == "warning")
