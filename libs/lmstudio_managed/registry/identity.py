"""Identity facts kept separate from runtime/provider IDs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelIdentityFacts:
    """Verified identity facts for a model across Lab/native/compat surfaces."""

    candidate_key: str
    source_id: str | None = None
    compat_model_id: str | None = None
    native_model_key: str | None = None
    format: str | None = None
    bits_per_weight: float | None = None
    size_bytes: int | None = None
    params_label: str | None = None
    quantization: str | None = None
    ready_on_disk: bool = False
    identity_verified: bool = False
