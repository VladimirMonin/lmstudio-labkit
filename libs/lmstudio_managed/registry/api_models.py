"""Pure model-list REST parsing contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .._safe import as_bool, as_float, as_int, as_str, safe_hash_ref
from ..client.endpoint import EndpointKind
from ..client.errors import ApiErrorKind, SafeApiError


@dataclass(frozen=True, slots=True)
class VisibleModelRecord:
    model_id: str
    endpoint_kind: EndpointKind
    owned_by_lmstudio: bool | None = None


@dataclass(frozen=True, slots=True)
class LoadedInstanceRecord:
    instance_ref: str
    model_key: str
    context_length: int | None
    parallel: int | None
    owned_by_us: bool = True


@dataclass(frozen=True, slots=True)
class NativeModelFacts:
    native_model_key: str
    format: str | None
    bits_per_weight: float | None
    size_bytes: int | None
    quantization: str | None
    loaded_instances: tuple[LoadedInstanceRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelListRequest:
    endpoint_kind: EndpointKind


@dataclass(frozen=True, slots=True)
class ModelListResponse:
    endpoint_kind: EndpointKind
    visible_models: tuple[VisibleModelRecord, ...]
    native_models: tuple[NativeModelFacts, ...]
    error: SafeApiError | None = None


def parse_compat_model_list(payload: Mapping[str, object]) -> ModelListResponse:
    records = _as_mapping_sequence(payload.get("data"))
    if records is None:
        return _schema_error_response(EndpointKind.COMPAT_MODELS)

    visible_models: list[VisibleModelRecord] = []
    for item in records:
        model_id = as_str(item.get("id"))
        if model_id is None:
            return _schema_error_response(EndpointKind.COMPAT_MODELS)
        visible_models.append(
            VisibleModelRecord(
                model_id=model_id,
                endpoint_kind=EndpointKind.COMPAT_MODELS,
                owned_by_lmstudio=_owned_by_lmstudio(item.get("owned_by")),
            )
        )

    return ModelListResponse(
        endpoint_kind=EndpointKind.COMPAT_MODELS,
        visible_models=tuple(visible_models),
        native_models=(),
    )


def parse_native_model_list(payload: Mapping[str, object]) -> ModelListResponse:
    raw_models = _as_mapping_sequence(payload.get("models"))
    if raw_models is None:
        raw_models = _as_mapping_sequence(payload.get("data"))
    if raw_models is None:
        return _schema_error_response(EndpointKind.NATIVE_MODELS)

    visible_models: list[VisibleModelRecord] = []
    native_models: list[NativeModelFacts] = []
    for item in raw_models:
        model_key = _first_str(item, "model_key", "modelKey", "id", "key")
        if model_key is None:
            return _schema_error_response(EndpointKind.NATIVE_MODELS)

        visible_models.append(
            VisibleModelRecord(
                model_id=model_key,
                endpoint_kind=EndpointKind.NATIVE_MODELS,
            )
        )
        native_models.append(
            NativeModelFacts(
                native_model_key=model_key,
                format=_first_str(item, "format"),
                bits_per_weight=_first_float(item, "bits_per_weight", "bitsPerWeight"),
                size_bytes=_first_int(item, "size_bytes", "sizeBytes"),
                quantization=_first_str(item, "quantization"),
                loaded_instances=_parse_loaded_instances(model_key, item),
            )
        )

    return ModelListResponse(
        endpoint_kind=EndpointKind.NATIVE_MODELS,
        visible_models=tuple(visible_models),
        native_models=tuple(native_models),
    )


def _parse_loaded_instances(
    model_key: str,
    item: Mapping[str, object],
) -> tuple[LoadedInstanceRecord, ...]:
    raw_instances = _as_mapping_sequence(item.get("loaded_instances"))
    if raw_instances is None:
        raw_instances = _as_mapping_sequence(item.get("loadedInstances"))
    if raw_instances is None:
        return ()

    instances: list[LoadedInstanceRecord] = []
    for raw_instance in raw_instances:
        raw_ref = _first_str(
            raw_instance,
            "instance_ref",
            "instanceRef",
            "instance_id",
            "instanceId",
            "id",
        )
        instance_ref = safe_hash_ref(raw_ref)
        if instance_ref is None:
            continue
        instances.append(
            LoadedInstanceRecord(
                instance_ref=instance_ref,
                model_key=_first_str(raw_instance, "model_key", "modelKey") or model_key,
                context_length=_first_int(
                    raw_instance,
                    "context_length",
                    "contextLength",
                    "max_context_length",
                    "maxContextLength",
                ),
                parallel=_first_int(
                    raw_instance,
                    "parallel",
                    "n_parallel",
                    "nParallel",
                    "num_parallel",
                    "numParallelSequences",
                ),
                owned_by_us=_first_bool(raw_instance, "owned_by_us", "ownedByUs") is not False,
            )
        )
    return tuple(instances)


def _owned_by_lmstudio(value: object) -> bool | None:
    text = as_str(value)
    if text is None:
        return None
    normalized = text.lower().replace("-", "").replace("_", "")
    return normalized == "lmstudio"


def _schema_error_response(endpoint_kind: EndpointKind) -> ModelListResponse:
    return ModelListResponse(
        endpoint_kind=endpoint_kind,
        visible_models=(),
        native_models=(),
        error=SafeApiError(
            kind=ApiErrorKind.UNEXPECTED_SCHEMA,
            message="model_list_unexpected_schema",
        ),
    )


def _as_mapping_sequence(value: object) -> tuple[Mapping[str, object], ...] | None:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return None
    items: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        items.append(item)
    return tuple(items)


def _first_str(mapping: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = as_str(mapping.get(key))
        if value is not None:
            return value
    return None


def _first_int(mapping: Mapping[str, object], *keys: str) -> int | None:
    for key in keys:
        value = as_int(mapping.get(key))
        if value is not None:
            return value
    return None


def _first_float(mapping: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        value = as_float(mapping.get(key))
        if value is not None:
            return value
    return None


def _first_bool(mapping: Mapping[str, object], *keys: str) -> bool | None:
    for key in keys:
        value = as_bool(mapping.get(key))
        if value is not None:
            return value
    return None
