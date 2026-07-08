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
    expected_output: Any | None = None
    expected_ids: tuple[str, ...] = ()
    image_ground_truth: dict[str, Any] | None = None


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
        axes = {key: tuple(str(item) for item in value) for key, value in axes_payload.items()}
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
        contract = ResponseContract(
            mode="json" if self.task.schema is not None else "text",
            schema=self.task.schema,
            expected_ids=self.task.expected_ids,
            language=self.axes.get("language"),
            expected_output=self.task.expected_output,
            image_ground_truth=self.task.image_ground_truth,
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
            metadata={"task_id": self.task.task_id, "task_family": self.task.family},
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

    def execute(self, plan: RequestPlan) -> tuple[str, RequestResult]:
        started = time.monotonic()
        expected = plan.envelope.response_contract.expected_output
        if expected is None:
            expected = {"id": plan.cell_id, "text": "offline fake response"}
        raw_response = (
            json.dumps(expected, ensure_ascii=False, sort_keys=True)
            if plan.envelope.response_contract.mode == "json"
            else str(expected)
        )
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        result = RequestResult.from_raw_response(
            request_id=plan.envelope.request_id,
            model_id=plan.options.model_id,
            raw_response=raw_response,
            latency_ms=elapsed_ms,
            token_counts={
                "prompt": sum(
                    item.safe_metadata()["char_count"] for item in plan.envelope.text_inputs
                ),
                "completion": len(raw_response),
            },
        )
        return raw_response, result


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
        raw_response, result = transport.execute(request_plan)
        validation = validate_response(raw_response, request_plan.envelope.response_contract)
        retry_count = 0
        if validation.status == "fail" and cell.axes.get("retry_policy") == "retry1":
            retry_count = 1
            raw_response, result = transport.execute(request_plan)
            validation = validate_response(raw_response, request_plan.envelope.response_contract)
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
        expected_output=payload.get("expected_output"),
        expected_ids=tuple(str(item) for item in payload.get("expected_ids", [])),
        image_ground_truth=payload.get("image_ground_truth"),
    )


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
