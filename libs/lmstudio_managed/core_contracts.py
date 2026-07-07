"""Pure lab-only core contracts for managed LM Studio evidence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ._safe import as_bool, as_int, as_str

EXPECTED_LAB_ARTIFACT_FILENAMES = (
    "environment.json",
    "run_config.json",
    "load_response_sanitized.json",
    "requests.jsonl",
    "metrics.jsonl",
    "system_samples.jsonl",
    "system_summary.json",
    "comparison_summary.json",
    "privacy_scan.json",
    "report.md",
)
OPTIONAL_LAB_ARTIFACT_FILENAMES = ("comparison_summary.json",)
REQUIRED_LAB_ARTIFACT_FILENAMES = tuple(
    name for name in EXPECTED_LAB_ARTIFACT_FILENAMES if name not in OPTIONAL_LAB_ARTIFACT_FILENAMES
)
EXACT_PUBLIC_MARKER_FIELDS = ("model_id", "model_key")
LAB_ARTIFACT_SCHEMA = {
    "schema_family": "lmstudio_lab_artifacts",
    "contract_version": "l3.7a",
    "artifact_filenames": EXPECTED_LAB_ARTIFACT_FILENAMES,
    "required_artifacts": REQUIRED_LAB_ARTIFACT_FILENAMES,
    "optional_artifacts": OPTIONAL_LAB_ARTIFACT_FILENAMES,
    "privacy_policy": {
        "store_raw_prompt_response": False,
        "store_state_ids_raw": False,
        "store_local_urls": False,
        "exact_public_marker_fields": EXACT_PUBLIC_MARKER_FIELDS,
    },
}


class ExperimentStatus(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
    BLOCKED_INTERNAL_ERROR = "blocked_internal_error"


class ResultClassification(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
    BLOCKED_INTERNAL_ERROR = "blocked_internal_error"
    PRIMARY_CANDIDATE = "primary_candidate"
    RESEARCH_LATENCY_CANDIDATE = "research_latency_candidate"
    BASELINE = "baseline"
    CACHE_ACCOUNTING_CANDIDATE = "cache_accounting_candidate"
    PRODUCTION_BLOCKED = "production_blocked"


class RouteMode(StrEnum):
    COMPACT_MEMORY = "compact_memory"
    NATIVE_CHAT_STATEFUL = "native_chat_stateful"
    STATELESS_FULL_PREFIX = "stateless_full_prefix"
    OPENAI_RESPONSES = "openai_responses"
    STRICT_JSON_CHAT_COMPLETIONS = "strict_json_chat_completions"


class StructuredOutputStatus(StrEnum):
    UNKNOWN = "unknown"
    SUPPORTED = "supported"
    STRICT_JSON_ONLY = "strict_json_only"
    BLOCKED = "blocked"


class LoadOwnership(StrEnum):
    EXTERNAL_OR_UNKNOWN = "external_or_unknown"
    LAB_OWNED_EPHEMERAL = "lab_owned_ephemeral"


class CleanupPolicy(StrEnum):
    RETURN_TO_ZERO_INSTANCES = "return_to_zero_instances"
    DO_NOT_TOUCH_EXTERNAL = "do_not_touch_external"


class PrivacyScanStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class EvidenceKind(StrEnum):
    ARTIFACT_BUNDLE = "artifact_bundle"
    MARKDOWN_SUMMARY = "markdown_summary"


@dataclass(frozen=True, slots=True)
class ExperimentIdentity:
    experiment_id: str
    run_id: str
    schema_version: str = "1.0"
    lab_only: bool = True
    production_default: bool = False
    wvm_runtime_integration: bool = False

    @property
    def is_lab_only(self) -> bool:
        return self.lab_only


@dataclass(frozen=True, slots=True)
class SafetyFlags:
    generation_allowed: bool = False
    live_25k_authorized: bool = False
    kv_reuse_proven: bool = False
    store_raw_prompt_response: bool = False
    store_state_ids_raw: bool = False
    store_local_urls: bool = False

    @property
    def is_privacy_safe(self) -> bool:
        return not any(
            (
                self.store_raw_prompt_response,
                self.store_state_ids_raw,
                self.store_local_urls,
            )
        )


@dataclass(frozen=True, slots=True)
class ModelProfile:
    model_key: str | None = None
    model_id: str | None = None
    family: str | None = None
    quantization: str | None = None
    backend: str | None = None
    structured_output_status: StructuredOutputStatus = StructuredOutputStatus.UNKNOWN
    recommended_context_lengths: tuple[int, ...] = ()
    blocked_modes: tuple[RouteMode, ...] = (RouteMode.OPENAI_RESPONSES,)
    allowed_modes: tuple[RouteMode, ...] = ()


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    os: str | None = None
    cpu: str | None = None
    ram: str | None = None
    gpu: str | None = None
    vram: str | None = None
    backend_capabilities: tuple[str, ...] = ()
    mlx_notes: str | None = None
    cuda_notes: str | None = None
    llama_cpp_notes: str | None = None


@dataclass(frozen=True, slots=True)
class LoadProfile:
    context_length: int | None = None
    parallel: int | None = None
    flash_attention: bool | None = None
    offload_kv_cache_to_gpu: bool | None = None
    applied_load_config: tuple[tuple[str, object], ...] = ()
    ownership: LoadOwnership = LoadOwnership.EXTERNAL_OR_UNKNOWN
    cleanup_policy: CleanupPolicy = CleanupPolicy.DO_NOT_TOUCH_EXTERNAL


@dataclass(frozen=True, slots=True)
class RouteObservation:
    route: RouteMode
    status: ExperimentStatus = ExperimentStatus.PASSED
    classification: ResultClassification | None = None
    request_id: str | None = None
    request_succeeded: bool = True
    previous_response_id_used: bool = False
    kv_reuse_proven: bool = False


@dataclass(frozen=True, slots=True)
class ArtifactSetValidation:
    expected_artifacts: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    optional_artifacts: tuple[str, ...]
    provided_artifacts: tuple[str, ...]
    missing_required_artifacts: tuple[str, ...] = ()
    missing_optional_artifacts: tuple[str, ...] = ()
    unexpected_artifacts: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.missing_required_artifacts


@dataclass(frozen=True, slots=True)
class PrivacyValidationPolicy:
    store_raw_prompt_response: bool = False
    store_state_ids_raw: bool = False
    store_local_urls: bool = False
    exact_public_marker_fields: tuple[str, ...] = EXACT_PUBLIC_MARKER_FIELDS
    public_model_id: str | None = None
    public_model_key: str | None = None

    def is_exact_public_marker_exempt(self, field_name: str, value: object) -> bool:
        normalized_name = (field_name or "").strip()
        if normalized_name not in self.exact_public_marker_fields:
            return False
        normalized_value = as_str(value)
        if normalized_value is None:
            return False
        if normalized_name == "model_id":
            return self.public_model_id is not None and normalized_value == self.public_model_id
        if normalized_name == "model_key":
            return self.public_model_key is not None and normalized_value == self.public_model_key
        return False


@dataclass(frozen=True, slots=True)
class ArtifactBundleSummary:
    identity: ExperimentIdentity
    safety: SafetyFlags
    model: ModelProfile
    load: LoadProfile
    privacy_policy: PrivacyValidationPolicy = PrivacyValidationPolicy()
    artifact_validation: ArtifactSetValidation | None = None
    route_results: tuple[RouteObservation, ...] = ()
    privacy_scan_status: PrivacyScanStatus = PrivacyScanStatus.UNKNOWN
    evidence_kind: EvidenceKind = EvidenceKind.ARTIFACT_BUNDLE

    @property
    def comparison_available(self) -> bool:
        return any(result.classification is not None for result in self.route_results)

    def classification_for(self, route: RouteMode) -> ResultClassification | None:
        for result in self.route_results:
            if result.route == route:
                return result.classification
        return None


@dataclass(frozen=True, slots=True)
class LabEvidenceRef:
    experiment_id: str
    summary_ref: str
    status: ExperimentStatus = ExperimentStatus.PASSED
    kind: EvidenceKind = EvidenceKind.MARKDOWN_SUMMARY
    artifact_bundle_available: bool = False
    notes: str | None = None

    @property
    def has_artifact_bundle(self) -> bool:
        return self.artifact_bundle_available


@dataclass(frozen=True, slots=True)
class RouteRecommendation:
    route: RouteMode
    status: ExperimentStatus = ExperimentStatus.PASSED
    classification: ResultClassification | None = None
    user_facing_recommendation: bool = False
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class RecommendationDraft:
    routes: tuple[RouteRecommendation, ...]
    final_user_facing: bool = False

    def classification_for(self, route: RouteMode) -> ResultClassification | None:
        for route_policy in self.routes:
            if route_policy.route == route:
                return route_policy.classification
        return None


@dataclass(frozen=True, slots=True)
class ManagedCoreContract:
    identity: ExperimentIdentity
    safety: SafetyFlags = SafetyFlags()
    model: ModelProfile = ModelProfile()
    hardware: HardwareProfile = HardwareProfile()
    load: LoadProfile = LoadProfile()
    privacy_policy: PrivacyValidationPolicy = PrivacyValidationPolicy()
    route_results: tuple[RouteObservation, ...] = ()
    evidence_refs: tuple[LabEvidenceRef, ...] = ()
    artifact_summary: ArtifactBundleSummary | None = None
    recommendation_draft: RecommendationDraft | None = None
    status: ExperimentStatus = ExperimentStatus.BLOCKED
    classification: ResultClassification = ResultClassification.PRODUCTION_BLOCKED

    @property
    def is_production_promotable(self) -> bool:
        if self.identity.is_lab_only:
            return False
        if not self.identity.production_default:
            return False
        if not self.identity.wvm_runtime_integration:
            return False
        if not self.safety.kv_reuse_proven:
            return False
        if self.status != ExperimentStatus.PASSED:
            return False
        return self.classification != ResultClassification.PRODUCTION_BLOCKED


def _mapping_or_none(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _freeze_jsonish(value: object) -> object:
    mapping = _mapping_or_none(value)
    if mapping is not None:
        return tuple(
            (str(key), _freeze_jsonish(nested_value))
            for key, nested_value in sorted(mapping.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_jsonish(item) for item in value)
    return value


def _sorted_strings(values: Iterable[object]) -> tuple[str, ...]:
    normalized = {text for value in values if (text := as_str(value)) is not None}
    return tuple(sorted(normalized))


def _route_mode_or_none(value: object) -> RouteMode | None:
    text = as_str(value)
    if text is None:
        return None
    try:
        return RouteMode(text)
    except ValueError:
        return None


def _classification_or_none(value: object) -> ResultClassification | None:
    text = as_str(value)
    if text is None:
        return None
    try:
        return ResultClassification(text)
    except ValueError:
        return None


def _privacy_scan_status_or_unknown(value: object) -> PrivacyScanStatus:
    text = as_str(value)
    if text is None:
        return PrivacyScanStatus.UNKNOWN
    try:
        return PrivacyScanStatus(text)
    except ValueError:
        return PrivacyScanStatus.UNKNOWN


def validate_required_artifact_set(
    artifact_names: Iterable[object],
) -> ArtifactSetValidation:
    provided_artifacts = _sorted_strings(artifact_names)
    expected = EXPECTED_LAB_ARTIFACT_FILENAMES
    required = REQUIRED_LAB_ARTIFACT_FILENAMES
    optional = OPTIONAL_LAB_ARTIFACT_FILENAMES
    provided_set = set(provided_artifacts)
    expected_set = set(expected)
    missing_required = tuple(name for name in required if name not in provided_set)
    missing_optional = tuple(name for name in optional if name not in provided_set)
    unexpected = tuple(sorted(provided_set - expected_set))
    return ArtifactSetValidation(
        expected_artifacts=expected,
        required_artifacts=required,
        optional_artifacts=optional,
        provided_artifacts=provided_artifacts,
        missing_required_artifacts=missing_required,
        missing_optional_artifacts=missing_optional,
        unexpected_artifacts=unexpected,
    )


def _build_identity(
    environment_payload: Mapping[str, Any],
    run_config_payload: Mapping[str, Any],
) -> ExperimentIdentity:
    safety_payload = _mapping_or_none(run_config_payload.get("safety")) or {}
    return ExperimentIdentity(
        experiment_id=as_str(environment_payload.get("experiment_id"))
        or as_str(run_config_payload.get("experiment_id"))
        or "unknown_experiment",
        run_id=as_str(environment_payload.get("run_id"))
        or as_str(run_config_payload.get("run_id"))
        or "unknown_run",
        schema_version=as_str(environment_payload.get("schema_version"))
        or as_str(run_config_payload.get("schema_version"))
        or "1.0",
        lab_only=as_bool(environment_payload.get("lab_only"))
        if as_bool(environment_payload.get("lab_only")) is not None
        else True,
        production_default=as_bool(environment_payload.get("production_default"))
        if as_bool(environment_payload.get("production_default")) is not None
        else bool(as_bool(safety_payload.get("production_default"))),
        wvm_runtime_integration=as_bool(environment_payload.get("wvm_runtime_integration"))
        if as_bool(environment_payload.get("wvm_runtime_integration")) is not None
        else bool(as_bool(safety_payload.get("wvm_runtime_integration"))),
    )


def _build_safety_flags(
    environment_payload: Mapping[str, Any],
    run_config_payload: Mapping[str, Any],
    privacy_scan_payload: Mapping[str, Any],
) -> SafetyFlags:
    safety_payload = _mapping_or_none(run_config_payload.get("safety")) or {}
    privacy_payload = _mapping_or_none(run_config_payload.get("privacy")) or {}
    raw_prompt_response_stored = as_bool(privacy_scan_payload.get("raw_prompt_response_stored"))
    return SafetyFlags(
        generation_allowed=bool(
            as_bool(environment_payload.get("generation_allowed"))
            if as_bool(environment_payload.get("generation_allowed")) is not None
            else as_bool(safety_payload.get("generation_allowed"))
        ),
        live_25k_authorized=bool(
            as_bool(environment_payload.get("live_25k_authorized"))
            if as_bool(environment_payload.get("live_25k_authorized")) is not None
            else as_bool(safety_payload.get("live_25k_authorized"))
        ),
        kv_reuse_proven=bool(
            as_bool(environment_payload.get("kv_reuse_proven"))
            if as_bool(environment_payload.get("kv_reuse_proven")) is not None
            else as_bool(safety_payload.get("kv_reuse_proven"))
        ),
        store_raw_prompt_response=bool(
            raw_prompt_response_stored
            if raw_prompt_response_stored is not None
            else as_bool(privacy_payload.get("store_raw_prompt_response"))
        ),
        store_state_ids_raw=bool(as_bool(privacy_payload.get("store_state_ids_raw"))),
        store_local_urls=bool(as_bool(privacy_payload.get("store_local_urls"))),
    )


def _build_model_profile(
    run_config_payload: Mapping[str, Any],
    route_results: tuple[RouteObservation, ...],
) -> ModelProfile:
    load_payload = _mapping_or_none(run_config_payload.get("load")) or {}
    allowed_modes = tuple(dict.fromkeys(result.route for result in route_results))
    recommended_context_length = as_int(load_payload.get("context_length")) or as_int(
        run_config_payload.get("requested_context_length")
    )
    return ModelProfile(
        model_key=as_str(run_config_payload.get("model_key")),
        model_id=as_str(run_config_payload.get("model_id")),
        backend=as_str(run_config_payload.get("mode")),
        recommended_context_lengths=(recommended_context_length,)
        if recommended_context_length is not None
        else (),
        allowed_modes=allowed_modes,
    )


def _build_load_profile(
    environment_payload: Mapping[str, Any],
    run_config_payload: Mapping[str, Any],
    comparison_summary_payload: Mapping[str, Any] | None,
) -> LoadProfile:
    load_payload = _mapping_or_none(run_config_payload.get("load")) or {}
    safety_payload = _mapping_or_none(run_config_payload.get("safety")) or {}
    managed_live = bool(as_bool(environment_payload.get("managed_live")))
    final_loaded_instances_required = as_int(safety_payload.get("final_loaded_instances_required"))
    cleanup_to_zero = final_loaded_instances_required == 0 or bool(
        as_bool(safety_payload.get("unload_required"))
    )
    if (
        comparison_summary_payload is not None
        and as_int(comparison_summary_payload.get("final_loaded_instances")) == 0
    ):
        cleanup_to_zero = True
    return LoadProfile(
        context_length=as_int(load_payload.get("context_length"))
        or as_int(run_config_payload.get("requested_context_length")),
        parallel=as_int(load_payload.get("parallel"))
        or as_int(run_config_payload.get("requested_parallel")),
        flash_attention=as_bool(load_payload.get("flash_attention")),
        offload_kv_cache_to_gpu=as_bool(load_payload.get("offload_kv_cache_to_gpu")),
        applied_load_config=tuple(
            (str(key), _freeze_jsonish(value))
            for key, value in sorted(load_payload.items(), key=lambda item: str(item[0]))
        ),
        ownership=(
            LoadOwnership.LAB_OWNED_EPHEMERAL if managed_live else LoadOwnership.EXTERNAL_OR_UNKNOWN
        ),
        cleanup_policy=(
            CleanupPolicy.RETURN_TO_ZERO_INSTANCES
            if cleanup_to_zero
            else CleanupPolicy.DO_NOT_TOUCH_EXTERNAL
        ),
    )


def _build_route_results(
    run_config_payload: Mapping[str, Any],
    comparison_summary_payload: Mapping[str, Any] | None,
) -> tuple[RouteObservation, ...]:
    if comparison_summary_payload is not None:
        mode_results = comparison_summary_payload.get("mode_results")
        if isinstance(mode_results, list):
            observations: list[RouteObservation] = []
            for item in mode_results:
                item_payload = _mapping_or_none(item)
                if item_payload is None:
                    continue
                route = _route_mode_or_none(item_payload.get("route") or item_payload.get("mode"))
                if route is None:
                    continue
                request_succeeded = bool(as_bool(item_payload.get("request_succeeded")))
                observations.append(
                    RouteObservation(
                        route=route,
                        status=(
                            ExperimentStatus.PASSED
                            if request_succeeded
                            else ExperimentStatus.BLOCKED_INTERNAL_ERROR
                        ),
                        classification=_classification_or_none(item_payload.get("classification")),
                        request_id=as_str(item_payload.get("request_id")),
                        request_succeeded=request_succeeded,
                        previous_response_id_used=bool(
                            as_bool(item_payload.get("previous_response_id_used"))
                        ),
                        kv_reuse_proven=bool(as_bool(item_payload.get("kv_reuse_proven"))),
                    )
                )
            return tuple(observations)

    generation_payload = _mapping_or_none(run_config_payload.get("generation")) or {}
    route = _route_mode_or_none(generation_payload.get("route"))
    if route is None:
        return ()
    return (
        RouteObservation(
            route=route,
            status=ExperimentStatus.PASSED,
            request_succeeded=True,
            previous_response_id_used=bool(as_bool(generation_payload.get("store"))),
        ),
    )


def build_artifact_bundle_summary(
    environment_payload: Mapping[str, Any] | None,
    run_config_payload: Mapping[str, Any] | None,
    privacy_scan_payload: Mapping[str, Any] | None,
    comparison_summary_payload: Mapping[str, Any] | None = None,
) -> ArtifactBundleSummary:
    environment_data = _mapping_or_none(environment_payload) or {}
    run_config_data = _mapping_or_none(run_config_payload) or {}
    privacy_scan_data = _mapping_or_none(privacy_scan_payload) or {}
    comparison_data = _mapping_or_none(comparison_summary_payload)
    route_results = _build_route_results(run_config_data, comparison_data)
    artifact_validation = validate_required_artifact_set(run_config_data.get("artifacts", ()))
    return ArtifactBundleSummary(
        identity=_build_identity(environment_data, run_config_data),
        safety=_build_safety_flags(environment_data, run_config_data, privacy_scan_data),
        model=_build_model_profile(run_config_data, route_results),
        load=_build_load_profile(environment_data, run_config_data, comparison_data),
        privacy_policy=PrivacyValidationPolicy(
            public_model_id=as_str(run_config_data.get("model_id")),
            public_model_key=as_str(run_config_data.get("model_key")),
        ),
        artifact_validation=artifact_validation,
        route_results=route_results,
        privacy_scan_status=_privacy_scan_status_or_unknown(privacy_scan_data.get("status")),
    )


def build_l3_7a_recommendation_draft() -> RecommendationDraft:
    return RecommendationDraft(
        routes=(
            RouteRecommendation(
                route=RouteMode.COMPACT_MEMORY,
                classification=ResultClassification.PRIMARY_CANDIDATE,
                notes="Primary internal default for future lab drafts.",
            ),
            RouteRecommendation(
                route=RouteMode.NATIVE_CHAT_STATEFUL,
                classification=ResultClassification.RESEARCH_LATENCY_CANDIDATE,
                notes="Research accelerator only; not a production promotion signal.",
            ),
            RouteRecommendation(
                route=RouteMode.STATELESS_FULL_PREFIX,
                classification=ResultClassification.BASELINE,
                notes="Baseline and fallback route.",
            ),
            RouteRecommendation(
                route=RouteMode.STRICT_JSON_CHAT_COMPLETIONS,
                notes="Internal strict JSON lane preserved without final user-facing recommendation.",
            ),
            RouteRecommendation(
                route=RouteMode.OPENAI_RESPONSES,
                status=ExperimentStatus.BLOCKED,
                classification=ResultClassification.PRODUCTION_BLOCKED,
                notes="Blocked for long-context use.",
            ),
        ),
        final_user_facing=False,
    )


__all__ = [
    "ArtifactBundleSummary",
    "ArtifactSetValidation",
    "CleanupPolicy",
    "EvidenceKind",
    "EXACT_PUBLIC_MARKER_FIELDS",
    "EXPECTED_LAB_ARTIFACT_FILENAMES",
    "ExperimentIdentity",
    "ExperimentStatus",
    "HardwareProfile",
    "LAB_ARTIFACT_SCHEMA",
    "LabEvidenceRef",
    "LoadOwnership",
    "LoadProfile",
    "ManagedCoreContract",
    "ModelProfile",
    "OPTIONAL_LAB_ARTIFACT_FILENAMES",
    "PrivacyScanStatus",
    "PrivacyValidationPolicy",
    "REQUIRED_LAB_ARTIFACT_FILENAMES",
    "RecommendationDraft",
    "ResultClassification",
    "RouteMode",
    "RouteObservation",
    "RouteRecommendation",
    "SafetyFlags",
    "StructuredOutputStatus",
    "build_artifact_bundle_summary",
    "build_l3_7a_recommendation_draft",
    "validate_required_artifact_set",
]
