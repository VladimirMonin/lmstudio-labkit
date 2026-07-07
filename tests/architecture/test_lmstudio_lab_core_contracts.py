from __future__ import annotations

# ruff: noqa: I001

from dataclasses import replace
from pathlib import Path

import yaml

from libs.lmstudio_managed.core_contracts import (
    ExperimentIdentity,
    ExperimentStatus,
    ManagedCoreContract,
    ResultClassification,
    RouteMode,
    RouteObservation,
    SafetyFlags,
)
from libs.lmstudio_managed.registry.candidate_intake import build_candidate_model_intake_catalog
from libs.lmstudio_managed.registry.candidate_execution import (
    CandidateExecutionGateStatus,
    CandidateExecutionRecord,
    build_candidate_execution_catalog,
)
from libs.lmstudio_managed.registry.profiles import build_initial_model_registry
from libs.lmstudio_managed.registry.recommendations import (
    InternalModelRecommendation,
    InternalRecommendationStatus,
    InternalRouteGuidance,
    build_internal_recommendation_draft,
)
from libs.lmstudio_managed.registry.structured_matrix import build_structured_json_validation_matrix

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_candidate_intake_profiles_stay_lab_only_and_non_runtime() -> None:
    catalog = build_candidate_model_intake_catalog()

    for candidate in catalog.candidates:
        assert candidate.production_default is False
        assert candidate.final_user_facing_recommendation is False
        assert hasattr(candidate, "wvm_runtime_integration") is False

    assert catalog.hardware_feasibility.load_only_required_before_live is True


def test_l3_8_candidate_execution_records_stay_lab_only_and_non_runtime() -> None:
    catalog = build_candidate_execution_catalog()
    record = catalog.require("gemma4_e4b_q4km")

    assert record.no_live_feasibility_status == (
        CandidateExecutionGateStatus.NO_LIVE_FEASIBILITY_PASSED
    )
    assert record.load_only_16k_32k_status == CandidateExecutionGateStatus.LOAD_ONLY_PASSED
    assert record.tiny_live_smoke_status == (CandidateExecutionGateStatus.TINY_LIVE_SMOKE_PASSED)
    assert record.structured_json_status == CandidateExecutionGateStatus.STRUCTURED_JSON_PASSED
    assert record.route_matrix_blocked is True
    assert record.production_default is False
    assert record.wvm_runtime_integration is False
    assert record.kv_reuse_proven is False
    assert record.final_user_facing_recommendation is False


def test_l3_8d_strict_json_smoke_config_cannot_promote_production_runtime_or_user_flags() -> None:
    config_path = (
        PROJECT_ROOT
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_8d_gemma4_e4b_strict_json_smoke.yaml"
    )
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert payload["experiment_id"] == "l3_8d_gemma4_e4b_strict_json_smoke"
    assert payload["mode"] == "strict_json_smoke"
    assert payload["generation"]["route"] == "strict_json_chat_completions"
    assert payload["generation"]["endpoint_path"] == "/v1/chat/completions"
    assert payload["generation"]["max_tokens"] == 512
    assert payload["safety"]["generation_allowed"] is True
    assert payload["safety"]["live_25k_authorized"] is False
    assert payload["safety"]["production_default"] is False
    assert payload["safety"]["wvm_runtime_integration"] is False
    assert payload["safety"]["kv_reuse_proven"] is False
    assert payload["safety"]["final_user_facing_recommendation"] is False


def test_l3_9b_gemma_family_configs_do_not_define_promotion_or_runtime_fields() -> None:
    config_dir = PROJECT_ROOT / "experiments" / "lmstudio" / "configs"

    for config_name, experiment_id, model_key, model_id in (
        (
            "l3_9b_gemma_family_blocks_json_gemma4_e2b.yaml",
            "l3_9b_gemma_family_blocks_json_gemma4_e2b",
            "gemma4_e2b_q4km",
            "google/gemma-4-e2b",
        ),
        (
            "l3_9b_gemma_family_blocks_json_gemma4_e4b.yaml",
            "l3_9b_gemma_family_blocks_json_gemma4_e4b",
            "gemma4_e4b_q4km",
            "google/gemma-4-e4b",
        ),
    ):
        config_path = config_dir / config_name
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config_text = config_path.read_text(encoding="utf-8")

        assert payload["experiment_id"] == experiment_id
        assert payload["models"][0]["key"] == model_key
        assert payload["models"][0]["model_id"] == model_id
        assert payload["datasets"] == ["blocks_json_medium_chunked"]
        assert payload["modes"] == ["json_schema_single"]
        assert payload["repeats"] == 1
        assert payload["warmup_runs"] == 0
        assert payload["privacy"] == {
            "store_prompt_text": False,
            "store_response_text": False,
            "store_prompt_hash": True,
        }
        assert "production_default" not in payload
        assert "wvm_runtime_integration" not in payload
        assert "kv_reuse_proven" not in payload
        assert "final_user_facing_recommendation" not in payload
        assert "/v1/responses" not in config_text


def test_l3_9c_gemma4_12b_qat_managed_live_config_stays_lab_only_and_non_runtime() -> None:
    config_path = (
        PROJECT_ROOT
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_9c_gemma_family_blocks_json_gemma4_12b_qat.yaml"
    )
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_text = config_path.read_text(encoding="utf-8")

    assert payload["experiment_id"] == "l3_9c_gemma_family_blocks_json_gemma4_12b_qat"
    assert payload["hardware_profile"] == "local_manual"
    assert payload["lmstudio_base_url"] == "http://127.0.0.1:1234"
    assert payload["allow_remote"] is False
    assert payload["models"][0]["key"] == "gemma4_12b_qat"
    assert payload["models"][0]["model_id"] == "google/gemma-4-12b-qat"
    assert payload["models"][0]["load"] == {"context_length": [8192], "parallel": [1]}
    assert payload["datasets"] == ["blocks_json_medium_chunked"]
    assert payload["modes"] == ["json_schema_single"]
    assert payload["repeats"] == 1
    assert payload["warmup_runs"] == 0
    assert payload["prerequisites"] == {
        "load_only_evidence_dir": "experiments/lmstudio/results_summaries/run_l3-9c-gemma4-12b-qat-load-only-20260707_l3_9c_gemma4_12b_qat_load_only_8k_16k",
        "required_decision": "load_only_passed",
        "required_tiers": [8192, 16384],
        "require_final_loaded_instances": 0,
    }
    assert payload["privacy"] == {
        "store_prompt_text": False,
        "store_response_text": False,
        "store_prompt_hash": True,
    }
    assert "production_default" not in payload
    assert "wvm_runtime_integration" not in payload
    assert "kv_reuse_proven" not in payload
    assert "final_user_facing_recommendation" not in payload
    assert "/v1/responses" not in config_text


def test_l3_10a_gemma4_12b_qat_id_forensics_config_stays_lab_only_and_non_runtime() -> None:
    config_path = (
        PROJECT_ROOT
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_10a_gemma4_12b_qat_id_forensics.yaml"
    )
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_text = config_path.read_text(encoding="utf-8")

    assert payload["experiment_id"] == "l3_10a_gemma4_12b_qat_id_forensics"
    assert payload["hardware_profile"] == "local_manual"
    assert payload["lmstudio_base_url"] == "http://127.0.0.1:1234"
    assert payload["allow_remote"] is False
    assert payload["models"][0]["key"] == "gemma4_12b_qat"
    assert payload["models"][0]["model_id"] == "google/gemma-4-12b-qat"
    assert payload["models"][0]["load"] == {"context_length": [8192], "parallel": [1]}
    assert payload["datasets"] == ["blocks_json_medium_chunked"]
    assert payload["modes"] == ["json_schema_single"]
    assert payload["repeats"] == 1
    assert payload["warmup_runs"] == 0
    assert payload["prerequisites"] == {
        "load_only_evidence_dir": "experiments/lmstudio/results_summaries/run_l3-9c-gemma4-12b-qat-load-only-20260707_l3_9c_gemma4_12b_qat_load_only_8k_16k",
        "required_decision": "load_only_passed",
        "required_tiers": [8192, 16384],
        "require_final_loaded_instances": 0,
    }
    assert payload["privacy"] == {
        "store_prompt_text": False,
        "store_response_text": False,
        "store_prompt_hash": True,
    }
    assert "production_default" not in payload
    assert "wvm_runtime_integration" not in payload
    assert "kv_reuse_proven" not in payload
    assert "final_user_facing_recommendation" not in payload
    assert "/v1/responses" not in config_text


def test_l3_10c_prompt_variant_configs_stay_lab_only_and_non_runtime() -> None:
    config_dir = PROJECT_ROOT / "experiments" / "lmstudio" / "configs"

    for config_name, experiment_id, prompt_variant in (
        (
            "l3_10c_gemma4_12b_qat_prompt_strict_id_contract.yaml",
            "l3_10c_gemma4_12b_qat_prompt_strict_id_contract",
            "strict_id_contract",
        ),
        (
            "l3_10c_gemma4_12b_qat_prompt_ultra_minimal_transform.yaml",
            "l3_10c_gemma4_12b_qat_prompt_ultra_minimal_transform",
            "ultra_minimal_transform",
        ),
    ):
        config_path = config_dir / config_name
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config_text = config_path.read_text(encoding="utf-8")

        assert payload["experiment_id"] == experiment_id
        assert payload["hardware_profile"] == "local_manual"
        assert payload["lmstudio_base_url"] == "http://127.0.0.1:1234"
        assert payload["allow_remote"] is False
        assert payload["models"][0]["key"] == "gemma4_12b_qat"
        assert payload["models"][0]["model_id"] == "google/gemma-4-12b-qat"
        assert payload["models"][0]["load"] == {"context_length": [8192], "parallel": [1]}
        assert payload["datasets"] == ["blocks_json_medium_chunked"]
        assert payload["modes"] == ["json_schema_single"]
        assert payload["repeats"] == 1
        assert payload["warmup_runs"] == 0
        assert payload["structured_prompt_variant"] == prompt_variant
        assert payload["prerequisites"] == {
            "load_only_evidence_dir": "experiments/lmstudio/results_summaries/run_l3-9c-gemma4-12b-qat-load-only-20260707_l3_9c_gemma4_12b_qat_load_only_8k_16k",
            "required_decision": "load_only_passed",
            "required_tiers": [8192, 16384],
            "require_final_loaded_instances": 0,
        }
        assert payload["privacy"] == {
            "store_prompt_text": False,
            "store_response_text": False,
            "store_prompt_hash": True,
        }
        assert "production_default" not in payload
        assert "wvm_runtime_integration" not in payload
        assert "kv_reuse_proven" not in payload
        assert "final_user_facing_recommendation" not in payload
        assert "/v1/responses" not in config_text


def test_l3_10d_schema_variant_config_stays_lab_only_and_non_runtime() -> None:
    config_path = (
        PROJECT_ROOT
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_10d_gemma4_12b_qat_schema_per_position_id_const.yaml"
    )
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_text = config_path.read_text(encoding="utf-8")

    assert payload["experiment_id"] == "l3_10d_gemma4_12b_qat_schema_per_position_id_const"
    assert payload["hardware_profile"] == "local_manual"
    assert payload["lmstudio_base_url"] == "http://127.0.0.1:1234"
    assert payload["allow_remote"] is False
    assert payload["models"][0]["key"] == "gemma4_12b_qat"
    assert payload["models"][0]["model_id"] == "google/gemma-4-12b-qat"
    assert payload["models"][0]["load"] == {"context_length": [8192], "parallel": [1]}
    assert payload["datasets"] == ["blocks_json_medium_chunked"]
    assert payload["modes"] == ["json_schema_single"]
    assert payload["repeats"] == 1
    assert payload["warmup_runs"] == 0
    assert payload["structured_prompt_variant"] == "baseline"
    assert payload["structured_schema_variant"] == "per_position_id_const"
    assert payload["prerequisites"] == {
        "load_only_evidence_dir": "experiments/lmstudio/results_summaries/run_l3-9c-gemma4-12b-qat-load-only-20260707_l3_9c_gemma4_12b_qat_load_only_8k_16k",
        "required_decision": "load_only_passed",
        "required_tiers": [8192, 16384],
        "require_final_loaded_instances": 0,
    }
    assert payload["privacy"] == {
        "store_prompt_text": False,
        "store_response_text": False,
        "store_prompt_hash": True,
    }
    assert payload["safety"] == {
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
        "final_user_facing_recommendation": False,
    }
    assert "/v1/responses" not in config_text


def test_l3_10e_chunk_size_sensitivity_configs_stay_lab_only_and_non_runtime() -> None:
    config_dir = PROJECT_ROOT / "experiments" / "lmstudio" / "configs"

    for config_name, experiment_id, dataset_id in (
        (
            "l3_10e_gemma4_12b_qat_chunk_size_25.yaml",
            "l3_10e_gemma4_12b_qat_chunk_size_25",
            "blocks_json_medium_chunked",
        ),
        (
            "l3_10e_gemma4_12b_qat_chunk_size_10.yaml",
            "l3_10e_gemma4_12b_qat_chunk_size_10",
            "blocks_json_medium_chunked_10",
        ),
        (
            "l3_10e_gemma4_12b_qat_chunk_size_5.yaml",
            "l3_10e_gemma4_12b_qat_chunk_size_5",
            "blocks_json_medium_chunked_5",
        ),
    ):
        config_path = config_dir / config_name
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config_text = config_path.read_text(encoding="utf-8")

        assert payload["experiment_id"] == experiment_id
        assert payload["hardware_profile"] == "local_manual"
        assert payload["lmstudio_base_url"] == "http://127.0.0.1:1234"
        assert payload["allow_remote"] is False
        assert payload["models"][0]["key"] == "gemma4_12b_qat"
        assert payload["models"][0]["model_id"] == "google/gemma-4-12b-qat"
        assert payload["models"][0]["load"] == {"context_length": [8192], "parallel": [1]}
        assert payload["datasets"] == [dataset_id]
        assert payload["modes"] == ["json_schema_single"]
        assert payload["repeats"] == 1
        assert payload["warmup_runs"] == 0
        assert payload["structured_prompt_variant"] == "baseline"
        assert payload["structured_schema_variant"] == "baseline"
        assert payload["prerequisites"] == {
            "load_only_evidence_dir": "experiments/lmstudio/results_summaries/run_l3-9c-gemma4-12b-qat-load-only-20260707_l3_9c_gemma4_12b_qat_load_only_8k_16k",
            "required_decision": "load_only_passed",
            "required_tiers": [8192, 16384],
            "require_final_loaded_instances": 0,
        }
        assert payload["privacy"] == {
            "store_prompt_text": False,
            "store_response_text": False,
            "store_prompt_hash": True,
        }
        assert payload["safety"] == {
            "production_default": False,
            "wvm_runtime_integration": False,
            "kv_reuse_proven": False,
            "final_user_facing_recommendation": False,
        }
        assert "/v1/responses" not in config_text


def test_l3_10f_business_retry_config_stays_lab_only_and_non_runtime() -> None:
    config_path = (
        PROJECT_ROOT
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_10f_gemma4_12b_qat_business_retry.yaml"
    )
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_text = config_path.read_text(encoding="utf-8")

    assert payload["experiment_id"] == "l3_10f_gemma4_12b_qat_business_retry"
    assert payload["hardware_profile"] == "local_manual"
    assert payload["lmstudio_base_url"] == "http://127.0.0.1:1234"
    assert payload["allow_remote"] is False
    assert payload["models"][0]["key"] == "gemma4_12b_qat"
    assert payload["models"][0]["model_id"] == "google/gemma-4-12b-qat"
    assert payload["models"][0]["load"] == {"context_length": [8192], "parallel": [1]}
    assert payload["datasets"] == ["blocks_json_medium_chunked"]
    assert payload["modes"] == ["json_schema_single"]
    assert payload["repeats"] == 1
    assert payload["warmup_runs"] == 0
    assert payload["structured_prompt_variant"] == "baseline"
    assert payload["structured_schema_variant"] == "baseline"
    assert payload["business_failure_retry_limit"] == 1
    assert payload["prerequisites"] == {
        "load_only_evidence_dir": "experiments/lmstudio/results_summaries/run_l3-9c-gemma4-12b-qat-load-only-20260707_l3_9c_gemma4_12b_qat_load_only_8k_16k",
        "required_decision": "load_only_passed",
        "required_tiers": [8192, 16384],
        "require_final_loaded_instances": 0,
    }
    assert payload["privacy"] == {
        "store_prompt_text": False,
        "store_response_text": False,
        "store_prompt_hash": True,
    }
    assert payload["safety"] == {
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
        "final_user_facing_recommendation": False,
    }
    assert "/v1/responses" not in config_text


def test_l3_9c_and_l3_9d_load_only_configs_stay_lab_only_and_non_runtime() -> None:
    config_dir = PROJECT_ROOT / "experiments" / "lmstudio" / "configs"

    for config_name, experiment_id, mode, model_key, model_id, context_tiers in (
        (
            "l3_9c_gemma4_12b_qat_load_only_8k_16k.yaml",
            "l3_9c_gemma4_12b_qat_load_only_8k_16k",
            "candidate_load_only_8k_16k",
            "gemma4_12b_qat",
            "google/gemma-4-12b-qat",
            [8192, 16384],
        ),
        (
            "l3_9d_gemma4_26b_a4b_qat_load_only_8k.yaml",
            "l3_9d_gemma4_26b_a4b_qat_load_only_8k",
            "candidate_load_only_8k",
            "gemma4_26b_a4b_qat",
            "google/gemma-4-26b-a4b-qat",
            [8192],
        ),
    ):
        config_path = config_dir / config_name
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config_text = config_path.read_text(encoding="utf-8")

        assert payload["experiment_id"] == experiment_id
        assert payload["mode"] == mode
        assert payload["lmstudio_base_url"] == "http://127.0.0.1:1234"
        assert payload["allow_remote"] is False
        assert payload["model"]["key"] == model_key
        assert payload["model"]["lmstudio_model_id"] == model_id
        assert payload["load"]["context_tiers"] == context_tiers
        assert payload["load"]["parallel"] == 1
        assert payload["safety"]["generation_allowed"] is False
        assert payload["safety"]["live_25k_authorized"] is False
        assert payload["safety"]["production_default"] is False
        assert payload["safety"]["wvm_runtime_integration"] is False
        assert payload["safety"]["kv_reuse_proven"] is False
        assert "generation" not in payload
        assert "/v1/responses" not in config_text


def test_l3_9_gemma_family_collapse_plan_stays_lab_only_and_non_runtime() -> None:
    plan_path = (
        PROJECT_ROOT
        / "experiments"
        / "lmstudio"
        / "results_summaries"
        / "l3_9_gemma_family_collapse_plan.md"
    )
    plan_text = plan_path.read_text(encoding="utf-8")

    assert "blocks_json_medium_chunked" in plan_text
    assert "synthetic/privacy-safe" in plan_text
    assert "100 blocks" in plan_text
    assert "4 chunks" in plan_text
    assert "25 blocks per chunk" in plan_text
    assert "expected ids `0..99`" in plan_text
    assert "gemma4_e2b_q4km" in plan_text
    assert "google/gemma-4-e2b" in plan_text
    assert "gemma4_e4b_q4km" in plan_text
    assert "google/gemma-4-e4b" in plan_text
    assert "executable load-only 8k/16k evidence guard" in plan_text
    assert "L3.9d 26B remains load-only/capacity-only" in plan_text
    assert "production_default: `false`" in plan_text
    assert "wvm_runtime_integration: `false`" in plan_text
    assert "kv_reuse_proven: `false`" in plan_text
    assert "final_user_facing_recommendation: `false`" in plan_text
    assert "no `/v1/responses`" in plan_text
    assert "no route matrix" in plan_text
    assert "no WVM runtime integration" in plan_text


def test_l3_10_12b_id_drift_appeal_plan_stays_lab_only_and_sanitized() -> None:
    plan_path = (
        PROJECT_ROOT
        / "experiments"
        / "lmstudio"
        / "results_summaries"
        / "l3_10_12b_id_drift_appeal_plan.md"
    )
    plan_text = plan_path.read_text(encoding="utf-8")

    assert "L3.10a — failed-chunk ID forensics" in plan_text
    assert "batch_0001_chunk_0000" in plan_text
    assert "sha256:aed190389f285e69e5a4c53488f46c54f888d248fbfb79e97d7addb268c21c6b" in plan_text
    assert "expected_ids" in plan_text
    assert "returned_ids" in plan_text
    assert "duplicate_ids" in plan_text
    assert "reordered_positions" in plan_text
    assert "L3.10b deterministic reruns" in plan_text
    assert "strict_id_contract" in plan_text
    assert "ultra_minimal_transform" in plan_text
    assert "l3_10c_gemma4_12b_qat_prompt_strict_id_contract.yaml" in plan_text
    assert "l3_10c_gemma4_12b_qat_prompt_ultra_minimal_transform.yaml" in plan_text
    assert "L3.10g final decision" in plan_text
    assert "lab-only" in plan_text
    assert "no WVM runtime" in plan_text
    assert "no UI" in plan_text
    assert "no QueueManager" in plan_text
    assert "no `/v1/responses`" in plan_text
    assert "no route matrix" in plan_text
    assert "no 26B generation/live" in plan_text
    assert "sanitized artifacts only" in plan_text


def test_lab_only_contract_cannot_be_production_promoted() -> None:
    contract = ManagedCoreContract(
        identity=ExperimentIdentity(
            experiment_id="l3_6d_25k_mode_comparison_gemma4_e2b",
            run_id="run-l3-6d",
            lab_only=True,
            production_default=False,
            wvm_runtime_integration=False,
        ),
        safety=SafetyFlags(
            generation_allowed=True,
            live_25k_authorized=True,
            kv_reuse_proven=False,
        ),
        route_results=(
            RouteObservation(
                route=RouteMode.COMPACT_MEMORY,
                status=ExperimentStatus.PASSED,
                classification=ResultClassification.PRIMARY_CANDIDATE,
            ),
        ),
        status=ExperimentStatus.PASSED,
    )

    assert contract.is_production_promotable is False


def test_route_classification_change_alone_cannot_flip_production_gates() -> None:
    base_contract = ManagedCoreContract(
        identity=ExperimentIdentity(
            experiment_id="l3_7a_guardrail",
            run_id="run-l3-7a-guardrail",
            lab_only=True,
            production_default=False,
            wvm_runtime_integration=False,
        ),
        safety=SafetyFlags(
            generation_allowed=True,
            live_25k_authorized=True,
            kv_reuse_proven=False,
        ),
        route_results=(
            RouteObservation(
                route=RouteMode.STATELESS_FULL_PREFIX,
                status=ExperimentStatus.PASSED,
                classification=ResultClassification.BASELINE,
            ),
        ),
        status=ExperimentStatus.PASSED,
    )
    promoted_route_only = replace(
        base_contract,
        route_results=(
            RouteObservation(
                route=RouteMode.COMPACT_MEMORY,
                status=ExperimentStatus.PASSED,
                classification=ResultClassification.PRIMARY_CANDIDATE,
            ),
        ),
    )

    assert base_contract.identity.production_default is False
    assert base_contract.identity.wvm_runtime_integration is False
    assert base_contract.safety.kv_reuse_proven is False
    assert base_contract.is_production_promotable is False

    assert promoted_route_only.identity.production_default is False
    assert promoted_route_only.identity.wvm_runtime_integration is False
    assert promoted_route_only.safety.kv_reuse_proven is False
    assert promoted_route_only.is_production_promotable is False


def test_model_registry_profiles_stay_lab_only_internal_recommendations() -> None:
    registry = build_initial_model_registry()
    gemma = registry.require("gemma4_e2b_q4km")
    qwen4b = registry.require("qwen35_4b")
    qwen9b = registry.require("qwen35_9b")

    assert registry.has_route_conflicts is False
    assert registry.is_production_promotion_guarded is True

    assert gemma.is_final_user_facing_recommendation is False
    assert gemma.kv_reuse_proven is False
    assert gemma.production_default is False

    assert qwen4b.is_production_promotion_guarded is True
    assert qwen9b.is_production_promotion_guarded is True


def test_structured_json_matrix_rows_stay_lab_only_and_non_runtime() -> None:
    matrix = build_structured_json_validation_matrix()

    for row in matrix.rows:
        assert row.production_default is False
        assert row.wvm_runtime_integration is False
        assert row.kv_reuse_proven is False

    assert matrix.require("gemma4_e2b_q4km").live_allowed_in_l3_7d is True
    assert matrix.require("qwen35_4b").live_allowed_in_l3_7d is False


def test_internal_recommendation_draft_stays_lab_only_and_non_runtime() -> None:
    draft = build_internal_recommendation_draft()

    assert draft.production_default is False
    assert draft.wvm_runtime_integration is False
    assert draft.kv_reuse_proven is False
    assert draft.final_user_facing_recommendation is False
    assert draft.is_safe_for_user_facing_recommendation() is False

    for recommendation in draft.models:
        assert recommendation.production_default is False
        assert recommendation.wvm_runtime_integration is False
        assert recommendation.kv_reuse_proven is False
        assert recommendation.final_user_facing_recommendation is False
        for route in recommendation.route_guidance:
            assert route.production_default is False
            assert route.wvm_runtime_integration is False
            assert route.kv_reuse_proven is False
            assert route.final_user_facing_recommendation is False


def test_internal_recommendation_draft_constructors_reject_promotion_flags() -> None:
    try:
        InternalRouteGuidance(
            model_key="bad-model",
            model_id="bad/model",
            route=RouteMode.COMPACT_MEMORY,
            status=InternalRecommendationStatus.INTERNAL_PRIMARY_CANDIDATE,
            production_default=True,
        )
    except ValueError as exc:
        assert "production_default=true" in str(exc)
    else:
        raise AssertionError("Expected internal route production guard")

    try:
        InternalModelRecommendation(
            model_key="bad-model",
            model_id="bad/model",
            status=InternalRecommendationStatus.INTERNAL_PRIMARY_CANDIDATE,
            final_user_facing_recommendation=True,
        )
    except ValueError as exc:
        assert "final_user_facing_recommendation=true" in str(exc)
    else:
        raise AssertionError("Expected internal model user-facing guard")


def test_l3_8_candidate_execution_constructor_rejects_promotion_flags() -> None:
    try:
        CandidateExecutionRecord(
            model_key="bad-model",
            model_id="bad/model",
            family="gemma4",
            size_class=build_candidate_execution_catalog().require("gemma4_e4b_q4km").size_class,
            profile_type="q4_k_m",
            no_live_feasibility_status=CandidateExecutionGateStatus.NO_LIVE_FEASIBILITY_PASSED,
            load_only_16k_32k_status=CandidateExecutionGateStatus.LOAD_ONLY_PASSED,
            tiny_live_smoke_status=CandidateExecutionGateStatus.TINY_LIVE_SMOKE_PASSED,
            structured_json_status=CandidateExecutionGateStatus.STRUCTURED_JSON_PASSED,
            route_matrix_status=(
                CandidateExecutionGateStatus.ROUTE_MATRIX_BLOCKED_UNTIL_PREREQUISITES
            ),
            production_default=True,
        )
    except ValueError as exc:
        assert "production_default=true" in str(exc)
    else:
        raise AssertionError("Expected candidate execution production guard")
