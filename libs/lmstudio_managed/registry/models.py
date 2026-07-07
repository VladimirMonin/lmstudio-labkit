"""Pure registry catalog DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .identity import ModelIdentityFacts


class ProfilePurpose(StrEnum):
    FACTUAL_BLOCKS = "factual_blocks"
    PLAIN_TEXT_ARTIFACTS = "plain_text_artifacts"
    VISION = "vision"
    EMBEDDINGS = "embeddings"


class ProfileStatus(StrEnum):
    LAB_BASELINE = "lab_baseline"
    LAB_CANDIDATE = "lab_candidate"
    LAB_CANDIDATE_HEAVIER = "lab_candidate_heavier"
    RECOVERY_TRACK = "recovery_track"
    NOT_CANDIDATE_YET = "not_candidate_yet"


class ModelVerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    COMPAT_VERIFIED = "compat_verified"
    NATIVE_VERIFIED = "native_verified"
    VERIFIED = "verified"


class ModelCapability(StrEnum):
    TEXT_GENERATION = "text_generation"
    STRUCTURED_JSON = "structured_json"
    PLAIN_TEXT = "plain_text"
    VISION = "vision"
    EMBEDDINGS = "embeddings"


@dataclass(frozen=True, slots=True)
class ModelEvidenceRef:
    run_id: str
    summary_ref: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    candidate_key: str
    source_id: str | None = None
    compat_model_id: str | None = None
    native_model_key: str | None = None
    verification_status: ModelVerificationStatus = ModelVerificationStatus.UNVERIFIED


@dataclass(frozen=True, slots=True)
class ModelProfileRecommendation:
    profile_id: str
    model_key: str
    purpose: ProfilePurpose
    status: ProfileStatus
    production_default: bool = False
    evidence_refs: tuple[ModelEvidenceRef, ...] = ()
    max_tokens: int | None = None
    load_parallel: int | None = None
    app_concurrency: int | None = None


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    identity: ModelIdentity
    capabilities: tuple[ModelCapability, ...] = ()
    recommendations: tuple[ModelProfileRecommendation, ...] = ()
    notes: str | None = None


__all__ = [
    "ModelCandidate",
    "ModelCapability",
    "ModelEvidenceRef",
    "ModelIdentity",
    "ModelIdentityFacts",
    "ModelProfileRecommendation",
    "ModelVerificationStatus",
    "ProfilePurpose",
    "ProfileStatus",
]
