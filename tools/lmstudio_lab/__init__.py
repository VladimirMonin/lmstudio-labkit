from __future__ import annotations

from importlib import import_module

_EXPORTS_BY_MODULE: dict[str, tuple[str, ...]] = {
    "cache_plan": (
        "CACHE_PLAN_ALLOWED_MODEL_IDS",
        "CACHE_PLAN_MEASUREMENT_SOURCE",
        "CACHE_PLAN_MEASUREMENT_STATUS",
        "CACHE_PLAN_REQUIRED_BRANCHES",
        "CACHE_PLAN_REQUIRED_METRICS",
        "CACHE_PLAN_REQUIRED_VARIANTS",
        "CACHE_PLAN_RESULT_FILE_NAMES",
        "CachePlanConfig",
        "CachePlanPrivacy",
        "RootContextSummary",
        "create_cache_plan_artifacts",
        "default_cache_plan_run_id",
        "load_cache_plan_config",
        "load_raw_cache_plan_config",
        "render_cache_plan_report",
        "validate_cache_plan_payload",
    ),
    "candidate_resolution": (
        "CANDIDATE_RESOLUTION_ENDPOINT_PATH",
        "CANDIDATE_RESOLUTION_RESULT_FILE_NAMES",
        "CandidateResolutionResult",
        "CandidateResolutionTransport",
        "build_candidate_resolution_url",
        "is_local_candidate_resolution_base_url",
        "render_candidate_resolution_report",
        "resolve_candidate_models",
    ),
    "config": (
        "ExperimentConfig",
        "ModelConfig",
        "PrivacyConfig",
        "load_experiment_config",
        "load_raw_experiment_config",
        "validate_experiment_config_payload",
    ),
    "context_fit": (
        "ContextFitResult",
        "evaluate_context_fit",
    ),
    "datasets": (
        "ChunkedDatasetView",
        "DatasetChunk",
        "DatasetManifest",
        "default_datasets_root",
        "load_chunked_dataset_view",
        "load_dataset_manifest",
    ),
    "identity_probe": (
        "IDENTITY_PROBE_COMPAT_ENDPOINT_PATH",
        "IDENTITY_PROBE_NATIVE_ENDPOINT_PATH",
        "IDENTITY_PROBE_RESULT_FILE_NAMES",
        "IdentityProbeResult",
        "IdentityProbeTransport",
        "build_identity_probe_compat_url",
        "build_identity_probe_native_url",
        "is_local_identity_probe_base_url",
        "probe_lmstudio_identity",
        "render_identity_probe_report",
    ),
    "live_config": (
        "LiveLoadFieldValue",
        "LiveLoadScalar",
        "LiveModelConfig",
        "LivePrivacyConfig",
        "LiveSmokeConfig",
        "is_local_lmstudio_base_url",
        "load_live_smoke_config",
    ),
    "live_smoke": (
        "CHUNKED_WARMUP_POLICY_CHOICES",
        "EFFECTIVE_PROFILE_CHOICES",
        "LiveChunkedSmokeOutcome",
        "LiveConcurrencyDiagnosticsOutcome",
        "LivePromptMetadata",
        "LiveSmokeOutcome",
        "LiveTransport",
        "build_factual_blocks_response_format",
        "build_live_structured_messages",
        "run_live_chunked_structured_smoke",
        "run_live_concurrency_diagnostics",
        "run_live_structured_smoke",
    ),
    "load_probe": (
        "LOAD_PROBE_ENDPOINT_PATH",
        "LOAD_PROBE_RESULT_FILE_NAMES",
        "LoadProbeResult",
        "LoadProbeTransport",
        "build_load_probe_url",
        "is_local_load_probe_base_url",
        "probe_lmstudio_load",
        "render_load_probe_report",
        "validate_load_probe_model_id",
    ),
    "managed_runner": (
        "ManagedLabRunner",
        "ManagedTransport",
    ),
    "metrics": (
        "SAFE_ERROR_CATEGORIES",
        "SCHEMA_VERSION",
        "LMStudioLabMetricRecord",
        "LoadConfigSummary",
        "ResponseFormatSummary",
        "SystemMetrics",
        "TimingMetrics",
        "TokenMetrics",
        "ValidationMetrics",
        "append_jsonl_record",
    ),
    "model_acquisition": (
        "MODEL_ACQUISITION_ENDPOINT_PATH",
        "MODEL_ACQUISITION_RESULT_FILE_NAMES",
        "MODEL_ACQUISITION_STATUS_ENDPOINT_TEMPLATE",
        "ModelAcquisitionResult",
        "ModelAcquisitionTransport",
        "acquire_candidate_model",
        "build_model_acquisition_status_url",
        "build_model_acquisition_url",
        "is_local_model_acquisition_base_url",
        "render_model_acquisition_report",
    ),
    "model_lifecycle": (
        "MODEL_LIFECYCLE_LIST_ENDPOINT_PATH",
        "MODEL_LIFECYCLE_LOAD_ENDPOINT_PATH",
        "MODEL_LIFECYCLE_RESULT_FILE_NAMES",
        "MODEL_LIFECYCLE_SCENARIO_CHOICES",
        "MODEL_LIFECYCLE_UNLOAD_ENDPOINT_PATH",
        "ModelLifecycleResult",
        "ModelLifecycleTransport",
        "build_model_lifecycle_list_url",
        "build_model_lifecycle_load_url",
        "build_model_lifecycle_unload_url",
        "is_local_model_lifecycle_base_url",
        "probe_model_lifecycle",
        "render_model_lifecycle_report",
        "validate_model_lifecycle_api_token_env",
        "validate_model_lifecycle_model_id",
    ),
    "model_probe": (
        "MODEL_PROBE_ENDPOINT_PATH",
        "MODEL_PROBE_RESULT_FILE_NAMES",
        "ModelProbeResult",
        "ModelProbeTransport",
        "build_model_probe_url",
        "is_local_model_probe_base_url",
        "probe_lmstudio_models",
        "render_model_probe_report",
    ),
    "privacy": (
        "REDACTED_VALUE",
        "find_privacy_violations",
        "is_forbidden_metric_key",
        "sanitize_metric_payload",
    ),
    "report": (
        "CONCURRENCY_DIAGNOSTICS_RESULT_FILE_NAMES",
        "LIVE_CHUNKED_RESULT_FILE_NAMES",
        "LIVE_RESULT_FILE_NAMES",
        "RESULT_FILE_NAMES",
        "STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES",
        "build_structured_validation_summary_csv_row",
        "render_concurrency_diagnostics_report",
        "render_dry_run_report",
        "render_live_chunked_smoke_report",
        "render_live_smoke_report",
        "write_csv_file",
        "write_json_file",
        "write_yaml_file",
    ),
    "structured": (
        "FACTUAL_BLOCKS_SCHEMA_NAME",
        "SCHEMA_PASS_MEANING",
        "STRUCTURED_FIXTURE_MANIFEST_NAME",
        "StructuredFixtureCase",
        "StructuredFixtureManifest",
        "StructuredFixtureValidationBatch",
        "StructuredValidationResult",
        "StructuredValidationSummary",
        "default_structured_fixtures_root",
        "load_structured_fixture_manifest",
        "summarize_structured_validation_results",
        "validate_factual_blocks_response",
        "validate_structured_fixture_manifest",
    ),
    "system_metrics": (
        "SystemMetricsSampler",
        "SystemMetricsSnapshot",
        "SystemMetricsSummary",
        "collect_system_snapshot",
        "parse_nvidia_smi_csv_output",
        "summarize_system_samples",
        "write_system_telemetry_artifacts",
    ),
    "tokens": (
        "DEFAULT_CHARS_PER_TOKEN",
        "DEFAULT_TOKENIZER_SPEC",
        "TokenizerSpec",
        "calculate_estimate_error_ratio",
        "estimate_input_tokens_from_chars",
    ),
}

_MODULE_BY_EXPORT = {
    export_name: module_name
    for module_name, export_names in _EXPORTS_BY_MODULE.items()
    for export_name in export_names
}

__all__ = list(_MODULE_BY_EXPORT)


def __getattr__(name: str):
    module_name = _MODULE_BY_EXPORT.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
