from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

import yaml

from .privacy import find_privacy_violations

type LoadScalar = bool | int | str
type LoadFieldValue = LoadScalar | tuple[LoadScalar, ...]


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


def _require_int(value: Any, *, field_name: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    return value


def _require_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _require_string_sequence(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field_name} must be a list of strings")

    items = [_require_non_empty_string(item, field_name=f"{field_name}[]") for item in value]
    if not items:
        raise ValueError(f"{field_name} must not be empty")
    return tuple(items)


def _normalize_load_scalar(value: Any, *, field_name: str) -> LoadScalar:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _require_non_empty_string(value, field_name=field_name)
    raise ValueError(f"{field_name} must use bool, int, or string values")


def _normalize_load_value(value: Any, *, field_name: str) -> LoadFieldValue:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized_items = tuple(
            _normalize_load_scalar(item, field_name=field_name) for item in value
        )
        if not normalized_items:
            raise ValueError(f"{field_name} list must not be empty")
        return normalized_items
    return _normalize_load_scalar(value, field_name=field_name)


@dataclass(slots=True, frozen=True)
class PrivacyConfig:
    store_prompt_text: bool = False
    store_response_text: bool = False
    store_prompt_hash: bool = True

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> PrivacyConfig:
        if payload is None:
            return cls()

        raw_payload = _require_mapping(payload, context="privacy")
        return cls(
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

    def to_dict(self) -> dict[str, bool]:
        return {
            "store_prompt_hash": self.store_prompt_hash,
            "store_prompt_text": self.store_prompt_text,
            "store_response_text": self.store_response_text,
        }


@dataclass(slots=True, frozen=True)
class ModelConfig:
    key: str
    load: dict[str, LoadFieldValue] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ModelConfig:
        raw_payload = _require_mapping(payload, context="models[]")
        load_payload = raw_payload.get("load", {})
        if load_payload is None:
            load_payload = {}
        load_mapping = _require_mapping(load_payload, context="models[].load")
        normalized_load = {
            _require_non_empty_string(
                raw_key, field_name="models[].load key"
            ): _normalize_load_value(
                raw_value,
                field_name=f"models[].load.{raw_key}",
            )
            for raw_key, raw_value in load_mapping.items()
        }
        return cls(
            key=_require_non_empty_string(raw_payload.get("key"), field_name="models[].key"),
            load=normalized_load,
        )

    def iter_load_configs(self) -> tuple[dict[str, LoadScalar], ...]:
        if not self.load:
            return ({},)

        load_items = []
        for key, value in self.load.items():
            values = list(value) if isinstance(value, tuple) else [value]
            load_items.append((key, values))

        variants: list[dict[str, LoadScalar]] = []
        keys = [key for key, _ in load_items]
        value_groups = [values for _, values in load_items]
        for combination in product(*value_groups):
            variants.append(dict(zip(keys, combination, strict=True)))
        return tuple(variants)

    def to_dict(self) -> dict[str, Any]:
        normalized_load: dict[str, Any] = {}
        for key, value in self.load.items():
            normalized_load[key] = list(value) if isinstance(value, tuple) else value
        return {"key": self.key, "load": normalized_load}


@dataclass(slots=True, frozen=True)
class ExperimentConfig:
    experiment_id: str
    models: tuple[ModelConfig, ...]
    modes: tuple[str, ...]
    datasets: tuple[str, ...]
    repeats: int
    hardware_profile: str | None = None
    lmstudio_base_url: str | None = "http://127.0.0.1:1234"
    warmup_runs: int = 0
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "experiment_id": self.experiment_id,
            "models": [model.to_dict() for model in self.models],
            "modes": list(self.modes),
            "datasets": list(self.datasets),
            "repeats": self.repeats,
            "warmup_runs": self.warmup_runs,
            "privacy": self.privacy.to_dict(),
        }
        if self.hardware_profile is not None:
            payload["hardware_profile"] = self.hardware_profile
        if self.lmstudio_base_url is not None:
            payload["lmstudio_base_url"] = self.lmstudio_base_url
        return payload


def load_raw_experiment_config(path: str | Path) -> tuple[str, Mapping[str, Any]]:
    config_path = Path(path)
    config_text = config_path.read_text(encoding="utf-8")
    payload = yaml.safe_load(config_text)
    return config_text, _require_mapping(payload, context="experiment config")


def validate_experiment_config_payload(payload: Mapping[str, Any]) -> None:
    violations = find_privacy_violations(payload, context="experiment config")
    if violations:
        raise ValueError(f"unsafe experiment config: {violations[0]}")


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    _, raw_payload = load_raw_experiment_config(path)

    models_value = raw_payload.get("models")
    if not isinstance(models_value, Sequence) or isinstance(models_value, (str, bytes, bytearray)):
        raise ValueError("models must be a list")

    models = tuple(ModelConfig.from_mapping(item) for item in models_value)
    if not models:
        raise ValueError("models must not be empty")

    hardware_profile = raw_payload.get("hardware_profile")
    if hardware_profile is not None:
        hardware_profile = _require_non_empty_string(
            hardware_profile,
            field_name="hardware_profile",
        )

    lmstudio_base_url = raw_payload.get("lmstudio_base_url", "http://127.0.0.1:1234")
    if lmstudio_base_url is not None:
        lmstudio_base_url = _require_non_empty_string(
            lmstudio_base_url,
            field_name="lmstudio_base_url",
        )

    return ExperimentConfig(
        experiment_id=_require_non_empty_string(
            raw_payload.get("experiment_id"),
            field_name="experiment_id",
        ),
        models=models,
        modes=_require_string_sequence(raw_payload.get("modes"), field_name="modes"),
        datasets=_require_string_sequence(
            raw_payload.get("datasets"),
            field_name="datasets",
        ),
        repeats=_require_int(raw_payload.get("repeats"), field_name="repeats", minimum=1),
        hardware_profile=hardware_profile,
        lmstudio_base_url=lmstudio_base_url,
        warmup_runs=_require_int(
            raw_payload.get("warmup_runs", 0),
            field_name="warmup_runs",
            minimum=0,
        ),
        privacy=PrivacyConfig.from_mapping(raw_payload.get("privacy")),
    )


__all__ = [
    "ExperimentConfig",
    "LoadFieldValue",
    "LoadScalar",
    "ModelConfig",
    "PrivacyConfig",
    "load_raw_experiment_config",
    "load_experiment_config",
    "validate_experiment_config_payload",
]
