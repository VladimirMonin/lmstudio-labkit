"""Offline structured matrix planning and fake execution harness."""

from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from itertools import product
from pathlib import Path
from typing import Any

from lmstudio_managed.metrics import (
    MemoryCellObservation,
    MemoryRecommendationCatalog,
    SafetyReservePolicy,
    build_memory_recommendation,
)

from .config import ExperimentConfig, load_experiment_config, load_raw_experiment_config
from .datasets import DatasetManifest, load_dataset_manifest
from .metrics import SCHEMA_VERSION, append_jsonl_record
from .privacy import find_privacy_violations
from .report import write_csv_file, write_json_file
from .structured import validate_factual_blocks_response

MATRIX_PLAN_OUTPUT_FILE_NAMES = (
    "experiment.yaml",
    "planner_summary.json",
    "matrix_cells.jsonl",
    "cell_summary.csv",
    "privacy_scan.json",
    "report.md",
)
MATRIX_FAKE_RUN_OUTPUT_FILE_NAMES = (
    "experiment.yaml",
    "planner_summary.json",
    "cell_results.jsonl",
    "cell_summary.csv",
    "model_summary.csv",
    "failure_summary.csv",
    "retry_summary.csv",
    "resource_summary.csv",
    "privacy_scan.json",
    "report.md",
)
MATRIX_CELL_FIELDNAMES = (
    "run_id",
    "cell_id",
    "model_key",
    "mode",
    "dataset_id",
    "modality",
    "language",
    "structure_complexity",
    "volume",
    "context_tier",
    "schema_variant",
    "retry_policy",
    "repeat_index",
    "status",
    "business_pass",
    "error_category",
)
MODEL_SUMMARY_FIELDNAMES = (
    "run_id",
    "model_key",
    "planned_cells",
    "completed_cells",
    "business_pass_count",
    "business_pass_rate",
)
FAILURE_SUMMARY_FIELDNAMES = (
    "run_id",
    "failure_category",
    "affected_models",
    "count",
)
RETRY_SUMMARY_FIELDNAMES = (
    "run_id",
    "retry_policy",
    "attempt_count",
    "business_pass_count",
    "recovery_rate",
)
RESOURCE_SUMMARY_FIELDNAMES = (
    "run_id",
    "model_key",
    "context_tier",
    "estimated_input_tokens",
    "actual_input_tokens",
    "estimated_output_tokens",
    "actual_output_tokens",
    "latency_ms",
)
_SAFE_ID_REPLACEMENTS = str.maketrans({"/": "_", "\\": "_", " ": "_"})
MEMORY_MATRIX_SCHEMA_REVISION = "gpu-memory-concurrency-matrix.v1"
MEMORY_MATRIX_CONTEXT_TIERS = (8192, 16_384, 32_768, 49_152, 65_536)
MEMORY_MATRIX_LANES = ("load_only", "p1", "p2", "p4")


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


@dataclass(frozen=True, slots=True)
class MemoryMatrixCandidate:
    model_artifact: str
    artifact_revision: str
    artifact_checksum: str
    quantization: str
    gpu_placement: str
    kv_placement: str
    runtime_identity: str
    runner_revision: str
    schema_revision: str

    def __post_init__(self) -> None:
        for field_name in (
            "model_artifact",
            "artifact_revision",
            "artifact_checksum",
            "quantization",
            "gpu_placement",
            "kv_placement",
            "runtime_identity",
            "runner_revision",
            "schema_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_non_empty(getattr(self, field_name), field_name=field_name),
            )
        checksum = self.artifact_checksum
        digest = checksum.removeprefix("sha256:")
        if (
            not checksum.startswith("sha256:")
            or len(digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
        ):
            raise ValueError("artifact_checksum must be a complete sha256 digest")


@dataclass(frozen=True, slots=True)
class MemoryMatrixWorkload:
    workload_id: str
    modality: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "workload_id",
            _require_non_empty(self.workload_id, field_name="workload_id"),
        )
        normalized_modality = _require_non_empty(self.modality, field_name="modality").lower()
        if normalized_modality not in {"text", "vision"}:
            raise ValueError("modality must be text or vision")
        object.__setattr__(self, "modality", normalized_modality)


@dataclass(frozen=True, slots=True)
class MemoryMatrixCell:
    cell_id: str
    lane: str
    model_artifact: str
    artifact_revision: str
    artifact_checksum: str
    quantization: str
    context_tokens: int
    runtime_parallel: int
    application_concurrency: int
    gpu_placement: str
    kv_placement: str
    workload_id: str
    workload_modality: str
    runtime_identity: str
    runner_revision: str
    schema_revision: str
    required_attempts: int

    def identity_payload(self) -> dict[str, object]:
        return {
            "application_concurrency": self.application_concurrency,
            "artifact_checksum": self.artifact_checksum,
            "artifact_revision": self.artifact_revision,
            "context_tokens": self.context_tokens,
            "gpu_placement": self.gpu_placement,
            "kv_placement": self.kv_placement,
            "model_artifact": self.model_artifact,
            "quantization": self.quantization,
            "runner_revision": self.runner_revision,
            "runtime_identity": self.runtime_identity,
            "runtime_parallel": self.runtime_parallel,
            "schema_revision": self.schema_revision,
            "workload_id": self.workload_id,
            "workload_modality": self.workload_modality,
        }


@dataclass(frozen=True, slots=True)
class MemoryConcurrencyPlan:
    plan_id: str
    schema_revision: str
    context_tiers: tuple[int, ...]
    workload_modality: str
    required_attempts: int
    cells: tuple[MemoryMatrixCell, ...]


@dataclass(frozen=True, slots=True)
class RequestInterval:
    request_id: str
    started_monotonic_s: float
    ended_monotonic_s: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_id",
            _require_non_empty(self.request_id, field_name="request_id"),
        )
        if not math.isfinite(self.started_monotonic_s) or not math.isfinite(self.ended_monotonic_s):
            raise ValueError("request interval timestamps must be finite")
        if self.ended_monotonic_s <= self.started_monotonic_s:
            raise ValueError("request interval end must be after start")

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "started_monotonic_s": self.started_monotonic_s,
            "ended_monotonic_s": self.ended_monotonic_s,
        }


@dataclass(frozen=True, slots=True)
class MemoryMatrixAttemptReservation:
    attempt_id: str
    cell_id: str
    attempt_index: int


@dataclass(frozen=True, slots=True)
class MemoryMatrixAttemptResult:
    operation_succeeded: bool
    observed_identity: Mapping[str, object]
    request_intervals: tuple[RequestInterval, ...] = ()
    phase_evidence_valid: bool = False
    independent_cycle_proven: bool = False
    immutable_owner_evidence_bound: bool = False


def _canonical_hash(payload: Mapping[str, object] | Sequence[object]) -> str:
    return _hash_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def aggregate_memory_recommendations(
    observations: Sequence[MemoryCellObservation],
    *,
    required_repeats: int = 3,
    reserve_policy: SafetyReservePolicy | None = None,
) -> MemoryRecommendationCatalog:
    """Aggregate exact measured cells without extrapolating one lane into another."""

    grouped: defaultdict[tuple[object, ...], list[MemoryCellObservation]] = defaultdict(list)
    for observation in observations:
        if not isinstance(observation, MemoryCellObservation):
            raise TypeError("observations must contain MemoryCellObservation values")
        grouped[observation.cell_identity()].append(observation)
    recommendations = tuple(
        sorted(
            (
                build_memory_recommendation(
                    tuple(rows),
                    required_repeats=required_repeats,
                    reserve_policy=reserve_policy,
                )
                for rows in grouped.values()
            ),
            key=lambda row: (
                row.model_artifact,
                row.artifact_revision,
                row.artifact_checksum,
                row.quantization,
                row.context_tokens,
                row.runtime_parallel,
                row.application_concurrency,
                row.workload_class,
                row.placement_requirement,
                row.kv_placement,
            ),
        )
    )
    return MemoryRecommendationCatalog(recommendations=recommendations)


def build_memory_concurrency_plan(
    *,
    candidate: MemoryMatrixCandidate,
    workloads: Sequence[MemoryMatrixWorkload],
    context_tiers: Sequence[int] = MEMORY_MATRIX_CONTEXT_TIERS,
    required_attempts: int = 3,
    text_plan_admitted: bool = False,
) -> MemoryConcurrencyPlan:
    normalized_workloads = tuple(workloads)
    if not normalized_workloads:
        raise ValueError("workloads must not be empty")
    workload_ids = tuple(workload.workload_id for workload in normalized_workloads)
    if len(set(workload_ids)) != len(workload_ids):
        raise ValueError("workload_id values must be unique")
    modalities = {workload.modality for workload in normalized_workloads}
    if len(modalities) != 1:
        raise ValueError("memory matrix must not mix text and vision workloads")
    modality = next(iter(modalities))
    if modality == "vision" and not text_plan_admitted:
        raise ValueError("vision matrix requires admitted text plan evidence")
    if (
        isinstance(required_attempts, bool)
        or not isinstance(required_attempts, int)
        or required_attempts < 3
    ):
        raise ValueError("required_attempts must be an integer >= 3")

    normalized_contexts = tuple(context_tiers)
    if not normalized_contexts or any(
        isinstance(context, bool) or not isinstance(context, int) for context in normalized_contexts
    ):
        raise ValueError("context_tiers must contain integer token counts")
    if normalized_contexts != MEMORY_MATRIX_CONTEXT_TIERS[: len(normalized_contexts)]:
        raise ValueError("context_tiers must be the ordered 8K/16K/32K/48K/64K prefix")

    cell_payloads: list[dict[str, Any]] = []
    for context_tokens in normalized_contexts:
        for workload in normalized_workloads:
            for lane, runtime_parallel, application_concurrency in (
                ("load_only", 1, 0),
                ("p1", 1, 1),
                ("p2", 2, 2),
                ("p4", 4, 4),
            ):
                identity = {
                    "application_concurrency": application_concurrency,
                    "artifact_checksum": candidate.artifact_checksum,
                    "artifact_revision": candidate.artifact_revision,
                    "context_tokens": context_tokens,
                    "gpu_placement": candidate.gpu_placement,
                    "kv_placement": candidate.kv_placement,
                    "model_artifact": candidate.model_artifact,
                    "quantization": candidate.quantization,
                    "runner_revision": candidate.runner_revision,
                    "runtime_identity": candidate.runtime_identity,
                    "runtime_parallel": runtime_parallel,
                    "schema_revision": candidate.schema_revision,
                    "workload_id": workload.workload_id,
                    "workload_modality": workload.modality,
                }
                cell_payloads.append(
                    {
                        **identity,
                        "cell_id": _canonical_hash(identity),
                        "lane": lane,
                        "required_attempts": required_attempts,
                    }
                )
    plan_payload = {
        "matrix_schema_revision": MEMORY_MATRIX_SCHEMA_REVISION,
        "required_attempts": required_attempts,
        "cells": cell_payloads,
    }
    return MemoryConcurrencyPlan(
        plan_id=_canonical_hash(plan_payload),
        schema_revision=MEMORY_MATRIX_SCHEMA_REVISION,
        context_tiers=normalized_contexts,
        workload_modality=modality,
        required_attempts=required_attempts,
        cells=tuple(MemoryMatrixCell(**payload) for payload in cell_payloads),
    )


def _maximum_observed_overlap(intervals: Sequence[RequestInterval]) -> int:
    points: list[tuple[float, int]] = []
    request_ids: set[str] = set()
    for interval in intervals:
        if interval.request_id in request_ids:
            raise ValueError("request interval ids must be unique within an attempt")
        request_ids.add(interval.request_id)
        points.append((interval.started_monotonic_s, 1))
        points.append((interval.ended_monotonic_s, -1))
    active = 0
    maximum = 0
    for _timestamp, delta in sorted(points, key=lambda point: (point[0], point[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


class MemoryMatrixAttemptStore:
    """Append-only reservation/outcome journal for one immutable matrix plan."""

    def __init__(self, path: str | Path, plan: MemoryConcurrencyPlan) -> None:
        self.path = Path(path)
        self.plan = plan
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() or self.path.stat().st_size == 0:
            self._append(
                {
                    "event": "plan_bound",
                    "plan_id": plan.plan_id,
                    "schema_revision": plan.schema_revision,
                }
            )
        events = self.events()
        binding = events[0] if events else {}
        if binding.get("event") != "plan_bound" or binding.get("plan_id") != plan.plan_id:
            raise ValueError("attempt journal plan identity mismatch")

    def _append(self, payload: Mapping[str, object]) -> dict[str, object]:
        row = {
            **payload,
            "recorded_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        encoded = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return row

    def events(self) -> tuple[dict[str, object], ...]:
        return tuple(
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def reservation_for(self, attempt_id: str) -> dict[str, object] | None:
        return next(
            (
                event
                for event in self.events()
                if event.get("event") == "attempt_reserved"
                and event.get("attempt_id") == attempt_id
            ),
            None,
        )

    def _cell_reservations(self, cell_id: str) -> tuple[dict[str, object], ...]:
        return tuple(
            event
            for event in self.events()
            if event.get("event") == "attempt_reserved" and event.get("cell_id") == cell_id
        )

    def _cell_outcomes(self, cell_id: str) -> tuple[dict[str, object], ...]:
        return tuple(
            event
            for event in self.events()
            if event.get("event") == "attempt_outcome" and event.get("cell_id") == cell_id
        )

    def _cell_admitted(self, cell: MemoryMatrixCell) -> bool:
        outcomes = self._cell_outcomes(cell.cell_id)
        return len(outcomes) >= cell.required_attempts and all(
            outcome.get("status") == "admitted" for outcome in outcomes
        )

    def _prerequisite_cell(self, cell: MemoryMatrixCell) -> MemoryMatrixCell | None:
        lane_index = MEMORY_MATRIX_LANES.index(cell.lane)
        if lane_index > 0:
            required_lane = MEMORY_MATRIX_LANES[lane_index - 1]
            return next(
                candidate
                for candidate in self.plan.cells
                if candidate.context_tokens == cell.context_tokens
                and candidate.workload_id == cell.workload_id
                and candidate.lane == required_lane
            )
        context_index = self.plan.context_tiers.index(cell.context_tokens)
        if context_index == 0:
            return None
        prior_context = self.plan.context_tiers[context_index - 1]
        return next(
            candidate
            for candidate in self.plan.cells
            if candidate.context_tokens == prior_context
            and candidate.workload_id == cell.workload_id
            and candidate.lane == "p4"
        )

    def ready_cells(self) -> tuple[MemoryMatrixCell, ...]:
        ready: list[MemoryMatrixCell] = []
        for cell in self.plan.cells:
            prerequisite = self._prerequisite_cell(cell)
            if prerequisite is not None and not self._cell_admitted(prerequisite):
                continue
            if len(self._cell_reservations(cell.cell_id)) >= cell.required_attempts:
                continue
            ready.append(cell)
        return tuple(ready)

    def reserve(self, cell: MemoryMatrixCell) -> MemoryMatrixAttemptReservation:
        known_cell = next(
            (candidate for candidate in self.plan.cells if candidate.cell_id == cell.cell_id),
            None,
        )
        if known_cell != cell:
            raise ValueError("cell does not belong to the bound matrix plan")
        if cell not in self.ready_cells():
            raise ValueError("cell is not eligible for a missing attempt")
        attempt_index = len(self._cell_reservations(cell.cell_id)) + 1
        attempt_id = f"{cell.cell_id}:attempt-{attempt_index:04d}"
        self._append(
            {
                "event": "attempt_reserved",
                "plan_id": self.plan.plan_id,
                "cell_id": cell.cell_id,
                "attempt_id": attempt_id,
                "attempt_index": attempt_index,
                "lane": cell.lane,
                "identity": cell.identity_payload(),
            }
        )
        return MemoryMatrixAttemptReservation(
            attempt_id=attempt_id,
            cell_id=cell.cell_id,
            attempt_index=attempt_index,
        )

    def complete(
        self,
        reservation: MemoryMatrixAttemptReservation,
        cell: MemoryMatrixCell,
        result: MemoryMatrixAttemptResult,
    ) -> dict[str, object]:
        known_cell = next(
            (candidate for candidate in self.plan.cells if candidate.cell_id == cell.cell_id),
            None,
        )
        if known_cell != cell:
            raise ValueError("cell does not belong to the bound matrix plan")
        persisted_reservation = self.reservation_for(reservation.attempt_id)
        if persisted_reservation is None:
            raise ValueError("attempt outcome requires a persisted reservation")
        if (
            reservation.cell_id != cell.cell_id
            or persisted_reservation.get("cell_id") != cell.cell_id
            or persisted_reservation.get("attempt_index") != reservation.attempt_index
        ):
            raise ValueError("attempt reservation identity mismatch")
        if any(
            event.get("event") == "attempt_outcome"
            and event.get("attempt_id") == reservation.attempt_id
            for event in self.events()
        ):
            raise ValueError("attempt outcome is append-only and already exists")

        identity_matches = dict(result.observed_identity) == cell.identity_payload()
        maximum_overlap = _maximum_observed_overlap(result.request_intervals)
        overlap_proven = (
            True
            if cell.application_concurrency == 0
            else maximum_overlap >= cell.application_concurrency
        )
        if not result.operation_succeeded:
            status = "operation_failed"
        elif not identity_matches:
            status = "identity_mismatch"
        elif not overlap_proven:
            status = "overlap_unproven"
        elif not result.phase_evidence_valid:
            status = "phase_evidence_invalid"
        elif not result.independent_cycle_proven:
            status = "independent_cycle_unproven"
        elif not result.immutable_owner_evidence_bound:
            status = "immutable_owner_evidence_unbound"
        else:
            status = "admitted"
        return self._append(
            {
                "event": "attempt_outcome",
                "plan_id": self.plan.plan_id,
                "cell_id": cell.cell_id,
                "attempt_id": reservation.attempt_id,
                "status": status,
                "operation_succeeded": result.operation_succeeded,
                "identity_matches": identity_matches,
                "configured_runtime_parallel": cell.runtime_parallel,
                "configured_application_concurrency": cell.application_concurrency,
                "maximum_observed_overlap": maximum_overlap,
                "overlap_proven": overlap_proven,
                "phase_evidence_valid": result.phase_evidence_valid,
                "independent_cycle_proven": result.independent_cycle_proven,
                "immutable_owner_evidence_bound": result.immutable_owner_evidence_bound,
                "request_intervals": [interval.to_dict() for interval in result.request_intervals],
            }
        )


def execute_memory_matrix_attempt(
    *,
    store: MemoryMatrixAttemptStore,
    cell: MemoryMatrixCell,
    executor: Callable[[MemoryMatrixAttemptReservation], MemoryMatrixAttemptResult],
    live_enabled: bool = False,
    downloads_allowed: bool = False,
) -> dict[str, object]:
    if downloads_allowed:
        raise ValueError("downloads are forbidden for the memory concurrency matrix")
    if not live_enabled:
        raise ValueError("memory matrix execution requires live_enabled=True")
    reservation = store.reserve(cell)
    try:
        result = executor(reservation)
    except Exception:
        store.complete(
            reservation,
            cell,
            MemoryMatrixAttemptResult(
                operation_succeeded=False,
                observed_identity=cell.identity_payload(),
            ),
        )
        raise
    if not isinstance(result, MemoryMatrixAttemptResult):
        raise TypeError("matrix executor must return MemoryMatrixAttemptResult")
    return store.complete(reservation, cell, result)


@dataclass(frozen=True, slots=True)
class StructuredMatrixPlan:
    config: ExperimentConfig
    run_id: str
    matrix_axes: Mapping[str, tuple[str, ...]]
    cells: tuple[dict[str, Any], ...]

    def planner_summary(self) -> dict[str, Any]:
        selected_axes = {key: list(value) for key, value in self.matrix_axes.items()}
        planned_repeats = self.config.repeats
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "experiment_id": self.config.experiment_id,
            "config_hash": _hash_text(json.dumps(self.config.to_dict(), sort_keys=True)),
            "selected_axes": selected_axes,
            "cell_count": len(self.cells),
            "planned_repeats": planned_repeats,
            "live_mode": False,
            "offline_mode": True,
            "fake_runner": False,
            "privacy_mode": "publication_safe",
            "schema_versions": [SCHEMA_VERSION],
            "raw_prompt_response_stored": False,
        }


def _hash_text(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def _safe_id(value: str) -> str:
    safe = value.translate(_SAFE_ID_REPLACEMENTS)
    return "".join(
        character if character.isalnum() or character in "_.-" else "_" for character in safe
    )


def _require_string_axis(value: Any, *, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = tuple(value)
    else:
        raise ValueError(f"matrix.{field_name} must be a string or list of strings")
    normalized = tuple(str(item).strip() for item in items if str(item).strip())
    if not normalized:
        raise ValueError(f"matrix.{field_name} must not be empty")
    return normalized


def _matrix_axis(
    matrix_payload: Mapping[str, Any],
    field_name: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if field_name not in matrix_payload:
        return default
    return _require_string_axis(matrix_payload[field_name], field_name=field_name)


def _load_matrix_axes(raw_payload: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    raw_matrix = raw_payload.get("matrix", {})
    if raw_matrix is None:
        raw_matrix = {}
    if not isinstance(raw_matrix, Mapping):
        raise ValueError("matrix must be a mapping")
    retry_default = (
        ("retry1",) if int(raw_payload.get("business_failure_retry_limit") or 0) > 0 else ("off",)
    )
    schema_default = (str(raw_payload.get("structured_schema_variant") or "baseline_loose"),)
    return {
        "modality": _matrix_axis(raw_matrix, "modality", ("text",)),
        "language": _matrix_axis(raw_matrix, "language", ("en_en",)),
        "structure_complexity": _matrix_axis(raw_matrix, "structure_complexity", ("simple",)),
        "volume": _matrix_axis(raw_matrix, "volume", ("single",)),
        "schema_variant": _matrix_axis(raw_matrix, "schema_variant", schema_default),
        "retry_policy": _matrix_axis(raw_matrix, "retry_policy", retry_default),
    }


def _load_config_and_axes(
    config_path: str | Path,
) -> tuple[bytes, ExperimentConfig, dict[str, tuple[str, ...]]]:
    config_bytes = Path(config_path).read_bytes()
    _, raw_payload = load_raw_experiment_config(config_path)
    config = load_experiment_config(config_path)
    axes = _load_matrix_axes(raw_payload)
    return config_bytes, config, axes


def _default_run_id(experiment_id: str, *, fake_run: bool = False) -> str:
    suffix = "matrix_fake_run" if fake_run else "matrix_plan"
    return f"{experiment_id}_{suffix}"


def _prepare_run_dir(*, output_root: Path, run_id: str, experiment_id: str) -> Path:
    run_dir = output_root / f"run_{run_id}_{experiment_id}"
    if run_dir.exists():
        raise FileExistsError(
            f"matrix output already exists for run_id {run_id!r} and experiment_id {experiment_id!r}"
        )
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _context_tier(load_config: Mapping[str, Any]) -> str:
    value = load_config.get("context_length")
    return str(value) if value is not None else "model-specific"


def build_structured_matrix_plan(
    config_path: str | Path, *, run_id: str | None = None
) -> StructuredMatrixPlan:
    _, config, axes = _load_config_and_axes(config_path)
    resolved_run_id = run_id or _default_run_id(config.experiment_id)
    dataset_manifests = {
        dataset_id: load_dataset_manifest(dataset_id) for dataset_id in config.datasets
    }

    cells: list[dict[str, Any]] = []
    cell_index = 1
    axis_names = tuple(axes)
    axis_products = tuple(product(*(axes[name] for name in axis_names)))
    for model in config.models:
        for load_config in model.iter_load_configs():
            context_tier = _context_tier(load_config)
            for mode in config.modes:
                for dataset_id, manifest in dataset_manifests.items():
                    for repeat_index in range(1, config.repeats + 1):
                        for axis_values in axis_products:
                            axis_payload = dict(zip(axis_names, axis_values, strict=True))
                            cell_id = f"cell_{cell_index:05d}"
                            request_metadata = {
                                "cell_id": cell_id,
                                "model_key": model.key,
                                "mode": mode,
                                "dataset_id": dataset_id,
                                "dataset_hash": manifest.content_hash,
                                "context_tier": context_tier,
                                "repeat_index": repeat_index,
                                **axis_payload,
                            }
                            cells.append(
                                {
                                    "schema_version": SCHEMA_VERSION,
                                    "run_id": resolved_run_id,
                                    "cell_id": cell_id,
                                    "model_key": model.key,
                                    "mode": mode,
                                    "dataset_id": dataset_id,
                                    "dataset_hash": manifest.content_hash,
                                    "dataset_items_count": manifest.items_count,
                                    "estimated_input_tokens": manifest.estimated_input_tokens,
                                    "actual_input_tokens": manifest.actual_input_tokens,
                                    "context_tier": context_tier,
                                    "load_config_hash": _hash_text(
                                        json.dumps(load_config, sort_keys=True)
                                    ),
                                    "repeat_index": repeat_index,
                                    "request_metadata_hash": _hash_text(
                                        json.dumps(request_metadata, sort_keys=True)
                                    ),
                                    "raw_prompt_response_stored": False,
                                    "status": "planned",
                                    **axis_payload,
                                }
                            )
                            cell_index += 1
    return StructuredMatrixPlan(
        config=config,
        run_id=resolved_run_id,
        matrix_axes=axes,
        cells=tuple(cells),
    )


def _cell_summary_row(
    cell: Mapping[str, Any], *, status: str, result: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    result = result or {}
    return {
        "run_id": cell.get("run_id"),
        "cell_id": cell.get("cell_id"),
        "model_key": cell.get("model_key"),
        "mode": cell.get("mode"),
        "dataset_id": cell.get("dataset_id"),
        "modality": cell.get("modality"),
        "language": cell.get("language"),
        "structure_complexity": cell.get("structure_complexity"),
        "volume": cell.get("volume"),
        "context_tier": cell.get("context_tier"),
        "schema_variant": cell.get("schema_variant"),
        "retry_policy": cell.get("retry_policy"),
        "repeat_index": cell.get("repeat_index"),
        "status": status,
        "business_pass": result.get("business_pass"),
        "error_category": result.get("error_category"),
    }


def _scan_privacy_payloads(
    payloads: Sequence[Mapping[str, Any]], *, artifact_names: Sequence[str]
) -> dict[str, Any]:
    violations: list[str] = []
    for index, payload in enumerate(payloads):
        violations.extend(find_privacy_violations(payload, context=f"artifact[{index}]"))
    categories = sorted({violation.rsplit(" ", 1)[-1] for violation in violations})
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": "matrix-artifacts.v1",
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "violation_categories": categories,
        "scanned_artifact_names": list(artifact_names),
    }


def _render_matrix_report(
    *,
    title: str,
    plan: StructuredMatrixPlan,
    status: str,
    output_files: Sequence[str],
    result_summary: Mapping[str, Any] | None = None,
) -> str:
    summary = plan.planner_summary()
    output_list = "\n".join(f"- `{file_name}`" for file_name in output_files)
    lines = [
        title,
        "",
        "## Run",
        "",
        f"- experiment_id: `{plan.config.experiment_id}`",
        f"- run_id: `{plan.run_id}`",
        "- Mode: offline structured matrix",
        "- Network: disabled",
        "- LM Studio API: not called",
        f"- status: `{status}`",
        "",
        "## Plan",
        "",
        f"- cell_count: `{summary['cell_count']}`",
        f"- planned_repeats: `{summary['planned_repeats']}`",
        f"- selected_axes: `{json.dumps(summary['selected_axes'], sort_keys=True)}`",
        "",
    ]
    if result_summary is not None:
        lines.extend(
            [
                "## Fake Runner Summary",
                "",
                f"- completed_cells: `{result_summary.get('completed_cells')}`",
                f"- business_pass_count: `{result_summary.get('business_pass_count')}`",
                f"- failure_count: `{result_summary.get('failure_count')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Privacy",
            "",
            "- raw prompts: not stored",
            "- raw responses: not stored",
            "- raw local paths: not stored",
            "- artifacts contain hashes, counts, statuses, model identifiers, axis values, and validation summaries only",
            "",
            "## Output Files",
            "",
            output_list,
            "",
        ]
    )
    return "\n".join(lines)


def create_structured_matrix_plan_artifacts(
    config_path: str | Path,
    *,
    output_root: str | Path,
    run_id: str | None = None,
) -> Path:
    config_bytes, _, _ = _load_config_and_axes(config_path)
    plan = build_structured_matrix_plan(config_path, run_id=run_id)
    run_dir = _prepare_run_dir(
        output_root=Path(output_root),
        run_id=plan.run_id,
        experiment_id=plan.config.experiment_id,
    )
    (run_dir / "experiment.yaml").write_bytes(config_bytes)
    planner_summary = plan.planner_summary()
    write_json_file(run_dir / "planner_summary.json", planner_summary)
    matrix_path = run_dir / "matrix_cells.jsonl"
    matrix_path.write_text("", encoding="utf-8")
    for cell in plan.cells:
        append_jsonl_record(matrix_path, cell)
    write_csv_file(
        run_dir / "cell_summary.csv",
        fieldnames=MATRIX_CELL_FIELDNAMES,
        rows=[_cell_summary_row(cell, status="planned") for cell in plan.cells],
    )
    privacy_scan = _scan_privacy_payloads(
        [planner_summary, *plan.cells],
        artifact_names=MATRIX_PLAN_OUTPUT_FILE_NAMES,
    )
    write_json_file(run_dir / "privacy_scan.json", privacy_scan)
    (run_dir / "report.md").write_text(
        _render_matrix_report(
            title="# LM Studio Lab Structured Matrix Plan",
            plan=plan,
            status="planned",
            output_files=MATRIX_PLAN_OUTPUT_FILE_NAMES,
        ),
        encoding="utf-8",
    )
    return run_dir


def _expected_ids_for_dataset(manifest: DatasetManifest) -> tuple[int, ...]:
    return tuple(range(manifest.items_count))


def _fake_response_for_cell(cell: Mapping[str, Any], expected_ids: Sequence[int]) -> str:
    fail_this_cell = str(cell.get("schema_variant")) == "fake_failure"
    returned_ids = tuple(expected_ids)
    if fail_this_cell and returned_ids:
        returned_ids = returned_ids[:-1]
    return json.dumps(
        {
            "schema_version": "factual_blocks.v1",
            "status": "success",
            "blocks": [
                {
                    "block_id": block_id,
                    "normalized_text": f"Synthetic normalized block {block_id}.",
                    "status": "success",
                    "warnings": [],
                }
                for block_id in returned_ids
            ],
            "warnings": [],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _build_fake_result_record(
    *,
    cell: Mapping[str, Any],
    manifest: DatasetManifest,
    fake_output: str,
) -> dict[str, Any]:
    expected_ids = _expected_ids_for_dataset(manifest)
    validation = validate_factual_blocks_response(fake_output, expected_block_ids=expected_ids)
    validation_payload = validation.to_dict()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": cell["run_id"],
        "cell_id": cell["cell_id"],
        "model_key": cell["model_key"],
        "mode": cell["mode"],
        "dataset_id": cell["dataset_id"],
        "dataset_hash": cell["dataset_hash"],
        "modality": cell["modality"],
        "language": cell["language"],
        "structure_complexity": cell["structure_complexity"],
        "volume": cell["volume"],
        "context_tier": cell["context_tier"],
        "schema_variant": cell["schema_variant"],
        "retry_policy": cell["retry_policy"],
        "repeat_index": cell["repeat_index"],
        "input_hash": cell["request_metadata_hash"],
        "output_hash": _hash_text(fake_output),
        "output_chars": len(fake_output),
        "estimated_input_tokens": manifest.estimated_input_tokens,
        "actual_input_tokens": manifest.actual_input_tokens,
        "estimated_output_tokens": len(fake_output) // 3,
        "actual_output_tokens": None,
        "latency_ms": 0.0,
        "fake_runner": True,
        "offline_mode": True,
        "raw_prompt_response_stored": False,
        "json_parse_pass": validation.json_parse_pass,
        "schema_pass": validation.schema_pass,
        "business_pass": validation.business_pass,
        "ids_exact_pass": validation.ids_exact_pass,
        "reasoning_leak": validation.reasoning_leak,
        "error_category": validation.error_category,
        "validation": validation_payload,
    }


def _aggregate_model_summary(
    run_id: str, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_model: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        by_model[str(record["model_key"])].append(record)
    rows: list[dict[str, Any]] = []
    for model_key, model_records in sorted(by_model.items()):
        pass_count = sum(record.get("business_pass") is True for record in model_records)
        total = len(model_records)
        rows.append(
            {
                "run_id": run_id,
                "model_key": model_key,
                "planned_cells": total,
                "completed_cells": total,
                "business_pass_count": pass_count,
                "business_pass_rate": pass_count / total if total else None,
            }
        )
    return rows


def _aggregate_failure_summary(
    run_id: str, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        category = str(record.get("error_category") or "none")
        if category == "none":
            continue
        by_category[category][str(record["model_key"])] += 1
    return [
        {
            "run_id": run_id,
            "failure_category": category,
            "affected_models": ";".join(sorted(counter)),
            "count": sum(counter.values()),
        }
        for category, counter in sorted(by_category.items())
    ]


def _aggregate_retry_summary(
    run_id: str, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_policy: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        by_policy[str(record["retry_policy"])].append(record)
    return [
        {
            "run_id": run_id,
            "retry_policy": retry_policy,
            "attempt_count": len(policy_records),
            "business_pass_count": sum(
                record.get("business_pass") is True for record in policy_records
            ),
            "recovery_rate": None if retry_policy == "off" else 0.0,
        }
        for retry_policy, policy_records in sorted(by_policy.items())
    ]


def _aggregate_resource_summary(
    run_id: str, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        key = (str(record["model_key"]), str(record["context_tier"]))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "run_id": run_id,
                "model_key": key[0],
                "context_tier": key[1],
                "estimated_input_tokens": record.get("estimated_input_tokens"),
                "actual_input_tokens": record.get("actual_input_tokens"),
                "estimated_output_tokens": record.get("estimated_output_tokens"),
                "actual_output_tokens": record.get("actual_output_tokens"),
                "latency_ms": record.get("latency_ms"),
            }
        )
    return rows


def create_structured_matrix_fake_run_artifacts(
    config_path: str | Path,
    *,
    output_root: str | Path,
    run_id: str | None = None,
) -> Path:
    config_bytes, _, _ = _load_config_and_axes(config_path)
    plan = build_structured_matrix_plan(
        config_path,
        run_id=run_id
        or _default_run_id(load_experiment_config(config_path).experiment_id, fake_run=True),
    )
    run_dir = _prepare_run_dir(
        output_root=Path(output_root),
        run_id=plan.run_id,
        experiment_id=plan.config.experiment_id,
    )
    (run_dir / "experiment.yaml").write_bytes(config_bytes)
    planner_summary = {**plan.planner_summary(), "fake_runner": True}
    write_json_file(run_dir / "planner_summary.json", planner_summary)

    manifests = {
        dataset_id: load_dataset_manifest(dataset_id) for dataset_id in plan.config.datasets
    }
    records: list[dict[str, Any]] = []
    results_path = run_dir / "cell_results.jsonl"
    results_path.write_text("", encoding="utf-8")
    for cell in plan.cells:
        manifest = manifests[str(cell["dataset_id"])]
        fake_output = _fake_response_for_cell(cell, _expected_ids_for_dataset(manifest))
        result = _build_fake_result_record(cell=cell, manifest=manifest, fake_output=fake_output)
        records.append(result)
        append_jsonl_record(results_path, result)

    write_csv_file(
        run_dir / "cell_summary.csv",
        fieldnames=MATRIX_CELL_FIELDNAMES,
        rows=[_cell_summary_row(record, status="completed", result=record) for record in records],
    )
    model_rows = _aggregate_model_summary(plan.run_id, records)
    failure_rows = _aggregate_failure_summary(plan.run_id, records)
    retry_rows = _aggregate_retry_summary(plan.run_id, records)
    resource_rows = _aggregate_resource_summary(plan.run_id, records)
    write_csv_file(
        run_dir / "model_summary.csv", fieldnames=MODEL_SUMMARY_FIELDNAMES, rows=model_rows
    )
    write_csv_file(
        run_dir / "failure_summary.csv",
        fieldnames=FAILURE_SUMMARY_FIELDNAMES,
        rows=failure_rows,
    )
    write_csv_file(
        run_dir / "retry_summary.csv", fieldnames=RETRY_SUMMARY_FIELDNAMES, rows=retry_rows
    )
    write_csv_file(
        run_dir / "resource_summary.csv",
        fieldnames=RESOURCE_SUMMARY_FIELDNAMES,
        rows=resource_rows,
    )
    privacy_scan = _scan_privacy_payloads(
        [planner_summary, *records, *model_rows, *failure_rows, *retry_rows, *resource_rows],
        artifact_names=MATRIX_FAKE_RUN_OUTPUT_FILE_NAMES,
    )
    write_json_file(run_dir / "privacy_scan.json", privacy_scan)
    business_pass_count = sum(record.get("business_pass") is True for record in records)
    result_summary = {
        "completed_cells": len(records),
        "business_pass_count": business_pass_count,
        "failure_count": len(records) - business_pass_count,
    }
    (run_dir / "report.md").write_text(
        _render_matrix_report(
            title="# LM Studio Lab Structured Matrix Fake Run",
            plan=plan,
            status="completed",
            output_files=MATRIX_FAKE_RUN_OUTPUT_FILE_NAMES,
            result_summary=result_summary,
        ),
        encoding="utf-8",
    )
    return run_dir


__all__ = [
    "MEMORY_MATRIX_CONTEXT_TIERS",
    "MEMORY_MATRIX_LANES",
    "MEMORY_MATRIX_SCHEMA_REVISION",
    "MATRIX_CELL_FIELDNAMES",
    "MATRIX_FAKE_RUN_OUTPUT_FILE_NAMES",
    "MATRIX_PLAN_OUTPUT_FILE_NAMES",
    "MemoryConcurrencyPlan",
    "MemoryMatrixAttemptReservation",
    "MemoryMatrixAttemptResult",
    "MemoryMatrixAttemptStore",
    "MemoryMatrixCandidate",
    "MemoryMatrixCell",
    "MemoryMatrixWorkload",
    "RequestInterval",
    "StructuredMatrixPlan",
    "aggregate_memory_recommendations",
    "build_memory_concurrency_plan",
    "build_structured_matrix_plan",
    "create_structured_matrix_fake_run_artifacts",
    "create_structured_matrix_plan_artifacts",
    "execute_memory_matrix_attempt",
]
