from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from lmstudio_managed.registry import (
    ModelCandidate,
    ModelCapability,
    ModelEvidenceRef,
    ModelIdentity,
    ModelIdentityFacts,
    ModelProfileRecommendation,
    ModelVerificationStatus,
    ProfilePurpose,
    ProfileStatus,
)


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _string_value(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _bool_value(payload: Mapping[str, object], key: str, *, default: bool = False) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return default


def _int_value(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _float_value(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _sequence_value(payload: Mapping[str, object], key: str) -> Sequence[object]:
    value = payload.get(key)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return value
    return ()


def _candidate_key(candidate: Mapping[str, object]) -> str:
    candidate_key = _string_value(candidate, "candidate_key") or _string_value(candidate, "lab_key")
    if candidate_key is None:
        raise ValueError("Candidate payload must define candidate_key or lab_key.")
    return candidate_key


def _native_identity(candidate: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(candidate.get("native_identity"))


def _disk_state(candidate: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(candidate.get("disk_state"))


def _compat_model_id(candidate: Mapping[str, object]) -> str | None:
    return _string_value(candidate, "compat_model_id")


def _native_key_verified(candidate: Mapping[str, object]) -> bool:
    return _bool_value(_native_identity(candidate), "native_key_verified")


def _verification_status(candidate: Mapping[str, object]) -> ModelVerificationStatus:
    compat_model_id = _compat_model_id(candidate)
    native_verified = _native_key_verified(candidate)
    if native_verified and compat_model_id is not None:
        return ModelVerificationStatus.VERIFIED
    if native_verified:
        return ModelVerificationStatus.NATIVE_VERIFIED
    if compat_model_id is not None:
        return ModelVerificationStatus.COMPAT_VERIFIED
    return ModelVerificationStatus.UNVERIFIED


def _capabilities_from_candidate_payload(
    candidate: Mapping[str, object],
) -> tuple[ModelCapability, ...]:
    capabilities = [ModelCapability.TEXT_GENERATION]
    native_identity = _native_identity(candidate)
    native_capabilities = _sequence_value(native_identity, "capabilities")
    if any(
        isinstance(value, str) and value.strip().lower() == "vision"
        for value in native_capabilities
    ):
        capabilities.append(ModelCapability.VISION)
    return tuple(dict.fromkeys(capabilities))


def _model_key_from_recommendation_payload(payload: Mapping[str, object]) -> str:
    model_key = _string_value(payload, "model_key")
    candidate_key = _string_value(payload, "candidate_key")
    alias_model_key = _string_value(payload, "model")

    resolved = model_key or candidate_key or alias_model_key
    if resolved is None:
        raise ValueError("Recommendation payload must define model_key or candidate_key.")
    if model_key is not None and candidate_key is not None and model_key != candidate_key:
        raise ValueError("Recommendation payload model_key/candidate_key mismatch.")
    if model_key is not None and alias_model_key is not None and model_key != alias_model_key:
        raise ValueError("Recommendation payload model/model_key mismatch.")
    return resolved


_SAFE_EVIDENCE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _safe_evidence_label(value: str | None) -> str | None:
    if value is None:
        return None

    label = value.strip()
    if not label:
        return None
    if any(character.isspace() for character in label):
        return None
    if "/" in label or "\\" in label or ":" in label:
        return None
    if not _SAFE_EVIDENCE_LABEL_RE.fullmatch(label):
        return None
    return label


def _evidence_ref_from_payload(payload: Mapping[str, object]) -> ModelEvidenceRef | None:
    run_id = (
        _safe_evidence_label(_string_value(payload, "run_id"))
        or _safe_evidence_label(_string_value(payload, "observed_by"))
        or _safe_evidence_label(_string_value(payload, "observed_after"))
    )
    if run_id is None:
        return None

    summary_ref = _safe_evidence_label(_string_value(payload, "summary_ref"))
    if summary_ref is None:
        summary_ref = _safe_evidence_label(_string_value(payload, "source"))

    return ModelEvidenceRef(
        run_id=run_id,
        summary_ref=summary_ref,
        notes=_string_value(payload, "notes"),
    )


def _evidence_refs_from_payload(payload: Mapping[str, object]) -> tuple[ModelEvidenceRef, ...]:
    raw_refs = _sequence_value(payload, "evidence_refs")
    if raw_refs:
        evidence_refs: list[ModelEvidenceRef] = []
        for raw_ref in raw_refs:
            evidence_ref = _evidence_ref_from_payload(_mapping(raw_ref))
            if evidence_ref is not None:
                evidence_refs.append(evidence_ref)
        return tuple(evidence_refs)

    evidence_ref = _evidence_ref_from_payload(payload)
    if evidence_ref is None:
        return ()
    return (evidence_ref,)


def model_identity_facts_from_candidate_payload(
    candidate: Mapping[str, object],
) -> ModelIdentityFacts:
    native_identity = _native_identity(candidate)
    return ModelIdentityFacts(
        candidate_key=_candidate_key(candidate),
        source_id=_string_value(candidate, "source_id"),
        compat_model_id=_compat_model_id(candidate),
        native_model_key=_string_value(native_identity, "native_model_key"),
        format=_string_value(native_identity, "format"),
        bits_per_weight=_float_value(native_identity, "bits_per_weight"),
        size_bytes=_int_value(native_identity, "size_bytes"),
        params_label=_string_value(native_identity, "params"),
        quantization=_string_value(native_identity, "quantization"),
        ready_on_disk=_bool_value(_disk_state(candidate), "ready_on_disk"),
        identity_verified=_native_key_verified(candidate),
    )


def model_identity_from_candidate_payload(candidate: Mapping[str, object]) -> ModelIdentity:
    native_identity = _native_identity(candidate)
    return ModelIdentity(
        candidate_key=_candidate_key(candidate),
        source_id=_string_value(candidate, "source_id"),
        compat_model_id=_compat_model_id(candidate),
        native_model_key=_string_value(native_identity, "native_model_key"),
        verification_status=_verification_status(candidate),
    )


def model_candidate_from_payload(
    candidate: Mapping[str, object],
    recommendations: Sequence[ModelProfileRecommendation] = (),
) -> ModelCandidate:
    return ModelCandidate(
        identity=model_identity_from_candidate_payload(candidate),
        capabilities=_capabilities_from_candidate_payload(candidate),
        recommendations=tuple(recommendations),
    )


def managed_candidates_from_registry_payload(
    payload: Mapping[str, object],
    recommendations_by_candidate_key: Mapping[str, Sequence[ModelProfileRecommendation]]
    | None = None,
) -> tuple[ModelCandidate, ...]:
    recommendations_by_candidate_key = recommendations_by_candidate_key or {}
    candidates: list[ModelCandidate] = []
    for raw_candidate in _sequence_value(payload, "candidates"):
        candidate = _mapping(raw_candidate)
        candidate_key = _candidate_key(candidate)
        candidates.append(
            model_candidate_from_payload(
                candidate,
                recommendations=recommendations_by_candidate_key.get(candidate_key, ()),
            )
        )
    return tuple(candidates)


def profile_recommendation_from_payload(
    payload: Mapping[str, object],
) -> ModelProfileRecommendation:
    production_default = payload.get("production_default")
    if production_default not in (None, False):
        raise ValueError("Lab profile recommendations must not declare production defaults.")

    purpose_value = _string_value(payload, "purpose")
    if purpose_value is None:
        raise ValueError("Recommendation payload must define purpose.")

    status_value = _string_value(payload, "status")
    if status_value is None:
        raise ValueError("Recommendation payload must define status.")

    profile_id = _string_value(payload, "profile_id")
    if profile_id is None:
        raise ValueError("Recommendation payload must define profile_id.")

    return ModelProfileRecommendation(
        profile_id=profile_id,
        model_key=_model_key_from_recommendation_payload(payload),
        purpose=ProfilePurpose(purpose_value),
        status=ProfileStatus(status_value),
        production_default=False,
        evidence_refs=_evidence_refs_from_payload(payload),
        max_tokens=_int_value(payload, "max_tokens"),
        load_parallel=_int_value(payload, "load_parallel"),
        app_concurrency=_int_value(payload, "app_concurrency"),
    )


__all__ = [
    "managed_candidates_from_registry_payload",
    "model_candidate_from_payload",
    "model_identity_facts_from_candidate_payload",
    "model_identity_from_candidate_payload",
    "profile_recommendation_from_payload",
]
