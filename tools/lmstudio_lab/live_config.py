from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from .config import load_raw_experiment_config, validate_experiment_config_payload
from .datasets import load_dataset_manifest

type LiveLoadScalar = bool | int | str
type LiveLoadFieldValue = LiveLoadScalar | tuple[LiveLoadScalar, ...]

_DEFAULT_LMSTUDIO_BASE_URL = "http://127.0.0.1:1234"
_LOCAL_LMSTUDIO_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
STRUCTURED_PROMPT_VARIANT_CHOICES = (
    "baseline",
    "anti_reasoning",
    "strict_id_contract",
    "ultra_minimal_transform",
)
STRUCTURED_SCHEMA_VARIANT_CHOICES = (
    "baseline",
    "per_position_id_const",
)


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


def _require_int(value: Any, *, field_name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    return value


def _require_zero_or_one_int(value: Any, *, field_name: str) -> int:
    normalized = _require_int(value, field_name=field_name, minimum=0)
    if normalized not in {0, 1}:
        raise ValueError(f"{field_name} must be 0 or 1")
    return normalized


def _require_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _require_string_sequence(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field_name} must be a list of strings")

    items = tuple(_require_non_empty_string(item, field_name=f"{field_name}[]") for item in value)
    if not items:
        raise ValueError(f"{field_name} must not be empty")
    return items


def _require_structured_prompt_variant(value: Any, *, field_name: str) -> str:
    variant = _require_non_empty_string(value, field_name=field_name)
    if variant not in STRUCTURED_PROMPT_VARIANT_CHOICES:
        supported = ", ".join(STRUCTURED_PROMPT_VARIANT_CHOICES)
        raise ValueError(f"{field_name} must be one of: {supported}")
    return variant


def _require_structured_schema_variant(value: Any, *, field_name: str) -> str:
    variant = _require_non_empty_string(value, field_name=field_name)
    if variant not in STRUCTURED_SCHEMA_VARIANT_CHOICES:
        supported = ", ".join(STRUCTURED_SCHEMA_VARIANT_CHOICES)
        raise ValueError(f"{field_name} must be one of: {supported}")
    return variant


def _normalize_load_scalar(value: Any, *, field_name: str) -> LiveLoadScalar:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _require_non_empty_string(value, field_name=field_name)
    raise ValueError(f"{field_name} must use bool, int, or string values")


def _normalize_load_value(value: Any, *, field_name: str) -> LiveLoadFieldValue:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized_items = tuple(
            _normalize_load_scalar(item, field_name=field_name) for item in value
        )
        if not normalized_items:
            raise ValueError(f"{field_name} list must not be empty")
        return normalized_items
    return _normalize_load_scalar(value, field_name=field_name)


def _normalize_url(url: str) -> SplitResult:
    candidate = _require_non_empty_string(url, field_name="lmstudio_base_url")
    if "://" not in candidate:
        candidate = f"http://{candidate}"

    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError("lmstudio_base_url must use http or https")
    if not parsed.hostname:
        raise ValueError("lmstudio_base_url must include a hostname")
    return parsed


def _normalize_url_text(url: str) -> str:
    parsed = _normalize_url(url)
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def is_local_lmstudio_base_url(url: str) -> bool:
    return _normalize_url(url).hostname.lower() in _LOCAL_LMSTUDIO_HOSTS


@dataclass(slots=True, frozen=True)
class LivePrivacyConfig:
    store_prompt_text: bool = False
    store_response_text: bool = False
    store_prompt_hash: bool = True

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> LivePrivacyConfig:
        if payload is None:
            privacy = cls()
        else:
            raw_payload = _require_mapping(payload, context="privacy")
            privacy = cls(
                store_prompt_text=_require_bool(
                    raw_payload.get("store_prompt_text", False),
                    field_name="privacy.store_prompt_text",
                ),
                store_response_text=_require_bool(
                    raw_payload.get("store_response_text", False),
                    field_name="privacy.store_response_text",
                ),
                store_prompt_hash=_require_bool(
                    raw_payload.get("store_prompt_hash", True),
                    field_name="privacy.store_prompt_hash",
                ),
            )

        if privacy.store_prompt_text:
            raise ValueError("privacy.store_prompt_text must remain false for live smoke")
        if privacy.store_response_text:
            raise ValueError("privacy.store_response_text must remain false for live smoke")
        if not privacy.store_prompt_hash:
            raise ValueError("privacy.store_prompt_hash must remain true for live smoke")
        return privacy


@dataclass(slots=True, frozen=True)
class LiveModelConfig:
    key: str
    model_id: str
    load: dict[str, LiveLoadFieldValue] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> LiveModelConfig:
        raw_payload = _require_mapping(payload, context="models[]")
        if "model_id" not in raw_payload:
            raise ValueError("models[].model_id is required")

        load_payload = raw_payload.get("load", {})
        if load_payload is None:
            load_payload = {}
        load_mapping = _require_mapping(load_payload, context="models[].load")
        normalized_load = {
            _require_non_empty_string(
                raw_key,
                field_name="models[].load key",
            ): _normalize_load_value(
                raw_value,
                field_name=f"models[].load.{raw_key}",
            )
            for raw_key, raw_value in load_mapping.items()
        }
        return cls(
            key=_require_non_empty_string(raw_payload.get("key"), field_name="models[].key"),
            model_id=_require_non_empty_string(
                raw_payload.get("model_id"),
                field_name="models[].model_id",
            ),
            load=normalized_load,
        )


@dataclass(slots=True, frozen=True)
class LiveSmokeConfig:
    experiment_id: str
    models: tuple[LiveModelConfig, ...]
    modes: tuple[str, ...]
    datasets: tuple[str, ...]
    repeats: int
    lmstudio_base_url: str = _DEFAULT_LMSTUDIO_BASE_URL
    allow_remote: bool = False
    hardware_profile: str | None = None
    warmup_runs: int = 0
    structured_prompt_variant: str = "baseline"
    structured_schema_variant: str = "baseline"
    business_failure_retry_limit: int = 0
    privacy: LivePrivacyConfig = field(default_factory=LivePrivacyConfig)


def _validate_datasets_are_synthetic(
    dataset_ids: Sequence[str],
    *,
    datasets_root: str | Path | None,
) -> None:
    for dataset_id in dataset_ids:
        try:
            manifest = load_dataset_manifest(dataset_id, datasets_root=datasets_root)
        except OSError as error:
            raise ValueError(
                f"dataset manifest could not be read for dataset_id {dataset_id!r}"
            ) from error
        if manifest.privacy != "synthetic":
            raise ValueError(f"dataset {dataset_id!r} must use synthetic privacy")


def load_live_smoke_config(
    path: str | Path,
    *,
    live_enabled: bool = False,
    datasets_root: str | Path | None = None,
) -> LiveSmokeConfig:
    if not live_enabled:
        raise ValueError("live smoke config requires explicit --live opt-in")

    try:
        _, raw_payload = load_raw_experiment_config(path)
    except OSError as error:
        raise ValueError("live smoke config could not be read") from error

    validate_experiment_config_payload(raw_payload)

    models_value = raw_payload.get("models")
    if not isinstance(models_value, Sequence) or isinstance(
        models_value,
        (str, bytes, bytearray),
    ):
        raise ValueError("models must be a list")

    models = tuple(LiveModelConfig.from_mapping(item) for item in models_value)
    if not models:
        raise ValueError("models must not be empty")

    allow_remote = _require_bool(
        raw_payload.get("allow_remote", False),
        field_name="allow_remote",
    )
    lmstudio_base_url = _normalize_url_text(
        raw_payload.get("lmstudio_base_url", _DEFAULT_LMSTUDIO_BASE_URL)
    )
    if not allow_remote and not is_local_lmstudio_base_url(lmstudio_base_url):
        raise ValueError("lmstudio_base_url must stay on localhost unless allow_remote is true")

    dataset_ids = _require_string_sequence(
        raw_payload.get("datasets"),
        field_name="datasets",
    )
    _validate_datasets_are_synthetic(dataset_ids, datasets_root=datasets_root)

    hardware_profile = raw_payload.get("hardware_profile")
    if hardware_profile is not None:
        hardware_profile = _require_non_empty_string(
            hardware_profile,
            field_name="hardware_profile",
        )

    return LiveSmokeConfig(
        experiment_id=_require_non_empty_string(
            raw_payload.get("experiment_id"),
            field_name="experiment_id",
        ),
        models=models,
        modes=_require_string_sequence(raw_payload.get("modes"), field_name="modes"),
        datasets=dataset_ids,
        repeats=_require_int(raw_payload.get("repeats"), field_name="repeats", minimum=1),
        lmstudio_base_url=lmstudio_base_url,
        allow_remote=allow_remote,
        hardware_profile=hardware_profile,
        warmup_runs=_require_int(
            raw_payload.get("warmup_runs", 0),
            field_name="warmup_runs",
            minimum=0,
        ),
        structured_prompt_variant=_require_structured_prompt_variant(
            raw_payload.get("structured_prompt_variant", "baseline"),
            field_name="structured_prompt_variant",
        ),
        structured_schema_variant=_require_structured_schema_variant(
            raw_payload.get("structured_schema_variant", "baseline"),
            field_name="structured_schema_variant",
        ),
        business_failure_retry_limit=_require_zero_or_one_int(
            raw_payload.get("business_failure_retry_limit", 0),
            field_name="business_failure_retry_limit",
        ),
        privacy=LivePrivacyConfig.from_mapping(raw_payload.get("privacy")),
    )


__all__ = [
    "LiveLoadFieldValue",
    "LiveLoadScalar",
    "LiveModelConfig",
    "LivePrivacyConfig",
    "LiveSmokeConfig",
    "STRUCTURED_PROMPT_VARIANT_CHOICES",
    "STRUCTURED_SCHEMA_VARIANT_CHOICES",
    "is_local_lmstudio_base_url",
    "load_live_smoke_config",
]
