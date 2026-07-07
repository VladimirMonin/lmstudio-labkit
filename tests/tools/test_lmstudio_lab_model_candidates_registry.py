from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from libs.lmstudio_managed.registry import ModelCapability, ModelVerificationStatus
from tools.lmstudio_lab.registry_bridge import (
    managed_candidates_from_registry_payload,
    model_candidate_from_payload,
    model_identity_facts_from_candidate_payload,
    profile_recommendation_from_payload,
)

REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "experiments" / "lmstudio" / "models" / "candidates.yaml"
)


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _candidate_by_lab_key(registry: dict, lab_key: str) -> dict:
    return next(
        candidate for candidate in registry["candidates"] if candidate["lab_key"] == lab_key
    )


def test_candidates_registry_has_exactly_four_unique_lab_keys() -> None:
    registry = _load_registry()

    lab_keys = [candidate["lab_key"] for candidate in registry["candidates"]]

    assert len(lab_keys) == 4
    assert len(set(lab_keys)) == 4


def test_candidates_registry_keeps_unresolved_compat_ids_null() -> None:
    registry = _load_registry()

    unresolved = [
        candidate
        for candidate in registry["candidates"]
        if candidate["compat_model_id_status"] == "pending_safe_resolution"
    ]

    assert len(unresolved) == 0
    assert all(candidate["compat_model_id"] is None for candidate in unresolved)


def test_qwen35_4b_q4km_candidate_records_lab_verified_registry_fields() -> None:
    registry = _load_registry()

    candidate = next(
        candidate
        for candidate in registry["candidates"]
        if candidate["lab_key"] == "qwen35_4b_q4km"
    )

    assert candidate["compat_model_id"] == "qwen3.5-4b"
    assert candidate["structured_output_policy"] == "blocked"
    assert candidate["compat_model_id_status"] == "lab_verified"
    assert candidate["compat_resolution"] == {
        "status": "lab_verified",
        "source": "acquisition_and_native_lifecycle_lab",
        "exact_visible_id": True,
    }
    assert candidate["native_identity"] == {
        "native_model_key": "qwen3.5-4b",
        "native_key_verified": True,
        "format": "gguf",
        "quantization": "Q4_K_M",
        "quantization_verified": True,
        "bits_per_weight": 4,
        "params": "4B",
        "size_bytes": 3383082464,
        "source_verified_by_native_list": True,
    }
    assert candidate["disk_state"] == {
        "ready_on_disk": True,
        "observed_by": "acq_live_qwen35_4b_q4km_001",
    }
    assert candidate["last_observed_load_state"] == {
        "loaded_instances": 0,
        "observed_after": "l4c_unload_happy_qwen35_4b_001",
        "loaded_in_ram_vram": False,
    }


def test_gemma4_e4b_q4km_candidate_records_lab_verified_registry_fields() -> None:
    registry = _load_registry()

    candidate = next(
        candidate
        for candidate in registry["candidates"]
        if candidate["lab_key"] == "gemma4_e4b_q4km"
    )

    assert candidate["compat_model_id"] == "google/gemma-4-e4b"
    assert candidate["structured_output_policy"] == "candidate_heavy"
    assert candidate["compat_model_id_status"] == "lab_verified"
    assert candidate["compat_resolution"] == {
        "status": "lab_verified",
        "source": "identity_probe_lab",
        "exact_visible_id": True,
    }
    assert candidate["native_identity"] == {
        "native_model_key": "google/gemma-4-e4b",
        "native_key_verified": True,
        "format": "gguf",
        "quantization": None,
        "quantization_verified": False,
        "bits_per_weight": 4,
        "params": None,
        "size_bytes": 6326932336,
        "source_verified_by_native_list": True,
    }
    assert candidate["disk_state"] == {
        "ready_on_disk": True,
        "observed_by": "m0_3_identity_gemma4_e4b_002",
    }
    assert candidate["load_echo"] == {
        "context_length": 8192,
        "parallel": 1,
        "context_length_verified": True,
        "parallel_verified": True,
        "observed_by": "l4j_policy_backed_smoke_gemma4_e4b_001",
    }
    assert candidate["last_observed_load_state"] == {
        "loaded_instances": 0,
        "observed_after": "l4j_policy_backed_smoke_gemma4_e4b_001",
        "loaded_in_ram_vram": False,
    }
    assert candidate["status"] == "lab_verified"


def test_qwen35_9b_q4km_candidate_records_lab_verified_registry_fields() -> None:
    registry = _load_registry()

    candidate = _candidate_by_lab_key(registry, "qwen35_9b_q4km")

    assert candidate["compat_model_id"] == "qwen/qwen3.5-9b"
    assert candidate["structured_output_policy"] == "recovery_only"
    assert candidate["compat_model_id_status"] == "lab_verified"
    assert candidate["compat_resolution"] == {
        "status": "lab_verified",
        "source": "identity_probe_lab",
        "exact_visible_id": True,
    }
    assert candidate["native_identity"] == {
        "native_model_key": "qwen/qwen3.5-9b",
        "native_key_verified": True,
        "format": "gguf",
        "quantization": None,
        "quantization_verified": False,
        "bits_per_weight": 4,
        "params": None,
        "size_bytes": 6548927711,
        "capabilities": ["reasoning", "trained_for_tool_use", "vision"],
        "source_verified_by_native_list": True,
    }
    assert candidate["disk_state"] == {
        "ready_on_disk": True,
        "observed_by": "m0_6_identity_qwen35_9b_001",
    }
    assert candidate["load_echo"] == {
        "context_length": 8192,
        "parallel": 1,
        "context_length_verified": True,
        "parallel_verified": True,
        "observed_by": "m0_7_policy_backed_smoke_qwen35_9b_001",
    }
    assert candidate["last_observed_load_state"] == {
        "loaded_instances": 0,
        "observed_after": "m0_7_policy_backed_smoke_qwen35_9b_001",
        "loaded_in_ram_vram": False,
    }
    assert candidate["status"] == "lab_verified"


def test_each_yaml_candidate_maps_to_managed_model_candidate_without_lab_key_field() -> None:
    registry = _load_registry()

    managed_candidates = managed_candidates_from_registry_payload(registry)

    assert len(managed_candidates) == len(registry["candidates"])

    for raw_candidate, managed_candidate in zip(
        registry["candidates"], managed_candidates, strict=True
    ):
        assert managed_candidate.identity.candidate_key == raw_candidate["lab_key"]
        assert not hasattr(managed_candidate.identity, "lab_key")

    baseline_candidate = next(
        candidate
        for candidate in managed_candidates
        if candidate.identity.candidate_key == "gemma4_e2b_q4km"
    )
    verified_candidate = next(
        candidate
        for candidate in managed_candidates
        if candidate.identity.candidate_key == "qwen35_4b_q4km"
    )

    assert (
        baseline_candidate.identity.verification_status == ModelVerificationStatus.COMPAT_VERIFIED
    )
    assert verified_candidate.identity.verification_status == ModelVerificationStatus.VERIFIED


def test_candidate_without_compat_id_but_with_native_identity_maps_native_verified_status() -> None:
    candidate = model_candidate_from_payload(
        {
            "lab_key": "native_only_candidate",
            "native_identity": {"native_key_verified": True},
        }
    )

    assert candidate.identity.verification_status == ModelVerificationStatus.NATIVE_VERIFIED


def test_candidate_without_native_or_compat_verification_maps_unverified_status() -> None:
    candidate = model_candidate_from_payload({"lab_key": "unverified_candidate"})

    assert candidate.identity.verification_status == ModelVerificationStatus.UNVERIFIED


def test_qwen_and_gemma_identity_facts_map_to_managed_registry_dto() -> None:
    registry = _load_registry()

    qwen_candidate = _candidate_by_lab_key(registry, "qwen35_4b_q4km")
    gemma_candidate = _candidate_by_lab_key(registry, "gemma4_e4b_q4km")

    qwen_identity = model_identity_facts_from_candidate_payload(qwen_candidate)
    gemma_identity = model_identity_facts_from_candidate_payload(gemma_candidate)

    assert qwen_identity.candidate_key == "qwen35_4b_q4km"
    assert qwen_identity.source_id == qwen_candidate["source_id"]
    assert qwen_identity.compat_model_id == "qwen3.5-4b"
    assert qwen_identity.native_model_key == "qwen3.5-4b"
    assert qwen_identity.format == "gguf"
    assert qwen_identity.bits_per_weight == 4.0
    assert qwen_identity.size_bytes == 3383082464
    assert qwen_identity.params_label == "4B"
    assert qwen_identity.quantization == "Q4_K_M"
    assert qwen_identity.ready_on_disk is True
    assert qwen_identity.identity_verified is True

    assert gemma_identity.candidate_key == "gemma4_e4b_q4km"
    assert gemma_identity.compat_model_id == "google/gemma-4-e4b"
    assert gemma_identity.native_model_key == "google/gemma-4-e4b"
    assert gemma_identity.bits_per_weight == 4.0
    assert gemma_identity.size_bytes == 6326932336
    assert gemma_identity.params_label is None
    assert gemma_identity.quantization is None
    assert gemma_identity.ready_on_disk is True
    assert gemma_identity.identity_verified is True


def test_qwen35_9b_candidate_maps_vision_capability_without_invented_extra_capabilities() -> None:
    registry = _load_registry()

    candidate = model_candidate_from_payload(_candidate_by_lab_key(registry, "qwen35_9b_q4km"))

    assert ModelCapability.TEXT_GENERATION in candidate.capabilities
    assert ModelCapability.VISION in candidate.capabilities
    assert ModelCapability.STRUCTURED_JSON not in candidate.capabilities
    assert ModelCapability.PLAIN_TEXT not in candidate.capabilities
    assert ModelCapability.EMBEDDINGS not in candidate.capabilities


def test_structured_output_policy_keeps_gemma_candidates_primary_and_qwen_non_default() -> None:
    registry = _load_registry()

    gemma_e2b = _candidate_by_lab_key(registry, "gemma4_e2b_q4km")
    qwen_4b = _candidate_by_lab_key(registry, "qwen35_4b_q4km")
    qwen_9b = _candidate_by_lab_key(registry, "qwen35_9b_q4km")

    assert gemma_e2b["structured_output_policy"] == "candidate_primary"
    assert qwen_4b["structured_output_policy"] == "blocked"
    assert qwen_9b["structured_output_policy"] == "recovery_only"

    for candidate in (qwen_4b, qwen_9b):
        recommendations = candidate.get("profile_recommendations", [])
        assert all(
            not (
                recommendation.get("purpose")
                in {"factual_blocks", "strict_json", "production_structured_output"}
                and recommendation.get("production_default") is True
            )
            for recommendation in recommendations
        )


def test_profile_recommendation_payload_maps_to_safe_managed_registry_dto() -> None:
    recommendation = profile_recommendation_from_payload(
        {
            "profile_id": "gemma4_e4b_structured_medium_true_parallel2",
            "candidate_key": "gemma4_e4b_q4km",
            "purpose": "factual_blocks",
            "status": "lab_candidate_heavier",
            "production_default": False,
            "max_tokens": 768,
            "load_parallel": 2,
            "app_concurrency": 2,
            "evidence_refs": [
                {
                    "observed_by": "r2_m1_structured_gemma4_e4b_001",
                    "summary_ref": "lmstudio_lab_summary_gemma4_e4b_r2",
                    "summary_path": "private_summary_marker",
                }
            ],
        }
    )

    assert recommendation.profile_id == "gemma4_e4b_structured_medium_true_parallel2"
    assert recommendation.model_key == "gemma4_e4b_q4km"
    assert recommendation.production_default is False
    assert recommendation.max_tokens == 768
    assert recommendation.load_parallel == 2
    assert recommendation.app_concurrency == 2
    assert len(recommendation.evidence_refs) == 1
    assert recommendation.evidence_refs[0].run_id == "r2_m1_structured_gemma4_e4b_001"
    assert recommendation.evidence_refs[0].summary_ref == "lmstudio_lab_summary_gemma4_e4b_r2"
    assert not hasattr(recommendation.evidence_refs[0], "summary_path")


def test_profile_recommendation_rejects_production_default_true() -> None:
    with pytest.raises(
        ValueError, match="Lab profile recommendations must not declare production defaults."
    ):
        profile_recommendation_from_payload(
            {
                "profile_id": "bad_default",
                "candidate_key": "gemma4_e4b_q4km",
                "purpose": "factual_blocks",
                "status": "lab_candidate",
                "production_default": True,
            }
        )


def test_profile_recommendation_ignores_unsafe_source_for_evidence_identity_fields() -> None:
    recommendation = profile_recommendation_from_payload(
        {
            "profile_id": "safe_source_guard",
            "candidate_key": "gemma4_e4b_q4km",
            "purpose": "factual_blocks",
            "status": "lab_candidate",
            "evidence_refs": [
                {
                    "observed_by": "safe_observation_001",
                    "source": "https://example.test/private/run-001",
                }
            ],
        }
    )

    assert len(recommendation.evidence_refs) == 1
    assert recommendation.evidence_refs[0].run_id == "safe_observation_001"
    assert recommendation.evidence_refs[0].summary_ref is None


def test_managed_candidates_from_registry_payload_matches_yaml_candidate_count() -> None:
    registry = _load_registry()

    managed_candidates = managed_candidates_from_registry_payload(registry)

    assert len(managed_candidates) == len(registry["candidates"])
