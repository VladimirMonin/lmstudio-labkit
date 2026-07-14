"""Fail-closed controller contract for the bounded Qwen 3.5 full-GPU matrix."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from .strict_vision import validate_strict_vision_grounding
from .validation import validate_json_schema, validate_no_reasoning_leak


class Qwen35MatrixError(RuntimeError):
    """Raised when the frozen matrix or its runtime safety contract is violated."""


_IDENTITY_FIELDS = (
    "key",
    "type",
    "publisher",
    "architecture",
    "format",
    "params_string",
    "quantization",
    "size_bytes",
    "max_context_length",
    "capabilities",
    "selected_variant",
    "variants",
)
_ALLOWED_CONDITIONS = {"base_full_gpu", "context_16k_full_gpu", "parallel2_full_gpu"}
_EXPECTED_MODELS = ("qwen/qwen3.5-4b", "qwen3.5-9b-mtp")


class Qwen35FullGPUHost(Protocol):
    """Host seam; implementations must not silently lower the requested GPU ratio."""

    def model_metadata(self, *, model_id: str) -> Mapping[str, object] | None: ...

    def count_all_loaded_instances(self) -> int | None: ...

    def observe_global_zero(
        self, *, phase: str, model_id: str | None, load_group: str | None
    ) -> Mapping[str, object]: ...

    def load_model_full_gpu(
        self,
        *,
        model_id: str,
        context_length: int,
        parallel: int,
        gpu: Literal["max"],
        echo_load_config: bool,
    ) -> object: ...

    def materialized_model_metadata(self, *, model_id: str) -> Mapping[str, object] | None: ...

    def gpu_observation(self, *, model_id: str) -> Mapping[str, object] | None: ...

    def execute_matrix_row(
        self, *, row: Mapping[str, object], timeout_s: float
    ) -> Mapping[str, object]: ...

    def cleanup_model(self, *, model_id: str) -> object: ...


@dataclass(frozen=True, slots=True)
class Qwen35MatrixRow:
    ordinal: int
    row_id: str
    model_id: str
    lane: str
    load_group: str
    request_kind: str
    context_length: int
    parallel: int
    reasoning: Literal["off", "on", "omitted"]
    condition: str
    fixture_id: str | None
    schema_name: str | None
    source_binding: str
    repeat_of: str | None
    row_sha256: str

    def binding(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "row_id": self.row_id,
            "model_id": self.model_id,
            "lane": self.lane,
            "load_group": self.load_group,
            "request_kind": self.request_kind,
            "context_length": self.context_length,
            "parallel": self.parallel,
            "reasoning": self.reasoning,
            "condition": self.condition,
            "fixture_id": self.fixture_id,
            "schema_name": self.schema_name,
            "source_binding": self.source_binding,
            "repeat_of": self.repeat_of,
        }


@dataclass(frozen=True, slots=True)
class Qwen35ModelPin:
    model_id: str
    identity_sha256: str
    identity_snapshot: Mapping[str, object]
    reasoning_modes: tuple[str, ...]
    variant_identity: Mapping[str, object]
    artifact_identity: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Qwen35ArtifactFilePin:
    path: Path
    path_sha256: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Qwen35ArtifactExecutionPin:
    model_id: str
    variant: str
    files: tuple[Qwen35ArtifactFilePin, ...]
    pin_sha256: str


def _canonical_artifact_execution_pin(value: object) -> Mapping[str, object] | None:
    """Validate an execution pin without depending on its defining module identity."""

    model_id = getattr(value, "model_id", None)
    variant = getattr(value, "variant", None)
    files = getattr(value, "files", None)
    pin_sha256 = getattr(value, "pin_sha256", None)
    if (
        not isinstance(model_id, str)
        or not model_id
        or not isinstance(variant, str)
        or not variant
        or not isinstance(files, tuple)
        or not files
        or not _is_sha256(pin_sha256)
    ):
        return None
    canonical_files: list[dict[str, object]] = []
    for file_pin in files:
        path = getattr(file_pin, "path", None)
        path_sha256 = getattr(file_pin, "path_sha256", None)
        size_bytes = getattr(file_pin, "size_bytes", None)
        sha256 = getattr(file_pin, "sha256", None)
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path != path.resolve()
            or not _is_sha256(path_sha256)
            or not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes <= 0
            or not _is_sha256(sha256)
        ):
            return None
        canonical_files.append(
            {
                "path": str(path),
                "path_sha256": path_sha256,
                "size_bytes": size_bytes,
                "sha256": sha256,
            }
        )
    unsigned = {"model_id": model_id, "variant": variant, "files": canonical_files}
    if _canonical_sha256(unsigned) != pin_sha256:
        return None
    return {**unsigned, "pin_sha256": pin_sha256}


@dataclass(frozen=True, slots=True)
class Qwen35MatrixManifest:
    manifest_sha256: str
    source_path: Path
    repo_root: Path
    max_inference_calls: int
    models: tuple[Qwen35ModelPin, ...]
    rows: tuple[Qwen35MatrixRow, ...]
    production_binding: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Qwen35RowResult:
    row_id: str
    status: Literal["executed", "stop_gated", "resumed"]
    inference_call_index: int | None
    accepted: bool | None
    reason: str | None
    capture_sha256: str | None


@dataclass(frozen=True, slots=True)
class Qwen35MatrixResult:
    manifest_sha256: str
    rows: tuple[Qwen35RowResult, ...]
    cumulative_inference_calls: int
    final_loaded_global_count: int


def load_qwen35_full_gpu_manifest(
    path: Path, *, expected_sha256: str, repo_root: Path
) -> Qwen35MatrixManifest:
    """Load the exact serial matrix and verify all reusable source bindings."""

    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if not _is_sha256(expected_sha256) or actual != expected_sha256:
        raise Qwen35MatrixError("Qwen manifest digest pin mismatch")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise Qwen35MatrixError("Qwen manifest is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise Qwen35MatrixError("Qwen manifest must be an object")
    if (
        payload.get("manifest_version") != 1
        or payload.get("name") != "qwen35_full_gpu_matrix_v1"
        or payload.get("serial") is not True
        or payload.get("retry_policy") != "off"
    ):
        raise Qwen35MatrixError("Qwen manifest execution controls are invalid")
    maximum = payload.get("max_inference_calls")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 80:
        raise Qwen35MatrixError("Qwen manifest call ceiling must be in 1..80")

    root = repo_root.resolve()
    _validate_reuse_bindings(payload.get("reuse_bindings"), repo_root=root)
    models = _load_models(payload.get("models"))
    rows = _load_rows(payload.get("rows"))
    if len(rows) != 66 or maximum != 68:
        raise Qwen35MatrixError("Qwen manifest exact 66-row/68-call schedule is invalid")
    _validate_schedule(rows, models=models)
    _validate_contract_sections(payload)
    production_binding = _validate_production_binding(payload.get("production_binding"))
    return Qwen35MatrixManifest(
        manifest_sha256=actual,
        source_path=path.resolve(),
        repo_root=root,
        max_inference_calls=maximum,
        models=models,
        rows=rows,
        production_binding=production_binding,
    )


def load_qwen35_artifact_execution_pins(
    path: Path,
    *,
    expected_sha256: str,
    manifest: Qwen35MatrixManifest,
) -> Mapping[str, Qwen35ArtifactExecutionPin]:
    """Load an externally frozen owner-only path/size/digest execution pin set."""

    resolved_pin_path = path.resolve()
    if (
        not resolved_pin_path.is_file()
        or resolved_pin_path == manifest.repo_root
        or resolved_pin_path.is_relative_to(manifest.repo_root)
        or os.stat(resolved_pin_path).st_mode & 0o777 != 0o600
    ):
        raise Qwen35MatrixError("Qwen artifact pin manifest must be owner-only outside the repo")
    raw = resolved_pin_path.read_bytes()
    if not _is_sha256(expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Qwen35MatrixError("Qwen artifact pin manifest digest mismatch")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise Qwen35MatrixError("Qwen artifact pin manifest is not valid JSON") from error
    if (
        not isinstance(payload, Mapping)
        or payload.get("manifest_sha256") != manifest.manifest_sha256
    ):
        raise Qwen35MatrixError("Qwen artifact pins are not bound to the launch manifest")
    models = payload.get("models")
    if not isinstance(models, list) or len(models) > len(manifest.models):
        raise Qwen35MatrixError("Qwen artifact pin manifest model set is invalid")
    loaded: dict[str, Qwen35ArtifactExecutionPin] = {}
    for item in models:
        if not isinstance(item, Mapping):
            raise Qwen35MatrixError("Qwen artifact execution pin is invalid")
        model_id = item.get("model_id")
        variant = item.get("variant")
        files = item.get("files")
        pin_sha256 = item.get("pin_sha256")
        unsigned = {key: value for key, value in item.items() if key != "pin_sha256"}
        if (
            not isinstance(model_id, str)
            or not isinstance(variant, str)
            or not isinstance(files, list)
            or not files
            or not _is_sha256(pin_sha256)
            or _canonical_sha256(unsigned) != pin_sha256
            or model_id in loaded
        ):
            raise Qwen35MatrixError("Qwen artifact execution pin binding is invalid")
        model_pin = next((pin for pin in manifest.models if pin.model_id == model_id), None)
        if model_pin is None:
            raise Qwen35MatrixError("Qwen artifact pin contains an unknown model")
        expected_variant = model_pin.variant_identity.get("selected_variant") or model_id
        expected_names = model_pin.artifact_identity.get("required_file_names")
        if variant != expected_variant or not isinstance(expected_names, list):
            raise Qwen35MatrixError("Qwen artifact variant pin mismatch")
        file_pins: list[Qwen35ArtifactFilePin] = []
        for file_item in files:
            if not isinstance(file_item, Mapping):
                raise Qwen35MatrixError("Qwen artifact file pin is invalid")
            raw_path = file_item.get("path")
            size = file_item.get("size_bytes")
            digest = file_item.get("sha256")
            path_digest = file_item.get("path_sha256")
            if (
                not isinstance(raw_path, str)
                or not Path(raw_path).is_absolute()
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size <= 0
                or not _is_sha256(digest)
                or not _is_sha256(path_digest)
            ):
                raise Qwen35MatrixError("Qwen artifact file pin fields are invalid")
            artifact_path = Path(raw_path).resolve()
            if hashlib.sha256(os.fsencode(artifact_path)).hexdigest() != path_digest:
                raise Qwen35MatrixError("Qwen artifact path digest mismatch")
            if not artifact_path.is_file() or artifact_path.stat().st_size != size:
                raise Qwen35MatrixError("Qwen artifact path or size pin mismatch")
            file_digest = hashlib.sha256()
            with artifact_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    file_digest.update(chunk)
            if file_digest.hexdigest() != digest:
                raise Qwen35MatrixError("Qwen artifact file digest mismatch")
            file_pins.append(
                Qwen35ArtifactFilePin(artifact_path, str(path_digest), size, str(digest))
            )
        if [file_pin.path.name for file_pin in file_pins] != expected_names:
            raise Qwen35MatrixError("Qwen artifact file set was substituted or reordered")
        loaded[model_id] = Qwen35ArtifactExecutionPin(
            model_id, variant, tuple(file_pins), str(pin_sha256)
        )
    expected_order = tuple(pin.model_id for pin in manifest.models if pin.model_id in loaded)
    if tuple(loaded) != expected_order:
        raise Qwen35MatrixError("Qwen artifact model order was substituted")
    return loaded


def write_qwen35_artifact_execution_pins(
    path: Path,
    *,
    manifest: Qwen35MatrixManifest,
    artifact_paths: Mapping[str, Sequence[Path]],
) -> str:
    """Create and re-validate an owner-only pin bound to the exact manifest."""

    resolved = path.resolve()
    parent = resolved.parent
    if (
        resolved == manifest.repo_root
        or resolved.is_relative_to(manifest.repo_root)
        or not parent.is_dir()
        or os.stat(parent).st_mode & 0o777 != 0o700
    ):
        raise Qwen35MatrixError(
            "Qwen artifact pin output requires an existing owner-only directory outside the repo"
        )
    expected_order = tuple(
        pin.model_id for pin in manifest.models if pin.model_id in artifact_paths
    )
    if tuple(artifact_paths) != expected_order or not artifact_paths:
        raise Qwen35MatrixError("Qwen artifact pin generation model order is invalid")
    models: list[dict[str, object]] = []
    for model_id, supplied_paths in artifact_paths.items():
        model_pin = next(pin for pin in manifest.models if pin.model_id == model_id)
        expected_names = model_pin.artifact_identity.get("required_file_names")
        paths = tuple(item.resolve() for item in supplied_paths)
        if (
            not isinstance(expected_names, list)
            or [item.name for item in paths] != expected_names
            or any(not item.is_file() for item in paths)
        ):
            raise Qwen35MatrixError("Qwen artifact pin generation file set is invalid")
        files = []
        for artifact_path in paths:
            file_digest = hashlib.sha256()
            with artifact_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    file_digest.update(chunk)
            files.append(
                {
                    "path": str(artifact_path),
                    "path_sha256": hashlib.sha256(os.fsencode(artifact_path)).hexdigest(),
                    "size_bytes": artifact_path.stat().st_size,
                    "sha256": file_digest.hexdigest(),
                }
            )
        unsigned = {
            "model_id": model_id,
            "variant": model_pin.variant_identity.get("selected_variant") or model_id,
            "files": files,
        }
        models.append({**unsigned, "pin_sha256": _canonical_sha256(unsigned)})
    raw = (
        _canonical_json({"manifest_sha256": manifest.manifest_sha256, "models": models}) + "\n"
    ).encode()
    try:
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise Qwen35MatrixError("Qwen artifact pin output already exists") from error
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(resolved, 0o600)
    digest = hashlib.sha256(raw).hexdigest()
    load_qwen35_artifact_execution_pins(resolved, expected_sha256=digest, manifest=manifest)
    return digest


def load_qwen35_adjudication_ledger(
    path: Path,
    *,
    manifest: Qwen35MatrixManifest,
    private_root: Path,
) -> Mapping[str, Mapping[str, object]]:
    """Read append-only post-execution review records bound to private captures."""

    resolved = path.resolve()
    root = private_root.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise Qwen35MatrixError("Qwen adjudication ledger must be inside owner-only capture")
    if os.stat(resolved).st_mode & 0o777 != 0o600:
        raise Qwen35MatrixError("Qwen adjudication ledger mode must be 0600")
    rows = {row.row_id: row for row in manifest.rows}
    records: dict[str, Mapping[str, object]] = {}
    for line in resolved.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise Qwen35MatrixError("Qwen adjudication ledger is malformed") from error
        row_id = record.get("row_id") if isinstance(record, Mapping) else None
        row = rows.get(row_id) if isinstance(row_id, str) else None
        if (
            row is None
            or row_id in records
            or record.get("manifest_sha256") != manifest.manifest_sha256
            or record.get("row_sha256") != row.row_sha256
            or not _is_sha256(record.get("capture_sha256"))
            or not isinstance(record.get("semantic_pass"), bool)
            or not isinstance(record.get("reason_code"), str)
            or not record.get("reason_code")
        ):
            raise Qwen35MatrixError("Qwen adjudication record binding is invalid")
        capture = root / f"call-{row.ordinal:02d}-{row.row_id}.json"
        if not capture.is_file() or hashlib.sha256(capture.read_bytes()).hexdigest() != record.get(
            "capture_sha256"
        ):
            raise Qwen35MatrixError("Qwen adjudication capture digest mismatch")
        expected_dimension = (
            "vision_pixel_content_fidelity"
            if row.lane == "strict_structured_vision"
            else "structured_text_content_fidelity"
            if row.lane == "structured_text"
            else None
        )
        if record.get("dimension") != expected_dimension:
            raise Qwen35MatrixError("Qwen adjudication dimension is invalid for the row")
        assert isinstance(row_id, str)
        records[row_id] = record
    return records


def _load_models(value: object) -> tuple[Qwen35ModelPin, ...]:
    if not isinstance(value, list) or len(value) != 2:
        raise Qwen35MatrixError("Qwen manifest requires two exact model pins")
    pins: list[Qwen35ModelPin] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise Qwen35MatrixError("Qwen model pin is invalid")
        model_id = item.get("model_id")
        digest = item.get("identity_sha256")
        snapshot = item.get("identity_snapshot")
        control = item.get("reasoning_control")
        variant_identity = item.get("variant_identity")
        artifact_identity = item.get("artifact_identity")
        if (
            not isinstance(model_id, str)
            or not _is_sha256(digest)
            or not isinstance(snapshot, Mapping)
            or not isinstance(control, Mapping)
            or not isinstance(variant_identity, Mapping)
            or not isinstance(artifact_identity, Mapping)
        ):
            raise Qwen35MatrixError("Qwen model identity pin is invalid")
        if snapshot.get("key") != model_id or _canonical_sha256(snapshot) != digest:
            raise Qwen35MatrixError("Qwen model identity snapshot digest mismatch")
        modes = control.get("measured_modes")
        if not isinstance(modes, list) or any(
            mode not in {"off", "on", "omitted"} for mode in modes
        ):
            raise Qwen35MatrixError("Qwen reasoning control pin is invalid")
        _validate_execution_identity(
            snapshot=snapshot,
            variant_identity=variant_identity,
            artifact_identity=artifact_identity,
        )
        pins.append(
            Qwen35ModelPin(
                model_id,
                str(digest),
                dict(snapshot),
                tuple(modes),
                dict(variant_identity),
                dict(artifact_identity),
            )
        )
    if tuple(pin.model_id for pin in pins) != _EXPECTED_MODELS:
        raise Qwen35MatrixError("Qwen model order or identity was substituted")
    if pins[0].reasoning_modes != ("off", "on") or pins[1].reasoning_modes != ("omitted",):
        raise Qwen35MatrixError("Qwen exact reasoning matrix is invalid")
    return tuple(pins)


def _load_rows(value: object) -> tuple[Qwen35MatrixRow, ...]:
    if not isinstance(value, list):
        raise Qwen35MatrixError("Qwen manifest rows are invalid")
    rows: list[Qwen35MatrixRow] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise Qwen35MatrixError("Qwen manifest row is invalid")
        unsigned = {key: item.get(key) for key in item if key != "row_sha256"}
        digest = item.get("row_sha256")
        if not _is_sha256(digest) or _canonical_sha256(unsigned) != digest:
            raise Qwen35MatrixError("Qwen row digest mismatch")
        try:
            row = Qwen35MatrixRow(
                ordinal=_strict_int(item.get("ordinal")),
                row_id=_strict_str(item.get("row_id")),
                model_id=_strict_str(item.get("model_id")),
                lane=_strict_str(item.get("lane")),
                load_group=_strict_str(item.get("load_group")),
                request_kind=_strict_str(item.get("request_kind")),
                context_length=_strict_int(item.get("context_length")),
                parallel=_strict_int(item.get("parallel")),
                reasoning=_reasoning(item.get("reasoning")),
                condition=_strict_str(item.get("condition")),
                fixture_id=_optional_str(item.get("fixture_id")),
                schema_name=_optional_str(item.get("schema_name")),
                source_binding=_strict_str(item.get("source_binding")),
                repeat_of=_optional_str(item.get("repeat_of")),
                row_sha256=str(digest),
            )
        except (TypeError, ValueError) as error:
            raise Qwen35MatrixError("Qwen manifest row fields are invalid") from error
        rows.append(row)
    return tuple(rows)


def _validate_schedule(
    rows: tuple[Qwen35MatrixRow, ...], *, models: tuple[Qwen35ModelPin, ...]
) -> None:
    if [row.ordinal for row in rows] != list(range(1, 67)):
        raise Qwen35MatrixError("Qwen serial row order is invalid")
    if [row.row_id for row in rows] != [f"q35-{index:02d}" for index in range(1, 67)]:
        raise Qwen35MatrixError("Qwen row ids are invalid")
    if len({row.row_id for row in rows}) != len(rows):
        raise Qwen35MatrixError("Qwen row ids are not unique")
    counts = {pin.model_id: sum(row.model_id == pin.model_id for row in rows) for pin in models}
    if counts != {models[0].model_id: 36, models[1].model_id: 30}:
        raise Qwen35MatrixError("Qwen per-model call denominators are invalid")
    lane_counts = {
        lane: sum(row.lane == lane for row in rows)
        for lane in {
            "lifecycle_strict_canary",
            "structured_text",
            "context_cache",
            "concurrency",
            "strict_structured_vision",
        }
    }
    if lane_counts != {
        "lifecycle_strict_canary": 2,
        "structured_text": 18,
        "context_cache": 16,
        "concurrency": 4,
        "strict_structured_vision": 26,
    }:
        raise Qwen35MatrixError("Qwen lane denominators are invalid")
    row_ids = {row.row_id for row in rows}
    for row in rows:
        if row.model_id not in _EXPECTED_MODELS or row.condition not in _ALLOWED_CONDITIONS:
            raise Qwen35MatrixError("Qwen row model or stop gate is invalid")
        if row.context_length not in {8192, 16384} or row.parallel not in {1, 2}:
            raise Qwen35MatrixError("Qwen row runtime shape is invalid")
        if row.context_length == 16384 and row.condition != "context_16k_full_gpu":
            raise Qwen35MatrixError("Qwen 16k row is not stop-gated")
        if row.parallel == 2 and row.condition != "parallel2_full_gpu":
            raise Qwen35MatrixError("Qwen parallel=2 row is not stop-gated")
        if row.repeat_of is not None and row.repeat_of not in row_ids:
            raise Qwen35MatrixError("Qwen repeat row reference is invalid")
    if any(row.reasoning == "on" and row.model_id != models[0].model_id for row in rows):
        raise Qwen35MatrixError("Qwen unadvertised reasoning control was scheduled")


def _validate_reuse_bindings(value: object, *, repo_root: Path) -> None:
    if not isinstance(value, Mapping) or len(value) != 9:
        raise Qwen35MatrixError("Qwen reusable runner inventory is incomplete")
    for item in value.values():
        if not isinstance(item, Mapping):
            raise Qwen35MatrixError("Qwen reusable runner binding is invalid")
        relative = item.get("path")
        digest = item.get("sha256")
        if not isinstance(relative, str) or Path(relative).is_absolute() or not _is_sha256(digest):
            raise Qwen35MatrixError("Qwen reusable runner binding fields are invalid")
        source = (repo_root / relative).resolve()
        if (
            not source.is_relative_to(repo_root)
            or hashlib.sha256(source.read_bytes()).hexdigest() != digest
        ):
            raise Qwen35MatrixError("Qwen reusable runner binding digest mismatch")


def _validate_contract_sections(payload: Mapping[str, object]) -> None:
    full_gpu = payload.get("full_gpu_contract")
    resume = payload.get("resume_contract")
    capture = payload.get("capture_contract")
    fixtures = payload.get("vision_fixtures")
    if not isinstance(full_gpu, Mapping) or not isinstance(full_gpu.get("load_request"), Mapping):
        raise Qwen35MatrixError("Qwen full-GPU contract is missing")
    load = full_gpu["load_request"]
    assert isinstance(load, Mapping)
    if (
        load.get("transport") != "lms load --gpu max"
        or load.get("gpu") != "max"
        or load.get("gpu_ratio_equivalent") != 1.0
        or full_gpu.get("artifact_attestation_scope") != "per_model_fail_closed"
    ):
        raise Qwen35MatrixError("Qwen full-GPU load request is not fail-closed")
    if full_gpu.get("partial_gpu_fallback") != "forbidden":
        raise Qwen35MatrixError("Qwen partial GPU fallback must be forbidden")
    if not isinstance(resume, Mapping) or resume.get("resume_only_missing_rows") is not True:
        raise Qwen35MatrixError("Qwen resume contract is missing")
    if not isinstance(capture, Mapping) or capture.get("inside_repository_forbidden") is not True:
        raise Qwen35MatrixError("Qwen owner-only capture contract is missing")
    if not isinstance(fixtures, list) or len(fixtures) != 4:
        raise Qwen35MatrixError("Qwen exact vision fixture set is invalid")
    if (
        resume.get("validate_row_sha256") is not True
        or resume.get("validate_capture_sha256") is not True
        or resume.get("reconstruct_base_stop_gates") is not True
        or resume.get("require_contiguous_manifest_prefix") is not True
        or resume.get("stateful_partial_group_action") != "stop_gate_remaining_group_without_replay"
    ):
        raise Qwen35MatrixError("Qwen resume evidence reconstruction contract is missing")
    if (
        capture.get("reserve_actual_attempt_before_send") is not True
        or capture.get("capture_transport_and_partial_parallel_failures") is not True
        or capture.get("capture_exact_lifecycle_invocation_response") is not True
        or capture.get("capture_initial_and_final_lms_ps_api_zero") is not True
        or capture.get("capture_pre_inference_materialization_attestation") is not True
        or capture.get("capture_authoritative_sdk_instance_reference") is not True
        or capture.get("start_process_monitor_before_materialization") is not True
        or capture.get("explicit_negative_capability_unavailable_fails_closed") is not True
    ):
        raise Qwen35MatrixError("Qwen durable HTTP attempt capture contract is missing")


def _validate_production_binding(value: object) -> Mapping[str, object]:
    expected = {
        "entrypoint": "python -m lmstudio_labkit.qwen35_full_gpu run",
        "host": "lmstudio_labkit.qwen35_full_gpu_host.LocalQwen35FullGPUHost",
        "transport": "installed_lms_cli_sdk_instance_runtime_log_proc_v9",
        "parallel_pair_actual_calls": 2,
    }
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise Qwen35MatrixError("Qwen production host and entrypoint binding is invalid")
    return dict(value)


def _validate_execution_identity(
    *,
    snapshot: Mapping[str, object],
    variant_identity: Mapping[str, object],
    artifact_identity: Mapping[str, object],
) -> None:
    variant_status = variant_identity.get("status")
    selected_variant = variant_identity.get("selected_variant")
    if variant_status == "pinned":
        if not isinstance(selected_variant, str) or selected_variant != snapshot.get(
            "selected_variant"
        ):
            raise Qwen35MatrixError("Qwen pinned variant identity is invalid")
    elif variant_status == "unavailable_fail_closed":
        if selected_variant is not None or not isinstance(variant_identity.get("evidence"), str):
            raise Qwen35MatrixError("Qwen unavailable variant evidence is invalid")
    else:
        raise Qwen35MatrixError("Qwen variant identity status is invalid")
    artifact_status = artifact_identity.get("status")
    required_names = artifact_identity.get("required_file_names")
    if (
        artifact_status != "external_owner_pin_required"
        or not isinstance(required_names, list)
        or not required_names
        or any(not isinstance(name, str) or not name for name in required_names)
    ):
        raise Qwen35MatrixError("Qwen artifact identity status is invalid")


@dataclass(slots=True)
class Qwen35FullGPUController:
    manifest: Qwen35MatrixManifest
    host: Qwen35FullGPUHost
    private_root: Path
    artifact_pins: Mapping[str, Qwen35ArtifactExecutionPin] = field(default_factory=dict)
    allow_model_loads: bool = False
    timeout_s: float = 120.0
    adjudications: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    def run(self) -> Qwen35MatrixResult:
        verified = load_qwen35_full_gpu_manifest(
            self.manifest.source_path,
            expected_sha256=self.manifest.manifest_sha256,
            repo_root=self.manifest.repo_root,
        )
        if verified != self.manifest:
            raise Qwen35MatrixError("Qwen manifest snapshot was substituted")
        if not self.allow_model_loads:
            raise Qwen35MatrixError("Qwen model loads require allow_model_loads=true")
        expected_pin_order = tuple(
            pin.model_id for pin in self.manifest.models if pin.model_id in self.artifact_pins
        )
        if tuple(self.artifact_pins) != expected_pin_order:
            raise Qwen35MatrixError("Qwen externally frozen artifact pin order is invalid")
        self._prepare_private_root()
        lock_path = self.private_root / "qwen35-full-gpu.lock"
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise Qwen35MatrixError("Qwen matrix already has an active exclusive lock") from error
        os.close(descriptor)
        ledger_path = self.private_root / "qwen35-full-gpu-progress.jsonl"
        try:
            previous = self._read_progress(ledger_path)
            previous = self._reconcile_orphan_attempts(ledger_path, previous)
            return self._run_locked(ledger_path, previous)
        finally:
            lock_path.unlink(missing_ok=True)

    def _run_locked(
        self, ledger_path: Path, previous: Mapping[str, Mapping[str, object]]
    ) -> Qwen35MatrixResult:
        results: list[Qwen35RowResult] = []
        inference_count = sum(
            _strict_int(item.get("actual_inference_calls", 0))
            for item in previous.values()
            if item.get("status") == "executed"
        )
        base_failed_models = {
            row.model_id
            for row in self.manifest.rows
            if (
                (prior := previous.get(row.row_id)) is not None
                and row.condition == "base_full_gpu"
                and prior.get("status") == "stop_gated"
                and prior.get("reason")
                in {"full_gpu_materialization_not_proven", "execution_identity_unavailable"}
            )
        }
        rows_by_group = _contiguous_groups(self.manifest.rows)
        for group in rows_by_group:
            pending = [row for row in group if row.row_id not in previous]
            for row in group:
                prior = previous.get(row.row_id)
                if prior is not None:
                    results.append(self._resumed_result(row, prior))
            if not pending:
                continue
            if group[0].lane == "context_cache" and len(pending) != len(group):
                for row in pending:
                    result = self._stop_gate(row, "stateful_group_resume_not_reconstructable")
                    results.append(result)
                    self._append_progress(ledger_path, row, result)
                continue
            model_id = group[0].model_id
            if model_id not in self.artifact_pins:
                base_failed_models.add(model_id)
                for row in pending:
                    result = self._stop_gate(row, "execution_identity_unavailable")
                    results.append(result)
                    self._append_progress(ledger_path, row, result)
                continue
            if model_id in base_failed_models:
                for row in pending:
                    result = self._stop_gate(row, "base_full_gpu_not_proven")
                    results.append(result)
                    self._append_progress(ledger_path, row, result)
                continue
            pin = next(pin for pin in self.manifest.models if pin.model_id == model_id)
            self._validate_live_identity(pin)
            initial_zero = self.host.observe_global_zero(
                phase="initial", model_id=model_id, load_group=group[0].load_group
            )
            self._write_group_capture(
                f"zero-initial-{group[0].ordinal:02d}-{group[0].load_group}.json",
                initial_zero,
            )
            if not _global_zero_verified(initial_zero):
                raise Qwen35MatrixError("Qwen load group requires verified global zero")
            load_attempted = False
            cleanup: object = {"cleanup_verified": False}
            group_verified = False
            group_capture: dict[str, object] = {}
            try:
                load_attempted = True
                load_response = self.host.load_model_full_gpu(
                    model_id=model_id,
                    context_length=group[0].context_length,
                    parallel=group[0].parallel,
                    gpu="max",
                    echo_load_config=True,
                )
                materialized = self.host.materialized_model_metadata(model_id=model_id)
                gpu = self.host.gpu_observation(model_id=model_id)
                global_loaded_count = self.host.count_all_loaded_instances()
                group_capture = {
                    "manifest_sha256": self.manifest.manifest_sha256,
                    "model_id": model_id,
                    "load_group": group[0].load_group,
                    "load_response": load_response,
                    "materialized_model": materialized,
                    "gpu_observation": gpu,
                    "global_loaded_count": global_loaded_count,
                }
                self._write_group_capture(
                    f"load-{group[0].ordinal:02d}-{group[0].load_group}.json", group_capture
                )
                attestation = _materialization_attestation(
                    load_response,
                    materialized,
                    gpu,
                    global_loaded_count=global_loaded_count,
                    model_id=model_id,
                    context_length=group[0].context_length,
                    parallel=group[0].parallel,
                )
                self._write_group_capture(
                    f"attestation-{group[0].ordinal:02d}-{group[0].load_group}.json",
                    attestation,
                )
                group_verified = attestation["verified"] is True
                if group_verified:
                    for row in pending:
                        expected_calls = 2 if row.request_kind == "parallel_pair" else 1
                        if inference_count + expected_calls > self.manifest.max_inference_calls:
                            raise Qwen35MatrixError("Qwen inference call ceiling exceeded")
                        result, actual_calls = self._execute_row(
                            row, inference_call_index=inference_count + 1
                        )
                        inference_count += actual_calls
                        results.append(result)
                        self._append_progress(
                            ledger_path,
                            row,
                            result,
                            actual_inference_calls=actual_calls,
                        )
                else:
                    if group[0].condition == "base_full_gpu":
                        base_failed_models.add(model_id)
                    for row in pending:
                        result = self._stop_gate(row, "full_gpu_materialization_not_proven")
                        results.append(result)
                        self._append_progress(ledger_path, row, result)
            finally:
                if load_attempted:
                    cleanup = self.host.cleanup_model(model_id=model_id)
                    final_zero = self.host.observe_global_zero(
                        phase="final", model_id=model_id, load_group=group[0].load_group
                    )
                    self._write_group_capture(
                        f"zero-final-{group[0].ordinal:02d}-{group[0].load_group}.json",
                        final_zero,
                    )
                    if not _cleanup_verified(cleanup) or not _global_zero_verified(final_zero):
                        raise Qwen35MatrixError("Qwen cleanup or global-zero verification failed")
            del group_verified, group_capture, cleanup
        matrix_final = self.host.observe_global_zero(
            phase="matrix_final", model_id=None, load_group=None
        )
        self._write_group_capture("zero-matrix-final.json", matrix_final)
        if not _global_zero_verified(matrix_final):
            raise Qwen35MatrixError("Qwen matrix-final global loaded count must be zero")
        ordered = {result.row_id: result for result in results}
        if set(ordered) != {row.row_id for row in self.manifest.rows}:
            raise Qwen35MatrixError("Qwen progress did not reconcile all rows")
        return Qwen35MatrixResult(
            self.manifest.manifest_sha256,
            tuple(ordered[row.row_id] for row in self.manifest.rows),
            inference_count,
            0,
        )

    def _execute_row(
        self, row: Qwen35MatrixRow, *, inference_call_index: int
    ) -> tuple[Qwen35RowResult, int]:
        try:
            raw = self.host.execute_matrix_row(row=row.binding(), timeout_s=self.timeout_s)
            exchanges = raw.get("exchanges")
            expected_calls = 2 if row.request_kind == "parallel_pair" else 1
            if not isinstance(exchanges, Sequence) or isinstance(
                exchanges, (str, bytes, bytearray)
            ):
                exchanges = ()
            validated = [_validate_exact_exchange(exchange, row=row) for exchange in exchanges]
            response_payloads = [
                payload
                for payload, reason in validated
                if reason is None and isinstance(payload, Mapping)
            ]
            evidence_reasons = [reason for _payload, reason in validated if reason is not None]
            actual_calls = len(exchanges)
            accounting_failed = actual_calls != expected_calls
            if evidence_reasons or accounting_failed:
                verdicts = {
                    "transport": "fail",
                    "response_surface": "fail",
                    "raw_parse": "skip",
                    "schema": "skip",
                    "business": "skip",
                    "semantic": "fail",
                }
            else:
                verdicts = _controller_verdicts(
                    row,
                    response_payloads,
                    repo_root=self.manifest.repo_root,
                )
            private = {
                "manifest_sha256": self.manifest.manifest_sha256,
                "row_sha256": row.row_sha256,
                "inference_call_index": inference_call_index,
                "actual_inference_calls": actual_calls,
                "exchanges": list(exchanges),
                "runtime": raw.get("runtime"),
                "controller_verdicts": verdicts,
            }
            path = self._write_private_json(f"call-{row.ordinal:02d}-{row.row_id}.json", private)
            capture_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            semantic_pass, semantic_reason = _validate_manual_adjudication(
                self.adjudications.get(row.row_id),
                row=row,
                capture_sha256=capture_sha256,
            )
            deterministic_pass = all(verdict == "pass" for verdict in verdicts.values())
            accepted = deterministic_pass and semantic_pass and not evidence_reasons
            failure_reason = (
                evidence_reasons[0]
                if evidence_reasons
                else "actual_inference_call_accounting_mismatch"
                if accounting_failed
                else semantic_reason or "controller_validation_failed"
            )
            return (
                Qwen35RowResult(
                    row.row_id,
                    "executed",
                    inference_call_index,
                    accepted,
                    None if accepted else failure_reason,
                    capture_sha256,
                ),
                actual_calls,
            )
        except Qwen35MatrixError:
            raise
        except Exception as error:
            private = {
                "manifest_sha256": self.manifest.manifest_sha256,
                "row_sha256": row.row_sha256,
                "inference_call_index": inference_call_index,
                "transport_error_category": type(error).__name__,
            }
            self._write_private_json(f"call-{row.ordinal:02d}-{row.row_id}.json", private)
            raise Qwen35MatrixError(
                "Qwen row failed before exact outbound and raw response capture"
            ) from error

    def _resumed_result(
        self,
        row: Qwen35MatrixRow,
        prior: Mapping[str, object],
    ) -> Qwen35RowResult:
        if prior.get("status") == "stop_gated":
            return Qwen35RowResult(
                row.row_id,
                "resumed",
                None,
                None,
                _optional_str(prior.get("reason")),
                None,
            )
        capture_sha256 = _strict_str(prior.get("capture_sha256"))
        capture_path = self.private_root / f"call-{row.ordinal:02d}-{row.row_id}.json"
        capture = json.loads(capture_path.read_text(encoding="utf-8"))
        if not isinstance(capture, Mapping):
            raise Qwen35MatrixError("Qwen resumed capture must be an object")
        verdicts = capture.get("controller_verdicts")
        deterministic_pass = (
            isinstance(verdicts, Mapping)
            and bool(verdicts)
            and all(verdict == "pass" for verdict in verdicts.values())
        )
        semantic_pass, semantic_reason = _validate_manual_adjudication(
            self.adjudications.get(row.row_id),
            row=row,
            capture_sha256=capture_sha256,
        )
        accepted = deterministic_pass and semantic_pass
        reason = None if accepted else semantic_reason or _optional_str(prior.get("reason"))
        return Qwen35RowResult(
            row.row_id,
            "resumed",
            _optional_int(prior.get("inference_call_index")),
            accepted,
            None if accepted else reason or "controller_validation_failed",
            capture_sha256,
        )

    def _validate_live_identity(self, pin: Qwen35ModelPin) -> None:
        metadata = self.host.model_metadata(model_id=pin.model_id)
        if not isinstance(metadata, Mapping):
            raise Qwen35MatrixError("Qwen exact installed model metadata was not observed")
        snapshot = {key: metadata[key] for key in _IDENTITY_FIELDS if key in metadata}
        if (
            snapshot != dict(pin.identity_snapshot)
            or _canonical_sha256(snapshot) != pin.identity_sha256
        ):
            raise Qwen35MatrixError("Qwen installed model identity hash mismatch")
        artifact = metadata.get("artifact_evidence")
        execution_pin = self.artifact_pins.get(pin.model_id)
        canonical_pin = _canonical_artifact_execution_pin(execution_pin)
        canonical_files = None if canonical_pin is None else canonical_pin.get("files")
        if (
            canonical_pin is None
            or canonical_pin.get("model_id") != pin.model_id
            or not isinstance(canonical_files, list)
            or not isinstance(artifact, Mapping)
            or artifact.get("status") != "verified"
            or artifact.get("variant") != canonical_pin.get("variant")
            or artifact.get("pin_sha256") != canonical_pin.get("pin_sha256")
            or artifact.get("file_count") != len(canonical_files)
        ):
            raise Qwen35MatrixError(
                "Qwen execution identity unavailable before canary: exact artifact evidence required"
            )

    def _prepare_private_root(self) -> None:
        root = self.private_root.resolve()
        if root == self.manifest.repo_root or root.is_relative_to(self.manifest.repo_root):
            raise Qwen35MatrixError("Qwen owner-only capture must be outside the repository")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        if os.stat(root).st_mode & 0o777 != 0o700:
            raise Qwen35MatrixError("Qwen owner-only capture directory mode must be 0700")

    def _read_progress(self, path: Path) -> dict[str, Mapping[str, object]]:
        if not path.exists():
            return {}
        records: dict[str, Mapping[str, object]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise Qwen35MatrixError("Qwen progress ledger is malformed") from error
            if (
                not isinstance(record, Mapping)
                or record.get("manifest_sha256") != self.manifest.manifest_sha256
            ):
                raise Qwen35MatrixError("Qwen progress ledger manifest binding mismatch")
            row_id = record.get("row_id")
            if not isinstance(row_id, str) or row_id in records:
                raise Qwen35MatrixError("Qwen progress ledger contains duplicate rows")
            records[row_id] = record
        expected = {row.row_id for row in self.manifest.rows}
        if not set(records).issubset(expected):
            raise Qwen35MatrixError("Qwen progress ledger contains unknown rows")
        expected_prefix = [row.row_id for row in self.manifest.rows[: len(records)]]
        if list(records) != expected_prefix:
            raise Qwen35MatrixError("Qwen progress ledger must be a contiguous manifest prefix")
        next_index = 1
        rows = {row.row_id: row for row in self.manifest.rows}
        for row_id, record in records.items():
            row = rows[row_id]
            status = record.get("status")
            if (
                status not in {"executed", "stop_gated"}
                or record.get("row_sha256") != row.row_sha256
            ):
                raise Qwen35MatrixError("Qwen progress ledger row evidence is invalid")
            actual_calls = record.get("actual_inference_calls")
            if status == "executed":
                expected_calls = 2 if row.request_kind == "parallel_pair" else 1
                if (
                    not isinstance(actual_calls, int)
                    or isinstance(actual_calls, bool)
                    or not 1 <= actual_calls <= expected_calls
                    or record.get("inference_call_index") != next_index
                    or not _is_sha256(record.get("capture_sha256"))
                    or not isinstance(record.get("accepted"), bool)
                    or (
                        record.get("accepted") is True
                        and row.lane in {"structured_text", "strict_structured_vision"}
                    )
                ):
                    raise Qwen35MatrixError("Qwen progress ledger inference evidence is invalid")
                capture_path = self.private_root / f"call-{row.ordinal:02d}-{row.row_id}.json"
                if not capture_path.is_file() or hashlib.sha256(
                    capture_path.read_bytes()
                ).hexdigest() != record.get("capture_sha256"):
                    raise Qwen35MatrixError("Qwen progress ledger capture digest mismatch")
                try:
                    capture = json.loads(capture_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as error:
                    raise Qwen35MatrixError(
                        "Qwen progress ledger capture evidence is malformed"
                    ) from error
                if (
                    not isinstance(capture, Mapping)
                    or capture.get("manifest_sha256") != self.manifest.manifest_sha256
                    or capture.get("row_sha256") != row.row_sha256
                    or capture.get("inference_call_index") != next_index
                    or capture.get("actual_inference_calls") != actual_calls
                    or not isinstance(capture.get("exchanges"), list)
                    or len(capture["exchanges"]) != actual_calls
                ):
                    raise Qwen35MatrixError(
                        "Qwen progress ledger capture evidence binding mismatch"
                    )
                next_index += actual_calls
            elif (
                actual_calls != 0
                or record.get("inference_call_index") is not None
                or record.get("capture_sha256") is not None
                or record.get("accepted") is not None
                or not _valid_stop_gate_reason(row, record.get("reason"))
            ):
                raise Qwen35MatrixError("Qwen stop-gated progress evidence is invalid")
        if next_index - 1 > self.manifest.max_inference_calls:
            raise Qwen35MatrixError("Qwen resumed inference call ceiling exceeded")
        return records

    def _reconcile_orphan_attempts(
        self,
        ledger_path: Path,
        previous: Mapping[str, Mapping[str, object]],
    ) -> dict[str, Mapping[str, object]]:
        records = dict(previous)
        attempts_by_row: dict[str, list[Mapping[str, object]]] = {}
        for request_path in sorted(self.private_root.glob("attempt-q35-*-slot-*-request.json")):
            try:
                request_record = json.loads(request_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise Qwen35MatrixError(
                    "Qwen durable attempt request evidence is malformed"
                ) from error
            if not isinstance(request_record, Mapping):
                raise Qwen35MatrixError("Qwen durable attempt request must be an object")
            row_id = request_record.get("row_id")
            worker_slot = request_record.get("worker_slot")
            if not isinstance(row_id, str) or not isinstance(worker_slot, int):
                raise Qwen35MatrixError("Qwen durable attempt request binding is invalid")
            row = next((item for item in self.manifest.rows if item.row_id == row_id), None)
            if (
                row is None
                or request_record.get("manifest_sha256") != self.manifest.manifest_sha256
                or request_record.get("row_sha256") != row.row_sha256
                or request_record.get("state") != "reserved_before_send"
            ):
                raise Qwen35MatrixError("Qwen durable attempt request manifest binding mismatch")
            exchange = {
                key: request_record[key]
                for key in (
                    "endpoint",
                    "worker_slot",
                    "attempt_index",
                    "outbound_bytes_b64",
                    "outbound_sha256",
                )
            }
            response_path = self.private_root / f"attempt-{row_id}-slot-{worker_slot}-response.json"
            if response_path.exists():
                try:
                    response_record = json.loads(response_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as error:
                    raise Qwen35MatrixError(
                        "Qwen durable attempt response evidence is malformed"
                    ) from error
                if (
                    not isinstance(response_record, Mapping)
                    or response_record.get("manifest_sha256") != self.manifest.manifest_sha256
                    or response_record.get("row_id") != row_id
                    or response_record.get("worker_slot") != worker_slot
                    or response_record.get("attempt_index") != request_record.get("attempt_index")
                ):
                    raise Qwen35MatrixError("Qwen durable attempt response binding mismatch")
                exchange.update(
                    {
                        key: response_record[key]
                        for key in (
                            "response_available",
                            "transport_error_category",
                            "http_status",
                            "content_type",
                            "raw_response_bytes_b64",
                            "raw_response_sha256",
                            "latency_ms",
                            "decoded",
                        )
                        if key in response_record
                    }
                )
            else:
                exchange["response_available"] = False
                exchange["transport_error_category"] = "interrupted_after_reservation"
            attempts_by_row.setdefault(row_id, []).append(exchange)
        attempt_indices = sorted(
            _strict_int(exchange.get("attempt_index"))
            for exchanges in attempts_by_row.values()
            for exchange in exchanges
        )
        if attempt_indices != list(range(1, len(attempt_indices) + 1)):
            raise Qwen35MatrixError("Qwen durable attempt indices are not contiguous")
        for row_id in attempts_by_row:
            if row_id in records:
                continue
            next_row = (
                self.manifest.rows[len(records)] if len(records) < len(self.manifest.rows) else None
            )
            if next_row is None or next_row.row_id != row_id:
                raise Qwen35MatrixError("Qwen orphan attempts are not a contiguous manifest prefix")
            row = next_row
            exchanges = sorted(
                attempts_by_row[row_id], key=lambda item: _strict_int(item.get("worker_slot"))
            )
            validated = [_validate_exact_exchange(exchange, row=row) for exchange in exchanges]
            response_payloads = [
                payload
                for payload, reason in validated
                if reason is None and isinstance(payload, Mapping)
            ]
            evidence_reasons = [reason for _payload, reason in validated if reason is not None]
            expected_calls = 2 if row.request_kind == "parallel_pair" else 1
            complete = len(exchanges) == expected_calls and not evidence_reasons
            verdicts = (
                _controller_verdicts(row, response_payloads, repo_root=self.manifest.repo_root)
                if complete
                else {
                    "transport": "fail",
                    "response_surface": "fail",
                    "raw_parse": "skip",
                    "schema": "skip",
                    "business": "skip",
                    "semantic": "fail",
                }
            )
            call_index = min(_strict_int(item.get("attempt_index")) for item in exchanges)
            capture = {
                "manifest_sha256": self.manifest.manifest_sha256,
                "row_sha256": row.row_sha256,
                "inference_call_index": call_index,
                "actual_inference_calls": len(exchanges),
                "exchanges": exchanges,
                "runtime": {
                    "request_kind": row.request_kind,
                    "parallel_fanout": len(exchanges),
                },
                "controller_verdicts": verdicts,
            }
            capture_path = self.private_root / f"call-{row.ordinal:02d}-{row.row_id}.json"
            if not capture_path.exists():
                self._write_private_json(capture_path.name, capture)
            elif capture_path.read_bytes() != (_canonical_json(capture) + "\n").encode():
                raise Qwen35MatrixError("Qwen interrupted capture reconstruction mismatch")
            capture_sha256 = hashlib.sha256(capture_path.read_bytes()).hexdigest()
            semantic_pass, semantic_reason = _validate_manual_adjudication(
                self.adjudications.get(row.row_id), row=row, capture_sha256=capture_sha256
            )
            accepted = (
                complete and all(value == "pass" for value in verdicts.values()) and semantic_pass
            )
            failure_reason = semantic_reason
            if failure_reason is None and evidence_reasons:
                failure_reason = evidence_reasons[0]
            if failure_reason is None:
                failure_reason = "interrupted_attempt_not_replayed"
            result = Qwen35RowResult(
                row.row_id,
                "executed",
                call_index,
                accepted,
                None if accepted else failure_reason,
                capture_sha256,
            )
            self._append_progress(
                ledger_path,
                row,
                result,
                actual_inference_calls=len(exchanges),
            )
            records[row_id] = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[-1])
        return records

    def _append_progress(
        self,
        path: Path,
        row: Qwen35MatrixRow,
        result: Qwen35RowResult,
        *,
        actual_inference_calls: int = 0,
    ) -> None:
        record = {
            "manifest_sha256": self.manifest.manifest_sha256,
            "row_id": row.row_id,
            "row_sha256": row.row_sha256,
            "status": result.status,
            "inference_call_index": result.inference_call_index,
            "accepted": result.accepted,
            "reason": result.reason,
            "capture_sha256": result.capture_sha256,
            "actual_inference_calls": actual_inference_calls,
        }
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, (_canonical_json(record) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(path, 0o600)

    def _write_private_json(self, name: str, payload: Mapping[str, object]) -> Path:
        path = self.private_root / name
        if path.exists():
            raise Qwen35MatrixError("Qwen owner-only capture would overwrite existing evidence")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, (_canonical_json(payload) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return path

    def _write_group_capture(self, name: str, payload: Mapping[str, object]) -> Path:
        path = self.private_root / name
        if not path.exists():
            return self._write_private_json(name, payload)
        stem = path.stem
        suffix = path.suffix
        resume_index = 2
        while (self.private_root / f"{stem}-resume-{resume_index}{suffix}").exists():
            resume_index += 1
        return self._write_private_json(f"{stem}-resume-{resume_index}{suffix}", payload)

    @staticmethod
    def _stop_gate(row: Qwen35MatrixRow, reason: str) -> Qwen35RowResult:
        return Qwen35RowResult(row.row_id, "stop_gated", None, None, reason, None)


def _validate_exact_exchange(
    value: object, *, row: Qwen35MatrixRow
) -> tuple[Mapping[str, object] | None, str | None]:
    if not isinstance(value, Mapping):
        return None, "missing_exchange_evidence"
    strict_kinds = {
        "strict_json_canary",
        "structured_text",
        "strict_simple",
        "strict_medium",
        "strict_ui_repeat",
    }
    expected_route = "/v1/chat/completions" if row.request_kind in strict_kinds else "/api/v1/chat"
    if value.get("endpoint") != expected_route:
        return None, "http_route_evidence_mismatch"
    try:
        outbound = base64.b64decode(str(value["outbound_bytes_b64"]), validate=True)
    except (KeyError, ValueError) as error:
        raise Qwen35MatrixError("Qwen exact HTTP exchange bytes are invalid") from error
    if hashlib.sha256(outbound).hexdigest() != value.get("outbound_sha256"):
        raise Qwen35MatrixError("Qwen exact outbound HTTP exchange digest mismatch")
    try:
        request_payload = json.loads(outbound)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Qwen35MatrixError("Qwen exact outbound HTTP exchange is not JSON") from error
    if not isinstance(request_payload, Mapping):
        raise Qwen35MatrixError("Qwen exact outbound HTTP exchange must be an object")
    if request_payload.get("model") != row.model_id or request_payload.get("stream") is not False:
        raise Qwen35MatrixError("Qwen outbound model or stream binding mismatch")
    if row.reasoning == "omitted" and "reasoning" in request_payload:
        raise Qwen35MatrixError("Qwen unadvertised reasoning control was sent")
    if row.reasoning != "omitted" and request_payload.get("reasoning") != row.reasoning:
        raise Qwen35MatrixError("Qwen outbound reasoning control mismatch")
    if expected_route == "/v1/chat/completions":
        response_format = request_payload.get("response_format")
        if (
            not isinstance(response_format, Mapping)
            or response_format.get("type") != "json_schema"
            or request_payload.get("temperature") != 0.0
        ):
            raise Qwen35MatrixError("Qwen strict-route payload contract mismatch")
    elif request_payload.get("store") is not (
        row.request_kind in {"warm_prefix", "prefix_reuse", "session_reuse"}
    ):
        raise Qwen35MatrixError("Qwen native cache/session payload contract mismatch")
    if value.get("response_available") is False or isinstance(
        value.get("transport_error_category"), str
    ):
        return None, "transport_error"
    try:
        response = base64.b64decode(str(value["raw_response_bytes_b64"]), validate=True)
    except (KeyError, ValueError) as error:
        raise Qwen35MatrixError("Qwen raw response evidence bytes are invalid") from error
    if hashlib.sha256(response).hexdigest() != value.get("raw_response_sha256"):
        raise Qwen35MatrixError("Qwen raw response evidence digest mismatch")
    if value.get("http_status") != 200:
        return None, "http_non_200"
    try:
        response_payload = json.loads(response)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "malformed_response_json"
    if not isinstance(response_payload, Mapping):
        return None, "malformed_response_surface"
    return response_payload, None


def _controller_verdicts(
    row: Qwen35MatrixRow,
    responses: Sequence[Mapping[str, object]],
    *,
    repo_root: Path,
) -> dict[str, str]:
    verdicts = {
        "transport": "pass",
        "response_surface": "fail",
        "raw_parse": "skip",
        "schema": "skip",
        "business": "skip",
        "semantic": "fail",
    }
    strict = row.request_kind in {
        "strict_json_canary",
        "structured_text",
        "strict_simple",
        "strict_medium",
        "strict_ui_repeat",
    }
    if not strict:
        texts = [_native_final_text(response) for response in responses]
        if all(text is not None for text in texts):
            verdicts["response_surface"] = "pass"
            verdicts["raw_parse"] = "not_applicable"
            verdicts["schema"] = "not_applicable"
            verdicts["business"] = "pass"
            verdicts["semantic"] = "pass"
        return verdicts
    contents = [_compat_final_text(response) for response in responses]
    if any(content is None for content in contents):
        return verdicts
    verdicts["response_surface"] = "pass"
    try:
        parsed = [json.loads(content) for content in contents if content is not None]
    except json.JSONDecodeError:
        verdicts["raw_parse"] = "fail"
        return verdicts
    verdicts["raw_parse"] = "pass"
    schema = _schema_for_row(row, repo_root=repo_root)
    if not all(validate_json_schema(value, schema).status == "pass" for value in parsed):
        verdicts["schema"] = "fail"
        return verdicts
    verdicts["schema"] = "pass"
    if any(validate_no_reasoning_leak(value).status != "pass" for value in parsed):
        verdicts["business"] = "fail"
        return verdicts
    verdicts["business"] = "pass"
    if row.lane == "strict_structured_vision":
        truth = _vision_ground_truth(row, repo_root=repo_root)
        grounded = [
            validate_strict_vision_grounding(
                value,
                schema_name=str(row.schema_name),
                ground_truth=truth,
            )
            for value in parsed
        ]
        verdicts["semantic"] = (
            "pass" if all(result.status == "pass" for result in grounded) else "fail"
        )
    else:
        verdicts["semantic"] = "pass"
    return verdicts


def _validate_manual_adjudication(
    value: Mapping[str, object] | None,
    *,
    row: Qwen35MatrixRow,
    capture_sha256: str,
) -> tuple[bool, str | None]:
    if row.lane not in {"strict_structured_vision", "structured_text"}:
        return True, None
    required_dimension = (
        "vision_pixel_content_fidelity"
        if row.lane == "strict_structured_vision"
        else "structured_text_content_fidelity"
    )
    if (
        not isinstance(value, Mapping)
        or value.get("row_sha256") != row.row_sha256
        or value.get("capture_sha256") != capture_sha256
        or value.get("dimension") != required_dimension
        or value.get("semantic_pass") is not True
        or not isinstance(value.get("reason_code"), str)
        or not value.get("reason_code")
    ):
        return (
            False,
            "manual_pixel_adjudication_required"
            if row.lane == "strict_structured_vision"
            else "content_fidelity_adjudication_required",
        )
    return True, None


def _compat_final_text(response: Mapping[str, object]) -> str | None:
    choices = response.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, Mapping):
        return None
    message = choice.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    return content if isinstance(content, str) else None


def _native_final_text(response: Mapping[str, object]) -> str | None:
    text = response.get("output_text")
    if isinstance(text, str) and text.strip():
        return text
    output = response.get("output")
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes)):
        for item in reversed(output):
            if isinstance(item, Mapping) and isinstance(item.get("content"), str):
                return str(item["content"])
    return None


def _schema_for_row(row: Qwen35MatrixRow, *, repo_root: Path) -> dict[str, Any]:
    if row.request_kind == "strict_json_canary":
        return {
            "type": "object",
            "required": ["id", "text"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": ["integer", "string"]},
                "text": {"type": "string", "minLength": 1},
            },
        }
    if row.lane == "structured_text":
        if row.schema_name == "simple":
            path = (
                repo_root
                / "experiments/lmstudio/private_benchmark_pack/v1/schemas/normalization_output_v1.schema.json"
            )
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        fixture_path = (
            repo_root
            / f"experiments/lmstudio/private_benchmark_pack/v1/views/{row.source_binding}/fixture.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        units = fixture.get("ordered_units", []) if isinstance(fixture, Mapping) else []
        ids = [
            item["unit_index"]
            for item in units
            if isinstance(item, Mapping) and isinstance(item.get("unit_index"), int)
        ]
        return {
            "type": "object",
            "required": ["blocks"],
            "additionalProperties": False,
            "properties": {
                "blocks": {
                    "type": "array",
                    "minItems": len(ids),
                    "maxItems": len(ids),
                    "prefixItems": [
                        {
                            "type": "object",
                            "required": ["id", "text"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"const": item},
                                "text": {"type": "string", "minLength": 1},
                            },
                        }
                        for item in ids
                    ],
                    "items": False,
                }
            },
        }
    vision = json.loads(
        (repo_root / "experiments/lmstudio/strict_vision/launch_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    for item in vision.get("schemas", []):
        if isinstance(item, Mapping) and item.get("name") == row.schema_name:
            body = item.get("body")
            if isinstance(body, dict):
                return body
    raise Qwen35MatrixError("Qwen row schema binding could not be resolved")


def _vision_ground_truth(row: Qwen35MatrixRow, *, repo_root: Path) -> Mapping[str, object]:
    vision = json.loads(
        (repo_root / "experiments/lmstudio/strict_vision/launch_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    for item in vision.get("fixtures", []):
        if isinstance(item, Mapping) and item.get("fixture_id") == row.fixture_id:
            truth = item.get("ground_truth")
            if isinstance(truth, Mapping):
                return truth
    raise Qwen35MatrixError("Qwen vision fixture ground truth binding could not be resolved")


def _materialization_attestation(
    load_response: object,
    materialized: object,
    gpu: object,
    *,
    global_loaded_count: int | None,
    model_id: str,
    context_length: int,
    parallel: int,
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "exact_model_id": False,
        "context_length": False,
        "parallel": False,
        "authoritative_all_layers_gpu": False,
        "runtime_telemetry_authority_validated": False,
        "runtime_instance_reference_authority_validated": False,
        "kv_cache_gpu_when_supported": False,
        "cpu_fallback_false": False,
        "resource_guardrail_downgrade_false": False,
        "memory_thrash_observed_false": False,
        "global_loaded_count_one": global_loaded_count == 1,
        "load_verified": isinstance(load_response, Mapping)
        and load_response.get("load_verified") is True,
    }
    if not evidence["global_loaded_count_one"] or not evidence["load_verified"]:
        return {"verified": False, "evidence": evidence}
    assert isinstance(load_response, Mapping)
    applied = load_response.get(
        "requested_load_config",
        load_response.get("applied_load_config", load_response.get("load_config")),
    )
    if not isinstance(applied, Mapping):
        return {"verified": False, "evidence": evidence}
    explicit_full = applied.get("gpu") == "max" or applied.get("gpu_offload_ratio") == 1.0
    if (
        not explicit_full
        or applied.get("context_length") != context_length
        or applied.get("parallel") != parallel
    ):
        return {"verified": False, "evidence": evidence}
    if not isinstance(materialized, Mapping) or materialized.get("key") != model_id:
        return {"verified": False, "evidence": evidence}
    evidence["exact_model_id"] = True
    instances = materialized.get("loaded_instances")
    if (
        not isinstance(instances, Sequence)
        or isinstance(instances, (str, bytes))
        or len(instances) != 1
    ):
        return {"verified": False, "evidence": evidence}
    instance = instances[0]
    if not isinstance(instance, Mapping):
        return {"verified": False, "evidence": evidence}
    instance_id = instance.get("id", instance.get("instance_id"))
    if not isinstance(instance_id, str) or not instance_id:
        return {"verified": False, "evidence": evidence}
    config = instance.get("config", instance.get("load_config", instance.get("loadConfig")))
    if not isinstance(config, Mapping):
        return {"verified": False, "evidence": evidence}
    observed_context = config.get("context_length", config.get("contextLength"))
    observed_parallel = config.get("parallel", config.get("maxParallelPredictions"))
    evidence["context_length"] = observed_context == context_length
    evidence["parallel"] = observed_parallel == parallel
    if not isinstance(gpu, Mapping):
        return {"verified": False, "evidence": evidence}
    if gpu.get("model_key") != model_id or gpu.get("instance_id") != instance_id:
        return {"verified": False, "evidence": evidence}
    telemetry_sha256 = gpu.get("runtime_telemetry_sha256")
    telemetry_authority_validated = (
        gpu.get("runtime_telemetry_available") is True
        and gpu.get("runtime_telemetry_authoritative") is True
        and gpu.get("runtime_telemetry_source") == "installed_sdk_runtime_log_proc_v2"
        and gpu.get("runtime_telemetry_model_key") == model_id
        and gpu.get("runtime_telemetry_instance_id") == instance_id
        and isinstance(telemetry_sha256, str)
        and len(telemetry_sha256) == 64
        and all(character in "0123456789abcdef" for character in telemetry_sha256)
    )
    instance_reference = gpu.get("runtime_instance_reference")
    authoritative_instance_reference = gpu.get("authoritative_instance_reference")
    runtime_instance_reference_authority_validated = (
        telemetry_authority_validated
        and isinstance(instance_reference, str)
        and bool(instance_reference)
        and instance_reference == authoritative_instance_reference
        and isinstance(gpu.get("runtime_pid"), int)
        and not isinstance(gpu.get("runtime_pid"), bool)
        and gpu.get("runtime_pid", 0) > 0
        and isinstance(gpu.get("runtime_process_start_ticks"), int)
        and not isinstance(gpu.get("runtime_process_start_ticks"), bool)
        and gpu.get("runtime_process_start_ticks", 0) > 0
    )
    gpu_layers = gpu.get("gpu_layers")
    total_layers = gpu.get("total_layers")
    layers_full = (
        telemetry_authority_validated
        and isinstance(gpu_layers, int)
        and not isinstance(gpu_layers, bool)
        and isinstance(total_layers, int)
        and not isinstance(total_layers, bool)
        and gpu_layers == total_layers
        and gpu_layers > 0
    )
    evidence["runtime_telemetry_authority_validated"] = telemetry_authority_validated
    evidence["runtime_instance_reference_authority_validated"] = (
        runtime_instance_reference_authority_validated
    )
    evidence["authoritative_all_layers_gpu"] = layers_full
    evidence["kv_cache_gpu_when_supported"] = (
        gpu.get("kv_cache_gpu_supported") is False or gpu.get("kv_cache_gpu") is True
    )
    evidence["cpu_fallback_false"] = gpu.get("cpu_fallback") is False
    evidence["resource_guardrail_downgrade_false"] = (
        gpu.get("resource_guardrail_downgrade") is False
    )
    evidence["memory_thrash_observed_false"] = gpu.get("memory_thrash_observed") is False
    return {"verified": all(value is True for value in evidence.values()), "evidence": evidence}


def _full_gpu_verified(
    load_response: object,
    materialized: object,
    gpu: object,
    *,
    global_loaded_count: int | None,
    model_id: str,
    context_length: int,
    parallel: int,
) -> bool:
    return (
        _materialization_attestation(
            load_response,
            materialized,
            gpu,
            global_loaded_count=global_loaded_count,
            model_id=model_id,
            context_length=context_length,
            parallel=parallel,
        )["verified"]
        is True
    )


def _global_zero_verified(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("global_zero_verified") is True
        and value.get("lms_ps_loaded_total") == 0
        and value.get("api_loaded_total") == 0
    )


def _cleanup_verified(value: object) -> bool:
    return isinstance(value, Mapping) and value.get("cleanup_verified") is True


def _valid_stop_gate_reason(row: Qwen35MatrixRow, value: object) -> bool:
    if not isinstance(value, str):
        return False
    allowed = {
        "base_full_gpu_not_proven",
        "execution_identity_unavailable",
        "full_gpu_materialization_not_proven",
        "stateful_group_resume_not_reconstructable",
    }
    if value == "base_full_gpu_not_proven":
        return row.condition in _ALLOWED_CONDITIONS
    if value == "stateful_group_resume_not_reconstructable":
        return row.lane == "context_cache"
    return value in allowed


def _contiguous_groups(
    rows: tuple[Qwen35MatrixRow, ...],
) -> tuple[tuple[Qwen35MatrixRow, ...], ...]:
    groups: list[list[Qwen35MatrixRow]] = []
    for row in rows:
        key = (row.model_id, row.load_group, row.context_length, row.parallel, row.condition)
        if not groups:
            groups.append([row])
            continue
        previous = groups[-1][0]
        previous_key = (
            previous.model_id,
            previous.load_group,
            previous.context_length,
            previous.parallel,
            previous.condition,
        )
        if key == previous_key:
            groups[-1].append(row)
        else:
            groups.append([row])
    return tuple(tuple(group) for group in groups)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _strict_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError
    return value


def _strict_str(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError
    return value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _strict_str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _strict_int(value)


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TypeError
    return value


def _reasoning(value: object) -> Literal["off", "on", "omitted"]:
    if value not in {"off", "on", "omitted"}:
        raise ValueError
    return value  # type: ignore[return-value]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--manifest-sha256", required=True)
    run.add_argument("--private-root", type=Path, required=True)
    run.add_argument("--artifact-pins", type=Path, required=True)
    run.add_argument("--artifact-pins-sha256", required=True)
    run.add_argument("--repo-root", type=Path, default=Path("."))
    run.add_argument("--base-url", default="http://127.0.0.1:1234")
    run.add_argument("--timeout", type=float, default=900.0)
    run.add_argument("--adjudications", type=Path)
    run.add_argument("--allow-model-loads", action="store_true")
    pin = subparsers.add_parser("pin-artifacts")
    pin.add_argument("--manifest", type=Path, required=True)
    pin.add_argument("--manifest-sha256", required=True)
    pin.add_argument("--repo-root", type=Path, default=Path("."))
    pin.add_argument("--output", type=Path, required=True)
    pin.add_argument("--artifact", action="append", default=[], required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = load_qwen35_full_gpu_manifest(
        args.manifest,
        expected_sha256=args.manifest_sha256,
        repo_root=args.repo_root,
    )
    if args.command == "pin-artifacts":
        artifact_paths: dict[str, list[Path]] = {}
        for binding in args.artifact:
            if not isinstance(binding, str) or "=" not in binding:
                raise Qwen35MatrixError("Qwen --artifact must be MODEL_ID=/absolute/path")
            model_id, raw_path = binding.split("=", 1)
            if not model_id or not Path(raw_path).is_absolute():
                raise Qwen35MatrixError("Qwen --artifact must be MODEL_ID=/absolute/path")
            artifact_paths.setdefault(model_id, []).append(Path(raw_path))
        digest = write_qwen35_artifact_execution_pins(
            args.output, manifest=manifest, artifact_paths=artifact_paths
        )
        print(_canonical_json({"manifest_sha256": manifest.manifest_sha256, "pin_sha256": digest}))
        return 0
    artifact_pins = load_qwen35_artifact_execution_pins(
        args.artifact_pins,
        expected_sha256=args.artifact_pins_sha256,
        manifest=manifest,
    )
    adjudications: Mapping[str, Mapping[str, object]] = {}
    if args.adjudications is not None:
        adjudications = load_qwen35_adjudication_ledger(
            args.adjudications,
            manifest=manifest,
            private_root=args.private_root,
        )
    from .qwen35_full_gpu_host import LocalQwen35FullGPUHost

    host = LocalQwen35FullGPUHost(
        manifest=manifest,
        private_root=args.private_root,
        artifact_pins=artifact_pins,
        base_url=args.base_url,
        default_timeout_s=args.timeout,
    )
    result = Qwen35FullGPUController(
        manifest=manifest,
        host=host,
        private_root=args.private_root,
        artifact_pins=artifact_pins,
        allow_model_loads=args.allow_model_loads,
        timeout_s=args.timeout,
        adjudications=adjudications,
    ).run()
    print(
        _canonical_json(
            {
                "manifest_sha256": result.manifest_sha256,
                "cumulative_inference_calls": result.cumulative_inference_calls,
                "final_loaded_global_count": result.final_loaded_global_count,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
