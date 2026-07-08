from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from .artifacts import ArtifactSet, write_run_artifacts
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


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    family: str
    modality: str = "text"
    prompt: str = ""
    image_hash: str | None = None
    schema: dict[str, Any] | None = None
    schema_family: str | None = None
    schema_variant: str | None = None
    expected_output: Any | None = None
    expected_ids: tuple[Any, ...] = ()
    image_ground_truth: dict[str, Any] | None = None
    fake_mode: str = "valid"
    min_length_ratio: float | None = None
    max_length_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    run_id: str
    models: tuple[ModelSpec, ...]
    tasks: tuple[TaskSpec, ...]
    axes: dict[str, tuple[str, ...]]
    repeats: int = 1

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

    def planner_summary(self, *, live: bool = False) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config_hash": self.config_hash,
            "axes": {key: list(value) for key, value in self.axes.items()},
            "cell_count": len(self.cells),
            "repeats": self.repeats,
            "live": live,
            "privacy_mode": "safe-default",
            "schema_version": "structured-matrix-v1",
        }


def plan_matrix(config: BenchmarkConfig) -> MatrixPlan:
    cells: list[MatrixCell] = []
    for model in config.models:
        for task in config.tasks:
            for modality in config.axes.get("modality", (task.modality,)):
                if modality not in model.supported_modalities:
                    continue
                for language in config.axes.get("language", ("en_en",)):
                    for complexity in config.axes.get("structure_complexity", ("simple",)):
                        for volume in config.axes.get("volume", ("single",)):
                            for context_tier in config.axes.get("context_tier", ("8192",)):
                                for schema_variant in config.axes.get(
                                    "schema_variant", ("baseline_loose",)
                                ):
                                    for retry_policy in config.axes.get("retry_policy", ("off",)):
                                        for repeat_index in range(config.repeats):
                                            axes = {
                                                "modality": modality,
                                                "language": language,
                                                "structure_complexity": complexity,
                                                "volume": volume,
                                                "context_tier": context_tier,
                                                "schema_variant": schema_variant,
                                                "retry_policy": retry_policy,
                                            }
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
    return MatrixPlan(config.run_id, config.safe_hash(), tuple(cells), config.axes, config.repeats)


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
        raise ValueError("Live LM Studio execution is not implemented in the safe default runner")
    plan = plan_matrix(config)
    rows: list[dict[str, Any]] = []
    transport = FakeTransport()
    for cell in plan.cells:
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
    run_dir = Path(output_root) / config.run_id
    return write_run_artifacts(run_dir, plan.planner_summary(live=False), rows)


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
    )


def _task_from_dict(payload: dict[str, Any]) -> TaskSpec:
    return TaskSpec(
        task_id=str(payload["task_id"]),
        family=str(payload.get("family", "simple_flat")),
        modality=str(payload.get("modality", "text")),
        prompt=str(payload.get("prompt", "")),
        image_hash=payload.get("image_hash"),
        schema=payload.get("schema"),
        schema_family=payload.get("schema_family"),
        schema_variant=payload.get("schema_variant"),
        expected_output=payload.get("expected_output"),
        expected_ids=tuple(payload.get("expected_ids", [])),
        image_ground_truth=payload.get("image_ground_truth"),
        fake_mode=str(payload.get("fake_mode", "valid")),
        min_length_ratio=payload.get("min_length_ratio"),
        max_length_ratio=payload.get("max_length_ratio"),
    )


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
