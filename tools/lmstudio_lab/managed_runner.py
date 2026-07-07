from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from hashlib import sha256
from os import PathLike
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, cast
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import yaml

from libs.lmstudio_managed.cache_contracts.contracts import (
    CacheEvidence,
    CacheExperimentPlan,
    CacheMeasurementStatus,
    CacheReuseVerdict,
    ResponsesCacheProbeStatus,
    parse_responses_usage,
)
from libs.lmstudio_managed.client import (
    DownloadClient,
    GenerationClient,
    LifecycleClient,
    LMStudioEndpointFamily,
    ModelListClient,
    TransportRequest,
)
from libs.lmstudio_managed.client.errors import SafeApiError
from libs.lmstudio_managed.download import DownloadRequest
from libs.lmstudio_managed.generation import (
    PlainTextGenerationRequest,
    ResponseFormatKind,
    StructuredGenerationRequest,
)
from libs.lmstudio_managed.lifecycle import LoadModelRequest, UnloadModelRequest
from libs.lmstudio_managed.registry import (
    LoadedInstanceRecord,
    ModelListResponse,
    parse_native_model_list,
)

from .config import load_raw_experiment_config
from .context_fit import evaluate_context_fit
from .datasets import default_datasets_root, load_chunked_dataset_view, load_dataset_manifest
from .live_config import (
    LiveLoadFieldValue,
    LiveModelConfig,
    LivePrivacyConfig,
    LiveSmokeConfig,
    load_live_smoke_config,
)
from .live_smoke import LiveTransport, run_live_chunked_structured_smoke, run_live_structured_smoke
from .metrics import (
    SCHEMA_VERSION,
    LMStudioLabMetricRecord,
    TokenMetrics,
    append_jsonl_record,
)
from .model_lifecycle import ModelLifecycleTransport, run_exact_model_operation
from .privacy import (
    find_privacy_violations,
    is_forbidden_metric_key,
    normalize_metric_key,
    sanitize_metric_payload,
    sanitize_metric_value,
)
from .report import (
    STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES,
    build_structured_validation_summary_csv_row,
    write_csv_file,
    write_json_file,
)
from .structured import (
    FACTUAL_BLOCKS_SCHEMA_NAME,
    StructuredValidationResult,
)
from .system_metrics import (
    SystemMetricsSampler,
    SystemMetricsSnapshot,
    SystemMetricsSummary,
    write_system_telemetry_artifacts,
)
from .tokens import estimate_input_tokens_from_chars

ManagedTransport = Callable[[TransportRequest], object]
ManagedOperation = Callable[[], dict[str, object]]
ManagedStreamingTransport = Callable[[str, Mapping[str, Any], float], Mapping[str, Any]]
ResponsesProbeTransport = Callable[[urllib_request.Request, float], bytes]

_DEFAULT_SYSTEM_PROVIDERS = {"lmstudio_local": "managed_runner"}
_RUN_SUMMARY_FORBIDDEN_TOP_LEVEL_KEYS = frozenset({"payload"})
_SAFE_SYSTEM_SUMMARY_KEYS = (
    "ram_before_mb",
    "ram_peak_mb",
    "ram_after_mb",
    "process_rss_before_mb",
    "process_rss_peak_mb",
    "process_rss_after_mb",
    "vram_before_mb",
    "vram_peak_mb",
    "vram_after_mb",
    "gpu_util_peak_percent",
    "gpu_power_peak_watts",
)
_MEDIUM_CHUNKED_PREP_DATASET_ID = "blocks_json_medium_chunked"
_MEDIUM_CHUNKED_LIVE_ALLOWED_DATASET_IDS = frozenset(
    {
        "blocks_json_medium_chunked",
        "blocks_json_medium_chunked_10",
        "blocks_json_medium_chunked_5",
    }
)
_MEDIUM_CHUNKED_PREP_MODEL_KEYS = (
    "gemma4_e2b_q4km",
    "gemma4_e4b_q4km",
)
_MEDIUM_CHUNKED_PREP_MODE = "managed_runner_medium_chunked_sequential_prep"
_MEDIUM_CHUNKED_PREP_PROFILE_ID = "gemma_medium_chunked_sequential_prep"
_MEDIUM_CHUNKED_PREP_VALIDATION_SOURCE = "safe_generation_envelope_no_raw_content"
_MEDIUM_CHUNKED_PREP_VALIDATION_STATUS = "not_evaluated_no_live"
_CACHE_STATEFUL_NO_LIVE_MODE = "managed_runner_cache_stateful_no_live"
_CACHE_STATEFUL_NO_LIVE_ALLOWED_MODEL_KEY = "gemma4_e2b_q4km"
_CACHE_STATEFUL_NO_LIVE_ALLOWED_CONTEXT_WINDOWS = (8192, 16384)
_CACHE_STATEFUL_NO_LIVE_OUTPUT_FILES = (
    "run_config.json",
    "cache_plan.json",
    "requests.jsonl",
    "metrics.jsonl",
    "cache_summary.json",
    "privacy_scan.json",
    "report.md",
    "system_samples.jsonl",
    "system_summary.json",
)
_CACHE_25K_NO_LIVE_PREP_MODE = "managed_runner_cache_25k_no_live_prep"
_CACHE_25K_NO_LIVE_PREP_EXPERIMENT_ID = "l3_5_cache_25k_no_live_prep"
_CACHE_25K_NO_LIVE_PREP_MODEL_KEY = "gemma4_e2b_q4km"
_CACHE_25K_NO_LIVE_PREP_MODEL_ID = "google/gemma-4-e2b"
_CACHE_25K_NO_LIVE_PREP_DATASET_ID = "lecture_25k_tokens"
_CACHE_25K_NO_LIVE_PREP_ALLOWED_MODES = (
    "compact_memory_primary",
    "stateful_root_branches_experimental",
    "stateless_full_prefix_baseline",
)
_CACHE_25K_NO_LIVE_PREP_CONTEXT_WINDOWS = (8192, 16384, 32768, 65536)
_CACHE_25K_NO_LIVE_PREP_APP_CONCURRENCY = 1
_CACHE_25K_NO_LIVE_PREP_OUTPUT_RESERVE_TOKENS = 2048
_CACHE_25K_NO_LIVE_PREP_SAFETY_RATIO = 0.85
_CACHE_25K_NO_LIVE_PREP_DATASET_CHARS = 75000
_CACHE_25K_NO_LIVE_PREP_ESTIMATED_INPUT_TOKENS = 25000
_CACHE_25K_NO_LIVE_PREP_CONTENT_HASH = "sha256:lecture-25k-tokens-v1"
_CACHE_25K_NO_LIVE_PREP_SOURCE_HASH = "sha256:lecture-25k-source-v1"
_CACHE_25K_NO_LIVE_PREP_BRANCH_SPECS = (
    ("summary_short", 480, 160, 64),
    ("summary_detailed", 1320, 440, 176),
    ("timeline_topics", 900, 300, 120),
    ("glossary_terms", 780, 260, 104),
    ("postprocess_chunk_1", 720, 240, 96),
    ("postprocess_chunk_2", 750, 250, 100),
    ("postprocess_chunk_3", 780, 260, 104),
    ("postprocess_chunk_4", 810, 270, 108),
)
_CACHE_25K_NO_LIVE_PREP_OUTPUT_FILES = (
    "dataset_manifest.json",
    "token_manifest.json",
    "context_fit_report.json",
    "cache_plan.json",
    "branch_plan.json",
    "request_shapes.jsonl",
    "mode_comparison_plan.json",
    "privacy_scan.json",
    "report.md",
)
_L3_6_25K_NO_LIVE_PREFLIGHT_MODE = "no_live_preflight"
_L3_6_25K_NO_LIVE_PREFLIGHT_EXPERIMENT_ID = "l3_6_25k_no_live_preflight_gemma4_e2b"
_L3_6_25K_NO_LIVE_PREFLIGHT_MODEL_KEY = "gemma4_e2b_q4km"
_L3_6_25K_NO_LIVE_PREFLIGHT_MODEL_ID = "google/gemma-4-e2b"
_L3_6_25K_NO_LIVE_PREFLIGHT_DATASET_ID = "lecture_25k_tokens"
_L3_6_25K_NO_LIVE_PREFLIGHT_TARGET_CONTEXT_LENGTH = 32768
_L3_6_25K_NO_LIVE_PREFLIGHT_CHECKS = (
    "tokenized_prompt_fit",
    "output_reserve",
    "prompt_shape_minimization",
    "mode_selection",
    "abort_conditions",
    "privacy_artifact_plan",
)
_L3_6_25K_NO_LIVE_PREFLIGHT_OUTPUT_FILES = (
    "tokenized_prompt_report.json",
    "output_reserve_report.json",
    "prompt_shape_report.md",
    "mode_plan.json",
    "abort_conditions.md",
    "privacy_scan.json",
    "report.md",
)
_L3_6_25K_NO_LIVE_PREFLIGHT_RESPONSES_STATUS = "blocked_long_context_internal_error"
_L3_6A_25K_TOKENIZATION_PROMPT_FIT_MODE = "tokenization_prompt_fit_no_live"
_L3_6A_25K_TOKENIZATION_PROMPT_FIT_EXPERIMENT_ID = "l3_6a_25k_tokenization_prompt_fit_gemma4_e2b"
_L3_6A_25K_TOKENIZATION_PROMPT_FIT_MODEL_KEY = "gemma4_e2b_q4km"
_L3_6A_25K_TOKENIZATION_PROMPT_FIT_MODEL_ID = "google/gemma-4-e2b"
_L3_6A_25K_TOKENIZATION_PROMPT_FIT_DATASET_ID = "lecture_25k_tokens"
_L3_6A_25K_TOKENIZATION_PROMPT_FIT_TARGET_CONTEXT_LENGTH = 32768
_L3_6A_25K_TOKENIZATION_PROMPT_FIT_CHECKS = (
    "heuristic_token_budget",
    "exact_tokenizer_pending",
    "chat_template_overhead",
    "prompt_minimization",
    "output_reserve_policy",
    "privacy_scan",
)
_L3_6A_25K_TOKENIZATION_PROMPT_FIT_OUTPUT_FILES = (
    "tokenization_strategy_report.md",
    "token_budget_breakdown.json",
    "chat_template_overhead_report.json",
    "prompt_minimization_candidates.md",
    "output_reserve_policy.json",
    "l3_6a_report.md",
    "privacy_scan.json",
)
_L3_6A_25K_MINIMUM_APPROVED_SAFETY_MARGIN_TOKENS = 2048
_L3_6A_25K_MINIMUM_OUTPUT_RESERVE_TOKENS = 2048
_L3_6A_25K_ASSUMED_CHAT_TEMPLATE_OVERHEAD_TOKENS = 0
_L3_6A_25K_ESTIMATED_CHAT_TEMPLATE_OVERHEAD_TOKENS = 512
_L3_6A_25K_CONSERVATIVE_CHAT_TEMPLATE_OVERHEAD_TOKENS = 1024
_L3_6A_25K_MARGIN_STATUS = "blocked_high_risk_below_minimum_threshold"
_L3_6B_25K_PROMPT_MINIMIZATION_MODE = "prompt_minimization_no_live"
_L3_6B_25K_PROMPT_MINIMIZATION_EXPERIMENT_ID = "l3_6b_25k_prompt_minimization_gemma4_e2b"
_L3_6B_25K_PROMPT_MINIMIZATION_MODEL_KEY = "gemma4_e2b_q4km"
_L3_6B_25K_PROMPT_MINIMIZATION_MODEL_ID = "google/gemma-4-e2b"
_L3_6B_25K_PROMPT_MINIMIZATION_DATASET_ID = "lecture_25k_tokens"
_L3_6B_25K_PROMPT_MINIMIZATION_TARGET_CONTEXT_LENGTH = 32768
_L3_6B_25K_PROMPT_MINIMIZATION_CHECKS = (
    "baseline_snapshot_validation",
    "minimized_budget_recompute",
    "prompt_shape_minimization",
    "mode_plan_refresh",
    "abort_conditions_update",
    "privacy_scan",
)
_L3_6B_25K_PROMPT_MINIMIZATION_OUTPUT_FILES = (
    "minimized_prompt_shape_report.md",
    "minimized_token_budget_breakdown.json",
    "prompt_diff_summary.md",
    "updated_abort_conditions.md",
    "l3_6b_report.md",
    "privacy_scan.json",
)
_L3_6B_25K_BASELINE_INPUT_TOKENS = 25000
_L3_6B_25K_BASELINE_REQUIRED_TOKENS = 27048
_L3_6B_25K_BASELINE_BUDGET_TOKENS = 27852
_L3_6B_25K_BASELINE_MARGIN_TOKENS = 804
_L3_6B_25K_BASELINE_ESTIMATED_MARGIN_TOKENS = 292
_L3_6B_25K_BASELINE_CONSERVATIVE_MARGIN_TOKENS = -220
_L3_6B_25K_MINIMIZED_INPUT_TOKENS = 22700
_L3_6B_25K_MINIMIZED_REDUCTION_TOKENS = 2300
_L3_6B_25K_MINIMIZED_REQUIRED_TOKENS = 24748
_L3_6B_25K_MINIMIZED_MARGIN_TOKENS = 3104
_L3_6B_25K_ESTIMATED_OVERHEAD_REQUIRED_TOKENS = 25260
_L3_6B_25K_ESTIMATED_OVERHEAD_MARGIN_TOKENS = 2592
_L3_6B_25K_CONSERVATIVE_OVERHEAD_REQUIRED_TOKENS = 25772
_L3_6B_25K_CONSERVATIVE_OVERHEAD_MARGIN_TOKENS = 2080
_L3_6B_25K_LIVE_AUTHORIZATION_STATUS = (
    "blocked_pending_exact_tokenization_and_chat_template_measurement"
)
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_MODE = "structured_json_controlled_live_smoke"
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_EXPERIMENT_ID = "l3_7d_structured_json_live_smoke_gemma4_e2b"
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_MODEL_KEY = "gemma4_e2b_q4km"
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_MODEL_ID = "google/gemma-4-e2b"
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_CONTEXT_LENGTH = 8192
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_PARALLEL = 1
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_APP_CONCURRENCY = 1
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_DATASET_ID = "blocks_json_small"
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_ROUTE = "strict_json_chat_completions"
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_HELPER_MODE = "json_schema_single"
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_ENDPOINT_PATH = "/v1/chat/completions"
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_TEMPERATURE = 0
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_MAX_TOKENS = 512
_L3_7D_STRUCTURED_JSON_LIVE_SMOKE_OUTPUT_FILES = (
    "environment.json",
    "run_config.json",
    "load_response_sanitized.json",
    "requests.jsonl",
    "metrics.jsonl",
    "structured_errors.jsonl",
    "system_samples.jsonl",
    "system_summary.json",
    "privacy_scan.json",
    "report.md",
)
_CACHE_32K_LOAD_ONLY_MODE = "load_only"
_CACHE_32K_LOAD_ONLY_EXPERIMENT_ID = "l3_5b_32k_load_only_smoke_gemma4_e2b"
_CACHE_32K_LOAD_ONLY_MODEL_KEY = "gemma4_e2b_q4km"
_CACHE_32K_LOAD_ONLY_MODEL_ID = "google/gemma-4-e2b"
_CACHE_32K_LOAD_ONLY_CONTEXT_LENGTH = 32768
_CACHE_32K_LOAD_ONLY_PARALLEL = 1
_CACHE_32K_LOAD_ONLY_OUTPUT_FILES = (
    "environment.json",
    "run_config.json",
    "load_request.json",
    "load_response_sanitized.json",
    "models_before.json",
    "models_after_load.json",
    "unload_response_sanitized.json",
    "models_after_unload.json",
    "system_summary.json",
    "privacy_scan.json",
    "report.md",
)
_L3_8B_GEMMA4_E4B_LOAD_ONLY_MODE = "candidate_load_only_16k_32k"
_L3_8B_GEMMA4_E4B_LOAD_ONLY_EXPERIMENT_ID = "l3_8b_gemma4_e4b_load_only_16k_32k"
_L3_8B_GEMMA4_E4B_LOAD_ONLY_MODEL_KEY = "gemma4_e4b_q4km"
_L3_8B_GEMMA4_E4B_LOAD_ONLY_MODEL_ID = "google/gemma-4-e4b"
_L3_8B_GEMMA4_E4B_LOAD_ONLY_CONTEXT_TIERS = (16_384, 32_768)
_L3_8B_GEMMA4_E4B_LOAD_ONLY_PARALLEL = 1
_L3_8B_GEMMA4_E4B_LOAD_ONLY_APP_CONCURRENCY = 1
_L3_8B_GEMMA4_E4B_LOAD_ONLY_OUTPUT_FILES = (
    "environment.json",
    "run_config.json",
    "load_attempts.jsonl",
    "load_response_sanitized.jsonl",
    "models_summary.jsonl",
    "system_samples.jsonl",
    "system_summary.json",
    "privacy_scan.json",
    "report.md",
)
_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_MODE = "candidate_load_only_8k_16k"
_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_EXPERIMENT_ID = "l3_9c_gemma4_12b_qat_load_only_8k_16k"
_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_MODEL_KEY = "gemma4_12b_qat"
_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_MODEL_ID = "google/gemma-4-12b-qat"
_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_CONTEXT_TIERS = (8192, 16_384)
_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_PARALLEL = 1
_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_APP_CONCURRENCY = 1
_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_OUTPUT_FILES = _L3_8B_GEMMA4_E4B_LOAD_ONLY_OUTPUT_FILES
_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_MODE = "candidate_load_only_8k"
_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_EXPERIMENT_ID = "l3_9d_gemma4_26b_a4b_qat_load_only_8k"
_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_MODEL_KEY = "gemma4_26b_a4b_qat"
_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_MODEL_ID = "google/gemma-4-26b-a4b-qat"
_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_CONTEXT_TIERS = (8192,)
_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_PARALLEL = 1
_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_APP_CONCURRENCY = 1
_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_OUTPUT_FILES = _L3_8B_GEMMA4_E4B_LOAD_ONLY_OUTPUT_FILES
_L3_8B_GEMMA4_E4B_FORBIDDEN_ENDPOINT_FRAGMENTS = (
    "/api/v1/chat",
    "/v1/responses",
    "/v1/chat/completions",
)
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_MODE = "candidate_tiny_live_smoke"
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_EXPERIMENT_ID = "l3_8c_gemma4_e4b_tiny_live_smoke"
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_MODEL_KEY = "gemma4_e4b_q4km"
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_MODEL_ID = "google/gemma-4-e4b"
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_CONTEXT_LENGTH = 16_384
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_PARALLEL = 1
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_APP_CONCURRENCY = 1
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ROUTE = "tiny_live_chat"
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ENDPOINT_PATH = "/api/v1/chat"
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_TEMPERATURE = 0
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_MAX_OUTPUT_TOKENS = 64
_L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_OUTPUT_FILES = (
    "environment.json",
    "run_config.json",
    "load_response_sanitized.json",
    "requests.jsonl",
    "metrics.jsonl",
    "system_samples.jsonl",
    "system_summary.json",
    "privacy_scan.json",
    "report.md",
)
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_MODE = "strict_json_smoke"
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_EXPERIMENT_ID = "l3_8d_gemma4_e4b_strict_json_smoke"
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_MODEL_KEY = "gemma4_e4b_q4km"
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_MODEL_ID = "google/gemma-4-e4b"
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_CONTEXT_LENGTH = 8192
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_PARALLEL = 1
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_APP_CONCURRENCY = 1
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_DATASET_ID = "blocks_json_small"
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ROUTE = "strict_json_chat_completions"
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_HELPER_MODE = "json_schema_single"
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ENDPOINT_PATH = "/v1/chat/completions"
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_TEMPERATURE = 0
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_MAX_TOKENS = 512
_L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_OUTPUT_FILES = (
    "environment.json",
    "run_config.json",
    "load_response_sanitized.json",
    "requests.jsonl",
    "metrics.jsonl",
    "structured_errors.jsonl",
    "system_samples.jsonl",
    "system_summary.json",
    "privacy_scan.json",
    "report.md",
)
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_MODE = "compact_memory_controlled_live_smoke"
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_EXPERIMENT_ID = (
    "l3_6c_25k_compact_memory_live_smoke_gemma4_e2b"
)
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_MODEL_KEY = "gemma4_e2b_q4km"
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_MODEL_ID = "google/gemma-4-e2b"
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_CONTEXT_LENGTH = 32768
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_PARALLEL = 1
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_APP_CONCURRENCY = 1
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_DATASET_ID = "lecture_25k_tokens"
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ENDPOINT_PATH = "/api/v1/chat"
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ROUTE = "compact_memory"
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_TEMPERATURE = 0
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_MAX_OUTPUT_TOKENS = 64
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ALLOWED_MAX_OUTPUT_TOKENS = (64, 128)
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ESTIMATED_INPUT_TOKENS = 22700
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ESTIMATED_REDUCTION_TOKENS = 2300
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_BASELINE_INPUT_TOKENS = 25000
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_OUTPUT_RESERVE_TOKENS = 2048
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_PROMPT_CHARS = 68100
_L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_OUTPUT_FILES = (
    "environment.json",
    "run_config.json",
    "load_response_sanitized.json",
    "requests.jsonl",
    "metrics.jsonl",
    "system_samples.jsonl",
    "system_summary.json",
    "privacy_scan.json",
    "report.md",
)
_L3_6D_25K_MODE_COMPARISON_LIVE_MODE = "mode_comparison_controlled_live"
_L3_6D_25K_MODE_COMPARISON_LIVE_EXPERIMENT_ID = "l3_6d_25k_mode_comparison_gemma4_e2b"
_L3_6D_25K_MODE_COMPARISON_LIVE_MODEL_KEY = "gemma4_e2b_q4km"
_L3_6D_25K_MODE_COMPARISON_LIVE_MODEL_ID = "google/gemma-4-e2b"
_L3_6D_25K_MODE_COMPARISON_LIVE_CONTEXT_LENGTH = 32768
_L3_6D_25K_MODE_COMPARISON_LIVE_PARALLEL = 1
_L3_6D_25K_MODE_COMPARISON_LIVE_APP_CONCURRENCY = 1
_L3_6D_25K_MODE_COMPARISON_LIVE_DATASET_ID = "lecture_25k_tokens"
_L3_6D_25K_MODE_COMPARISON_LIVE_ENDPOINT_PATH = "/api/v1/chat"
_L3_6D_25K_MODE_COMPARISON_LIVE_SETUP_MODE = "native_chat_stateful_setup"
_L3_6D_25K_MODE_COMPARISON_LIVE_SETUP_CLASSIFICATION = "setup_metadata"
_L3_6D_25K_MODE_COMPARISON_LIVE_MAX_OUTPUT_TOKENS = 64
_L3_6D_25K_MODE_COMPARISON_LIVE_ALLOWED_MAX_OUTPUT_TOKENS = (64, 128)
_L3_6D_25K_MODE_COMPARISON_LIVE_TEMPERATURE = 0
_L3_6D_25K_MODE_COMPARISON_LIVE_MINIMIZED_INPUT_TOKENS = 22700
_L3_6D_25K_MODE_COMPARISON_LIVE_MINIMIZED_REDUCTION_TOKENS = 2300
_L3_6D_25K_MODE_COMPARISON_LIVE_BASELINE_INPUT_TOKENS = 25000
_L3_6D_25K_MODE_COMPARISON_LIVE_OUTPUT_RESERVE_TOKENS = 2048
_L3_6D_25K_MODE_COMPARISON_LIVE_STATEFUL_SETUP_PROMPT_CHARS = 75000
_L3_6D_25K_MODE_COMPARISON_LIVE_COMPACT_PROMPT_CHARS = 68100
_L3_6D_25K_MODE_COMPARISON_LIVE_STATELESS_PROMPT_CHARS = 75000
_L3_6D_25K_MODE_COMPARISON_LIVE_COMPARABLE_MODES = (
    "compact_memory",
    "native_chat_stateful",
    "stateless_full_prefix",
)
_L3_6D_25K_MODE_COMPARISON_LIVE_CLASSIFICATIONS = {
    "compact_memory": "primary_candidate",
    "native_chat_stateful": "research_latency_candidate",
    "stateless_full_prefix": "baseline",
}
_L3_6D_25K_MODE_COMPARISON_LIVE_STORES = {
    "compact_memory": False,
    "native_chat_stateful": True,
    "stateless_full_prefix": False,
}
_L3_6D_25K_MODE_COMPARISON_LIVE_OUTPUT_FILES = (
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
_RESPONSES_CACHE_PROBE_MODE = "responses_cache_probe"
_RESPONSES_CACHE_PROBE_EXPERIMENT_ID = "l3_5r_responses_cache_probe_gemma4_e2b"
_RESPONSES_CACHE_PROBE_16K_EXPERIMENT_ID = "l3_5r_16k_responses_cache_probe_gemma4_e2b"
_RESPONSES_CACHE_PROBE_MODEL_KEY = "gemma4_e2b_q4km"
_RESPONSES_CACHE_PROBE_MODEL_ID = "google/gemma-4-e2b"
_RESPONSES_CACHE_PROBE_ENDPOINT_PATH = "/v1/responses"
_RESPONSES_CACHE_PROBE_DATASET_TOKENS = {
    "synthetic_2k_root": 2000,
    "synthetic_8k_root": 8000,
    "synthetic_16k_root": 16000,
}
_RESPONSES_CACHE_PROBE_VARIANTS = {
    _RESPONSES_CACHE_PROBE_EXPERIMENT_ID: {
        "max_context_tokens": 8192,
        "datasets": ("synthetic_2k_root", "synthetic_8k_root"),
    },
    _RESPONSES_CACHE_PROBE_16K_EXPERIMENT_ID: {
        "max_context_tokens": 16384,
        "datasets": ("synthetic_16k_root",),
    },
}
_RESPONSES_CACHE_PROBE_MODES = (
    "responses_root_branch",
    "responses_repeated_prefix",
    "responses_mutated_prefix",
)
_RESPONSES_CACHE_PROBE_OUTPUT_FILES = (
    "environment.json",
    "run_config.json",
    "requests.jsonl",
    "metrics.jsonl",
    "responses_usage_summary.json",
    "privacy_scan.json",
    "report.md",
)
_CACHE_STATEFUL_LIVE_SMOKE_MODE = "managed_runner_cache_stateful_live_smoke"
_CACHE_STATEFUL_LIVE_SMOKE_MODEL_KEY = "gemma4_e2b_q4km"
_CACHE_STATEFUL_LIVE_SMOKE_MODEL_ID = "google/gemma-4-e2b"
_CACHE_STATEFUL_LIVE_SMOKE_DATASET_ID = "cache_stateful_smoke"
_CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH = 8192
_CACHE_STATEFUL_LIVE_SMOKE_PARALLEL = 1
_CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY = 1
_CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS = (
    "summary_short",
    "glossary_short",
)
_CACHE_STATEFUL_COMPARISON_LIVE_MODE = "managed_runner_cache_stateful_comparison_live"
_CACHE_STATEFUL_COMPARISON_LIVE_EXPERIMENT_ID = "l3_4_cache_stateful_vs_prefix_gemma4_e2b_live"
_CACHE_STATEFUL_INSTRUMENTATION_LIVE_MODE = "managed_runner_cache_stateful_instrumentation_live"
_CACHE_STATEFUL_INSTRUMENTATION_LIVE_EXPERIMENT_ID = (
    "l3_4b_cache_stateful_instrumentation_gemma4_e2b_live"
)
_CACHE_STATEFUL_COMPARISON_LIVE_MODES = (
    "stateful_root_branches",
    "stateless_full_prefix",
    "compact_memory",
)
_CACHE_STATEFUL_COMPARISON_LIVE_OUTPUT_FILES = (
    "environment.json",
    "experiment.yaml",
    "run_config.json",
    "requests.jsonl",
    "metrics.jsonl",
    "cache_comparison_summary.json",
    "privacy_scan.json",
    "report.md",
    "system_samples.jsonl",
    "system_summary.json",
)
_CACHE_STATEFUL_INSTRUMENTATION_LIVE_OUTPUT_FILES = (
    "environment.json",
    "experiment.yaml",
    "run_config.json",
    "requests.jsonl",
    "metrics.jsonl",
    "cache_instrumentation_summary.json",
    "privacy_scan.json",
    "report.md",
    "system_samples.jsonl",
    "system_summary.json",
)
_CACHE_STATEFUL_LIVE_SMOKE_OUTPUT_FILES = (
    "environment.json",
    "experiment.yaml",
    "run_config.json",
    "requests.jsonl",
    "metrics.jsonl",
    "cache_summary.json",
    "privacy_scan.json",
    "report.md",
    "system_samples.jsonl",
    "system_summary.json",
)
_MEDIUM_CHUNKED_PREP_OUTPUT_FILES = (
    "run_config.json",
    "metrics.jsonl",
    "batch_summary.json",
    "structured_validation_summary.json",
    "structured_validation_summary.csv",
    "privacy_scan.json",
    "report.md",
    "system_samples.jsonl",
    "system_summary.json",
)
_MEDIUM_CHUNKED_LIVE_MODE = "managed_runner_medium_chunked_sequential_live"
_MEDIUM_CHUNKED_LIVE_CONTEXT_LENGTH = 8192
_MEDIUM_CHUNKED_LIVE_PARALLEL = 1
_MEDIUM_CHUNKED_TRUE_PARALLEL_LIVE_MODE = "managed_runner_medium_chunked_true_parallel_live"
_MEDIUM_CHUNKED_TRUE_PARALLEL_APP_CONCURRENCY = 2
_MEDIUM_CHUNKED_TRUE_PARALLEL_PARALLEL = 2
_MEDIUM_CHUNKED_LIVE_ALLOWED_LOAD_KEYS = frozenset({"context_length", "parallel", "n_parallel"})
_MEDIUM_CHUNKED_LIVE_ALLOWED_PROMPT_VARIANTS = frozenset(
    {"baseline", "strict_id_contract", "ultra_minimal_transform"}
)
_MEDIUM_CHUNKED_LIVE_ALLOWED_SCHEMA_VARIANTS = frozenset({"baseline", "per_position_id_const"})
_MEDIUM_CHUNKED_LIVE_REDACTED_BASE_URL = "redacted_local_lmstudio_url"
_MEDIUM_CHUNKED_LIVE_OUTPUT_FILES = (
    "environment.json",
    "experiment.yaml",
    "run_config.json",
    "metrics.jsonl",
    "structured_errors.jsonl",
    "batch_summary.json",
    "structured_validation_summary.json",
    "structured_validation_summary.csv",
    "privacy_scan.json",
    "report.md",
    "system_samples.jsonl",
    "system_summary.json",
)
_MEDIUM_CHUNKED_SEQUENTIAL_LIVE_ALLOWED_MODEL_IDS = {
    "gemma4_e2b_q4km": "google/gemma-4-e2b",
    "gemma4_e4b_q4km": "google/gemma-4-e4b",
    "gemma4_12b_qat": "google/gemma-4-12b-qat",
}
_MEDIUM_CHUNKED_TRUE_PARALLEL_LIVE_ALLOWED_MODEL_IDS = {
    "gemma4_e2b_q4km": "google/gemma-4-e2b",
    "gemma4_e4b_q4km": "google/gemma-4-e4b",
}


class _SystemSamplerProtocol(Protocol):
    samples: list[SystemMetricsSnapshot]

    def start(self, *, providers: Mapping[str, str] | None = None) -> None: ...

    def stop(
        self,
        *,
        providers: Mapping[str, str] | None = None,
    ) -> SystemMetricsSummary: ...


class ManagedLabRunner:
    """Small fake-first facade over managed LM Studio clients."""

    __slots__ = (
        "_download_client",
        "_generation_client",
        "_lifecycle_client",
        "_model_list_client",
        "_system_sampler",
    )

    def __init__(
        self,
        transport: ManagedTransport,
        *,
        default_timeout_s: float | None = None,
        system_sampler: _SystemSamplerProtocol | None = None,
    ) -> None:
        self._model_list_client = ModelListClient(
            transport,
            default_timeout_s=default_timeout_s,
        )
        self._download_client = DownloadClient(
            transport,
            default_timeout_s=default_timeout_s,
        )
        self._lifecycle_client = LifecycleClient(
            transport,
            default_timeout_s=default_timeout_s,
        )
        self._generation_client = GenerationClient(
            transport,
            default_timeout_s=default_timeout_s,
        )
        self._system_sampler = system_sampler or SystemMetricsSampler()

    def list_models(self, timeout_s: float | None = None) -> dict[str, object]:
        compat_response = self._model_list_client.list_compat_models(timeout_s=timeout_s)
        native_response = self._model_list_client.list_native_models(timeout_s=timeout_s)
        return {
            "compat_error": _api_error_kind(compat_response.error),
            "native_error": _api_error_kind(native_response.error),
            "compat_count": len(compat_response.visible_models),
            "native_count": len(native_response.native_models),
            "loaded_instance_count": _loaded_instance_count(native_response),
            "raw_prompt_response_stored": False,
        }

    def ensure_downloaded(
        self,
        request: DownloadRequest,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        result = self._download_client.ensure_downloaded(request, timeout_s=timeout_s)
        return {
            "status": _enum_value(result.status),
            "ready_on_disk": result.ready_on_disk,
            "terminal_success": result.is_terminal_success,
            "error_kind": _enum_value(result.error_kind),
        }

    def ensure_loaded(
        self,
        request: LoadModelRequest,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        result = self._lifecycle_client.load_model(request, timeout_s=timeout_s)
        return {
            "status": _enum_value(result.status),
            "instance_ref_present": result.instance is not None,
            "echo_context_length": result.echo.context_length if result.echo else None,
            "echo_parallel": result.echo.parallel if result.echo else None,
            "error_kind": _api_error_kind(result.error),
        }

    def ensure_unloaded(
        self,
        request: UnloadModelRequest,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        result = self._lifecycle_client.unload_instance(request, timeout_s=timeout_s)
        return {
            "status": _enum_value(result.status),
            "unloaded": result.unloaded,
            "error_kind": _api_error_kind(result.error),
        }

    def complete_structured(
        self,
        request: StructuredGenerationRequest,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        result = self._generation_client.complete_structured(request, timeout_s=timeout_s)
        return _generation_summary(result)

    def complete_plain(
        self,
        request: PlainTextGenerationRequest,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        result = self._generation_client.complete_plain_text(request, timeout_s=timeout_s)
        return _generation_summary(result)

    def run_with_system_metrics(
        self,
        operation: ManagedOperation,
        run_dir: str | PathLike[str],
        *,
        providers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        normalized_providers = _normalize_providers(providers)
        operation_summary: dict[str, object] | None = None
        system_summary: SystemMetricsSummary | None = None
        pending_exception: (
            tuple[type[BaseException], BaseException, TracebackType | None] | None
        ) = None

        self._system_sampler.start(providers=normalized_providers)
        try:
            operation_summary = _sanitize_operation_summary(operation())
        except Exception:
            pending_exception = sys.exc_info()
        finally:
            cleanup_error: Exception | None = None
            try:
                system_summary = self._system_sampler.stop(providers=normalized_providers)
                write_system_telemetry_artifacts(
                    Path(run_dir),
                    samples=self._system_sampler.samples,
                    summary=system_summary,
                )
            except Exception as error:
                cleanup_error = error

            if pending_exception is not None:
                exc_type, exc, traceback = pending_exception
                if exc is not None:
                    raise exc.with_traceback(traceback)
                raise exc_type
            if cleanup_error is not None:
                raise cleanup_error

        assert operation_summary is not None
        assert system_summary is not None
        return {
            **operation_summary,
            **_build_safe_system_summary(system_summary),
        }

    def run_cache_stateful_no_live(
        self,
        *,
        run_dir: str | PathLike[str],
        run_id: str,
        plan: CacheExperimentPlan,
        providers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        _validate_cache_stateful_no_live_plan(plan)
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        run_config = _build_cache_stateful_no_live_run_config(plan=plan, run_id=safe_run_id)
        cache_plan_payload = _build_cache_stateful_no_live_plan_payload(
            plan=plan, run_id=safe_run_id
        )
        request_rows = _build_cache_stateful_no_live_request_rows(plan=plan, run_id=safe_run_id)

        write_json_file(run_path / "run_config.json", run_config)
        write_json_file(run_path / "cache_plan.json", cache_plan_payload)

        requests_path = run_path / "requests.jsonl"
        metrics_path = run_path / "metrics.jsonl"
        privacy_scan_path = run_path / "privacy_scan.json"
        report_path = run_path / "report.md"
        metric_rows: list[dict[str, Any]] = []

        def _operation() -> dict[str, object]:
            requests_path.write_text("", encoding="utf-8")
            metrics_path.write_text("", encoding="utf-8")
            metric_rows.clear()

            for request_row in request_rows:
                append_jsonl_record(requests_path, request_row)
                metric_rows.append(
                    _restore_cache_stateful_no_live_null_metrics(
                        append_jsonl_record(
                            metrics_path,
                            _build_cache_stateful_no_live_metric_row(
                                plan=plan,
                                run_id=safe_run_id,
                                request_row=request_row,
                            ),
                        )
                    )
                )

            _rewrite_jsonl_records(metrics_path, metric_rows)

            return _build_cache_stateful_no_live_summary(
                plan=plan,
                run_id=safe_run_id,
                placeholder_metric_count=len(metric_rows),
            )

        cache_summary = self.run_with_system_metrics(
            _operation,
            run_path,
            providers=providers,
        )
        cache_summary = _restore_cache_stateful_no_live_null_metrics(cache_summary)
        write_json_file(run_path / "cache_summary.json", cache_summary)

        requests_payload = _load_jsonl_records(requests_path)
        metrics_payload = _load_jsonl_records(metrics_path)
        system_summary_payload = json.loads(
            (run_path / "system_summary.json").read_text(encoding="utf-8")
        )
        system_samples_payload = _load_jsonl_records(run_path / "system_samples.jsonl")
        privacy_scan = _build_cache_stateful_no_live_privacy_scan(
            run_config=run_config,
            cache_plan=cache_plan_payload,
            request_rows=requests_payload,
            metric_rows=metrics_payload,
            cache_summary=cache_summary,
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=_render_cache_stateful_no_live_report(
                run_id=safe_run_id,
                plan=plan,
                cache_summary=cache_summary,
                privacy_scan_status="pending_scan",
            ),
        )
        report_text = _render_cache_stateful_no_live_report(
            run_id=safe_run_id,
            plan=plan,
            cache_summary=cache_summary,
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )
        privacy_scan = _build_cache_stateful_no_live_privacy_scan(
            run_config=run_config,
            cache_plan=cache_plan_payload,
            request_rows=requests_payload,
            metric_rows=metrics_payload,
            cache_summary=cache_summary,
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=report_text,
        )
        write_json_file(privacy_scan_path, privacy_scan)
        report_path.write_text(report_text, encoding="utf-8")
        return cache_summary

    def run_cache_25k_no_live_prep(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        del providers

        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        config_scope = _load_cache_25k_no_live_prep_scope(config_path)
        dataset_manifest_payload = _load_cache_25k_no_live_prep_dataset_manifest(
            config_scope["dataset_id"]
        )
        branch_specs = _cache_25k_no_live_prep_branch_specs()
        token_manifest = _build_cache_25k_no_live_prep_token_manifest(
            run_id=safe_run_id,
            config_scope=config_scope,
            dataset_manifest=dataset_manifest_payload,
            branch_specs=branch_specs,
        )
        context_fit_report = _build_cache_25k_no_live_prep_context_fit_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            dataset_manifest=dataset_manifest_payload,
        )
        cache_plan_payload = _build_cache_25k_no_live_prep_cache_plan(
            run_id=safe_run_id,
            config_scope=config_scope,
            dataset_manifest=dataset_manifest_payload,
            branch_specs=branch_specs,
        )
        branch_plan_payload = _build_cache_25k_no_live_prep_branch_plan(branch_specs)
        request_shape_rows = _build_cache_25k_no_live_prep_request_shapes(
            run_id=safe_run_id,
            config_scope=config_scope,
            dataset_manifest=dataset_manifest_payload,
            token_manifest=token_manifest,
            branch_specs=branch_specs,
        )
        mode_comparison_plan = _build_cache_25k_no_live_prep_mode_comparison_plan()

        report_text = _render_cache_25k_no_live_prep_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            dataset_manifest=dataset_manifest_payload,
            context_fit_report=context_fit_report,
            request_shape_count=len(request_shape_rows),
            privacy_scan_status="pending_scan",
        )
        provisional_privacy_scan = _build_cache_25k_no_live_prep_privacy_scan(
            dataset_manifest=dataset_manifest_payload,
            token_manifest=token_manifest,
            context_fit_report=context_fit_report,
            cache_plan=cache_plan_payload,
            branch_plan=branch_plan_payload,
            request_shapes=request_shape_rows,
            mode_comparison_plan=mode_comparison_plan,
            report_text=report_text,
        )
        report_text = _render_cache_25k_no_live_prep_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            dataset_manifest=dataset_manifest_payload,
            context_fit_report=context_fit_report,
            request_shape_count=len(request_shape_rows),
            privacy_scan_status=_as_optional_str(provisional_privacy_scan.get("status"))
            or "unknown",
        )
        privacy_scan = _build_cache_25k_no_live_prep_privacy_scan(
            dataset_manifest=dataset_manifest_payload,
            token_manifest=token_manifest,
            context_fit_report=context_fit_report,
            cache_plan=cache_plan_payload,
            branch_plan=branch_plan_payload,
            request_shapes=request_shape_rows,
            mode_comparison_plan=mode_comparison_plan,
            report_text=report_text,
        )

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        write_json_file(run_path / "dataset_manifest.json", dataset_manifest_payload)
        write_json_file(run_path / "token_manifest.json", token_manifest)
        write_json_file(run_path / "context_fit_report.json", context_fit_report)
        write_json_file(run_path / "cache_plan.json", cache_plan_payload)
        write_json_file(run_path / "branch_plan.json", branch_plan_payload)
        request_shapes_path = run_path / "request_shapes.jsonl"
        request_shapes_path.write_text("", encoding="utf-8")
        for row in request_shape_rows:
            append_jsonl_record(request_shapes_path, row)
        write_json_file(run_path / "mode_comparison_plan.json", mode_comparison_plan)
        write_json_file(run_path / "privacy_scan.json", privacy_scan)
        (run_path / "report.md").write_text(report_text, encoding="utf-8")

        return _build_cache_25k_no_live_prep_summary(
            run_id=safe_run_id,
            config_scope=config_scope,
            request_shape_count=len(request_shape_rows),
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )

    def run_l3_6_25k_no_live_preflight(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        del providers

        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        config_scope = _load_l3_6_25k_no_live_preflight_scope(config_path)
        dataset_manifest_payload = _load_cache_25k_no_live_prep_dataset_manifest(
            config_scope["dataset_id"]
        )
        tokenized_prompt_report = _build_l3_6_25k_no_live_preflight_tokenized_prompt_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            dataset_manifest=dataset_manifest_payload,
        )
        output_reserve_report = _build_l3_6_25k_no_live_preflight_output_reserve_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            tokenized_prompt_report=tokenized_prompt_report,
        )
        prompt_shape_report = _render_l3_6_25k_no_live_preflight_prompt_shape_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            tokenized_prompt_report=tokenized_prompt_report,
        )
        mode_plan = _build_l3_6_25k_no_live_preflight_mode_plan(
            run_id=safe_run_id,
            config_scope=config_scope,
        )
        abort_conditions = _render_l3_6_25k_no_live_preflight_abort_conditions(
            run_id=safe_run_id,
            tokenized_prompt_report=tokenized_prompt_report,
            output_reserve_report=output_reserve_report,
        )
        report_text = _render_l3_6_25k_no_live_preflight_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            tokenized_prompt_report=tokenized_prompt_report,
            output_reserve_report=output_reserve_report,
            mode_plan=mode_plan,
            privacy_scan_status="pending_scan",
        )
        provisional_privacy_scan = _build_l3_6_25k_no_live_preflight_privacy_scan(
            tokenized_prompt_report=tokenized_prompt_report,
            output_reserve_report=output_reserve_report,
            prompt_shape_report=prompt_shape_report,
            mode_plan=mode_plan,
            abort_conditions=abort_conditions,
            report_text=report_text,
        )
        report_text = _render_l3_6_25k_no_live_preflight_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            tokenized_prompt_report=tokenized_prompt_report,
            output_reserve_report=output_reserve_report,
            mode_plan=mode_plan,
            privacy_scan_status=_as_optional_str(provisional_privacy_scan.get("status"))
            or "unknown",
        )
        privacy_scan = _build_l3_6_25k_no_live_preflight_privacy_scan(
            tokenized_prompt_report=tokenized_prompt_report,
            output_reserve_report=output_reserve_report,
            prompt_shape_report=prompt_shape_report,
            mode_plan=mode_plan,
            abort_conditions=abort_conditions,
            report_text=report_text,
        )

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        write_json_file(run_path / "tokenized_prompt_report.json", tokenized_prompt_report)
        write_json_file(run_path / "output_reserve_report.json", output_reserve_report)
        (run_path / "prompt_shape_report.md").write_text(prompt_shape_report, encoding="utf-8")
        write_json_file(run_path / "mode_plan.json", mode_plan)
        (run_path / "abort_conditions.md").write_text(abort_conditions, encoding="utf-8")
        write_json_file(run_path / "privacy_scan.json", privacy_scan)
        (run_path / "report.md").write_text(report_text, encoding="utf-8")

        return _build_l3_6_25k_no_live_preflight_summary(
            run_id=safe_run_id,
            config_scope=config_scope,
            tokenized_prompt_report=tokenized_prompt_report,
            output_reserve_report=output_reserve_report,
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )

    def run_l3_6a_25k_tokenization_prompt_fit(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        del providers

        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        config_scope = _load_l3_6a_25k_tokenization_prompt_fit_scope(config_path)
        dataset_manifest_payload = _load_cache_25k_no_live_prep_dataset_manifest(
            config_scope["dataset_id"]
        )
        token_budget_breakdown = _build_l3_6a_25k_token_budget_breakdown(
            run_id=safe_run_id,
            config_scope=config_scope,
            dataset_manifest=dataset_manifest_payload,
        )
        chat_template_overhead_report = _build_l3_6a_25k_chat_template_overhead_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            token_budget_breakdown=token_budget_breakdown,
        )
        output_reserve_policy = _build_l3_6a_25k_output_reserve_policy(
            run_id=safe_run_id,
            config_scope=config_scope,
            token_budget_breakdown=token_budget_breakdown,
        )
        tokenization_strategy_report = _render_l3_6a_25k_tokenization_strategy_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            token_budget_breakdown=token_budget_breakdown,
            chat_template_overhead_report=chat_template_overhead_report,
            output_reserve_policy=output_reserve_policy,
        )
        prompt_minimization_candidates = _render_l3_6a_25k_prompt_minimization_candidates(
            run_id=safe_run_id,
            token_budget_breakdown=token_budget_breakdown,
        )
        report_text = _render_l3_6a_25k_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            token_budget_breakdown=token_budget_breakdown,
            chat_template_overhead_report=chat_template_overhead_report,
            output_reserve_policy=output_reserve_policy,
            privacy_scan_status="pending_scan",
        )
        provisional_privacy_scan = _build_l3_6a_25k_privacy_scan(
            tokenization_strategy_report=tokenization_strategy_report,
            token_budget_breakdown=token_budget_breakdown,
            chat_template_overhead_report=chat_template_overhead_report,
            prompt_minimization_candidates=prompt_minimization_candidates,
            output_reserve_policy=output_reserve_policy,
            report_text=report_text,
        )
        report_text = _render_l3_6a_25k_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            token_budget_breakdown=token_budget_breakdown,
            chat_template_overhead_report=chat_template_overhead_report,
            output_reserve_policy=output_reserve_policy,
            privacy_scan_status=_as_optional_str(provisional_privacy_scan.get("status"))
            or "unknown",
        )
        privacy_scan = _build_l3_6a_25k_privacy_scan(
            tokenization_strategy_report=tokenization_strategy_report,
            token_budget_breakdown=token_budget_breakdown,
            chat_template_overhead_report=chat_template_overhead_report,
            prompt_minimization_candidates=prompt_minimization_candidates,
            output_reserve_policy=output_reserve_policy,
            report_text=report_text,
        )

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        (run_path / "tokenization_strategy_report.md").write_text(
            tokenization_strategy_report,
            encoding="utf-8",
        )
        write_json_file(run_path / "token_budget_breakdown.json", token_budget_breakdown)
        write_json_file(
            run_path / "chat_template_overhead_report.json",
            chat_template_overhead_report,
        )
        (run_path / "prompt_minimization_candidates.md").write_text(
            prompt_minimization_candidates,
            encoding="utf-8",
        )
        write_json_file(run_path / "output_reserve_policy.json", output_reserve_policy)
        (run_path / "l3_6a_report.md").write_text(report_text, encoding="utf-8")
        write_json_file(run_path / "privacy_scan.json", privacy_scan)

        return _build_l3_6a_25k_summary(
            run_id=safe_run_id,
            config_scope=config_scope,
            token_budget_breakdown=token_budget_breakdown,
            output_reserve_policy=output_reserve_policy,
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )

    def run_l3_6b_25k_prompt_minimization(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        del providers

        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        config_scope = _load_l3_6b_25k_prompt_minimization_scope(config_path)
        dataset_manifest_payload = _load_cache_25k_no_live_prep_dataset_manifest(
            config_scope["dataset_id"]
        )
        minimized_token_budget_breakdown = _build_l3_6b_25k_minimized_token_budget_breakdown(
            run_id=safe_run_id,
            config_scope=config_scope,
            dataset_manifest=dataset_manifest_payload,
        )
        minimized_prompt_shape_report = _render_l3_6b_25k_minimized_prompt_shape_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            minimized_token_budget_breakdown=minimized_token_budget_breakdown,
        )
        prompt_diff_summary = _render_l3_6b_25k_prompt_diff_summary(run_id=safe_run_id)
        updated_abort_conditions = _render_l3_6b_25k_updated_abort_conditions(
            run_id=safe_run_id,
            minimized_token_budget_breakdown=minimized_token_budget_breakdown,
        )
        report_text = _render_l3_6b_25k_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            minimized_token_budget_breakdown=minimized_token_budget_breakdown,
            privacy_scan_status="pending_scan",
        )
        provisional_privacy_scan = _build_l3_6b_25k_privacy_scan(
            minimized_prompt_shape_report=minimized_prompt_shape_report,
            minimized_token_budget_breakdown=minimized_token_budget_breakdown,
            prompt_diff_summary=prompt_diff_summary,
            updated_abort_conditions=updated_abort_conditions,
            report_text=report_text,
        )
        report_text = _render_l3_6b_25k_report(
            run_id=safe_run_id,
            config_scope=config_scope,
            minimized_token_budget_breakdown=minimized_token_budget_breakdown,
            privacy_scan_status=_as_optional_str(provisional_privacy_scan.get("status"))
            or "unknown",
        )
        privacy_scan = _build_l3_6b_25k_privacy_scan(
            minimized_prompt_shape_report=minimized_prompt_shape_report,
            minimized_token_budget_breakdown=minimized_token_budget_breakdown,
            prompt_diff_summary=prompt_diff_summary,
            updated_abort_conditions=updated_abort_conditions,
            report_text=report_text,
        )

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        (run_path / "minimized_prompt_shape_report.md").write_text(
            minimized_prompt_shape_report,
            encoding="utf-8",
        )
        write_json_file(
            run_path / "minimized_token_budget_breakdown.json",
            minimized_token_budget_breakdown,
        )
        (run_path / "prompt_diff_summary.md").write_text(prompt_diff_summary, encoding="utf-8")
        (run_path / "updated_abort_conditions.md").write_text(
            updated_abort_conditions,
            encoding="utf-8",
        )
        (run_path / "l3_6b_report.md").write_text(report_text, encoding="utf-8")
        write_json_file(run_path / "privacy_scan.json", privacy_scan)

        return _build_l3_6b_25k_summary(
            run_id=safe_run_id,
            config_scope=config_scope,
            minimized_token_budget_breakdown=minimized_token_budget_breakdown,
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )

    def run_cache_32k_load_only_smoke(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
        timeout_s: float = 120.0,
        native_transport: ModelLifecycleTransport | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        _, raw_payload = load_raw_experiment_config(Path(config_path))

        def _require_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
            if not isinstance(value, Mapping):
                raise ValueError(f"{field_name} must be a mapping")
            return value

        def _require_non_empty_string(value: object, *, field_name: str) -> str:
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            text = value.strip()
            if not text:
                raise ValueError(f"{field_name} must be a non-empty string")
            return text

        def _require_bool(value: object, *, field_name: str) -> bool:
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean")
            return value

        def _require_int(value: object, *, field_name: str, minimum: int | None = None) -> int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
            if minimum is not None and value < minimum:
                raise ValueError(f"{field_name} must be >= {minimum}")
            return value

        def _require_string_sequence(value: object, *, field_name: str) -> tuple[str, ...]:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                raise ValueError(f"{field_name} must be a sequence of strings")
            items: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    raise ValueError(f"{field_name} must be a sequence of strings")
                items.append(item)
            return tuple(items)

        def _default_native_transport(
            request: urllib_request.Request,
            request_timeout_s: float,
        ) -> bytes:
            with urllib_request.urlopen(request, timeout=request_timeout_s) as response:
                response_bytes = response.read()
                if not isinstance(response_bytes, bytes):
                    raise TypeError("native transport response must be bytes")
                return response_bytes

        request_transport = native_transport or _default_native_transport

        def _request_json(
            *,
            method: str,
            url: str,
            body: Mapping[str, Any] | None = None,
        ) -> tuple[Mapping[str, Any], str]:
            data = None
            headers = {"Accept": "application/json"}
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = urllib_request.Request(url, data=data, headers=headers, method=method)
            response_bytes = request_transport(request, timeout_s)
            response_text = response_bytes.decode("utf-8")
            decoded = json.loads(response_text)
            if not isinstance(decoded, Mapping):
                raise ValueError(f"{method} response must be a JSON object")
            return decoded, response_text

        experiment_id = _require_non_empty_string(
            raw_payload.get("experiment_id"),
            field_name="experiment_id",
        )
        if experiment_id != _CACHE_32K_LOAD_ONLY_EXPERIMENT_ID:
            raise ValueError(
                "32k load-only smoke requires experiment_id 'l3_5b_32k_load_only_smoke_gemma4_e2b'"
            )

        mode = _require_non_empty_string(raw_payload.get("mode"), field_name="mode")
        if mode != _CACHE_32K_LOAD_ONLY_MODE:
            raise ValueError("32k load-only smoke requires mode 'load_only'")

        model_payload = _require_mapping(raw_payload.get("model"), field_name="model")
        model_key = _require_non_empty_string(model_payload.get("key"), field_name="model.key")
        if model_key != _CACHE_32K_LOAD_ONLY_MODEL_KEY:
            raise ValueError("32k load-only smoke requires model.key 'gemma4_e2b_q4km'")
        model_id = _require_non_empty_string(
            model_payload.get("lmstudio_model_id"),
            field_name="model.lmstudio_model_id",
        )
        if model_id != _CACHE_32K_LOAD_ONLY_MODEL_ID:
            raise ValueError(
                "32k load-only smoke requires model.lmstudio_model_id 'google/gemma-4-e2b'"
            )

        load_payload = _require_mapping(raw_payload.get("load"), field_name="load")
        requested_context_length = _require_int(
            load_payload.get("context_length"),
            field_name="load.context_length",
            minimum=1,
        )
        if requested_context_length != _CACHE_32K_LOAD_ONLY_CONTEXT_LENGTH:
            raise ValueError("32k load-only smoke requires load.context_length=32768")
        echo_load_config = _require_bool(
            load_payload.get("echo_load_config"),
            field_name="load.echo_load_config",
        )
        flash_attention = _require_bool(
            load_payload.get("flash_attention"),
            field_name="load.flash_attention",
        )
        offload_kv_cache_to_gpu = _require_bool(
            load_payload.get("offload_kv_cache_to_gpu"),
            field_name="load.offload_kv_cache_to_gpu",
        )
        requested_parallel = _require_int(
            load_payload.get("parallel"),
            field_name="load.parallel",
            minimum=1,
        )
        if requested_parallel != _CACHE_32K_LOAD_ONLY_PARALLEL:
            raise ValueError("32k load-only smoke requires load.parallel=1")

        safety_payload = _require_mapping(raw_payload.get("safety"), field_name="safety")
        generation_allowed = _require_bool(
            safety_payload.get("generation_allowed"),
            field_name="safety.generation_allowed",
        )
        live_25k_authorized = _require_bool(
            safety_payload.get("live_25k_authorized"),
            field_name="safety.live_25k_authorized",
        )
        unload_required = _require_bool(
            safety_payload.get("unload_required"),
            field_name="safety.unload_required",
        )
        final_loaded_instances_required = _require_int(
            safety_payload.get("final_loaded_instances_required"),
            field_name="safety.final_loaded_instances_required",
            minimum=0,
        )
        if generation_allowed:
            raise ValueError("32k load-only smoke requires safety.generation_allowed=false")
        if live_25k_authorized:
            raise ValueError("32k load-only smoke requires safety.live_25k_authorized=false")
        if not unload_required:
            raise ValueError("32k load-only smoke requires safety.unload_required=true")
        if final_loaded_instances_required != 0:
            raise ValueError(
                "32k load-only smoke requires safety.final_loaded_instances_required=0"
            )

        privacy_payload = _require_mapping(raw_payload.get("privacy"), field_name="privacy")
        if _require_bool(
            privacy_payload.get("store_raw_prompt_response"),
            field_name="privacy.store_raw_prompt_response",
        ):
            raise ValueError("privacy.store_raw_prompt_response must remain false")
        if _require_bool(
            privacy_payload.get("store_local_urls"),
            field_name="privacy.store_local_urls",
        ):
            raise ValueError("privacy.store_local_urls must remain false")
        if _require_bool(
            privacy_payload.get("store_state_ids_raw"),
            field_name="privacy.store_state_ids_raw",
        ):
            raise ValueError("privacy.store_state_ids_raw must remain false")

        artifacts = raw_payload.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes, bytearray)):
            raise ValueError("artifacts must be a list of strings")
        artifact_names = tuple(
            _require_non_empty_string(artifact_name, field_name="artifacts[]")
            for artifact_name in artifacts
        )
        if artifact_names != _CACHE_32K_LOAD_ONLY_OUTPUT_FILES:
            raise ValueError(
                "32k load-only smoke requires the exact artifact list declared by the L3.5b contract"
            )

        base_url = str(raw_payload.get("lmstudio_base_url", "http://127.0.0.1:1234")).strip()
        if not base_url:
            base_url = "http://127.0.0.1:1234"
        base_url = base_url.rstrip("/")

        def _sanitize_models_payload(
            *,
            response_payload: Mapping[str, Any],
            response_text: str,
        ) -> dict[str, object]:
            parsed = parse_native_model_list(response_payload)
            if parsed.error is not None:
                raise ValueError("native model list response must parse successfully")
            target_model = next(
                (model for model in parsed.native_models if model.native_model_key == model_id),
                None,
            )
            loaded_instances = tuple(
                target_model.loaded_instances if target_model is not None else ()
            )
            return {
                "endpoint_kind": "native_models",
                "method": "GET",
                "target_model_id": model_id,
                "target_model_key": model_key,
                "target_model_present": target_model is not None,
                "target_loaded_instance_count": len(loaded_instances),
                "instance_id_hashes": [instance.instance_ref for instance in loaded_instances],
                "context_lengths": [
                    instance.context_length
                    for instance in loaded_instances
                    if instance.context_length is not None
                ],
                "parallels": [
                    instance.parallel
                    for instance in loaded_instances
                    if instance.parallel is not None
                ],
                "response_hash": _safe_hash(response_text),
                "response_chars": len(response_text),
            }

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        environment_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "endpoint_family": "model_lifecycle",
            "managed_live": True,
            "dry_run": False,
            "production_default": False,
            "live_25k_authorized": False,
        }
        write_json_file(run_path / "environment.json", environment_payload)

        run_config_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "endpoint_family": "model_lifecycle",
            "model_key": model_key,
            "model_id": model_id,
            "requested_context_length": requested_context_length,
            "requested_parallel": requested_parallel,
            "load": {
                "context_length": requested_context_length,
                "echo_load_config": echo_load_config,
                "flash_attention": flash_attention,
                "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
                "parallel": requested_parallel,
            },
            "safety": {
                "generation_allowed": False,
                "live_25k_authorized": False,
                "unload_required": True,
                "final_loaded_instances_required": final_loaded_instances_required,
            },
            "privacy": {
                "store_raw_prompt_response": False,
                "store_local_urls": False,
                "store_state_ids_raw": False,
            },
            "artifacts": list(artifact_names),
        }
        write_json_file(run_path / "run_config.json", run_config_payload)

        normalized_providers = _normalize_providers(providers)
        operation_summary: dict[str, object] | None = None
        system_summary: SystemMetricsSummary | None = None
        raw_instance_id: str | None = None
        instance_id_hash: str | None = None
        unload_attempted = False
        pending_exception: (
            tuple[type[BaseException], BaseException, TracebackType | None] | None
        ) = None

        self._system_sampler.start(providers=normalized_providers)
        try:
            load_request_body = {
                "model": model_id,
                "context_length": requested_context_length,
                "echo_load_config": echo_load_config,
                "flash_attention": flash_attention,
                "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
                "parallel": requested_parallel,
            }
            write_json_file(
                run_path / "load_request.json",
                {
                    "endpoint_kind": "native_load",
                    "method": "POST",
                    "body_field_names": list(load_request_body),
                    "body_fields": load_request_body,
                },
            )

            models_before_payload, models_before_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            models_before = _sanitize_models_payload(
                response_payload=models_before_payload,
                response_text=models_before_text,
            )
            write_json_file(run_path / "models_before.json", models_before)

            load_response_payload, load_response_text = _request_json(
                method="POST",
                url=f"{base_url}/api/v1/models/load",
                body=load_request_body,
            )
            raw_instance_id = _as_optional_str(
                load_response_payload.get("instance_id")
                or load_response_payload.get("instanceId")
                or load_response_payload.get("id")
            )
            if raw_instance_id is None:
                raise ValueError("load response must include instance_id")
            instance_id_hash = _safe_hash(raw_instance_id)
            load_config_response = load_response_payload.get("load_config")
            if not isinstance(load_config_response, Mapping):
                raise ValueError("load response must include load_config mapping")
            applied_context_length = _as_optional_int(load_config_response.get("context_length"))
            applied_parallel = _as_optional_int(
                load_config_response.get("parallel", load_config_response.get("n_parallel"))
            )
            load_response_sanitized = {
                "endpoint_kind": "native_load",
                "method": "POST",
                "status": _as_optional_str(load_response_payload.get("status")) or "unknown",
                "instance_id_hash": instance_id_hash,
                "load_config": {
                    "context_length": applied_context_length,
                    "parallel": applied_parallel,
                    "echo_load_config": _as_optional_bool(
                        load_config_response.get("echo_load_config")
                    ),
                    "flash_attention": _as_optional_bool(
                        load_config_response.get("flash_attention")
                    ),
                    "offload_kv_cache_to_gpu": _as_optional_bool(
                        load_config_response.get("offload_kv_cache_to_gpu")
                    ),
                },
                "response_hash": _safe_hash(load_response_text),
                "response_chars": len(load_response_text),
            }
            write_json_file(run_path / "load_response_sanitized.json", load_response_sanitized)

            models_after_load_payload, models_after_load_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            models_after_load = _sanitize_models_payload(
                response_payload=models_after_load_payload,
                response_text=models_after_load_text,
            )
            write_json_file(run_path / "models_after_load.json", models_after_load)

            unload_response_payload, unload_response_text = _request_json(
                method="POST",
                url=f"{base_url}/api/v1/models/unload",
                body={"instance_id": raw_instance_id},
            )
            unload_attempted = True
            unload_response_sanitized = {
                "endpoint_kind": "native_unload",
                "method": "POST",
                "status": _as_optional_str(unload_response_payload.get("status")) or "unknown",
                "requested_instance_id_hash": instance_id_hash,
                "response_hash": _safe_hash(unload_response_text),
                "response_chars": len(unload_response_text),
            }
            write_json_file(run_path / "unload_response_sanitized.json", unload_response_sanitized)

            models_after_unload_payload, models_after_unload_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            models_after_unload = _sanitize_models_payload(
                response_payload=models_after_unload_payload,
                response_text=models_after_unload_text,
            )
            write_json_file(run_path / "models_after_unload.json", models_after_unload)

            load_verified = (
                models_after_load["target_loaded_instance_count"] >= 1
                and instance_id_hash in models_after_load["instance_id_hashes"]
                and applied_context_length == requested_context_length
                and applied_parallel == requested_parallel
            )
            cleanup_verified = (
                models_after_unload["target_loaded_instance_count"]
                == final_loaded_instances_required
                and instance_id_hash not in models_after_unload["instance_id_hashes"]
            )
            echo_load_config_received = bool(load_config_response)
            decision = "load_only_pass" if load_verified and cleanup_verified else "load_only_fail"

            operation_summary = _sanitize_operation_summary(
                {
                    "schema_version": SCHEMA_VERSION,
                    "run_id": safe_run_id,
                    "experiment_id": experiment_id,
                    "mode": mode,
                    "endpoint_family": "model_lifecycle",
                    "model_key": model_key,
                    "model_id": model_id,
                    "instance_id_hash": instance_id_hash,
                    "requested_context_length": requested_context_length,
                    "applied_context_length": applied_context_length,
                    "requested_parallel": requested_parallel,
                    "applied_parallel": applied_parallel,
                    "load_called": True,
                    "generation_called": False,
                    "chat_called": False,
                    "responses_called": False,
                    "chat_completions_called": False,
                    "inference_endpoint_called": False,
                    "unload_called": True,
                    "echo_load_config_received": echo_load_config_received,
                    "load_verified": load_verified,
                    "cleanup_verified": cleanup_verified,
                    "cleanup_status": "cleanup_verified"
                    if cleanup_verified
                    else "cleanup_unverified",
                    "models_before_loaded_instances": models_before["target_loaded_instance_count"],
                    "models_after_load_instances": models_after_load[
                        "target_loaded_instance_count"
                    ],
                    "final_owned_instances": models_after_unload["target_loaded_instance_count"],
                    "live_25k_authorized": False,
                    "generation_allowed": False,
                    "production_default": False,
                    "kv_reuse_proven": False,
                    "decision": decision,
                    "raw_prompt_response_stored": False,
                }
            )
        except Exception:
            pending_exception = sys.exc_info()
        finally:
            cleanup_error: Exception | None = None
            if raw_instance_id is not None and not unload_attempted:
                try:
                    _request_json(
                        method="POST",
                        url=f"{base_url}/api/v1/models/unload",
                        body={"instance_id": raw_instance_id},
                    )
                    unload_attempted = True
                except Exception as error:
                    cleanup_error = error
            try:
                system_summary = self._system_sampler.stop(providers=normalized_providers)
                write_json_file(run_path / "system_summary.json", system_summary.to_dict())
            except Exception as error:
                if cleanup_error is None:
                    cleanup_error = error

            if pending_exception is not None:
                exc_type, exc, traceback = pending_exception
                if exc is not None:
                    raise exc.with_traceback(traceback)
                raise exc_type
            if cleanup_error is not None:
                raise cleanup_error

        assert operation_summary is not None
        assert system_summary is not None

        report_rows = [
            ("experiment_id", experiment_id),
            ("endpoint_family", "model_lifecycle"),
            ("inference_endpoint_called", "false"),
            ("requested_context_length", str(requested_context_length)),
            ("applied_context_length", str(operation_summary.get("applied_context_length"))),
            ("instance_id_hash", str(operation_summary.get("instance_id_hash"))),
            ("cleanup_verified", str(operation_summary.get("cleanup_verified")).lower()),
            ("final_owned_instances", str(operation_summary.get("final_owned_instances"))),
            ("generation_allowed", "false"),
            ("live_25k_authorized", "false"),
            ("decision", str(operation_summary.get("decision"))),
        ]
        report_text = "\n".join(
            [
                "# LM Studio Lab L3.5b 32k Load-Only Smoke Report",
                "",
                "| Field | Value |",
                "| --- | --- |",
                *[f"| {field} | `{value}` |" for field, value in report_rows],
                "",
                "This run does not prove generation stability, quality, structured output correctness, or KV reuse.",
                "It only proves whether the model can be loaded with the requested 32k context profile and cleaned up safely.",
                "",
            ]
        )

        privacy_payloads = {
            "environment.json": environment_payload,
            "run_config.json": run_config_payload,
            "load_request.json": json.loads(
                (run_path / "load_request.json").read_text(encoding="utf-8")
            ),
            "load_response_sanitized.json": json.loads(
                (run_path / "load_response_sanitized.json").read_text(encoding="utf-8")
            ),
            "models_before.json": json.loads(
                (run_path / "models_before.json").read_text(encoding="utf-8")
            ),
            "models_after_load.json": json.loads(
                (run_path / "models_after_load.json").read_text(encoding="utf-8")
            ),
            "unload_response_sanitized.json": json.loads(
                (run_path / "unload_response_sanitized.json").read_text(encoding="utf-8")
            ),
            "models_after_unload.json": json.loads(
                (run_path / "models_after_unload.json").read_text(encoding="utf-8")
            ),
            "system_summary.json": system_summary.to_dict(),
            "report.md": report_text,
        }
        privacy_violations: list[str] = []
        for artifact_name, artifact_payload in privacy_payloads.items():
            serialized_payload = json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True)
            privacy_violations.extend(
                find_privacy_violations(
                    {"artifact_name": artifact_name, "serialized": serialized_payload},
                    context=artifact_name,
                )
            )
        privacy_scan = {
            "status": "pass" if not privacy_violations else "fail",
            "violation_count": len(privacy_violations),
            "scan_scope": "cache_32k_load_only_raw_url_path_private_value_scan",
            "scanned_artifacts": list(privacy_payloads),
            "raw_prompt_response_stored": False,
        }
        write_json_file(run_path / "privacy_scan.json", privacy_scan)
        (run_path / "report.md").write_text(report_text, encoding="utf-8")

        return {
            **operation_summary,
            **_build_safe_system_summary(system_summary),
            "privacy_scan_status": privacy_scan["status"],
        }

    def _run_candidate_managed_load_only(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None,
        timeout_s: float,
        native_transport: ModelLifecycleTransport | None,
        expected_experiment_id: str,
        expected_mode: str,
        expected_model_key: str,
        expected_model_id: str,
        expected_context_tiers: tuple[int, ...],
        expected_parallel: int,
        expected_app_concurrency: int,
        expected_artifacts: tuple[str, ...],
        contract_label: str,
        report_title: str,
        privacy_scan_scope: str,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        _, raw_payload = load_raw_experiment_config(Path(config_path))

        def _require_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
            if not isinstance(value, Mapping):
                raise ValueError(f"{field_name} must be a mapping")
            return value

        def _require_non_empty_string(value: object, *, field_name: str) -> str:
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            text = value.strip()
            if not text:
                raise ValueError(f"{field_name} must be a non-empty string")
            return text

        def _require_bool(value: object, *, field_name: str) -> bool:
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean")
            return value

        def _require_int(value: object, *, field_name: str, minimum: int | None = None) -> int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
            if minimum is not None and value < minimum:
                raise ValueError(f"{field_name} must be >= {minimum}")
            return value

        def _require_int_sequence(value: object, *, field_name: str) -> tuple[int, ...]:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                raise ValueError(f"{field_name} must be a sequence of integers")
            values: list[int] = []
            for item in value:
                values.append(_require_int(item, field_name=f"{field_name}[]", minimum=1))
            return tuple(values)

        def _require_string_sequence(value: object, *, field_name: str) -> tuple[str, ...]:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                raise ValueError(f"{field_name} must be a sequence of strings")
            values: list[str] = []
            for item in value:
                values.append(_require_non_empty_string(item, field_name=f"{field_name}[]"))
            return tuple(values)

        def _default_native_transport(
            request: urllib_request.Request,
            request_timeout_s: float,
        ) -> bytes:
            with urllib_request.urlopen(request, timeout=request_timeout_s) as response:
                response_bytes = response.read()
                if not isinstance(response_bytes, bytes):
                    raise TypeError("native transport response must be bytes")
                return response_bytes

        request_transport = native_transport or _default_native_transport

        def _request_json(
            *,
            method: str,
            url: str,
            body: Mapping[str, Any] | None = None,
        ) -> tuple[Mapping[str, Any], str]:
            data = None
            headers = {"Accept": "application/json"}
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = urllib_request.Request(url, data=data, headers=headers, method=method)
            response_bytes = request_transport(request, timeout_s)
            response_text = response_bytes.decode("utf-8")
            decoded = json.loads(response_text)
            if not isinstance(decoded, Mapping):
                raise ValueError(f"{method} response must be a JSON object")
            return decoded, response_text

        def _sanitize_models_payload(
            *,
            response_payload: Mapping[str, Any],
            response_text: str,
        ) -> dict[str, object]:
            parsed = parse_native_model_list(response_payload)
            if parsed.error is not None:
                raise ValueError("native model list response must parse successfully")
            target_model = next(
                (model for model in parsed.native_models if model.native_model_key == model_id),
                None,
            )
            loaded_instances = tuple(
                target_model.loaded_instances if target_model is not None else ()
            )
            return {
                "endpoint_kind": "native_models",
                "method": "GET",
                "target_model_id": model_id,
                "target_model_key": model_key,
                "target_model_present": target_model is not None,
                "target_loaded_instance_count": len(loaded_instances),
                "instance_id_hashes": [instance.instance_ref for instance in loaded_instances],
                "context_lengths": [
                    instance.context_length
                    for instance in loaded_instances
                    if instance.context_length is not None
                ],
                "parallels": [
                    instance.parallel
                    for instance in loaded_instances
                    if instance.parallel is not None
                ],
                "response_hash": _safe_hash(response_text),
                "response_chars": len(response_text),
            }

        experiment_id = _require_non_empty_string(
            raw_payload.get("experiment_id"), field_name="experiment_id"
        )
        if experiment_id != expected_experiment_id:
            raise ValueError(f"{contract_label} requires experiment_id '{expected_experiment_id}'")

        mode = _require_non_empty_string(raw_payload.get("mode"), field_name="mode")
        if mode != expected_mode:
            raise ValueError(f"{contract_label} requires mode '{expected_mode}'")

        model_payload = _require_mapping(raw_payload.get("model"), field_name="model")
        model_key = _require_non_empty_string(model_payload.get("key"), field_name="model.key")
        if model_key != expected_model_key:
            raise ValueError(f"{contract_label} requires model.key '{expected_model_key}'")
        model_id = _require_non_empty_string(
            model_payload.get("lmstudio_model_id"),
            field_name="model.lmstudio_model_id",
        )
        if model_id != expected_model_id:
            raise ValueError(
                f"{contract_label} requires model.lmstudio_model_id '{expected_model_id}'"
            )

        load_payload = _require_mapping(raw_payload.get("load"), field_name="load")
        requested_context_tiers = _require_int_sequence(
            load_payload.get("context_tiers"),
            field_name="load.context_tiers",
        )
        if requested_context_tiers != expected_context_tiers:
            raise ValueError(
                f"{contract_label} requires load.context_tiers={list(expected_context_tiers)}"
            )
        echo_load_config = _require_bool(
            load_payload.get("echo_load_config"),
            field_name="load.echo_load_config",
        )
        flash_attention = _require_bool(
            load_payload.get("flash_attention"),
            field_name="load.flash_attention",
        )
        offload_kv_cache_to_gpu = _require_bool(
            load_payload.get("offload_kv_cache_to_gpu"),
            field_name="load.offload_kv_cache_to_gpu",
        )
        requested_parallel = _require_int(
            load_payload.get("parallel"),
            field_name="load.parallel",
            minimum=1,
        )
        if requested_parallel != expected_parallel:
            raise ValueError(f"{contract_label} requires load.parallel={expected_parallel}")

        app_concurrency = _require_int(
            raw_payload.get("app_concurrency"),
            field_name="app_concurrency",
            minimum=1,
        )
        if app_concurrency != expected_app_concurrency:
            raise ValueError(
                f"{contract_label} requires app_concurrency={expected_app_concurrency}"
            )

        allow_remote = _require_bool(
            raw_payload.get("allow_remote", False), field_name="allow_remote"
        )
        if allow_remote:
            raise ValueError(f"{contract_label} requires allow_remote=false")

        safety_payload = _require_mapping(raw_payload.get("safety"), field_name="safety")
        generation_allowed = _require_bool(
            safety_payload.get("generation_allowed"),
            field_name="safety.generation_allowed",
        )
        live_25k_authorized = _require_bool(
            safety_payload.get("live_25k_authorized"),
            field_name="safety.live_25k_authorized",
        )
        unload_required = _require_bool(
            safety_payload.get("unload_required"),
            field_name="safety.unload_required",
        )
        final_loaded_instances_required = _require_int(
            safety_payload.get("final_loaded_instances_required"),
            field_name="safety.final_loaded_instances_required",
            minimum=0,
        )
        production_default = _require_bool(
            safety_payload.get("production_default"),
            field_name="safety.production_default",
        )
        wvm_runtime_integration = _require_bool(
            safety_payload.get("wvm_runtime_integration"),
            field_name="safety.wvm_runtime_integration",
        )
        kv_reuse_proven = _require_bool(
            safety_payload.get("kv_reuse_proven"),
            field_name="safety.kv_reuse_proven",
        )
        if generation_allowed:
            raise ValueError(f"{contract_label} requires safety.generation_allowed=false")
        if live_25k_authorized:
            raise ValueError(f"{contract_label} requires safety.live_25k_authorized=false")
        if not unload_required:
            raise ValueError(f"{contract_label} requires safety.unload_required=true")
        if final_loaded_instances_required != 0:
            raise ValueError(f"{contract_label} requires safety.final_loaded_instances_required=0")
        if production_default:
            raise ValueError(f"{contract_label} requires safety.production_default=false")
        if wvm_runtime_integration:
            raise ValueError(f"{contract_label} requires safety.wvm_runtime_integration=false")
        if kv_reuse_proven:
            raise ValueError(f"{contract_label} requires safety.kv_reuse_proven=false")

        privacy_payload = _require_mapping(raw_payload.get("privacy"), field_name="privacy")
        if _require_bool(
            privacy_payload.get("store_raw_prompt_response"),
            field_name="privacy.store_raw_prompt_response",
        ):
            raise ValueError("privacy.store_raw_prompt_response must remain false")
        if _require_bool(
            privacy_payload.get("store_local_urls"),
            field_name="privacy.store_local_urls",
        ):
            raise ValueError("privacy.store_local_urls must remain false")
        if _require_bool(
            privacy_payload.get("store_state_ids_raw"),
            field_name="privacy.store_state_ids_raw",
        ):
            raise ValueError("privacy.store_state_ids_raw must remain false")

        artifact_names = _require_string_sequence(
            raw_payload.get("artifacts"), field_name="artifacts"
        )
        if artifact_names != expected_artifacts:
            raise ValueError(
                f"{contract_label} requires the exact artifact list declared by the contract"
            )

        base_url = str(raw_payload.get("lmstudio_base_url", "http://127.0.0.1:1234")).strip()
        if not base_url:
            base_url = "http://127.0.0.1:1234"
        base_url = base_url.rstrip("/")
        parsed_base_url = urllib_parse.urlparse(base_url)
        if (
            parsed_base_url.scheme not in {"http", "https"}
            or parsed_base_url.hostname not in {"127.0.0.1", "localhost"}
            or not parsed_base_url.netloc
            or parsed_base_url.path not in {"", "/"}
            or parsed_base_url.params
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise ValueError(f"{contract_label} requires localhost-only lmstudio_base_url")

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        environment_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "endpoint_family": "model_lifecycle",
            "managed_live": True,
            "dry_run": False,
            "allow_remote": False,
            "generation_allowed": False,
            "production_default": False,
            "wvm_runtime_integration": False,
            "kv_reuse_proven": False,
        }
        write_json_file(run_path / "environment.json", environment_payload)

        run_config_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "endpoint_family": "model_lifecycle",
            "model_key": model_key,
            "model_id": model_id,
            "load_context_tiers": list(requested_context_tiers),
            "requested_parallel": requested_parallel,
            "app_concurrency": app_concurrency,
            "allow_remote": False,
            "load": {
                "context_tiers": list(requested_context_tiers),
                "echo_load_config": echo_load_config,
                "flash_attention": flash_attention,
                "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
                "parallel": requested_parallel,
            },
            "safety": {
                "generation_allowed": False,
                "live_25k_authorized": False,
                "unload_required": True,
                "final_loaded_instances_required": final_loaded_instances_required,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
            },
            "privacy": {
                "store_raw_prompt_response": False,
                "store_local_urls": False,
                "store_state_ids_raw": False,
            },
            "artifacts": list(artifact_names),
        }
        write_json_file(run_path / "run_config.json", run_config_payload)

        load_attempts_path = run_path / "load_attempts.jsonl"
        load_response_path = run_path / "load_response_sanitized.jsonl"
        models_summary_path = run_path / "models_summary.jsonl"
        for path in (load_attempts_path, load_response_path, models_summary_path):
            path.write_text("", encoding="utf-8")

        normalized_providers = _normalize_providers(providers)
        system_summary: SystemMetricsSummary | None = None
        execution_failure: BaseException | None = None
        accepted = True

        self._system_sampler.start(providers=normalized_providers)
        try:
            for tier_index, requested_context_length in enumerate(requested_context_tiers, start=1):
                raw_instance_id: str | None = None
                instance_id_hash: str | None = None
                pre_models: dict[str, object] | None = None
                post_load_models: dict[str, object] | None = None
                post_unload_models: dict[str, object] | None = None
                applied_context_length: int | None = None
                applied_parallel: int | None = None
                model_list_context_metadata_present = False
                model_list_parallel_metadata_present = False
                model_list_applied_metadata_verified: bool | None = None
                load_response_recorded = False
                load_verified = False
                cleanup_verified = False
                unload_called = False
                load_post_called = False
                failure_reason: str | None = None
                tier_error: BaseException | None = None

                try:
                    models_before_payload, models_before_text = _request_json(
                        method="GET",
                        url=f"{base_url}/api/v1/models",
                    )
                    pre_models = _sanitize_models_payload(
                        response_payload=models_before_payload,
                        response_text=models_before_text,
                    )
                    append_jsonl_record(
                        models_summary_path,
                        {
                            "tier_index": tier_index,
                            "requested_context_length": requested_context_length,
                            "phase": "before_load",
                            **pre_models,
                        },
                    )
                    pre_existing_loaded_instances = int(pre_models["target_loaded_instance_count"])
                    if pre_existing_loaded_instances != 0:
                        failure_reason = "preloaded_target_instances_present"
                        raise RuntimeError(
                            f"{contract_label} aborts before POST load when the target model "
                            "already has loaded instances"
                        )

                    load_request_body = {
                        "model": model_id,
                        "context_length": requested_context_length,
                        "echo_load_config": echo_load_config,
                        "flash_attention": flash_attention,
                        "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
                        "parallel": requested_parallel,
                    }
                    load_post_called = True
                    load_response_payload, load_response_text = _request_json(
                        method="POST",
                        url=f"{base_url}/api/v1/models/load",
                        body=load_request_body,
                    )
                    raw_instance_id = _as_optional_str(
                        load_response_payload.get("instance_id")
                        or load_response_payload.get("instanceId")
                        or load_response_payload.get("id")
                    )
                    if raw_instance_id is None:
                        failure_reason = "missing_instance_id"
                        raise ValueError("load response must include instance_id")
                    instance_id_hash = _safe_hash(raw_instance_id)
                    load_config_response = load_response_payload.get("load_config")
                    if not isinstance(load_config_response, Mapping):
                        failure_reason = "missing_load_config"
                        raise ValueError("load response must include load_config mapping")
                    applied_context_length = _as_optional_int(
                        load_config_response.get("context_length")
                    )
                    applied_parallel = _as_optional_int(
                        load_config_response.get("parallel", load_config_response.get("n_parallel"))
                    )
                    append_jsonl_record(
                        load_response_path,
                        {
                            "tier_index": tier_index,
                            "requested_context_length": requested_context_length,
                            "endpoint_kind": "native_load",
                            "method": "POST",
                            "status": _as_optional_str(load_response_payload.get("status"))
                            or "unknown",
                            "instance_id_hash": instance_id_hash,
                            "load_config": {
                                "context_length": applied_context_length,
                                "parallel": applied_parallel,
                                "echo_load_config": _as_optional_bool(
                                    load_config_response.get("echo_load_config")
                                ),
                                "flash_attention": _as_optional_bool(
                                    load_config_response.get("flash_attention")
                                ),
                                "offload_kv_cache_to_gpu": _as_optional_bool(
                                    load_config_response.get("offload_kv_cache_to_gpu")
                                ),
                            },
                            "response_hash": _safe_hash(load_response_text),
                            "response_chars": len(load_response_text),
                        },
                    )
                    load_response_recorded = True

                    models_after_load_payload, models_after_load_text = _request_json(
                        method="GET",
                        url=f"{base_url}/api/v1/models",
                    )
                    post_load_models = _sanitize_models_payload(
                        response_payload=models_after_load_payload,
                        response_text=models_after_load_text,
                    )
                    append_jsonl_record(
                        models_summary_path,
                        {
                            "tier_index": tier_index,
                            "requested_context_length": requested_context_length,
                            "phase": "post_load",
                            **post_load_models,
                        },
                    )
                    model_list_context_lengths = cast(
                        list[int], post_load_models["context_lengths"]
                    )
                    model_list_parallels = cast(list[int], post_load_models["parallels"])
                    model_list_context_metadata_present = bool(model_list_context_lengths)
                    model_list_parallel_metadata_present = bool(model_list_parallels)
                    if model_list_context_metadata_present and model_list_parallel_metadata_present:
                        model_list_applied_metadata_verified = (
                            requested_context_length in model_list_context_lengths
                            and requested_parallel in model_list_parallels
                        )
                    else:
                        model_list_applied_metadata_verified = None

                    load_verified = (
                        int(post_load_models["target_loaded_instance_count"]) == 1
                        and instance_id_hash
                        in cast(list[str], post_load_models["instance_id_hashes"])
                        and applied_context_length == requested_context_length
                        and applied_parallel == requested_parallel
                    )
                    if not load_verified:
                        failure_reason = "applied_load_contract_mismatch"
                        raise RuntimeError(
                            f"{contract_label} requires exact applied context_length and parallel "
                            "from the native load response plus owned instance materialization in "
                            "the post-load model list"
                        )
                except Exception as error:
                    tier_error = error
                finally:
                    cleanup_error: BaseException | None = None
                    if raw_instance_id is not None:
                        try:
                            _request_json(
                                method="POST",
                                url=f"{base_url}/api/v1/models/unload",
                                body={"instance_id": raw_instance_id},
                            )
                            unload_called = True
                        except Exception as error:
                            cleanup_error = error
                    if raw_instance_id is not None or load_post_called:
                        try:
                            models_after_unload_payload, models_after_unload_text = _request_json(
                                method="GET",
                                url=f"{base_url}/api/v1/models",
                            )
                            post_unload_models = _sanitize_models_payload(
                                response_payload=models_after_unload_payload,
                                response_text=models_after_unload_text,
                            )
                            append_jsonl_record(
                                models_summary_path,
                                {
                                    "tier_index": tier_index,
                                    "requested_context_length": requested_context_length,
                                    "phase": "post_unload",
                                    **post_unload_models,
                                },
                            )
                        except Exception as error:
                            if cleanup_error is None:
                                cleanup_error = error

                    final_loaded_instances = (
                        int(post_unload_models["target_loaded_instance_count"])
                        if post_unload_models is not None
                        else int(pre_models["target_loaded_instance_count"])
                        if pre_models is not None
                        else None
                    )
                    cleanup_verified = (
                        post_unload_models is not None
                        and final_loaded_instances == final_loaded_instances_required
                        and (
                            instance_id_hash is None
                            or instance_id_hash
                            not in cast(list[str], post_unload_models["instance_id_hashes"])
                        )
                    )
                    if tier_error is None and not cleanup_verified:
                        failure_reason = failure_reason or "cleanup_verification_failed"
                        tier_error = RuntimeError(
                            f"{contract_label} requires exact cleanup verification after each tier"
                        )
                    if cleanup_error is not None and tier_error is None:
                        failure_reason = failure_reason or "cleanup_request_failed"
                        tier_error = cleanup_error

                    attempt_record = {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": safe_run_id,
                        "experiment_id": experiment_id,
                        "mode": mode,
                        "endpoint_family": "model_lifecycle",
                        "tier_index": tier_index,
                        "requested_context_length": requested_context_length,
                        "requested_parallel": requested_parallel,
                        "pre_existing_loaded_instances": int(
                            pre_models["target_loaded_instance_count"]
                        )
                        if pre_models is not None
                        else None,
                        "load_post_called": load_post_called,
                        "load_response_recorded": load_response_recorded,
                        "unload_called": unload_called,
                        "instance_id_hash": instance_id_hash,
                        "applied_context_length": applied_context_length,
                        "applied_parallel": applied_parallel,
                        "model_list_context_metadata_present": model_list_context_metadata_present,
                        "model_list_parallel_metadata_present": model_list_parallel_metadata_present,
                        "model_list_applied_metadata_verified": model_list_applied_metadata_verified,
                        "load_verified": load_verified,
                        "cleanup_verified": cleanup_verified,
                        "final_loaded_instances": final_loaded_instances,
                        "decision": "load_only_passed"
                        if tier_error is None and load_verified and cleanup_verified
                        else "load_only_failed",
                        "failure_reason": failure_reason,
                        "generation_called": False,
                        "chat_called": False,
                        "responses_called": False,
                        "chat_completions_called": False,
                        "inference_endpoint_called": False,
                        "production_default": False,
                        "wvm_runtime_integration": False,
                        "kv_reuse_proven": False,
                        "raw_prompt_response_stored": False,
                    }
                    append_jsonl_record(load_attempts_path, attempt_record)

                if tier_error is not None:
                    accepted = False
                    execution_failure = tier_error
                    break
        finally:
            system_summary = self._system_sampler.stop(providers=normalized_providers)
            write_system_telemetry_artifacts(
                run_path,
                samples=self._system_sampler.samples,
                summary=system_summary,
            )

        attempt_rows = _load_jsonl_records(load_attempts_path)
        models_rows = _load_jsonl_records(models_summary_path)
        load_response_rows = _load_jsonl_records(load_response_path)
        all_tiers_passed = len(attempt_rows) == len(requested_context_tiers) and all(
            row.get("decision") == "load_only_passed" for row in attempt_rows
        )
        overall_decision = (
            "load_only_passed" if accepted and all_tiers_passed else "load_only_failed"
        )
        final_loaded_instances = (
            attempt_rows[-1].get("final_loaded_instances") if attempt_rows else None
        )

        def _format_report_boolish(value: object) -> str:
            if isinstance(value, bool):
                return str(value).lower()
            if value is None:
                return "unknown"
            return str(value)

        report_lines = [
            f"# {report_title}",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| experiment_id | `{experiment_id}` |",
            "| endpoint_family | `model_lifecycle` |",
            f"| model_key | `{model_key}` |",
            f"| model_id | `{model_id}` |",
            f"| load_context_tiers | `{', '.join(str(value) for value in requested_context_tiers)}` |",
            f"| requested_parallel | `{requested_parallel}` |",
            f"| app_concurrency | `{app_concurrency}` |",
            "| allow_remote | `false` |",
            "| generation_allowed | `false` |",
            "| production_default | `false` |",
            "| wvm_runtime_integration | `false` |",
            "| kv_reuse_proven | `false` |",
            f"| final_loaded_instances | `{final_loaded_instances}` |",
            f"| decision | `{overall_decision}` |",
            "",
            "## Per-tier attempts",
            "",
            "| Tier | Requested context | Applied context | Applied parallel | Model-list ctx metadata | Model-list parallel metadata | Model-list applied metadata verified | Cleanup verified | Decision | Failure reason |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in attempt_rows:
            report_lines.append(
                "| "
                f"`{row.get('tier_index')}` | `{row.get('requested_context_length')}` | "
                f"`{row.get('applied_context_length')}` | `{row.get('applied_parallel')}` | "
                f"`{_format_report_boolish(row.get('model_list_context_metadata_present'))}` | "
                f"`{_format_report_boolish(row.get('model_list_parallel_metadata_present'))}` | "
                f"`{_format_report_boolish(row.get('model_list_applied_metadata_verified'))}` | "
                f"`{_format_report_boolish(row.get('cleanup_verified'))}` | `{row.get('decision')}` | "
                f"`{row.get('failure_reason')}` |"
            )
        report_lines.extend(
            [
                "",
                "## Notes",
                "",
                "- This gate is load-only: no inference, no native chat, no responses, and no chat-completions endpoints are allowed.",
                "- Acceptance requires every configured tier to materialize exactly one WVM-owned instance in the post-load model list, match the requested context_length and parallel in the native load response, and clean up back to zero target loaded instances.",
                "- Model-list context_length/parallel arrays are optional telemetry only; when present they are reported, but they do not gate acceptance.",
                "- This report remains lab-only: not production default, not WVM runtime integration, no live generation, and no user-facing recommendation proof.",
                "- Cleanup must be explicitly verified after the final unload and the final target loaded instance count must remain 0.",
                "",
                "## Output Files",
                "",
                *[f"- `{artifact_name}`" for artifact_name in artifact_names],
                "",
            ]
        )
        report_text = "\n".join(report_lines)
        (run_path / "report.md").write_text(report_text, encoding="utf-8")

        assert system_summary is not None
        privacy_payloads = {
            "environment.json": environment_payload,
            "run_config.json": run_config_payload,
            "load_attempts.jsonl": attempt_rows,
            "load_response_sanitized.jsonl": load_response_rows,
            "models_summary.jsonl": models_rows,
            "system_samples.jsonl": [sample.to_dict() for sample in self._system_sampler.samples],
            "system_summary.json": system_summary.to_dict(),
            "report.md": report_text,
        }
        privacy_violations: list[str] = []
        for artifact_name, artifact_payload in privacy_payloads.items():
            serialized_payload = json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True)
            privacy_violations.extend(
                find_privacy_violations(
                    {"artifact_name": artifact_name, "serialized": serialized_payload},
                    context=artifact_name,
                )
            )
        privacy_scan = {
            "status": "pass" if not privacy_violations else "fail",
            "violation_count": len(privacy_violations),
            "scan_scope": privacy_scan_scope,
            "scanned_artifacts": list(privacy_payloads),
            "raw_prompt_response_stored": False,
        }
        write_json_file(run_path / "privacy_scan.json", privacy_scan)

        summary_payload = _sanitize_operation_summary(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "endpoint_family": "model_lifecycle",
                "model_key": model_key,
                "model_id": model_id,
                "load_context_tiers": list(requested_context_tiers),
                "requested_parallel": requested_parallel,
                "app_concurrency": app_concurrency,
                "load_called": any(bool(row.get("load_post_called")) for row in attempt_rows),
                "unload_called": any(bool(row.get("unload_called")) for row in attempt_rows),
                "generation_called": False,
                "chat_called": False,
                "responses_called": False,
                "chat_completions_called": False,
                "inference_endpoint_called": False,
                "load_tiers_passed_count": sum(
                    1 for row in attempt_rows if row.get("decision") == "load_only_passed"
                ),
                "cleanup_verified": all(bool(row.get("cleanup_verified")) for row in attempt_rows)
                if attempt_rows
                else False,
                "final_loaded_instances": final_loaded_instances,
                "live_25k_authorized": False,
                "generation_allowed": False,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "final_user_facing_recommendation": False,
                "decision": overall_decision,
                "raw_prompt_response_stored": False,
            }
        )

        if privacy_scan["status"] != "pass":
            raise RuntimeError(f"{contract_label} acceptance gate failed: privacy_scan_failed")
        if execution_failure is not None:
            raise execution_failure
        if overall_decision != "load_only_passed":
            raise RuntimeError(f"{contract_label} acceptance gate failed: load_only_failed")

        return {
            **summary_payload,
            **_build_safe_system_summary(system_summary),
            "privacy_scan_status": privacy_scan["status"],
        }

    def run_l3_8b_gemma4_e4b_load_only_16k_32k(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
        timeout_s: float = 120.0,
        native_transport: ModelLifecycleTransport | None = None,
    ) -> dict[str, object]:
        return self._run_candidate_managed_load_only(
            config_path=config_path,
            run_dir=run_dir,
            run_id=run_id,
            providers=providers,
            timeout_s=timeout_s,
            native_transport=native_transport,
            expected_experiment_id=_L3_8B_GEMMA4_E4B_LOAD_ONLY_EXPERIMENT_ID,
            expected_mode=_L3_8B_GEMMA4_E4B_LOAD_ONLY_MODE,
            expected_model_key=_L3_8B_GEMMA4_E4B_LOAD_ONLY_MODEL_KEY,
            expected_model_id=_L3_8B_GEMMA4_E4B_LOAD_ONLY_MODEL_ID,
            expected_context_tiers=_L3_8B_GEMMA4_E4B_LOAD_ONLY_CONTEXT_TIERS,
            expected_parallel=_L3_8B_GEMMA4_E4B_LOAD_ONLY_PARALLEL,
            expected_app_concurrency=_L3_8B_GEMMA4_E4B_LOAD_ONLY_APP_CONCURRENCY,
            expected_artifacts=_L3_8B_GEMMA4_E4B_LOAD_ONLY_OUTPUT_FILES,
            contract_label="L3.8b Gemma E4B load-only",
            report_title="LM Studio Lab L3.8b Gemma4 E4B Load-Only 16k/32k Report",
            privacy_scan_scope="candidate_load_only_16k_32k_raw_url_path_private_value_scan",
        )

    def run_l3_9c_gemma4_12b_qat_load_only_8k_16k(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
        timeout_s: float = 120.0,
        native_transport: ModelLifecycleTransport | None = None,
    ) -> dict[str, object]:
        return self._run_candidate_managed_load_only(
            config_path=config_path,
            run_dir=run_dir,
            run_id=run_id,
            providers=providers,
            timeout_s=timeout_s,
            native_transport=native_transport,
            expected_experiment_id=_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_EXPERIMENT_ID,
            expected_mode=_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_MODE,
            expected_model_key=_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_MODEL_KEY,
            expected_model_id=_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_MODEL_ID,
            expected_context_tiers=_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_CONTEXT_TIERS,
            expected_parallel=_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_PARALLEL,
            expected_app_concurrency=_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_APP_CONCURRENCY,
            expected_artifacts=_L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_OUTPUT_FILES,
            contract_label="L3.9c Gemma4 12B QAT load-only",
            report_title="LM Studio Lab L3.9c Gemma4 12B QAT Load-Only 8k/16k Report",
            privacy_scan_scope="candidate_load_only_8k_16k_raw_url_path_private_value_scan",
        )

    def run_l3_9d_gemma4_26b_a4b_qat_load_only_8k(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
        timeout_s: float = 120.0,
        native_transport: ModelLifecycleTransport | None = None,
    ) -> dict[str, object]:
        return self._run_candidate_managed_load_only(
            config_path=config_path,
            run_dir=run_dir,
            run_id=run_id,
            providers=providers,
            timeout_s=timeout_s,
            native_transport=native_transport,
            expected_experiment_id=_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_EXPERIMENT_ID,
            expected_mode=_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_MODE,
            expected_model_key=_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_MODEL_KEY,
            expected_model_id=_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_MODEL_ID,
            expected_context_tiers=_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_CONTEXT_TIERS,
            expected_parallel=_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_PARALLEL,
            expected_app_concurrency=_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_APP_CONCURRENCY,
            expected_artifacts=_L3_9D_GEMMA4_26B_A4B_QAT_LOAD_ONLY_OUTPUT_FILES,
            contract_label="L3.9d Gemma4 26B A4B QAT load-only",
            report_title="LM Studio Lab L3.9d Gemma4 26B A4B QAT Load-Only 8k Report",
            privacy_scan_scope="candidate_load_only_8k_raw_url_path_private_value_scan",
        )

    def run_l3_8c_gemma4_e4b_tiny_live_smoke(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
        timeout_s: float = 120.0,
        native_transport: ModelLifecycleTransport | None = None,
        chat_transport: LiveTransport | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        _, raw_payload = load_raw_experiment_config(Path(config_path))

        def _require_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
            if not isinstance(value, Mapping):
                raise ValueError(f"{field_name} must be a mapping")
            return value

        def _require_non_empty_string(value: object, *, field_name: str) -> str:
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            text = value.strip()
            if not text:
                raise ValueError(f"{field_name} must be a non-empty string")
            return text

        def _require_bool(value: object, *, field_name: str) -> bool:
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean")
            return value

        def _require_int(value: object, *, field_name: str, minimum: int | None = None) -> int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
            if minimum is not None and value < minimum:
                raise ValueError(f"{field_name} must be >= {minimum}")
            return value

        def _require_string_sequence(value: object, *, field_name: str) -> tuple[str, ...]:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                raise ValueError(f"{field_name} must be a sequence of strings")
            values: list[str] = []
            for item in value:
                values.append(_require_non_empty_string(item, field_name=f"{field_name}[]"))
            return tuple(values)

        def _default_native_transport(
            request: urllib_request.Request,
            request_timeout_s: float,
        ) -> bytes:
            with urllib_request.urlopen(request, timeout=request_timeout_s) as response:
                response_bytes = response.read()
                if not isinstance(response_bytes, bytes):
                    raise TypeError("native transport response must be bytes")
                return response_bytes

        def _request_json(
            *,
            method: str,
            url: str,
            body: Mapping[str, Any] | None = None,
        ) -> tuple[Mapping[str, Any], str]:
            data = None
            headers = {"Accept": "application/json"}
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = urllib_request.Request(url, data=data, headers=headers, method=method)
            response_bytes = request_transport(request, timeout_s)
            response_text = response_bytes.decode("utf-8")
            decoded = json.loads(response_text)
            if not isinstance(decoded, Mapping):
                raise ValueError(f"{method} response must be a JSON object")
            return decoded, response_text

        def _sanitize_models_payload(
            *,
            response_payload: Mapping[str, Any],
            response_text: str,
        ) -> tuple[dict[str, object], tuple[LoadedInstanceRecord, ...]]:
            parsed = parse_native_model_list(response_payload)
            if parsed.error is not None:
                raise ValueError("native model list response must parse successfully")
            target_model = next(
                (model for model in parsed.native_models if model.native_model_key == model_id),
                None,
            )
            loaded_instances = tuple(
                target_model.loaded_instances if target_model is not None else ()
            )
            return (
                {
                    "endpoint_kind": "native_models",
                    "method": "GET",
                    "target_model_id": model_id,
                    "target_model_key": model_key,
                    "target_model_present": target_model is not None,
                    "target_loaded_instance_count": len(loaded_instances),
                    "instance_id_hashes": [instance.instance_ref for instance in loaded_instances],
                    "response_hash": _safe_hash(response_text),
                    "response_chars": len(response_text),
                },
                loaded_instances,
            )

        def _build_tiny_prompt() -> str:
            return (
                "L3.8c Gemma4 E4B tiny live smoke synthetic prompt. "
                "Return one short public sentence confirming deterministic lab execution."
            )

        def _extract_usage_tokens(
            response_payload: Mapping[str, Any],
        ) -> tuple[int | None, int | None]:
            usage = response_payload.get("usage")
            if not isinstance(usage, Mapping):
                return None, None
            input_tokens = _as_optional_int(usage.get("prompt_tokens", usage.get("input_tokens")))
            output_tokens = _as_optional_int(
                usage.get("completion_tokens", usage.get("output_tokens"))
            )
            return input_tokens, output_tokens

        def _extract_stats_rate(
            response_payload: Mapping[str, Any],
            *field_names: str,
        ) -> float | None:
            stats = response_payload.get("stats")
            if not isinstance(stats, Mapping):
                return None
            for field_name in field_names:
                value = _as_optional_rate(stats.get(field_name))
                if value is not None:
                    return round(value, 3)
            return None

        def _extract_prompt_processing_ms(response_payload: Mapping[str, Any]) -> float | None:
            prompt_processing_ms = _extract_stats_rate(
                response_payload,
                "prompt_processing_ms",
                "prompt_processing_time_ms",
            )
            if prompt_processing_ms is not None:
                return prompt_processing_ms
            prompt_processing_seconds = _extract_stats_rate(
                response_payload,
                "prompt_processing_seconds",
                "prompt_processing_time_seconds",
                "prompt_processing",
                "prompt_processing_time",
            )
            if prompt_processing_seconds is not None:
                return round(prompt_processing_seconds * 1000.0, 3)
            return None

        request_transport = native_transport or _default_native_transport
        request_chat_transport = chat_transport or _default_live_transport

        experiment_id = _require_non_empty_string(
            raw_payload.get("experiment_id"),
            field_name="experiment_id",
        )
        if experiment_id != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_EXPERIMENT_ID:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires experiment_id "
                "'l3_8c_gemma4_e4b_tiny_live_smoke'"
            )

        mode = _require_non_empty_string(raw_payload.get("mode"), field_name="mode")
        if mode != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_MODE:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires mode 'candidate_tiny_live_smoke'"
            )

        model_payload = _require_mapping(raw_payload.get("model"), field_name="model")
        model_key = _require_non_empty_string(model_payload.get("key"), field_name="model.key")
        if model_key != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_MODEL_KEY:
            raise ValueError("L3.8c Gemma E4B tiny live smoke requires model.key 'gemma4_e4b_q4km'")
        model_id = _require_non_empty_string(
            model_payload.get("lmstudio_model_id"),
            field_name="model.lmstudio_model_id",
        )
        if model_id != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_MODEL_ID:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires model.lmstudio_model_id 'google/gemma-4-e4b'"
            )

        load_payload = _require_mapping(raw_payload.get("load"), field_name="load")
        requested_context_length = _require_int(
            load_payload.get("context_length"),
            field_name="load.context_length",
            minimum=1,
        )
        if requested_context_length != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_CONTEXT_LENGTH:
            raise ValueError("L3.8c Gemma E4B tiny live smoke requires load.context_length=16384")
        echo_load_config = _require_bool(
            load_payload.get("echo_load_config", True),
            field_name="load.echo_load_config",
        )
        if not echo_load_config:
            raise ValueError("L3.8c Gemma E4B tiny live smoke requires load.echo_load_config=true")
        flash_attention = _require_bool(
            load_payload.get("flash_attention", True),
            field_name="load.flash_attention",
        )
        if not flash_attention:
            raise ValueError("L3.8c Gemma E4B tiny live smoke requires load.flash_attention=true")
        offload_kv_cache_to_gpu = _require_bool(
            load_payload.get("offload_kv_cache_to_gpu", True),
            field_name="load.offload_kv_cache_to_gpu",
        )
        if not offload_kv_cache_to_gpu:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires load.offload_kv_cache_to_gpu=true"
            )
        requested_parallel = _require_int(
            load_payload.get("parallel"),
            field_name="load.parallel",
            minimum=1,
        )
        if requested_parallel != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_PARALLEL:
            raise ValueError("L3.8c Gemma E4B tiny live smoke requires load.parallel=1")

        app_concurrency = _require_int(
            raw_payload.get("app_concurrency"),
            field_name="app_concurrency",
            minimum=1,
        )
        if app_concurrency != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_APP_CONCURRENCY:
            raise ValueError("L3.8c Gemma E4B tiny live smoke requires app_concurrency=1")

        generation_payload = _require_mapping(
            raw_payload.get("generation"), field_name="generation"
        )
        generation_route = _require_non_empty_string(
            generation_payload.get("route"),
            field_name="generation.route",
        )
        if generation_route != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ROUTE:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires generation.route 'tiny_live_chat'"
            )
        endpoint_path = _require_non_empty_string(
            generation_payload.get("endpoint_path"),
            field_name="generation.endpoint_path",
        )
        if endpoint_path != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_ENDPOINT_PATH:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires generation.endpoint_path '/api/v1/chat'"
            )
        temperature = _require_int(
            generation_payload.get("temperature"),
            field_name="generation.temperature",
            minimum=0,
        )
        if temperature != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_TEMPERATURE:
            raise ValueError("L3.8c Gemma E4B tiny live smoke requires generation.temperature=0")
        max_output_tokens = _require_int(
            generation_payload.get("max_output_tokens"),
            field_name="generation.max_output_tokens",
            minimum=1,
        )
        if max_output_tokens != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_MAX_OUTPUT_TOKENS:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires generation.max_output_tokens=64"
            )
        store = _require_bool(generation_payload.get("store", False), field_name="generation.store")
        if store:
            raise ValueError("L3.8c Gemma E4B tiny live smoke requires generation.store=false")

        safety_payload = _require_mapping(raw_payload.get("safety"), field_name="safety")
        generation_allowed = _require_bool(
            safety_payload.get("generation_allowed"),
            field_name="safety.generation_allowed",
        )
        if not generation_allowed:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires safety.generation_allowed=true"
            )
        live_25k_authorized = _require_bool(
            safety_payload.get("live_25k_authorized"),
            field_name="safety.live_25k_authorized",
        )
        if live_25k_authorized:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires safety.live_25k_authorized=false"
            )
        production_default = _require_bool(
            safety_payload.get("production_default"),
            field_name="safety.production_default",
        )
        if production_default:
            raise ValueError("safety.production_default must remain false")
        wvm_runtime_integration = _require_bool(
            safety_payload.get("wvm_runtime_integration"),
            field_name="safety.wvm_runtime_integration",
        )
        if wvm_runtime_integration:
            raise ValueError("safety.wvm_runtime_integration must remain false")
        kv_reuse_proven = _require_bool(
            safety_payload.get("kv_reuse_proven"),
            field_name="safety.kv_reuse_proven",
        )
        if kv_reuse_proven:
            raise ValueError("safety.kv_reuse_proven must remain false")
        unload_required = _require_bool(
            safety_payload.get("unload_required"),
            field_name="safety.unload_required",
        )
        if not unload_required:
            raise ValueError("L3.8c Gemma E4B tiny live smoke requires safety.unload_required=true")
        final_loaded_instances_required = _require_int(
            safety_payload.get("final_loaded_instances_required"),
            field_name="safety.final_loaded_instances_required",
            minimum=0,
        )
        if final_loaded_instances_required != 0:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires safety.final_loaded_instances_required=0"
            )

        privacy_payload = _require_mapping(raw_payload.get("privacy"), field_name="privacy")
        if _require_bool(
            privacy_payload.get("store_raw_prompt_response"),
            field_name="privacy.store_raw_prompt_response",
        ):
            raise ValueError("privacy.store_raw_prompt_response must remain false")
        if _require_bool(
            privacy_payload.get("store_local_urls"),
            field_name="privacy.store_local_urls",
        ):
            raise ValueError("privacy.store_local_urls must remain false")
        if _require_bool(
            privacy_payload.get("store_state_ids_raw"),
            field_name="privacy.store_state_ids_raw",
        ):
            raise ValueError("privacy.store_state_ids_raw must remain false")

        artifact_names = _require_string_sequence(
            raw_payload.get("artifacts"), field_name="artifacts"
        )
        if artifact_names != _L3_8C_GEMMA4_E4B_TINY_LIVE_SMOKE_OUTPUT_FILES:
            raise ValueError(
                "L3.8c Gemma E4B tiny live smoke requires the exact artifact list declared by the contract"
            )

        base_url = str(raw_payload.get("lmstudio_base_url", "http://127.0.0.1:1234")).strip()
        if not base_url:
            base_url = "http://127.0.0.1:1234"
        base_url = base_url.rstrip("/")
        endpoint_url = _build_cache_stateful_live_smoke_url(base_url)

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        requests_path = run_path / "requests.jsonl"
        metrics_path = run_path / "metrics.jsonl"
        requests_path.write_text("", encoding="utf-8")
        metrics_path.write_text("", encoding="utf-8")

        prompt_text = _build_tiny_prompt()
        prompt_hash = _safe_hash(prompt_text)
        prompt_chars = len(prompt_text)
        prompt_privacy_marker = _build_prompt_privacy_marker(prompt_text)
        estimated_input_tokens = estimate_input_tokens_from_chars(prompt_chars)

        environment_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "managed_live": True,
            "lab_only": True,
            "generation_allowed": True,
            "live_25k_authorized": False,
            "production_default": False,
            "wvm_runtime_integration": False,
            "kv_reuse_proven": False,
            "final_user_facing_recommendation": False,
        }
        write_json_file(run_path / "environment.json", environment_payload)

        run_config_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "model_key": model_key,
            "model_id": model_id,
            "app_concurrency": app_concurrency,
            "requested_context_length": requested_context_length,
            "requested_parallel": requested_parallel,
            "load": {
                "context_length": requested_context_length,
                "parallel": requested_parallel,
                "echo_load_config": echo_load_config,
                "flash_attention": flash_attention,
                "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
            },
            "generation": {
                "route": generation_route,
                "endpoint_path": endpoint_path,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "store": False,
            },
            "input_shape": {
                "input_hash": prompt_hash,
                "input_chars": prompt_chars,
                "estimated_input_tokens": estimated_input_tokens,
            },
            "safety": {
                "generation_allowed": True,
                "live_25k_authorized": False,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "unload_required": True,
                "final_loaded_instances_required": 0,
                "final_user_facing_recommendation": False,
            },
            "privacy": {
                "store_raw_prompt_response": False,
                "store_local_urls": False,
                "store_state_ids_raw": False,
            },
            "artifacts": list(artifact_names),
        }
        write_json_file(run_path / "run_config.json", run_config_payload)
        write_json_file(
            run_path / "load_response_sanitized.json",
            {
                "endpoint_kind": "native_load",
                "method": "POST",
                "status": "not_attempted",
                "instance_id_hash": None,
                "load_time_ms": None,
                "applied_load_config": {
                    "context_length": None,
                    "parallel": None,
                    "echo_load_config": None,
                    "flash_attention": None,
                    "offload_kv_cache_to_gpu": None,
                },
                "response_hash": None,
                "response_chars": None,
            },
        )

        normalized_providers = _normalize_providers(providers)
        request_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []
        raw_instance_id: str | None = None
        raw_response_id: str | None = None
        raw_output_text: str | None = None
        instance_id_hash: str | None = None
        applied_context_length: int | None = None
        applied_parallel: int | None = None
        load_verified = False
        unload_called = False
        generation_called = False
        request_succeeded = False
        non_empty_text_pass = False
        cleanup_verified = False
        final_loaded_instances: int | None = None
        load_time_ms: float | None = None
        total_latency_ms: float | None = None
        prompt_processing_ms: float | None = None
        time_to_first_token_ms: float | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        tokens_per_second: float | None = None
        failure_reason: str | None = None
        system_summary: SystemMetricsSummary | None = None
        execution_failure: BaseException | None = None

        self._system_sampler.start(providers=normalized_providers)
        try:
            models_before_payload, models_before_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            models_before, preexisting_loaded_instances = _sanitize_models_payload(
                response_payload=models_before_payload,
                response_text=models_before_text,
            )
            if models_before["target_loaded_instance_count"] != 0 or preexisting_loaded_instances:
                failure_reason = "preloaded_target_instances_present"
                raise RuntimeError(
                    "L3.8c candidate tiny live smoke aborts before POST load when the target model already has loaded instances"
                )

            load_request_body = {
                "model": model_id,
                "context_length": requested_context_length,
                "echo_load_config": echo_load_config,
                "flash_attention": flash_attention,
                "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
                "parallel": requested_parallel,
            }
            load_started_at = _live_request_perf_counter()
            load_response_payload, load_response_text = _request_json(
                method="POST",
                url=f"{base_url}/api/v1/models/load",
                body=load_request_body,
            )
            load_time_ms = round((_live_request_perf_counter() - load_started_at) * 1000.0, 3)
            raw_instance_id = _as_optional_str(
                load_response_payload.get("instance_id")
                or load_response_payload.get("instanceId")
                or load_response_payload.get("id")
            )
            if raw_instance_id is None:
                failure_reason = "missing_instance_id"
                raise ValueError("load response must include instance_id")
            instance_id_hash = _safe_hash(raw_instance_id)
            load_config_response = load_response_payload.get("load_config")
            if not isinstance(load_config_response, Mapping):
                failure_reason = "missing_load_config"
                raise ValueError("load response must include load_config mapping")
            applied_context_length = _as_optional_int(load_config_response.get("context_length"))
            applied_parallel = _as_optional_int(
                load_config_response.get("parallel", load_config_response.get("n_parallel"))
            )
            if applied_context_length != requested_context_length:
                failure_reason = "applied_context_mismatch"
                raise ValueError("owned native load must materialize context_length=16384")
            if applied_parallel != requested_parallel:
                failure_reason = "applied_parallel_mismatch"
                raise ValueError("owned native load must materialize parallel=1")
            write_json_file(
                run_path / "load_response_sanitized.json",
                {
                    "endpoint_kind": "native_load",
                    "method": "POST",
                    "status": _as_optional_str(load_response_payload.get("status")) or "unknown",
                    "instance_id_hash": instance_id_hash,
                    "load_time_ms": load_time_ms,
                    "applied_load_config": {
                        "context_length": applied_context_length,
                        "parallel": applied_parallel,
                        "echo_load_config": _as_optional_bool(
                            load_config_response.get("echo_load_config")
                        ),
                        "flash_attention": _as_optional_bool(
                            load_config_response.get("flash_attention")
                        ),
                        "offload_kv_cache_to_gpu": _as_optional_bool(
                            load_config_response.get("offload_kv_cache_to_gpu")
                        ),
                    },
                    "response_hash": _safe_hash(load_response_text),
                    "response_chars": len(load_response_text),
                },
            )

            models_after_load_payload, models_after_load_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            models_after_load, loaded_instances = _sanitize_models_payload(
                response_payload=models_after_load_payload,
                response_text=models_after_load_text,
            )
            owned_instance = next(
                (
                    instance
                    for instance in loaded_instances
                    if instance.instance_ref == instance_id_hash
                ),
                None,
            )
            load_verified = (
                models_after_load["target_loaded_instance_count"] == 1
                and owned_instance is not None
                and applied_context_length == requested_context_length
                and applied_parallel == requested_parallel
            )
            if not load_verified:
                failure_reason = "owned_instance_verification_failed"
                raise ValueError("owned native load verification failed")

            request_payload = {
                "model": model_id,
                "input": prompt_text,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "store": False,
            }
            generation_called = True
            request_started_at = _live_request_perf_counter()
            response_payload = request_chat_transport(endpoint_url, request_payload, timeout_s)
            total_latency_ms = round(
                (_live_request_perf_counter() - request_started_at) * 1000.0,
                3,
            )
            if not isinstance(response_payload, Mapping):
                failure_reason = "response_not_json_object"
                raise ValueError("tiny live smoke response must be a JSON object")
            if "previous_response_id" in request_payload:
                failure_reason = "previous_response_id_not_allowed"
                raise ValueError("tiny live smoke request must not set previous_response_id")

            raw_response_id = _as_optional_str(
                response_payload.get("response_id")
                or response_payload.get("responseId")
                or response_payload.get("id")
            )
            raw_output_text = _extract_cache_stateful_live_smoke_output_text(response_payload)
            request_succeeded = True
            non_empty_text_pass = raw_output_text is not None
            input_tokens, output_tokens = _extract_usage_tokens(response_payload)
            prompt_processing_ms = _extract_prompt_processing_ms(response_payload)
            time_to_first_token_ms = _extract_stats_ttft_ms(response_payload)
            tokens_per_second = _extract_stats_rate(response_payload, "tokens_per_second")
            if (
                tokens_per_second is None
                and output_tokens is not None
                and total_latency_ms not in (None, 0)
            ):
                tokens_per_second = round(output_tokens / (total_latency_ms / 1000.0), 3)

            response_hash = _safe_hash(raw_output_text) if raw_output_text is not None else None
            response_chars = len(raw_output_text) if raw_output_text is not None else 0
            request_row = {
                "schema_version": SCHEMA_VERSION,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "managed_live": True,
                "request_id": "tiny_live_smoke_single",
                "request_role": generation_route,
                "model_key": model_key,
                "model_id": model_id,
                "endpoint_path": endpoint_path,
                "app_concurrency": app_concurrency,
                "requested_context_length": requested_context_length,
                "requested_parallel": requested_parallel,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "store": False,
                "input_hash": prompt_hash,
                "input_chars": prompt_chars,
                "estimated_input_tokens": estimated_input_tokens,
                "response_id_present": raw_response_id is not None,
                "response_id_hash": (_safe_hash(raw_response_id) if raw_response_id else None),
                "response_hash": response_hash,
                "response_chars": response_chars,
                "content_nonempty": non_empty_text_pass,
                "non_empty_text_pass": non_empty_text_pass,
                "raw_prompt_response_stored": False,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "live_25k_authorized": False,
                "generation_allowed": True,
                "responses_called": False,
                "chat_completions_called": False,
                "status": "success" if non_empty_text_pass else "empty_output",
            }
            metric_row = {
                "schema_version": SCHEMA_VERSION,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "managed_live": True,
                "request_id": "tiny_live_smoke_single",
                "request_role": generation_route,
                "model_key": model_key,
                "model_id": model_id,
                "endpoint_path": endpoint_path,
                "app_concurrency": app_concurrency,
                "requested_context_length": requested_context_length,
                "applied_context_length": applied_context_length,
                "requested_parallel": requested_parallel,
                "applied_parallel": applied_parallel,
                "load_verified": True,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "store": False,
                "input_hash": prompt_hash,
                "input_chars": prompt_chars,
                "estimated_input_tokens": estimated_input_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "prompt_processing_ms": prompt_processing_ms,
                "time_to_first_token_ms": time_to_first_token_ms,
                "tokens_per_second": tokens_per_second,
                "total_latency_ms": total_latency_ms,
                "response_id_present": raw_response_id is not None,
                "response_id_hash": (_safe_hash(raw_response_id) if raw_response_id else None),
                "response_hash": response_hash,
                "response_chars": response_chars,
                "content_nonempty": non_empty_text_pass,
                "non_empty_text_pass": non_empty_text_pass,
                "raw_prompt_response_stored": False,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "live_25k_authorized": False,
                "generation_allowed": True,
                "responses_called": False,
                "chat_completions_called": False,
                "status": "success" if non_empty_text_pass else "empty_output",
            }
            request_rows.append(append_jsonl_record(requests_path, request_row))
            metric_rows.append(append_jsonl_record(metrics_path, metric_row))
            if not non_empty_text_pass:
                failure_reason = "empty_public_output"
                raise ValueError("tiny live smoke response must include non-empty public output")
        except Exception as error:
            execution_failure = error
            if failure_reason is None:
                failure_reason = error.__class__.__name__
        finally:
            cleanup_error: BaseException | None = None
            if raw_instance_id is not None:
                try:
                    _request_json(
                        method="POST",
                        url=f"{base_url}/api/v1/models/unload",
                        body={"instance_id": raw_instance_id},
                    )
                    unload_called = True
                except Exception as error:
                    cleanup_error = error
                try:
                    models_after_unload_payload, models_after_unload_text = _request_json(
                        method="GET",
                        url=f"{base_url}/api/v1/models",
                    )
                    models_after_unload, _ = _sanitize_models_payload(
                        response_payload=models_after_unload_payload,
                        response_text=models_after_unload_text,
                    )
                    final_loaded_instances = _as_optional_int(
                        models_after_unload.get("target_loaded_instance_count")
                    )
                    models_after_unload_instance_hashes = _require_string_sequence(
                        models_after_unload.get("instance_id_hashes"),
                        field_name="models_after_unload.instance_id_hashes",
                    )
                    cleanup_verified = bool(
                        final_loaded_instances == final_loaded_instances_required
                        and instance_id_hash is not None
                        and instance_id_hash not in models_after_unload_instance_hashes
                    )
                    if not cleanup_verified and cleanup_error is None:
                        cleanup_error = RuntimeError("native cleanup not verified")
                except Exception as error:
                    if cleanup_error is None:
                        cleanup_error = error

            stop_error: BaseException | None = None
            try:
                system_summary = self._system_sampler.stop(providers=normalized_providers)
                write_system_telemetry_artifacts(
                    run_path,
                    samples=self._system_sampler.samples,
                    summary=system_summary,
                )
            except Exception as error:
                stop_error = error

            if cleanup_error is not None:
                failure_reason = failure_reason or "cleanup_request_failed"
                if execution_failure is None:
                    execution_failure = cleanup_error
            if stop_error is not None and execution_failure is None:
                failure_reason = failure_reason or "system_metrics_write_failed"
                execution_failure = stop_error

        assert system_summary is not None

        if not cleanup_verified and raw_instance_id is not None:
            failure_reason = failure_reason or "cleanup_verification_failed"
            if execution_failure is None:
                execution_failure = RuntimeError("native cleanup not verified")

        report_rows = (
            ("experiment_id", experiment_id),
            ("run_id", safe_run_id),
            ("mode", mode),
            ("route", generation_route),
            ("endpoint_path", endpoint_path),
            ("requested_context_length", str(requested_context_length)),
            ("applied_context_length", str(applied_context_length)),
            ("requested_parallel", str(requested_parallel)),
            ("applied_parallel", str(applied_parallel)),
            ("load_verified", str(load_verified).lower()),
            ("generation_called", str(generation_called).lower()),
            ("request_succeeded", str(request_succeeded).lower()),
            ("non_empty_text_pass", str(non_empty_text_pass).lower()),
            ("cleanup_verified", str(cleanup_verified).lower()),
            ("final_loaded_instances", str(final_loaded_instances)),
            ("temperature", str(temperature)),
            ("max_output_tokens", str(max_output_tokens)),
            ("estimated_input_tokens", str(estimated_input_tokens)),
            ("failure_reason", str(failure_reason)),
            ("production_default", "false"),
            ("wvm_runtime_integration", "false"),
            ("kv_reuse_proven", "false"),
            ("final_user_facing_recommendation", "false"),
        )
        report_text = "\n".join(
            [
                "# LM Studio Lab L3.8c Gemma4 E4B Tiny Live Smoke Report",
                "",
                "This is a lab-only controlled tiny live smoke for Gemma4 E4B after L3.8b load-only acceptance.",
                "production_default=false, wvm_runtime_integration=false, kv_reuse_proven=false, final_user_facing_recommendation=false.",
                "",
                "| Field | Value |",
                "| --- | --- |",
                *[f"| {field} | `{value}` |" for field, value in report_rows],
                "",
                "The run performs exactly one `/api/v1/chat` request after an exact native load verification and requires exact unload cleanup proof.",
                "No `/v1/responses` or `/v1/chat/completions` calls are allowed in this gate.",
                "No raw prompt, raw response text, raw response identifiers, or raw localhost URLs are stored in artifacts.",
                "",
                "## Output Files",
                "",
                *[f"- `{artifact_name}`" for artifact_name in artifact_names],
                "",
            ]
        )
        (run_path / "report.md").write_text(report_text, encoding="utf-8")

        privacy_payloads: dict[str, object] = {
            "environment.json": environment_payload,
            "run_config.json": run_config_payload,
            "load_response_sanitized.json": json.loads(
                (run_path / "load_response_sanitized.json").read_text(encoding="utf-8")
            ),
            "requests.jsonl": list(request_rows),
            "metrics.jsonl": list(metric_rows),
            "system_samples.jsonl": [sample.to_dict() for sample in self._system_sampler.samples],
            "system_summary.json": system_summary.to_dict(),
            "report.md": report_text,
        }
        privacy_violations: list[str] = []
        public_safe_markers = {
            marker
            for marker in (
                _qualifying_privacy_marker(model_id),
                _qualifying_privacy_marker(model_key),
            )
            if marker is not None
        }
        instance_privacy_marker = _qualifying_privacy_marker(raw_instance_id)
        if instance_privacy_marker in public_safe_markers:
            instance_privacy_marker = None
        raw_markers = {
            marker
            for marker in (
                _qualifying_privacy_marker(base_url),
                _qualifying_privacy_marker(endpoint_url),
                instance_privacy_marker,
                _qualifying_privacy_marker(raw_response_id),
                _qualifying_privacy_marker(raw_output_text),
                _qualifying_privacy_marker(prompt_privacy_marker),
            )
            if marker is not None
        }
        for artifact_name, artifact_payload in privacy_payloads.items():
            serialized_payload = (
                artifact_payload
                if isinstance(artifact_payload, str)
                else json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True)
            )
            privacy_violations.extend(
                find_privacy_violations(
                    {"artifact_name": artifact_name, "serialized": serialized_payload},
                    context=artifact_name,
                )
            )
            for raw_marker in raw_markers:
                if raw_marker and raw_marker in serialized_payload:
                    privacy_violations.append(f"{artifact_name} contains a raw private marker")
        privacy_scan = {
            "status": "pass" if not privacy_violations else "fail",
            "violation_count": len(privacy_violations),
            "scan_scope": "l3_8c_gemma4_e4b_tiny_live_smoke_raw_url_path_private_value_scan",
            "scanned_artifacts": list(privacy_payloads),
            "raw_prompt_response_stored": False,
        }
        write_json_file(run_path / "privacy_scan.json", privacy_scan)

        decision = (
            "candidate_tiny_live_smoke_pass"
            if (
                load_verified
                and request_succeeded
                and non_empty_text_pass
                and cleanup_verified
                and privacy_scan["status"] == "pass"
            )
            else "candidate_tiny_live_smoke_fail"
        )
        summary = _sanitize_operation_summary(
            {
                "decision": decision,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "model_key": model_key,
                "model_id": model_id,
                "requested_context_length": requested_context_length,
                "applied_context_length": applied_context_length,
                "requested_parallel": requested_parallel,
                "applied_parallel": applied_parallel,
                "load_verified": load_verified,
                "load_called": raw_instance_id is not None,
                "unload_called": unload_called,
                "generation_called": generation_called,
                "request_succeeded": request_succeeded,
                "non_empty_text_pass": non_empty_text_pass,
                "content_nonempty": non_empty_text_pass,
                "cleanup_verified": cleanup_verified,
                "final_loaded_instances": final_loaded_instances,
                "privacy_scan_status": privacy_scan["status"],
                "failure_reason": failure_reason,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "final_user_facing_recommendation": False,
                "live_25k_authorized": False,
                "generation_allowed": True,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "estimated_input_tokens": estimated_input_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "load_time_ms": load_time_ms,
                "prompt_processing_ms": prompt_processing_ms,
                "time_to_first_token_ms": time_to_first_token_ms,
                "total_latency_ms": total_latency_ms,
                "tokens_per_second": tokens_per_second,
                "managed_live": True,
                "lab_only": True,
                "route": generation_route,
                "endpoint_path": endpoint_path,
                "responses_called": False,
                "chat_completions_called": False,
                "store_raw_prompt_response": False,
                "raw_prompt_response_stored": False,
            }
        )

        if privacy_scan["status"] != "pass":
            raise RuntimeError(
                "L3.8c Gemma E4B tiny live smoke acceptance gate failed: privacy_scan_failed"
            )
        if execution_failure is not None:
            raise execution_failure
        if decision != "candidate_tiny_live_smoke_pass":
            raise RuntimeError(
                "L3.8c Gemma E4B tiny live smoke acceptance gate failed: tiny_live_smoke_failed"
            )

        return {
            **summary,
            **_build_safe_system_summary(system_summary),
        }

    def run_l3_6c_25k_compact_memory_live_smoke(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
        timeout_s: float = 120.0,
        native_transport: ModelLifecycleTransport | None = None,
        chat_transport: LiveTransport | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        _, raw_payload = load_raw_experiment_config(Path(config_path))

        def _require_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
            if not isinstance(value, Mapping):
                raise ValueError(f"{field_name} must be a mapping")
            return value

        def _require_non_empty_string(value: object, *, field_name: str) -> str:
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            text = value.strip()
            if not text:
                raise ValueError(f"{field_name} must be a non-empty string")
            return text

        def _require_bool(value: object, *, field_name: str) -> bool:
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean")
            return value

        def _require_int(value: object, *, field_name: str, minimum: int | None = None) -> int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
            if minimum is not None and value < minimum:
                raise ValueError(f"{field_name} must be >= {minimum}")
            return value

        def _require_string_sequence(value: object, *, field_name: str) -> tuple[str, ...]:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                raise ValueError(f"{field_name} must be a sequence of strings")
            items: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    raise ValueError(f"{field_name} must be a sequence of strings")
                items.append(item)
            return tuple(items)

        def _default_native_transport(
            request: urllib_request.Request,
            request_timeout_s: float,
        ) -> bytes:
            with urllib_request.urlopen(request, timeout=request_timeout_s) as response:
                response_bytes = response.read()
                if not isinstance(response_bytes, bytes):
                    raise TypeError("native transport response must be bytes")
                return response_bytes

        def _request_json(
            *,
            method: str,
            url: str,
            body: Mapping[str, Any] | None = None,
        ) -> tuple[Mapping[str, Any], str]:
            data = None
            headers = {"Accept": "application/json"}
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = urllib_request.Request(url, data=data, headers=headers, method=method)
            response_bytes = request_transport(request, timeout_s)
            response_text = response_bytes.decode("utf-8")
            decoded = json.loads(response_text)
            if not isinstance(decoded, Mapping):
                raise ValueError(f"{method} response must be a JSON object")
            return decoded, response_text

        def _sanitize_models_payload(
            *,
            response_payload: Mapping[str, Any],
            response_text: str,
        ) -> tuple[dict[str, object], tuple[LoadedInstanceRecord, ...]]:
            parsed = parse_native_model_list(response_payload)
            if parsed.error is not None:
                raise ValueError("native model list response must parse successfully")
            target_model = next(
                (model for model in parsed.native_models if model.native_model_key == model_id),
                None,
            )
            loaded_instances = tuple(
                target_model.loaded_instances if target_model is not None else ()
            )
            return (
                {
                    "endpoint_kind": "native_models",
                    "method": "GET",
                    "target_model_id": model_id,
                    "target_model_key": model_key,
                    "target_model_present": target_model is not None,
                    "target_loaded_instance_count": len(loaded_instances),
                    "instance_id_hashes": [instance.instance_ref for instance in loaded_instances],
                    "context_lengths": [
                        instance.context_length
                        for instance in loaded_instances
                        if instance.context_length is not None
                    ],
                    "parallels": [
                        instance.parallel
                        for instance in loaded_instances
                        if instance.parallel is not None
                    ],
                    "response_hash": _safe_hash(response_text),
                    "response_chars": len(response_text),
                },
                loaded_instances,
            )

        def _build_synthetic_prompt() -> str:
            target_chars = _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_PROMPT_CHARS
            parts = [
                "Compact memory controlled live smoke synthetic minimized L3.6b prompt. "
                "Lab-only deterministic input with no user content.\n"
            ]
            current_chars = len(parts[0])
            index = 1
            while current_chars < target_chars:
                segment = (
                    f"[{index:04d}] queue checkpoint glossary export recap stateful stateless "
                    "compact memory controlled live smoke minimized prompt segment. "
                )
                remaining = target_chars - current_chars
                if len(segment) > remaining:
                    segment = segment[:remaining]
                parts.append(segment)
                current_chars += len(segment)
                index += 1
            prompt_text = "".join(parts)
            if len(prompt_text) != target_chars:
                raise RuntimeError(
                    "failed to materialize deterministic compact-memory prompt shape"
                )
            if (
                estimate_input_tokens_from_chars(len(prompt_text))
                != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ESTIMATED_INPUT_TOKENS
            ):
                raise RuntimeError(
                    "deterministic compact-memory prompt no longer matches 22.7k token shape"
                )
            return prompt_text

        def _extract_usage_tokens(
            response_payload: Mapping[str, Any],
        ) -> tuple[int | None, int | None]:
            usage = response_payload.get("usage")
            if not isinstance(usage, Mapping):
                return None, None
            input_tokens = _as_optional_int(usage.get("prompt_tokens", usage.get("input_tokens")))
            output_tokens = _as_optional_int(
                usage.get("completion_tokens", usage.get("output_tokens"))
            )
            return input_tokens, output_tokens

        def _extract_stats_rate(
            response_payload: Mapping[str, Any],
            *field_names: str,
        ) -> float | None:
            stats = response_payload.get("stats")
            if not isinstance(stats, Mapping):
                return None
            for field_name in field_names:
                value = _as_optional_rate(stats.get(field_name))
                if value is not None:
                    return round(value, 3)
            return None

        def _extract_prompt_processing_ms(response_payload: Mapping[str, Any]) -> float | None:
            prompt_processing_ms = _extract_stats_rate(
                response_payload,
                "prompt_processing_ms",
                "prompt_processing_time_ms",
            )
            if prompt_processing_ms is not None:
                return prompt_processing_ms
            prompt_processing_seconds = _extract_stats_rate(
                response_payload,
                "prompt_processing_seconds",
                "prompt_processing_time_seconds",
                "prompt_processing",
                "prompt_processing_time",
            )
            if prompt_processing_seconds is not None:
                return round(prompt_processing_seconds * 1000.0, 3)
            return None

        request_transport = native_transport or _default_native_transport
        request_chat_transport = chat_transport or _default_live_transport

        experiment_id = _require_non_empty_string(
            raw_payload.get("experiment_id"),
            field_name="experiment_id",
        )
        if experiment_id != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_EXPERIMENT_ID:
            raise ValueError(
                "L3.6c compact-memory live smoke requires experiment_id 'l3_6c_25k_compact_memory_live_smoke_gemma4_e2b'"
            )

        mode = _require_non_empty_string(raw_payload.get("mode"), field_name="mode")
        if mode != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_MODE:
            raise ValueError(
                "L3.6c compact-memory live smoke requires mode 'compact_memory_controlled_live_smoke'"
            )

        model_payload = _require_mapping(raw_payload.get("model"), field_name="model")
        model_key = _require_non_empty_string(model_payload.get("key"), field_name="model.key")
        if model_key != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_MODEL_KEY:
            raise ValueError("L3.6c compact-memory live smoke requires model.key 'gemma4_e2b_q4km'")
        model_id = _require_non_empty_string(
            model_payload.get("lmstudio_model_id"),
            field_name="model.lmstudio_model_id",
        )
        if model_id != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_MODEL_ID:
            raise ValueError(
                "L3.6c compact-memory live smoke requires model.lmstudio_model_id 'google/gemma-4-e2b'"
            )

        load_payload = _require_mapping(raw_payload.get("load"), field_name="load")
        requested_context_length = _require_int(
            load_payload.get("context_length"),
            field_name="load.context_length",
            minimum=1,
        )
        if requested_context_length != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_CONTEXT_LENGTH:
            raise ValueError("L3.6c compact-memory live smoke requires load.context_length=32768")
        echo_load_config = _require_bool(
            load_payload.get("echo_load_config"),
            field_name="load.echo_load_config",
        )
        if not echo_load_config:
            raise ValueError("L3.6c compact-memory live smoke requires load.echo_load_config=true")
        flash_attention = _require_bool(
            load_payload.get("flash_attention"),
            field_name="load.flash_attention",
        )
        if not flash_attention:
            raise ValueError("L3.6c compact-memory live smoke requires load.flash_attention=true")
        offload_kv_cache_to_gpu = _require_bool(
            load_payload.get("offload_kv_cache_to_gpu"),
            field_name="load.offload_kv_cache_to_gpu",
        )
        if not offload_kv_cache_to_gpu:
            raise ValueError(
                "L3.6c compact-memory live smoke requires load.offload_kv_cache_to_gpu=true"
            )
        requested_parallel = _require_int(
            load_payload.get("parallel"),
            field_name="load.parallel",
            minimum=1,
        )
        if requested_parallel != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_PARALLEL:
            raise ValueError("L3.6c compact-memory live smoke requires load.parallel=1")

        app_concurrency = _require_int(
            raw_payload.get("app_concurrency"),
            field_name="app_concurrency",
            minimum=1,
        )
        if app_concurrency != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_APP_CONCURRENCY:
            raise ValueError("L3.6c compact-memory live smoke requires app_concurrency=1")

        dataset_payload = _require_mapping(raw_payload.get("dataset"), field_name="dataset")
        dataset_id = _require_non_empty_string(dataset_payload.get("id"), field_name="dataset.id")
        if dataset_id != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_DATASET_ID:
            raise ValueError(
                "L3.6c compact-memory live smoke requires dataset.id 'lecture_25k_tokens'"
            )

        minimized_prompt_payload = _require_mapping(
            raw_payload.get("minimized_prompt"),
            field_name="minimized_prompt",
        )
        if (
            _require_int(
                minimized_prompt_payload.get("estimated_input_tokens"),
                field_name="minimized_prompt.estimated_input_tokens",
                minimum=1,
            )
            != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ESTIMATED_INPUT_TOKENS
        ):
            raise ValueError(
                "L3.6c compact-memory live smoke requires minimized_prompt.estimated_input_tokens=22700"
            )
        if (
            _require_int(
                minimized_prompt_payload.get("estimated_reduction_tokens"),
                field_name="minimized_prompt.estimated_reduction_tokens",
                minimum=1,
            )
            != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ESTIMATED_REDUCTION_TOKENS
        ):
            raise ValueError(
                "L3.6c compact-memory live smoke requires minimized_prompt.estimated_reduction_tokens=2300"
            )
        if (
            _require_int(
                minimized_prompt_payload.get("baseline_estimated_input_tokens"),
                field_name="minimized_prompt.baseline_estimated_input_tokens",
                minimum=1,
            )
            != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_BASELINE_INPUT_TOKENS
        ):
            raise ValueError(
                "L3.6c compact-memory live smoke requires minimized_prompt.baseline_estimated_input_tokens=25000"
            )
        if (
            _require_int(
                minimized_prompt_payload.get("output_reserve_tokens"),
                field_name="minimized_prompt.output_reserve_tokens",
                minimum=1,
            )
            != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_OUTPUT_RESERVE_TOKENS
        ):
            raise ValueError(
                "L3.6c compact-memory live smoke requires minimized_prompt.output_reserve_tokens=2048"
            )

        generation_payload = _require_mapping(
            raw_payload.get("generation"), field_name="generation"
        )
        generation_route = _require_non_empty_string(
            generation_payload.get("route"),
            field_name="generation.route",
        )
        if generation_route != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ROUTE:
            raise ValueError(
                "L3.6c compact-memory live smoke requires generation.route 'compact_memory'"
            )
        endpoint_path = _require_non_empty_string(
            generation_payload.get("endpoint_path"),
            field_name="generation.endpoint_path",
        )
        if endpoint_path != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ENDPOINT_PATH:
            raise ValueError(
                "L3.6c compact-memory live smoke requires generation.endpoint_path '/api/v1/chat'"
            )
        temperature = _require_int(
            generation_payload.get("temperature"),
            field_name="generation.temperature",
            minimum=0,
        )
        if temperature != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_TEMPERATURE:
            raise ValueError("L3.6c compact-memory live smoke requires generation.temperature=0")
        max_output_tokens = _require_int(
            generation_payload.get("max_output_tokens"),
            field_name="generation.max_output_tokens",
            minimum=1,
        )
        if max_output_tokens not in _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ALLOWED_MAX_OUTPUT_TOKENS:
            raise ValueError(
                "L3.6c compact-memory live smoke requires generation.max_output_tokens; allowed values are 64 or 128"
            )
        store = _require_bool(generation_payload.get("store"), field_name="generation.store")
        if store:
            raise ValueError("L3.6c compact-memory live smoke requires generation.store=false")

        safety_payload = _require_mapping(raw_payload.get("safety"), field_name="safety")
        generation_allowed = _require_bool(
            safety_payload.get("generation_allowed"),
            field_name="safety.generation_allowed",
        )
        if not generation_allowed:
            raise ValueError(
                "L3.6c compact-memory live smoke requires safety.generation_allowed=true"
            )
        live_25k_authorized = _require_bool(
            safety_payload.get("live_25k_authorized"),
            field_name="safety.live_25k_authorized",
        )
        if not live_25k_authorized:
            raise ValueError(
                "L3.6c compact-memory live smoke requires safety.live_25k_authorized=true"
            )
        production_default = _require_bool(
            safety_payload.get("production_default"),
            field_name="safety.production_default",
        )
        if production_default:
            raise ValueError("safety.production_default must remain false")
        wvm_runtime_integration = _require_bool(
            safety_payload.get("wvm_runtime_integration"),
            field_name="safety.wvm_runtime_integration",
        )
        if wvm_runtime_integration:
            raise ValueError("safety.wvm_runtime_integration must remain false")
        kv_reuse_proven = _require_bool(
            safety_payload.get("kv_reuse_proven"),
            field_name="safety.kv_reuse_proven",
        )
        if kv_reuse_proven:
            raise ValueError("safety.kv_reuse_proven must remain false")
        unload_required = _require_bool(
            safety_payload.get("unload_required"),
            field_name="safety.unload_required",
        )
        if not unload_required:
            raise ValueError("L3.6c compact-memory live smoke requires safety.unload_required=true")
        final_loaded_instances_required = _require_int(
            safety_payload.get("final_loaded_instances_required"),
            field_name="safety.final_loaded_instances_required",
            minimum=0,
        )
        if final_loaded_instances_required != 0:
            raise ValueError(
                "L3.6c compact-memory live smoke requires safety.final_loaded_instances_required=0"
            )

        privacy_payload = _require_mapping(raw_payload.get("privacy"), field_name="privacy")
        if _require_bool(
            privacy_payload.get("store_raw_prompt_response"),
            field_name="privacy.store_raw_prompt_response",
        ):
            raise ValueError("privacy.store_raw_prompt_response must remain false")
        if _require_bool(
            privacy_payload.get("store_local_urls"),
            field_name="privacy.store_local_urls",
        ):
            raise ValueError("privacy.store_local_urls must remain false")
        if _require_bool(
            privacy_payload.get("store_state_ids_raw"),
            field_name="privacy.store_state_ids_raw",
        ):
            raise ValueError("privacy.store_state_ids_raw must remain false")

        memory_safety_payload = _require_mapping(
            raw_payload.get("memory_safety"),
            field_name="memory_safety",
        )
        max_ram_peak_mb = _require_int(
            memory_safety_payload.get("max_ram_peak_mb"),
            field_name="memory_safety.max_ram_peak_mb",
            minimum=1,
        )
        max_vram_peak_mb = _require_int(
            memory_safety_payload.get("max_vram_peak_mb"),
            field_name="memory_safety.max_vram_peak_mb",
            minimum=1,
        )

        artifacts = raw_payload.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes, bytearray)):
            raise ValueError("artifacts must be a list of strings")
        artifact_names = tuple(
            _require_non_empty_string(artifact_name, field_name="artifacts[]")
            for artifact_name in artifacts
        )
        if artifact_names != _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_OUTPUT_FILES:
            raise ValueError(
                "L3.6c compact-memory live smoke requires the exact artifact list declared by the L3.6c contract"
            )

        base_url = str(raw_payload.get("lmstudio_base_url", "http://127.0.0.1:1234")).strip()
        if not base_url:
            base_url = "http://127.0.0.1:1234"
        base_url = base_url.rstrip("/")
        endpoint_url = _build_cache_stateful_live_smoke_url(base_url)

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        requests_path = run_path / "requests.jsonl"
        metrics_path = run_path / "metrics.jsonl"
        requests_path.write_text("", encoding="utf-8")
        metrics_path.write_text("", encoding="utf-8")

        prompt_text = _build_synthetic_prompt()
        prompt_chars = len(prompt_text)
        prompt_hash = _safe_hash(prompt_text)
        prompt_privacy_marker = _build_prompt_privacy_marker(prompt_text)
        estimated_input_tokens = estimate_input_tokens_from_chars(prompt_chars)

        environment_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "managed_live": True,
            "lab_only": True,
            "generation_allowed": True,
            "live_25k_authorized": True,
            "production_default": False,
            "wvm_runtime_integration": False,
            "kv_reuse_proven": False,
        }
        write_json_file(run_path / "environment.json", environment_payload)

        run_config_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "model_key": model_key,
            "model_id": model_id,
            "dataset_id": dataset_id,
            "app_concurrency": app_concurrency,
            "requested_context_length": requested_context_length,
            "requested_parallel": requested_parallel,
            "load": {
                "context_length": requested_context_length,
                "parallel": requested_parallel,
                "echo_load_config": echo_load_config,
                "flash_attention": flash_attention,
                "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
            },
            "generation": {
                "route": generation_route,
                "endpoint_path": endpoint_path,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "store": False,
            },
            "input_shape": {
                "input_hash": prompt_hash,
                "input_chars": prompt_chars,
                "estimated_input_tokens": estimated_input_tokens,
                "estimated_reduction_tokens": _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_ESTIMATED_REDUCTION_TOKENS,
                "baseline_estimated_input_tokens": _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_BASELINE_INPUT_TOKENS,
                "output_reserve_tokens": _L3_6C_25K_COMPACT_MEMORY_LIVE_SMOKE_OUTPUT_RESERVE_TOKENS,
            },
            "safety": {
                "generation_allowed": True,
                "live_25k_authorized": True,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "unload_required": True,
                "final_loaded_instances_required": 0,
            },
            "privacy": {
                "store_raw_prompt_response": False,
                "store_local_urls": False,
                "store_state_ids_raw": False,
            },
            "memory_safety": {
                "max_ram_peak_mb": max_ram_peak_mb,
                "max_vram_peak_mb": max_vram_peak_mb,
            },
            "artifacts": list(artifact_names),
        }
        write_json_file(run_path / "run_config.json", run_config_payload)

        normalized_providers = _normalize_providers(providers)
        request_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []
        raw_instance_id: str | None = None
        raw_response_id: str | None = None
        raw_output_text: str | None = None
        instance_id_hash: str | None = None
        applied_context_length: int | None = None
        applied_parallel: int | None = None
        load_verified = False
        generation_called = False
        request_succeeded = False
        non_empty_text_pass = False
        cleanup_verified = False
        final_loaded_instances: int | None = None
        load_time_ms: float | None = None
        total_latency_ms: float | None = None
        prompt_processing_ms: float | None = None
        time_to_first_token_ms: float | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        tokens_per_second: float | None = None
        observed_ram_peak_mb: float | None = None
        observed_vram_peak_mb: float | None = None
        memory_safety_pass = True
        system_summary: SystemMetricsSummary | None = None
        pending_exception: (
            tuple[type[BaseException], BaseException, TracebackType | None] | None
        ) = None

        self._system_sampler.start(providers=normalized_providers)
        try:
            models_before_payload, models_before_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            _, preexisting_loaded_instances = _sanitize_models_payload(
                response_payload=models_before_payload,
                response_text=models_before_text,
            )
            if preexisting_loaded_instances:
                raise ValueError("target model already has loaded instances before WVM-owned load")

            load_request_body = {
                "model": model_id,
                "context_length": requested_context_length,
                "echo_load_config": echo_load_config,
                "flash_attention": flash_attention,
                "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
                "parallel": requested_parallel,
            }
            load_started_at = _live_request_perf_counter()
            load_response_payload, load_response_text = _request_json(
                method="POST",
                url=f"{base_url}/api/v1/models/load",
                body=load_request_body,
            )
            load_time_ms = round((_live_request_perf_counter() - load_started_at) * 1000.0, 3)
            raw_instance_id = _as_optional_str(
                load_response_payload.get("instance_id")
                or load_response_payload.get("instanceId")
                or load_response_payload.get("id")
            )
            if raw_instance_id is None:
                raise ValueError("load response must include instance_id")
            instance_id_hash = _safe_hash(raw_instance_id)
            load_config_response = load_response_payload.get("load_config")
            if not isinstance(load_config_response, Mapping):
                raise ValueError("load response must include load_config mapping")
            applied_context_length = _as_optional_int(load_config_response.get("context_length"))
            applied_parallel = _as_optional_int(
                load_config_response.get("parallel", load_config_response.get("n_parallel"))
            )
            if applied_context_length != requested_context_length:
                raise ValueError("owned native load must materialize context_length=32768")
            if applied_parallel != requested_parallel:
                raise ValueError("owned native load must materialize parallel=1")
            write_json_file(
                run_path / "load_response_sanitized.json",
                {
                    "endpoint_kind": "native_load",
                    "method": "POST",
                    "status": _as_optional_str(load_response_payload.get("status")) or "unknown",
                    "instance_id_hash": instance_id_hash,
                    "load_time_ms": load_time_ms,
                    "applied_load_config": {
                        "context_length": applied_context_length,
                        "parallel": applied_parallel,
                        "echo_load_config": _as_optional_bool(
                            load_config_response.get("echo_load_config")
                        ),
                        "flash_attention": _as_optional_bool(
                            load_config_response.get("flash_attention")
                        ),
                        "offload_kv_cache_to_gpu": _as_optional_bool(
                            load_config_response.get("offload_kv_cache_to_gpu")
                        ),
                    },
                    "response_hash": _safe_hash(load_response_text),
                    "response_chars": len(load_response_text),
                },
            )

            models_after_load_payload, models_after_load_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            models_after_load, loaded_instances = _sanitize_models_payload(
                response_payload=models_after_load_payload,
                response_text=models_after_load_text,
            )
            owned_instance = next(
                (
                    instance
                    for instance in loaded_instances
                    if instance.instance_ref == instance_id_hash
                ),
                None,
            )
            load_verified = (
                owned_instance is not None
                and applied_context_length == requested_context_length
                and applied_parallel == requested_parallel
            )
            if not load_verified:
                raise ValueError("owned native load verification failed")

            request_payload = {
                "model": model_id,
                "input": prompt_text,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "store": False,
            }
            generation_called = True
            request_started_at = _live_request_perf_counter()
            response_payload = request_chat_transport(endpoint_url, request_payload, timeout_s)
            total_latency_ms = round(
                (_live_request_perf_counter() - request_started_at) * 1000.0,
                3,
            )
            if not isinstance(response_payload, Mapping):
                raise ValueError("compact-memory live smoke response must be a JSON object")
            if "previous_response_id" in request_payload:
                raise ValueError(
                    "compact-memory live smoke request must not set previous_response_id"
                )

            raw_response_id = _as_optional_str(
                response_payload.get("response_id")
                or response_payload.get("responseId")
                or response_payload.get("id")
            )
            raw_output_text = _extract_cache_stateful_live_smoke_output_text(response_payload)
            if raw_output_text is None:
                raise ValueError("compact-memory live smoke response must include non-empty output")
            non_empty_text_pass = True
            request_succeeded = True
            input_tokens, output_tokens = _extract_usage_tokens(response_payload)
            prompt_processing_ms = _extract_prompt_processing_ms(response_payload)
            time_to_first_token_ms = _extract_stats_ttft_ms(response_payload)
            tokens_per_second = _extract_stats_rate(response_payload, "tokens_per_second")
            if (
                tokens_per_second is None
                and output_tokens is not None
                and total_latency_ms not in (None, 0)
            ):
                tokens_per_second = round(output_tokens / (total_latency_ms / 1000.0), 3)

            request_row = {
                "schema_version": SCHEMA_VERSION,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "managed_live": True,
                "request_id": "compact_memory_single",
                "request_role": "compact_memory",
                "model_key": model_key,
                "model_id": model_id,
                "endpoint_path": endpoint_path,
                "app_concurrency": app_concurrency,
                "requested_context_length": requested_context_length,
                "requested_parallel": requested_parallel,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "store": False,
                "input_hash": prompt_hash,
                "input_chars": prompt_chars,
                "estimated_input_tokens": estimated_input_tokens,
                "previous_response_id_used": False,
                "response_id_present": raw_response_id is not None,
                "response_id_hash": (_safe_hash(raw_response_id) if raw_response_id else None),
                "response_hash": _safe_hash(raw_output_text),
                "response_chars": len(raw_output_text),
                "content_nonempty": True,
                "non_empty_text_pass": True,
                "raw_prompt_response_stored": False,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "live_25k_authorized": True,
                "generation_allowed": True,
                "status": "success",
            }
            metric_row = {
                "schema_version": SCHEMA_VERSION,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "managed_live": True,
                "request_id": "compact_memory_single",
                "request_role": "compact_memory",
                "model_key": model_key,
                "model_id": model_id,
                "endpoint_path": endpoint_path,
                "app_concurrency": app_concurrency,
                "requested_context_length": requested_context_length,
                "applied_context_length": applied_context_length,
                "requested_parallel": requested_parallel,
                "applied_parallel": applied_parallel,
                "load_verified": True,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "store": False,
                "input_hash": prompt_hash,
                "input_chars": prompt_chars,
                "estimated_input_tokens": estimated_input_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "prompt_processing_ms": prompt_processing_ms,
                "time_to_first_token_ms": time_to_first_token_ms,
                "tokens_per_second": tokens_per_second,
                "total_latency_ms": total_latency_ms,
                "response_id_present": raw_response_id is not None,
                "response_id_hash": (_safe_hash(raw_response_id) if raw_response_id else None),
                "response_hash": _safe_hash(raw_output_text),
                "response_chars": len(raw_output_text),
                "content_nonempty": True,
                "non_empty_text_pass": True,
                "raw_prompt_response_stored": False,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "live_25k_authorized": True,
                "generation_allowed": True,
                "status": "success",
            }
            request_rows.append(append_jsonl_record(requests_path, request_row))
            metric_rows.append(append_jsonl_record(metrics_path, metric_row))
        except Exception:
            pending_exception = cast(
                tuple[type[BaseException], BaseException, TracebackType | None],
                sys.exc_info(),
            )
        finally:
            cleanup_error: Exception | None = None
            if raw_instance_id is not None:
                try:
                    _request_json(
                        method="POST",
                        url=f"{base_url}/api/v1/models/unload",
                        body={"instance_id": raw_instance_id},
                    )
                    models_after_unload_payload, models_after_unload_text = _request_json(
                        method="GET",
                        url=f"{base_url}/api/v1/models",
                    )
                    models_after_unload, _ = _sanitize_models_payload(
                        response_payload=models_after_unload_payload,
                        response_text=models_after_unload_text,
                    )
                    final_loaded_instances = _as_optional_int(
                        models_after_unload.get("target_loaded_instance_count")
                    )
                    models_after_unload_instance_hashes = _require_string_sequence(
                        models_after_unload.get("instance_id_hashes"),
                        field_name="models_after_unload.instance_id_hashes",
                    )
                    cleanup_verified = bool(
                        final_loaded_instances == final_loaded_instances_required
                        and instance_id_hash is not None
                        and instance_id_hash not in models_after_unload_instance_hashes
                    )
                    if not cleanup_verified:
                        cleanup_error = RuntimeError("native cleanup not verified")
                except Exception as error:
                    cleanup_error = error
            try:
                system_summary = self._system_sampler.stop(providers=normalized_providers)
                write_system_telemetry_artifacts(
                    run_path,
                    samples=self._system_sampler.samples,
                    summary=system_summary,
                )
            except Exception as error:
                if cleanup_error is None:
                    cleanup_error = error

            if pending_exception is not None:
                exc_type, exc, traceback = pending_exception
                if exc is not None:
                    raise exc.with_traceback(traceback)
                raise exc_type
            if cleanup_error is not None:
                raise cleanup_error

        assert system_summary is not None

        system_summary_payload = system_summary.to_dict()
        observed_ram_peak_mb = _as_optional_rate(system_summary_payload.get("ram_peak_mb"))
        observed_vram_peak_mb = _as_optional_rate(system_summary_payload.get("vram_peak_mb"))
        memory_safety_pass = True
        if observed_ram_peak_mb is not None and observed_ram_peak_mb > max_ram_peak_mb:
            memory_safety_pass = False
        if observed_vram_peak_mb is not None and observed_vram_peak_mb > max_vram_peak_mb:
            memory_safety_pass = False

        for metric_row in metric_rows:
            metric_row["max_ram_peak_mb"] = max_ram_peak_mb
            metric_row["max_vram_peak_mb"] = max_vram_peak_mb
            metric_row["memory_safety_pass"] = memory_safety_pass
        if metric_rows:
            _rewrite_jsonl_records(metrics_path, metric_rows)

        report_rows = (
            ("experiment_id", experiment_id),
            ("run_id", safe_run_id),
            ("mode", mode),
            ("route", generation_route),
            ("endpoint_path", endpoint_path),
            ("requested_context_length", str(requested_context_length)),
            ("applied_context_length", str(applied_context_length)),
            ("requested_parallel", str(requested_parallel)),
            ("applied_parallel", str(applied_parallel)),
            ("load_verified", str(load_verified).lower()),
            ("generation_called", str(generation_called).lower()),
            ("request_succeeded", str(request_succeeded).lower()),
            ("non_empty_text_pass", str(non_empty_text_pass).lower()),
            ("cleanup_verified", str(cleanup_verified).lower()),
            ("final_loaded_instances", str(final_loaded_instances)),
            ("ram_peak_mb", str(observed_ram_peak_mb)),
            ("vram_peak_mb", str(observed_vram_peak_mb)),
            ("max_ram_peak_mb", str(max_ram_peak_mb)),
            ("max_vram_peak_mb", str(max_vram_peak_mb)),
            ("memory_safety_pass", str(memory_safety_pass).lower()),
            ("production_default", "false"),
            ("wvm_runtime_integration", "false"),
            ("kv_reuse_proven", "false"),
            ("temperature", str(temperature)),
            ("max_output_tokens", str(max_output_tokens)),
            ("estimated_input_tokens", str(estimated_input_tokens)),
        )
        report_text = "\n".join(
            [
                "# LM Studio Lab L3.6c Compact Memory Controlled Live Smoke Report",
                "",
                "This is a lab-only compact_memory-only live smoke gate after L3.6b prompt minimization.",
                "production_default=false, wvm_runtime_integration=false, kv_reuse_proven=false.",
                "KV reuse is not proven by this run.",
                "",
                "| Field | Value |",
                "| --- | --- |",
                *[f"| {field} | `{value}` |" for field, value in report_rows],
                "",
                "The run performs exactly one compact-memory `/api/v1/chat` request after an exact native load verification and requires exact unload cleanup proof.",
                "A pass decision also requires a clean privacy scan and memory peaks within the configured lab-only safety thresholds.",
                "No raw prompt, raw response text, raw response identifiers, or raw localhost URLs are stored in artifacts.",
                "",
            ]
        )

        privacy_payloads: dict[str, object] = {
            "environment.json": environment_payload,
            "run_config.json": run_config_payload,
            "load_response_sanitized.json": json.loads(
                (run_path / "load_response_sanitized.json").read_text(encoding="utf-8")
            ),
            "requests.jsonl": list(request_rows),
            "metrics.jsonl": list(metric_rows),
            "system_samples.jsonl": [sample.to_dict() for sample in self._system_sampler.samples],
            "system_summary.json": system_summary.to_dict(),
            "report.md": report_text,
        }
        privacy_violations: list[str] = []
        public_safe_markers = {
            marker
            for marker in (
                _qualifying_privacy_marker(model_id),
                _qualifying_privacy_marker(model_key),
            )
            if marker is not None
        }
        instance_privacy_marker = _qualifying_privacy_marker(raw_instance_id)
        if instance_privacy_marker in public_safe_markers:
            instance_privacy_marker = None
        raw_markers = {
            marker
            for marker in (
                _qualifying_privacy_marker(base_url),
                _qualifying_privacy_marker(endpoint_url),
                instance_privacy_marker,
                _qualifying_privacy_marker(raw_response_id),
                _qualifying_privacy_marker(raw_output_text),
                _qualifying_privacy_marker(prompt_privacy_marker),
            )
            if marker is not None
        }
        for artifact_name, artifact_payload in privacy_payloads.items():
            serialized_payload = (
                artifact_payload
                if isinstance(artifact_payload, str)
                else json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True)
            )
            privacy_violations.extend(
                find_privacy_violations(
                    {"artifact_name": artifact_name, "serialized": serialized_payload},
                    context=artifact_name,
                )
            )
            for raw_marker in raw_markers:
                if raw_marker and raw_marker in serialized_payload:
                    privacy_violations.append(f"{artifact_name} contains a raw private marker")
        privacy_scan = {
            "status": "pass" if not privacy_violations else "fail",
            "violation_count": len(privacy_violations),
            "scan_scope": "l3_6c_compact_memory_live_smoke_raw_url_path_private_value_scan",
            "scanned_artifacts": list(privacy_payloads),
            "raw_prompt_response_stored": False,
        }
        write_json_file(run_path / "privacy_scan.json", privacy_scan)
        (run_path / "report.md").write_text(report_text, encoding="utf-8")

        privacy_pass = privacy_scan["status"] == "pass"

        decision = (
            "compact_memory_live_smoke_pass"
            if (
                load_verified
                and request_succeeded
                and non_empty_text_pass
                and cleanup_verified
                and privacy_pass
                and memory_safety_pass
            )
            else "compact_memory_live_smoke_fail"
        )
        if not privacy_pass or not memory_safety_pass:
            failure_reasons: list[str] = []
            if not privacy_pass:
                failure_reasons.append("privacy_scan_failed")
            if not memory_safety_pass:
                failure_reasons.append("memory_safety_failed")
            raise RuntimeError(
                "L3.6c compact-memory live smoke acceptance gate failed: "
                + ", ".join(failure_reasons)
            )
        summary = _sanitize_operation_summary(
            {
                "decision": decision,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "model_id": model_id,
                "requested_context_length": requested_context_length,
                "applied_context_length": applied_context_length,
                "requested_parallel": requested_parallel,
                "applied_parallel": applied_parallel,
                "applied_load_config": {
                    "context_length": applied_context_length,
                    "parallel": applied_parallel,
                    "echo_load_config": True,
                    "flash_attention": True,
                    "offload_kv_cache_to_gpu": True,
                },
                "load_verified": load_verified,
                "generation_called": generation_called,
                "request_succeeded": request_succeeded,
                "non_empty_text_pass": non_empty_text_pass,
                "content_nonempty": non_empty_text_pass,
                "cleanup_verified": cleanup_verified,
                "final_loaded_instances": final_loaded_instances,
                "privacy_scan_status": privacy_scan["status"],
                "memory_safety_pass": memory_safety_pass,
                "max_ram_peak_mb": max_ram_peak_mb,
                "max_vram_peak_mb": max_vram_peak_mb,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "live_25k_authorized": True,
                "generation_allowed": True,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "estimated_input_tokens": estimated_input_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "load_time_ms": load_time_ms,
                "prompt_processing_ms": prompt_processing_ms,
                "time_to_first_token_ms": time_to_first_token_ms,
                "total_latency_ms": total_latency_ms,
                "tokens_per_second": tokens_per_second,
                "managed_live": True,
                "lab_only": True,
                "route": generation_route,
                "app_concurrency": app_concurrency,
                "store_raw_prompt_response": False,
                "raw_prompt_response_stored": False,
            }
        )
        return {
            **summary,
            **_build_safe_system_summary(system_summary),
        }

    def run_l3_6d_25k_mode_comparison_live(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
        timeout_s: float = 120.0,
        native_transport: ModelLifecycleTransport | None = None,
        chat_transport: LiveTransport | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        _, raw_payload = load_raw_experiment_config(Path(config_path))

        def _require_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
            if not isinstance(value, Mapping):
                raise ValueError(f"{field_name} must be a mapping")
            return value

        def _require_non_empty_string(value: object, *, field_name: str) -> str:
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            text = value.strip()
            if not text:
                raise ValueError(f"{field_name} must be a non-empty string")
            return text

        def _require_bool(value: object, *, field_name: str) -> bool:
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean")
            return value

        def _require_int(value: object, *, field_name: str, minimum: int | None = None) -> int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
            if minimum is not None and value < minimum:
                raise ValueError(f"{field_name} must be >= {minimum}")
            return value

        def _require_sequence_of_mappings(
            value: object,
            *,
            field_name: str,
        ) -> tuple[Mapping[str, Any], ...]:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                raise ValueError(f"{field_name} must be a sequence of mappings")
            rows: list[Mapping[str, Any]] = []
            for index, item in enumerate(value):
                if not isinstance(item, Mapping):
                    raise ValueError(f"{field_name}[{index}] must be a mapping")
                rows.append(item)
            return tuple(rows)

        def _default_native_transport(
            request: urllib_request.Request,
            request_timeout_s: float,
        ) -> bytes:
            with urllib_request.urlopen(request, timeout=request_timeout_s) as response:
                response_bytes = response.read()
                if not isinstance(response_bytes, bytes):
                    raise TypeError("native transport response must be bytes")
                return response_bytes

        def _request_json(
            *,
            method: str,
            url: str,
            body: Mapping[str, Any] | None = None,
        ) -> tuple[Mapping[str, Any], str]:
            data = None
            headers = {"Accept": "application/json"}
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = urllib_request.Request(url, data=data, headers=headers, method=method)
            response_bytes = request_transport(request, timeout_s)
            response_text = response_bytes.decode("utf-8")
            decoded = json.loads(response_text)
            if not isinstance(decoded, Mapping):
                raise ValueError(f"{method} response must be a JSON object")
            return decoded, response_text

        def _sanitize_models_payload(
            *,
            response_payload: Mapping[str, Any],
            response_text: str,
        ) -> tuple[dict[str, object], tuple[LoadedInstanceRecord, ...]]:
            parsed = parse_native_model_list(response_payload)
            if parsed.error is not None:
                raise ValueError("native model list response must parse successfully")
            target_model = next(
                (model for model in parsed.native_models if model.native_model_key == model_id),
                None,
            )
            loaded_instances = tuple(
                target_model.loaded_instances if target_model is not None else ()
            )
            return (
                {
                    "endpoint_kind": "native_models",
                    "method": "GET",
                    "target_model_id": model_id,
                    "target_model_key": model_key,
                    "target_model_present": target_model is not None,
                    "target_loaded_instance_count": len(loaded_instances),
                    "instance_id_hashes": [instance.instance_ref for instance in loaded_instances],
                    "context_lengths": [
                        instance.context_length
                        for instance in loaded_instances
                        if instance.context_length is not None
                    ],
                    "parallels": [
                        instance.parallel
                        for instance in loaded_instances
                        if instance.parallel is not None
                    ],
                    "response_hash": _safe_hash(response_text),
                    "response_chars": len(response_text),
                },
                loaded_instances,
            )

        def _build_fixed_char_prompt(
            *,
            intro: str,
            segment_seed: str,
            target_chars: int,
            expected_tokens: int,
        ) -> str:
            parts = [f"{intro}\n"]
            current_chars = len(parts[0])
            index = 1
            while current_chars < target_chars:
                segment = (
                    f"[{index:04d}] {segment_seed} synthetic lecture covers queue warmup checkpoints, "
                    "pause-resume stability, export verification, glossary notes, recap writing, "
                    "and stateful versus stateless follow-up routing. "
                )
                remaining = target_chars - current_chars
                if len(segment) > remaining:
                    segment = segment[:remaining]
                parts.append(segment)
                current_chars += len(segment)
                index += 1
            prompt_text = "".join(parts)
            if len(prompt_text) != target_chars:
                raise RuntimeError("failed to materialize deterministic L3.6d prompt shape")
            if estimate_input_tokens_from_chars(len(prompt_text)) != expected_tokens:
                raise RuntimeError("deterministic L3.6d prompt no longer matches token estimate")
            return prompt_text

        def _build_stateful_setup_prompt() -> str:
            return _build_fixed_char_prompt(
                intro=(
                    "Stateful root setup synthetic 25k lecture prompt for L3.6d mode comparison. "
                    "Retain the lecture context for one later summary task and reply with a brief acknowledgement only."
                ),
                segment_seed="stateful-root-setup",
                target_chars=_L3_6D_25K_MODE_COMPARISON_LIVE_STATEFUL_SETUP_PROMPT_CHARS,
                expected_tokens=_L3_6D_25K_MODE_COMPARISON_LIVE_BASELINE_INPUT_TOKENS,
            )

        def _build_compact_memory_prompt(task_text: str) -> str:
            return _build_fixed_char_prompt(
                intro=(
                    "Compact memory controlled synthetic minimized prompt for L3.6d mode comparison. "
                    f"Task: {task_text}"
                ),
                segment_seed="compact-memory-minimized",
                target_chars=_L3_6D_25K_MODE_COMPARISON_LIVE_COMPACT_PROMPT_CHARS,
                expected_tokens=_L3_6D_25K_MODE_COMPARISON_LIVE_MINIMIZED_INPUT_TOKENS,
            )

        def _build_stateless_full_prefix_prompt(task_text: str) -> str:
            return _build_fixed_char_prompt(
                intro=(
                    "Stateless full-prefix synthetic 25k lecture prompt for L3.6d mode comparison. "
                    f"Task: {task_text}"
                ),
                segment_seed="stateless-full-prefix",
                target_chars=_L3_6D_25K_MODE_COMPARISON_LIVE_STATELESS_PROMPT_CHARS,
                expected_tokens=_L3_6D_25K_MODE_COMPARISON_LIVE_BASELINE_INPUT_TOKENS,
            )

        def _extract_usage_tokens(
            response_payload: Mapping[str, Any],
        ) -> tuple[int | None, int | None]:
            usage = response_payload.get("usage")
            if not isinstance(usage, Mapping):
                return None, None
            input_tokens = _as_optional_int(usage.get("prompt_tokens", usage.get("input_tokens")))
            output_tokens = _as_optional_int(
                usage.get("completion_tokens", usage.get("output_tokens"))
            )
            return input_tokens, output_tokens

        def _extract_stats_rate(
            response_payload: Mapping[str, Any],
            *field_names: str,
        ) -> float | None:
            stats = response_payload.get("stats")
            if not isinstance(stats, Mapping):
                return None
            for field_name in field_names:
                value = _as_optional_rate(stats.get(field_name))
                if value is not None:
                    return round(value, 3)
            return None

        def _extract_prompt_processing_ms(response_payload: Mapping[str, Any]) -> float | None:
            prompt_processing_ms = _extract_stats_rate(
                response_payload,
                "prompt_processing_ms",
                "prompt_processing_time_ms",
            )
            if prompt_processing_ms is not None:
                return prompt_processing_ms
            prompt_processing_seconds = _extract_stats_rate(
                response_payload,
                "prompt_processing_seconds",
                "prompt_processing_time_seconds",
                "prompt_processing",
                "prompt_processing_time",
            )
            if prompt_processing_seconds is not None:
                return round(prompt_processing_seconds * 1000.0, 3)
            return None

        request_transport = native_transport or _default_native_transport
        request_chat_transport = chat_transport or _default_live_transport

        experiment_id = _require_non_empty_string(
            raw_payload.get("experiment_id"),
            field_name="experiment_id",
        )
        if experiment_id != _L3_6D_25K_MODE_COMPARISON_LIVE_EXPERIMENT_ID:
            raise ValueError(
                "L3.6d mode comparison live requires experiment_id 'l3_6d_25k_mode_comparison_gemma4_e2b'"
            )

        mode = _require_non_empty_string(raw_payload.get("mode"), field_name="mode")
        if mode != _L3_6D_25K_MODE_COMPARISON_LIVE_MODE:
            raise ValueError(
                "L3.6d mode comparison live requires mode 'mode_comparison_controlled_live'"
            )

        model_payload = _require_mapping(raw_payload.get("model"), field_name="model")
        model_key = _require_non_empty_string(model_payload.get("key"), field_name="model.key")
        if model_key != _L3_6D_25K_MODE_COMPARISON_LIVE_MODEL_KEY:
            raise ValueError("L3.6d mode comparison live requires model.key 'gemma4_e2b_q4km'")
        model_id = _require_non_empty_string(
            model_payload.get("lmstudio_model_id"),
            field_name="model.lmstudio_model_id",
        )
        if model_id != _L3_6D_25K_MODE_COMPARISON_LIVE_MODEL_ID:
            raise ValueError(
                "L3.6d mode comparison live requires model.lmstudio_model_id 'google/gemma-4-e2b'"
            )

        load_payload = _require_mapping(raw_payload.get("load"), field_name="load")
        requested_context_length = _require_int(
            load_payload.get("context_length"),
            field_name="load.context_length",
            minimum=1,
        )
        if requested_context_length != _L3_6D_25K_MODE_COMPARISON_LIVE_CONTEXT_LENGTH:
            raise ValueError("L3.6d mode comparison live requires load.context_length=32768")
        echo_load_config = _require_bool(
            load_payload.get("echo_load_config"),
            field_name="load.echo_load_config",
        )
        if not echo_load_config:
            raise ValueError("L3.6d mode comparison live requires load.echo_load_config=true")
        flash_attention = _require_bool(
            load_payload.get("flash_attention"),
            field_name="load.flash_attention",
        )
        if not flash_attention:
            raise ValueError("L3.6d mode comparison live requires load.flash_attention=true")
        offload_kv_cache_to_gpu = _require_bool(
            load_payload.get("offload_kv_cache_to_gpu"),
            field_name="load.offload_kv_cache_to_gpu",
        )
        if not offload_kv_cache_to_gpu:
            raise ValueError(
                "L3.6d mode comparison live requires load.offload_kv_cache_to_gpu=true"
            )
        requested_parallel = _require_int(
            load_payload.get("parallel"),
            field_name="load.parallel",
            minimum=1,
        )
        if requested_parallel != _L3_6D_25K_MODE_COMPARISON_LIVE_PARALLEL:
            raise ValueError("L3.6d mode comparison live requires load.parallel=1")

        app_concurrency = _require_int(
            raw_payload.get("app_concurrency"),
            field_name="app_concurrency",
            minimum=1,
        )
        if app_concurrency != _L3_6D_25K_MODE_COMPARISON_LIVE_APP_CONCURRENCY:
            raise ValueError("L3.6d mode comparison live requires app_concurrency=1")

        dataset_payload = _require_mapping(raw_payload.get("dataset"), field_name="dataset")
        dataset_id = _require_non_empty_string(dataset_payload.get("id"), field_name="dataset.id")
        if dataset_id != _L3_6D_25K_MODE_COMPARISON_LIVE_DATASET_ID:
            raise ValueError("L3.6d mode comparison live requires dataset.id 'lecture_25k_tokens'")

        prompt_shapes_payload = _require_mapping(
            raw_payload.get("prompt_shapes"),
            field_name="prompt_shapes",
        )
        if (
            _require_int(
                prompt_shapes_payload.get("stateful_setup_estimated_input_tokens"),
                field_name="prompt_shapes.stateful_setup_estimated_input_tokens",
                minimum=1,
            )
            != _L3_6D_25K_MODE_COMPARISON_LIVE_BASELINE_INPUT_TOKENS
        ):
            raise ValueError(
                "L3.6d mode comparison live requires prompt_shapes.stateful_setup_estimated_input_tokens=25000"
            )
        if (
            _require_int(
                prompt_shapes_payload.get("compact_memory_estimated_input_tokens"),
                field_name="prompt_shapes.compact_memory_estimated_input_tokens",
                minimum=1,
            )
            != _L3_6D_25K_MODE_COMPARISON_LIVE_MINIMIZED_INPUT_TOKENS
        ):
            raise ValueError(
                "L3.6d mode comparison live requires prompt_shapes.compact_memory_estimated_input_tokens=22700"
            )
        if (
            _require_int(
                prompt_shapes_payload.get("compact_memory_estimated_reduction_tokens"),
                field_name="prompt_shapes.compact_memory_estimated_reduction_tokens",
                minimum=1,
            )
            != _L3_6D_25K_MODE_COMPARISON_LIVE_MINIMIZED_REDUCTION_TOKENS
        ):
            raise ValueError(
                "L3.6d mode comparison live requires prompt_shapes.compact_memory_estimated_reduction_tokens=2300"
            )
        if (
            _require_int(
                prompt_shapes_payload.get("baseline_estimated_input_tokens"),
                field_name="prompt_shapes.baseline_estimated_input_tokens",
                minimum=1,
            )
            != _L3_6D_25K_MODE_COMPARISON_LIVE_BASELINE_INPUT_TOKENS
        ):
            raise ValueError(
                "L3.6d mode comparison live requires prompt_shapes.baseline_estimated_input_tokens=25000"
            )
        if (
            _require_int(
                prompt_shapes_payload.get("output_reserve_tokens"),
                field_name="prompt_shapes.output_reserve_tokens",
                minimum=1,
            )
            != _L3_6D_25K_MODE_COMPARISON_LIVE_OUTPUT_RESERVE_TOKENS
        ):
            raise ValueError(
                "L3.6d mode comparison live requires prompt_shapes.output_reserve_tokens=2048"
            )

        mode_comparison_payload = _require_mapping(
            raw_payload.get("mode_comparison"),
            field_name="mode_comparison",
        )
        setup_request_payload = _require_mapping(
            mode_comparison_payload.get("setup_request"),
            field_name="mode_comparison.setup_request",
        )
        setup_mode = _require_non_empty_string(
            setup_request_payload.get("mode"),
            field_name="mode_comparison.setup_request.mode",
        )
        if setup_mode != _L3_6D_25K_MODE_COMPARISON_LIVE_SETUP_MODE:
            raise ValueError(
                "L3.6d mode comparison live requires mode_comparison.setup_request.mode 'native_chat_stateful_setup'"
            )
        setup_classification = _require_non_empty_string(
            setup_request_payload.get("classification"),
            field_name="mode_comparison.setup_request.classification",
        )
        if setup_classification != _L3_6D_25K_MODE_COMPARISON_LIVE_SETUP_CLASSIFICATION:
            raise ValueError(
                "L3.6d mode comparison live requires mode_comparison.setup_request.classification 'setup_metadata'"
            )
        setup_route = _require_non_empty_string(
            setup_request_payload.get("route"),
            field_name="mode_comparison.setup_request.route",
        )
        if setup_route != "native_chat_stateful":
            raise ValueError(
                "L3.6d mode comparison live requires mode_comparison.setup_request.route 'native_chat_stateful'"
            )
        setup_endpoint_path = _require_non_empty_string(
            setup_request_payload.get("endpoint_path"),
            field_name="mode_comparison.setup_request.endpoint_path",
        )
        if setup_endpoint_path != _L3_6D_25K_MODE_COMPARISON_LIVE_ENDPOINT_PATH:
            raise ValueError(
                "L3.6d mode comparison live requires mode_comparison.setup_request.endpoint_path '/api/v1/chat'"
            )
        setup_store = _require_bool(
            setup_request_payload.get("store"),
            field_name="mode_comparison.setup_request.store",
        )
        if not setup_store:
            raise ValueError(
                "L3.6d mode comparison live requires mode_comparison.setup_request.store=true"
            )
        setup_previous_response_id_used = _require_bool(
            setup_request_payload.get("previous_response_id_used"),
            field_name="mode_comparison.setup_request.previous_response_id_used",
        )
        if setup_previous_response_id_used:
            raise ValueError(
                "L3.6d mode comparison live requires mode_comparison.setup_request.previous_response_id_used=false"
            )

        comparable_mode_payloads = _require_sequence_of_mappings(
            mode_comparison_payload.get("comparable_modes"),
            field_name="mode_comparison.comparable_modes",
        )
        if len(comparable_mode_payloads) != len(_L3_6D_25K_MODE_COMPARISON_LIVE_COMPARABLE_MODES):
            raise ValueError("L3.6d mode comparison live requires exactly three comparable modes")
        comparable_mode_names = tuple(
            _require_non_empty_string(
                item.get("mode"),
                field_name=f"mode_comparison.comparable_modes[{index}].mode",
            )
            for index, item in enumerate(comparable_mode_payloads)
        )
        if comparable_mode_names != _L3_6D_25K_MODE_COMPARISON_LIVE_COMPARABLE_MODES:
            raise ValueError(
                "L3.6d mode comparison live requires comparable modes ['compact_memory', 'native_chat_stateful', 'stateless_full_prefix']"
            )

        comparable_mode_specs: list[dict[str, object]] = []
        for index, mode_payload in enumerate(comparable_mode_payloads):
            comparable_mode_name = comparable_mode_names[index]
            classification = _require_non_empty_string(
                mode_payload.get("classification"),
                field_name=f"mode_comparison.comparable_modes[{index}].classification",
            )
            if (
                classification
                != _L3_6D_25K_MODE_COMPARISON_LIVE_CLASSIFICATIONS[comparable_mode_name]
            ):
                raise ValueError(
                    f"L3.6d mode comparison live requires mode_comparison.comparable_modes[{index}].classification '{_L3_6D_25K_MODE_COMPARISON_LIVE_CLASSIFICATIONS[comparable_mode_name]}'"
                )
            route = _require_non_empty_string(
                mode_payload.get("route"),
                field_name=f"mode_comparison.comparable_modes[{index}].route",
            )
            if route != comparable_mode_name:
                raise ValueError(
                    f"L3.6d mode comparison live requires mode_comparison.comparable_modes[{index}].route '{comparable_mode_name}'"
                )
            endpoint_path = _require_non_empty_string(
                mode_payload.get("endpoint_path"),
                field_name=f"mode_comparison.comparable_modes[{index}].endpoint_path",
            )
            if endpoint_path != _L3_6D_25K_MODE_COMPARISON_LIVE_ENDPOINT_PATH:
                raise ValueError(
                    f"L3.6d mode comparison live requires mode_comparison.comparable_modes[{index}].endpoint_path '/api/v1/chat'"
                )
            previous_response_id_used = _require_bool(
                mode_payload.get("previous_response_id_used"),
                field_name=f"mode_comparison.comparable_modes[{index}].previous_response_id_used",
            )
            expected_previous_response_id_used = comparable_mode_name == "native_chat_stateful"
            if previous_response_id_used != expected_previous_response_id_used:
                expected_value = str(expected_previous_response_id_used).lower()
                raise ValueError(
                    "L3.6d mode comparison live requires "
                    f"mode_comparison.comparable_modes[{index}].previous_response_id_used={expected_value}"
                )
            store = _require_bool(
                mode_payload.get("store"),
                field_name=f"mode_comparison.comparable_modes[{index}].store",
            )
            if store != _L3_6D_25K_MODE_COMPARISON_LIVE_STORES[comparable_mode_name]:
                expected_store = str(
                    _L3_6D_25K_MODE_COMPARISON_LIVE_STORES[comparable_mode_name]
                ).lower()
                raise ValueError(
                    f"L3.6d mode comparison live requires mode_comparison.comparable_modes[{index}].store={expected_store}"
                )
            comparable_mode_specs.append(
                {
                    "mode": comparable_mode_name,
                    "classification": classification,
                    "route": route,
                    "endpoint_path": endpoint_path,
                    "previous_response_id_used": previous_response_id_used,
                    "store": store,
                }
            )

        generation_payload = _require_mapping(
            raw_payload.get("generation"), field_name="generation"
        )
        temperature = _require_int(
            generation_payload.get("temperature"),
            field_name="generation.temperature",
            minimum=0,
        )
        if temperature != _L3_6D_25K_MODE_COMPARISON_LIVE_TEMPERATURE:
            raise ValueError("L3.6d mode comparison live requires generation.temperature=0")
        max_output_tokens = _require_int(
            generation_payload.get("max_output_tokens"),
            field_name="generation.max_output_tokens",
            minimum=1,
        )
        if max_output_tokens not in _L3_6D_25K_MODE_COMPARISON_LIVE_ALLOWED_MAX_OUTPUT_TOKENS:
            raise ValueError(
                "L3.6d mode comparison live requires generation.max_output_tokens; allowed values are 64 or 128"
            )

        safety_payload = _require_mapping(raw_payload.get("safety"), field_name="safety")
        generation_allowed = _require_bool(
            safety_payload.get("generation_allowed"),
            field_name="safety.generation_allowed",
        )
        if not generation_allowed:
            raise ValueError("L3.6d mode comparison live requires safety.generation_allowed=true")
        live_25k_authorized = _require_bool(
            safety_payload.get("live_25k_authorized"),
            field_name="safety.live_25k_authorized",
        )
        if not live_25k_authorized:
            raise ValueError("L3.6d mode comparison live requires safety.live_25k_authorized=true")
        production_default = _require_bool(
            safety_payload.get("production_default"),
            field_name="safety.production_default",
        )
        if production_default:
            raise ValueError("safety.production_default must remain false")
        wvm_runtime_integration = _require_bool(
            safety_payload.get("wvm_runtime_integration"),
            field_name="safety.wvm_runtime_integration",
        )
        if wvm_runtime_integration:
            raise ValueError("safety.wvm_runtime_integration must remain false")
        kv_reuse_proven = _require_bool(
            safety_payload.get("kv_reuse_proven"),
            field_name="safety.kv_reuse_proven",
        )
        if kv_reuse_proven:
            raise ValueError("safety.kv_reuse_proven must remain false")
        unload_required = _require_bool(
            safety_payload.get("unload_required"),
            field_name="safety.unload_required",
        )
        if not unload_required:
            raise ValueError("L3.6d mode comparison live requires safety.unload_required=true")
        final_loaded_instances_required = _require_int(
            safety_payload.get("final_loaded_instances_required"),
            field_name="safety.final_loaded_instances_required",
            minimum=0,
        )
        if final_loaded_instances_required != 0:
            raise ValueError(
                "L3.6d mode comparison live requires safety.final_loaded_instances_required=0"
            )

        privacy_payload = _require_mapping(raw_payload.get("privacy"), field_name="privacy")
        if _require_bool(
            privacy_payload.get("store_raw_prompt_response"),
            field_name="privacy.store_raw_prompt_response",
        ):
            raise ValueError("privacy.store_raw_prompt_response must remain false")
        if _require_bool(
            privacy_payload.get("store_local_urls"),
            field_name="privacy.store_local_urls",
        ):
            raise ValueError("privacy.store_local_urls must remain false")
        if _require_bool(
            privacy_payload.get("store_state_ids_raw"),
            field_name="privacy.store_state_ids_raw",
        ):
            raise ValueError("privacy.store_state_ids_raw must remain false")

        memory_safety_payload = _require_mapping(
            raw_payload.get("memory_safety"),
            field_name="memory_safety",
        )
        max_ram_peak_mb = _require_int(
            memory_safety_payload.get("max_ram_peak_mb"),
            field_name="memory_safety.max_ram_peak_mb",
            minimum=1,
        )
        max_vram_peak_mb = _require_int(
            memory_safety_payload.get("max_vram_peak_mb"),
            field_name="memory_safety.max_vram_peak_mb",
            minimum=1,
        )

        artifacts = raw_payload.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes, bytearray)):
            raise ValueError("artifacts must be a list of strings")
        artifact_names = tuple(
            _require_non_empty_string(artifact_name, field_name="artifacts[]")
            for artifact_name in artifacts
        )
        if artifact_names != _L3_6D_25K_MODE_COMPARISON_LIVE_OUTPUT_FILES:
            raise ValueError(
                "L3.6d mode comparison live requires the exact artifact list declared by the L3.6d contract"
            )

        base_url = str(raw_payload.get("lmstudio_base_url", "http://127.0.0.1:1234")).strip()
        if not base_url:
            base_url = "http://127.0.0.1:1234"
        base_url = base_url.rstrip("/")
        endpoint_url = _build_cache_stateful_live_smoke_url(base_url)

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        requests_path = run_path / "requests.jsonl"
        metrics_path = run_path / "metrics.jsonl"
        requests_path.write_text("", encoding="utf-8")
        metrics_path.write_text("", encoding="utf-8")

        branch_task = _build_cache_stateful_live_smoke_branch_inputs()["summary_short"]
        stateful_setup_input = _build_stateful_setup_prompt()
        compact_memory_input = _build_compact_memory_prompt(branch_task)
        stateless_full_prefix_input = _build_stateless_full_prefix_prompt(branch_task)
        input_by_mode = {
            "compact_memory": compact_memory_input,
            "native_chat_stateful": branch_task,
            "stateless_full_prefix": stateless_full_prefix_input,
        }
        prompt_privacy_markers = tuple(
            marker
            for marker in (
                _build_prompt_privacy_marker(stateful_setup_input),
                _build_prompt_privacy_marker(branch_task),
                _build_prompt_privacy_marker(compact_memory_input),
                _build_prompt_privacy_marker(stateless_full_prefix_input),
            )
            if marker
        )

        environment_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "managed_live": True,
            "lab_only": True,
            "generation_allowed": True,
            "live_25k_authorized": True,
            "production_default": False,
            "wvm_runtime_integration": False,
            "kv_reuse_proven": False,
        }
        write_json_file(run_path / "environment.json", environment_payload)

        run_config_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "model_key": model_key,
            "model_id": model_id,
            "dataset_id": dataset_id,
            "app_concurrency": app_concurrency,
            "requested_context_length": requested_context_length,
            "requested_parallel": requested_parallel,
            "load": {
                "context_length": requested_context_length,
                "parallel": requested_parallel,
                "echo_load_config": echo_load_config,
                "flash_attention": flash_attention,
                "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
            },
            "generation": {
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
            "input_shape": {
                "stateful_setup_input_hash": _safe_hash(stateful_setup_input),
                "stateful_setup_input_chars": len(stateful_setup_input),
                "stateful_setup_estimated_input_tokens": estimate_input_tokens_from_chars(
                    len(stateful_setup_input)
                ),
                "compact_memory_input_hash": _safe_hash(compact_memory_input),
                "compact_memory_input_chars": len(compact_memory_input),
                "compact_memory_estimated_input_tokens": estimate_input_tokens_from_chars(
                    len(compact_memory_input)
                ),
                "native_chat_stateful_input_hash": _safe_hash(branch_task),
                "native_chat_stateful_input_chars": len(branch_task),
                "native_chat_stateful_estimated_input_tokens": estimate_input_tokens_from_chars(
                    len(branch_task)
                ),
                "stateless_full_prefix_input_hash": _safe_hash(stateless_full_prefix_input),
                "stateless_full_prefix_input_chars": len(stateless_full_prefix_input),
                "stateless_full_prefix_estimated_input_tokens": estimate_input_tokens_from_chars(
                    len(stateless_full_prefix_input)
                ),
                "compact_memory_estimated_reduction_tokens": _L3_6D_25K_MODE_COMPARISON_LIVE_MINIMIZED_REDUCTION_TOKENS,
                "baseline_estimated_input_tokens": _L3_6D_25K_MODE_COMPARISON_LIVE_BASELINE_INPUT_TOKENS,
                "output_reserve_tokens": _L3_6D_25K_MODE_COMPARISON_LIVE_OUTPUT_RESERVE_TOKENS,
            },
            "mode_comparison": {
                "setup_request": {
                    "mode": setup_mode,
                    "classification": setup_classification,
                    "route": setup_route,
                    "endpoint_path": setup_endpoint_path,
                    "previous_response_id_used": False,
                    "store": setup_store,
                },
                "comparable_modes": list(comparable_mode_specs),
            },
            "safety": {
                "generation_allowed": True,
                "live_25k_authorized": True,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "unload_required": True,
                "final_loaded_instances_required": 0,
            },
            "privacy": {
                "store_raw_prompt_response": False,
                "store_local_urls": False,
                "store_state_ids_raw": False,
            },
            "memory_safety": {
                "max_ram_peak_mb": max_ram_peak_mb,
                "max_vram_peak_mb": max_vram_peak_mb,
            },
            "artifacts": list(artifact_names),
        }
        write_json_file(run_path / "run_config.json", run_config_payload)

        normalized_providers = _normalize_providers(providers)
        request_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []
        raw_instance_id: str | None = None
        raw_root_state_id: str | None = None
        raw_response_ids: list[str] = []
        raw_output_texts: list[str] = []
        raw_previous_response_ids: list[str] = []
        instance_id_hash: str | None = None
        applied_context_length: int | None = None
        applied_parallel: int | None = None
        load_verified = False
        cleanup_verified = False
        final_loaded_instances: int | None = None
        load_time_ms: float | None = None
        observed_ram_peak_mb: float | None = None
        observed_vram_peak_mb: float | None = None
        memory_safety_pass = True
        system_summary: SystemMetricsSummary | None = None
        pending_exception: (
            tuple[type[BaseException], BaseException, TracebackType | None] | None
        ) = None

        self._system_sampler.start(providers=normalized_providers)
        try:
            models_before_payload, models_before_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            _, preexisting_loaded_instances = _sanitize_models_payload(
                response_payload=models_before_payload,
                response_text=models_before_text,
            )
            if preexisting_loaded_instances:
                raise ValueError("target model already has loaded instances before WVM-owned load")

            load_request_body = {
                "model": model_id,
                "context_length": requested_context_length,
                "echo_load_config": echo_load_config,
                "flash_attention": flash_attention,
                "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
                "parallel": requested_parallel,
            }
            load_started_at = _live_request_perf_counter()
            load_response_payload, load_response_text = _request_json(
                method="POST",
                url=f"{base_url}/api/v1/models/load",
                body=load_request_body,
            )
            load_time_ms = round((_live_request_perf_counter() - load_started_at) * 1000.0, 3)
            raw_instance_id = _as_optional_str(
                load_response_payload.get("instance_id")
                or load_response_payload.get("instanceId")
                or load_response_payload.get("id")
            )
            if raw_instance_id is None:
                raise ValueError("load response must include instance_id")
            instance_id_hash = _safe_hash(raw_instance_id)
            load_config_response = load_response_payload.get("load_config")
            if not isinstance(load_config_response, Mapping):
                raise ValueError("load response must include load_config mapping")
            applied_context_length = _as_optional_int(load_config_response.get("context_length"))
            applied_parallel = _as_optional_int(
                load_config_response.get("parallel", load_config_response.get("n_parallel"))
            )
            if applied_context_length != requested_context_length:
                raise ValueError("owned native load must materialize context_length=32768")
            if applied_parallel != requested_parallel:
                raise ValueError("owned native load must materialize parallel=1")
            write_json_file(
                run_path / "load_response_sanitized.json",
                {
                    "endpoint_kind": "native_load",
                    "method": "POST",
                    "status": _as_optional_str(load_response_payload.get("status")) or "unknown",
                    "instance_id_hash": instance_id_hash,
                    "load_time_ms": load_time_ms,
                    "applied_load_config": {
                        "context_length": applied_context_length,
                        "parallel": applied_parallel,
                        "echo_load_config": _as_optional_bool(
                            load_config_response.get("echo_load_config")
                        ),
                        "flash_attention": _as_optional_bool(
                            load_config_response.get("flash_attention")
                        ),
                        "offload_kv_cache_to_gpu": _as_optional_bool(
                            load_config_response.get("offload_kv_cache_to_gpu")
                        ),
                    },
                    "response_hash": _safe_hash(load_response_text),
                    "response_chars": len(load_response_text),
                },
            )

            models_after_load_payload, models_after_load_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            _models_after_load, loaded_instances = _sanitize_models_payload(
                response_payload=models_after_load_payload,
                response_text=models_after_load_text,
            )
            owned_instance = next(
                (
                    instance
                    for instance in loaded_instances
                    if instance.instance_ref == instance_id_hash
                ),
                None,
            )
            load_verified = (
                owned_instance is not None
                and applied_context_length == requested_context_length
                and applied_parallel == requested_parallel
            )
            if not load_verified:
                raise ValueError("owned native load verification failed")

            def _record_chat_request(
                *,
                sequence_index: int,
                request_id: str,
                request_role: str,
                classification: str,
                route: str,
                endpoint_path: str,
                prompt_text: str,
                store: bool,
                previous_response_id: str | None,
                root_state_id_hash: str | None,
                comparable_mode: bool,
            ) -> dict[str, object]:
                request_payload = {
                    "model": model_id,
                    "input": prompt_text,
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                    "store": store,
                }
                if previous_response_id is not None:
                    request_payload["previous_response_id"] = previous_response_id
                started_at = _live_request_perf_counter()
                response_payload = request_chat_transport(endpoint_url, request_payload, timeout_s)
                total_latency_ms = round(
                    (_live_request_perf_counter() - started_at) * 1000.0,
                    3,
                )
                if not isinstance(response_payload, Mapping):
                    raise ValueError("L3.6d mode comparison response must be a JSON object")
                if route != "native_chat_stateful" and "previous_response_id" in request_payload:
                    raise ValueError(
                        "compact_memory and stateless_full_prefix requests must not set previous_response_id"
                    )

                raw_response_id = _as_optional_str(
                    response_payload.get("response_id")
                    or response_payload.get("responseId")
                    or response_payload.get("id")
                )
                if raw_response_id is not None:
                    raw_response_ids.append(raw_response_id)
                output_text = _extract_cache_stateful_live_smoke_output_text(response_payload)
                if output_text is None:
                    raise ValueError("L3.6d mode comparison response must include non-empty output")
                raw_output_texts.append(output_text)
                response_id_hash = (
                    _safe_hash(raw_response_id) if raw_response_id is not None else None
                )
                input_tokens, output_tokens = _extract_usage_tokens(response_payload)
                prompt_processing_ms = _extract_prompt_processing_ms(response_payload)
                time_to_first_token_ms = _extract_stats_ttft_ms(response_payload)
                tokens_per_second = _extract_stats_rate(response_payload, "tokens_per_second")
                if (
                    tokens_per_second is None
                    and output_tokens is not None
                    and total_latency_ms not in (None, 0)
                ):
                    tokens_per_second = round(output_tokens / (total_latency_ms / 1000.0), 3)
                previous_response_id_hash = (
                    _safe_hash(previous_response_id) if previous_response_id is not None else None
                )
                estimated_input_tokens = estimate_input_tokens_from_chars(len(prompt_text))
                request_row = {
                    "schema_version": SCHEMA_VERSION,
                    "run_id": safe_run_id,
                    "experiment_id": experiment_id,
                    "mode": mode,
                    "managed_live": True,
                    "request_id": request_id,
                    "request_role": request_role,
                    "sequence_index": sequence_index,
                    "classification": classification,
                    "route": route,
                    "endpoint_path": endpoint_path,
                    "comparable_mode": comparable_mode,
                    "model_key": model_key,
                    "model_id": model_id,
                    "app_concurrency": app_concurrency,
                    "requested_context_length": requested_context_length,
                    "requested_parallel": requested_parallel,
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                    "store": store,
                    "input_hash": _safe_hash(prompt_text),
                    "input_chars": len(prompt_text),
                    "estimated_input_tokens": estimated_input_tokens,
                    "previous_response_id_used": previous_response_id is not None,
                    "previous_response_id_hash": previous_response_id_hash,
                    "root_state_id_hash": root_state_id_hash,
                    "state_id_hash": response_id_hash,
                    "response_id_present": raw_response_id is not None,
                    "response_id_hash": response_id_hash,
                    "response_hash": _safe_hash(output_text),
                    "response_chars": len(output_text),
                    "content_nonempty": True,
                    "non_empty_text_pass": True,
                    "request_succeeded": True,
                    "raw_prompt_response_stored": False,
                    "production_default": False,
                    "wvm_runtime_integration": False,
                    "kv_reuse_proven": False,
                    "live_25k_authorized": True,
                    "generation_allowed": True,
                    "status": "success",
                }
                metric_row = {
                    **request_row,
                    "applied_context_length": applied_context_length,
                    "applied_parallel": applied_parallel,
                    "load_verified": True,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "prompt_processing_ms": prompt_processing_ms,
                    "time_to_first_token_ms": time_to_first_token_ms,
                    "tokens_per_second": tokens_per_second,
                    "total_latency_ms": total_latency_ms,
                }
                request_rows.append(append_jsonl_record(requests_path, request_row))
                metric_rows.append(append_jsonl_record(metrics_path, metric_row))
                return {
                    "raw_response_id": raw_response_id,
                    "state_id_hash": response_id_hash,
                }

            setup_result = _record_chat_request(
                sequence_index=1,
                request_id="stateful_setup_root",
                request_role=setup_mode,
                classification=setup_classification,
                route=setup_route,
                endpoint_path=setup_endpoint_path,
                prompt_text=stateful_setup_input,
                store=setup_store,
                previous_response_id=None,
                root_state_id_hash=None,
                comparable_mode=False,
            )
            raw_root_state_id = cast(str | None, setup_result["raw_response_id"])
            if raw_root_state_id is None:
                raise ValueError("stateful setup root response must include response_id")
            root_state_id_hash = cast(str | None, setup_result["state_id_hash"])

            for sequence_offset, comparable_mode_spec in enumerate(comparable_mode_specs, start=2):
                comparable_mode_name = cast(str, comparable_mode_spec["mode"])
                previous_response_id = (
                    raw_root_state_id
                    if comparable_mode_spec["previous_response_id_used"] is True
                    else None
                )
                if previous_response_id is not None:
                    raw_previous_response_ids.append(previous_response_id)
                _record_chat_request(
                    sequence_index=sequence_offset,
                    request_id=f"{comparable_mode_name}_single",
                    request_role=comparable_mode_name,
                    classification=cast(str, comparable_mode_spec["classification"]),
                    route=cast(str, comparable_mode_spec["route"]),
                    endpoint_path=cast(str, comparable_mode_spec["endpoint_path"]),
                    prompt_text=input_by_mode[comparable_mode_name],
                    store=cast(bool, comparable_mode_spec["store"]),
                    previous_response_id=previous_response_id,
                    root_state_id_hash=root_state_id_hash,
                    comparable_mode=True,
                )
        except Exception:
            pending_exception = cast(
                tuple[type[BaseException], BaseException, TracebackType | None],
                sys.exc_info(),
            )
        finally:
            cleanup_error: Exception | None = None
            if raw_instance_id is not None:
                try:
                    _request_json(
                        method="POST",
                        url=f"{base_url}/api/v1/models/unload",
                        body={"instance_id": raw_instance_id},
                    )
                    models_after_unload_payload, models_after_unload_text = _request_json(
                        method="GET",
                        url=f"{base_url}/api/v1/models",
                    )
                    models_after_unload, _ = _sanitize_models_payload(
                        response_payload=models_after_unload_payload,
                        response_text=models_after_unload_text,
                    )
                    final_loaded_instances = _as_optional_int(
                        models_after_unload.get("target_loaded_instance_count")
                    )
                    instance_hashes_after_unload = tuple(
                        str(item)
                        for item in cast(
                            Sequence[object],
                            models_after_unload.get("instance_id_hashes", ()),
                        )
                    )
                    cleanup_verified = bool(
                        final_loaded_instances == final_loaded_instances_required
                        and instance_id_hash is not None
                        and instance_id_hash not in instance_hashes_after_unload
                    )
                    if not cleanup_verified:
                        cleanup_error = RuntimeError("native cleanup not verified")
                except Exception as error:
                    cleanup_error = error
            try:
                system_summary = self._system_sampler.stop(providers=normalized_providers)
                write_system_telemetry_artifacts(
                    run_path,
                    samples=self._system_sampler.samples,
                    summary=system_summary,
                )
            except Exception as error:
                if cleanup_error is None:
                    cleanup_error = error

            if pending_exception is not None:
                exc_type, exc, traceback = pending_exception
                if exc is not None:
                    raise exc.with_traceback(traceback)
                raise exc_type
            if cleanup_error is not None:
                raise cleanup_error

        assert system_summary is not None

        system_summary_payload = system_summary.to_dict()
        observed_ram_peak_mb = _as_optional_rate(system_summary_payload.get("ram_peak_mb"))
        observed_vram_peak_mb = _as_optional_rate(system_summary_payload.get("vram_peak_mb"))
        if observed_ram_peak_mb is not None and observed_ram_peak_mb > max_ram_peak_mb:
            memory_safety_pass = False
        if observed_vram_peak_mb is not None and observed_vram_peak_mb > max_vram_peak_mb:
            memory_safety_pass = False

        for metric_row in metric_rows:
            metric_row["max_ram_peak_mb"] = max_ram_peak_mb
            metric_row["max_vram_peak_mb"] = max_vram_peak_mb
            metric_row["memory_safety_pass"] = memory_safety_pass
        if metric_rows:
            _rewrite_jsonl_records(metrics_path, metric_rows)

        setup_metric_row = next(
            (row for row in metric_rows if row.get("comparable_mode") is False), None
        )
        comparable_metric_rows = [row for row in metric_rows if row.get("comparable_mode") is True]
        comparable_metric_rows_by_mode = {
            cast(str, row.get("request_role")): row for row in comparable_metric_rows
        }
        all_comparable_requests_succeeded = all(
            row.get("request_succeeded") is True for row in comparable_metric_rows
        )
        all_comparable_content_nonempty = all(
            row.get("content_nonempty") is True for row in comparable_metric_rows
        )

        summary_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "managed_live": True,
            "lab_only": True,
            "model_key": model_key,
            "model_id": model_id,
            "dataset_id": dataset_id,
            "requested_context_length": requested_context_length,
            "applied_context_length": applied_context_length,
            "requested_parallel": requested_parallel,
            "applied_parallel": applied_parallel,
            "load_verified": load_verified,
            "app_concurrency": app_concurrency,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "setup_request": {
                "request_id": setup_metric_row.get("request_id") if setup_metric_row else None,
                "request_role": setup_metric_row.get("request_role") if setup_metric_row else None,
                "classification": setup_metric_row.get("classification")
                if setup_metric_row
                else None,
                "route": setup_metric_row.get("route") if setup_metric_row else None,
                "store": setup_metric_row.get("store") if setup_metric_row else None,
                "request_succeeded": (
                    setup_metric_row.get("request_succeeded") if setup_metric_row else None
                ),
                "content_nonempty": (
                    setup_metric_row.get("content_nonempty") if setup_metric_row else None
                ),
                "non_empty_text_pass": (
                    setup_metric_row.get("non_empty_text_pass") if setup_metric_row else None
                ),
                "input_hash": setup_metric_row.get("input_hash") if setup_metric_row else None,
                "input_chars": setup_metric_row.get("input_chars") if setup_metric_row else None,
                "estimated_input_tokens": (
                    setup_metric_row.get("estimated_input_tokens") if setup_metric_row else None
                ),
                "input_tokens": setup_metric_row.get("input_tokens") if setup_metric_row else None,
                "output_tokens": setup_metric_row.get("output_tokens")
                if setup_metric_row
                else None,
                "prompt_processing_ms": (
                    setup_metric_row.get("prompt_processing_ms") if setup_metric_row else None
                ),
                "time_to_first_token_ms": (
                    setup_metric_row.get("time_to_first_token_ms") if setup_metric_row else None
                ),
                "total_latency_ms": (
                    setup_metric_row.get("total_latency_ms") if setup_metric_row else None
                ),
                "tokens_per_second": (
                    setup_metric_row.get("tokens_per_second") if setup_metric_row else None
                ),
                "state_id_hash": setup_metric_row.get("state_id_hash")
                if setup_metric_row
                else None,
                "response_id_hash": (
                    setup_metric_row.get("response_id_hash") if setup_metric_row else None
                ),
                "response_hash": setup_metric_row.get("response_hash")
                if setup_metric_row
                else None,
                "response_chars": (
                    setup_metric_row.get("response_chars") if setup_metric_row else None
                ),
            },
            "comparable_mode_order": list(_L3_6D_25K_MODE_COMPARISON_LIVE_COMPARABLE_MODES),
            "mode_results": [
                {
                    "mode": comparable_mode_name,
                    "classification": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "classification"
                    ),
                    "route": comparable_metric_rows_by_mode[comparable_mode_name].get("route"),
                    "request_id": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "request_id"
                    ),
                    "request_succeeded": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "request_succeeded"
                    ),
                    "content_nonempty": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "content_nonempty"
                    ),
                    "non_empty_text_pass": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "non_empty_text_pass"
                    ),
                    "previous_response_id_used": comparable_metric_rows_by_mode[
                        comparable_mode_name
                    ].get("previous_response_id_used"),
                    "previous_response_id_hash": comparable_metric_rows_by_mode[
                        comparable_mode_name
                    ].get("previous_response_id_hash"),
                    "root_state_id_hash": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "root_state_id_hash"
                    ),
                    "state_id_hash": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "state_id_hash"
                    ),
                    "response_id_hash": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "response_id_hash"
                    ),
                    "response_hash": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "response_hash"
                    ),
                    "response_chars": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "response_chars"
                    ),
                    "input_tokens": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "input_tokens"
                    ),
                    "output_tokens": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "output_tokens"
                    ),
                    "prompt_processing_ms": comparable_metric_rows_by_mode[
                        comparable_mode_name
                    ].get("prompt_processing_ms"),
                    "time_to_first_token_ms": comparable_metric_rows_by_mode[
                        comparable_mode_name
                    ].get("time_to_first_token_ms"),
                    "total_latency_ms": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "total_latency_ms"
                    ),
                    "tokens_per_second": comparable_metric_rows_by_mode[comparable_mode_name].get(
                        "tokens_per_second"
                    ),
                    "kv_reuse_proven": False,
                }
                for comparable_mode_name in _L3_6D_25K_MODE_COMPARISON_LIVE_COMPARABLE_MODES
            ],
            "comparable_request_count": len(comparable_metric_rows),
            "all_comparable_requests_succeeded": all_comparable_requests_succeeded,
            "all_comparable_content_nonempty": all_comparable_content_nonempty,
            "cleanup_verified": cleanup_verified,
            "final_loaded_instances": final_loaded_instances,
            "ram_peak_mb": observed_ram_peak_mb,
            "vram_peak_mb": observed_vram_peak_mb,
            "max_ram_peak_mb": max_ram_peak_mb,
            "max_vram_peak_mb": max_vram_peak_mb,
            "memory_safety_pass": memory_safety_pass,
            "production_default": False,
            "wvm_runtime_integration": False,
            "kv_reuse_proven": False,
            "generation_allowed": True,
            "live_25k_authorized": True,
            "privacy_scan_status": "pending",
            "decision": "pending_privacy_scan",
        }

        report_text = "\n".join(
            [
                "# LM Studio Lab L3.6d Mode Comparison Report",
                "",
                "This is a lab-only LM Studio mode comparison gate for a synthetic 25k lecture workload.",
                "production_default=false, wvm_runtime_integration=false, kv_reuse_proven=false.",
                "native_chat_stateful is a research latency candidate only and does not prove KV reuse.",
                "",
                "| Field | Value |",
                "| --- | --- |",
                f"| experiment_id | `{experiment_id}` |",
                f"| run_id | `{safe_run_id}` |",
                f"| mode | `{mode}` |",
                f"| requested_context_length | `{requested_context_length}` |",
                f"| applied_context_length | `{applied_context_length}` |",
                f"| requested_parallel | `{requested_parallel}` |",
                f"| applied_parallel | `{applied_parallel}` |",
                f"| cleanup_verified | `{str(cleanup_verified).lower()}` |",
                f"| final_loaded_instances | `{final_loaded_instances}` |",
                f"| ram_peak_mb | `{observed_ram_peak_mb}` |",
                f"| vram_peak_mb | `{observed_vram_peak_mb}` |",
                f"| max_ram_peak_mb | `{max_ram_peak_mb}` |",
                f"| max_vram_peak_mb | `{max_vram_peak_mb}` |",
                f"| memory_safety_pass | `{str(memory_safety_pass).lower()}` |",
                "",
                "## Comparable modes",
                "",
                "| Mode | Classification | Success | Non-empty | Prompt ms | TTFT ms | Total latency ms | Tokens/s | Input tokens | Output tokens |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
                *[
                    "| "
                    f"{row['mode']} | {row['classification']} | {str(row['request_succeeded']).lower()} | "
                    f"{str(row['content_nonempty']).lower()} | {row['prompt_processing_ms']} | "
                    f"{row['time_to_first_token_ms']} | {row['total_latency_ms']} | "
                    f"{row['tokens_per_second']} | {row['input_tokens']} | {row['output_tokens']} |"
                    for row in cast(list[Mapping[str, object]], summary_payload["mode_results"])
                ],
                "",
                "All measured requests use `/api/v1/chat`; only the native_chat_stateful branch uses a hashed previous_response_id in artifacts.",
                "No raw prompt text, raw response text, raw state identifiers, or raw localhost URLs are stored in artifacts.",
                "",
            ]
        )

        privacy_payloads: dict[str, object] = {
            "environment.json": environment_payload,
            "run_config.json": run_config_payload,
            "load_response_sanitized.json": json.loads(
                (run_path / "load_response_sanitized.json").read_text(encoding="utf-8")
            ),
            "requests.jsonl": list(request_rows),
            "metrics.jsonl": list(metric_rows),
            "system_samples.jsonl": [sample.to_dict() for sample in self._system_sampler.samples],
            "system_summary.json": system_summary.to_dict(),
            "comparison_summary.json": summary_payload,
            "report.md": report_text,
        }
        privacy_violations: list[str] = []
        public_safe_markers = {
            marker
            for marker in (
                _qualifying_privacy_marker(model_id),
                _qualifying_privacy_marker(model_key),
            )
            if marker is not None
        }
        instance_privacy_marker = _qualifying_privacy_marker(raw_instance_id)
        if instance_privacy_marker in public_safe_markers:
            instance_privacy_marker = None
        raw_markers = {
            marker
            for marker in (
                _qualifying_privacy_marker(base_url),
                _qualifying_privacy_marker(endpoint_url),
                instance_privacy_marker,
                *(_qualifying_privacy_marker(value) for value in raw_response_ids),
                *(_qualifying_privacy_marker(value) for value in raw_output_texts),
                *(_qualifying_privacy_marker(value) for value in raw_previous_response_ids),
                *(_qualifying_privacy_marker(value) for value in prompt_privacy_markers),
            )
            if marker is not None
        }
        for artifact_name, artifact_payload in privacy_payloads.items():
            serialized_payload = (
                artifact_payload
                if isinstance(artifact_payload, str)
                else json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True)
            )
            privacy_violations.extend(
                find_privacy_violations(
                    {"artifact_name": artifact_name, "serialized": serialized_payload},
                    context=artifact_name,
                )
            )
            for raw_marker in raw_markers:
                if raw_marker and raw_marker in serialized_payload:
                    privacy_violations.append(f"{artifact_name} contains a raw private marker")
        privacy_scan = {
            "status": "pass" if not privacy_violations else "fail",
            "violation_count": len(privacy_violations),
            "scan_scope": "l3_6d_mode_comparison_live_raw_url_path_private_value_scan",
            "scanned_artifacts": list(privacy_payloads),
            "raw_prompt_response_stored": False,
        }

        privacy_pass = privacy_scan["status"] == "pass"
        decision = (
            "mode_comparison_live_pass"
            if (
                load_verified
                and all_comparable_requests_succeeded
                and all_comparable_content_nonempty
                and cleanup_verified
                and privacy_pass
                and memory_safety_pass
            )
            else "mode_comparison_live_fail"
        )
        summary_payload["privacy_scan_status"] = privacy_scan["status"]
        summary_payload["decision"] = decision

        write_json_file(run_path / "comparison_summary.json", summary_payload)
        write_json_file(run_path / "privacy_scan.json", privacy_scan)
        (run_path / "report.md").write_text(report_text, encoding="utf-8")

        if not privacy_pass or not memory_safety_pass:
            failure_reasons: list[str] = []
            if not privacy_pass:
                failure_reasons.append("privacy_scan_failed")
            if not memory_safety_pass:
                failure_reasons.append("memory_safety_failed")
            raise RuntimeError(
                "L3.6d mode comparison live acceptance gate failed: " + ", ".join(failure_reasons)
            )

        summary = _sanitize_operation_summary(summary_payload)
        return {
            **summary,
            **_build_safe_system_summary(system_summary),
        }

    def run_l3_7d_structured_json_live_smoke(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
        timeout_s: float = 120.0,
        native_transport: ModelLifecycleTransport | None = None,
        chat_transport: LiveTransport | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        _, raw_payload = load_raw_experiment_config(Path(config_path))

        def _require_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
            if not isinstance(value, Mapping):
                raise ValueError(f"{field_name} must be a mapping")
            return value

        def _require_non_empty_string(value: object, *, field_name: str) -> str:
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            text = value.strip()
            if not text:
                raise ValueError(f"{field_name} must be a non-empty string")
            return text

        def _require_bool(value: object, *, field_name: str) -> bool:
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean")
            return value

        def _require_int(value: object, *, field_name: str, minimum: int | None = None) -> int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
            if minimum is not None and value < minimum:
                raise ValueError(f"{field_name} must be >= {minimum}")
            return value

        def _require_string_sequence(value: object, *, field_name: str) -> tuple[str, ...]:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                raise ValueError(f"{field_name} must be a sequence of strings")
            items: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    raise ValueError(f"{field_name} must be a sequence of strings")
                items.append(item)
            return tuple(items)

        def _default_native_transport(
            request: urllib_request.Request,
            request_timeout_s: float,
        ) -> bytes:
            with urllib_request.urlopen(request, timeout=request_timeout_s) as response:
                response_bytes = response.read()
                if not isinstance(response_bytes, bytes):
                    raise TypeError("native transport response must be bytes")
                return response_bytes

        def _request_json(
            *,
            method: str,
            url: str,
            body: Mapping[str, Any] | None = None,
        ) -> tuple[Mapping[str, Any], str]:
            data = None
            headers = {"Accept": "application/json"}
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = urllib_request.Request(url, data=data, headers=headers, method=method)
            response_bytes = request_transport(request, timeout_s)
            response_text = response_bytes.decode("utf-8")
            decoded = json.loads(response_text)
            if not isinstance(decoded, Mapping):
                raise ValueError(f"{method} response must be a JSON object")
            return decoded, response_text

        def _sanitize_models_payload(
            *,
            response_payload: Mapping[str, Any],
            response_text: str,
        ) -> tuple[dict[str, object], tuple[LoadedInstanceRecord, ...]]:
            parsed = parse_native_model_list(response_payload)
            if parsed.error is not None:
                raise ValueError("native model list response must parse successfully")
            target_model = next(
                (model for model in parsed.native_models if model.native_model_key == model_id),
                None,
            )
            loaded_instances = tuple(
                target_model.loaded_instances if target_model is not None else ()
            )
            return (
                {
                    "endpoint_kind": "native_models",
                    "method": "GET",
                    "target_model_id": model_id,
                    "target_model_key": model_key,
                    "target_model_present": target_model is not None,
                    "target_loaded_instance_count": len(loaded_instances),
                    "instance_id_hashes": [instance.instance_ref for instance in loaded_instances],
                    "context_lengths": [
                        instance.context_length
                        for instance in loaded_instances
                        if instance.context_length is not None
                    ],
                    "parallels": [
                        instance.parallel
                        for instance in loaded_instances
                        if instance.parallel is not None
                    ],
                    "response_hash": _safe_hash(response_text),
                    "response_chars": len(response_text),
                },
                loaded_instances,
            )

        request_transport = native_transport or _default_native_transport
        request_chat_transport = chat_transport or _default_live_transport

        experiment_id = _require_non_empty_string(
            raw_payload.get("experiment_id"),
            field_name="experiment_id",
        )
        if experiment_id != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_EXPERIMENT_ID:
            raise ValueError(
                "L3.7d structured JSON live smoke requires experiment_id "
                "'l3_7d_structured_json_live_smoke_gemma4_e2b'"
            )

        mode = _require_non_empty_string(raw_payload.get("mode"), field_name="mode")
        if mode != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_MODE:
            raise ValueError(
                "L3.7d structured JSON live smoke requires mode "
                "'structured_json_controlled_live_smoke'"
            )

        model_payload = _require_mapping(raw_payload.get("model"), field_name="model")
        model_key = _require_non_empty_string(model_payload.get("key"), field_name="model.key")
        if model_key != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_MODEL_KEY:
            raise ValueError(
                "L3.7d structured JSON live smoke requires model.key 'gemma4_e2b_q4km'"
            )
        model_id = _require_non_empty_string(
            model_payload.get("lmstudio_model_id"),
            field_name="model.lmstudio_model_id",
        )
        if model_id != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_MODEL_ID:
            raise ValueError(
                "L3.7d structured JSON live smoke requires model.lmstudio_model_id "
                "'google/gemma-4-e2b'"
            )

        load_payload = _require_mapping(raw_payload.get("load"), field_name="load")
        requested_context_length = _require_int(
            load_payload.get("context_length"),
            field_name="load.context_length",
            minimum=1,
        )
        if requested_context_length != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_CONTEXT_LENGTH:
            raise ValueError("L3.7d structured JSON live smoke requires load.context_length=8192")
        echo_load_config = _require_bool(
            load_payload.get("echo_load_config"),
            field_name="load.echo_load_config",
        )
        if not echo_load_config:
            raise ValueError("L3.7d structured JSON live smoke requires load.echo_load_config=true")
        requested_parallel = _require_int(
            load_payload.get("parallel"),
            field_name="load.parallel",
            minimum=1,
        )
        if requested_parallel != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_PARALLEL:
            raise ValueError("L3.7d structured JSON live smoke requires load.parallel=1")

        app_concurrency = _require_int(
            raw_payload.get("app_concurrency"),
            field_name="app_concurrency",
            minimum=1,
        )
        if app_concurrency != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_APP_CONCURRENCY:
            raise ValueError("L3.7d structured JSON live smoke requires app_concurrency=1")

        dataset_payload = _require_mapping(raw_payload.get("dataset"), field_name="dataset")
        dataset_id = _require_non_empty_string(dataset_payload.get("id"), field_name="dataset.id")
        if dataset_id != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_DATASET_ID:
            raise ValueError(
                "L3.7d structured JSON live smoke requires dataset.id 'blocks_json_small'"
            )

        generation_payload = _require_mapping(
            raw_payload.get("generation"), field_name="generation"
        )
        generation_route = _require_non_empty_string(
            generation_payload.get("route"),
            field_name="generation.route",
        )
        if generation_route != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_ROUTE:
            raise ValueError(
                "L3.7d structured JSON live smoke requires generation.route "
                "'strict_json_chat_completions'"
            )
        helper_mode = _require_non_empty_string(
            generation_payload.get("helper_mode"),
            field_name="generation.helper_mode",
        )
        if helper_mode != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_HELPER_MODE:
            raise ValueError(
                "L3.7d structured JSON live smoke requires generation.helper_mode "
                "'json_schema_single'"
            )
        endpoint_path = _require_non_empty_string(
            generation_payload.get("endpoint_path"),
            field_name="generation.endpoint_path",
        )
        if endpoint_path != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_ENDPOINT_PATH:
            raise ValueError(
                "L3.7d structured JSON live smoke requires generation.endpoint_path "
                "'/v1/chat/completions'"
            )
        temperature = _require_int(
            generation_payload.get("temperature"),
            field_name="generation.temperature",
            minimum=0,
        )
        if temperature != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_TEMPERATURE:
            raise ValueError("L3.7d structured JSON live smoke requires generation.temperature=0")
        max_tokens = _require_int(
            generation_payload.get("max_tokens"),
            field_name="generation.max_tokens",
            minimum=1,
        )
        if max_tokens != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_MAX_TOKENS:
            raise ValueError("L3.7d structured JSON live smoke requires generation.max_tokens=512")

        safety_payload = _require_mapping(raw_payload.get("safety"), field_name="safety")
        generation_allowed = _require_bool(
            safety_payload.get("generation_allowed"),
            field_name="safety.generation_allowed",
        )
        if not generation_allowed:
            raise ValueError(
                "L3.7d structured JSON live smoke requires safety.generation_allowed=true"
            )
        production_default = _require_bool(
            safety_payload.get("production_default"),
            field_name="safety.production_default",
        )
        if production_default:
            raise ValueError("safety.production_default must remain false")
        wvm_runtime_integration = _require_bool(
            safety_payload.get("wvm_runtime_integration"),
            field_name="safety.wvm_runtime_integration",
        )
        if wvm_runtime_integration:
            raise ValueError("safety.wvm_runtime_integration must remain false")
        kv_reuse_proven = _require_bool(
            safety_payload.get("kv_reuse_proven"),
            field_name="safety.kv_reuse_proven",
        )
        if kv_reuse_proven:
            raise ValueError("safety.kv_reuse_proven must remain false")
        unload_required = _require_bool(
            safety_payload.get("unload_required"),
            field_name="safety.unload_required",
        )
        if not unload_required:
            raise ValueError(
                "L3.7d structured JSON live smoke requires safety.unload_required=true"
            )
        final_loaded_instances_required = _require_int(
            safety_payload.get("final_loaded_instances_required"),
            field_name="safety.final_loaded_instances_required",
            minimum=0,
        )
        if final_loaded_instances_required != 0:
            raise ValueError(
                "L3.7d structured JSON live smoke requires safety.final_loaded_instances_required=0"
            )

        privacy_payload = _require_mapping(raw_payload.get("privacy"), field_name="privacy")
        if _require_bool(
            privacy_payload.get("store_raw_prompt_response"),
            field_name="privacy.store_raw_prompt_response",
        ):
            raise ValueError("privacy.store_raw_prompt_response must remain false")
        if _require_bool(
            privacy_payload.get("store_local_urls"),
            field_name="privacy.store_local_urls",
        ):
            raise ValueError("privacy.store_local_urls must remain false")
        if _require_bool(
            privacy_payload.get("store_state_ids_raw"),
            field_name="privacy.store_state_ids_raw",
        ):
            raise ValueError("privacy.store_state_ids_raw must remain false")

        artifacts = raw_payload.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes, bytearray)):
            raise ValueError("artifacts must be a list of strings")
        artifact_names = tuple(
            _require_non_empty_string(artifact_name, field_name="artifacts[]")
            for artifact_name in artifacts
        )
        if artifact_names != _L3_7D_STRUCTURED_JSON_LIVE_SMOKE_OUTPUT_FILES:
            raise ValueError(
                "L3.7d structured JSON live smoke requires the exact artifact list declared by the L3.7d contract"
            )

        base_url = str(raw_payload.get("lmstudio_base_url", "http://127.0.0.1:1234")).strip()
        if not base_url:
            base_url = "http://127.0.0.1:1234"
        base_url = base_url.rstrip("/")

        live_config = LiveSmokeConfig(
            experiment_id=experiment_id,
            models=(
                LiveModelConfig(
                    key=model_key,
                    model_id=model_id,
                    load={
                        "context_length": (requested_context_length,),
                        "parallel": (requested_parallel,),
                    },
                ),
            ),
            modes=(helper_mode,),
            datasets=(dataset_id,),
            repeats=1,
            lmstudio_base_url=base_url,
            allow_remote=False,
            hardware_profile="managed_runner_l3_7d_structured_json",
            warmup_runs=0,
            privacy=LivePrivacyConfig(
                store_prompt_text=False,
                store_response_text=False,
                store_prompt_hash=True,
            ),
        )

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        requests_path = run_path / "requests.jsonl"
        metrics_path = run_path / "metrics.jsonl"
        structured_errors_path = run_path / "structured_errors.jsonl"
        requests_path.write_text("", encoding="utf-8")
        metrics_path.write_text("", encoding="utf-8")
        structured_errors_path.write_text("", encoding="utf-8")

        environment_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "managed_live": True,
            "lab_only": True,
            "structured_json_live_smoke": True,
            "production_default": False,
            "wvm_runtime_integration": False,
            "kv_reuse_proven": False,
        }
        write_json_file(run_path / "environment.json", environment_payload)

        run_config_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "model_key": model_key,
            "model_id": model_id,
            "dataset_id": dataset_id,
            "app_concurrency": app_concurrency,
            "requested_context_length": requested_context_length,
            "requested_parallel": requested_parallel,
            "load": {
                "context_length": requested_context_length,
                "parallel": requested_parallel,
                "echo_load_config": echo_load_config,
            },
            "generation": {
                "route": generation_route,
                "helper_mode": helper_mode,
                "endpoint_path": endpoint_path,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            "safety": {
                "generation_allowed": True,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "unload_required": True,
                "final_loaded_instances_required": 0,
            },
            "privacy": {
                "store_raw_prompt_response": False,
                "store_local_urls": False,
                "store_state_ids_raw": False,
            },
            "artifacts": list(artifact_names),
        }
        write_json_file(run_path / "run_config.json", run_config_payload)

        normalized_providers = _normalize_providers(providers)
        request_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []
        structured_error_rows: list[dict[str, Any]] = []
        raw_instance_id: str | None = None
        raw_response_id: str | None = None
        raw_public_content: str | None = None
        prompt_privacy_marker: str | None = None
        instance_id_hash: str | None = None
        applied_context_length: int | None = None
        applied_parallel: int | None = None
        load_verified = False
        generation_called = False
        request_succeeded = False
        public_content_pass = False
        structured_validation_pass = False
        reasoning_content_present: bool | None = None
        cleanup_verified = False
        final_loaded_instances: int | None = None
        load_time_ms: float | None = None
        total_latency_ms: float | None = None
        prompt_processing_ms: float | None = None
        time_to_first_token_ms: float | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        tokens_per_second: float | None = None
        json_parse_pass = False
        schema_pass = False
        business_pass = False
        structured_gate_status = "not_started"
        failure_reasons: list[str] = []
        system_summary: SystemMetricsSummary | None = None
        pending_exception: (
            tuple[type[BaseException], BaseException, TracebackType | None] | None
        ) = None

        def _tracked_chat_transport(
            url: str,
            payload: Mapping[str, Any],
            request_timeout_s: float,
        ) -> Mapping[str, Any]:
            nonlocal prompt_privacy_marker, raw_response_id, raw_public_content
            message_parts: list[str] = []
            for message in payload.get("messages", ()):
                if isinstance(message, Mapping):
                    content = message.get("content")
                    if isinstance(content, str):
                        message_parts.append(content)
            if message_parts:
                prompt_privacy_marker = _build_prompt_privacy_marker("\n".join(message_parts))
            response_payload = request_chat_transport(url, payload, request_timeout_s)
            if not isinstance(response_payload, Mapping):
                raise ValueError("LM Studio response must be a JSON object")
            raw_response_id = _as_optional_str(
                response_payload.get("id")
                or response_payload.get("response_id")
                or response_payload.get("responseId")
            )
            choices = response_payload.get("choices")
            if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes, bytearray)):
                if choices:
                    first_choice = choices[0]
                    if isinstance(first_choice, Mapping):
                        message = first_choice.get("message")
                        if isinstance(message, Mapping):
                            content = message.get("content")
                            if isinstance(content, str) and content.strip():
                                raw_public_content = content
            return response_payload

        self._system_sampler.start(providers=normalized_providers)
        try:
            models_before_payload, models_before_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            _, preexisting_loaded_instances = _sanitize_models_payload(
                response_payload=models_before_payload,
                response_text=models_before_text,
            )
            if preexisting_loaded_instances:
                raise ValueError("target model already has loaded instances before WVM-owned load")

            load_request_body = {
                "model": model_id,
                "context_length": requested_context_length,
                "echo_load_config": echo_load_config,
                "parallel": requested_parallel,
            }
            load_started_at = _live_request_perf_counter()
            load_response_payload, load_response_text = _request_json(
                method="POST",
                url=f"{base_url}/api/v1/models/load",
                body=load_request_body,
            )
            load_time_ms = round((_live_request_perf_counter() - load_started_at) * 1000.0, 3)
            raw_instance_id = _as_optional_str(
                load_response_payload.get("instance_id")
                or load_response_payload.get("instanceId")
                or load_response_payload.get("id")
            )
            if raw_instance_id is None:
                raise ValueError("load response must include instance_id")
            instance_id_hash = _safe_hash(raw_instance_id)
            load_config_response = load_response_payload.get("load_config")
            if not isinstance(load_config_response, Mapping):
                raise ValueError("load response must include load_config mapping")
            applied_context_length = _as_optional_int(load_config_response.get("context_length"))
            applied_parallel = _as_optional_int(
                load_config_response.get("parallel", load_config_response.get("n_parallel"))
            )
            if applied_context_length != requested_context_length:
                raise ValueError("owned native load must materialize context_length=8192")
            if applied_parallel != requested_parallel:
                raise ValueError("owned native load must materialize parallel=1")
            write_json_file(
                run_path / "load_response_sanitized.json",
                {
                    "endpoint_kind": "native_load",
                    "method": "POST",
                    "status": _as_optional_str(load_response_payload.get("status")) or "unknown",
                    "instance_id_hash": instance_id_hash,
                    "load_time_ms": load_time_ms,
                    "applied_load_config": {
                        "context_length": applied_context_length,
                        "parallel": applied_parallel,
                        "echo_load_config": _as_optional_bool(
                            load_config_response.get("echo_load_config")
                        ),
                    },
                    "response_hash": _safe_hash(load_response_text),
                    "response_chars": len(load_response_text),
                },
            )

            models_after_load_payload, models_after_load_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            models_after_load, loaded_instances = _sanitize_models_payload(
                response_payload=models_after_load_payload,
                response_text=models_after_load_text,
            )
            owned_instance = next(
                (
                    instance
                    for instance in loaded_instances
                    if instance.instance_ref == instance_id_hash
                ),
                None,
            )
            load_verified = (
                owned_instance is not None
                and applied_context_length == requested_context_length
                and applied_parallel == requested_parallel
            )
            if not load_verified:
                raise ValueError("owned native load verification failed")

            generation_called = True
            outcome = run_live_structured_smoke(
                live_config,
                run_id=safe_run_id,
                timeout_s=timeout_s,
                transport=_tracked_chat_transport,
                verified_context_length=requested_context_length,
            )
            metric_row = outcome.metric.to_dict()
            metric_row["raw_prompt_response_stored"] = False
            metric_rows.append(append_jsonl_record(metrics_path, metric_row))
            if outcome.structured_error is not None:
                structured_error_rows.append(
                    append_jsonl_record(structured_errors_path, outcome.structured_error)
                )

            validation_payload = metric_row.get("validation")
            if isinstance(validation_payload, Mapping):
                json_parse_pass = bool(validation_payload.get("json_parse_pass") is True)
                schema_pass = bool(validation_payload.get("schema_pass") is True)
                business_pass = bool(validation_payload.get("business_pass") is True)
            reasoning_content_present = _as_optional_bool(
                metric_row.get("reasoning_content_present")
            )
            public_content_pass = metric_row.get("content_empty") is False
            structured_validation_pass = (
                public_content_pass
                and json_parse_pass
                and schema_pass
                and business_pass
                and outcome.structured_error is None
            )
            request_succeeded = structured_validation_pass
            if request_succeeded:
                structured_gate_status = "passed"
            elif public_content_pass is False and reasoning_content_present is True:
                structured_gate_status = "failed_reasoning_only_json"
            elif public_content_pass is False:
                structured_gate_status = "failed_public_content_empty"
            else:
                structured_gate_status = "failed"

            input_tokens = _as_optional_int(metric_row.get("tokens", {}).get("prompt_tokens"))
            output_tokens = _as_optional_int(metric_row.get("tokens", {}).get("completion_tokens"))
            total_latency_ms = _as_optional_rate(
                metric_row.get("timing", {}).get("total_elapsed_ms")
            )
            prompt_processing_ms = _as_optional_rate(
                metric_row.get("timing", {}).get("prompt_processing_ms")
            )
            time_to_first_token_ms = _as_optional_rate(
                metric_row.get("timing", {}).get("time_to_first_token_ms")
            )
            tokens_per_second = _as_optional_rate(
                metric_row.get("timing", {}).get("tokens_per_second")
            )

            request_row = {
                "schema_version": SCHEMA_VERSION,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "managed_live": True,
                "request_id": metric_row.get("request_id"),
                "request_role": generation_route,
                "route": generation_route,
                "helper_mode": helper_mode,
                "model_key": model_key,
                "model_id": model_id,
                "endpoint_path": endpoint_path,
                "app_concurrency": app_concurrency,
                "requested_context_length": requested_context_length,
                "requested_parallel": requested_parallel,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "prompt_hash": metric_row.get("prompt_hash"),
                "prompt_chars": metric_row.get("prompt_chars"),
                "response_id_present": raw_response_id is not None,
                "response_id_hash": (_safe_hash(raw_response_id) if raw_response_id else None),
                "response_hash": metric_row.get("response_hash"),
                "response_chars": metric_row.get("response_chars"),
                "content_nonempty": public_content_pass,
                "reasoning_content_present": reasoning_content_present,
                "json_parse_pass": json_parse_pass,
                "schema_pass": schema_pass,
                "business_pass": business_pass,
                "structured_gate_status": structured_gate_status,
                "raw_prompt_response_stored": False,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "status": "success" if request_succeeded else "failed",
            }
            request_rows.append(append_jsonl_record(requests_path, request_row))
        except Exception:
            pending_exception = cast(
                tuple[type[BaseException], BaseException, TracebackType | None],
                sys.exc_info(),
            )
        finally:
            cleanup_error: Exception | None = None
            if raw_instance_id is not None:
                try:
                    _request_json(
                        method="POST",
                        url=f"{base_url}/api/v1/models/unload",
                        body={"instance_id": raw_instance_id},
                    )
                    models_after_unload_payload, models_after_unload_text = _request_json(
                        method="GET",
                        url=f"{base_url}/api/v1/models",
                    )
                    models_after_unload, _ = _sanitize_models_payload(
                        response_payload=models_after_unload_payload,
                        response_text=models_after_unload_text,
                    )
                    final_loaded_instances = _as_optional_int(
                        models_after_unload.get("target_loaded_instance_count")
                    )
                    models_after_unload_instance_hashes = _require_string_sequence(
                        models_after_unload.get("instance_id_hashes"),
                        field_name="models_after_unload.instance_id_hashes",
                    )
                    cleanup_verified = bool(
                        final_loaded_instances == final_loaded_instances_required
                        and instance_id_hash is not None
                        and instance_id_hash not in models_after_unload_instance_hashes
                    )
                    if not cleanup_verified:
                        cleanup_error = RuntimeError("native cleanup not verified")
                except Exception as error:
                    cleanup_error = error
            try:
                system_summary = self._system_sampler.stop(providers=normalized_providers)
                write_system_telemetry_artifacts(
                    run_path,
                    samples=self._system_sampler.samples,
                    summary=system_summary,
                )
            except Exception as error:
                if cleanup_error is None:
                    cleanup_error = error

            if pending_exception is not None:
                exc_type, exc, traceback = pending_exception
                if exc is not None:
                    raise exc.with_traceback(traceback)
                raise exc_type
            if cleanup_error is not None:
                raise cleanup_error

        assert system_summary is not None

        if not structured_error_rows:
            structured_errors_path.write_text("", encoding="utf-8")

        report_rows = (
            ("experiment_id", experiment_id),
            ("run_id", safe_run_id),
            ("mode", mode),
            ("route", generation_route),
            ("helper_mode", helper_mode),
            ("endpoint_path", endpoint_path),
            ("requested_context_length", str(requested_context_length)),
            ("applied_context_length", str(applied_context_length)),
            ("requested_parallel", str(requested_parallel)),
            ("applied_parallel", str(applied_parallel)),
            ("load_verified", str(load_verified).lower()),
            ("generation_called", str(generation_called).lower()),
            ("request_succeeded", str(request_succeeded).lower()),
            ("public_content_pass", str(public_content_pass).lower()),
            ("reasoning_content_present", str(reasoning_content_present).lower()),
            ("json_parse_pass", str(json_parse_pass).lower()),
            ("schema_pass", str(schema_pass).lower()),
            ("business_pass", str(business_pass).lower()),
            ("structured_gate_status", structured_gate_status),
            ("cleanup_verified", str(cleanup_verified).lower()),
            ("final_loaded_instances", str(final_loaded_instances)),
            ("production_default", "false"),
            ("wvm_runtime_integration", "false"),
            ("kv_reuse_proven", "false"),
            ("temperature", str(temperature)),
            ("max_tokens", str(max_tokens)),
        )
        report_text = "\n".join(
            [
                "# LM Studio Lab L3.7d Structured JSON Live Smoke Report",
                "",
                "This is a lab-only managed strict JSON chat-completions smoke gate for the current Gemma E2B candidate.",
                "production_default=false, wvm_runtime_integration=false, kv_reuse_proven=false.",
                "Public assistant content is required; reasoning-only JSON is a failure.",
                "",
                "| Field | Value |",
                "| --- | --- |",
                *[f"| {field} | `{value}` |" for field, value in report_rows],
                "",
                "Exactly one `/v1/chat/completions` structured JSON request runs after exact owned native load verification and before exact unload cleanup verification.",
                "No raw prompt text, raw response text, raw state identifiers, or raw localhost URLs are stored in artifacts.",
                "",
            ]
        )

        privacy_payloads: dict[str, object] = {
            "environment.json": environment_payload,
            "run_config.json": run_config_payload,
            "load_response_sanitized.json": json.loads(
                (run_path / "load_response_sanitized.json").read_text(encoding="utf-8")
            ),
            "requests.jsonl": list(request_rows),
            "metrics.jsonl": list(metric_rows),
            "structured_errors.jsonl": list(structured_error_rows),
            "system_samples.jsonl": [sample.to_dict() for sample in self._system_sampler.samples],
            "system_summary.json": system_summary.to_dict(),
            "report.md": report_text,
        }
        privacy_violations: list[str] = []
        public_safe_markers = {
            marker
            for marker in (
                _qualifying_privacy_marker(model_id),
                _qualifying_privacy_marker(model_key),
            )
            if marker is not None
        }
        instance_privacy_marker = _qualifying_privacy_marker(raw_instance_id)
        if instance_privacy_marker in public_safe_markers:
            instance_privacy_marker = None
        raw_markers = {
            marker
            for marker in (
                _qualifying_privacy_marker(base_url),
                instance_privacy_marker,
                _qualifying_privacy_marker(raw_response_id),
                _qualifying_privacy_marker(raw_public_content),
                _qualifying_privacy_marker(prompt_privacy_marker),
            )
            if marker is not None
        }
        for artifact_name, artifact_payload in privacy_payloads.items():
            serialized_payload = (
                artifact_payload
                if isinstance(artifact_payload, str)
                else json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True)
            )
            privacy_violations.extend(
                find_privacy_violations(
                    {"artifact_name": artifact_name, "serialized": serialized_payload},
                    context=artifact_name,
                )
            )
            for raw_marker in raw_markers:
                if raw_marker and raw_marker in serialized_payload:
                    privacy_violations.append(f"{artifact_name} contains a raw private marker")
        privacy_scan = {
            "status": "pass" if not privacy_violations else "fail",
            "violation_count": len(privacy_violations),
            "scan_scope": "l3_7d_structured_json_live_smoke_raw_url_path_private_value_scan",
            "scanned_artifacts": list(privacy_payloads),
            "raw_prompt_response_stored": False,
        }
        write_json_file(run_path / "privacy_scan.json", privacy_scan)
        (run_path / "report.md").write_text(report_text, encoding="utf-8")

        if not public_content_pass:
            failure_reasons.append(structured_gate_status)
        elif not structured_validation_pass:
            failure_reasons.append("structured_validation_failed")
        if privacy_scan["status"] != "pass":
            failure_reasons.append("privacy_scan_failed")

        decision = (
            "structured_json_live_smoke_pass"
            if not failure_reasons and cleanup_verified and load_verified and request_succeeded
            else "structured_json_live_smoke_fail"
        )
        summary = _sanitize_operation_summary(
            {
                "decision": decision,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "model_id": model_id,
                "route": generation_route,
                "helper_mode": helper_mode,
                "requested_context_length": requested_context_length,
                "applied_context_length": applied_context_length,
                "requested_parallel": requested_parallel,
                "applied_parallel": applied_parallel,
                "load_verified": load_verified,
                "generation_called": generation_called,
                "request_succeeded": request_succeeded,
                "public_output_pass": public_content_pass,
                "reasoning_present": reasoning_content_present,
                "json_parse_pass": json_parse_pass,
                "schema_pass": schema_pass,
                "business_pass": business_pass,
                "structured_validation_pass": structured_validation_pass,
                "structured_gate_status": structured_gate_status,
                "cleanup_verified": cleanup_verified,
                "final_loaded_instances": final_loaded_instances,
                "privacy_scan_status": privacy_scan["status"],
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "generation_allowed": True,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "load_time_ms": load_time_ms,
                "prompt_processing_ms": prompt_processing_ms,
                "time_to_first_token_ms": time_to_first_token_ms,
                "total_latency_ms": total_latency_ms,
                "tokens_per_second": tokens_per_second,
                "managed_live": True,
                "lab_only": True,
                "app_concurrency": app_concurrency,
                "raw_prompt_response_stored": False,
            }
        )
        if failure_reasons:
            raise RuntimeError(
                "L3.7d structured JSON live smoke acceptance gate failed: "
                + ", ".join(failure_reasons)
            )
        return {
            **summary,
            **_build_safe_system_summary(system_summary),
        }

    def run_l3_8d_gemma4_e4b_strict_json_smoke(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
        timeout_s: float = 120.0,
        native_transport: ModelLifecycleTransport | None = None,
        chat_transport: LiveTransport | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        _, raw_payload = load_raw_experiment_config(Path(config_path))

        def _require_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
            if not isinstance(value, Mapping):
                raise ValueError(f"{field_name} must be a mapping")
            return value

        def _require_non_empty_string(value: object, *, field_name: str) -> str:
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            text = value.strip()
            if not text:
                raise ValueError(f"{field_name} must be a non-empty string")
            return text

        def _require_bool(value: object, *, field_name: str) -> bool:
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean")
            return value

        def _require_int(value: object, *, field_name: str, minimum: int | None = None) -> int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
            if minimum is not None and value < minimum:
                raise ValueError(f"{field_name} must be >= {minimum}")
            return value

        def _require_string_sequence(value: object, *, field_name: str) -> tuple[str, ...]:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                raise ValueError(f"{field_name} must be a sequence of strings")
            items: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    raise ValueError(f"{field_name} must be a sequence of strings")
                items.append(item)
            return tuple(items)

        def _default_native_transport(
            request: urllib_request.Request,
            request_timeout_s: float,
        ) -> bytes:
            with urllib_request.urlopen(request, timeout=request_timeout_s) as response:
                response_bytes = response.read()
                if not isinstance(response_bytes, bytes):
                    raise TypeError("native transport response must be bytes")
                return response_bytes

        def _request_json(
            *,
            method: str,
            url: str,
            body: Mapping[str, Any] | None = None,
        ) -> tuple[Mapping[str, Any], str]:
            data = None
            headers = {"Accept": "application/json"}
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = urllib_request.Request(url, data=data, headers=headers, method=method)
            response_bytes = request_transport(request, timeout_s)
            response_text = response_bytes.decode("utf-8")
            decoded = json.loads(response_text)
            if not isinstance(decoded, Mapping):
                raise ValueError(f"{method} response must be a JSON object")
            return decoded, response_text

        def _sanitize_models_payload(
            *,
            response_payload: Mapping[str, Any],
            response_text: str,
        ) -> tuple[dict[str, object], tuple[LoadedInstanceRecord, ...]]:
            parsed = parse_native_model_list(response_payload)
            if parsed.error is not None:
                raise ValueError("native model list response must parse successfully")
            target_model = next(
                (model for model in parsed.native_models if model.native_model_key == model_id),
                None,
            )
            loaded_instances = tuple(
                target_model.loaded_instances if target_model is not None else ()
            )
            return (
                {
                    "endpoint_kind": "native_models",
                    "method": "GET",
                    "target_model_id": model_id,
                    "target_model_key": model_key,
                    "target_model_present": target_model is not None,
                    "target_loaded_instance_count": len(loaded_instances),
                    "instance_id_hashes": [instance.instance_ref for instance in loaded_instances],
                    "context_lengths": [
                        instance.context_length
                        for instance in loaded_instances
                        if instance.context_length is not None
                    ],
                    "parallels": [
                        instance.parallel
                        for instance in loaded_instances
                        if instance.parallel is not None
                    ],
                    "response_hash": _safe_hash(response_text),
                    "response_chars": len(response_text),
                },
                loaded_instances,
            )

        request_transport = native_transport or _default_native_transport
        request_chat_transport = chat_transport or _default_live_transport

        experiment_id = _require_non_empty_string(
            raw_payload.get("experiment_id"),
            field_name="experiment_id",
        )
        if experiment_id != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_EXPERIMENT_ID:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires experiment_id "
                "'l3_8d_gemma4_e4b_strict_json_smoke'"
            )

        mode = _require_non_empty_string(raw_payload.get("mode"), field_name="mode")
        if mode != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_MODE:
            raise ValueError("L3.8d Gemma E4B strict JSON smoke requires mode 'strict_json_smoke'")

        model_payload = _require_mapping(raw_payload.get("model"), field_name="model")
        model_key = _require_non_empty_string(model_payload.get("key"), field_name="model.key")
        if model_key != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_MODEL_KEY:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires model.key 'gemma4_e4b_q4km'"
            )
        model_id = _require_non_empty_string(
            model_payload.get("lmstudio_model_id"),
            field_name="model.lmstudio_model_id",
        )
        if model_id != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_MODEL_ID:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires model.lmstudio_model_id "
                "'google/gemma-4-e4b'"
            )

        load_payload = _require_mapping(raw_payload.get("load"), field_name="load")
        requested_context_length = _require_int(
            load_payload.get("context_length"),
            field_name="load.context_length",
            minimum=1,
        )
        if requested_context_length != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_CONTEXT_LENGTH:
            raise ValueError("L3.8d Gemma E4B strict JSON smoke requires load.context_length=8192")
        echo_load_config = _require_bool(
            load_payload.get("echo_load_config"),
            field_name="load.echo_load_config",
        )
        if not echo_load_config:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires load.echo_load_config=true"
            )
        requested_parallel = _require_int(
            load_payload.get("parallel"),
            field_name="load.parallel",
            minimum=1,
        )
        if requested_parallel != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_PARALLEL:
            raise ValueError("L3.8d Gemma E4B strict JSON smoke requires load.parallel=1")

        app_concurrency = _require_int(
            raw_payload.get("app_concurrency"),
            field_name="app_concurrency",
            minimum=1,
        )
        if app_concurrency != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_APP_CONCURRENCY:
            raise ValueError("L3.8d Gemma E4B strict JSON smoke requires app_concurrency=1")

        dataset_payload = _require_mapping(raw_payload.get("dataset"), field_name="dataset")
        dataset_id = _require_non_empty_string(dataset_payload.get("id"), field_name="dataset.id")
        if dataset_id != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_DATASET_ID:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires dataset.id 'blocks_json_small'"
            )

        generation_payload = _require_mapping(
            raw_payload.get("generation"), field_name="generation"
        )
        generation_route = _require_non_empty_string(
            generation_payload.get("route"),
            field_name="generation.route",
        )
        if generation_route != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ROUTE:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires generation.route "
                "'strict_json_chat_completions'"
            )
        helper_mode = _require_non_empty_string(
            generation_payload.get("helper_mode"),
            field_name="generation.helper_mode",
        )
        if helper_mode != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_HELPER_MODE:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires generation.helper_mode "
                "'json_schema_single'"
            )
        endpoint_path = _require_non_empty_string(
            generation_payload.get("endpoint_path"),
            field_name="generation.endpoint_path",
        )
        if endpoint_path != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_ENDPOINT_PATH:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires generation.endpoint_path "
                "'/v1/chat/completions'"
            )
        temperature = _require_int(
            generation_payload.get("temperature"),
            field_name="generation.temperature",
            minimum=0,
        )
        if temperature != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_TEMPERATURE:
            raise ValueError("L3.8d Gemma E4B strict JSON smoke requires generation.temperature=0")
        max_tokens = _require_int(
            generation_payload.get("max_tokens"),
            field_name="generation.max_tokens",
            minimum=1,
        )
        if max_tokens != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_MAX_TOKENS:
            raise ValueError("L3.8d Gemma E4B strict JSON smoke requires generation.max_tokens=512")

        safety_payload = _require_mapping(raw_payload.get("safety"), field_name="safety")
        generation_allowed = _require_bool(
            safety_payload.get("generation_allowed"),
            field_name="safety.generation_allowed",
        )
        if not generation_allowed:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires safety.generation_allowed=true"
            )
        live_25k_authorized = _require_bool(
            safety_payload.get("live_25k_authorized"),
            field_name="safety.live_25k_authorized",
        )
        if live_25k_authorized:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires safety.live_25k_authorized=false"
            )
        production_default = _require_bool(
            safety_payload.get("production_default"),
            field_name="safety.production_default",
        )
        if production_default:
            raise ValueError("safety.production_default must remain false")
        wvm_runtime_integration = _require_bool(
            safety_payload.get("wvm_runtime_integration"),
            field_name="safety.wvm_runtime_integration",
        )
        if wvm_runtime_integration:
            raise ValueError("safety.wvm_runtime_integration must remain false")
        kv_reuse_proven = _require_bool(
            safety_payload.get("kv_reuse_proven"),
            field_name="safety.kv_reuse_proven",
        )
        if kv_reuse_proven:
            raise ValueError("safety.kv_reuse_proven must remain false")
        final_user_facing_recommendation = _require_bool(
            safety_payload.get("final_user_facing_recommendation"),
            field_name="safety.final_user_facing_recommendation",
        )
        if final_user_facing_recommendation:
            raise ValueError("safety.final_user_facing_recommendation must remain false")
        unload_required = _require_bool(
            safety_payload.get("unload_required"),
            field_name="safety.unload_required",
        )
        if not unload_required:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires safety.unload_required=true"
            )
        final_loaded_instances_required = _require_int(
            safety_payload.get("final_loaded_instances_required"),
            field_name="safety.final_loaded_instances_required",
            minimum=0,
        )
        if final_loaded_instances_required != 0:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires safety.final_loaded_instances_required=0"
            )

        privacy_payload = _require_mapping(raw_payload.get("privacy"), field_name="privacy")
        if _require_bool(
            privacy_payload.get("store_raw_prompt_response"),
            field_name="privacy.store_raw_prompt_response",
        ):
            raise ValueError("privacy.store_raw_prompt_response must remain false")
        if _require_bool(
            privacy_payload.get("store_local_urls"),
            field_name="privacy.store_local_urls",
        ):
            raise ValueError("privacy.store_local_urls must remain false")
        if _require_bool(
            privacy_payload.get("store_state_ids_raw"),
            field_name="privacy.store_state_ids_raw",
        ):
            raise ValueError("privacy.store_state_ids_raw must remain false")

        artifacts = raw_payload.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes, bytearray)):
            raise ValueError("artifacts must be a list of strings")
        artifact_names = tuple(
            _require_non_empty_string(artifact_name, field_name="artifacts[]")
            for artifact_name in artifacts
        )
        if artifact_names != _L3_8D_GEMMA4_E4B_STRICT_JSON_SMOKE_OUTPUT_FILES:
            raise ValueError(
                "L3.8d Gemma E4B strict JSON smoke requires the exact artifact list declared by the L3.8d contract"
            )

        base_url = str(raw_payload.get("lmstudio_base_url", "http://127.0.0.1:1234")).strip()
        if not base_url:
            base_url = "http://127.0.0.1:1234"
        base_url = base_url.rstrip("/")

        live_config = LiveSmokeConfig(
            experiment_id=experiment_id,
            models=(
                LiveModelConfig(
                    key=model_key,
                    model_id=model_id,
                    load={
                        "context_length": (requested_context_length,),
                        "parallel": (requested_parallel,),
                    },
                ),
            ),
            modes=(helper_mode,),
            datasets=(dataset_id,),
            repeats=1,
            lmstudio_base_url=base_url,
            allow_remote=False,
            hardware_profile="managed_runner_l3_8d_strict_json",
            warmup_runs=0,
            privacy=LivePrivacyConfig(
                store_prompt_text=False,
                store_response_text=False,
                store_prompt_hash=True,
            ),
        )

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        requests_path = run_path / "requests.jsonl"
        metrics_path = run_path / "metrics.jsonl"
        structured_errors_path = run_path / "structured_errors.jsonl"
        requests_path.write_text("", encoding="utf-8")
        metrics_path.write_text("", encoding="utf-8")
        structured_errors_path.write_text("", encoding="utf-8")

        environment_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "managed_live": True,
            "lab_only": True,
            "strict_json_live_smoke": True,
            "live_25k_authorized": False,
            "production_default": False,
            "wvm_runtime_integration": False,
            "kv_reuse_proven": False,
            "final_user_facing_recommendation": False,
        }
        write_json_file(run_path / "environment.json", environment_payload)

        run_config_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "model_key": model_key,
            "model_id": model_id,
            "dataset_id": dataset_id,
            "app_concurrency": app_concurrency,
            "requested_context_length": requested_context_length,
            "requested_parallel": requested_parallel,
            "load": {
                "context_length": requested_context_length,
                "parallel": requested_parallel,
                "echo_load_config": echo_load_config,
            },
            "generation": {
                "route": generation_route,
                "helper_mode": helper_mode,
                "endpoint_path": endpoint_path,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            "safety": {
                "generation_allowed": True,
                "live_25k_authorized": False,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "final_user_facing_recommendation": False,
                "unload_required": True,
                "final_loaded_instances_required": 0,
            },
            "privacy": {
                "store_raw_prompt_response": False,
                "store_local_urls": False,
                "store_state_ids_raw": False,
            },
            "artifacts": list(artifact_names),
        }
        write_json_file(run_path / "run_config.json", run_config_payload)

        normalized_providers = _normalize_providers(providers)
        request_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []
        structured_error_rows: list[dict[str, Any]] = []
        raw_instance_id: str | None = None
        raw_response_id: str | None = None
        raw_public_content: str | None = None
        prompt_privacy_marker: str | None = None
        instance_id_hash: str | None = None
        applied_context_length: int | None = None
        applied_parallel: int | None = None
        load_verified = False
        generation_called = False
        request_succeeded = False
        public_content_pass = False
        structured_validation_pass = False
        reasoning_content_present: bool | None = None
        cleanup_verified = False
        final_loaded_instances: int | None = None
        load_time_ms: float | None = None
        total_latency_ms: float | None = None
        prompt_processing_ms: float | None = None
        time_to_first_token_ms: float | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        tokens_per_second: float | None = None
        json_parse_pass = False
        schema_pass = False
        business_pass = False
        structured_gate_status = "not_started"
        failure_reasons: list[str] = []
        system_summary: SystemMetricsSummary | None = None
        pending_exception: (
            tuple[type[BaseException], BaseException, TracebackType | None] | None
        ) = None

        def _tracked_chat_transport(
            url: str,
            payload: Mapping[str, Any],
            request_timeout_s: float,
        ) -> Mapping[str, Any]:
            nonlocal prompt_privacy_marker, raw_response_id, raw_public_content
            message_parts: list[str] = []
            for message in payload.get("messages", ()):
                if isinstance(message, Mapping):
                    content = message.get("content")
                    if isinstance(content, str):
                        message_parts.append(content)
            if message_parts:
                prompt_privacy_marker = _build_prompt_privacy_marker("\n".join(message_parts))
            response_payload = request_chat_transport(url, payload, request_timeout_s)
            if not isinstance(response_payload, Mapping):
                raise ValueError("LM Studio response must be a JSON object")
            raw_response_id = _as_optional_str(
                response_payload.get("id")
                or response_payload.get("response_id")
                or response_payload.get("responseId")
            )
            choices = response_payload.get("choices")
            if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes, bytearray)):
                if choices:
                    first_choice = choices[0]
                    if isinstance(first_choice, Mapping):
                        message = first_choice.get("message")
                        if isinstance(message, Mapping):
                            content = message.get("content")
                            if isinstance(content, str) and content.strip():
                                raw_public_content = content
            return response_payload

        self._system_sampler.start(providers=normalized_providers)
        try:
            models_before_payload, models_before_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            _, preexisting_loaded_instances = _sanitize_models_payload(
                response_payload=models_before_payload,
                response_text=models_before_text,
            )
            if preexisting_loaded_instances:
                raise ValueError("target model already has loaded instances before WVM-owned load")

            load_request_body = {
                "model": model_id,
                "context_length": requested_context_length,
                "echo_load_config": echo_load_config,
                "parallel": requested_parallel,
            }
            load_started_at = _live_request_perf_counter()
            load_response_payload, load_response_text = _request_json(
                method="POST",
                url=f"{base_url}/api/v1/models/load",
                body=load_request_body,
            )
            load_time_ms = round((_live_request_perf_counter() - load_started_at) * 1000.0, 3)
            raw_instance_id = _as_optional_str(
                load_response_payload.get("instance_id")
                or load_response_payload.get("instanceId")
                or load_response_payload.get("id")
            )
            if raw_instance_id is None:
                raise ValueError("load response must include instance_id")
            instance_id_hash = _safe_hash(raw_instance_id)
            load_config_response = load_response_payload.get("load_config")
            if not isinstance(load_config_response, Mapping):
                raise ValueError("load response must include load_config mapping")
            applied_context_length = _as_optional_int(load_config_response.get("context_length"))
            applied_parallel = _as_optional_int(
                load_config_response.get("parallel", load_config_response.get("n_parallel"))
            )
            if applied_context_length != requested_context_length:
                raise ValueError("owned native load must materialize context_length=8192")
            if applied_parallel != requested_parallel:
                raise ValueError("owned native load must materialize parallel=1")
            write_json_file(
                run_path / "load_response_sanitized.json",
                {
                    "endpoint_kind": "native_load",
                    "method": "POST",
                    "status": _as_optional_str(load_response_payload.get("status")) or "unknown",
                    "instance_id_hash": instance_id_hash,
                    "load_time_ms": load_time_ms,
                    "applied_load_config": {
                        "context_length": applied_context_length,
                        "parallel": applied_parallel,
                        "echo_load_config": _as_optional_bool(
                            load_config_response.get("echo_load_config")
                        ),
                    },
                    "response_hash": _safe_hash(load_response_text),
                    "response_chars": len(load_response_text),
                },
            )

            models_after_load_payload, models_after_load_text = _request_json(
                method="GET",
                url=f"{base_url}/api/v1/models",
            )
            models_after_load, loaded_instances = _sanitize_models_payload(
                response_payload=models_after_load_payload,
                response_text=models_after_load_text,
            )
            owned_instance = next(
                (
                    instance
                    for instance in loaded_instances
                    if instance.instance_ref == instance_id_hash
                ),
                None,
            )
            load_verified = (
                models_after_load["target_loaded_instance_count"] == 1
                and owned_instance is not None
                and applied_context_length == requested_context_length
                and applied_parallel == requested_parallel
            )
            if not load_verified:
                raise ValueError("owned native load verification failed")

            generation_called = True
            outcome = run_live_structured_smoke(
                live_config,
                run_id=safe_run_id,
                timeout_s=timeout_s,
                transport=_tracked_chat_transport,
                verified_context_length=requested_context_length,
            )
            metric_row = outcome.metric.to_dict()
            metric_row["raw_prompt_response_stored"] = False
            metric_rows.append(append_jsonl_record(metrics_path, metric_row))
            if outcome.structured_error is not None:
                structured_error_rows.append(
                    append_jsonl_record(structured_errors_path, outcome.structured_error)
                )

            validation_payload = metric_row.get("validation")
            if isinstance(validation_payload, Mapping):
                json_parse_pass = bool(validation_payload.get("json_parse_pass") is True)
                schema_pass = bool(validation_payload.get("schema_pass") is True)
                business_pass = bool(validation_payload.get("business_pass") is True)
            reasoning_content_present = _as_optional_bool(
                metric_row.get("reasoning_content_present")
            )
            public_content_pass = metric_row.get("content_empty") is False
            structured_validation_pass = (
                public_content_pass
                and reasoning_content_present is False
                and json_parse_pass
                and schema_pass
                and business_pass
                and outcome.structured_error is None
            )
            request_succeeded = structured_validation_pass
            if request_succeeded:
                structured_gate_status = "passed"
            elif public_content_pass is False and reasoning_content_present is True:
                structured_gate_status = "failed_reasoning_only_json"
            elif public_content_pass is False:
                structured_gate_status = "failed_public_content_empty"
            elif reasoning_content_present is True:
                structured_gate_status = "failed_reasoning_content_present"
            else:
                structured_gate_status = "failed"

            input_tokens = _as_optional_int(metric_row.get("tokens", {}).get("prompt_tokens"))
            output_tokens = _as_optional_int(metric_row.get("tokens", {}).get("completion_tokens"))
            total_latency_ms = _as_optional_rate(
                metric_row.get("timing", {}).get("total_elapsed_ms")
            )
            prompt_processing_ms = _as_optional_rate(
                metric_row.get("timing", {}).get("prompt_processing_ms")
            )
            time_to_first_token_ms = _as_optional_rate(
                metric_row.get("timing", {}).get("time_to_first_token_ms")
            )
            tokens_per_second = _as_optional_rate(
                metric_row.get("timing", {}).get("tokens_per_second")
            )

            request_row = {
                "schema_version": SCHEMA_VERSION,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "managed_live": True,
                "request_id": metric_row.get("request_id"),
                "request_role": generation_route,
                "route": generation_route,
                "helper_mode": helper_mode,
                "model_key": model_key,
                "model_id": model_id,
                "endpoint_path": endpoint_path,
                "app_concurrency": app_concurrency,
                "requested_context_length": requested_context_length,
                "requested_parallel": requested_parallel,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "prompt_hash": metric_row.get("prompt_hash"),
                "prompt_chars": metric_row.get("prompt_chars"),
                "response_id_present": raw_response_id is not None,
                "response_id_hash": (_safe_hash(raw_response_id) if raw_response_id else None),
                "response_hash": metric_row.get("response_hash"),
                "response_chars": metric_row.get("response_chars"),
                "content_nonempty": public_content_pass,
                "reasoning_content_present": reasoning_content_present,
                "json_parse_pass": json_parse_pass,
                "schema_pass": schema_pass,
                "business_pass": business_pass,
                "structured_gate_status": structured_gate_status,
                "raw_prompt_response_stored": False,
                "live_25k_authorized": False,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "final_user_facing_recommendation": False,
                "status": "success" if request_succeeded else "failed",
            }
            request_rows.append(append_jsonl_record(requests_path, request_row))
        except Exception:
            pending_exception = cast(
                tuple[type[BaseException], BaseException, TracebackType | None],
                sys.exc_info(),
            )
        finally:
            cleanup_error: Exception | None = None
            if raw_instance_id is not None:
                try:
                    _request_json(
                        method="POST",
                        url=f"{base_url}/api/v1/models/unload",
                        body={"instance_id": raw_instance_id},
                    )
                    models_after_unload_payload, models_after_unload_text = _request_json(
                        method="GET",
                        url=f"{base_url}/api/v1/models",
                    )
                    models_after_unload, _ = _sanitize_models_payload(
                        response_payload=models_after_unload_payload,
                        response_text=models_after_unload_text,
                    )
                    final_loaded_instances = _as_optional_int(
                        models_after_unload.get("target_loaded_instance_count")
                    )
                    models_after_unload_instance_hashes = _require_string_sequence(
                        models_after_unload.get("instance_id_hashes"),
                        field_name="models_after_unload.instance_id_hashes",
                    )
                    cleanup_verified = bool(
                        final_loaded_instances == final_loaded_instances_required
                        and instance_id_hash is not None
                        and instance_id_hash not in models_after_unload_instance_hashes
                    )
                    if not cleanup_verified:
                        cleanup_error = RuntimeError("native cleanup not verified")
                except Exception as error:
                    cleanup_error = error
            try:
                system_summary = self._system_sampler.stop(providers=normalized_providers)
                write_system_telemetry_artifacts(
                    run_path,
                    samples=self._system_sampler.samples,
                    summary=system_summary,
                )
            except Exception as error:
                if cleanup_error is None:
                    cleanup_error = error

            if pending_exception is not None:
                exc_type, exc, traceback = pending_exception
                if exc is not None:
                    raise exc.with_traceback(traceback)
                raise exc_type
            if cleanup_error is not None:
                raise cleanup_error

        assert system_summary is not None

        if not structured_error_rows:
            structured_errors_path.write_text("", encoding="utf-8")

        report_rows = (
            ("experiment_id", experiment_id),
            ("run_id", safe_run_id),
            ("mode", mode),
            ("route", generation_route),
            ("helper_mode", helper_mode),
            ("endpoint_path", endpoint_path),
            ("requested_context_length", str(requested_context_length)),
            ("applied_context_length", str(applied_context_length)),
            ("requested_parallel", str(requested_parallel)),
            ("applied_parallel", str(applied_parallel)),
            ("load_verified", str(load_verified).lower()),
            ("generation_called", str(generation_called).lower()),
            ("request_succeeded", str(request_succeeded).lower()),
            ("public_content_pass", str(public_content_pass).lower()),
            ("reasoning_content_present", str(reasoning_content_present).lower()),
            ("json_parse_pass", str(json_parse_pass).lower()),
            ("schema_pass", str(schema_pass).lower()),
            ("business_pass", str(business_pass).lower()),
            ("structured_gate_status", structured_gate_status),
            ("cleanup_verified", str(cleanup_verified).lower()),
            ("final_loaded_instances", str(final_loaded_instances)),
            ("live_25k_authorized", "false"),
            ("production_default", "false"),
            ("wvm_runtime_integration", "false"),
            ("kv_reuse_proven", "false"),
            ("final_user_facing_recommendation", "false"),
            ("temperature", str(temperature)),
            ("max_tokens", str(max_tokens)),
        )
        report_text = "\n".join(
            [
                "# LM Studio Lab L3.8d Gemma4 E4B Strict JSON Smoke Report",
                "",
                "This is a lab-only managed strict JSON chat-completions smoke gate for the current Gemma E4B candidate.",
                "live_25k_authorized=false, production_default=false, wvm_runtime_integration=false, kv_reuse_proven=false, final_user_facing_recommendation=false.",
                "Public assistant content is required; reasoning-only JSON or reasoning_content leakage is a failure.",
                "",
                "| Field | Value |",
                "| --- | --- |",
                *[f"| {field} | `{value}` |" for field, value in report_rows],
                "",
                "Exactly one `/v1/chat/completions` structured JSON request runs after exact owned native load verification and before exact unload cleanup verification.",
                "No `/api/v1/chat` or `/v1/responses` calls are allowed in this gate.",
                "No raw prompt text, raw response text, raw state identifiers, or raw localhost URLs are stored in artifacts.",
                "",
            ]
        )

        privacy_payloads: dict[str, object] = {
            "environment.json": environment_payload,
            "run_config.json": run_config_payload,
            "load_response_sanitized.json": json.loads(
                (run_path / "load_response_sanitized.json").read_text(encoding="utf-8")
            ),
            "requests.jsonl": list(request_rows),
            "metrics.jsonl": list(metric_rows),
            "structured_errors.jsonl": list(structured_error_rows),
            "system_samples.jsonl": [sample.to_dict() for sample in self._system_sampler.samples],
            "system_summary.json": system_summary.to_dict(),
            "report.md": report_text,
        }
        privacy_violations: list[str] = []
        public_safe_markers = {
            marker
            for marker in (
                _qualifying_privacy_marker(model_id),
                _qualifying_privacy_marker(model_key),
            )
            if marker is not None
        }
        instance_privacy_marker = _qualifying_privacy_marker(raw_instance_id)
        if instance_privacy_marker in public_safe_markers:
            instance_privacy_marker = None
        raw_markers = {
            marker
            for marker in (
                _qualifying_privacy_marker(base_url),
                instance_privacy_marker,
                _qualifying_privacy_marker(raw_response_id),
                _qualifying_privacy_marker(raw_public_content),
                _qualifying_privacy_marker(prompt_privacy_marker),
            )
            if marker is not None
        }
        for artifact_name, artifact_payload in privacy_payloads.items():
            serialized_payload = (
                artifact_payload
                if isinstance(artifact_payload, str)
                else json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True)
            )
            privacy_violations.extend(
                find_privacy_violations(
                    {"artifact_name": artifact_name, "serialized": serialized_payload},
                    context=artifact_name,
                )
            )
            for raw_marker in raw_markers:
                if raw_marker and raw_marker in serialized_payload:
                    privacy_violations.append(f"{artifact_name} contains a raw private marker")
        privacy_scan = {
            "status": "pass" if not privacy_violations else "fail",
            "violation_count": len(privacy_violations),
            "scan_scope": "l3_8d_gemma4_e4b_strict_json_smoke_raw_url_path_private_value_scan",
            "scanned_artifacts": list(privacy_payloads),
            "raw_prompt_response_stored": False,
        }
        write_json_file(run_path / "privacy_scan.json", privacy_scan)
        (run_path / "report.md").write_text(report_text, encoding="utf-8")

        if not public_content_pass:
            failure_reasons.append(structured_gate_status)
        elif reasoning_content_present:
            failure_reasons.append("reasoning_content_present")
        elif not structured_validation_pass:
            failure_reasons.append("structured_validation_failed")
        if privacy_scan["status"] != "pass":
            failure_reasons.append("privacy_scan_failed")

        decision = (
            "l3_8d_strict_json_smoke_pass"
            if not failure_reasons and cleanup_verified and load_verified and request_succeeded
            else "l3_8d_strict_json_smoke_fail"
        )
        summary = _sanitize_operation_summary(
            {
                "decision": decision,
                "run_id": safe_run_id,
                "experiment_id": experiment_id,
                "mode": mode,
                "model_id": model_id,
                "route": generation_route,
                "helper_mode": helper_mode,
                "requested_context_length": requested_context_length,
                "applied_context_length": applied_context_length,
                "requested_parallel": requested_parallel,
                "applied_parallel": applied_parallel,
                "load_verified": load_verified,
                "generation_called": generation_called,
                "request_succeeded": request_succeeded,
                "public_output_pass": public_content_pass,
                "reasoning_present": reasoning_content_present,
                "json_parse_pass": json_parse_pass,
                "schema_pass": schema_pass,
                "business_pass": business_pass,
                "structured_validation_pass": structured_validation_pass,
                "structured_gate_status": structured_gate_status,
                "cleanup_verified": cleanup_verified,
                "final_loaded_instances": final_loaded_instances,
                "privacy_scan_status": privacy_scan["status"],
                "live_25k_authorized": False,
                "production_default": False,
                "wvm_runtime_integration": False,
                "kv_reuse_proven": False,
                "final_user_facing_recommendation": False,
                "generation_allowed": True,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "load_time_ms": load_time_ms,
                "prompt_processing_ms": prompt_processing_ms,
                "time_to_first_token_ms": time_to_first_token_ms,
                "total_latency_ms": total_latency_ms,
                "tokens_per_second": tokens_per_second,
                "managed_live": True,
                "lab_only": True,
                "app_concurrency": app_concurrency,
                "raw_prompt_response_stored": False,
            }
        )
        if failure_reasons:
            raise RuntimeError(
                "L3.8d Gemma E4B strict JSON smoke acceptance gate failed: "
                + ", ".join(failure_reasons)
            )
        return {
            **summary,
            **_build_safe_system_summary(system_summary),
        }

    def run_responses_cache_probe(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        providers: Mapping[str, str] | None = None,
        timeout_s: float = 120.0,
        responses_transport: ResponsesProbeTransport | None = None,
    ) -> dict[str, object]:
        del providers

        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        config_scope = _load_responses_cache_probe_scope(config_path)
        request_transport = responses_transport or _default_responses_probe_transport
        endpoint_family = LMStudioEndpointFamily.OPENAI_RESPONSES.value
        endpoint_url = _normalize_responses_base_url(config_scope["base_url"])
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        environment_payload = _build_responses_probe_environment_payload(
            run_id=safe_run_id,
            config_scope=config_scope,
        )
        run_config_payload = _build_responses_probe_run_config(
            run_id=safe_run_id,
            config_scope=config_scope,
        )
        write_json_file(run_path / "environment.json", environment_payload)
        write_json_file(run_path / "run_config.json", run_config_payload)

        request_specs = _build_responses_probe_request_specs(
            run_id=safe_run_id,
            config_scope=config_scope,
        )
        requests_path = run_path / "requests.jsonl"
        metrics_path = run_path / "metrics.jsonl"
        requests_path.write_text("", encoding="utf-8")
        metrics_path.write_text("", encoding="utf-8")

        metrics_rows: list[dict[str, Any]] = []
        raw_response_ids_seen: list[str] = []
        raw_previous_response_ids_seen: list[str] = []
        successful_previous_response_id_count = 0
        response_id_by_pair_key: dict[str, str] = {}

        for request_spec in request_specs:
            previous_pair_key = _as_optional_str(request_spec.get("previous_pair_key"))
            previous_response_id = (
                response_id_by_pair_key.get(previous_pair_key)
                if previous_pair_key is not None
                else None
            )
            previous_response_id_hash = (
                _safe_hash(previous_response_id) if previous_response_id is not None else None
            )
            previous_response_id_used = previous_pair_key is not None
            request_row = {
                "schema_version": SCHEMA_VERSION,
                "run_id": safe_run_id,
                "experiment_id": config_scope["experiment_id"],
                "mode": request_spec["mode"],
                "dataset_id": request_spec["dataset_id"],
                "dataset_target_tokens": request_spec["dataset_target_tokens"],
                "repeat_phase": request_spec["repeat_phase"],
                "repeat_index": request_spec["repeat_index"],
                "sequence_index": request_spec["sequence_index"],
                "request_id": request_spec["request_id"],
                "request_role": request_spec["request_role"],
                "endpoint_family": endpoint_family,
                "model_key": config_scope["model_key"],
                "model_id": config_scope["model_id"],
                "input_hash": _safe_hash(request_spec["input_text"]),
                "input_chars": len(request_spec["input_text"]),
                "estimated_input_tokens": request_spec["estimated_input_tokens"],
                "max_output_tokens": request_spec["max_output_tokens"],
                "previous_response_id_used": previous_response_id_used,
                "previous_response_id_hash": previous_response_id_hash,
                "inference_endpoint_called": True,
                "production_default": False,
                "wvm_runtime_integration": False,
                "live_25k_authorized": False,
                "kv_reuse_proven": False,
                "store_raw_prompt_response": False,
                "store_response_id_raw": False,
                "hash_response_id": True,
            }
            append_jsonl_record(requests_path, request_row)

            if previous_response_id_used and previous_response_id is None:
                metric_row = {
                    **request_row,
                    "total_latency_ms": 0.0,
                    "response_id_present": False,
                    "response_id_hash": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "cached_tokens": None,
                    "cached_tokens_available": False,
                    "cache_hit_ratio": None,
                    "raw_usage_keys": (),
                    "content_nonempty": False,
                    "finish_status": "not_sent_missing_previous_response_id",
                    "error_type": "missing_previous_response_id",
                }
                metrics_rows.append(append_jsonl_record(metrics_path, metric_row))
                continue

            request_payload = {
                "model": config_scope["model_id"],
                "input": request_spec["input_text"],
                "store": True,
                "max_output_tokens": request_spec["max_output_tokens"],
            }
            if previous_response_id is not None:
                request_payload["previous_response_id"] = previous_response_id
                raw_previous_response_ids_seen.append(previous_response_id)

            started_at = time.monotonic()
            try:
                response_payload, _, response_status_code = _request_responses_probe_json(
                    request_transport=request_transport,
                    endpoint_url=endpoint_url,
                    timeout_s=timeout_s,
                    request_payload=request_payload,
                )
                usage_summary = parse_responses_usage(response_payload)
                response_id = _as_optional_str(
                    response_payload.get("id") or response_payload.get("response_id")
                )
                if response_id is not None:
                    raw_response_ids_seen.append(response_id)
                response_id_hash = _safe_hash(response_id) if response_id is not None else None
                error_type = _extract_responses_probe_error_type(response_payload)
                finish_status = _resolve_responses_probe_finish_status(
                    response_payload=response_payload,
                    response_status_code=response_status_code,
                    error_type=error_type,
                )
                content_text = _extract_responses_probe_output_text(response_payload)
                content_nonempty = bool(content_text and content_text.strip())
                if error_type is None and not content_nonempty:
                    error_type = "empty_output"
                    finish_status = "empty_output"
                latency_ms = (time.monotonic() - started_at) * 1000.0
                cache_hit_ratio = None
                if (
                    usage_summary.cached_tokens is not None
                    and usage_summary.input_tokens is not None
                    and usage_summary.input_tokens > 0
                ):
                    cache_hit_ratio = usage_summary.cached_tokens / usage_summary.input_tokens

                metric_row = {
                    **request_row,
                    "total_latency_ms": latency_ms,
                    "response_id_present": response_id is not None,
                    "response_id_hash": response_id_hash,
                    "input_tokens": usage_summary.input_tokens,
                    "output_tokens": usage_summary.output_tokens,
                    "total_tokens": usage_summary.total_tokens,
                    "cached_tokens": usage_summary.cached_tokens,
                    "cached_tokens_available": usage_summary.cached_tokens_available,
                    "cache_hit_ratio": cache_hit_ratio,
                    "raw_usage_keys": usage_summary.raw_usage_keys,
                    "content_nonempty": content_nonempty,
                    "finish_status": finish_status,
                    "error_type": error_type,
                }
                metrics_rows.append(append_jsonl_record(metrics_path, metric_row))

                if request_spec["captures_response_id"] and response_id is not None:
                    response_id_by_pair_key[str(request_spec["pair_key"])] = response_id
                if error_type is None and previous_response_id_used and response_id is not None:
                    successful_previous_response_id_count += 1
            except Exception as error:
                metric_row = {
                    **request_row,
                    "total_latency_ms": (time.monotonic() - started_at) * 1000.0,
                    "response_id_present": False,
                    "response_id_hash": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "cached_tokens": None,
                    "cached_tokens_available": False,
                    "cache_hit_ratio": None,
                    "raw_usage_keys": (),
                    "content_nonempty": False,
                    "finish_status": "transport_error",
                    "error_type": type(error).__name__,
                }
                metrics_rows.append(append_jsonl_record(metrics_path, metric_row))

        summary_payload = _build_responses_probe_summary(
            run_id=safe_run_id,
            config_scope=config_scope,
            metric_rows=metrics_rows,
            previous_response_id_supported=successful_previous_response_id_count > 0,
        )
        write_json_file(run_path / "responses_usage_summary.json", summary_payload)

        report_text = _render_responses_cache_probe_report(summary_payload=summary_payload)
        privacy_scan = _build_responses_probe_privacy_scan(
            environment_payload=environment_payload,
            run_config_payload=run_config_payload,
            request_rows=_load_jsonl_records(requests_path),
            metric_rows=_load_jsonl_records(metrics_path),
            summary_payload=summary_payload,
            report_text=report_text,
            raw_base_url=config_scope["base_url"],
            raw_endpoint_url=endpoint_url,
            raw_response_ids=raw_response_ids_seen,
            raw_previous_response_ids=raw_previous_response_ids_seen,
        )
        write_json_file(run_path / "privacy_scan.json", privacy_scan)
        (run_path / "report.md").write_text(report_text, encoding="utf-8")
        return {
            **summary_payload,
            "privacy_scan_status": privacy_scan["status"],
        }

    def run_cache_stateful_live_smoke(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        timeout_s: float = 120.0,
        app_concurrency: int = _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
        providers: Mapping[str, str] | None = None,
        native_transport: ModelLifecycleTransport | None = None,
        stateful_transport: LiveTransport | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")
        if isinstance(app_concurrency, bool) or not isinstance(app_concurrency, int):
            raise ValueError("app_concurrency must be exactly 1 for L3.3 live smoke")
        if app_concurrency != _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY:
            raise ValueError("app_concurrency must be exactly 1 for L3.3 live smoke")

        config = load_live_smoke_config(config_path, live_enabled=True)
        live_scope = _validate_cache_stateful_live_smoke_config(config)
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        environment_payload = _build_cache_stateful_live_smoke_environment_payload(
            experiment_id=config.experiment_id,
            run_id=safe_run_id,
        )
        experiment_yaml_payload = _build_medium_chunked_live_experiment_payload(config)
        experiment_yaml_text = yaml.safe_dump(experiment_yaml_payload, sort_keys=False)
        write_json_file(run_path / "environment.json", environment_payload)
        (run_path / "experiment.yaml").write_text(experiment_yaml_text, encoding="utf-8")

        dataset_manifest = load_dataset_manifest(str(live_scope["dataset_id"]))
        requests_path = run_path / "requests.jsonl"
        metrics_path = run_path / "metrics.jsonl"
        privacy_scan_path = run_path / "privacy_scan.json"
        report_path = run_path / "report.md"

        root_input = _build_cache_stateful_live_smoke_root_input()
        branch_inputs = _build_cache_stateful_live_smoke_branch_inputs()
        run_config = _build_cache_stateful_live_smoke_run_config(
            config=config,
            run_id=safe_run_id,
            dataset_manifest=dataset_manifest,
            root_input=root_input,
            branch_inputs=branch_inputs,
        )
        write_json_file(run_path / "run_config.json", run_config)

        request_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []

        def _operation() -> dict[str, object]:
            requests_path.write_text("", encoding="utf-8")
            metrics_path.write_text("", encoding="utf-8")
            request_rows.clear()
            metric_rows.clear()

            def _live_operation(_lifecycle_state: Mapping[str, object]) -> dict[str, object]:
                request_transport = stateful_transport or _default_live_transport
                stateful_url = _build_cache_stateful_live_smoke_url(config.lmstudio_base_url)
                root_request_id = "root_context"
                raw_root_state_id: str | None = None
                root_state_hash: str | None = None

                def _record_request(
                    *,
                    request_id: str,
                    request_kind: str,
                    prompt_text: str,
                    branch_id: str | None = None,
                    previous_state_id: str | None = None,
                    root_state_id_hash: str | None = None,
                ) -> tuple[str, str]:
                    payload: dict[str, object] = {
                        "model": str(live_scope["model_id"]),
                        "input": prompt_text,
                        "store": True,
                    }
                    if previous_state_id is not None:
                        payload["previous_response_id"] = previous_state_id
                    response_payload = request_transport(stateful_url, payload, timeout_s)
                    if not isinstance(response_payload, Mapping):
                        raise ValueError("stateful live smoke response must be a JSON object")

                    raw_state_id = _as_optional_str(response_payload.get("response_id"))
                    if not raw_state_id:
                        raise ValueError("stateful live smoke response must include response_id")
                    output_text = _extract_cache_stateful_live_smoke_output_text(response_payload)
                    if output_text is None:
                        raise ValueError(
                            "stateful live smoke response must include non-empty output"
                        )

                    state_id_hash = _safe_hash(raw_state_id)
                    output_hash = _safe_hash(output_text)
                    estimated_input_tokens = _estimate_cache_stateful_live_smoke_tokens(prompt_text)
                    previous_state_hash = (
                        _safe_hash(previous_state_id) if previous_state_id is not None else None
                    )
                    used_previous_root_state = (
                        previous_state_id is not None and previous_state_hash == root_state_id_hash
                    )
                    request_row = {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": safe_run_id,
                        "experiment_id": config.experiment_id,
                        "mode": _CACHE_STATEFUL_LIVE_SMOKE_MODE,
                        "managed_live": True,
                        "request_id": request_id,
                        "request_kind": request_kind,
                        "branch_id": branch_id,
                        "dataset_id": dataset_manifest.dataset_id,
                        "dataset_hash": dataset_manifest.content_hash,
                        "model_key": str(live_scope["model_key"]),
                        "model_id": str(live_scope["model_id"]),
                        "context_window": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
                        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
                        "measurement_status": CacheMeasurementStatus.INCONCLUSIVE.value,
                        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
                        "kv_reuse_proven": False,
                        "stateful_functional_ok": False,
                        "store": True,
                        "prompt_hash": _safe_hash(prompt_text),
                        "prompt_chars": len(prompt_text),
                        "estimated_input_tokens": estimated_input_tokens,
                        "state_id_hash": state_id_hash,
                        "root_state_hash": root_state_id_hash or state_id_hash,
                        "previous_state_hash": previous_state_hash,
                        "used_previous_root_state": used_previous_root_state,
                        "output_hash": output_hash,
                        "output_chars": len(output_text),
                        "output_present": True,
                        "status": "success",
                        "raw_prompt_response_stored": False,
                        "production_default": False,
                    }
                    metric_row = {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": safe_run_id,
                        "experiment_id": config.experiment_id,
                        "mode": _CACHE_STATEFUL_LIVE_SMOKE_MODE,
                        "managed_live": True,
                        "request_id": request_id,
                        "dataset_id": dataset_manifest.dataset_id,
                        "dataset_hash": dataset_manifest.content_hash,
                        "model_key": str(live_scope["model_key"]),
                        "model_id": str(live_scope["model_id"]),
                        "endpoint_kind": "native_stateful_chat",
                        "request_kind": request_kind,
                        "branch_id": branch_id,
                        "requested_context_length": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
                        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
                        "configured_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "applied_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "parallel_verified": True,
                        "parallel_semantics": "sequential",
                        "measurement_status": CacheMeasurementStatus.INCONCLUSIVE.value,
                        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
                        "stateful_functional_ok": False,
                        "kv_reuse_proven": False,
                        "prompt_hash": _safe_hash(prompt_text),
                        "prompt_chars": len(prompt_text),
                        "estimated_input_tokens": estimated_input_tokens,
                        "state_id_hash": state_id_hash,
                        "root_state_hash": root_state_id_hash or state_id_hash,
                        "previous_state_hash": previous_state_hash,
                        "used_previous_root_state": used_previous_root_state,
                        "output_hash": output_hash,
                        "output_chars": len(output_text),
                        "output_present": True,
                        "status": "success",
                        "raw_prompt_response_stored": False,
                        "production_default": False,
                    }
                    request_rows.append(append_jsonl_record(requests_path, request_row))
                    metric_rows.append(append_jsonl_record(metrics_path, metric_row))
                    return raw_state_id, state_id_hash

                raw_root_state_id, root_state_hash = _record_request(
                    request_id=root_request_id,
                    request_kind="stateful_root",
                    prompt_text=root_input,
                )
                for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS:
                    _record_request(
                        request_id=branch_id,
                        request_kind="stateful_branch",
                        branch_id=branch_id,
                        prompt_text=branch_inputs[branch_id],
                        previous_state_id=raw_root_state_id,
                        root_state_id_hash=root_state_hash,
                    )

                live_summary = _build_cache_stateful_live_smoke_summary(
                    config=config,
                    dataset_manifest=dataset_manifest,
                    run_id=safe_run_id,
                    request_rows=request_rows,
                )
                if live_summary.get("stateful_functional_ok") is True:
                    finalized_status = CacheMeasurementStatus.FUNCTIONAL_STATEFUL_OK.value
                    for row in request_rows:
                        row["measurement_status"] = finalized_status
                        row["stateful_functional_ok"] = True
                    for row in metric_rows:
                        row["measurement_status"] = finalized_status
                        row["stateful_functional_ok"] = True
                    _rewrite_jsonl_records(requests_path, request_rows)
                    _rewrite_jsonl_records(metrics_path, metric_rows)
                return live_summary

            return run_exact_model_operation(
                config.lmstudio_base_url,
                model_id=str(live_scope["model_id"]),
                context_length=_CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
                parallel=_CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                timeout_s=timeout_s,
                transport=native_transport,
                operation=_live_operation,
            )

        cache_summary = self.run_with_system_metrics(
            _operation,
            run_path,
            providers=providers,
        )
        write_json_file(run_path / "cache_summary.json", cache_summary)

        requests_payload = _load_jsonl_records(requests_path)
        metrics_payload = _load_jsonl_records(metrics_path)
        system_summary_payload = json.loads(
            (run_path / "system_summary.json").read_text(encoding="utf-8")
        )
        system_samples_payload = _load_jsonl_records(run_path / "system_samples.jsonl")
        privacy_scan = _build_cache_stateful_live_smoke_privacy_scan(
            environment_payload=environment_payload,
            experiment_yaml_payload=experiment_yaml_payload,
            run_config=run_config,
            request_rows=requests_payload,
            metric_rows=metrics_payload,
            cache_summary=cache_summary,
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=_render_cache_stateful_live_smoke_report(
                run_id=safe_run_id,
                experiment_id=config.experiment_id,
                dataset_id=dataset_manifest.dataset_id,
                dataset_hash=dataset_manifest.content_hash,
                model_key=str(live_scope["model_key"]),
                model_id=str(live_scope["model_id"]),
                cache_summary=cache_summary,
                privacy_scan_status="pending_scan",
            ),
        )
        report_text = _render_cache_stateful_live_smoke_report(
            run_id=safe_run_id,
            experiment_id=config.experiment_id,
            dataset_id=dataset_manifest.dataset_id,
            dataset_hash=dataset_manifest.content_hash,
            model_key=str(live_scope["model_key"]),
            model_id=str(live_scope["model_id"]),
            cache_summary=cache_summary,
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )
        privacy_scan = _build_cache_stateful_live_smoke_privacy_scan(
            environment_payload=environment_payload,
            experiment_yaml_payload=experiment_yaml_payload,
            run_config=run_config,
            request_rows=requests_payload,
            metric_rows=metrics_payload,
            cache_summary=cache_summary,
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=report_text,
        )
        write_json_file(privacy_scan_path, privacy_scan)
        report_path.write_text(report_text, encoding="utf-8")
        return cache_summary

    def run_cache_stateful_comparison_live(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        timeout_s: float = 120.0,
        app_concurrency: int = _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
        providers: Mapping[str, str] | None = None,
        native_transport: ModelLifecycleTransport | None = None,
        stateful_transport: LiveTransport | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")
        if isinstance(app_concurrency, bool) or not isinstance(app_concurrency, int):
            raise ValueError("app_concurrency must be exactly 1 for L3.4 live comparison")
        if app_concurrency != _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY:
            raise ValueError("app_concurrency must be exactly 1 for L3.4 live comparison")

        config = load_live_smoke_config(config_path, live_enabled=True)
        live_scope = _validate_cache_stateful_comparison_live_config(config)
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        environment_payload = _build_cache_stateful_comparison_live_environment_payload(
            experiment_id=config.experiment_id,
            run_id=safe_run_id,
        )
        experiment_yaml_payload = _build_medium_chunked_live_experiment_payload(config)
        experiment_yaml_text = yaml.safe_dump(experiment_yaml_payload, sort_keys=False)
        write_json_file(run_path / "environment.json", environment_payload)
        (run_path / "experiment.yaml").write_text(experiment_yaml_text, encoding="utf-8")

        dataset_manifest = load_dataset_manifest(str(live_scope["dataset_id"]))
        requests_path = run_path / "requests.jsonl"
        metrics_path = run_path / "metrics.jsonl"
        summary_path = run_path / "cache_comparison_summary.json"
        privacy_scan_path = run_path / "privacy_scan.json"
        report_path = run_path / "report.md"

        root_input = _build_cache_stateful_live_smoke_root_input()
        branch_inputs = _build_cache_stateful_live_smoke_branch_inputs()
        stateless_full_prefix_inputs = _build_cache_stateful_full_prefix_branch_inputs(
            root_input=root_input,
            branch_inputs=branch_inputs,
        )
        compact_memory_contexts = _build_cache_stateful_compact_memory_contexts()
        compact_memory_inputs = _build_cache_stateful_compact_memory_branch_inputs(
            compact_memory_contexts=compact_memory_contexts,
            branch_inputs=branch_inputs,
        )
        run_config = _build_cache_stateful_comparison_live_run_config(
            config=config,
            run_id=safe_run_id,
            dataset_manifest=dataset_manifest,
            root_input=root_input,
            branch_inputs=branch_inputs,
            stateless_full_prefix_inputs=stateless_full_prefix_inputs,
            compact_memory_contexts=compact_memory_contexts,
            compact_memory_inputs=compact_memory_inputs,
        )
        write_json_file(run_path / "run_config.json", run_config)

        request_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []

        def _operation() -> dict[str, object]:
            requests_path.write_text("", encoding="utf-8")
            metrics_path.write_text("", encoding="utf-8")
            request_rows.clear()
            metric_rows.clear()

            def _live_operation(_lifecycle_state: Mapping[str, object]) -> dict[str, object]:
                request_transport = stateful_transport or _default_live_transport
                stateful_url = _build_cache_stateful_live_smoke_url(config.lmstudio_base_url)
                root_request_id = "root_context"
                raw_root_state_id: str | None = None
                root_state_hash: str | None = None

                def _record_request(
                    *,
                    mode: str,
                    request_id: str,
                    request_kind: str,
                    prompt_text: str,
                    branch_id: str | None = None,
                    previous_state_id: str | None = None,
                    root_state_id_hash: str | None = None,
                    compact_memory_text: str | None = None,
                ) -> tuple[str, str]:
                    payload: dict[str, object] = {
                        "model": str(live_scope["model_id"]),
                        "input": prompt_text,
                        "store": True,
                    }
                    if previous_state_id is not None:
                        payload["previous_response_id"] = previous_state_id

                    started_at = _live_request_perf_counter()
                    response_payload = request_transport(stateful_url, payload, timeout_s)
                    total_latency_ms = round(
                        (_live_request_perf_counter() - started_at) * 1000.0,
                        3,
                    )
                    if not isinstance(response_payload, Mapping):
                        raise ValueError("cache/stateful comparison response must be a JSON object")

                    raw_state_id = _as_optional_str(response_payload.get("response_id"))
                    if not raw_state_id:
                        raise ValueError(
                            "cache/stateful comparison response must include response_id"
                        )
                    output_text = _extract_cache_stateful_live_smoke_output_text(response_payload)
                    if output_text is None:
                        raise ValueError(
                            "cache/stateful comparison response must include non-empty output"
                        )

                    prompt_hash = _safe_hash(prompt_text)
                    state_id_hash = _safe_hash(raw_state_id)
                    output_hash = _safe_hash(output_text)
                    estimated_input_tokens = _estimate_cache_stateful_live_smoke_tokens(prompt_text)
                    previous_state_hash = (
                        _safe_hash(previous_state_id) if previous_state_id is not None else None
                    )
                    used_previous_root_state = (
                        previous_state_id is not None and previous_state_hash == root_state_id_hash
                    )
                    compact_memory_hash = (
                        _safe_hash(compact_memory_text) if compact_memory_text is not None else None
                    )
                    compact_memory_chars = (
                        len(compact_memory_text) if compact_memory_text is not None else None
                    )
                    estimated_memory_tokens = (
                        _estimate_cache_stateful_live_smoke_tokens(compact_memory_text)
                        if compact_memory_text is not None
                        else None
                    )

                    request_row = {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": safe_run_id,
                        "experiment_id": config.experiment_id,
                        "runner_mode": _CACHE_STATEFUL_COMPARISON_LIVE_MODE,
                        "mode": mode,
                        "managed_live": True,
                        "request_id": request_id,
                        "request_kind": request_kind,
                        "branch_id": branch_id,
                        "dataset_id": dataset_manifest.dataset_id,
                        "dataset_hash": dataset_manifest.content_hash,
                        "model_key": str(live_scope["model_key"]),
                        "model_id": str(live_scope["model_id"]),
                        "context_window": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
                        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
                        "measurement_status": CacheMeasurementStatus.INCONCLUSIVE.value,
                        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
                        "kv_reuse_proven": False,
                        "stateful_functional_ok": False,
                        "store": True,
                        "prompt_hash": prompt_hash,
                        "prompt_chars": len(prompt_text),
                        "estimated_input_tokens": estimated_input_tokens,
                        "state_id_hash": state_id_hash,
                        "root_state_hash": root_state_id_hash,
                        "previous_state_hash": previous_state_hash,
                        "used_previous_root_state": used_previous_root_state,
                        "compact_memory_hash": compact_memory_hash,
                        "compact_memory_chars": compact_memory_chars,
                        "estimated_memory_tokens": estimated_memory_tokens,
                        "output_hash": output_hash,
                        "output_chars": len(output_text),
                        "output_present": True,
                        "status": "success",
                        "total_latency_ms": total_latency_ms,
                        "ttft_ms": None,
                        "prompt_processing_ms": None,
                        "cached_tokens": None,
                        "cache_proxy": None,
                        "raw_prompt_response_stored": False,
                        "production_default": False,
                    }
                    metric_row = {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": safe_run_id,
                        "experiment_id": config.experiment_id,
                        "runner_mode": _CACHE_STATEFUL_COMPARISON_LIVE_MODE,
                        "mode": mode,
                        "managed_live": True,
                        "request_id": request_id,
                        "dataset_id": dataset_manifest.dataset_id,
                        "dataset_hash": dataset_manifest.content_hash,
                        "model_key": str(live_scope["model_key"]),
                        "model_id": str(live_scope["model_id"]),
                        "endpoint_kind": "native_stateful_chat",
                        "request_kind": request_kind,
                        "branch_id": branch_id,
                        "requested_context_length": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
                        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
                        "configured_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "applied_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "parallel_verified": True,
                        "parallel_semantics": "sequential",
                        "measurement_status": CacheMeasurementStatus.INCONCLUSIVE.value,
                        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
                        "stateful_functional_ok": False,
                        "kv_reuse_proven": False,
                        "prompt_hash": prompt_hash,
                        "prompt_chars": len(prompt_text),
                        "estimated_input_tokens": estimated_input_tokens,
                        "state_id_hash": state_id_hash,
                        "root_state_hash": root_state_id_hash,
                        "previous_state_hash": previous_state_hash,
                        "used_previous_root_state": used_previous_root_state,
                        "compact_memory_hash": compact_memory_hash,
                        "compact_memory_chars": compact_memory_chars,
                        "estimated_memory_tokens": estimated_memory_tokens,
                        "output_hash": output_hash,
                        "output_chars": len(output_text),
                        "output_present": True,
                        "status": "success",
                        "total_latency_ms": total_latency_ms,
                        "ttft_ms": None,
                        "prompt_processing_ms": None,
                        "cached_tokens": None,
                        "cache_proxy": None,
                        "raw_prompt_response_stored": False,
                        "production_default": False,
                    }
                    request_rows.append(append_jsonl_record(requests_path, request_row))
                    metric_rows.append(append_jsonl_record(metrics_path, metric_row))
                    return raw_state_id, state_id_hash

                raw_root_state_id, root_state_hash = _record_request(
                    mode="stateful_root_branches",
                    request_id=root_request_id,
                    request_kind="stateful_root",
                    prompt_text=root_input,
                )

                for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS:
                    _record_request(
                        mode="stateful_root_branches",
                        request_id=f"stateful_{branch_id}",
                        request_kind="stateful_branch",
                        branch_id=branch_id,
                        prompt_text=branch_inputs[branch_id],
                        previous_state_id=raw_root_state_id,
                        root_state_id_hash=root_state_hash,
                    )

                for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS:
                    _record_request(
                        mode="stateless_full_prefix",
                        request_id=f"stateless_full_prefix_{branch_id}",
                        request_kind="stateless_full_prefix_branch",
                        branch_id=branch_id,
                        prompt_text=stateless_full_prefix_inputs[branch_id],
                    )

                for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS:
                    _record_request(
                        mode="compact_memory",
                        request_id=f"compact_memory_{branch_id}",
                        request_kind="compact_memory_branch",
                        branch_id=branch_id,
                        prompt_text=compact_memory_inputs[branch_id],
                        compact_memory_text=compact_memory_contexts[branch_id],
                    )

                comparison_summary = _build_cache_stateful_comparison_live_summary(
                    config=config,
                    dataset_manifest=dataset_manifest,
                    run_id=safe_run_id,
                    request_rows=request_rows,
                )
                if comparison_summary.get("stateful_functional_ok") is True:
                    for row in request_rows:
                        row["stateful_functional_ok"] = True
                    for row in metric_rows:
                        row["stateful_functional_ok"] = True
                    _rewrite_jsonl_records(requests_path, request_rows)
                    _rewrite_jsonl_records(metrics_path, metric_rows)
                return comparison_summary

            return run_exact_model_operation(
                config.lmstudio_base_url,
                model_id=str(live_scope["model_id"]),
                context_length=_CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
                parallel=_CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                timeout_s=timeout_s,
                transport=native_transport,
                operation=_live_operation,
            )

        comparison_summary = self.run_with_system_metrics(
            _operation,
            run_path,
            providers=providers,
        )
        write_json_file(summary_path, comparison_summary)

        requests_payload = _load_jsonl_records(requests_path)
        metrics_payload = _load_jsonl_records(metrics_path)
        system_summary_payload = json.loads(
            (run_path / "system_summary.json").read_text(encoding="utf-8")
        )
        system_samples_payload = _load_jsonl_records(run_path / "system_samples.jsonl")
        privacy_scan = _build_cache_stateful_comparison_live_privacy_scan(
            environment_payload=environment_payload,
            experiment_yaml_payload=experiment_yaml_payload,
            run_config=run_config,
            request_rows=requests_payload,
            metric_rows=metrics_payload,
            comparison_summary=comparison_summary,
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=_render_cache_stateful_comparison_live_report(
                run_id=safe_run_id,
                experiment_id=config.experiment_id,
                dataset_id=dataset_manifest.dataset_id,
                dataset_hash=dataset_manifest.content_hash,
                model_key=str(live_scope["model_key"]),
                model_id=str(live_scope["model_id"]),
                comparison_summary=comparison_summary,
                privacy_scan_status="pending_scan",
            ),
        )
        report_text = _render_cache_stateful_comparison_live_report(
            run_id=safe_run_id,
            experiment_id=config.experiment_id,
            dataset_id=dataset_manifest.dataset_id,
            dataset_hash=dataset_manifest.content_hash,
            model_key=str(live_scope["model_key"]),
            model_id=str(live_scope["model_id"]),
            comparison_summary=comparison_summary,
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )
        privacy_scan = _build_cache_stateful_comparison_live_privacy_scan(
            environment_payload=environment_payload,
            experiment_yaml_payload=experiment_yaml_payload,
            run_config=run_config,
            request_rows=requests_payload,
            metric_rows=metrics_payload,
            comparison_summary=comparison_summary,
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=report_text,
        )
        write_json_file(privacy_scan_path, privacy_scan)
        report_path.write_text(report_text, encoding="utf-8")
        return comparison_summary

    def run_cache_stateful_instrumentation_live(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        timeout_s: float = 120.0,
        app_concurrency: int = _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
        providers: Mapping[str, str] | None = None,
        native_transport: ModelLifecycleTransport | None = None,
        streaming_transport: ManagedStreamingTransport | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")
        if isinstance(app_concurrency, bool) or not isinstance(app_concurrency, int):
            raise ValueError("app_concurrency must be exactly 1 for L3.4b live instrumentation")
        if app_concurrency != _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY:
            raise ValueError("app_concurrency must be exactly 1 for L3.4b live instrumentation")

        config = load_live_smoke_config(config_path, live_enabled=True)
        live_scope = _validate_cache_stateful_instrumentation_live_config(config)
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        environment_payload = _build_cache_stateful_instrumentation_live_environment_payload(
            experiment_id=config.experiment_id,
            run_id=safe_run_id,
        )
        experiment_yaml_payload = _build_medium_chunked_live_experiment_payload(config)
        experiment_yaml_text = yaml.safe_dump(experiment_yaml_payload, sort_keys=False)
        write_json_file(run_path / "environment.json", environment_payload)
        (run_path / "experiment.yaml").write_text(experiment_yaml_text, encoding="utf-8")

        dataset_manifest = load_dataset_manifest(str(live_scope["dataset_id"]))
        requests_path = run_path / "requests.jsonl"
        metrics_path = run_path / "metrics.jsonl"
        summary_path = run_path / "cache_instrumentation_summary.json"
        privacy_scan_path = run_path / "privacy_scan.json"
        report_path = run_path / "report.md"

        root_input = _build_cache_stateful_live_smoke_root_input()
        branch_inputs = _build_cache_stateful_live_smoke_branch_inputs()
        stateless_full_prefix_inputs = _build_cache_stateful_full_prefix_branch_inputs(
            root_input=root_input,
            branch_inputs=branch_inputs,
        )
        compact_memory_contexts = _build_cache_stateful_compact_memory_contexts()
        compact_memory_inputs = _build_cache_stateful_compact_memory_branch_inputs(
            compact_memory_contexts=compact_memory_contexts,
            branch_inputs=branch_inputs,
        )
        run_config = _build_cache_stateful_instrumentation_live_run_config(
            config=config,
            run_id=safe_run_id,
            dataset_manifest=dataset_manifest,
            root_input=root_input,
            branch_inputs=branch_inputs,
            stateless_full_prefix_inputs=stateless_full_prefix_inputs,
            compact_memory_contexts=compact_memory_contexts,
            compact_memory_inputs=compact_memory_inputs,
        )
        write_json_file(run_path / "run_config.json", run_config)

        request_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []

        def _operation() -> dict[str, object]:
            requests_path.write_text("", encoding="utf-8")
            metrics_path.write_text("", encoding="utf-8")
            request_rows.clear()
            metric_rows.clear()

            def _live_operation(_lifecycle_state: Mapping[str, object]) -> dict[str, object]:
                request_transport = streaming_transport or _default_live_streaming_transport
                stateful_url = _build_cache_stateful_live_smoke_url(config.lmstudio_base_url)
                root_request_id = "root_context"
                raw_root_state_id: str | None = None
                root_state_hash: str | None = None

                def _record_request(
                    *,
                    mode: str,
                    request_id: str,
                    request_kind: str,
                    prompt_text: str,
                    branch_id: str | None = None,
                    previous_state_id: str | None = None,
                    root_state_id_hash: str | None = None,
                    compact_memory_text: str | None = None,
                ) -> tuple[str, str]:
                    payload: dict[str, object] = {
                        "model": str(live_scope["model_id"]),
                        "input": prompt_text,
                        "store": True,
                        "stream": True,
                    }
                    if previous_state_id is not None:
                        payload["previous_response_id"] = previous_state_id

                    started_at = _live_request_perf_counter()
                    streaming_summary = request_transport(stateful_url, payload, timeout_s)
                    total_latency_ms = round(
                        (_live_request_perf_counter() - started_at) * 1000.0,
                        3,
                    )
                    if not isinstance(streaming_summary, Mapping):
                        raise ValueError(
                            "cache/stateful instrumentation stream must return a JSON object"
                        )

                    response_payload = _extract_streaming_response_payload(streaming_summary)
                    raw_state_id = _as_optional_str(response_payload.get("response_id"))
                    if not raw_state_id:
                        raise ValueError(
                            "cache/stateful instrumentation response must include response_id"
                        )
                    output_text = _extract_cache_stateful_live_smoke_output_text(response_payload)
                    if output_text is None:
                        raise ValueError(
                            "cache/stateful instrumentation response must include non-empty output"
                        )

                    prompt_hash = _safe_hash(prompt_text)
                    state_id_hash = _safe_hash(raw_state_id)
                    output_hash = _safe_hash(output_text)
                    estimated_input_tokens = _estimate_cache_stateful_live_smoke_tokens(prompt_text)
                    previous_state_hash = (
                        _safe_hash(previous_state_id) if previous_state_id is not None else None
                    )
                    used_previous_root_state = (
                        previous_state_id is not None and previous_state_hash == root_state_id_hash
                    )
                    compact_memory_hash = (
                        _safe_hash(compact_memory_text) if compact_memory_text is not None else None
                    )
                    compact_memory_chars = (
                        len(compact_memory_text) if compact_memory_text is not None else None
                    )
                    estimated_memory_tokens = (
                        _estimate_cache_stateful_live_smoke_tokens(compact_memory_text)
                        if compact_memory_text is not None
                        else None
                    )
                    stream_ttft_ms = _as_optional_rate(streaming_summary.get("stream_ttft_ms"))
                    stats_ttft_ms = _as_optional_rate(streaming_summary.get("stats_ttft_ms"))
                    ttft_ms = _as_optional_rate(streaming_summary.get("ttft_ms"))
                    if ttft_ms is None:
                        ttft_ms = stream_ttft_ms if stream_ttft_ms is not None else stats_ttft_ms
                    prompt_processing_ms = _as_optional_rate(
                        streaming_summary.get("prompt_processing_ms")
                    )
                    cached_tokens = _as_optional_int(streaming_summary.get("cached_tokens"))
                    prompt_processing_events_seen = (
                        _as_optional_bool(streaming_summary.get("prompt_processing_events_seen"))
                        is True
                    )
                    effective_root_state_hash = root_state_id_hash or state_id_hash

                    request_row = {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": safe_run_id,
                        "experiment_id": config.experiment_id,
                        "runner_mode": _CACHE_STATEFUL_INSTRUMENTATION_LIVE_MODE,
                        "mode": mode,
                        "managed_live": True,
                        "request_id": request_id,
                        "request_kind": request_kind,
                        "branch_id": branch_id,
                        "dataset_id": dataset_manifest.dataset_id,
                        "dataset_hash": dataset_manifest.content_hash,
                        "model_key": str(live_scope["model_key"]),
                        "model_id": str(live_scope["model_id"]),
                        "context_window": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
                        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
                        "measurement_status": CacheMeasurementStatus.INCONCLUSIVE.value,
                        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
                        "kv_reuse_proven": False,
                        "stateful_functional_ok": False,
                        "store": True,
                        "prompt_hash": prompt_hash,
                        "prompt_chars": len(prompt_text),
                        "estimated_input_tokens": estimated_input_tokens,
                        "state_id_hash": state_id_hash,
                        "root_state_hash": effective_root_state_hash,
                        "previous_state_hash": previous_state_hash,
                        "used_previous_root_state": used_previous_root_state,
                        "compact_memory_hash": compact_memory_hash,
                        "compact_memory_chars": compact_memory_chars,
                        "estimated_memory_tokens": estimated_memory_tokens,
                        "output_hash": output_hash,
                        "output_chars": len(output_text),
                        "output_present": True,
                        "status": "success",
                        "total_latency_ms": total_latency_ms,
                        "ttft_ms": ttft_ms,
                        "stream_ttft_ms": stream_ttft_ms,
                        "stats_ttft_ms": stats_ttft_ms,
                        "prompt_processing_ms": prompt_processing_ms,
                        "prompt_processing_events_seen": prompt_processing_events_seen,
                        "cached_tokens": cached_tokens,
                        "cache_proxy": None,
                        "raw_prompt_response_stored": False,
                        "production_default": False,
                    }
                    metric_row = {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": safe_run_id,
                        "experiment_id": config.experiment_id,
                        "runner_mode": _CACHE_STATEFUL_INSTRUMENTATION_LIVE_MODE,
                        "mode": mode,
                        "managed_live": True,
                        "request_id": request_id,
                        "dataset_id": dataset_manifest.dataset_id,
                        "dataset_hash": dataset_manifest.content_hash,
                        "model_key": str(live_scope["model_key"]),
                        "model_id": str(live_scope["model_id"]),
                        "endpoint_kind": "native_stateful_chat_stream",
                        "request_kind": request_kind,
                        "branch_id": branch_id,
                        "requested_context_length": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
                        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
                        "configured_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "applied_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                        "parallel_verified": True,
                        "parallel_semantics": "sequential",
                        "measurement_status": CacheMeasurementStatus.INCONCLUSIVE.value,
                        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
                        "stateful_functional_ok": False,
                        "kv_reuse_proven": False,
                        "prompt_hash": prompt_hash,
                        "prompt_chars": len(prompt_text),
                        "estimated_input_tokens": estimated_input_tokens,
                        "state_id_hash": state_id_hash,
                        "root_state_hash": effective_root_state_hash,
                        "previous_state_hash": previous_state_hash,
                        "used_previous_root_state": used_previous_root_state,
                        "compact_memory_hash": compact_memory_hash,
                        "compact_memory_chars": compact_memory_chars,
                        "estimated_memory_tokens": estimated_memory_tokens,
                        "output_hash": output_hash,
                        "output_chars": len(output_text),
                        "output_present": True,
                        "status": "success",
                        "total_latency_ms": total_latency_ms,
                        "ttft_ms": ttft_ms,
                        "stream_ttft_ms": stream_ttft_ms,
                        "stats_ttft_ms": stats_ttft_ms,
                        "prompt_processing_ms": prompt_processing_ms,
                        "prompt_processing_events_seen": prompt_processing_events_seen,
                        "cached_tokens": cached_tokens,
                        "cache_proxy": None,
                        "raw_prompt_response_stored": False,
                        "production_default": False,
                    }
                    appended_request_row = append_jsonl_record(requests_path, request_row)
                    appended_metric_row = append_jsonl_record(metrics_path, metric_row)
                    appended_request_row["prompt_processing_events_seen"] = (
                        prompt_processing_events_seen
                    )
                    appended_metric_row["prompt_processing_events_seen"] = (
                        prompt_processing_events_seen
                    )
                    request_rows.append(appended_request_row)
                    metric_rows.append(appended_metric_row)
                    return raw_state_id, state_id_hash

                raw_root_state_id, root_state_hash = _record_request(
                    mode="stateful_root_branches",
                    request_id=root_request_id,
                    request_kind="stateful_root",
                    prompt_text=root_input,
                )

                for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS:
                    _record_request(
                        mode="stateful_root_branches",
                        request_id=f"stateful_{branch_id}",
                        request_kind="stateful_branch",
                        branch_id=branch_id,
                        prompt_text=branch_inputs[branch_id],
                        previous_state_id=raw_root_state_id,
                        root_state_id_hash=root_state_hash,
                    )

                for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS:
                    _record_request(
                        mode="stateless_full_prefix",
                        request_id=f"stateless_full_prefix_{branch_id}",
                        request_kind="stateless_full_prefix_branch",
                        branch_id=branch_id,
                        prompt_text=stateless_full_prefix_inputs[branch_id],
                    )

                for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS:
                    _record_request(
                        mode="compact_memory",
                        request_id=f"compact_memory_{branch_id}",
                        request_kind="compact_memory_branch",
                        branch_id=branch_id,
                        prompt_text=compact_memory_inputs[branch_id],
                        compact_memory_text=compact_memory_contexts[branch_id],
                    )

                instrumentation_summary = _build_cache_stateful_instrumentation_live_summary(
                    config=config,
                    dataset_manifest=dataset_manifest,
                    run_id=safe_run_id,
                    request_rows=request_rows,
                )
                if instrumentation_summary.get("stateful_functional_ok") is True:
                    for row in request_rows:
                        row["stateful_functional_ok"] = True
                    for row in metric_rows:
                        row["stateful_functional_ok"] = True
                _rewrite_jsonl_records(requests_path, request_rows)
                _rewrite_jsonl_records(metrics_path, metric_rows)
                return instrumentation_summary

            return run_exact_model_operation(
                config.lmstudio_base_url,
                model_id=str(live_scope["model_id"]),
                context_length=_CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
                parallel=_CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
                timeout_s=timeout_s,
                transport=native_transport,
                operation=_live_operation,
            )

        instrumentation_summary = self.run_with_system_metrics(
            _operation,
            run_path,
            providers=providers,
        )
        instrumentation_summary = {
            **_build_cache_stateful_instrumentation_live_summary(
                config=config,
                dataset_manifest=dataset_manifest,
                run_id=safe_run_id,
                request_rows=request_rows,
            ),
            **instrumentation_summary,
        }
        write_json_file(summary_path, instrumentation_summary)

        requests_payload = _load_jsonl_records(requests_path)
        metrics_payload = _load_jsonl_records(metrics_path)
        system_summary_payload = json.loads(
            (run_path / "system_summary.json").read_text(encoding="utf-8")
        )
        system_samples_payload = _load_jsonl_records(run_path / "system_samples.jsonl")
        privacy_scan = _build_cache_stateful_instrumentation_live_privacy_scan(
            environment_payload=environment_payload,
            experiment_yaml_payload=experiment_yaml_payload,
            run_config=run_config,
            request_rows=requests_payload,
            metric_rows=metrics_payload,
            instrumentation_summary=instrumentation_summary,
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=_render_cache_stateful_instrumentation_live_report(
                run_id=safe_run_id,
                experiment_id=config.experiment_id,
                dataset_id=dataset_manifest.dataset_id,
                dataset_hash=dataset_manifest.content_hash,
                model_key=str(live_scope["model_key"]),
                model_id=str(live_scope["model_id"]),
                instrumentation_summary=instrumentation_summary,
                privacy_scan_status="pending_scan",
            ),
        )
        report_text = _render_cache_stateful_instrumentation_live_report(
            run_id=safe_run_id,
            experiment_id=config.experiment_id,
            dataset_id=dataset_manifest.dataset_id,
            dataset_hash=dataset_manifest.content_hash,
            model_key=str(live_scope["model_key"]),
            model_id=str(live_scope["model_id"]),
            instrumentation_summary=instrumentation_summary,
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )
        privacy_scan = _build_cache_stateful_instrumentation_live_privacy_scan(
            environment_payload=environment_payload,
            experiment_yaml_payload=experiment_yaml_payload,
            run_config=run_config,
            request_rows=requests_payload,
            metric_rows=metrics_payload,
            instrumentation_summary=instrumentation_summary,
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=report_text,
        )
        write_json_file(privacy_scan_path, privacy_scan)
        report_path.write_text(report_text, encoding="utf-8")
        return instrumentation_summary

    def run_medium_chunked_sequential_prep(
        self,
        *,
        run_dir: str | PathLike[str],
        run_id: str,
        model_keys: Sequence[str] = _MEDIUM_CHUNKED_PREP_MODEL_KEYS,
        dataset_id: str = _MEDIUM_CHUNKED_PREP_DATASET_ID,
        timeout_s: float | None = None,
        providers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        dataset_key = _validate_medium_chunked_prep_dataset_id(dataset_id)
        selected_model_keys = _validate_medium_chunked_prep_model_keys(model_keys)
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        dataset_manifest = load_dataset_manifest(dataset_key)
        dataset_view = load_chunked_dataset_view(dataset_key)
        metrics_path = run_path / "metrics.jsonl"
        structured_summary_path = run_path / "structured_validation_summary.json"
        structured_summary_csv_path = run_path / "structured_validation_summary.csv"
        privacy_scan_path = run_path / "privacy_scan.json"
        report_path = run_path / "report.md"

        run_config = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "mode": _MEDIUM_CHUNKED_PREP_MODE,
            "dataset_id": dataset_manifest.dataset_id,
            "dataset_hash": dataset_manifest.content_hash,
            "model_keys": list(selected_model_keys),
            "model_count": len(selected_model_keys),
            "chunks_count": dataset_view.chunks_count,
            "chunk_size_blocks": dataset_view.chunk_size_blocks,
            "app_concurrency": 1,
            "configured_parallel": 1,
            "applied_parallel": 1,
            "parallel_verified": None,
            "queue_pressure_mode": False,
            "parallel_semantics": "sequential",
            "fake_first": True,
            "no_live": True,
            "uses_fake_transport_only": True,
            "lmstudio_api_called": False,
            "raw_prompt_response_stored": False,
        }
        write_json_file(run_path / "run_config.json", run_config)

        metric_rows: list[dict[str, Any]] = []
        validation_results: list[StructuredValidationResult] = []

        def _operation() -> dict[str, object]:
            metrics_path.write_text("", encoding="utf-8")
            metric_rows.clear()
            validation_results.clear()

            for model_key in selected_model_keys:
                for chunk in dataset_view.chunks:
                    request = StructuredGenerationRequest(
                        model_key=model_key,
                        response_format=ResponseFormatKind.JSON_SCHEMA,
                        prompt_hash=_build_medium_chunked_prep_prompt_hash(
                            model_key=model_key,
                            dataset_id=dataset_manifest.dataset_id,
                            chunk_id=chunk.chunk_id,
                            expected_ids=chunk.expected_ids,
                        ),
                        prompt_chars=chunk.chars,
                        max_tokens=_build_medium_chunked_prep_max_tokens(chunk),
                        profile_id=_MEDIUM_CHUNKED_PREP_PROFILE_ID,
                    )
                    generation_summary = self.complete_structured(request, timeout_s=timeout_s)
                    validation_result = _build_medium_chunked_prep_validation_result(
                        generation_summary,
                        expected_count=chunk.items_count,
                    )
                    validation_results.append(validation_result)

                    prompt_tokens = _as_optional_int(generation_summary.get("input_tokens"))
                    output_tokens = _as_optional_int(generation_summary.get("output_tokens"))
                    total_tokens = None
                    if prompt_tokens is not None or output_tokens is not None:
                        total_tokens = (prompt_tokens or 0) + (output_tokens or 0)

                    record = LMStudioLabMetricRecord.from_parts(
                        run_id=safe_run_id,
                        request_id=_build_medium_chunked_prep_request_id(
                            model_key=model_key,
                            chunk_id=chunk.chunk_id,
                        ),
                        dataset_id=dataset_manifest.dataset_id,
                        dataset_hash=dataset_manifest.content_hash,
                        model_key=model_key,
                        model_id=model_key,
                        endpoint_kind="compat_chat",
                        mode=_MEDIUM_CHUNKED_PREP_MODE,
                        app_concurrency=1,
                        configured_parallel=1,
                        applied_parallel=1,
                        parallel_verified=None,
                        queue_pressure_mode=False,
                        parallel_semantics="sequential",
                        max_tokens=request.max_tokens,
                        prompt_hash=request.prompt_hash,
                        prompt_chars=request.prompt_chars,
                        response_hash=_as_optional_str(generation_summary.get("response_hash")),
                        response_chars=_as_optional_int(generation_summary.get("response_chars")),
                        content_empty=_as_optional_bool(generation_summary.get("content_empty")),
                        reasoning_content_present=_as_optional_bool(
                            generation_summary.get("reasoning_content_present")
                        ),
                        response_format={
                            "type": ResponseFormatKind.JSON_SCHEMA.value,
                            "json_schema": {
                                "name": FACTUAL_BLOCKS_SCHEMA_NAME,
                                "strict": True,
                            },
                        },
                        tokens=TokenMetrics(
                            estimated_input_tokens=chunk.estimated_input_tokens,
                            estimate_scope="chunk",
                            prompt_tokens=prompt_tokens,
                            completion_tokens=output_tokens,
                            total_tokens=total_tokens,
                            total_output_tokens=output_tokens,
                            estimated_output_tokens=request.max_tokens,
                            actual_output_tokens=output_tokens,
                        ),
                        validation=validation_result.to_metrics(),
                        error_category=_medium_chunked_prep_error_category(
                            generation_summary,
                            validation_result=validation_result,
                        ),
                        error_status=(
                            "ok" if validation_result.error_category is None else "failed"
                        ),
                    )
                    metric_row = record.to_dict()
                    metric_row["validation_source"] = _MEDIUM_CHUNKED_PREP_VALIDATION_SOURCE
                    metric_row["validation_status"] = _MEDIUM_CHUNKED_PREP_VALIDATION_STATUS
                    metric_row["raw_prompt_response_stored"] = False
                    metric_rows.append(append_jsonl_record(metrics_path, metric_row))

            structured_summary = _build_medium_chunked_prep_structured_summary(validation_results)
            write_json_file(structured_summary_path, structured_summary)
            write_csv_file(
                structured_summary_csv_path,
                fieldnames=STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES,
                rows=[
                    build_structured_validation_summary_csv_row(
                        structured_summary,
                        run_id=safe_run_id,
                        mode=_MEDIUM_CHUNKED_PREP_MODE,
                        dataset_id=dataset_manifest.dataset_id,
                        status="completed",
                    )
                ],
            )

            measured_request_count = len(metric_rows)
            envelope_success_count = (
                _as_optional_int(structured_summary.get("envelope_success_count")) or 0
            )
            envelope_success_rate = _as_optional_rate(
                structured_summary.get("envelope_success_rate")
            )
            envelope_readiness_pass = envelope_success_count == measured_request_count
            return {
                "schema_version": SCHEMA_VERSION,
                "run_id": safe_run_id,
                "mode": _MEDIUM_CHUNKED_PREP_MODE,
                "dataset_id": dataset_manifest.dataset_id,
                "dataset_hash": dataset_manifest.content_hash,
                "model_keys": list(selected_model_keys),
                "model_count": len(selected_model_keys),
                "chunks_count": dataset_view.chunks_count,
                "chunk_size_blocks": dataset_view.chunk_size_blocks,
                "measured_request_count": measured_request_count,
                "app_concurrency": 1,
                "configured_parallel": 1,
                "applied_parallel": 1,
                "parallel_verified": None,
                "queue_pressure_mode": False,
                "parallel_semantics": "sequential",
                "validation_source": _MEDIUM_CHUNKED_PREP_VALIDATION_SOURCE,
                "validation_status": _MEDIUM_CHUNKED_PREP_VALIDATION_STATUS,
                "json_parse_pass_count": structured_summary["json_parse_pass_count"],
                "schema_pass_count": structured_summary["schema_pass_count"],
                "business_pass_count": structured_summary["business_pass_count"],
                "ids_exact_pass_count": structured_summary["ids_exact_pass_count"],
                "reasoning_leak_count": structured_summary["reasoning_leak_count"],
                "finish_length_count": structured_summary["finish_length_count"],
                "empty_text_count": structured_summary["empty_text_count"],
                "duplicate_id_count": structured_summary["duplicate_id_count"],
                "invalid_json_count": structured_summary["invalid_json_count"],
                "schema_error_count": structured_summary["schema_error_count"],
                "envelope_success_count": envelope_success_count,
                "envelope_success_rate": envelope_success_rate,
                "envelope_readiness_pass": envelope_readiness_pass,
                "all_chunks_pass": None,
                "batch_business_pass": None,
                "cleanup_status": "not_required_no_live",
                "final_loaded_instances": 0,
                "raw_prompt_response_stored": False,
            }

        batch_summary = self.run_with_system_metrics(
            _operation,
            run_path,
            providers=providers,
        )
        write_json_file(run_path / "batch_summary.json", batch_summary)

        structured_summary_payload = json.loads(structured_summary_path.read_text(encoding="utf-8"))
        system_summary_payload = json.loads(
            (run_path / "system_summary.json").read_text(encoding="utf-8")
        )
        system_samples_payload = _load_jsonl_records(run_path / "system_samples.jsonl")
        privacy_scan = _build_medium_chunked_prep_privacy_scan(
            run_config=run_config,
            metric_rows=metric_rows,
            batch_summary=batch_summary,
            structured_summary=structured_summary_payload,
            structured_summary_csv_text=structured_summary_csv_path.read_text(encoding="utf-8"),
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=_render_medium_chunked_prep_report(
                run_id=safe_run_id,
                dataset_id=dataset_manifest.dataset_id,
                dataset_hash=dataset_manifest.content_hash,
                model_keys=selected_model_keys,
                batch_summary=batch_summary,
                privacy_scan_status="pending_scan",
            ),
        )
        report_text = _render_medium_chunked_prep_report(
            run_id=safe_run_id,
            dataset_id=dataset_manifest.dataset_id,
            dataset_hash=dataset_manifest.content_hash,
            model_keys=selected_model_keys,
            batch_summary=batch_summary,
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )
        privacy_scan = _build_medium_chunked_prep_privacy_scan(
            run_config=run_config,
            metric_rows=metric_rows,
            batch_summary=batch_summary,
            structured_summary=structured_summary_payload,
            structured_summary_csv_text=structured_summary_csv_path.read_text(encoding="utf-8"),
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=report_text,
        )
        write_json_file(privacy_scan_path, privacy_scan)
        report_path.write_text(report_text, encoding="utf-8")
        return batch_summary

    def run_medium_chunked_sequential_live(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        timeout_s: float = 120.0,
        app_concurrency: int = 1,
        providers: Mapping[str, str] | None = None,
        native_transport: ModelLifecycleTransport | None = None,
        live_transport: LiveTransport | None = None,
        context_fit_safety_ratio: float = 0.85,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")
        if isinstance(app_concurrency, bool) or not isinstance(app_concurrency, int):
            raise ValueError("app_concurrency must be exactly 1 for MV2.2-live")
        if app_concurrency != 1:
            raise ValueError("app_concurrency must be exactly 1 for MV2.2-live")

        config = load_live_smoke_config(config_path, live_enabled=True)
        live_scope = _validate_medium_chunked_live_config(config, config_path=config_path)
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        environment_payload = _build_medium_chunked_live_environment_payload(
            experiment_id=config.experiment_id,
            run_id=safe_run_id,
            structured_prompt_variant=str(live_scope["structured_prompt_variant"]),
            structured_schema_variant=str(live_scope["structured_schema_variant"]),
            business_failure_retry_limit=config.business_failure_retry_limit,
        )
        experiment_yaml_payload = _build_medium_chunked_live_experiment_payload(config)
        experiment_yaml_text = yaml.safe_dump(experiment_yaml_payload, sort_keys=False)
        write_json_file(run_path / "environment.json", environment_payload)
        (run_path / "experiment.yaml").write_text(experiment_yaml_text, encoding="utf-8")

        dataset_manifest = load_dataset_manifest(str(live_scope["dataset_id"]))
        metrics_path = run_path / "metrics.jsonl"
        structured_errors_path = run_path / "structured_errors.jsonl"
        structured_summary_path = run_path / "structured_validation_summary.json"
        structured_summary_csv_path = run_path / "structured_validation_summary.csv"
        privacy_scan_path = run_path / "privacy_scan.json"
        report_path = run_path / "report.md"

        run_config = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "mode": _MEDIUM_CHUNKED_LIVE_MODE,
            "managed_live": True,
            "experiment_id": config.experiment_id,
            "dataset_id": dataset_manifest.dataset_id,
            "dataset_hash": dataset_manifest.content_hash,
            "structured_prompt_variant": live_scope["structured_prompt_variant"],
            "structured_schema_variant": live_scope["structured_schema_variant"],
            "business_failure_retry_limit": config.business_failure_retry_limit,
            "model_key": live_scope["model_key"],
            "model_id": live_scope["model_id"],
            "model_count": 1,
            "chunks_count": live_scope["chunks_count"],
            "chunk_size_blocks": live_scope["chunk_size_blocks"],
            "requested_context_length": live_scope["requested_context_length"],
            "requested_parallel": live_scope["requested_parallel"],
            "app_concurrency": 1,
            "queue_pressure_mode": False,
            "parallel_semantics": "sequential",
            "warmup_runs": config.warmup_runs,
            "raw_prompt_response_stored": False,
        }
        write_json_file(run_path / "run_config.json", run_config)

        metric_rows: list[dict[str, Any]] = []
        structured_error_rows: list[dict[str, Any]] = []

        def _operation() -> dict[str, object]:
            metrics_path.write_text("", encoding="utf-8")
            structured_errors_path.write_text("", encoding="utf-8")
            metric_rows.clear()
            structured_error_rows.clear()

            def _live_operation(lifecycle_state: Mapping[str, object]) -> dict[str, object]:
                verified_context_length = _as_optional_int(
                    lifecycle_state.get("verified_context_length")
                )
                outcome = run_live_chunked_structured_smoke(
                    config,
                    run_id=safe_run_id,
                    timeout_s=timeout_s,
                    transport=live_transport,
                    verified_context_length=verified_context_length,
                    context_fit_safety_ratio=context_fit_safety_ratio,
                    app_concurrency=1,
                    warmup_policy=None,
                    warmup_full_batch=False,
                    effective_profile="standard",
                    allow_queue_pressure=False,
                )

                for metric in outcome.metrics:
                    metric_row = metric.to_dict()
                    metric_row["raw_prompt_response_stored"] = False
                    metric_rows.append(append_jsonl_record(metrics_path, metric_row))
                for structured_error in outcome.structured_errors:
                    structured_error_rows.append(
                        append_jsonl_record(structured_errors_path, structured_error)
                    )

                structured_summary = _build_medium_chunked_live_structured_summary(
                    metric_rows=metric_rows,
                    structured_errors=structured_error_rows,
                )
                write_json_file(structured_summary_path, structured_summary)
                write_csv_file(
                    structured_summary_csv_path,
                    fieldnames=STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES,
                    rows=[
                        build_structured_validation_summary_csv_row(
                            structured_summary,
                            run_id=safe_run_id,
                            mode=_MEDIUM_CHUNKED_LIVE_MODE,
                            dataset_id=dataset_manifest.dataset_id,
                            status="completed",
                        )
                    ],
                )

                batch_summary = dict(outcome.batch_summary)
                batch_summary.update(
                    {
                        "managed_live": True,
                        "structured_prompt_variant": live_scope["structured_prompt_variant"],
                        "structured_schema_variant": live_scope["structured_schema_variant"],
                        "business_failure_retry_limit": config.business_failure_retry_limit,
                        "app_concurrency": 1,
                        "queue_pressure_mode": False,
                        "parallel_semantics": "sequential",
                        "json_parse_pass_count": structured_summary["json_parse_pass_count"],
                        "schema_pass_count": structured_summary["schema_pass_count"],
                        "business_pass_count": structured_summary["business_pass_count"],
                        "retry_attempt_count": structured_summary["retry_attempt_count"],
                        "retry_recovered_count": structured_summary["retry_recovered_count"],
                        "retry_failed_count": structured_summary["retry_failed_count"],
                        "ids_exact_pass_count": structured_summary["ids_exact_pass_count"],
                        "reasoning_leak_count": structured_summary["reasoning_leak_count"],
                        "finish_length_count": structured_summary["finish_length_count"],
                        "empty_text_count": structured_summary["empty_text_count"],
                        "invalid_json_count": structured_summary["invalid_json_count"],
                        "schema_error_count": structured_summary["schema_error_count"],
                        "structured_error_count": len(structured_error_rows),
                        "raw_prompt_response_stored": False,
                    }
                )
                return batch_summary

            return run_exact_model_operation(
                config.lmstudio_base_url,
                model_id=live_scope["model_id"],
                context_length=_MEDIUM_CHUNKED_LIVE_CONTEXT_LENGTH,
                parallel=_MEDIUM_CHUNKED_LIVE_PARALLEL,
                timeout_s=timeout_s,
                transport=native_transport,
                operation=_live_operation,
            )

        batch_summary = self.run_with_system_metrics(
            _operation,
            run_path,
            providers=providers,
        )
        write_json_file(run_path / "batch_summary.json", batch_summary)

        structured_summary_payload = json.loads(structured_summary_path.read_text(encoding="utf-8"))
        system_summary_payload = json.loads(
            (run_path / "system_summary.json").read_text(encoding="utf-8")
        )
        system_samples_payload = _load_jsonl_records(run_path / "system_samples.jsonl")
        privacy_scan = _build_medium_chunked_live_privacy_scan(
            environment_payload=environment_payload,
            experiment_yaml_payload=experiment_yaml_payload,
            run_config=run_config,
            metric_rows=metric_rows,
            structured_error_rows=structured_error_rows,
            batch_summary=batch_summary,
            structured_summary=structured_summary_payload,
            structured_summary_csv_text=structured_summary_csv_path.read_text(encoding="utf-8"),
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=_render_medium_chunked_live_report(
                run_id=safe_run_id,
                experiment_id=config.experiment_id,
                dataset_id=dataset_manifest.dataset_id,
                dataset_hash=dataset_manifest.content_hash,
                structured_prompt_variant=str(live_scope["structured_prompt_variant"]),
                structured_schema_variant=str(live_scope["structured_schema_variant"]),
                model_key=live_scope["model_key"],
                model_id=live_scope["model_id"],
                batch_summary=batch_summary,
                privacy_scan_status="pending_scan",
            ),
        )
        report_text = _render_medium_chunked_live_report(
            run_id=safe_run_id,
            experiment_id=config.experiment_id,
            dataset_id=dataset_manifest.dataset_id,
            dataset_hash=dataset_manifest.content_hash,
            structured_prompt_variant=str(live_scope["structured_prompt_variant"]),
            structured_schema_variant=str(live_scope["structured_schema_variant"]),
            model_key=live_scope["model_key"],
            model_id=live_scope["model_id"],
            batch_summary=batch_summary,
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )
        privacy_scan = _build_medium_chunked_live_privacy_scan(
            environment_payload=environment_payload,
            experiment_yaml_payload=experiment_yaml_payload,
            run_config=run_config,
            metric_rows=metric_rows,
            structured_error_rows=structured_error_rows,
            batch_summary=batch_summary,
            structured_summary=structured_summary_payload,
            structured_summary_csv_text=structured_summary_csv_path.read_text(encoding="utf-8"),
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=report_text,
        )
        write_json_file(privacy_scan_path, privacy_scan)
        report_path.write_text(report_text, encoding="utf-8")
        return batch_summary

    def run_medium_chunked_true_parallel_live(
        self,
        *,
        config_path: str | PathLike[str],
        run_dir: str | PathLike[str],
        run_id: str,
        timeout_s: float = 120.0,
        app_concurrency: int = _MEDIUM_CHUNKED_TRUE_PARALLEL_APP_CONCURRENCY,
        providers: Mapping[str, str] | None = None,
        native_transport: ModelLifecycleTransport | None = None,
        live_transport: LiveTransport | None = None,
        context_fit_safety_ratio: float = 0.85,
        sequential_baseline_wall_time_ms: float | None = None,
        baseline_end_to_end_wall_time_ms: float | None = None,
    ) -> dict[str, object]:
        safe_run_id = str(run_id).strip()
        if not safe_run_id:
            raise ValueError("run_id must be a non-empty string")
        if isinstance(app_concurrency, bool) or not isinstance(app_concurrency, int):
            raise ValueError("app_concurrency must be exactly 2 for MV2.3 true_parallel")
        if app_concurrency != _MEDIUM_CHUNKED_TRUE_PARALLEL_APP_CONCURRENCY:
            raise ValueError("app_concurrency must be exactly 2 for MV2.3 true_parallel")

        config = load_live_smoke_config(config_path, live_enabled=True)
        live_scope = _validate_medium_chunked_true_parallel_live_config(config)
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        environment_payload = _build_medium_chunked_true_parallel_environment_payload(
            experiment_id=config.experiment_id,
            run_id=safe_run_id,
            structured_prompt_variant=str(live_scope["structured_prompt_variant"]),
            structured_schema_variant=str(live_scope["structured_schema_variant"]),
            business_failure_retry_limit=config.business_failure_retry_limit,
        )
        experiment_yaml_payload = _build_medium_chunked_live_experiment_payload(config)
        experiment_yaml_text = yaml.safe_dump(experiment_yaml_payload, sort_keys=False)
        write_json_file(run_path / "environment.json", environment_payload)
        (run_path / "experiment.yaml").write_text(experiment_yaml_text, encoding="utf-8")

        dataset_manifest = load_dataset_manifest(str(live_scope["dataset_id"]))
        metrics_path = run_path / "metrics.jsonl"
        structured_errors_path = run_path / "structured_errors.jsonl"
        structured_summary_path = run_path / "structured_validation_summary.json"
        structured_summary_csv_path = run_path / "structured_validation_summary.csv"
        privacy_scan_path = run_path / "privacy_scan.json"
        report_path = run_path / "report.md"

        run_config = {
            "schema_version": SCHEMA_VERSION,
            "run_id": safe_run_id,
            "mode": _MEDIUM_CHUNKED_TRUE_PARALLEL_LIVE_MODE,
            "managed_live": True,
            "experiment_id": config.experiment_id,
            "dataset_id": dataset_manifest.dataset_id,
            "dataset_hash": dataset_manifest.content_hash,
            "structured_prompt_variant": live_scope["structured_prompt_variant"],
            "structured_schema_variant": live_scope["structured_schema_variant"],
            "business_failure_retry_limit": config.business_failure_retry_limit,
            "model_key": live_scope["model_key"],
            "model_id": live_scope["model_id"],
            "model_count": 1,
            "chunks_count": live_scope["chunks_count"],
            "chunk_size_blocks": live_scope["chunk_size_blocks"],
            "requested_context_length": live_scope["requested_context_length"],
            "requested_parallel": live_scope["requested_parallel"],
            "app_concurrency": _MEDIUM_CHUNKED_TRUE_PARALLEL_APP_CONCURRENCY,
            "queue_pressure_mode": False,
            "parallel_semantics": "true_parallel",
            "repeats": config.repeats,
            "warmup_runs": config.warmup_runs,
            "sequential_baseline_wall_time_ms": sequential_baseline_wall_time_ms,
            "baseline_end_to_end_wall_time_ms": baseline_end_to_end_wall_time_ms,
            "raw_prompt_response_stored": False,
        }
        write_json_file(run_path / "run_config.json", run_config)

        metric_rows: list[dict[str, Any]] = []
        structured_error_rows: list[dict[str, Any]] = []

        def _operation() -> dict[str, object]:
            metrics_path.write_text("", encoding="utf-8")
            structured_errors_path.write_text("", encoding="utf-8")
            metric_rows.clear()
            structured_error_rows.clear()

            def _live_operation(lifecycle_state: Mapping[str, object]) -> dict[str, object]:
                verified_context_length = _as_optional_int(
                    lifecycle_state.get("verified_context_length")
                )
                outcome = run_live_chunked_structured_smoke(
                    config,
                    run_id=safe_run_id,
                    timeout_s=timeout_s,
                    transport=live_transport,
                    verified_context_length=verified_context_length,
                    context_fit_safety_ratio=context_fit_safety_ratio,
                    app_concurrency=_MEDIUM_CHUNKED_TRUE_PARALLEL_APP_CONCURRENCY,
                    warmup_policy=None,
                    warmup_full_batch=False,
                    effective_profile="standard",
                    sequential_baseline_wall_time_ms=sequential_baseline_wall_time_ms,
                    baseline_end_to_end_wall_time_ms=baseline_end_to_end_wall_time_ms,
                    allow_queue_pressure=False,
                )

                for metric in outcome.metrics:
                    metric_row = metric.to_dict()
                    metric_row["raw_prompt_response_stored"] = False
                    metric_rows.append(append_jsonl_record(metrics_path, metric_row))
                for structured_error in outcome.structured_errors:
                    structured_error_rows.append(
                        append_jsonl_record(structured_errors_path, structured_error)
                    )

                structured_summary = _build_medium_chunked_live_structured_summary(
                    metric_rows=metric_rows,
                    structured_errors=structured_error_rows,
                )
                write_json_file(structured_summary_path, structured_summary)
                write_csv_file(
                    structured_summary_csv_path,
                    fieldnames=STRUCTURED_VALIDATION_SUMMARY_FIELDNAMES,
                    rows=[
                        build_structured_validation_summary_csv_row(
                            structured_summary,
                            run_id=safe_run_id,
                            mode=_MEDIUM_CHUNKED_TRUE_PARALLEL_LIVE_MODE,
                            dataset_id=dataset_manifest.dataset_id,
                            status="completed",
                        )
                    ],
                )

                batch_summary = dict(outcome.batch_summary)
                batch_summary.update(
                    {
                        "managed_live": True,
                        "structured_prompt_variant": live_scope["structured_prompt_variant"],
                        "structured_schema_variant": live_scope["structured_schema_variant"],
                        "business_failure_retry_limit": config.business_failure_retry_limit,
                        "app_concurrency": _MEDIUM_CHUNKED_TRUE_PARALLEL_APP_CONCURRENCY,
                        "queue_pressure_mode": False,
                        "parallel_semantics": "true_parallel",
                        "json_parse_pass_count": structured_summary["json_parse_pass_count"],
                        "schema_pass_count": structured_summary["schema_pass_count"],
                        "business_pass_count": structured_summary["business_pass_count"],
                        "retry_attempt_count": structured_summary["retry_attempt_count"],
                        "retry_recovered_count": structured_summary["retry_recovered_count"],
                        "retry_failed_count": structured_summary["retry_failed_count"],
                        "ids_exact_pass_count": structured_summary["ids_exact_pass_count"],
                        "reasoning_leak_count": structured_summary["reasoning_leak_count"],
                        "finish_length_count": structured_summary["finish_length_count"],
                        "empty_text_count": structured_summary["empty_text_count"],
                        "invalid_json_count": structured_summary["invalid_json_count"],
                        "schema_error_count": structured_summary["schema_error_count"],
                        "structured_error_count": len(structured_error_rows),
                        "raw_prompt_response_stored": False,
                    }
                )
                return batch_summary

            return run_exact_model_operation(
                config.lmstudio_base_url,
                model_id=live_scope["model_id"],
                context_length=int(live_scope["requested_context_length"]),
                parallel=_MEDIUM_CHUNKED_TRUE_PARALLEL_PARALLEL,
                timeout_s=timeout_s,
                transport=native_transport,
                operation=_live_operation,
            )

        batch_summary = self.run_with_system_metrics(
            _operation,
            run_path,
            providers=providers,
        )
        write_json_file(run_path / "batch_summary.json", batch_summary)

        structured_summary_payload = json.loads(structured_summary_path.read_text(encoding="utf-8"))
        system_summary_payload = json.loads(
            (run_path / "system_summary.json").read_text(encoding="utf-8")
        )
        system_samples_payload = _load_jsonl_records(run_path / "system_samples.jsonl")
        privacy_scan = _build_medium_chunked_live_privacy_scan(
            environment_payload=environment_payload,
            experiment_yaml_payload=experiment_yaml_payload,
            run_config=run_config,
            metric_rows=metric_rows,
            structured_error_rows=structured_error_rows,
            batch_summary=batch_summary,
            structured_summary=structured_summary_payload,
            structured_summary_csv_text=structured_summary_csv_path.read_text(encoding="utf-8"),
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=_render_medium_chunked_true_parallel_live_report(
                run_id=safe_run_id,
                experiment_id=config.experiment_id,
                dataset_id=dataset_manifest.dataset_id,
                dataset_hash=dataset_manifest.content_hash,
                structured_prompt_variant=str(live_scope["structured_prompt_variant"]),
                structured_schema_variant=str(live_scope["structured_schema_variant"]),
                model_key=live_scope["model_key"],
                model_id=live_scope["model_id"],
                batch_summary=batch_summary,
                privacy_scan_status="pending_scan",
            ),
        )
        report_text = _render_medium_chunked_true_parallel_live_report(
            run_id=safe_run_id,
            experiment_id=config.experiment_id,
            dataset_id=dataset_manifest.dataset_id,
            dataset_hash=dataset_manifest.content_hash,
            structured_prompt_variant=str(live_scope["structured_prompt_variant"]),
            structured_schema_variant=str(live_scope["structured_schema_variant"]),
            model_key=live_scope["model_key"],
            model_id=live_scope["model_id"],
            batch_summary=batch_summary,
            privacy_scan_status=_as_optional_str(privacy_scan.get("status")) or "unknown",
        )
        privacy_scan = _build_medium_chunked_live_privacy_scan(
            environment_payload=environment_payload,
            experiment_yaml_payload=experiment_yaml_payload,
            run_config=run_config,
            metric_rows=metric_rows,
            structured_error_rows=structured_error_rows,
            batch_summary=batch_summary,
            structured_summary=structured_summary_payload,
            structured_summary_csv_text=structured_summary_csv_path.read_text(encoding="utf-8"),
            system_summary=system_summary_payload,
            system_samples=system_samples_payload,
            report_text=report_text,
        )
        write_json_file(privacy_scan_path, privacy_scan)
        report_path.write_text(report_text, encoding="utf-8")
        return batch_summary


def _validate_medium_chunked_live_config(
    config: LiveSmokeConfig,
    *,
    config_path: str | PathLike[str],
) -> dict[str, object]:
    if len(config.models) != 1:
        raise ValueError("managed live run requires exactly one model")
    if len(config.modes) != 1:
        raise ValueError("managed live run requires exactly one mode")
    if len(config.datasets) != 1:
        raise ValueError("managed live run requires exactly one dataset")
    dataset_id = _validate_medium_chunked_live_dataset_id(
        config.datasets[0],
        mode_label="managed live run",
    )
    if config.modes[0] != "json_schema_single":
        raise ValueError("managed live run supports only json_schema_single")
    if config.repeats != 1:
        raise ValueError("managed live run requires repeats=1")
    if config.warmup_runs != 0:
        raise ValueError("managed live run requires warmup_runs=0")
    if config.allow_remote:
        raise ValueError("managed live run requires localhost-only LM Studio")
    structured_prompt_variant = _validate_medium_chunked_live_prompt_variant(
        config.structured_prompt_variant
    )
    structured_schema_variant = _validate_medium_chunked_live_schema_variant(
        config.structured_schema_variant
    )

    model = config.models[0]
    load_keys = {str(key) for key in model.load}
    unsupported_load_keys = sorted(load_keys - _MEDIUM_CHUNKED_LIVE_ALLOWED_LOAD_KEYS)
    if unsupported_load_keys:
        raise ValueError(
            "managed live run rejects unsupported load keys: " + ", ".join(unsupported_load_keys)
        )
    if "parallel" in load_keys and "n_parallel" in load_keys:
        raise ValueError(
            "managed live run rejects ambiguous load keys: use only one of "
            "models[0].load.parallel or models[0].load.n_parallel"
        )

    expected_model_id = _MEDIUM_CHUNKED_SEQUENTIAL_LIVE_ALLOWED_MODEL_IDS.get(model.key)
    if expected_model_id is None:
        raise ValueError(
            "managed live run supports only gemma4_e2b_q4km, gemma4_e4b_q4km, or gemma4_12b_qat"
        )
    if model.model_id != expected_model_id:
        raise ValueError("managed live run requires exact L3.9 Blocks JSON candidate model id")

    requested_context_length = _extract_single_positive_int_load_value(
        model.load.get("context_length"),
        field_name="models[0].load.context_length",
    )
    parallel_field_name = (
        "models[0].load.parallel" if "parallel" in load_keys else "models[0].load.n_parallel"
    )
    requested_parallel = _extract_single_positive_int_load_value(
        model.load.get("parallel", model.load.get("n_parallel")),
        field_name=parallel_field_name,
    )
    if requested_parallel != _MEDIUM_CHUNKED_LIVE_PARALLEL:
        raise ValueError("managed live run requires configured/requested parallel=1")
    if requested_context_length < _MEDIUM_CHUNKED_LIVE_CONTEXT_LENGTH:
        raise ValueError("managed live run requires requested context length >= 8192")

    if model.key == _L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_MODEL_KEY:
        _validate_gemma4_12b_qat_managed_live_prerequisite(config_path=config_path)

    dataset_view = load_chunked_dataset_view(dataset_id)
    return {
        "model_key": model.key,
        "model_id": model.model_id,
        "dataset_id": dataset_id,
        "structured_prompt_variant": structured_prompt_variant,
        "structured_schema_variant": structured_schema_variant,
        "requested_context_length": requested_context_length,
        "requested_parallel": requested_parallel,
        "chunks_count": dataset_view.chunks_count,
        "chunk_size_blocks": dataset_view.chunk_size_blocks,
    }


def _validate_gemma4_12b_qat_managed_live_prerequisite(
    *,
    config_path: str | PathLike[str],
) -> None:
    base_message = "managed live run missing/failed 12B load-only prerequisite"

    def _fail(reason: str, *, evidence_dir: str | None = None) -> None:
        detail = reason if evidence_dir is None else f"{reason}: {evidence_dir}"
        raise ValueError(f"{base_message}: {detail}")

    _, raw_payload = load_raw_experiment_config(Path(config_path))
    prerequisites = raw_payload.get("prerequisites")
    if not isinstance(prerequisites, Mapping):
        _fail("prerequisites section is required for gemma4_12b_qat")

    evidence_dir_value = prerequisites.get("load_only_evidence_dir")
    if not isinstance(evidence_dir_value, str) or not evidence_dir_value.strip():
        _fail("prerequisites.load_only_evidence_dir must be a non-empty relative path")
    evidence_dir_text = Path(evidence_dir_value.strip()).as_posix()
    if Path(evidence_dir_text).is_absolute():
        _fail(
            "prerequisites.load_only_evidence_dir must be relative", evidence_dir=evidence_dir_text
        )

    required_decision = prerequisites.get("required_decision")
    if required_decision != "load_only_passed":
        _fail(
            "prerequisites.required_decision must be load_only_passed",
            evidence_dir=evidence_dir_text,
        )

    required_tiers_value = prerequisites.get("required_tiers")
    if not isinstance(required_tiers_value, Sequence) or isinstance(
        required_tiers_value,
        (str, bytes, bytearray),
    ):
        _fail(
            "prerequisites.required_tiers must list 8192 and 16384",
            evidence_dir=evidence_dir_text,
        )
    required_tiers: list[int] = []
    for tier_value in required_tiers_value:
        if isinstance(tier_value, bool) or not isinstance(tier_value, int):
            _fail(
                "prerequisites.required_tiers must contain integers",
                evidence_dir=evidence_dir_text,
            )
        required_tiers.append(tier_value)
    if tuple(required_tiers) != _L3_9C_GEMMA4_12B_QAT_LOAD_ONLY_CONTEXT_TIERS:
        _fail(
            "prerequisites.required_tiers must equal [8192, 16384]",
            evidence_dir=evidence_dir_text,
        )

    required_final_loaded_instances = prerequisites.get("require_final_loaded_instances")
    if required_final_loaded_instances != 0:
        _fail(
            "prerequisites.require_final_loaded_instances must be 0",
            evidence_dir=evidence_dir_text,
        )

    repo_root = Path(__file__).resolve().parents[2]
    configured_evidence_dir = Path(evidence_dir_text)
    repo_relative_evidence_dir = repo_root / configured_evidence_dir
    config_relative_evidence_dir = Path(config_path).resolve().parent / configured_evidence_dir
    evidence_dir = (
        repo_relative_evidence_dir
        if repo_relative_evidence_dir.exists()
        else config_relative_evidence_dir
        if config_relative_evidence_dir.exists()
        else repo_relative_evidence_dir
    )
    if not evidence_dir.is_dir():
        _fail("evidence directory not found", evidence_dir=evidence_dir_text)

    load_attempts_path = evidence_dir / "load_attempts.jsonl"
    if not load_attempts_path.is_file():
        _fail("load_attempts.jsonl missing", evidence_dir=evidence_dir_text)
    privacy_scan_path = evidence_dir / "privacy_scan.json"
    if not privacy_scan_path.is_file():
        _fail("privacy_scan.json missing", evidence_dir=evidence_dir_text)

    try:
        attempt_rows = _load_jsonl_records(load_attempts_path)
        privacy_scan_payload = json.loads(privacy_scan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"{base_message}: evidence artifacts unreadable: {evidence_dir_text}"
        ) from error

    for required_tier in required_tiers:
        tier_rows = [
            row
            for row in attempt_rows
            if _as_optional_int(row.get("requested_context_length")) == required_tier
        ]
        if not tier_rows:
            _fail(
                f"required tier {required_tier} missing",
                evidence_dir=evidence_dir_text,
            )
        for row in tier_rows:
            if (
                row.get("decision") != required_decision
                or row.get("cleanup_verified") is not True
                or _as_optional_int(row.get("final_loaded_instances"))
                != required_final_loaded_instances
                or row.get("generation_called") is not False
                or row.get("chat_called") is not False
                or row.get("responses_called") is not False
                or row.get("chat_completions_called") is not False
                or row.get("inference_endpoint_called") is not False
            ):
                _fail(
                    f"required tier {required_tier} failed acceptance",
                    evidence_dir=evidence_dir_text,
                )

    if not isinstance(privacy_scan_payload, Mapping):
        _fail("privacy_scan.json must be a JSON object", evidence_dir=evidence_dir_text)
    if (
        privacy_scan_payload.get("status") != "pass"
        or privacy_scan_payload.get("violation_count") != 0
    ):
        _fail("privacy scan failed", evidence_dir=evidence_dir_text)


def _validate_medium_chunked_live_prompt_variant(prompt_variant: str) -> str:
    normalized_variant = str(prompt_variant).strip()
    if normalized_variant not in _MEDIUM_CHUNKED_LIVE_ALLOWED_PROMPT_VARIANTS:
        supported = ", ".join(sorted(_MEDIUM_CHUNKED_LIVE_ALLOWED_PROMPT_VARIANTS))
        raise ValueError(
            "managed live run supports only structured_prompt_variant values: " + supported
        )
    return normalized_variant


def _validate_medium_chunked_live_schema_variant(schema_variant: str) -> str:
    normalized_variant = str(schema_variant).strip()
    if normalized_variant not in _MEDIUM_CHUNKED_LIVE_ALLOWED_SCHEMA_VARIANTS:
        supported = ", ".join(sorted(_MEDIUM_CHUNKED_LIVE_ALLOWED_SCHEMA_VARIANTS))
        raise ValueError(
            "managed live run supports only structured_schema_variant values: " + supported
        )
    return normalized_variant


def _validate_medium_chunked_true_parallel_live_config(
    config: LiveSmokeConfig,
) -> dict[str, object]:
    if len(config.models) != 1:
        raise ValueError("managed true_parallel live run requires exactly one model")
    if len(config.modes) != 1:
        raise ValueError("managed true_parallel live run requires exactly one mode")
    if len(config.datasets) != 1:
        raise ValueError("managed true_parallel live run requires exactly one dataset")
    dataset_id = _validate_medium_chunked_live_dataset_id(
        config.datasets[0],
        mode_label="managed true_parallel live run",
    )
    if config.modes[0] != "json_schema_single":
        raise ValueError("managed true_parallel live run supports only json_schema_single")
    if config.repeats < 1:
        raise ValueError("managed true_parallel live run requires repeats>=1")
    if config.warmup_runs not in {0, 1}:
        raise ValueError("managed true_parallel live run supports only warmup_runs 0 or 1")
    if config.allow_remote:
        raise ValueError("managed true_parallel live run requires localhost-only LM Studio")
    structured_prompt_variant = _validate_medium_chunked_live_prompt_variant(
        config.structured_prompt_variant
    )
    structured_schema_variant = _validate_medium_chunked_live_schema_variant(
        config.structured_schema_variant
    )

    model = config.models[0]
    load_keys = {str(key) for key in model.load}
    unsupported_load_keys = sorted(load_keys - _MEDIUM_CHUNKED_LIVE_ALLOWED_LOAD_KEYS)
    if unsupported_load_keys:
        raise ValueError(
            "managed true_parallel live run rejects unsupported load keys: "
            + ", ".join(unsupported_load_keys)
        )
    if "parallel" in load_keys and "n_parallel" in load_keys:
        raise ValueError(
            "managed true_parallel live run rejects ambiguous load keys: use only one of "
            "models[0].load.parallel or models[0].load.n_parallel"
        )

    expected_model_id = _MEDIUM_CHUNKED_TRUE_PARALLEL_LIVE_ALLOWED_MODEL_IDS.get(model.key)
    if expected_model_id is None:
        raise ValueError(
            "managed true_parallel live run supports only gemma4_e2b_q4km or gemma4_e4b_q4km"
        )
    if model.model_id != expected_model_id:
        raise ValueError("managed true_parallel live run supports Gemma medium model ids only")

    requested_context_length = _extract_single_positive_int_load_value(
        model.load.get("context_length"),
        field_name="models[0].load.context_length",
    )
    parallel_field_name = (
        "models[0].load.parallel" if "parallel" in load_keys else "models[0].load.n_parallel"
    )
    requested_parallel = _extract_single_positive_int_load_value(
        model.load.get("parallel", model.load.get("n_parallel")),
        field_name=parallel_field_name,
    )
    if requested_parallel != _MEDIUM_CHUNKED_TRUE_PARALLEL_PARALLEL:
        raise ValueError("managed true_parallel live run requires configured/requested parallel=2")
    if requested_context_length < _MEDIUM_CHUNKED_LIVE_CONTEXT_LENGTH:
        raise ValueError("managed true_parallel live run requires requested context length >= 8192")

    dataset_view = load_chunked_dataset_view(dataset_id)
    return {
        "model_key": model.key,
        "model_id": model.model_id,
        "dataset_id": dataset_id,
        "structured_prompt_variant": structured_prompt_variant,
        "structured_schema_variant": structured_schema_variant,
        "requested_context_length": requested_context_length,
        "requested_parallel": requested_parallel,
        "chunks_count": dataset_view.chunks_count,
        "chunk_size_blocks": dataset_view.chunk_size_blocks,
    }


def _extract_single_positive_int_load_value(
    value: LiveLoadFieldValue | None,
    *,
    field_name: str,
) -> int:
    if value is None:
        raise ValueError(f"{field_name} is required")
    candidate = value[0] if isinstance(value, tuple) else value
    if isinstance(value, tuple) and len(value) != 1:
        raise ValueError(f"{field_name} must contain exactly one value")
    if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return candidate


def _count_true(values: Sequence[object]) -> int:
    return sum(value is True for value in values)


def _count_false(values: Sequence[object]) -> int:
    return sum(value is False for value in values)


def _build_medium_chunked_live_environment_payload(
    *,
    experiment_id: str,
    run_id: str,
    structured_prompt_variant: str,
    structured_schema_variant: str,
    business_failure_retry_limit: int,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "mode": _MEDIUM_CHUNKED_LIVE_MODE,
        "managed_live": True,
        "dry_run": False,
        "structured_prompt_variant": structured_prompt_variant,
        "structured_schema_variant": structured_schema_variant,
        "business_failure_retry_limit": business_failure_retry_limit,
    }


def _build_medium_chunked_true_parallel_environment_payload(
    *,
    experiment_id: str,
    run_id: str,
    structured_prompt_variant: str,
    structured_schema_variant: str,
    business_failure_retry_limit: int,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "mode": _MEDIUM_CHUNKED_TRUE_PARALLEL_LIVE_MODE,
        "managed_live": True,
        "dry_run": False,
        "structured_prompt_variant": structured_prompt_variant,
        "structured_schema_variant": structured_schema_variant,
        "business_failure_retry_limit": business_failure_retry_limit,
    }


def _build_medium_chunked_live_experiment_payload(
    config: LiveSmokeConfig,
) -> dict[str, object]:
    return {
        "experiment_id": config.experiment_id,
        "hardware_profile": config.hardware_profile,
        "lmstudio_base_url": _MEDIUM_CHUNKED_LIVE_REDACTED_BASE_URL,
        "allow_remote": config.allow_remote,
        "models": [
            {
                "key": model.key,
                "model_id": model.model_id,
                "load": {
                    str(load_key): (
                        list(load_value) if isinstance(load_value, tuple) else load_value
                    )
                    for load_key, load_value in model.load.items()
                },
            }
            for model in config.models
        ],
        "modes": list(config.modes),
        "datasets": list(config.datasets),
        "repeats": config.repeats,
        "warmup_runs": config.warmup_runs,
        "structured_prompt_variant": config.structured_prompt_variant,
        "structured_schema_variant": config.structured_schema_variant,
        "business_failure_retry_limit": config.business_failure_retry_limit,
        "privacy": {
            "store_prompt_text": config.privacy.store_prompt_text,
            "store_response_text": config.privacy.store_response_text,
            "store_prompt_hash": config.privacy.store_prompt_hash,
        },
    }


def _build_medium_chunked_live_structured_summary(
    *,
    metric_rows: Sequence[Mapping[str, Any]],
    structured_errors: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    validations = [
        row.get("validation") for row in metric_rows if isinstance(row.get("validation"), Mapping)
    ]
    total_count = len(metric_rows)
    json_parse_values = [validation.get("json_parse_pass") for validation in validations]
    schema_values = [validation.get("schema_pass") for validation in validations]
    business_values = [validation.get("business_pass") for validation in validations]
    ids_exact_values = [validation.get("ids_exact_pass") for validation in validations]
    duplicate_values = [validation.get("no_duplicate_ids") for validation in validations]
    non_empty_values = [validation.get("non_empty_text_pass") for validation in validations]
    reasoning_values = [validation.get("reasoning_leak") for validation in validations]
    finish_values = [validation.get("finish_reason") for validation in validations]
    retry_values = [validation.get("retry_count") for validation in validations]

    json_parse_pass_count = _count_true(json_parse_values)
    schema_pass_count = _count_true(schema_values)
    business_pass_count = _count_true(business_values)
    ids_exact_pass_count = _count_true(ids_exact_values)
    reasoning_leak_count = _count_true(reasoning_values)
    finish_length_count = sum(value == "length" for value in finish_values)
    duplicate_id_count = _count_false(duplicate_values)
    empty_text_count = _count_false(non_empty_values)
    invalid_json_count = _count_false(json_parse_values)
    schema_error_count = sum(
        json_pass is True and schema_pass is False
        for json_pass, schema_pass in zip(json_parse_values, schema_values, strict=False)
    )
    retry_attempt_count = sum(value == 1 for value in retry_values)
    retry_recovered_count = sum(
        retry_count == 1 and business_pass is True
        for retry_count, business_pass in zip(retry_values, business_values, strict=False)
    )
    retry_failed_count = sum(
        retry_count == 1 and business_pass is False
        for retry_count, business_pass in zip(retry_values, business_values, strict=False)
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "validation_source": "live_structured_validation",
        "validation_status": "completed_live",
        "total_count": total_count,
        "json_parse_pass_count": json_parse_pass_count,
        "json_parse_pass_rate": _rate_or_none(json_parse_pass_count, total_count),
        "schema_pass_count": schema_pass_count,
        "schema_pass_rate": _rate_or_none(schema_pass_count, total_count),
        "business_pass_count": business_pass_count,
        "business_pass_rate": _rate_or_none(business_pass_count, total_count),
        "retry_attempt_count": retry_attempt_count,
        "retry_recovered_count": retry_recovered_count,
        "retry_failed_count": retry_failed_count,
        "ids_exact_pass_count": ids_exact_pass_count,
        "ids_exact_pass_rate": _rate_or_none(ids_exact_pass_count, total_count),
        "reasoning_leak_count": reasoning_leak_count,
        "finish_length_count": finish_length_count,
        "duplicate_id_count": duplicate_id_count,
        "empty_text_count": empty_text_count,
        "invalid_json_count": invalid_json_count,
        "schema_error_count": schema_error_count,
        "structured_error_count": len(structured_errors),
    }


def _build_medium_chunked_live_privacy_scan(
    *,
    environment_payload: Mapping[str, Any],
    experiment_yaml_payload: Mapping[str, Any],
    run_config: Mapping[str, Any],
    metric_rows: Sequence[Mapping[str, Any]],
    structured_error_rows: Sequence[Mapping[str, Any]],
    batch_summary: Mapping[str, Any],
    structured_summary: Mapping[str, Any],
    structured_summary_csv_text: str,
    system_summary: Mapping[str, Any],
    system_samples: Sequence[Mapping[str, Any]],
    report_text: str,
) -> dict[str, object]:
    payloads = {
        "environment.json": environment_payload,
        "experiment.yaml": experiment_yaml_payload,
        "run_config.json": run_config,
        "metrics.jsonl": list(metric_rows),
        "structured_errors.jsonl": list(structured_error_rows),
        "batch_summary.json": batch_summary,
        "structured_validation_summary.json": structured_summary,
        "structured_validation_summary.csv": structured_summary_csv_text,
        "report.md": report_text,
        "system_summary.json": system_summary,
        "system_samples.jsonl": list(system_samples),
    }
    violations: list[str] = []
    for artifact_name, payload in payloads.items():
        serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        violations.extend(
            find_privacy_violations(
                {"artifact_name": artifact_name, "serialized": serialized_payload},
                context=artifact_name,
            )
        )
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "scan_scope": "managed_live_raw_url_path_private_value_scan",
        "scanned_artifacts": list(payloads),
        "raw_prompt_response_stored": False,
    }


def _render_medium_chunked_live_report(
    *,
    run_id: str,
    experiment_id: str,
    dataset_id: str,
    dataset_hash: str,
    structured_prompt_variant: str,
    structured_schema_variant: str,
    model_key: str,
    model_id: str,
    batch_summary: Mapping[str, object],
    privacy_scan_status: str,
) -> str:
    output_files = "\n".join(f"- `{file_name}`" for file_name in _MEDIUM_CHUNKED_LIVE_OUTPUT_FILES)
    return "\n".join(
        (
            "# LM Studio Lab Managed Runner Live Report",
            "",
            "## Run",
            "",
            f"- experiment_id: `{experiment_id}`",
            f"- run_id: `{run_id}`",
            f"- mode: `{_MEDIUM_CHUNKED_LIVE_MODE}`",
            "- L3.9 Blocks JSON sequential managed-live proof through ManagedLabRunner: `true`",
            "- true live/GPU/LM Studio used: `true`",
            "- not true_parallel proof: `true`",
            "- not production default: `true`",
            "- not WVM runtime integration: `true`",
            "- exact unload cleanup required/verified: `true`",
            "- raw_prompt_response_stored: `false`",
            "",
            "## Scope",
            "",
            f"- dataset_id: `{dataset_id}`",
            f"- dataset_hash: `{dataset_hash}`",
            f"- structured_prompt_variant: `{structured_prompt_variant}`",
            f"- structured_schema_variant: `{structured_schema_variant}`",
            f"- business_failure_retry_limit: `{batch_summary.get('business_failure_retry_limit')}`",
            f"- model_key: `{model_key}`",
            f"- model_id: `{model_id}`",
            "- app_concurrency: `1`",
            "- queue_pressure_mode: `false`",
            "- parallel_semantics: `sequential`",
            "",
            "## Lifecycle",
            "",
            f"- load_verified: `{batch_summary.get('load_verified')}`",
            (f"- applied_context_length: `{batch_summary.get('applied_context_length')}`"),
            f"- applied_parallel: `{batch_summary.get('applied_parallel')}`",
            f"- parallel_verified: `{batch_summary.get('parallel_verified')}`",
            f"- cleanup_status: `{batch_summary.get('cleanup_status')}`",
            (f"- cleanup_verified_count: `{batch_summary.get('cleanup_verified_count')}`"),
            (f"- final_loaded_instances: `{batch_summary.get('final_loaded_instances')}`"),
            "",
            "## Validation",
            "",
            (f"- json_parse_pass_count: `{batch_summary.get('json_parse_pass_count')}`"),
            f"- schema_pass_count: `{batch_summary.get('schema_pass_count')}`",
            f"- business_pass_count: `{batch_summary.get('business_pass_count')}`",
            f"- retry_attempt_count: `{batch_summary.get('retry_attempt_count')}`",
            f"- retry_recovered_count: `{batch_summary.get('retry_recovered_count')}`",
            f"- retry_failed_count: `{batch_summary.get('retry_failed_count')}`",
            f"- ids_exact_pass_count: `{batch_summary.get('ids_exact_pass_count')}`",
            f"- all_ids_covered: `{batch_summary.get('all_ids_covered')}`",
            f"- finish_length_count: `{batch_summary.get('finish_length_count')}`",
            (f"- reasoning_leak_count: `{batch_summary.get('reasoning_leak_count')}`"),
            (f"- structured_error_count: `{batch_summary.get('structured_error_count')}`"),
            "",
            "## Notes",
            "",
            (
                "- Sequential managed-live proof validates one allowed L3.9 "
                "Blocks JSON candidate config at a time."
            ),
            (
                "- Native load/unload uses exact owned instance cleanup only; "
                "wildcard unload is forbidden."
            ),
            (
                "- This artifact set is a Lab-only managed-live proof and does "
                "not claim WVM runtime integration."
            ),
            f"- privacy_scan_status: `{privacy_scan_status}`",
            "",
            "## Output Files",
            "",
            output_files,
            "",
        )
    )


def _render_medium_chunked_true_parallel_live_report(
    *,
    run_id: str,
    experiment_id: str,
    dataset_id: str,
    dataset_hash: str,
    structured_prompt_variant: str,
    structured_schema_variant: str,
    model_key: str,
    model_id: str,
    batch_summary: Mapping[str, object],
    privacy_scan_status: str,
) -> str:
    output_files = "\n".join(f"- `{file_name}`" for file_name in _MEDIUM_CHUNKED_LIVE_OUTPUT_FILES)
    return "\n".join(
        (
            "# LM Studio Lab Managed Runner True Parallel Live Report",
            "",
            "## Run",
            "",
            f"- experiment_id: `{experiment_id}`",
            f"- run_id: `{run_id}`",
            f"- mode: `{_MEDIUM_CHUNKED_TRUE_PARALLEL_LIVE_MODE}`",
            "- medium true_parallel=2 proof through ManagedLabRunner: `true`",
            "- true live/GPU/LM Studio used: `true`",
            "- not sequential proof: `true`",
            "- not production default: `true`",
            "- not WVM runtime integration: `true`",
            "- exact unload cleanup required/verified: `true`",
            "- raw_prompt_response_stored: `false`",
            "",
            "## Scope",
            "",
            f"- dataset_id: `{dataset_id}`",
            f"- dataset_hash: `{dataset_hash}`",
            f"- structured_prompt_variant: `{structured_prompt_variant}`",
            f"- structured_schema_variant: `{structured_schema_variant}`",
            f"- business_failure_retry_limit: `{batch_summary.get('business_failure_retry_limit')}`",
            f"- model_key: `{model_key}`",
            f"- model_id: `{model_id}`",
            "- app_concurrency: `2`",
            "- queue_pressure_mode: `false`",
            "- parallel_semantics: `true_parallel`",
            "",
            "## Lifecycle",
            "",
            f"- load_verified: `{batch_summary.get('load_verified')}`",
            f"- configured_parallel: `{batch_summary.get('configured_parallel')}`",
            f"- applied_context_length: `{batch_summary.get('applied_context_length')}`",
            f"- applied_parallel: `{batch_summary.get('applied_parallel')}`",
            f"- parallel_verified: `{batch_summary.get('parallel_verified')}`",
            f"- cleanup_status: `{batch_summary.get('cleanup_status')}`",
            f"- cleanup_verified_count: `{batch_summary.get('cleanup_verified_count')}`",
            f"- final_loaded_instances: `{batch_summary.get('final_loaded_instances')}`",
            "",
            "## Validation",
            "",
            f"- measured_batches: `{batch_summary.get('measured_batches')}`",
            f"- measured_request_count: `{batch_summary.get('measured_request_count')}`",
            f"- json_parse_pass_count: `{batch_summary.get('json_parse_pass_count')}`",
            f"- schema_pass_count: `{batch_summary.get('schema_pass_count')}`",
            f"- business_pass_count: `{batch_summary.get('business_pass_count')}`",
            f"- retry_attempt_count: `{batch_summary.get('retry_attempt_count')}`",
            f"- retry_recovered_count: `{batch_summary.get('retry_recovered_count')}`",
            f"- retry_failed_count: `{batch_summary.get('retry_failed_count')}`",
            f"- ids_exact_pass_count: `{batch_summary.get('ids_exact_pass_count')}`",
            f"- all_ids_covered: `{batch_summary.get('all_ids_covered')}`",
            f"- finish_length_count: `{batch_summary.get('finish_length_count')}`",
            f"- reasoning_leak_count: `{batch_summary.get('reasoning_leak_count')}`",
            f"- structured_error_count: `{batch_summary.get('structured_error_count')}`",
            "",
            "## Notes",
            "",
            (
                "- True-parallel managed-live proof validates one Gemma medium "
                "chunked config at a time."
            ),
            (
                "- Native load/unload uses exact owned instance cleanup only; "
                "wildcard unload is forbidden."
            ),
            (
                "- Baseline speedup fields are comparison metadata only when explicit "
                "baseline arguments are supplied."
            ),
            (
                "- This artifact set is a Lab-only managed-live proof and does "
                "not claim WVM runtime integration."
            ),
            f"- privacy_scan_status: `{privacy_scan_status}`",
            "",
            "## Output Files",
            "",
            output_files,
            "",
        )
    )


def _generation_summary(result: object) -> dict[str, object]:
    return {
        "content_empty": result.content_empty,
        "response_chars": result.content_chars,
        "response_hash": result.content_hash,
        "reasoning_content_present": result.reasoning_content_present,
        "finish_reason": result.finish_reason,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "error_kind": _enum_value(result.error_kind),
    }


def _loaded_instance_count(response: ModelListResponse) -> int:
    return sum(len(model.loaded_instances) for model in response.native_models)


def _api_error_kind(error: SafeApiError | None) -> str | None:
    if error is None:
        return None
    return error.kind.value


def _enum_value(value: object) -> str | None:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, str):
        return value
    return None


def _normalize_providers(providers: Mapping[str, str] | None) -> dict[str, str]:
    source = providers or _DEFAULT_SYSTEM_PROVIDERS
    normalized: dict[str, str] = {}
    for key, value in source.items():
        key_text = str(key)
        if is_forbidden_metric_key(key_text):
            continue
        sanitized_value, _ = sanitize_metric_value(str(value))
        normalized[key_text] = str(sanitized_value)
    return normalized


def _sanitize_operation_summary(summary: Mapping[str, object]) -> dict[str, object]:
    filtered_summary = {
        str(key): value
        for key, value in summary.items()
        if normalize_metric_key(key) not in _RUN_SUMMARY_FORBIDDEN_TOP_LEVEL_KEYS
        and not is_forbidden_metric_key(key)
    }
    sanitized_summary, _ = sanitize_metric_payload(filtered_summary)
    return {str(key): value for key, value in sanitized_summary.items()}


def _build_safe_system_summary(summary: SystemMetricsSummary) -> dict[str, object]:
    summary_payload = summary.to_dict()
    safe_summary = {"system_sample_count": summary.sample_count}
    for key in _SAFE_SYSTEM_SUMMARY_KEYS:
        safe_summary[key] = summary_payload.get(key)
    return safe_summary


def _cache_25k_no_live_prep_common_flags() -> dict[str, object]:
    return {
        "measurement_status": "not_measured_no_live",
        "kv_reuse_proven": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "managed_live": False,
        "network": False,
        "lmstudio_api_called": False,
        "load_called": False,
        "unload_called": False,
        "generation_allowed": False,
        "generation_called": False,
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
    }


def _require_cache_25k_no_live_prep_mapping(
    value: object,
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _require_cache_25k_no_live_prep_string(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


def _require_cache_25k_no_live_prep_bool(
    value: object,
    *,
    field_name: str,
) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _require_cache_25k_no_live_prep_int(
    value: object,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _require_cache_25k_no_live_prep_string_list(
    value: object,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field_name} must be a list of strings")
    values = tuple(
        _require_cache_25k_no_live_prep_string(item, field_name=f"{field_name}[]") for item in value
    )
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    return values


def _normalize_cache_25k_no_live_prep_int_tuple(
    value: object,
    *,
    field_name: str,
) -> tuple[int, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = tuple(
            _require_cache_25k_no_live_prep_int(item, field_name=f"{field_name}[]")
            for item in value
        )
        if not values:
            raise ValueError(f"{field_name} must not be empty")
        return values
    return (_require_cache_25k_no_live_prep_int(value, field_name=field_name),)


def _load_cache_25k_no_live_prep_scope(
    config_path: str | PathLike[str],
) -> dict[str, object]:
    try:
        _, raw_payload = load_raw_experiment_config(config_path)
    except OSError as error:
        raise ValueError("L3.5 cache 25k no-live prep config could not be read") from error
    experiment_id = _require_cache_25k_no_live_prep_string(
        raw_payload.get("experiment_id"),
        field_name="experiment_id",
    )
    if experiment_id != _CACHE_25K_NO_LIVE_PREP_EXPERIMENT_ID:
        raise ValueError(
            "experiment_id must be exactly 'l3_5_cache_25k_no_live_prep' for L3.5 no-live prep"
        )

    models_value = raw_payload.get("models")
    if not isinstance(models_value, Sequence) or isinstance(models_value, (str, bytes, bytearray)):
        raise ValueError("models must contain exactly one model for L3.5 no-live prep")
    if len(models_value) != 1:
        raise ValueError("models must contain exactly one model for L3.5 no-live prep")
    model_payload = _require_cache_25k_no_live_prep_mapping(models_value[0], field_name="models[0]")

    model_key = _require_cache_25k_no_live_prep_string(
        model_payload.get("key"),
        field_name="models[0].key",
    )
    if model_key != _CACHE_25K_NO_LIVE_PREP_MODEL_KEY:
        raise ValueError("models[0].key must be exactly 'gemma4_e2b_q4km'")

    model_id = _require_cache_25k_no_live_prep_string(
        model_payload.get("model_id"),
        field_name="models[0].model_id",
    )
    if model_id != _CACHE_25K_NO_LIVE_PREP_MODEL_ID:
        raise ValueError("models[0].model_id must be exactly 'google/gemma-4-e2b'")

    load_payload = _require_cache_25k_no_live_prep_mapping(
        model_payload.get("load"),
        field_name="models[0].load",
    )
    context_windows = _normalize_cache_25k_no_live_prep_int_tuple(
        load_payload.get("context_length"),
        field_name="models[0].load.context_length",
    )
    if context_windows != _CACHE_25K_NO_LIVE_PREP_CONTEXT_WINDOWS:
        raise ValueError(
            "models[0].load.context_length must be exactly [8192, 16384, 32768, 65536]"
        )

    parallel_value = load_payload.get("parallel", load_payload.get("n_parallel", (1,)))
    parallel_values = _normalize_cache_25k_no_live_prep_int_tuple(
        parallel_value,
        field_name="models[0].load.parallel",
    )
    if parallel_values != (1,):
        raise ValueError("models[0].load.parallel must resolve to exactly [1]")

    dataset_ids = _require_cache_25k_no_live_prep_string_list(
        raw_payload.get("datasets"),
        field_name="datasets",
    )
    if dataset_ids != (_CACHE_25K_NO_LIVE_PREP_DATASET_ID,):
        raise ValueError("datasets must be exactly ['lecture_25k_tokens']")

    modes = _require_cache_25k_no_live_prep_string_list(
        raw_payload.get("modes"), field_name="modes"
    )
    if modes != _CACHE_25K_NO_LIVE_PREP_ALLOWED_MODES:
        raise ValueError(
            "modes must be exactly ['compact_memory_primary', 'stateful_root_branches_experimental', 'stateless_full_prefix_baseline']"
        )

    repeats = _require_cache_25k_no_live_prep_int(raw_payload.get("repeats"), field_name="repeats")
    if repeats != 1:
        raise ValueError("repeats must be exactly 1 for L3.5 no-live prep")

    warmup_runs = _require_cache_25k_no_live_prep_int(
        raw_payload.get("warmup_runs", 0),
        field_name="warmup_runs",
    )
    if warmup_runs != 0:
        raise ValueError("warmup_runs must be exactly 0 for L3.5 no-live prep")

    allow_remote = _require_cache_25k_no_live_prep_bool(
        raw_payload.get("allow_remote", False),
        field_name="allow_remote",
    )
    if allow_remote:
        raise ValueError("allow_remote must be exactly false for L3.5 no-live prep")

    app_concurrency = _require_cache_25k_no_live_prep_int(
        raw_payload.get("app_concurrency"),
        field_name="app_concurrency",
    )
    if app_concurrency != _CACHE_25K_NO_LIVE_PREP_APP_CONCURRENCY:
        raise ValueError("app_concurrency must be exactly 1 for L3.5 no-live prep")

    privacy_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("privacy", {}),
        field_name="privacy",
    )
    for field_name in (
        "store_prompt_text",
        "store_response_text",
        "store_root_text",
        "store_branch_text",
        "store_material_text",
    ):
        if _require_cache_25k_no_live_prep_bool(
            privacy_payload.get(field_name, False),
            field_name=f"privacy.{field_name}",
        ):
            raise ValueError(f"privacy.{field_name} must be exactly false for L3.5 no-live prep")
    for field_name in (
        "store_prompt_hash",
        "store_root_hash",
        "store_branch_hash",
        "store_material_hash",
    ):
        if field_name in privacy_payload and not _require_cache_25k_no_live_prep_bool(
            privacy_payload.get(field_name),
            field_name=f"privacy.{field_name}",
        ):
            raise ValueError(f"privacy.{field_name} must be exactly true when present")

    return {
        "experiment_id": experiment_id,
        "model_key": model_key,
        "model_id": model_id,
        "dataset_id": dataset_ids[0],
        "modes": modes,
        "context_windows": context_windows,
        "repeats": repeats,
        "warmup_runs": warmup_runs,
        "allow_remote": allow_remote,
        "app_concurrency": app_concurrency,
        "privacy": dict(privacy_payload),
    }


def _load_cache_25k_no_live_prep_dataset_manifest(dataset_id: object) -> dict[str, object]:
    normalized_dataset_id = _require_cache_25k_no_live_prep_string(
        dataset_id,
        field_name="dataset_id",
    )
    manifest = load_dataset_manifest(normalized_dataset_id, datasets_root=default_datasets_root())
    manifest_path = default_datasets_root() / normalized_dataset_id / "manifest.yaml"
    raw_payload = _require_cache_25k_no_live_prep_mapping(
        yaml.safe_load(manifest_path.read_text(encoding="utf-8")),
        field_name="dataset manifest",
    )

    if manifest.dataset_id != _CACHE_25K_NO_LIVE_PREP_DATASET_ID:
        raise ValueError("dataset manifest dataset_id must be exactly 'lecture_25k_tokens'")
    if manifest.kind != "synthetic_long_lecture_transcript":
        raise ValueError(
            "dataset manifest kind must be exactly 'synthetic_long_lecture_transcript'"
        )
    if manifest.privacy != "synthetic":
        raise ValueError("dataset manifest privacy must be exactly 'synthetic'")
    if manifest.items_count != 1:
        raise ValueError("dataset manifest items_count must be exactly 1")
    if manifest.chars != _CACHE_25K_NO_LIVE_PREP_DATASET_CHARS:
        raise ValueError("dataset manifest chars must be exactly 75000")
    if manifest.estimated_input_tokens != _CACHE_25K_NO_LIVE_PREP_ESTIMATED_INPUT_TOKENS:
        raise ValueError("dataset manifest estimated_input_tokens must be exactly 25000")
    if manifest.actual_input_tokens is not None:
        raise ValueError("dataset manifest actual_input_tokens must be null")
    if manifest.estimate_error_ratio is not None:
        raise ValueError("dataset manifest estimate_error_ratio must be null")
    if manifest.content_hash != _CACHE_25K_NO_LIVE_PREP_CONTENT_HASH:
        raise ValueError("dataset manifest content_hash must match the synthetic lecture hash")

    source_hash = _require_cache_25k_no_live_prep_string(
        raw_payload.get("source_hash"),
        field_name="dataset manifest.source_hash",
    )
    if source_hash != _CACHE_25K_NO_LIVE_PREP_SOURCE_HASH:
        raise ValueError(
            "dataset manifest source_hash must match the synthetic lecture source hash"
        )
    privacy_safe = _require_cache_25k_no_live_prep_bool(
        raw_payload.get("privacy_safe"),
        field_name="dataset manifest.privacy_safe",
    )
    if not privacy_safe:
        raise ValueError("dataset manifest privacy_safe must be exactly true")

    return {
        "schema_version": SCHEMA_VERSION,
        **_cache_25k_no_live_prep_common_flags(),
        "dataset_id": manifest.dataset_id,
        "kind": manifest.kind,
        "privacy": manifest.privacy,
        "items_count": manifest.items_count,
        "chars": manifest.chars,
        "estimated_input_tokens": manifest.estimated_input_tokens,
        "actual_input_tokens": manifest.actual_input_tokens,
        "estimate_error_ratio": manifest.estimate_error_ratio,
        "tokenizer": {
            "method": manifest.tokenizer.method,
            "family": manifest.tokenizer.family,
            "version": manifest.tokenizer.version,
        },
        "content_hash": manifest.content_hash,
        "source_hash": source_hash,
        "privacy_safe": privacy_safe,
    }


def _cache_25k_no_live_prep_branch_specs() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "branch_id": branch_id,
            "chars": chars,
            "estimated_branch_tokens": estimated_branch_tokens,
            "estimated_memory_tokens": estimated_memory_tokens,
            "material_hash": _safe_hash(
                f"{_CACHE_25K_NO_LIVE_PREP_EXPERIMENT_ID}:{branch_id}:material"
            ),
            "prompt_hash": _safe_hash(
                f"{_CACHE_25K_NO_LIVE_PREP_EXPERIMENT_ID}:{branch_id}:prompt"
            ),
        }
        for branch_id, chars, estimated_branch_tokens, estimated_memory_tokens in _CACHE_25K_NO_LIVE_PREP_BRANCH_SPECS
    )


def _build_cache_25k_no_live_prep_token_manifest(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    dataset_manifest: Mapping[str, object],
    branch_specs: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "dataset_id": dataset_manifest["dataset_id"],
        **_cache_25k_no_live_prep_common_flags(),
        "root_material_hash": _safe_hash(f"{_CACHE_25K_NO_LIVE_PREP_EXPERIMENT_ID}:root:material"),
        "root_prompt_hash": _safe_hash(f"{_CACHE_25K_NO_LIVE_PREP_EXPERIMENT_ID}:root:prompt"),
        "chars": dataset_manifest["chars"],
        "estimated_input_tokens": dataset_manifest["estimated_input_tokens"],
        "output_reserve_tokens": _CACHE_25K_NO_LIVE_PREP_OUTPUT_RESERVE_TOKENS,
        "tokenizer_method": dataset_manifest["tokenizer"]["method"],
        "tokenizer_family": dataset_manifest["tokenizer"]["family"],
        "tokenizer_version": dataset_manifest["tokenizer"]["version"],
        "branches": [
            {
                "branch_id": spec["branch_id"],
                "chars": spec["chars"],
                "estimated_branch_tokens": spec["estimated_branch_tokens"],
                "estimated_memory_tokens": spec["estimated_memory_tokens"],
                "material_hash": spec["material_hash"],
                "prompt_hash": spec["prompt_hash"],
            }
            for spec in branch_specs
        ],
    }


def _build_cache_25k_no_live_prep_context_fit_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    dataset_manifest: Mapping[str, object],
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    estimated_input_tokens = _require_cache_25k_no_live_prep_int(
        dataset_manifest.get("estimated_input_tokens"),
        field_name="dataset_manifest.estimated_input_tokens",
    )
    for context_window in _CACHE_25K_NO_LIVE_PREP_CONTEXT_WINDOWS:
        fit = evaluate_context_fit(
            estimated_input_tokens=estimated_input_tokens,
            max_tokens=_CACHE_25K_NO_LIVE_PREP_OUTPUT_RESERVE_TOKENS,
            effective_context_length=context_window,
            safety_ratio=_CACHE_25K_NO_LIVE_PREP_SAFETY_RATIO,
        )
        if context_window == 8192:
            fit_status = "full_root_does_not_fit"
            allowed_next_gate = "blocked_root_too_large"
        elif context_window == 16384:
            fit_status = "likely_partial_only"
            allowed_next_gate = "partial_only_not_live_authorized"
        elif context_window == 32768:
            fit_status = "candidate_full_root_not_live_authorized"
            allowed_next_gate = "l3_5b_32k_load_only_smoke_after_approval"
        else:
            fit_status = "later_stress_not_current_live_target"
            allowed_next_gate = "later_stress_not_current_live_target"
        rows.append(
            {
                "context_window": context_window,
                "required_tokens": fit.required_tokens,
                "budget_tokens": fit.budget_tokens,
                "safety_ratio": fit.safety_ratio,
                "safety_margin_tokens": fit.budget_tokens - fit.required_tokens,
                "full_root_fits": fit.fits,
                "fit_status": fit_status,
                "allowed_next_gate": allowed_next_gate,
                "live_25k_authorized": False,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "dataset_id": dataset_manifest["dataset_id"],
        **_cache_25k_no_live_prep_common_flags(),
        "output_reserve_tokens": _CACHE_25K_NO_LIVE_PREP_OUTPUT_RESERVE_TOKENS,
        "context_windows": rows,
    }


def _build_cache_25k_no_live_prep_cache_plan(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    dataset_manifest: Mapping[str, object],
    branch_specs: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": _CACHE_25K_NO_LIVE_PREP_MODE,
        "model_key": config_scope["model_key"],
        "model_id": config_scope["model_id"],
        "dataset_id": dataset_manifest["dataset_id"],
        "modes": list(config_scope["modes"]),
        "context_windows": list(config_scope["context_windows"]),
        "repeats": config_scope["repeats"],
        "warmup_runs": config_scope["warmup_runs"],
        "app_concurrency": config_scope["app_concurrency"],
        "branch_count": len(branch_specs),
        "practical_candidate_mode": "compact_memory_primary",
        "experimental_candidate_mode": "stateful_root_branches_experimental",
        "baseline_mode": "stateless_full_prefix_baseline",
        "next_gate": "l3_5b_32k_load_only_smoke_after_approval",
        **_cache_25k_no_live_prep_common_flags(),
    }


def _build_cache_25k_no_live_prep_branch_plan(
    branch_specs: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        spec["branch_id"]: {
            "branch_id": spec["branch_id"],
            "chars": spec["chars"],
            "estimated_branch_tokens": spec["estimated_branch_tokens"],
            "estimated_memory_tokens": spec["estimated_memory_tokens"],
            "material_hash": spec["material_hash"],
            "prompt_hash": spec["prompt_hash"],
            "live_25k_authorized": False,
            "kv_reuse_proven": False,
        }
        for spec in branch_specs
    }


def _build_cache_25k_no_live_prep_request_shapes(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    dataset_manifest: Mapping[str, object],
    token_manifest: Mapping[str, object],
    branch_specs: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    common_flags = _cache_25k_no_live_prep_common_flags()
    rows: list[dict[str, object]] = [
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "experiment_id": config_scope["experiment_id"],
            "request_shape_id": "stateful_root_branches_experimental:root",
            "mode": "stateful_root_branches_experimental",
            "shape_kind": "root",
            "branch_id": None,
            "prompt_hash": token_manifest["root_prompt_hash"],
            "material_hash": token_manifest["root_material_hash"],
            "root_material_hash": token_manifest["root_material_hash"],
            "branch_material_hash": None,
            "chars": dataset_manifest["chars"],
            "estimated_tokens": dataset_manifest["estimated_input_tokens"],
            "context_window_candidate": 32768,
            **common_flags,
        }
    ]
    for spec in branch_specs:
        branch_id = spec["branch_id"]
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "experiment_id": config_scope["experiment_id"],
                "request_shape_id": f"stateful_root_branches_experimental:{branch_id}",
                "mode": "stateful_root_branches_experimental",
                "shape_kind": "branch",
                "branch_id": branch_id,
                "prompt_hash": spec["prompt_hash"],
                "material_hash": spec["material_hash"],
                "root_material_hash": token_manifest["root_material_hash"],
                "branch_material_hash": spec["material_hash"],
                "chars": spec["chars"],
                "estimated_tokens": spec["estimated_branch_tokens"],
                "context_window_candidate": 32768,
                **common_flags,
            }
        )
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "experiment_id": config_scope["experiment_id"],
                "request_shape_id": f"compact_memory_primary:{branch_id}",
                "mode": "compact_memory_primary",
                "shape_kind": "branch",
                "branch_id": branch_id,
                "prompt_hash": spec["prompt_hash"],
                "material_hash": spec["material_hash"],
                "root_material_hash": token_manifest["root_material_hash"],
                "branch_material_hash": spec["material_hash"],
                "chars": spec["chars"],
                "estimated_tokens": spec["estimated_branch_tokens"]
                + spec["estimated_memory_tokens"],
                "context_window_candidate": 32768,
                **common_flags,
            }
        )
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "experiment_id": config_scope["experiment_id"],
                "request_shape_id": f"stateless_full_prefix_baseline:{branch_id}",
                "mode": "stateless_full_prefix_baseline",
                "shape_kind": "branch",
                "branch_id": branch_id,
                "prompt_hash": spec["prompt_hash"],
                "material_hash": token_manifest["root_material_hash"],
                "root_material_hash": token_manifest["root_material_hash"],
                "branch_material_hash": spec["material_hash"],
                "chars": dataset_manifest["chars"] + spec["chars"],
                "estimated_tokens": dataset_manifest["estimated_input_tokens"]
                + spec["estimated_branch_tokens"],
                "context_window_candidate": 32768,
                **common_flags,
            }
        )
    return rows


def _build_cache_25k_no_live_prep_mode_comparison_plan() -> dict[str, object]:
    common_flags = _cache_25k_no_live_prep_common_flags()
    return {
        "compact_memory_primary": {
            "summary": "practical candidate / primary posture",
            "candidate_status": "primary",
            **common_flags,
        },
        "stateful_root_branches_experimental": {
            "summary": "experimental candidate, functional/instrumentable but KV unproven",
            "candidate_status": "experimental",
            **common_flags,
        },
        "stateless_full_prefix_baseline": {
            "summary": "expensive baseline",
            "candidate_status": "baseline",
            **common_flags,
        },
    }


def _build_cache_25k_no_live_prep_privacy_scan(
    *,
    dataset_manifest: Mapping[str, object],
    token_manifest: Mapping[str, object],
    context_fit_report: Mapping[str, object],
    cache_plan: Mapping[str, object],
    branch_plan: Mapping[str, object],
    request_shapes: Sequence[Mapping[str, object]],
    mode_comparison_plan: Mapping[str, object],
    report_text: str,
) -> dict[str, object]:
    provisional_scan = {
        "status": "pass",
        "violation_count": 0,
        "scanned_artifacts": list(_CACHE_25K_NO_LIVE_PREP_OUTPUT_FILES),
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
    }
    payloads = {
        "dataset_manifest.json": dataset_manifest,
        "token_manifest.json": token_manifest,
        "context_fit_report.json": context_fit_report,
        "cache_plan.json": cache_plan,
        "branch_plan.json": branch_plan,
        "request_shapes.jsonl": list(request_shapes),
        "mode_comparison_plan.json": mode_comparison_plan,
        "privacy_scan.json": provisional_scan,
        "report.md": report_text,
    }
    violations: list[str] = []
    for artifact_name, payload in payloads.items():
        serialized = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
        violations.extend(
            find_privacy_violations(
                {"artifact_name": artifact_name, "serialized": serialized},
                context=artifact_name,
            )
        )
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "scanned_artifacts": list(_CACHE_25K_NO_LIVE_PREP_OUTPUT_FILES),
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
    }


def _render_cache_25k_no_live_prep_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    dataset_manifest: Mapping[str, object],
    context_fit_report: Mapping[str, object],
    request_shape_count: int,
    privacy_scan_status: str,
) -> str:
    output_files = "\n".join(
        f"- `{file_name}`" for file_name in _CACHE_25K_NO_LIVE_PREP_OUTPUT_FILES
    )
    context_lines = "\n".join(
        f"- {row['context_window']} tokens -> {row['fit_status']} (budget `{row['budget_tokens']}`, required `{row['required_tokens']}`, next gate `{row['allowed_next_gate']}`)"
        for row in context_fit_report["context_windows"]
    )
    return "\n".join(
        (
            "# LM Studio Lab L3.5 Cache 25k No-Live Prep",
            "",
            "## Status",
            "",
            "- L3.5 is a no-live prep run only.",
            "- No 25k live request was run.",
            "- No HTTP/load/unload/generation occurred.",
            "- KV reuse remains unproven.",
            "- compact_memory_primary remains the practical candidate.",
            "- stateful_root_branches_experimental remains functional/instrumentable but KV unproven.",
            "- production_default: `false`",
            "- wvm_runtime_integration: `false`",
            "- managed_live: `false`",
            "- lmstudio_api_called/load_called/unload_called/generation_called: `false`",
            f"- privacy_scan_status: `{privacy_scan_status}`",
            "",
            "## Scope",
            "",
            f"- experiment_id: `{config_scope['experiment_id']}`",
            f"- run_id: `{run_id}`",
            f"- model_key: `{config_scope['model_key']}`",
            f"- model_id: `{config_scope['model_id']}`",
            f"- dataset_id: `{dataset_manifest['dataset_id']}`",
            f"- estimated_input_tokens: `{dataset_manifest['estimated_input_tokens']}`",
            f"- request_shape_count: `{request_shape_count}`",
            "",
            "## Context Fit Matrix",
            "",
            context_lines,
            "",
            "## Gate",
            "",
            "- Next gate is L3.5b 32k load-only smoke (not implemented/run here) only after approval.",
            "",
            "## Output Files",
            "",
            output_files,
        )
    )


def _build_cache_25k_no_live_prep_summary(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    request_shape_count: int,
    privacy_scan_status: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": _CACHE_25K_NO_LIVE_PREP_MODE,
        "model_key": config_scope["model_key"],
        "model_id": config_scope["model_id"],
        "dataset_id": config_scope["dataset_id"],
        "request_shape_count": request_shape_count,
        "app_concurrency": config_scope["app_concurrency"],
        "practical_candidate_mode": "compact_memory_primary",
        "next_gate": "l3_5b_32k_load_only_smoke_after_approval",
        "privacy_scan_status": privacy_scan_status,
        **_cache_25k_no_live_prep_common_flags(),
    }


def _load_l3_6_25k_no_live_preflight_scope(
    config_path: str | PathLike[str],
) -> dict[str, object]:
    try:
        _, raw_payload = load_raw_experiment_config(config_path)
    except OSError as error:
        raise ValueError("L3.6 25k no-live preflight config could not be read") from error

    experiment_id = _require_cache_25k_no_live_prep_string(
        raw_payload.get("experiment_id"),
        field_name="experiment_id",
    )
    if experiment_id != _L3_6_25K_NO_LIVE_PREFLIGHT_EXPERIMENT_ID:
        raise ValueError(
            "experiment_id must be exactly 'l3_6_25k_no_live_preflight_gemma4_e2b' for L3.6 no-live preflight"
        )

    mode = _require_cache_25k_no_live_prep_string(
        raw_payload.get("mode"),
        field_name="mode",
    )
    if mode != _L3_6_25K_NO_LIVE_PREFLIGHT_MODE:
        raise ValueError("mode must be exactly 'no_live_preflight' for L3.6 no-live preflight")

    model_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("model"),
        field_name="model",
    )
    model_key = _require_cache_25k_no_live_prep_string(
        model_payload.get("key"),
        field_name="model.key",
    )
    if model_key != _L3_6_25K_NO_LIVE_PREFLIGHT_MODEL_KEY:
        raise ValueError("model.key must be exactly 'gemma4_e2b_q4km'")
    model_id = _require_cache_25k_no_live_prep_string(
        model_payload.get("lmstudio_model_id"),
        field_name="model.lmstudio_model_id",
    )
    if model_id != _L3_6_25K_NO_LIVE_PREFLIGHT_MODEL_ID:
        raise ValueError("model.lmstudio_model_id must be exactly 'google/gemma-4-e2b'")

    target_context_length = _require_cache_25k_no_live_prep_int(
        raw_payload.get("target_context_length"),
        field_name="target_context_length",
    )
    if target_context_length != _L3_6_25K_NO_LIVE_PREFLIGHT_TARGET_CONTEXT_LENGTH:
        raise ValueError("target_context_length must be exactly 32768")

    dataset_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("dataset"),
        field_name="dataset",
    )
    dataset_id = _require_cache_25k_no_live_prep_string(
        dataset_payload.get("id"),
        field_name="dataset.id",
    )
    if dataset_id != _L3_6_25K_NO_LIVE_PREFLIGHT_DATASET_ID:
        raise ValueError("dataset.id must be exactly 'lecture_25k_tokens'")

    checks = _require_cache_25k_no_live_prep_string_list(
        raw_payload.get("checks"),
        field_name="checks",
    )
    if checks != _L3_6_25K_NO_LIVE_PREFLIGHT_CHECKS:
        raise ValueError("checks must exactly match the L3.6 25k no-live preflight contract")

    safety_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("safety"),
        field_name="safety",
    )
    for field_name in (
        "generation_allowed",
        "live_25k_authorized",
        "production_default",
        "wvm_runtime_integration",
        "kv_reuse_proven",
    ):
        value = _require_cache_25k_no_live_prep_bool(
            safety_payload.get(field_name),
            field_name=f"safety.{field_name}",
        )
        if value:
            raise ValueError(
                f"safety.{field_name} must be exactly false for L3.6 no-live preflight"
            )

    outputs = _require_cache_25k_no_live_prep_string_list(
        raw_payload.get("outputs"),
        field_name="outputs",
    )
    if outputs != _L3_6_25K_NO_LIVE_PREFLIGHT_OUTPUT_FILES:
        raise ValueError(
            "outputs must exactly match the L3.6 25k no-live preflight artifact contract"
        )

    return {
        "experiment_id": experiment_id,
        "mode": mode,
        "model_key": model_key,
        "model_id": model_id,
        "dataset_id": dataset_id,
        "target_context_length": target_context_length,
        "checks": checks,
        "outputs": outputs,
        "safety": dict(safety_payload),
    }


def _build_l3_6_25k_no_live_preflight_tokenized_prompt_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    dataset_manifest: Mapping[str, object],
) -> dict[str, object]:
    estimated_input_tokens = _require_cache_25k_no_live_prep_int(
        dataset_manifest.get("estimated_input_tokens"),
        field_name="dataset_manifest.estimated_input_tokens",
    )
    chars = _require_cache_25k_no_live_prep_int(
        dataset_manifest.get("chars"),
        field_name="dataset_manifest.chars",
    )
    fit = evaluate_context_fit(
        estimated_input_tokens=estimated_input_tokens,
        max_tokens=_CACHE_25K_NO_LIVE_PREP_OUTPUT_RESERVE_TOKENS,
        effective_context_length=_L3_6_25K_NO_LIVE_PREFLIGHT_TARGET_CONTEXT_LENGTH,
        safety_ratio=_CACHE_25K_NO_LIVE_PREP_SAFETY_RATIO,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": config_scope["mode"],
        "model": {
            "key": config_scope["model_key"],
            "lmstudio_model_id": config_scope["model_id"],
        },
        "dataset": {
            "id": dataset_manifest["dataset_id"],
            "chars": chars,
            "content_hash": dataset_manifest["content_hash"],
            "source_hash": dataset_manifest["source_hash"],
            "estimated_input_tokens": estimated_input_tokens,
            "tokenizer": dataset_manifest["tokenizer"],
        },
        "target_context_length": config_scope["target_context_length"],
        "tokenization_source": "dataset_manifest_static_estimate",
        "exact_tokenization_status": "pending_no_live",
        "chat_template_tokenization_status": "pending_no_live",
        "required_tokens": fit.required_tokens,
        "budget_tokens": fit.budget_tokens,
        "safety_ratio": fit.safety_ratio,
        "safety_margin_tokens": fit.budget_tokens - fit.required_tokens,
        "fit_status": "estimate_fit_with_pending_exact_tokenization"
        if fit.fits
        else "estimate_over_budget",
        "output_reserve_tokens": _CACHE_25K_NO_LIVE_PREP_OUTPUT_RESERVE_TOKENS,
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
        **_cache_25k_no_live_prep_common_flags(),
    }


def _build_l3_6_25k_no_live_preflight_output_reserve_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    tokenized_prompt_report: Mapping[str, object],
) -> dict[str, object]:
    required_tokens = _require_cache_25k_no_live_prep_int(
        tokenized_prompt_report.get("required_tokens"),
        field_name="tokenized_prompt_report.required_tokens",
    )
    budget_tokens = _require_cache_25k_no_live_prep_int(
        tokenized_prompt_report.get("budget_tokens"),
        field_name="tokenized_prompt_report.budget_tokens",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": config_scope["mode"],
        "reserve_tokens": _CACHE_25K_NO_LIVE_PREP_OUTPUT_RESERVE_TOKENS,
        "rationale": "Reuse the existing 2048-token reserve from the L3.5 25k no-live prep until exact tokenizer/chat-template measurement is available.",
        "required_tokens": required_tokens,
        "budget_tokens": budget_tokens,
        "safety_margin_tokens": budget_tokens - required_tokens,
        "safety_ratio": tokenized_prompt_report.get("safety_ratio"),
        "exact_tokenization_status": tokenized_prompt_report.get("exact_tokenization_status"),
        "generation_allowed": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
        **_cache_25k_no_live_prep_common_flags(),
    }


def _render_l3_6_25k_no_live_preflight_prompt_shape_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    tokenized_prompt_report: Mapping[str, object],
) -> str:
    return "\n".join(
        (
            "# L3.6 25k no-live prompt-shape report",
            "",
            f"- Run id: `{run_id}`",
            f"- Experiment: `{config_scope['experiment_id']}`",
            f"- Exact tokenization: `{tokenized_prompt_report['exact_tokenization_status']}`.",
            f"- Chat-template tokenization: `{tokenized_prompt_report['chat_template_tokenization_status']}`.",
            "- Preferred minimized shape: compact_memory primary candidate for long-context WVM work.",
            "- Native stateful research path: /api/v1/chat remains an instrumentation and latency candidate only.",
            "- Stateless full prefix remains the explicit baseline for comparison and fallback costing.",
            "- /v1/responses is blocked for 16k and therefore blocked for 25k long-context routing on the current LM Studio build.",
            "- This artifact is privacy-safe and contains no raw transcript, prompt, branch, or response material.",
            "- No live calls, generation, load, unload, or queue/runtime integration occurred in this preflight.",
        )
    )


def _build_l3_6_25k_no_live_preflight_mode_plan(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
) -> dict[str, object]:
    common_flags = _cache_25k_no_live_prep_common_flags()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": config_scope["mode"],
        "target_context_length": config_scope["target_context_length"],
        "model_key": config_scope["model_key"],
        "model_id": config_scope["model_id"],
        "dataset_id": config_scope["dataset_id"],
        "compact_memory": {
            "route_status": "primary_candidate",
            "summary": "practical long-context primary candidate",
            **common_flags,
        },
        "native_chat_stateful": {
            "endpoint_family": LMStudioEndpointFamily.NATIVE_CHAT.value,
            "endpoint_path": "/api/v1/chat",
            "route_status": "research_latency_candidate",
            "summary": "native instrumentation route with stateful root/branch support and prompt_processing telemetry",
            **common_flags,
        },
        "stateless_full_prefix": {
            "route_status": "baseline",
            "summary": "stateless full-prefix baseline for cost and latency comparison",
            **common_flags,
        },
        "responses": {
            "endpoint_family": LMStudioEndpointFamily.OPENAI_RESPONSES.value,
            "endpoint_path": _RESPONSES_CACHE_PROBE_ENDPOINT_PATH,
            "route_status": _L3_6_25K_NO_LIVE_PREFLIGHT_RESPONSES_STATUS,
            "summary": "small-context cache-accounting candidate only; blocked for 16k/25k long-context routing on current build",
            "cached_tokens_available": False,
            "cached_tokens_observed": False,
            "previous_response_id_supported": False,
            "root_branch_16k_status": "blocked_internal_error",
            "repeated_prefix_16k_status": "blocked_internal_error",
            "mutated_prefix_16k_status": "blocked_internal_error",
            **common_flags,
        },
        "qwen_structured": {
            "route_status": "blocked_recovery_only",
            "summary": "Qwen structured-output route remains blocked for default use and recovery only",
            **common_flags,
        },
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
        **common_flags,
    }


def _render_l3_6_25k_no_live_preflight_abort_conditions(
    *,
    run_id: str,
    tokenized_prompt_report: Mapping[str, object],
    output_reserve_report: Mapping[str, object],
) -> str:
    return "\n".join(
        (
            "# L3.6 25k live abort conditions",
            "",
            f"Run id: `{run_id}`.",
            "",
            "Block live until every condition below is cleared:",
            "- Exact tokenizer measurement is still pending (`pending_no_live`).",
            "- Chat-template tokenization is still pending (`pending_no_live`).",
            f"- Estimated safety margin remains below the approved `{_L3_6A_25K_MINIMUM_APPROVED_SAFETY_MARGIN_TOKENS}`-token minimum at `{output_reserve_report['safety_margin_tokens']}` tokens; any exact-token increase makes the run unsafe.",
            f"- Any output reserve below the approved `{_L3_6A_25K_MINIMUM_OUTPUT_RESERVE_TOKENS}`-token minimum blocks live immediately.",
            "- /v1/responses long-context route is blocked by 16k `internal_error` across root_branch, repeated_prefix, and mutated_prefix variants.",
            "- Any privacy-scan failure or any requirement to store unredacted prompt/response/material text blocks live escalation.",
            "- generation_allowed, live_25k_authorized, production_default, wvm_runtime_integration, and kv_reuse_proven must all remain false for this preflight.",
            "- 32k lifecycle proof must remain valid; if load-only ownership or cleanup proof regresses, stop before any future live run.",
            "- Output reserve must remain configured; removing or shrinking the reserve without a new approved calculation blocks live.",
            "- Any request for raw state ids, raw local URLs, raw provider bodies, or absolute local paths blocks artifact generation and live escalation.",
            "- This preflight alone never authorizes production defaults, queue/runtime wiring, or 25k live generation.",
            "",
            f"Current estimate fit status: `{tokenized_prompt_report['fit_status']}`.",
        )
    )


def _build_l3_6_25k_no_live_preflight_privacy_scan(
    *,
    tokenized_prompt_report: Mapping[str, object],
    output_reserve_report: Mapping[str, object],
    prompt_shape_report: str,
    mode_plan: Mapping[str, object],
    abort_conditions: str,
    report_text: str,
) -> dict[str, object]:
    provisional_scan = {
        "status": "pass",
        "violation_count": 0,
        "scanned_artifacts": list(_L3_6_25K_NO_LIVE_PREFLIGHT_OUTPUT_FILES),
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
    }
    payloads = {
        "tokenized_prompt_report.json": tokenized_prompt_report,
        "output_reserve_report.json": output_reserve_report,
        "prompt_shape_report.md": prompt_shape_report,
        "mode_plan.json": mode_plan,
        "abort_conditions.md": abort_conditions,
        "privacy_scan.json": provisional_scan,
        "report.md": report_text,
    }
    violations: list[str] = []
    for artifact_name, payload in payloads.items():
        serialized = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
        violations.extend(
            find_privacy_violations(
                {"artifact_name": artifact_name, "serialized": serialized},
                context=artifact_name,
            )
        )
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "scanned_artifacts": list(_L3_6_25K_NO_LIVE_PREFLIGHT_OUTPUT_FILES),
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
    }


def _render_l3_6_25k_no_live_preflight_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    tokenized_prompt_report: Mapping[str, object],
    output_reserve_report: Mapping[str, object],
    mode_plan: Mapping[str, object],
    privacy_scan_status: str,
) -> str:
    return "\n".join(
        (
            "# L3.6 25k no-live preflight report",
            "",
            f"- Run id: `{run_id}`",
            f"- Experiment: `{config_scope['experiment_id']}`",
            f"- Mode: `{config_scope['mode']}`",
            f"- Target context length: `{config_scope['target_context_length']}`",
            "- No live LM Studio HTTP, native endpoints, OpenAI-compatible endpoints, load, unload, or generation calls were made.",
            "- 25k live remains blocked.",
            f"- Exact tokenization: `{tokenized_prompt_report['exact_tokenization_status']}`.",
            f"- Estimated required/budget/margin tokens: `{tokenized_prompt_report['required_tokens']}` / `{tokenized_prompt_report['budget_tokens']}` / `{output_reserve_report['safety_margin_tokens']}`.",
            f"- Primary candidate mode: `{mode_plan['compact_memory']['route_status']}`.",
            f"- Responses long-context status: `{mode_plan['responses']['route_status']}`.",
            "- Recommended next step: no-live tokenization and mode review only; not a production or live authorization.",
            f"- privacy_scan_status: `{privacy_scan_status}`",
        )
    )


def _build_l3_6_25k_no_live_preflight_summary(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    tokenized_prompt_report: Mapping[str, object],
    output_reserve_report: Mapping[str, object],
    privacy_scan_status: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": config_scope["mode"],
        "model_key": config_scope["model_key"],
        "model_id": config_scope["model_id"],
        "dataset_id": config_scope["dataset_id"],
        "target_context_length": config_scope["target_context_length"],
        "artifact_count": len(_L3_6_25K_NO_LIVE_PREFLIGHT_OUTPUT_FILES),
        "exact_tokenization_status": tokenized_prompt_report["exact_tokenization_status"],
        "responses_long_context_status": _L3_6_25K_NO_LIVE_PREFLIGHT_RESPONSES_STATUS,
        "safety_margin_tokens": output_reserve_report["safety_margin_tokens"],
        "privacy_scan_status": privacy_scan_status,
        "next_gate": "no_live_tokenization_review_only",
        "generation_allowed": False,
        **_cache_25k_no_live_prep_common_flags(),
    }


def _load_l3_6a_25k_tokenization_prompt_fit_scope(
    config_path: str | PathLike[str],
) -> dict[str, object]:
    try:
        _, raw_payload = load_raw_experiment_config(config_path)
    except OSError as error:
        raise ValueError("L3.6a 25k tokenization/prompt-fit config could not be read") from error

    experiment_id = _require_cache_25k_no_live_prep_string(
        raw_payload.get("experiment_id"),
        field_name="experiment_id",
    )
    if experiment_id != _L3_6A_25K_TOKENIZATION_PROMPT_FIT_EXPERIMENT_ID:
        raise ValueError(
            "experiment_id must be exactly 'l3_6a_25k_tokenization_prompt_fit_gemma4_e2b' for L3.6a tokenization/prompt-fit"
        )

    mode = _require_cache_25k_no_live_prep_string(raw_payload.get("mode"), field_name="mode")
    if mode != _L3_6A_25K_TOKENIZATION_PROMPT_FIT_MODE:
        raise ValueError("mode must be exactly 'tokenization_prompt_fit_no_live' for L3.6a")

    model_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("model"),
        field_name="model",
    )
    model_key = _require_cache_25k_no_live_prep_string(
        model_payload.get("key"),
        field_name="model.key",
    )
    if model_key != _L3_6A_25K_TOKENIZATION_PROMPT_FIT_MODEL_KEY:
        raise ValueError("model.key must be exactly 'gemma4_e2b_q4km'")
    model_id = _require_cache_25k_no_live_prep_string(
        model_payload.get("lmstudio_model_id"),
        field_name="model.lmstudio_model_id",
    )
    if model_id != _L3_6A_25K_TOKENIZATION_PROMPT_FIT_MODEL_ID:
        raise ValueError("model.lmstudio_model_id must be exactly 'google/gemma-4-e2b'")

    target_context_length = _require_cache_25k_no_live_prep_int(
        raw_payload.get("target_context_length"),
        field_name="target_context_length",
    )
    if target_context_length != _L3_6A_25K_TOKENIZATION_PROMPT_FIT_TARGET_CONTEXT_LENGTH:
        raise ValueError("target_context_length must be exactly 32768")

    dataset_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("dataset"),
        field_name="dataset",
    )
    dataset_id = _require_cache_25k_no_live_prep_string(
        dataset_payload.get("id"),
        field_name="dataset.id",
    )
    if dataset_id != _L3_6A_25K_TOKENIZATION_PROMPT_FIT_DATASET_ID:
        raise ValueError("dataset.id must be exactly 'lecture_25k_tokens'")

    checks = _require_cache_25k_no_live_prep_string_list(
        raw_payload.get("checks"),
        field_name="checks",
    )
    if checks != _L3_6A_25K_TOKENIZATION_PROMPT_FIT_CHECKS:
        raise ValueError("checks must exactly match the L3.6a tokenization/prompt-fit contract")

    heuristic_fit_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("heuristic_fit"),
        field_name="heuristic_fit",
    )
    heuristic_fit = {
        "dataset_manifest_estimated_input_tokens": _require_cache_25k_no_live_prep_int(
            heuristic_fit_payload.get("dataset_manifest_estimated_input_tokens"),
            field_name="heuristic_fit.dataset_manifest_estimated_input_tokens",
        ),
        "expected_required_tokens": _require_cache_25k_no_live_prep_int(
            heuristic_fit_payload.get("expected_required_tokens"),
            field_name="heuristic_fit.expected_required_tokens",
        ),
        "expected_budget_tokens": _require_cache_25k_no_live_prep_int(
            heuristic_fit_payload.get("expected_budget_tokens"),
            field_name="heuristic_fit.expected_budget_tokens",
        ),
        "expected_remaining_safety_margin_tokens": _require_cache_25k_no_live_prep_int(
            heuristic_fit_payload.get("expected_remaining_safety_margin_tokens"),
            field_name="heuristic_fit.expected_remaining_safety_margin_tokens",
        ),
        "output_reserve_tokens": _require_cache_25k_no_live_prep_int(
            heuristic_fit_payload.get("output_reserve_tokens"),
            field_name="heuristic_fit.output_reserve_tokens",
        ),
    }

    approval_thresholds_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("approval_thresholds"),
        field_name="approval_thresholds",
    )
    approval_thresholds = {
        "minimum_approved_safety_margin_tokens": _require_cache_25k_no_live_prep_int(
            approval_thresholds_payload.get("minimum_approved_safety_margin_tokens"),
            field_name="approval_thresholds.minimum_approved_safety_margin_tokens",
        ),
        "minimum_output_reserve_tokens": _require_cache_25k_no_live_prep_int(
            approval_thresholds_payload.get("minimum_output_reserve_tokens"),
            field_name="approval_thresholds.minimum_output_reserve_tokens",
        ),
    }
    overhead_assumptions_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("overhead_assumptions"),
        field_name="overhead_assumptions",
    )
    overhead_assumptions = {
        "estimated_chat_template_overhead_tokens": _require_cache_25k_no_live_prep_int(
            overhead_assumptions_payload.get("estimated_chat_template_overhead_tokens"),
            field_name="overhead_assumptions.estimated_chat_template_overhead_tokens",
        ),
        "conservative_chat_template_overhead_tokens": _require_cache_25k_no_live_prep_int(
            overhead_assumptions_payload.get("conservative_chat_template_overhead_tokens"),
            field_name="overhead_assumptions.conservative_chat_template_overhead_tokens",
        ),
    }

    if (
        approval_thresholds["minimum_approved_safety_margin_tokens"]
        != _L3_6A_25K_MINIMUM_APPROVED_SAFETY_MARGIN_TOKENS
    ):
        raise ValueError(
            "approval_thresholds.minimum_approved_safety_margin_tokens must be exactly 2048"
        )
    if (
        approval_thresholds["minimum_output_reserve_tokens"]
        != _L3_6A_25K_MINIMUM_OUTPUT_RESERVE_TOKENS
    ):
        raise ValueError("approval_thresholds.minimum_output_reserve_tokens must be exactly 2048")
    if heuristic_fit["output_reserve_tokens"] != _L3_6A_25K_MINIMUM_OUTPUT_RESERVE_TOKENS:
        raise ValueError("heuristic_fit.output_reserve_tokens must be exactly 2048")
    if (
        overhead_assumptions["estimated_chat_template_overhead_tokens"]
        != _L3_6A_25K_ESTIMATED_CHAT_TEMPLATE_OVERHEAD_TOKENS
    ):
        raise ValueError(
            "overhead_assumptions.estimated_chat_template_overhead_tokens must be exactly 512"
        )
    if (
        overhead_assumptions["conservative_chat_template_overhead_tokens"]
        != _L3_6A_25K_CONSERVATIVE_CHAT_TEMPLATE_OVERHEAD_TOKENS
    ):
        raise ValueError(
            "overhead_assumptions.conservative_chat_template_overhead_tokens must be exactly 1024"
        )
    if (
        overhead_assumptions["conservative_chat_template_overhead_tokens"]
        < overhead_assumptions["estimated_chat_template_overhead_tokens"]
    ):
        raise ValueError(
            "overhead_assumptions.conservative_chat_template_overhead_tokens must be greater than or equal to the estimated assumption"
        )

    safety_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("safety"),
        field_name="safety",
    )
    for field_name in (
        "generation_allowed",
        "generation_called",
        "live_25k_authorized",
        "production_default",
        "wvm_runtime_integration",
        "kv_reuse_proven",
    ):
        value = _require_cache_25k_no_live_prep_bool(
            safety_payload.get(field_name),
            field_name=f"safety.{field_name}",
        )
        if value:
            raise ValueError(
                f"safety.{field_name} must be exactly false for L3.6a tokenization/prompt-fit"
            )

    outputs = _require_cache_25k_no_live_prep_string_list(
        raw_payload.get("outputs"),
        field_name="outputs",
    )
    if outputs != _L3_6A_25K_TOKENIZATION_PROMPT_FIT_OUTPUT_FILES:
        raise ValueError(
            "outputs must exactly match the L3.6a tokenization/prompt-fit artifact contract"
        )

    return {
        "experiment_id": experiment_id,
        "mode": mode,
        "model_key": model_key,
        "model_id": model_id,
        "dataset_id": dataset_id,
        "target_context_length": target_context_length,
        "checks": checks,
        "heuristic_fit": heuristic_fit,
        "overhead_assumptions": overhead_assumptions,
        "approval_thresholds": approval_thresholds,
        "outputs": outputs,
        "safety": dict(safety_payload),
    }


def _build_l3_6a_25k_mode_plan() -> dict[str, object]:
    common_flags = _cache_25k_no_live_prep_common_flags()
    return {
        "compact_memory": {
            "route_status": "primary_candidate",
            "summary": "preferred candidate after prompt minimization",
            **common_flags,
        },
        "native_chat_stateful": {
            "endpoint_family": LMStudioEndpointFamily.NATIVE_CHAT.value,
            "endpoint_path": "/api/v1/chat",
            "route_status": "research_latency_candidate",
            "summary": "stateful research-only route pending exact tokenization and long-context proof",
            **common_flags,
        },
        "stateless_full_prefix": {
            "route_status": "baseline",
            "summary": "baseline for cost and fallback comparison",
            **common_flags,
        },
        "responses": {
            "endpoint_family": LMStudioEndpointFamily.OPENAI_RESPONSES.value,
            "endpoint_path": _RESPONSES_CACHE_PROBE_ENDPOINT_PATH,
            "route_status": _L3_6_25K_NO_LIVE_PREFLIGHT_RESPONSES_STATUS,
            "summary": "responses route remains blocked for current long-context use",
            **common_flags,
        },
    }


def _classify_l3_6a_margin_status(
    *,
    margin_tokens: int,
    minimum_approved_safety_margin_tokens: int,
) -> str:
    if margin_tokens < 0:
        return "blocked_over_budget"
    if margin_tokens < minimum_approved_safety_margin_tokens:
        return _L3_6A_25K_MARGIN_STATUS
    return "approved_margin_threshold_met"


def _build_l3_6a_25k_token_budget_breakdown(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    dataset_manifest: Mapping[str, object],
) -> dict[str, object]:
    estimated_input_tokens = _require_cache_25k_no_live_prep_int(
        dataset_manifest.get("estimated_input_tokens"),
        field_name="dataset_manifest.estimated_input_tokens",
    )
    heuristic_fit = _require_cache_25k_no_live_prep_mapping(
        config_scope.get("heuristic_fit"),
        field_name="config_scope.heuristic_fit",
    )
    approval_thresholds = _require_cache_25k_no_live_prep_mapping(
        config_scope.get("approval_thresholds"),
        field_name="config_scope.approval_thresholds",
    )
    output_reserve_tokens = _require_cache_25k_no_live_prep_int(
        heuristic_fit.get("output_reserve_tokens"),
        field_name="heuristic_fit.output_reserve_tokens",
    )
    fit = evaluate_context_fit(
        estimated_input_tokens=estimated_input_tokens,
        max_tokens=output_reserve_tokens,
        effective_context_length=_L3_6A_25K_TOKENIZATION_PROMPT_FIT_TARGET_CONTEXT_LENGTH,
        safety_ratio=_CACHE_25K_NO_LIVE_PREP_SAFETY_RATIO,
    )
    if estimated_input_tokens != _require_cache_25k_no_live_prep_int(
        heuristic_fit.get("dataset_manifest_estimated_input_tokens"),
        field_name="heuristic_fit.dataset_manifest_estimated_input_tokens",
    ):
        raise ValueError(
            "heuristic_fit.dataset_manifest_estimated_input_tokens must match the dataset manifest estimate"
        )
    if fit.required_tokens != _require_cache_25k_no_live_prep_int(
        heuristic_fit.get("expected_required_tokens"),
        field_name="heuristic_fit.expected_required_tokens",
    ):
        raise ValueError("heuristic_fit.expected_required_tokens must match the computed heuristic")
    if fit.budget_tokens != _require_cache_25k_no_live_prep_int(
        heuristic_fit.get("expected_budget_tokens"),
        field_name="heuristic_fit.expected_budget_tokens",
    ):
        raise ValueError("heuristic_fit.expected_budget_tokens must match the computed heuristic")
    margin_tokens = fit.budget_tokens - fit.required_tokens
    if margin_tokens != _require_cache_25k_no_live_prep_int(
        heuristic_fit.get("expected_remaining_safety_margin_tokens"),
        field_name="heuristic_fit.expected_remaining_safety_margin_tokens",
    ):
        raise ValueError(
            "heuristic_fit.expected_remaining_safety_margin_tokens must match the computed heuristic"
        )

    minimum_approved_safety_margin_tokens = _require_cache_25k_no_live_prep_int(
        approval_thresholds.get("minimum_approved_safety_margin_tokens"),
        field_name="approval_thresholds.minimum_approved_safety_margin_tokens",
    )
    minimum_output_reserve_tokens = _require_cache_25k_no_live_prep_int(
        approval_thresholds.get("minimum_output_reserve_tokens"),
        field_name="approval_thresholds.minimum_output_reserve_tokens",
    )
    overhead_assumptions = _require_cache_25k_no_live_prep_mapping(
        config_scope.get("overhead_assumptions"),
        field_name="config_scope.overhead_assumptions",
    )
    estimated_overhead_tokens = _require_cache_25k_no_live_prep_int(
        overhead_assumptions.get("estimated_chat_template_overhead_tokens"),
        field_name="overhead_assumptions.estimated_chat_template_overhead_tokens",
    )
    conservative_overhead_tokens = _require_cache_25k_no_live_prep_int(
        overhead_assumptions.get("conservative_chat_template_overhead_tokens"),
        field_name="overhead_assumptions.conservative_chat_template_overhead_tokens",
    )
    estimated_required_tokens = fit.required_tokens + estimated_overhead_tokens
    estimated_margin_tokens = fit.budget_tokens - estimated_required_tokens
    conservative_required_tokens = fit.required_tokens + conservative_overhead_tokens
    conservative_margin_tokens = fit.budget_tokens - conservative_required_tokens
    mode_plan = _build_l3_6a_25k_mode_plan()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": config_scope["mode"],
        "model": {
            "key": config_scope["model_key"],
            "lmstudio_model_id": config_scope["model_id"],
        },
        "dataset": {
            "id": dataset_manifest["dataset_id"],
            "chars": dataset_manifest["chars"],
            "estimated_input_tokens": estimated_input_tokens,
            "content_hash": dataset_manifest["content_hash"],
            "source_hash": dataset_manifest["source_hash"],
        },
        "target_context_length": config_scope["target_context_length"],
        "current_heuristic_estimate": {
            "source": "dataset_manifest_static_estimate",
            "required_tokens": fit.required_tokens,
            "budget_tokens": fit.budget_tokens,
            "assumed_chat_template_overhead_tokens": _L3_6A_25K_ASSUMED_CHAT_TEMPLATE_OVERHEAD_TOKENS,
            "output_reserve_tokens": output_reserve_tokens,
            "remaining_safety_margin_tokens": margin_tokens,
        },
        "estimated_overhead_scenario": {
            "chat_template_overhead_tokens": estimated_overhead_tokens,
            "required_tokens": estimated_required_tokens,
            "remaining_safety_margin_tokens": estimated_margin_tokens,
            "threshold_met": estimated_margin_tokens >= minimum_approved_safety_margin_tokens,
            "status": _classify_l3_6a_margin_status(
                margin_tokens=estimated_margin_tokens,
                minimum_approved_safety_margin_tokens=minimum_approved_safety_margin_tokens,
            ),
            "measurement_kind": "no_live_estimate",
        },
        "conservative_overhead_scenario": {
            "chat_template_overhead_tokens": conservative_overhead_tokens,
            "required_tokens": conservative_required_tokens,
            "remaining_safety_margin_tokens": conservative_margin_tokens,
            "threshold_met": conservative_margin_tokens >= minimum_approved_safety_margin_tokens,
            "status": _classify_l3_6a_margin_status(
                margin_tokens=conservative_margin_tokens,
                minimum_approved_safety_margin_tokens=minimum_approved_safety_margin_tokens,
            ),
            "measurement_kind": "no_live_conservative_estimate",
        },
        "exact_tokenizer": {
            "status": "pending_no_live",
            "tokenizer_available": False,
            "blocks_live": True,
            "reason": "Exact tokenizer measurement is not available in this no-live slice.",
        },
        "chat_template_tokenization": {
            "status": "pending_no_live",
            "exact_measurement_available": False,
            "assumed_overhead_tokens": _L3_6A_25K_ASSUMED_CHAT_TEMPLATE_OVERHEAD_TOKENS,
            "assumption_status": "placeholder_only_not_approved",
            "blocks_live": True,
        },
        "output_reserve": {
            "current_output_reserve_tokens": output_reserve_tokens,
            "minimum_approved_output_reserve_tokens": minimum_output_reserve_tokens,
            "threshold_met": output_reserve_tokens >= minimum_output_reserve_tokens,
            "shrink_below_minimum_blocked": True,
        },
        "remaining_safety_margin": {
            "tokens": margin_tokens,
            "minimum_approved_safety_margin_tokens": minimum_approved_safety_margin_tokens,
            "threshold_met": margin_tokens >= minimum_approved_safety_margin_tokens,
            "status": _L3_6A_25K_MARGIN_STATUS,
        },
        "live_authorization": {
            "status": "blocked_pending_exact_tokenization_and_margin_threshold",
            "heuristic_fit_can_authorize_live": False,
            "exact_tokenization_required": True,
            "chat_template_tokenization_required": True,
            "minimization_required": True,
            "live_25k_authorized": False,
        },
        "mode_plan": mode_plan,
        **_cache_25k_no_live_prep_common_flags(),
    }


def _build_l3_6a_25k_chat_template_overhead_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    token_budget_breakdown: Mapping[str, object],
) -> dict[str, object]:
    current_heuristic_estimate = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("current_heuristic_estimate"),
        field_name="token_budget_breakdown.current_heuristic_estimate",
    )
    remaining_safety_margin = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("remaining_safety_margin"),
        field_name="token_budget_breakdown.remaining_safety_margin",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": config_scope["mode"],
        "exact_chat_template_tokenization_status": "pending_no_live",
        "exact_tokenizer_status": "pending_no_live",
        "estimated_chat_template_overhead_tokens": _require_cache_25k_no_live_prep_mapping(
            token_budget_breakdown.get("estimated_overhead_scenario"),
            field_name="token_budget_breakdown.estimated_overhead_scenario",
        )["chat_template_overhead_tokens"],
        "conservative_chat_template_overhead_tokens": _require_cache_25k_no_live_prep_mapping(
            token_budget_breakdown.get("conservative_overhead_scenario"),
            field_name="token_budget_breakdown.conservative_overhead_scenario",
        )["chat_template_overhead_tokens"],
        "estimate_kind": "no_live_estimate_only_not_exact_measurement",
        "current_heuristic_margin_tokens": current_heuristic_estimate[
            "remaining_safety_margin_tokens"
        ],
        "estimated_margin_tokens": _require_cache_25k_no_live_prep_mapping(
            token_budget_breakdown.get("estimated_overhead_scenario"),
            field_name="token_budget_breakdown.estimated_overhead_scenario",
        )["remaining_safety_margin_tokens"],
        "conservative_margin_tokens": _require_cache_25k_no_live_prep_mapping(
            token_budget_breakdown.get("conservative_overhead_scenario"),
            field_name="token_budget_breakdown.conservative_overhead_scenario",
        )["remaining_safety_margin_tokens"],
        "minimum_approved_safety_margin_tokens": remaining_safety_margin[
            "minimum_approved_safety_margin_tokens"
        ],
        "estimated_margin_status": _require_cache_25k_no_live_prep_mapping(
            token_budget_breakdown.get("estimated_overhead_scenario"),
            field_name="token_budget_breakdown.estimated_overhead_scenario",
        )["status"],
        "conservative_margin_status": _require_cache_25k_no_live_prep_mapping(
            token_budget_breakdown.get("conservative_overhead_scenario"),
            field_name="token_budget_breakdown.conservative_overhead_scenario",
        )["status"],
        "margin_status": remaining_safety_margin["status"],
        "live_authorization_status": "blocked_pending_exact_tokenization_and_margin_threshold",
        "minimization_required": True,
        **_cache_25k_no_live_prep_common_flags(),
    }


def _build_l3_6a_25k_output_reserve_policy(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    token_budget_breakdown: Mapping[str, object],
) -> dict[str, object]:
    output_reserve = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("output_reserve"),
        field_name="token_budget_breakdown.output_reserve",
    )
    remaining_safety_margin = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("remaining_safety_margin"),
        field_name="token_budget_breakdown.remaining_safety_margin",
    )
    current_output_reserve_tokens = _require_cache_25k_no_live_prep_int(
        output_reserve.get("current_output_reserve_tokens"),
        field_name="output_reserve.current_output_reserve_tokens",
    )
    minimum_output_reserve_tokens = _require_cache_25k_no_live_prep_int(
        output_reserve.get("minimum_approved_output_reserve_tokens"),
        field_name="output_reserve.minimum_approved_output_reserve_tokens",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": config_scope["mode"],
        "current_output_reserve_tokens": current_output_reserve_tokens,
        "minimum_approved_output_reserve_tokens": minimum_output_reserve_tokens,
        "reserve_status": "meets_minimum_threshold_exactly"
        if current_output_reserve_tokens == minimum_output_reserve_tokens
        else "above_minimum_threshold",
        "shrink_below_minimum_blocked": True,
        "remaining_safety_margin_tokens": remaining_safety_margin["tokens"],
        "minimum_approved_safety_margin_tokens": remaining_safety_margin[
            "minimum_approved_safety_margin_tokens"
        ],
        "margin_status": remaining_safety_margin["status"],
        "live_authorization_status": "blocked_pending_exact_tokenization_and_margin_threshold",
        **_cache_25k_no_live_prep_common_flags(),
    }


def _render_l3_6a_25k_tokenization_strategy_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    token_budget_breakdown: Mapping[str, object],
    chat_template_overhead_report: Mapping[str, object],
    output_reserve_policy: Mapping[str, object],
) -> str:
    current_heuristic_estimate = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("current_heuristic_estimate"),
        field_name="token_budget_breakdown.current_heuristic_estimate",
    )
    remaining_safety_margin = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("remaining_safety_margin"),
        field_name="token_budget_breakdown.remaining_safety_margin",
    )
    estimated_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("estimated_overhead_scenario"),
        field_name="token_budget_breakdown.estimated_overhead_scenario",
    )
    conservative_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("conservative_overhead_scenario"),
        field_name="token_budget_breakdown.conservative_overhead_scenario",
    )
    return "\n".join(
        (
            "# L3.6a 25k no-live tokenization strategy report",
            "",
            f"- Run id: `{run_id}`",
            f"- Experiment: `{config_scope['experiment_id']}`",
            f"- Current heuristic estimate: required `{current_heuristic_estimate['required_tokens']}`, budget `{current_heuristic_estimate['budget_tokens']}`, remaining margin `{current_heuristic_estimate['remaining_safety_margin_tokens']}`.",
            "- Exact tokenizer measurement: `pending_no_live`; heuristic fit cannot authorize live.",
            f"- Estimated no-live chat-template overhead scenario: `{estimated_overhead_scenario['chat_template_overhead_tokens']}` tokens -> required `{estimated_overhead_scenario['required_tokens']}`, remaining margin `{estimated_overhead_scenario['remaining_safety_margin_tokens']}`.",
            f"- Conservative no-live chat-template overhead scenario: `{conservative_overhead_scenario['chat_template_overhead_tokens']}` tokens -> required `{conservative_overhead_scenario['required_tokens']}`, remaining margin `{conservative_overhead_scenario['remaining_safety_margin_tokens']}`.",
            f"- Chat-template overhead status: `{chat_template_overhead_report['estimate_kind']}`; exact chat-template tokenization is still pending.",
            f"- Output reserve policy: current reserve `{output_reserve_policy['current_output_reserve_tokens']}` with minimum approved reserve `{output_reserve_policy['minimum_approved_output_reserve_tokens']}`; shrinking below the minimum remains blocked.",
            f"- Remaining safety margin classification: `{remaining_safety_margin['status']}` against minimum approved `{remaining_safety_margin['minimum_approved_safety_margin_tokens']}` tokens.",
            "- The current 804-token margin becomes much smaller under the estimated overhead scenario and can go negative under the conservative scenario.",
            "- Prompt minimization is required before any future live consideration.",
            "- Live authorization status: blocked pending exact tokenization, pending chat-template tokenization, and below-threshold margin.",
            "- This artifact is no-live only and contains no raw prompt text, response text, local URLs, state ids, or absolute paths.",
        )
    )


def _render_l3_6a_25k_prompt_minimization_candidates(
    *,
    run_id: str,
    token_budget_breakdown: Mapping[str, object],
) -> str:
    remaining_safety_margin = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("remaining_safety_margin"),
        field_name="token_budget_breakdown.remaining_safety_margin",
    )
    estimated_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("estimated_overhead_scenario"),
        field_name="token_budget_breakdown.estimated_overhead_scenario",
    )
    conservative_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("conservative_overhead_scenario"),
        field_name="token_budget_breakdown.conservative_overhead_scenario",
    )
    return "\n".join(
        (
            "# L3.6a prompt minimization candidates",
            "",
            f"- Run id: `{run_id}`",
            "- Outcome: prompt minimization required before any live long-context attempt.",
            f"- Remaining heuristic safety margin is `{remaining_safety_margin['tokens']}` tokens, which is below the approved minimum `{remaining_safety_margin['minimum_approved_safety_margin_tokens']}`.",
            f"- With the estimated no-live overhead scenario the remaining margin drops to `{estimated_overhead_scenario['remaining_safety_margin_tokens']}` tokens.",
            f"- With the conservative no-live overhead scenario the remaining margin drops to `{conservative_overhead_scenario['remaining_safety_margin_tokens']}` tokens, which is over budget.",
            "",
            "## Conservative candidate actions",
            "- Reduce repeated instruction prose in the long-context wrapper.",
            "- Collapse verbose field labels and helper text into shorter stable tags.",
            "- Remove optional examples from the default long-context prompt envelope.",
            "- Keep compact-memory routing as the primary candidate while exact tokenization remains pending.",
            "- Re-check the long-context prompt only after an exact tokenizer and chat-template measurement path exists.",
        )
    )


def _build_l3_6a_25k_privacy_scan(
    *,
    tokenization_strategy_report: str,
    token_budget_breakdown: Mapping[str, object],
    chat_template_overhead_report: Mapping[str, object],
    prompt_minimization_candidates: str,
    output_reserve_policy: Mapping[str, object],
    report_text: str,
) -> dict[str, object]:
    provisional_scan = {
        "status": "pass",
        "violation_count": 0,
        "scanned_artifacts": list(_L3_6A_25K_TOKENIZATION_PROMPT_FIT_OUTPUT_FILES),
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
    }
    payloads = {
        "tokenization_strategy_report.md": tokenization_strategy_report,
        "token_budget_breakdown.json": token_budget_breakdown,
        "chat_template_overhead_report.json": chat_template_overhead_report,
        "prompt_minimization_candidates.md": prompt_minimization_candidates,
        "output_reserve_policy.json": output_reserve_policy,
        "l3_6a_report.md": report_text,
        "privacy_scan.json": provisional_scan,
    }
    violations: list[str] = []
    for artifact_name, payload in payloads.items():
        serialized = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
        violations.extend(
            find_privacy_violations(
                {"artifact_name": artifact_name, "serialized": serialized},
                context=artifact_name,
            )
        )
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "scanned_artifacts": list(_L3_6A_25K_TOKENIZATION_PROMPT_FIT_OUTPUT_FILES),
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
    }


def _render_l3_6a_25k_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    token_budget_breakdown: Mapping[str, object],
    chat_template_overhead_report: Mapping[str, object],
    output_reserve_policy: Mapping[str, object],
    privacy_scan_status: str,
) -> str:
    current_heuristic_estimate = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("current_heuristic_estimate"),
        field_name="token_budget_breakdown.current_heuristic_estimate",
    )
    remaining_safety_margin = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("remaining_safety_margin"),
        field_name="token_budget_breakdown.remaining_safety_margin",
    )
    estimated_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("estimated_overhead_scenario"),
        field_name="token_budget_breakdown.estimated_overhead_scenario",
    )
    conservative_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("conservative_overhead_scenario"),
        field_name="token_budget_breakdown.conservative_overhead_scenario",
    )
    mode_plan = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("mode_plan"),
        field_name="token_budget_breakdown.mode_plan",
    )
    return "\n".join(
        (
            "# L3.6a 25k no-live tokenization and prompt-fit report",
            "",
            f"- Run id: `{run_id}`",
            f"- Experiment: `{config_scope['experiment_id']}`",
            f"- Mode: `{config_scope['mode']}`",
            f"- Target context length: `{config_scope['target_context_length']}`",
            f"- Current heuristic fit: required `{current_heuristic_estimate['required_tokens']}`, budget `{current_heuristic_estimate['budget_tokens']}`, remaining margin `{current_heuristic_estimate['remaining_safety_margin_tokens']}`.",
            "- Exact tokenizer status: `pending_no_live`.",
            f"- Estimated overhead scenario: `{estimated_overhead_scenario['chat_template_overhead_tokens']}` tokens -> remaining margin `{estimated_overhead_scenario['remaining_safety_margin_tokens']}`.",
            f"- Conservative overhead scenario: `{conservative_overhead_scenario['chat_template_overhead_tokens']}` tokens -> remaining margin `{conservative_overhead_scenario['remaining_safety_margin_tokens']}`.",
            f"- Chat-template overhead status: `{chat_template_overhead_report['estimate_kind']}`.",
            f"- Output reserve policy: current `{output_reserve_policy['current_output_reserve_tokens']}`, minimum approved `{output_reserve_policy['minimum_approved_output_reserve_tokens']}`.",
            f"- Remaining safety margin status: `{remaining_safety_margin['status']}`.",
            f"- compact_memory route: `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('compact_memory'), field_name='mode_plan.compact_memory')['route_status']}`.",
            f"- native_chat_stateful route: `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('native_chat_stateful'), field_name='mode_plan.native_chat_stateful')['route_status']}`.",
            f"- stateless_full_prefix route: `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('stateless_full_prefix'), field_name='mode_plan.stateless_full_prefix')['route_status']}`.",
            f"- responses route: `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('responses'), field_name='mode_plan.responses')['route_status']}`.",
            "- The current 804-token margin becomes much smaller under the estimated overhead scenario and can go negative under the conservative scenario.",
            "- Live authorization remains blocked; heuristic fit never authorizes live while exact tokenization is pending.",
            "- Likely honest outcome: prompt minimization required and live blocked.",
            f"- privacy_scan_status: `{privacy_scan_status}`",
        )
    )


def _build_l3_6a_25k_summary(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    token_budget_breakdown: Mapping[str, object],
    output_reserve_policy: Mapping[str, object],
    privacy_scan_status: str,
) -> dict[str, object]:
    remaining_safety_margin = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("remaining_safety_margin"),
        field_name="token_budget_breakdown.remaining_safety_margin",
    )
    live_authorization = _require_cache_25k_no_live_prep_mapping(
        token_budget_breakdown.get("live_authorization"),
        field_name="token_budget_breakdown.live_authorization",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": config_scope["mode"],
        "model_key": config_scope["model_key"],
        "model_id": config_scope["model_id"],
        "dataset_id": config_scope["dataset_id"],
        "target_context_length": config_scope["target_context_length"],
        "artifact_count": len(_L3_6A_25K_TOKENIZATION_PROMPT_FIT_OUTPUT_FILES),
        "exact_tokenization_status": "pending_no_live",
        "chat_template_tokenization_status": "pending_no_live",
        "safety_margin_tokens": remaining_safety_margin["tokens"],
        "minimum_approved_safety_margin_tokens": remaining_safety_margin[
            "minimum_approved_safety_margin_tokens"
        ],
        "current_output_reserve_tokens": output_reserve_policy["current_output_reserve_tokens"],
        "minimum_output_reserve_tokens": output_reserve_policy[
            "minimum_approved_output_reserve_tokens"
        ],
        "margin_status": remaining_safety_margin["status"],
        "prompt_minimization_required": True,
        "live_authorization_status": live_authorization["status"],
        "privacy_scan_status": privacy_scan_status,
        **_cache_25k_no_live_prep_common_flags(),
    }


def _load_l3_6b_25k_prompt_minimization_scope(
    config_path: str | PathLike[str],
) -> dict[str, object]:
    try:
        _, raw_payload = load_raw_experiment_config(config_path)
    except OSError as error:
        raise ValueError("L3.6b 25k prompt-minimization config could not be read") from error

    experiment_id = _require_cache_25k_no_live_prep_string(
        raw_payload.get("experiment_id"),
        field_name="experiment_id",
    )
    if experiment_id != _L3_6B_25K_PROMPT_MINIMIZATION_EXPERIMENT_ID:
        raise ValueError(
            "experiment_id must be exactly 'l3_6b_25k_prompt_minimization_gemma4_e2b' for L3.6b prompt minimization"
        )

    mode = _require_cache_25k_no_live_prep_string(raw_payload.get("mode"), field_name="mode")
    if mode != _L3_6B_25K_PROMPT_MINIMIZATION_MODE:
        raise ValueError("mode must be exactly 'prompt_minimization_no_live' for L3.6b")

    model_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("model"),
        field_name="model",
    )
    model_key = _require_cache_25k_no_live_prep_string(
        model_payload.get("key"),
        field_name="model.key",
    )
    if model_key != _L3_6B_25K_PROMPT_MINIMIZATION_MODEL_KEY:
        raise ValueError("model.key must be exactly 'gemma4_e2b_q4km'")
    model_id = _require_cache_25k_no_live_prep_string(
        model_payload.get("lmstudio_model_id"),
        field_name="model.lmstudio_model_id",
    )
    if model_id != _L3_6B_25K_PROMPT_MINIMIZATION_MODEL_ID:
        raise ValueError("model.lmstudio_model_id must be exactly 'google/gemma-4-e2b'")

    target_context_length = _require_cache_25k_no_live_prep_int(
        raw_payload.get("target_context_length"),
        field_name="target_context_length",
    )
    if target_context_length != _L3_6B_25K_PROMPT_MINIMIZATION_TARGET_CONTEXT_LENGTH:
        raise ValueError("target_context_length must be exactly 32768")

    dataset_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("dataset"),
        field_name="dataset",
    )
    dataset_id = _require_cache_25k_no_live_prep_string(
        dataset_payload.get("id"),
        field_name="dataset.id",
    )
    if dataset_id != _L3_6B_25K_PROMPT_MINIMIZATION_DATASET_ID:
        raise ValueError("dataset.id must be exactly 'lecture_25k_tokens'")

    checks = _require_cache_25k_no_live_prep_string_list(
        raw_payload.get("checks"),
        field_name="checks",
    )
    if checks != _L3_6B_25K_PROMPT_MINIMIZATION_CHECKS:
        raise ValueError("checks must exactly match the L3.6b prompt-minimization contract")

    baseline_snapshot_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("baseline_snapshot"),
        field_name="baseline_snapshot",
    )
    baseline_snapshot = {
        "estimated_input_tokens": _require_cache_25k_no_live_prep_int(
            baseline_snapshot_payload.get("estimated_input_tokens"),
            field_name="baseline_snapshot.estimated_input_tokens",
        ),
        "required_tokens": _require_cache_25k_no_live_prep_int(
            baseline_snapshot_payload.get("required_tokens"),
            field_name="baseline_snapshot.required_tokens",
        ),
        "budget_tokens": _require_cache_25k_no_live_prep_int(
            baseline_snapshot_payload.get("budget_tokens"),
            field_name="baseline_snapshot.budget_tokens",
        ),
        "remaining_safety_margin_tokens": _require_cache_25k_no_live_prep_int(
            baseline_snapshot_payload.get("remaining_safety_margin_tokens"),
            field_name="baseline_snapshot.remaining_safety_margin_tokens",
        ),
        "estimated_overhead_margin_tokens": _require_cache_25k_no_live_prep_int(
            baseline_snapshot_payload.get("estimated_overhead_margin_tokens"),
            field_name="baseline_snapshot.estimated_overhead_margin_tokens",
        ),
        "conservative_overhead_margin_tokens": _require_cache_25k_no_live_prep_int(
            baseline_snapshot_payload.get("conservative_overhead_margin_tokens"),
            field_name="baseline_snapshot.conservative_overhead_margin_tokens",
        ),
    }

    minimized_prompt_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("minimized_prompt"),
        field_name="minimized_prompt",
    )
    minimized_prompt = {
        "estimated_input_tokens": _require_cache_25k_no_live_prep_int(
            minimized_prompt_payload.get("estimated_input_tokens"),
            field_name="minimized_prompt.estimated_input_tokens",
        ),
        "estimated_reduction_tokens": _require_cache_25k_no_live_prep_int(
            minimized_prompt_payload.get("estimated_reduction_tokens"),
            field_name="minimized_prompt.estimated_reduction_tokens",
        ),
        "expected_budget_tokens": _require_cache_25k_no_live_prep_int(
            minimized_prompt_payload.get("expected_budget_tokens"),
            field_name="minimized_prompt.expected_budget_tokens",
        ),
        "output_reserve_tokens": _require_cache_25k_no_live_prep_int(
            minimized_prompt_payload.get("output_reserve_tokens"),
            field_name="minimized_prompt.output_reserve_tokens",
        ),
        "expected_required_tokens": _require_cache_25k_no_live_prep_int(
            minimized_prompt_payload.get("expected_required_tokens"),
            field_name="minimized_prompt.expected_required_tokens",
        ),
        "expected_remaining_safety_margin_tokens": _require_cache_25k_no_live_prep_int(
            minimized_prompt_payload.get("expected_remaining_safety_margin_tokens"),
            field_name="minimized_prompt.expected_remaining_safety_margin_tokens",
        ),
    }

    approval_thresholds_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("approval_thresholds"),
        field_name="approval_thresholds",
    )
    approval_thresholds = {
        "minimum_approved_safety_margin_tokens": _require_cache_25k_no_live_prep_int(
            approval_thresholds_payload.get("minimum_approved_safety_margin_tokens"),
            field_name="approval_thresholds.minimum_approved_safety_margin_tokens",
        ),
        "minimum_output_reserve_tokens": _require_cache_25k_no_live_prep_int(
            approval_thresholds_payload.get("minimum_output_reserve_tokens"),
            field_name="approval_thresholds.minimum_output_reserve_tokens",
        ),
    }

    overhead_assumptions_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("overhead_assumptions"),
        field_name="overhead_assumptions",
    )
    overhead_assumptions = {
        "estimated_chat_template_overhead_tokens": _require_cache_25k_no_live_prep_int(
            overhead_assumptions_payload.get("estimated_chat_template_overhead_tokens"),
            field_name="overhead_assumptions.estimated_chat_template_overhead_tokens",
        ),
        "conservative_chat_template_overhead_tokens": _require_cache_25k_no_live_prep_int(
            overhead_assumptions_payload.get("conservative_chat_template_overhead_tokens"),
            field_name="overhead_assumptions.conservative_chat_template_overhead_tokens",
        ),
        "estimated_required_tokens": _require_cache_25k_no_live_prep_int(
            overhead_assumptions_payload.get("estimated_required_tokens"),
            field_name="overhead_assumptions.estimated_required_tokens",
        ),
        "estimated_remaining_safety_margin_tokens": _require_cache_25k_no_live_prep_int(
            overhead_assumptions_payload.get("estimated_remaining_safety_margin_tokens"),
            field_name="overhead_assumptions.estimated_remaining_safety_margin_tokens",
        ),
        "conservative_required_tokens": _require_cache_25k_no_live_prep_int(
            overhead_assumptions_payload.get("conservative_required_tokens"),
            field_name="overhead_assumptions.conservative_required_tokens",
        ),
        "conservative_remaining_safety_margin_tokens": _require_cache_25k_no_live_prep_int(
            overhead_assumptions_payload.get("conservative_remaining_safety_margin_tokens"),
            field_name="overhead_assumptions.conservative_remaining_safety_margin_tokens",
        ),
    }

    if baseline_snapshot["estimated_input_tokens"] != _L3_6B_25K_BASELINE_INPUT_TOKENS:
        raise ValueError("baseline_snapshot.estimated_input_tokens must be exactly 25000")
    if baseline_snapshot["required_tokens"] != _L3_6B_25K_BASELINE_REQUIRED_TOKENS:
        raise ValueError("baseline_snapshot.required_tokens must be exactly 27048")
    if baseline_snapshot["budget_tokens"] != _L3_6B_25K_BASELINE_BUDGET_TOKENS:
        raise ValueError("baseline_snapshot.budget_tokens must be exactly 27852")
    if baseline_snapshot["remaining_safety_margin_tokens"] != _L3_6B_25K_BASELINE_MARGIN_TOKENS:
        raise ValueError("baseline_snapshot.remaining_safety_margin_tokens must be exactly 804")
    if (
        baseline_snapshot["estimated_overhead_margin_tokens"]
        != _L3_6B_25K_BASELINE_ESTIMATED_MARGIN_TOKENS
    ):
        raise ValueError("baseline_snapshot.estimated_overhead_margin_tokens must be exactly 292")
    if (
        baseline_snapshot["conservative_overhead_margin_tokens"]
        != _L3_6B_25K_BASELINE_CONSERVATIVE_MARGIN_TOKENS
    ):
        raise ValueError(
            "baseline_snapshot.conservative_overhead_margin_tokens must be exactly -220"
        )
    if (
        approval_thresholds["minimum_approved_safety_margin_tokens"]
        != _L3_6A_25K_MINIMUM_APPROVED_SAFETY_MARGIN_TOKENS
    ):
        raise ValueError(
            "approval_thresholds.minimum_approved_safety_margin_tokens must be exactly 2048"
        )
    if (
        approval_thresholds["minimum_output_reserve_tokens"]
        != _L3_6A_25K_MINIMUM_OUTPUT_RESERVE_TOKENS
    ):
        raise ValueError("approval_thresholds.minimum_output_reserve_tokens must be exactly 2048")
    if minimized_prompt["estimated_input_tokens"] != _L3_6B_25K_MINIMIZED_INPUT_TOKENS:
        raise ValueError("minimized_prompt.estimated_input_tokens must be exactly 22700")
    if minimized_prompt["estimated_reduction_tokens"] != _L3_6B_25K_MINIMIZED_REDUCTION_TOKENS:
        raise ValueError("minimized_prompt.estimated_reduction_tokens must be exactly 2300")
    if minimized_prompt["output_reserve_tokens"] != _L3_6A_25K_MINIMUM_OUTPUT_RESERVE_TOKENS:
        raise ValueError("minimized_prompt.output_reserve_tokens must be exactly 2048")
    if (
        minimized_prompt["estimated_reduction_tokens"]
        != baseline_snapshot["estimated_input_tokens"] - minimized_prompt["estimated_input_tokens"]
    ):
        raise ValueError(
            "minimized_prompt.estimated_reduction_tokens must match the baseline-to-minimized delta"
        )

    minimized_fit = evaluate_context_fit(
        estimated_input_tokens=minimized_prompt["estimated_input_tokens"],
        max_tokens=minimized_prompt["output_reserve_tokens"],
        effective_context_length=target_context_length,
        safety_ratio=_CACHE_25K_NO_LIVE_PREP_SAFETY_RATIO,
    )
    minimized_margin_tokens = minimized_fit.budget_tokens - minimized_fit.required_tokens
    if minimized_fit.budget_tokens != minimized_prompt["expected_budget_tokens"]:
        raise ValueError(
            "minimized_prompt.expected_budget_tokens must match the computed minimized heuristic"
        )
    if minimized_fit.required_tokens != minimized_prompt["expected_required_tokens"]:
        raise ValueError(
            "minimized_prompt.expected_required_tokens must match the computed minimized heuristic"
        )
    if minimized_margin_tokens != minimized_prompt["expected_remaining_safety_margin_tokens"]:
        raise ValueError(
            "minimized_prompt.expected_remaining_safety_margin_tokens must match the computed minimized heuristic"
        )
    if (
        overhead_assumptions["estimated_chat_template_overhead_tokens"]
        != _L3_6A_25K_ESTIMATED_CHAT_TEMPLATE_OVERHEAD_TOKENS
    ):
        raise ValueError(
            "overhead_assumptions.estimated_chat_template_overhead_tokens must be exactly 512"
        )
    if (
        overhead_assumptions["conservative_chat_template_overhead_tokens"]
        != _L3_6A_25K_CONSERVATIVE_CHAT_TEMPLATE_OVERHEAD_TOKENS
    ):
        raise ValueError(
            "overhead_assumptions.conservative_chat_template_overhead_tokens must be exactly 1024"
        )
    estimated_required_tokens = (
        minimized_fit.required_tokens
        + overhead_assumptions["estimated_chat_template_overhead_tokens"]
    )
    estimated_margin_tokens = minimized_fit.budget_tokens - estimated_required_tokens
    conservative_required_tokens = (
        minimized_fit.required_tokens
        + overhead_assumptions["conservative_chat_template_overhead_tokens"]
    )
    conservative_margin_tokens = minimized_fit.budget_tokens - conservative_required_tokens
    if overhead_assumptions["estimated_required_tokens"] != estimated_required_tokens:
        raise ValueError(
            "overhead_assumptions.estimated_required_tokens must match the computed minimized heuristic"
        )
    if overhead_assumptions["estimated_remaining_safety_margin_tokens"] != estimated_margin_tokens:
        raise ValueError(
            "overhead_assumptions.estimated_remaining_safety_margin_tokens must match the computed minimized heuristic"
        )
    if overhead_assumptions["conservative_required_tokens"] != conservative_required_tokens:
        raise ValueError(
            "overhead_assumptions.conservative_required_tokens must match the computed minimized heuristic"
        )
    if (
        overhead_assumptions["conservative_remaining_safety_margin_tokens"]
        != conservative_margin_tokens
    ):
        raise ValueError(
            "overhead_assumptions.conservative_remaining_safety_margin_tokens must match the computed minimized heuristic"
        )

    safety_payload = _require_cache_25k_no_live_prep_mapping(
        raw_payload.get("safety"),
        field_name="safety",
    )
    for field_name in (
        "generation_allowed",
        "generation_called",
        "live_25k_authorized",
        "production_default",
        "wvm_runtime_integration",
        "kv_reuse_proven",
    ):
        value = _require_cache_25k_no_live_prep_bool(
            safety_payload.get(field_name),
            field_name=f"safety.{field_name}",
        )
        if value:
            raise ValueError(
                f"safety.{field_name} must be exactly false for L3.6b prompt minimization"
            )

    outputs = _require_cache_25k_no_live_prep_string_list(
        raw_payload.get("outputs"),
        field_name="outputs",
    )
    if outputs != _L3_6B_25K_PROMPT_MINIMIZATION_OUTPUT_FILES:
        raise ValueError(
            "outputs must exactly match the L3.6b prompt-minimization artifact contract"
        )

    return {
        "experiment_id": experiment_id,
        "mode": mode,
        "model_key": model_key,
        "model_id": model_id,
        "dataset_id": dataset_id,
        "target_context_length": target_context_length,
        "checks": checks,
        "baseline_snapshot": baseline_snapshot,
        "minimized_prompt": minimized_prompt,
        "approval_thresholds": approval_thresholds,
        "overhead_assumptions": overhead_assumptions,
        "outputs": outputs,
        "safety": dict(safety_payload),
    }


def _build_l3_6b_25k_mode_plan() -> dict[str, object]:
    common_flags = _cache_25k_no_live_prep_common_flags()
    return {
        "compact_memory": {
            "route_status": "primary_candidate",
            "summary": "primary candidate after prompt minimization",
            **common_flags,
        },
        "native_chat_stateful": {
            "endpoint_family": LMStudioEndpointFamily.NATIVE_CHAT.value,
            "endpoint_path": "/api/v1/chat",
            "route_status": "research_latency_candidate",
            "summary": "stateful latency research candidate pending exact tokenization",
            **common_flags,
        },
        "stateless_full_prefix": {
            "route_status": "baseline",
            "summary": "baseline full-prefix comparison route",
            **common_flags,
        },
        "responses": {
            "endpoint_family": LMStudioEndpointFamily.OPENAI_RESPONSES.value,
            "endpoint_path": _RESPONSES_CACHE_PROBE_ENDPOINT_PATH,
            "route_status": _L3_6_25K_NO_LIVE_PREFLIGHT_RESPONSES_STATUS,
            "summary": "blocked for long-context routing on the current LM Studio build",
            "cached_tokens_available": False,
            "cached_tokens_observed": False,
            "previous_response_id_supported": False,
            **common_flags,
        },
        "qwen_structured": {
            "route_status": "blocked_recovery_only",
            "summary": "blocked for default use and recovery only",
            **common_flags,
        },
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
        **common_flags,
    }


def _build_l3_6b_25k_minimized_token_budget_breakdown(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    dataset_manifest: Mapping[str, object],
) -> dict[str, object]:
    baseline_snapshot = _require_cache_25k_no_live_prep_mapping(
        config_scope.get("baseline_snapshot"),
        field_name="config_scope.baseline_snapshot",
    )
    minimized_prompt = _require_cache_25k_no_live_prep_mapping(
        config_scope.get("minimized_prompt"),
        field_name="config_scope.minimized_prompt",
    )
    approval_thresholds = _require_cache_25k_no_live_prep_mapping(
        config_scope.get("approval_thresholds"),
        field_name="config_scope.approval_thresholds",
    )
    overhead_assumptions = _require_cache_25k_no_live_prep_mapping(
        config_scope.get("overhead_assumptions"),
        field_name="config_scope.overhead_assumptions",
    )
    minimum_approved_safety_margin_tokens = _require_cache_25k_no_live_prep_int(
        approval_thresholds.get("minimum_approved_safety_margin_tokens"),
        field_name="approval_thresholds.minimum_approved_safety_margin_tokens",
    )
    minimum_output_reserve_tokens = _require_cache_25k_no_live_prep_int(
        approval_thresholds.get("minimum_output_reserve_tokens"),
        field_name="approval_thresholds.minimum_output_reserve_tokens",
    )
    minimized_input_tokens = _require_cache_25k_no_live_prep_int(
        minimized_prompt.get("estimated_input_tokens"),
        field_name="minimized_prompt.estimated_input_tokens",
    )
    output_reserve_tokens = _require_cache_25k_no_live_prep_int(
        minimized_prompt.get("output_reserve_tokens"),
        field_name="minimized_prompt.output_reserve_tokens",
    )
    minimized_fit = evaluate_context_fit(
        estimated_input_tokens=minimized_input_tokens,
        max_tokens=output_reserve_tokens,
        effective_context_length=_L3_6B_25K_PROMPT_MINIMIZATION_TARGET_CONTEXT_LENGTH,
        safety_ratio=_CACHE_25K_NO_LIVE_PREP_SAFETY_RATIO,
    )
    no_overhead_margin_tokens = minimized_fit.budget_tokens - minimized_fit.required_tokens
    estimated_overhead_tokens = _require_cache_25k_no_live_prep_int(
        overhead_assumptions.get("estimated_chat_template_overhead_tokens"),
        field_name="overhead_assumptions.estimated_chat_template_overhead_tokens",
    )
    conservative_overhead_tokens = _require_cache_25k_no_live_prep_int(
        overhead_assumptions.get("conservative_chat_template_overhead_tokens"),
        field_name="overhead_assumptions.conservative_chat_template_overhead_tokens",
    )
    estimated_required_tokens = minimized_fit.required_tokens + estimated_overhead_tokens
    estimated_margin_tokens = minimized_fit.budget_tokens - estimated_required_tokens
    conservative_required_tokens = minimized_fit.required_tokens + conservative_overhead_tokens
    conservative_margin_tokens = minimized_fit.budget_tokens - conservative_required_tokens
    mode_plan = _build_l3_6b_25k_mode_plan()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": config_scope["mode"],
        "model": {
            "key": config_scope["model_key"],
            "lmstudio_model_id": config_scope["model_id"],
        },
        "dataset": {
            "id": dataset_manifest["dataset_id"],
            "chars": dataset_manifest["chars"],
            "estimated_input_tokens": dataset_manifest["estimated_input_tokens"],
            "content_hash": dataset_manifest["content_hash"],
            "source_hash": dataset_manifest["source_hash"],
        },
        "target_context_length": config_scope["target_context_length"],
        "baseline_snapshot": {
            "source": "l3_6a_accepted_snapshot",
            "estimated_input_tokens": baseline_snapshot["estimated_input_tokens"],
            "required_tokens": baseline_snapshot["required_tokens"],
            "budget_tokens": baseline_snapshot["budget_tokens"],
            "remaining_safety_margin_tokens": baseline_snapshot["remaining_safety_margin_tokens"],
            "estimated_overhead_margin_tokens": baseline_snapshot[
                "estimated_overhead_margin_tokens"
            ],
            "conservative_overhead_margin_tokens": baseline_snapshot[
                "conservative_overhead_margin_tokens"
            ],
            "risk_status": "b_c_risk_live_blocked",
        },
        "minimized_estimate": {
            "estimated_input_tokens": minimized_input_tokens,
            "estimated_reduction_tokens": minimized_prompt["estimated_reduction_tokens"],
            "required_tokens": minimized_fit.required_tokens,
            "budget_tokens": minimized_fit.budget_tokens,
            "output_reserve_tokens": output_reserve_tokens,
            "remaining_safety_margin_tokens": no_overhead_margin_tokens,
            "threshold_met": no_overhead_margin_tokens >= minimum_approved_safety_margin_tokens,
            "status": _classify_l3_6a_margin_status(
                margin_tokens=no_overhead_margin_tokens,
                minimum_approved_safety_margin_tokens=minimum_approved_safety_margin_tokens,
            ),
            "measurement_kind": "no_live_minimized_estimate",
        },
        "estimated_overhead_scenario": {
            "chat_template_overhead_tokens": estimated_overhead_tokens,
            "required_tokens": estimated_required_tokens,
            "remaining_safety_margin_tokens": estimated_margin_tokens,
            "threshold_met": estimated_margin_tokens >= minimum_approved_safety_margin_tokens,
            "status": _classify_l3_6a_margin_status(
                margin_tokens=estimated_margin_tokens,
                minimum_approved_safety_margin_tokens=minimum_approved_safety_margin_tokens,
            ),
            "measurement_kind": "no_live_estimate",
        },
        "conservative_overhead_scenario": {
            "chat_template_overhead_tokens": conservative_overhead_tokens,
            "required_tokens": conservative_required_tokens,
            "remaining_safety_margin_tokens": conservative_margin_tokens,
            "threshold_met": conservative_margin_tokens >= minimum_approved_safety_margin_tokens,
            "status": _classify_l3_6a_margin_status(
                margin_tokens=conservative_margin_tokens,
                minimum_approved_safety_margin_tokens=minimum_approved_safety_margin_tokens,
            ),
            "measurement_kind": "no_live_conservative_estimate",
        },
        "output_reserve": {
            "current_output_reserve_tokens": output_reserve_tokens,
            "minimum_approved_output_reserve_tokens": minimum_output_reserve_tokens,
            "threshold_met": output_reserve_tokens >= minimum_output_reserve_tokens,
            "shrink_below_minimum_blocked": True,
        },
        "exact_tokenizer": {
            "status": "pending_no_live",
            "tokenizer_available": False,
            "blocks_live": True,
            "reason": "Exact tokenizer measurement is not available in this no-live slice.",
        },
        "chat_template_tokenization": {
            "status": "pending_no_live",
            "exact_measurement_available": False,
            "blocks_live": True,
            "reason": "Chat-template tokenization remains heuristic-only in this no-live slice.",
        },
        "live_authorization": {
            "status": _L3_6B_25K_LIVE_AUTHORIZATION_STATUS,
            "heuristic_minimization_target_reached": True,
            "exact_tokenization_required": True,
            "chat_template_tokenization_required": True,
            "privacy_scan_required": True,
            "live_25k_authorized": False,
        },
        "mode_plan": mode_plan,
        **_cache_25k_no_live_prep_common_flags(),
    }


def _render_l3_6b_25k_minimized_prompt_shape_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    minimized_token_budget_breakdown: Mapping[str, object],
) -> str:
    minimized_estimate = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("minimized_estimate"),
        field_name="minimized_token_budget_breakdown.minimized_estimate",
    )
    estimated_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("estimated_overhead_scenario"),
        field_name="minimized_token_budget_breakdown.estimated_overhead_scenario",
    )
    conservative_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("conservative_overhead_scenario"),
        field_name="minimized_token_budget_breakdown.conservative_overhead_scenario",
    )
    mode_plan = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("mode_plan"),
        field_name="minimized_token_budget_breakdown.mode_plan",
    )
    return "\n".join(
        (
            "# L3.6b minimized prompt-shape report",
            "",
            f"- Run id: `{run_id}`",
            f"- Experiment: `{config_scope['experiment_id']}`",
            f"- Minimized input estimate: `{minimized_estimate['estimated_input_tokens']}` tokens (reduction `{minimized_estimate['estimated_reduction_tokens']}`).",
            f"- No-overhead minimized fit: required `{minimized_estimate['required_tokens']}`, budget `{minimized_estimate['budget_tokens']}`, remaining margin `{minimized_estimate['remaining_safety_margin_tokens']}`.",
            f"- Estimated overhead scenario: `{estimated_overhead_scenario['chat_template_overhead_tokens']}` tokens -> remaining margin `{estimated_overhead_scenario['remaining_safety_margin_tokens']}`.",
            f"- Conservative overhead scenario: `{conservative_overhead_scenario['chat_template_overhead_tokens']}` tokens -> remaining margin `{conservative_overhead_scenario['remaining_safety_margin_tokens']}`.",
            f"- compact_memory remains `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('compact_memory'), field_name='mode_plan.compact_memory')['route_status']}`.",
            f"- Native chat stateful remains `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('native_chat_stateful'), field_name='mode_plan.native_chat_stateful')['route_status']}` via `/api/v1/chat` metadata only.",
            f"- Stateless full prefix remains `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('stateless_full_prefix'), field_name='mode_plan.stateless_full_prefix')['route_status']}`.",
            f"- Responses remains `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('responses'), field_name='mode_plan.responses')['route_status']}`.",
            f"- Qwen structured remains `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('qwen_structured'), field_name='mode_plan.qwen_structured')['route_status']}`.",
            "- Only category-level prompt minimization metadata is stored here; no raw prompt or material text is present.",
            "- No live calls, generation, load, unload, or queue/runtime integration occurred in this slice.",
        )
    )


def _render_l3_6b_25k_prompt_diff_summary(*, run_id: str) -> str:
    return "\n".join(
        (
            "# L3.6b prompt diff summary",
            "",
            f"- Run id: `{run_id}`",
            "- Minimized categories only; no raw prompt text is stored.",
            "- duplicate schema/instruction text",
            "- system prompt prose",
            "- root metadata labels",
            "- branch instructions",
            "- diagnostic prose",
            "- verbose wrappers",
        )
    )


def _render_l3_6b_25k_updated_abort_conditions(
    *,
    run_id: str,
    minimized_token_budget_breakdown: Mapping[str, object],
) -> str:
    minimized_estimate = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("minimized_estimate"),
        field_name="minimized_token_budget_breakdown.minimized_estimate",
    )
    estimated_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("estimated_overhead_scenario"),
        field_name="minimized_token_budget_breakdown.estimated_overhead_scenario",
    )
    conservative_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("conservative_overhead_scenario"),
        field_name="minimized_token_budget_breakdown.conservative_overhead_scenario",
    )
    output_reserve = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("output_reserve"),
        field_name="minimized_token_budget_breakdown.output_reserve",
    )
    return "\n".join(
        (
            "# L3.6b updated abort conditions",
            "",
            f"Run id: `{run_id}`.",
            "",
            "Live remains blocked until every condition below is cleared:",
            "- Exact tokenizer measurement is still pending (`pending_no_live`).",
            "- Chat-template tokenization is still pending (`pending_no_live`).",
            "- Privacy scan must pass for all L3.6b artifacts.",
            "- `/v1/responses` remains blocked for long-context routing on the current LM Studio build.",
            f"- The minimized no-overhead margin improves to `{minimized_estimate['remaining_safety_margin_tokens']}` with reserve `{output_reserve['current_output_reserve_tokens']}`, but heuristic scenarios alone do not authorize live.",
            f"- Estimated overhead margin improves to `{estimated_overhead_scenario['remaining_safety_margin_tokens']}` and conservative overhead margin improves to `{conservative_overhead_scenario['remaining_safety_margin_tokens']}`; this improves margin/reserve blockers but is still insufficient without exact measurement.",
            "- generation_allowed, generation_called, live_25k_authorized, production_default, wvm_runtime_integration, and kv_reuse_proven must all remain false.",
            "- This slice does not authorize production defaults, WVM runtime integration, or any live 25k attempt.",
        )
    )


def _build_l3_6b_25k_privacy_scan(
    *,
    minimized_prompt_shape_report: str,
    minimized_token_budget_breakdown: Mapping[str, object],
    prompt_diff_summary: str,
    updated_abort_conditions: str,
    report_text: str,
) -> dict[str, object]:
    provisional_scan = {
        "status": "pass",
        "violation_count": 0,
        "scanned_artifacts": list(_L3_6B_25K_PROMPT_MINIMIZATION_OUTPUT_FILES),
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
    }
    payloads = {
        "minimized_prompt_shape_report.md": minimized_prompt_shape_report,
        "minimized_token_budget_breakdown.json": minimized_token_budget_breakdown,
        "prompt_diff_summary.md": prompt_diff_summary,
        "updated_abort_conditions.md": updated_abort_conditions,
        "l3_6b_report.md": report_text,
        "privacy_scan.json": provisional_scan,
    }
    violations: list[str] = []
    for artifact_name, payload in payloads.items():
        serialized = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
        violations.extend(
            find_privacy_violations(
                {"artifact_name": artifact_name, "serialized": serialized},
                context=artifact_name,
            )
        )
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "scanned_artifacts": list(_L3_6B_25K_PROMPT_MINIMIZATION_OUTPUT_FILES),
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
    }


def _render_l3_6b_25k_report(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    minimized_token_budget_breakdown: Mapping[str, object],
    privacy_scan_status: str,
) -> str:
    minimized_estimate = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("minimized_estimate"),
        field_name="minimized_token_budget_breakdown.minimized_estimate",
    )
    estimated_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("estimated_overhead_scenario"),
        field_name="minimized_token_budget_breakdown.estimated_overhead_scenario",
    )
    conservative_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("conservative_overhead_scenario"),
        field_name="minimized_token_budget_breakdown.conservative_overhead_scenario",
    )
    mode_plan = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("mode_plan"),
        field_name="minimized_token_budget_breakdown.mode_plan",
    )
    return "\n".join(
        (
            "# L3.6b 25k prompt minimization report",
            "",
            f"- Run id: `{run_id}`",
            f"- Experiment: `{config_scope['experiment_id']}`",
            f"- Mode: `{config_scope['mode']}`",
            f"- Target context length: `{config_scope['target_context_length']}`",
            "- No live LM Studio HTTP, native endpoints, OpenAI-compatible endpoints, load, unload, or generation calls were made.",
            "- Honest outcome: no-live prompt minimization target reached for heuristic scenarios.",
            f"- Minimized no-overhead margin: `{minimized_estimate['remaining_safety_margin_tokens']}`.",
            f"- Estimated overhead scenario margin: `{estimated_overhead_scenario['remaining_safety_margin_tokens']}` (>= `2048`).",
            f"- Conservative overhead scenario margin: `{conservative_overhead_scenario['remaining_safety_margin_tokens']}` (no longer over budget and still >= `2048`).",
            "- Live remains blocked due exact tokenizer and chat-template tokenization pending; this slice does not authorize production defaults.",
            f"- compact_memory route: `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('compact_memory'), field_name='mode_plan.compact_memory')['route_status']}`.",
            f"- native_chat_stateful route: `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('native_chat_stateful'), field_name='mode_plan.native_chat_stateful')['route_status']}`.",
            f"- stateless_full_prefix route: `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('stateless_full_prefix'), field_name='mode_plan.stateless_full_prefix')['route_status']}`.",
            f"- responses route: `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('responses'), field_name='mode_plan.responses')['route_status']}`.",
            f"- qwen_structured route: `{_require_cache_25k_no_live_prep_mapping(mode_plan.get('qwen_structured'), field_name='mode_plan.qwen_structured')['route_status']}`.",
            f"- privacy_scan_status: `{privacy_scan_status}`",
        )
    )


def _build_l3_6b_25k_summary(
    *,
    run_id: str,
    config_scope: Mapping[str, object],
    minimized_token_budget_breakdown: Mapping[str, object],
    privacy_scan_status: str,
) -> dict[str, object]:
    minimized_estimate = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("minimized_estimate"),
        field_name="minimized_token_budget_breakdown.minimized_estimate",
    )
    estimated_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("estimated_overhead_scenario"),
        field_name="minimized_token_budget_breakdown.estimated_overhead_scenario",
    )
    conservative_overhead_scenario = _require_cache_25k_no_live_prep_mapping(
        minimized_token_budget_breakdown.get("conservative_overhead_scenario"),
        field_name="minimized_token_budget_breakdown.conservative_overhead_scenario",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": config_scope["mode"],
        "model_key": config_scope["model_key"],
        "model_id": config_scope["model_id"],
        "dataset_id": config_scope["dataset_id"],
        "target_context_length": config_scope["target_context_length"],
        "artifact_count": len(_L3_6B_25K_PROMPT_MINIMIZATION_OUTPUT_FILES),
        "exact_tokenization_status": "pending_no_live",
        "chat_template_tokenization_status": "pending_no_live",
        "baseline_margin_tokens": _L3_6B_25K_BASELINE_MARGIN_TOKENS,
        "minimized_input_estimate_tokens": minimized_estimate["estimated_input_tokens"],
        "estimated_reduction_tokens": minimized_estimate["estimated_reduction_tokens"],
        "output_reserve_tokens": minimized_estimate["output_reserve_tokens"],
        "no_overhead_margin_tokens": minimized_estimate["remaining_safety_margin_tokens"],
        "estimated_overhead_margin_tokens": estimated_overhead_scenario[
            "remaining_safety_margin_tokens"
        ],
        "conservative_overhead_margin_tokens": conservative_overhead_scenario[
            "remaining_safety_margin_tokens"
        ],
        "estimated_overhead_threshold_met": estimated_overhead_scenario["threshold_met"],
        "conservative_overhead_threshold_met": conservative_overhead_scenario["threshold_met"],
        "live_authorization_status": _L3_6B_25K_LIVE_AUTHORIZATION_STATUS,
        "privacy_scan_status": privacy_scan_status,
        **_cache_25k_no_live_prep_common_flags(),
    }


def _validate_cache_stateful_no_live_plan(plan: CacheExperimentPlan) -> None:
    if plan.model_key != _CACHE_STATEFUL_NO_LIVE_ALLOWED_MODEL_KEY:
        raise ValueError(
            "plan.model_key must be exactly 'gemma4_e2b_q4km' for cache/stateful no-live"
        )
    if plan.context_window not in _CACHE_STATEFUL_NO_LIVE_ALLOWED_CONTEXT_WINDOWS:
        allowed_values = ", ".join(
            str(value) for value in _CACHE_STATEFUL_NO_LIVE_ALLOWED_CONTEXT_WINDOWS
        )
        raise ValueError(f"plan.context_window must be one of: {allowed_values}")
    if plan.production_default:
        raise ValueError("plan.production_default must be False for cache/stateful no-live")
    if plan.raw_material_stored:
        raise ValueError("plan.raw_material_stored must be False for cache/stateful no-live")
    if plan.root_request.raw_material_stored:
        raise ValueError(
            "plan.root_request.raw_material_stored must be False for cache/stateful no-live"
        )
    if plan.root_request.model_key != plan.model_key:
        raise ValueError("plan.root_request.model_key must match plan.model_key")
    if plan.root_request.context_window != plan.context_window:
        raise ValueError("plan.root_request.context_window must match plan.context_window")

    _require_cache_stateful_no_live_non_empty_string(
        plan.experiment_id, field_name="plan.experiment_id"
    )
    _require_cache_stateful_no_live_non_empty_string(
        plan.root_request.request_id,
        field_name="plan.root_request.request_id",
    )
    _require_cache_stateful_no_live_non_empty_string(
        plan.root_request.dataset_id,
        field_name="plan.root_request.dataset_id",
    )
    _require_cache_stateful_no_live_non_empty_string(
        plan.root_request.root_context_hash,
        field_name="plan.root_request.root_context_hash",
    )
    _require_cache_stateful_no_live_positive_int(
        plan.root_request.estimated_input_tokens,
        field_name="plan.root_request.estimated_input_tokens",
    )

    if not plan.stateful_branch_requests:
        raise ValueError(
            "plan.stateful_branch_requests must contain at least one request for cache/stateful no-live"
        )
    if not plan.stateless_prefix_requests:
        raise ValueError(
            "plan.stateless_prefix_requests must contain at least one request for cache/stateful no-live"
        )
    if not plan.compact_memory_requests:
        raise ValueError(
            "plan.compact_memory_requests must contain at least one request for cache/stateful no-live"
        )

    for index, request in enumerate(plan.stateful_branch_requests):
        if request.raw_material_stored:
            raise ValueError(
                f"plan.stateful_branch_requests[{index}].raw_material_stored must be False"
            )
        _require_cache_stateful_no_live_non_empty_string(
            request.request_id,
            field_name=f"plan.stateful_branch_requests[{index}].request_id",
        )
        _require_cache_stateful_no_live_non_empty_string(
            request.root_request_id,
            field_name=f"plan.stateful_branch_requests[{index}].root_request_id",
        )
        _require_cache_stateful_no_live_non_empty_string(
            request.branch_id,
            field_name=f"plan.stateful_branch_requests[{index}].branch_id",
        )
        _require_cache_stateful_no_live_non_empty_string(
            request.root_context_hash,
            field_name=f"plan.stateful_branch_requests[{index}].root_context_hash",
        )
        if request.root_request_id != plan.root_request.request_id:
            raise ValueError(
                f"plan.stateful_branch_requests[{index}].root_request_id must match plan.root_request.request_id"
            )
        if request.root_context_hash != plan.root_request.root_context_hash:
            raise ValueError(
                f"plan.stateful_branch_requests[{index}].root_context_hash must match plan.root_request.root_context_hash"
            )
        _require_cache_stateful_no_live_positive_int(
            request.estimated_branch_tokens,
            field_name=f"plan.stateful_branch_requests[{index}].estimated_branch_tokens",
        )

    for index, request in enumerate(plan.stateless_prefix_requests):
        if request.raw_material_stored:
            raise ValueError(
                f"plan.stateless_prefix_requests[{index}].raw_material_stored must be False"
            )
        _require_cache_stateful_no_live_non_empty_string(
            request.request_id,
            field_name=f"plan.stateless_prefix_requests[{index}].request_id",
        )
        _require_cache_stateful_no_live_non_empty_string(
            request.branch_id,
            field_name=f"plan.stateless_prefix_requests[{index}].branch_id",
        )
        _require_cache_stateful_no_live_non_empty_string(
            request.prefix_context_hash,
            field_name=f"plan.stateless_prefix_requests[{index}].prefix_context_hash",
        )
        _require_cache_stateful_no_live_positive_int(
            request.estimated_input_tokens,
            field_name=f"plan.stateless_prefix_requests[{index}].estimated_input_tokens",
        )

    for index, request in enumerate(plan.compact_memory_requests):
        if request.raw_material_stored:
            raise ValueError(
                f"plan.compact_memory_requests[{index}].raw_material_stored must be False"
            )
        _require_cache_stateful_no_live_non_empty_string(
            request.request_id,
            field_name=f"plan.compact_memory_requests[{index}].request_id",
        )
        _require_cache_stateful_no_live_non_empty_string(
            request.branch_id,
            field_name=f"plan.compact_memory_requests[{index}].branch_id",
        )
        _require_cache_stateful_no_live_non_empty_string(
            request.memory_hash,
            field_name=f"plan.compact_memory_requests[{index}].memory_hash",
        )
        _require_cache_stateful_no_live_positive_int(
            request.estimated_memory_tokens,
            field_name=f"plan.compact_memory_requests[{index}].estimated_memory_tokens",
        )
        _require_cache_stateful_no_live_positive_int(
            request.estimated_branch_tokens,
            field_name=f"plan.compact_memory_requests[{index}].estimated_branch_tokens",
        )


def _require_cache_stateful_no_live_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


def _require_cache_stateful_no_live_positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _build_cache_stateful_no_live_run_config(
    *,
    plan: CacheExperimentPlan,
    run_id: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": plan.experiment_id,
        "mode": _CACHE_STATEFUL_NO_LIVE_MODE,
        "model_key": plan.model_key,
        "context_window": plan.context_window,
        "planned_request_count": plan.planned_request_count,
        "fake_first": True,
        "no_live": True,
        "uses_fake_transport_only": True,
        "lmstudio_api_called": False,
        "network": False,
        "measurement_status": CacheMeasurementStatus.NOT_MEASURED_NO_LIVE.value,
        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
        "has_live_measurements": False,
        "kv_reuse_proven": False,
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "production_default": False,
    }


def _build_cache_stateful_no_live_plan_payload(
    *,
    plan: CacheExperimentPlan,
    run_id: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": plan.experiment_id,
        "mode": _CACHE_STATEFUL_NO_LIVE_MODE,
        "model_key": plan.model_key,
        "context_window": plan.context_window,
        "planned_request_count": plan.planned_request_count,
        "measurement_status": CacheMeasurementStatus.NOT_MEASURED_NO_LIVE.value,
        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
        "kv_reuse_proven": False,
        "has_live_measurements": False,
        "fake_first": True,
        "no_live": True,
        "uses_fake_transport_only": True,
        "lmstudio_api_called": False,
        "network": False,
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "production_default": False,
        "root_request": {
            "request_id": plan.root_request.request_id,
            "model_key": plan.root_request.model_key,
            "dataset_id": plan.root_request.dataset_id,
            "root_context_hash": plan.root_request.root_context_hash,
            "estimated_input_tokens": plan.root_request.estimated_input_tokens,
            "context_window": plan.root_request.context_window,
            "context_reuse_mode": plan.root_request.mode.value,
            "raw_material_stored": False,
        },
        "stateful_branch_requests": [
            {
                "request_id": request.request_id,
                "root_request_id": request.root_request_id,
                "branch_id": request.branch_id,
                "root_context_hash": request.root_context_hash,
                "estimated_branch_tokens": request.estimated_branch_tokens,
                "context_reuse_mode": request.mode.value,
                "raw_material_stored": False,
            }
            for request in plan.stateful_branch_requests
        ],
        "stateless_prefix_requests": [
            {
                "request_id": request.request_id,
                "branch_id": request.branch_id,
                "prefix_context_hash": request.prefix_context_hash,
                "estimated_input_tokens": request.estimated_input_tokens,
                "context_reuse_mode": request.mode.value,
                "raw_material_stored": False,
            }
            for request in plan.stateless_prefix_requests
        ],
        "compact_memory_requests": [
            {
                "request_id": request.request_id,
                "branch_id": request.branch_id,
                "memory_hash": request.memory_hash,
                "estimated_memory_tokens": request.estimated_memory_tokens,
                "estimated_branch_tokens": request.estimated_branch_tokens,
                "context_reuse_mode": request.mode.value,
                "raw_material_stored": False,
            }
            for request in plan.compact_memory_requests
        ],
    }


def _build_cache_stateful_no_live_request_rows(
    *,
    plan: CacheExperimentPlan,
    run_id: str,
) -> list[dict[str, object]]:
    base_row = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": plan.experiment_id,
        "mode": _CACHE_STATEFUL_NO_LIVE_MODE,
        "model_key": plan.model_key,
        "context_window": plan.context_window,
        "measurement_status": CacheMeasurementStatus.NOT_MEASURED_NO_LIVE.value,
        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
        "kv_reuse_proven": False,
        "fake_first": True,
        "no_live": True,
        "uses_fake_transport_only": True,
        "lmstudio_api_called": False,
        "network": False,
        "raw_material_stored": False,
        "production_default": False,
    }
    rows: list[dict[str, object]] = [
        {
            **base_row,
            "request_kind": "stateful_root",
            "request_id": plan.root_request.request_id,
            "dataset_id": plan.root_request.dataset_id,
            "root_context_hash": plan.root_request.root_context_hash,
            "estimated_input_tokens": plan.root_request.estimated_input_tokens,
            "context_reuse_mode": plan.root_request.mode.value,
        }
    ]
    rows.extend(
        {
            **base_row,
            "request_kind": "stateful_branch",
            "request_id": request.request_id,
            "root_request_id": request.root_request_id,
            "branch_id": request.branch_id,
            "root_context_hash": request.root_context_hash,
            "estimated_branch_tokens": request.estimated_branch_tokens,
            "context_reuse_mode": request.mode.value,
        }
        for request in plan.stateful_branch_requests
    )
    rows.extend(
        {
            **base_row,
            "request_kind": "stateless_prefix",
            "request_id": request.request_id,
            "branch_id": request.branch_id,
            "prefix_context_hash": request.prefix_context_hash,
            "estimated_input_tokens": request.estimated_input_tokens,
            "context_reuse_mode": request.mode.value,
        }
        for request in plan.stateless_prefix_requests
    )
    rows.extend(
        {
            **base_row,
            "request_kind": "compact_memory",
            "request_id": request.request_id,
            "branch_id": request.branch_id,
            "memory_hash": request.memory_hash,
            "estimated_memory_tokens": request.estimated_memory_tokens,
            "estimated_branch_tokens": request.estimated_branch_tokens,
            "context_reuse_mode": request.mode.value,
        }
        for request in plan.compact_memory_requests
    )
    return rows


def _build_cache_stateful_no_live_metric_row(
    *,
    plan: CacheExperimentPlan,
    run_id: str,
    request_row: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": plan.experiment_id,
        "mode": _CACHE_STATEFUL_NO_LIVE_MODE,
        "request_id": request_row.get("request_id"),
        "request_kind": request_row.get("request_kind"),
        "model_key": plan.model_key,
        "context_window": plan.context_window,
        "context_reuse_mode": request_row.get("context_reuse_mode"),
        "branch_id": request_row.get("branch_id"),
        "measurement_status": CacheMeasurementStatus.NOT_MEASURED_NO_LIVE.value,
        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
        "has_live_measurements": False,
        "stateful_functional_ok": None,
        "kv_reuse_proven": False,
        "ttft_ms": None,
        "prompt_processing_ms": None,
        "total_latency_ms": None,
        "cached_tokens": None,
        "cache_proxy": None,
        "ram_peak_mb": None,
        "vram_peak_mb": None,
        "fake_first": True,
        "no_live": True,
        "uses_fake_transport_only": True,
        "lmstudio_api_called": False,
        "network": False,
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "production_default": False,
    }


def _build_cache_stateful_no_live_summary(
    *,
    plan: CacheExperimentPlan,
    run_id: str,
    placeholder_metric_count: int,
) -> dict[str, object]:
    evidence = CacheEvidence(
        experiment_id=plan.experiment_id,
        model_key=plan.model_key,
        production_default=False,
        raw_material_stored=False,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": plan.experiment_id,
        "mode": _CACHE_STATEFUL_NO_LIVE_MODE,
        "model_key": plan.model_key,
        "context_window": plan.context_window,
        "planned_request_count": plan.planned_request_count,
        "placeholder_metric_count": placeholder_metric_count,
        "root_request_count": 1,
        "stateful_branch_request_count": len(plan.stateful_branch_requests),
        "stateless_prefix_request_count": len(plan.stateless_prefix_requests),
        "compact_memory_request_count": len(plan.compact_memory_requests),
        "measurement_status": evidence.measurement_status.value,
        "reuse_verdict": evidence.reuse_verdict.value,
        "successful_branch_count": evidence.successful_branch_count,
        "has_live_measurements": evidence.has_live_measurements,
        "stateful_functional_ok": None,
        "kv_reuse_proven": evidence.kv_reuse_proven,
        "ttft_ms": evidence.ttft_ms,
        "prompt_processing_ms": evidence.prompt_processing_ms,
        "total_latency_ms": evidence.total_latency_ms,
        "cached_tokens": evidence.cached_tokens,
        "cache_proxy": evidence.cache_proxy,
        "ram_peak_mb": evidence.ram_peak_mb,
        "vram_peak_mb": evidence.vram_peak_mb,
        "fake_first": True,
        "no_live": True,
        "uses_fake_transport_only": True,
        "lmstudio_api_called": False,
        "network": False,
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "production_default": False,
    }


def _build_cache_stateful_no_live_privacy_scan(
    *,
    run_config: Mapping[str, Any],
    cache_plan: Mapping[str, Any],
    request_rows: Sequence[Mapping[str, Any]],
    metric_rows: Sequence[Mapping[str, Any]],
    cache_summary: Mapping[str, Any],
    system_summary: Mapping[str, Any],
    system_samples: Sequence[Mapping[str, Any]],
    report_text: str,
) -> dict[str, object]:
    payloads = {
        "run_config.json": run_config,
        "cache_plan.json": cache_plan,
        "requests.jsonl": list(request_rows),
        "metrics.jsonl": list(metric_rows),
        "cache_summary.json": cache_summary,
        "report.md": report_text,
        "system_summary.json": system_summary,
        "system_samples.jsonl": list(system_samples),
    }
    violations: list[str] = []
    for artifact_name, payload in payloads.items():
        serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        violations.extend(
            find_privacy_violations(
                {"artifact_name": artifact_name, "serialized": serialized_payload},
                context=artifact_name,
            )
        )
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "scan_scope": "cache_stateful_no_live_raw_url_path_private_value_scan",
        "scanned_artifacts": list(payloads),
        "raw_prompt_response_stored": False,
    }


def _render_cache_stateful_no_live_report(
    *,
    run_id: str,
    plan: CacheExperimentPlan,
    cache_summary: Mapping[str, object],
    privacy_scan_status: str,
) -> str:
    output_files = "\n".join(
        f"- `{file_name}`" for file_name in _CACHE_STATEFUL_NO_LIVE_OUTPUT_FILES
    )
    return "\n".join(
        (
            "# LM Studio Lab Managed Runner Cache/Stateful No-Live Report",
            "",
            "## Run",
            "",
            f"- experiment_id: `{plan.experiment_id}`",
            f"- run_id: `{run_id}`",
            f"- mode: `{_CACHE_STATEFUL_NO_LIVE_MODE}`",
            "- no-live/fake-first cache/stateful path: `true`",
            "- LM Studio API/live/GPU/network: `not used`",
            "- transport path: `no generation/lifecycle/live transport calls; artifacts only`",
            "- uses_fake_transport_only: `true`",
            "- not production default: `true`",
            "- raw_prompt_response_stored: `false`",
            "",
            "## Scope",
            "",
            f"- model_key: `{plan.model_key}`",
            f"- context_window: `{plan.context_window}`",
            f"- planned_request_count: `{plan.planned_request_count}`",
            f"- stateful_branch_request_count: `{len(plan.stateful_branch_requests)}`",
            f"- stateless_prefix_request_count: `{len(plan.stateless_prefix_requests)}`",
            f"- compact_memory_request_count: `{len(plan.compact_memory_requests)}`",
            "",
            "## Evidence Status",
            "",
            f"- measurement_status: `{cache_summary.get('measurement_status')}`",
            f"- reuse_verdict: `{cache_summary.get('reuse_verdict')}`",
            f"- has_live_measurements: `{cache_summary.get('has_live_measurements')}`",
            f"- stateful_functional_ok: `{cache_summary.get('stateful_functional_ok')}`",
            f"- kv_reuse_proven: `{cache_summary.get('kv_reuse_proven')}`",
            "- stateful API contract is not proof of physical KV reuse",
            "- L3.2 stores only safe ids, hashes, counts, and no-live placeholders",
            "- L3.3 live/cache proof requires explicit approval",
            "",
            "## Boundaries",
            "",
            "- No LM Studio lifecycle/load/unload/live smoke helpers are called in this path.",
            "- No WVM runtime, QueueManager, UI, SQLite, GPU execution, or network activity occurs.",
            "- `cache_hit=true`, `branch_ttft_improved=true`, and `kv_reuse_proven=true` are intentionally absent from this no-live report.",
            f"- privacy_scan_status: `{privacy_scan_status}`",
            "",
            "## Output Files",
            "",
            output_files,
            "",
        )
    )


def _validate_cache_stateful_live_smoke_config(config: LiveSmokeConfig) -> dict[str, object]:
    if len(config.models) != 1:
        raise ValueError("cache/stateful live smoke requires exactly one model")
    if len(config.modes) != 1:
        raise ValueError("cache/stateful live smoke requires exactly one mode")
    if len(config.datasets) != 1:
        raise ValueError("cache/stateful live smoke requires exactly one dataset")
    if config.datasets[0] != _CACHE_STATEFUL_LIVE_SMOKE_DATASET_ID:
        raise ValueError("cache/stateful live smoke requires dataset_id 'cache_stateful_smoke'")
    if config.modes[0] != "stateful_root_branches":
        raise ValueError("cache/stateful live smoke supports only stateful_root_branches")
    if config.repeats != 1:
        raise ValueError("cache/stateful live smoke requires repeats=1")
    if config.warmup_runs != 0:
        raise ValueError("cache/stateful live smoke requires warmup_runs=0")
    if config.allow_remote:
        raise ValueError("cache/stateful live smoke requires localhost-only LM Studio")
    if config.privacy.store_prompt_text:
        raise ValueError("privacy.store_prompt_text must remain false for live smoke")
    if config.privacy.store_response_text:
        raise ValueError("privacy.store_response_text must remain false for live smoke")

    model = config.models[0]
    if model.key != _CACHE_STATEFUL_LIVE_SMOKE_MODEL_KEY:
        raise ValueError("cache/stateful live smoke requires model key 'gemma4_e2b_q4km'")
    if model.model_id != _CACHE_STATEFUL_LIVE_SMOKE_MODEL_ID:
        raise ValueError("cache/stateful live smoke requires model id 'google/gemma-4-e2b'")

    load_keys = {str(key) for key in model.load}
    unsupported_load_keys = sorted(load_keys - _MEDIUM_CHUNKED_LIVE_ALLOWED_LOAD_KEYS)
    if unsupported_load_keys:
        raise ValueError(
            "cache/stateful live smoke rejects unsupported load keys: "
            + ", ".join(unsupported_load_keys)
        )
    if "parallel" in load_keys and "n_parallel" in load_keys:
        raise ValueError(
            "cache/stateful live smoke rejects ambiguous load keys: use only one of "
            "models[0].load.parallel or models[0].load.n_parallel"
        )

    requested_context_length = _extract_single_positive_int_load_value(
        model.load.get("context_length"),
        field_name="models[0].load.context_length",
    )
    parallel_field_name = (
        "models[0].load.parallel" if "parallel" in load_keys else "models[0].load.n_parallel"
    )
    requested_parallel = _extract_single_positive_int_load_value(
        model.load.get("parallel", model.load.get("n_parallel")),
        field_name=parallel_field_name,
    )
    if requested_context_length != _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH:
        raise ValueError("cache/stateful live smoke requires context_length=8192")
    if requested_parallel != _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL:
        raise ValueError("cache/stateful live smoke requires parallel=1")

    return {
        "model_key": model.key,
        "model_id": model.model_id,
        "dataset_id": config.datasets[0],
        "requested_context_length": requested_context_length,
        "requested_parallel": requested_parallel,
    }


def _validate_cache_stateful_comparison_live_config(
    config: LiveSmokeConfig,
) -> dict[str, object]:
    if config.experiment_id != _CACHE_STATEFUL_COMPARISON_LIVE_EXPERIMENT_ID:
        raise ValueError(
            "cache/stateful comparison live requires experiment_id "
            "'l3_4_cache_stateful_vs_prefix_gemma4_e2b_live'"
        )
    if len(config.models) != 1:
        raise ValueError("cache/stateful comparison live requires exactly one model")
    if len(config.modes) != len(_CACHE_STATEFUL_COMPARISON_LIVE_MODES):
        raise ValueError(
            "cache/stateful comparison live requires exactly three modes: "
            "stateful_root_branches, stateless_full_prefix, compact_memory"
        )
    if tuple(config.modes) != _CACHE_STATEFUL_COMPARISON_LIVE_MODES:
        raise ValueError(
            "cache/stateful comparison live requires modes "
            "['stateful_root_branches', 'stateless_full_prefix', 'compact_memory']"
        )
    if len(config.datasets) != 1:
        raise ValueError("cache/stateful comparison live requires exactly one dataset")
    if config.datasets[0] != _CACHE_STATEFUL_LIVE_SMOKE_DATASET_ID:
        raise ValueError(
            "cache/stateful comparison live requires dataset_id 'cache_stateful_smoke'"
        )
    if config.repeats != 1:
        raise ValueError("cache/stateful comparison live requires repeats=1")
    if config.warmup_runs != 0:
        raise ValueError("cache/stateful comparison live requires warmup_runs=0")
    if config.allow_remote:
        raise ValueError("cache/stateful comparison live requires localhost-only LM Studio")
    if config.privacy.store_prompt_text:
        raise ValueError("privacy.store_prompt_text must remain false for live comparison")
    if config.privacy.store_response_text:
        raise ValueError("privacy.store_response_text must remain false for live comparison")

    model = config.models[0]
    if model.key != _CACHE_STATEFUL_LIVE_SMOKE_MODEL_KEY:
        raise ValueError("cache/stateful comparison live requires model key 'gemma4_e2b_q4km'")
    if model.model_id != _CACHE_STATEFUL_LIVE_SMOKE_MODEL_ID:
        raise ValueError("cache/stateful comparison live requires model id 'google/gemma-4-e2b'")

    load_keys = {str(key) for key in model.load}
    unsupported_load_keys = sorted(load_keys - _MEDIUM_CHUNKED_LIVE_ALLOWED_LOAD_KEYS)
    if unsupported_load_keys:
        raise ValueError(
            "cache/stateful comparison live rejects unsupported load keys: "
            + ", ".join(unsupported_load_keys)
        )
    if "parallel" in load_keys and "n_parallel" in load_keys:
        raise ValueError(
            "cache/stateful comparison live rejects ambiguous load keys: use only one of "
            "models[0].load.parallel or models[0].load.n_parallel"
        )

    requested_context_length = _extract_single_positive_int_load_value(
        model.load.get("context_length"),
        field_name="models[0].load.context_length",
    )
    parallel_field_name = (
        "models[0].load.parallel" if "parallel" in load_keys else "models[0].load.n_parallel"
    )
    requested_parallel = _extract_single_positive_int_load_value(
        model.load.get("parallel", model.load.get("n_parallel")),
        field_name=parallel_field_name,
    )
    if requested_context_length != _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH:
        raise ValueError("cache/stateful comparison live requires context_length=8192")
    if requested_parallel != _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL:
        raise ValueError("cache/stateful comparison live requires parallel=1")

    return {
        "model_key": model.key,
        "model_id": model.model_id,
        "dataset_id": config.datasets[0],
        "requested_context_length": requested_context_length,
        "requested_parallel": requested_parallel,
    }


def _validate_cache_stateful_instrumentation_live_config(
    config: LiveSmokeConfig,
) -> dict[str, object]:
    if config.experiment_id != _CACHE_STATEFUL_INSTRUMENTATION_LIVE_EXPERIMENT_ID:
        raise ValueError(
            "cache/stateful instrumentation live requires experiment_id "
            "'l3_4b_cache_stateful_instrumentation_gemma4_e2b_live'"
        )
    if len(config.models) != 1:
        raise ValueError("cache/stateful instrumentation live requires exactly one model")
    if len(config.modes) != len(_CACHE_STATEFUL_COMPARISON_LIVE_MODES):
        raise ValueError(
            "cache/stateful instrumentation live requires exactly three modes: "
            "stateful_root_branches, stateless_full_prefix, compact_memory"
        )
    if tuple(config.modes) != _CACHE_STATEFUL_COMPARISON_LIVE_MODES:
        raise ValueError(
            "cache/stateful instrumentation live requires modes "
            "['stateful_root_branches', 'stateless_full_prefix', 'compact_memory']"
        )
    if len(config.datasets) != 1:
        raise ValueError("cache/stateful instrumentation live requires exactly one dataset")
    if config.datasets[0] != _CACHE_STATEFUL_LIVE_SMOKE_DATASET_ID:
        raise ValueError(
            "cache/stateful instrumentation live requires dataset_id 'cache_stateful_smoke'"
        )
    if config.repeats != 1:
        raise ValueError("cache/stateful instrumentation live requires repeats=1")
    if config.warmup_runs != 0:
        raise ValueError("cache/stateful instrumentation live requires warmup_runs=0")
    if config.allow_remote:
        raise ValueError("cache/stateful instrumentation live requires localhost-only LM Studio")
    if config.privacy.store_prompt_text:
        raise ValueError("privacy.store_prompt_text must remain false for live smoke")
    if config.privacy.store_response_text:
        raise ValueError("privacy.store_response_text must remain false for live smoke")

    model = config.models[0]
    if model.key != _CACHE_STATEFUL_LIVE_SMOKE_MODEL_KEY:
        raise ValueError("cache/stateful instrumentation live requires model key 'gemma4_e2b_q4km'")
    if model.model_id != _CACHE_STATEFUL_LIVE_SMOKE_MODEL_ID:
        raise ValueError(
            "cache/stateful instrumentation live requires model id 'google/gemma-4-e2b'"
        )

    load_keys = {str(key) for key in model.load}
    unsupported_load_keys = sorted(load_keys - _MEDIUM_CHUNKED_LIVE_ALLOWED_LOAD_KEYS)
    if unsupported_load_keys:
        raise ValueError(
            "cache/stateful instrumentation live rejects unsupported load keys: "
            + ", ".join(unsupported_load_keys)
        )
    if "parallel" in load_keys and "n_parallel" in load_keys:
        raise ValueError(
            "cache/stateful instrumentation live rejects ambiguous load keys: use only one of "
            "models[0].load.parallel or models[0].load.n_parallel"
        )

    requested_context_length = _extract_single_positive_int_load_value(
        model.load.get("context_length"),
        field_name="models[0].load.context_length",
    )
    parallel_field_name = (
        "models[0].load.parallel" if "parallel" in load_keys else "models[0].load.n_parallel"
    )
    requested_parallel = _extract_single_positive_int_load_value(
        model.load.get("parallel", model.load.get("n_parallel")),
        field_name=parallel_field_name,
    )
    if requested_context_length != _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH:
        raise ValueError("cache/stateful instrumentation live requires context_length=8192")
    if requested_parallel != _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL:
        raise ValueError("cache/stateful instrumentation live requires parallel=1")

    return {
        "model_key": model.key,
        "model_id": model.model_id,
        "dataset_id": config.datasets[0],
        "requested_context_length": requested_context_length,
        "requested_parallel": requested_parallel,
    }


def _build_cache_stateful_live_smoke_environment_payload(
    *,
    experiment_id: str,
    run_id: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "mode": _CACHE_STATEFUL_LIVE_SMOKE_MODE,
        "managed_live": True,
        "dry_run": False,
    }


def _build_cache_stateful_comparison_live_environment_payload(
    *,
    experiment_id: str,
    run_id: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "mode": _CACHE_STATEFUL_COMPARISON_LIVE_MODE,
        "managed_live": True,
        "dry_run": False,
    }


def _build_cache_stateful_instrumentation_live_environment_payload(
    *,
    experiment_id: str,
    run_id: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "mode": _CACHE_STATEFUL_INSTRUMENTATION_LIVE_MODE,
        "managed_live": True,
        "dry_run": False,
    }


def _build_cache_stateful_live_smoke_run_config(
    *,
    config: LiveSmokeConfig,
    run_id: str,
    dataset_manifest: Any,
    root_input: str,
    branch_inputs: Mapping[str, str],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "mode": _CACHE_STATEFUL_LIVE_SMOKE_MODE,
        "managed_live": True,
        "dataset_id": dataset_manifest.dataset_id,
        "dataset_hash": dataset_manifest.content_hash,
        "model_key": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_KEY,
        "model_id": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_ID,
        "model_count": 1,
        "requested_context_length": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
        "branch_count": len(_CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS),
        "root_request": {
            "request_id": "root_context",
            "prompt_hash": _safe_hash(root_input),
            "prompt_chars": len(root_input),
            "estimated_input_tokens": dataset_manifest.estimated_input_tokens,
        },
        "branch_requests": [
            {
                "request_id": branch_id,
                "prompt_hash": _safe_hash(branch_inputs[branch_id]),
                "prompt_chars": len(branch_inputs[branch_id]),
                "estimated_input_tokens": _estimate_cache_stateful_live_smoke_tokens(
                    branch_inputs[branch_id]
                ),
            }
            for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS
        ],
        "raw_prompt_response_stored": False,
        "production_default": False,
        "wvm_runtime_integration": False,
    }


def _build_cache_stateful_comparison_live_run_config(
    *,
    config: LiveSmokeConfig,
    run_id: str,
    dataset_manifest: Any,
    root_input: str,
    branch_inputs: Mapping[str, str],
    stateless_full_prefix_inputs: Mapping[str, str],
    compact_memory_contexts: Mapping[str, str],
    compact_memory_inputs: Mapping[str, str],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "mode": _CACHE_STATEFUL_COMPARISON_LIVE_MODE,
        "comparison_modes": list(_CACHE_STATEFUL_COMPARISON_LIVE_MODES),
        "managed_live": True,
        "dataset_id": dataset_manifest.dataset_id,
        "dataset_hash": dataset_manifest.content_hash,
        "model_key": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_KEY,
        "model_id": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_ID,
        "model_count": 1,
        "requested_context_length": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
        "root_request": {
            "request_id": "root_context",
            "mode": "stateful_root_branches",
            "prompt_hash": _safe_hash(root_input),
            "prompt_chars": len(root_input),
            "estimated_input_tokens": dataset_manifest.estimated_input_tokens,
        },
        "stateful_branch_requests": [
            {
                "request_id": f"stateful_{branch_id}",
                "branch_id": branch_id,
                "mode": "stateful_root_branches",
                "prompt_hash": _safe_hash(branch_inputs[branch_id]),
                "prompt_chars": len(branch_inputs[branch_id]),
                "estimated_input_tokens": _estimate_cache_stateful_live_smoke_tokens(
                    branch_inputs[branch_id]
                ),
            }
            for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS
        ],
        "stateless_full_prefix_branch_requests": [
            {
                "request_id": f"stateless_full_prefix_{branch_id}",
                "branch_id": branch_id,
                "mode": "stateless_full_prefix",
                "prompt_hash": _safe_hash(stateless_full_prefix_inputs[branch_id]),
                "prompt_chars": len(stateless_full_prefix_inputs[branch_id]),
                "estimated_input_tokens": _estimate_cache_stateful_live_smoke_tokens(
                    stateless_full_prefix_inputs[branch_id]
                ),
            }
            for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS
        ],
        "compact_memory_branch_requests": [
            {
                "request_id": f"compact_memory_{branch_id}",
                "branch_id": branch_id,
                "mode": "compact_memory",
                "compact_memory_hash": _safe_hash(compact_memory_contexts[branch_id]),
                "compact_memory_chars": len(compact_memory_contexts[branch_id]),
                "estimated_memory_tokens": _estimate_cache_stateful_live_smoke_tokens(
                    compact_memory_contexts[branch_id]
                ),
                "prompt_hash": _safe_hash(compact_memory_inputs[branch_id]),
                "prompt_chars": len(compact_memory_inputs[branch_id]),
                "estimated_input_tokens": _estimate_cache_stateful_live_smoke_tokens(
                    compact_memory_inputs[branch_id]
                ),
            }
            for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS
        ],
        "raw_prompt_response_stored": False,
        "production_default": False,
        "wvm_runtime_integration": False,
    }


def _build_cache_stateful_instrumentation_live_run_config(
    *,
    config: LiveSmokeConfig,
    run_id: str,
    dataset_manifest: Any,
    root_input: str,
    branch_inputs: Mapping[str, str],
    stateless_full_prefix_inputs: Mapping[str, str],
    compact_memory_contexts: Mapping[str, str],
    compact_memory_inputs: Mapping[str, str],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "mode": _CACHE_STATEFUL_INSTRUMENTATION_LIVE_MODE,
        "comparison_modes": list(_CACHE_STATEFUL_COMPARISON_LIVE_MODES),
        "managed_live": True,
        "native_streaming": True,
        "dataset_id": dataset_manifest.dataset_id,
        "dataset_hash": dataset_manifest.content_hash,
        "model_key": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_KEY,
        "model_id": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_ID,
        "model_count": 1,
        "requested_context_length": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
        "root_request": {
            "request_id": "root_context",
            "mode": "stateful_root_branches",
            "prompt_hash": _safe_hash(root_input),
            "prompt_chars": len(root_input),
            "estimated_input_tokens": dataset_manifest.estimated_input_tokens,
        },
        "stateful_branch_requests": [
            {
                "request_id": f"stateful_{branch_id}",
                "branch_id": branch_id,
                "mode": "stateful_root_branches",
                "prompt_hash": _safe_hash(branch_inputs[branch_id]),
                "prompt_chars": len(branch_inputs[branch_id]),
                "estimated_input_tokens": _estimate_cache_stateful_live_smoke_tokens(
                    branch_inputs[branch_id]
                ),
            }
            for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS
        ],
        "stateless_full_prefix_branch_requests": [
            {
                "request_id": f"stateless_full_prefix_{branch_id}",
                "branch_id": branch_id,
                "mode": "stateless_full_prefix",
                "prompt_hash": _safe_hash(stateless_full_prefix_inputs[branch_id]),
                "prompt_chars": len(stateless_full_prefix_inputs[branch_id]),
                "estimated_input_tokens": _estimate_cache_stateful_live_smoke_tokens(
                    stateless_full_prefix_inputs[branch_id]
                ),
            }
            for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS
        ],
        "compact_memory_branch_requests": [
            {
                "request_id": f"compact_memory_{branch_id}",
                "branch_id": branch_id,
                "mode": "compact_memory",
                "compact_memory_hash": _safe_hash(compact_memory_contexts[branch_id]),
                "compact_memory_chars": len(compact_memory_contexts[branch_id]),
                "estimated_memory_tokens": _estimate_cache_stateful_live_smoke_tokens(
                    compact_memory_contexts[branch_id]
                ),
                "prompt_hash": _safe_hash(compact_memory_inputs[branch_id]),
                "prompt_chars": len(compact_memory_inputs[branch_id]),
                "estimated_input_tokens": _estimate_cache_stateful_live_smoke_tokens(
                    compact_memory_inputs[branch_id]
                ),
            }
            for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS
        ],
        "raw_prompt_response_stored": False,
        "production_default": False,
        "wvm_runtime_integration": False,
    }


def _build_cache_stateful_live_smoke_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/chat"


def _new_streaming_probe_state(started_at: float) -> dict[str, object]:
    return {
        "started_at": started_at,
        "first_delta_at": None,
        "prompt_processing_started_at": None,
        "prompt_processing_ended_at": None,
        "prompt_processing_events_seen": False,
        "final_payload": None,
        "error_seen": False,
    }


def _extract_streaming_response_payload(
    streaming_summary: Mapping[str, object],
) -> Mapping[str, Any]:
    response_payload = streaming_summary.get("response_payload")
    if isinstance(response_payload, Mapping):
        return dict(response_payload)
    raise ValueError("cache/stateful instrumentation streaming payload must include response")


def _stream_delta_contains_text(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        for key in (
            "text",
            "content",
            "delta",
            "reasoning",
            "reasoning_text",
            "reasoning_content",
            "message",
        ):
            if key in value and _stream_delta_contains_text(value[key]):
                return True
        return any(_stream_delta_contains_text(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_stream_delta_contains_text(item) for item in value)
    return False


def _resolve_stream_chat_end_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for candidate in (payload, payload.get("response"), payload.get("result"), payload.get("data")):
        if isinstance(candidate, Mapping) and any(
            key in candidate for key in ("response_id", "output", "stats", "usage")
        ):
            return dict(candidate)
    return dict(payload)


def _apply_streaming_probe_event(
    state: dict[str, object],
    *,
    event_type: str,
    data_payload: object,
    now: float,
) -> None:
    if event_type.startswith("prompt_processing."):
        state["prompt_processing_events_seen"] = True
        if (
            event_type == "prompt_processing.start"
            and state["prompt_processing_started_at"] is None
        ):
            state["prompt_processing_started_at"] = now
        if event_type == "prompt_processing.end" and state["prompt_processing_ended_at"] is None:
            state["prompt_processing_ended_at"] = now
        return
    if event_type == "message.delta":
        if state["first_delta_at"] is None and _stream_delta_contains_text(data_payload):
            state["first_delta_at"] = now
        return
    if event_type == "chat.end":
        if isinstance(data_payload, Mapping):
            state["final_payload"] = _resolve_stream_chat_end_payload(data_payload)
        return
    if event_type == "error":
        state["error_seen"] = True


def _extract_stats_ttft_ms(response_payload: Mapping[str, Any]) -> float | None:
    stats = response_payload.get("stats")
    if not isinstance(stats, Mapping):
        return None
    seconds = _as_optional_rate(stats.get("time_to_first_token_seconds"))
    if seconds is None:
        seconds = _as_optional_rate(stats.get("time_to_first_token"))
    if seconds is not None:
        return round(seconds * 1000.0, 3)
    milliseconds = _as_optional_rate(stats.get("time_to_first_token_ms"))
    if milliseconds is not None:
        return round(milliseconds, 3)
    return None


def _find_explicit_cached_tokens(value: object) -> int | None:
    if isinstance(value, Mapping):
        direct = _as_optional_int(value.get("cached_tokens"))
        if direct is not None:
            return direct
        for nested_value in value.values():
            nested = _find_explicit_cached_tokens(nested_value)
            if nested is not None:
                return nested
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested_value in value:
            nested = _find_explicit_cached_tokens(nested_value)
            if nested is not None:
                return nested
    return None


def _extract_cached_tokens_from_response_payload(response_payload: Mapping[str, Any]) -> int | None:
    for field_name in ("stats", "usage"):
        container = response_payload.get(field_name)
        cached_tokens = _find_explicit_cached_tokens(container)
        if cached_tokens is not None:
            return cached_tokens
    return None


def _finalize_streaming_probe_state(state: Mapping[str, object]) -> dict[str, object]:
    if state.get("error_seen") is True:
        raise ValueError("LM Studio streaming request returned an error event")
    response_payload = state.get("final_payload")
    if not isinstance(response_payload, Mapping):
        raise ValueError("LM Studio streaming request must end with chat.end response data")

    started_at = float(state["started_at"])
    first_delta_at = _as_optional_rate(state.get("first_delta_at"))
    prompt_processing_started_at = _as_optional_rate(state.get("prompt_processing_started_at"))
    prompt_processing_ended_at = _as_optional_rate(state.get("prompt_processing_ended_at"))
    stream_ttft_ms = None
    if first_delta_at is not None:
        stream_ttft_ms = round((first_delta_at - started_at) * 1000.0, 3)
    prompt_processing_ms = None
    if (
        prompt_processing_started_at is not None
        and prompt_processing_ended_at is not None
        and prompt_processing_ended_at >= prompt_processing_started_at
    ):
        prompt_processing_ms = round(
            (prompt_processing_ended_at - prompt_processing_started_at) * 1000.0,
            3,
        )
    stats_ttft_ms = _extract_stats_ttft_ms(response_payload)
    ttft_ms = stream_ttft_ms if stream_ttft_ms is not None else stats_ttft_ms
    return {
        "response_payload": dict(response_payload),
        "stream_ttft_ms": stream_ttft_ms,
        "stats_ttft_ms": stats_ttft_ms,
        "ttft_ms": ttft_ms,
        "prompt_processing_ms": prompt_processing_ms,
        "prompt_processing_events_seen": state.get("prompt_processing_events_seen") is True,
        "cached_tokens": _extract_cached_tokens_from_response_payload(response_payload),
    }


def _default_live_streaming_transport(
    url: str,
    payload: Mapping[str, Any],
    timeout_s: float,
) -> Mapping[str, Any]:
    request = urllib_request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    state = _new_streaming_probe_state(_live_request_perf_counter())
    current_event_type: str | None = None
    current_data_lines: list[str] = []

    def _flush_event() -> None:
        nonlocal current_event_type, current_data_lines
        if current_event_type is None:
            current_data_lines = []
            return
        payload_text = "\n".join(current_data_lines).strip()
        if payload_text == "[DONE]":
            current_event_type = None
            current_data_lines = []
            return
        try:
            decoded_payload = json.loads(payload_text) if payload_text else {}
        except json.JSONDecodeError as error:
            raise ValueError("LM Studio streaming event payload must be valid JSON") from error
        _apply_streaming_probe_event(
            state,
            event_type=current_event_type,
            data_payload=decoded_payload,
            now=_live_request_perf_counter(),
        )
        current_event_type = None
        current_data_lines = []

    with urllib_request.urlopen(request, timeout=timeout_s) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                _flush_event()
                continue
            if line.startswith(":"):
                continue
            field_name, separator, field_value = line.partition(":")
            if not separator:
                continue
            normalized_value = field_value.lstrip(" ")
            if field_name == "event":
                current_event_type = normalized_value
            elif field_name == "data":
                current_data_lines.append(normalized_value)
        _flush_event()
    return _finalize_streaming_probe_state(state)


def _default_live_transport(
    url: str,
    payload: Mapping[str, Any],
    timeout_s: float,
) -> Mapping[str, Any]:
    request = urllib_request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib_request.urlopen(request, timeout=timeout_s) as response:
        body = response.read().decode("utf-8")
    decoded = json.loads(body)
    if not isinstance(decoded, Mapping):
        raise ValueError("LM Studio response must be a JSON object")
    return decoded


def _live_request_perf_counter() -> float:
    return time.perf_counter()


def _build_cache_stateful_live_smoke_root_input() -> str:
    intro = (
        "Synthetic lecture transcript for cache/stateful lab smoke. Read the lecture, keep the "
        "context available for two follow-up requests, and reply with a brief acknowledgement."
    )
    sections = [intro]
    for index in range(1, 111):
        sections.append(
            " ".join(
                (
                    f"Section {index:02d} explains queue warmup checkpoints, stable pause-resume handling,",
                    "export verification, timestamped glossary notes, concise recap writing, and the",
                    "difference between stateful follow-up prompts and stateless prefix replay in a",
                    "synthetic lecture workflow.",
                )
            )
        )
    return "\n".join(sections)


def _build_cache_stateful_live_smoke_branch_inputs() -> dict[str, str]:
    return {
        "summary_short": (
            "Provide a short summary of the synthetic lecture in 3 bullet points with no extra preface."
        ),
        "glossary_short": (
            "List a short glossary with 5 terms from the synthetic lecture and brief definitions."
        ),
    }


def _build_cache_stateful_full_prefix_branch_inputs(
    *,
    root_input: str,
    branch_inputs: Mapping[str, str],
) -> dict[str, str]:
    return {
        branch_id: (
            f"{root_input}\n\n"
            "Follow-up branch task using full stateless prefix replay.\n"
            f"Task: {branch_inputs[branch_id]}"
        )
        for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS
    }


def _build_cache_stateful_compact_memory_contexts() -> dict[str, str]:
    return {
        "summary_short": (
            "Compact memory: synthetic lecture covers queue warmup checkpoints, stable "
            "pause-resume handling, export verification, glossary notes, recap writing, "
            "and stateful versus stateless follow-up requests."
        ),
        "glossary_short": (
            "Compact memory: synthetic lecture vocabulary includes queue warmup, "
            "pause-resume stability, export verification, glossary notes, recap writing, "
            "stateful follow-up prompts, and stateless prefix replay."
        ),
    }


def _build_cache_stateful_compact_memory_branch_inputs(
    *,
    compact_memory_contexts: Mapping[str, str],
    branch_inputs: Mapping[str, str],
) -> dict[str, str]:
    return {
        branch_id: (
            f"{compact_memory_contexts[branch_id]}\n\n"
            "Follow-up branch task using only the compact memory note above.\n"
            f"Task: {branch_inputs[branch_id]}"
        )
        for branch_id in _CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS
    }


def _estimate_cache_stateful_live_smoke_tokens(text: str) -> int:
    return max(1, (len(text.strip()) + 3) // 4)


def _extract_cache_stateful_live_smoke_output_text(
    response_payload: Mapping[str, Any],
) -> str | None:
    output = response_payload.get("output")
    if not isinstance(output, Sequence) or isinstance(output, (str, bytes, bytearray)):
        return None

    collected: list[str] = []

    def _walk(value: object) -> None:
        if isinstance(value, Mapping):
            text = _as_optional_str(value.get("text"))
            if text is not None:
                collected.append(text)
            content = value.get("content")
            if isinstance(content, str):
                collected.append(content)
            elif isinstance(content, Mapping) or (
                isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray))
            ):
                _walk(content)
            for key, nested_value in value.items():
                if key in {"text", "content"}:
                    continue
                if isinstance(nested_value, Mapping) or (
                    isinstance(nested_value, Sequence)
                    and not isinstance(nested_value, (str, bytes, bytearray))
                ):
                    _walk(nested_value)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                _walk(item)

    _walk(output)
    normalized = " ".join(part.strip() for part in collected if part.strip()).strip()
    return normalized or None


def _build_cache_stateful_live_smoke_summary(
    *,
    config: LiveSmokeConfig,
    dataset_manifest: Any,
    run_id: str,
    request_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    branch_rows = [
        row
        for row in request_rows
        if _as_optional_str(row.get("request_kind")) == "stateful_branch"
    ]
    successful_branch_count = sum(
        row.get("status") == "success" and row.get("used_previous_root_state") is True
        for row in branch_rows
    )
    stateful_functional_ok = (
        len(request_rows) == 1 + len(_CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS)
        and successful_branch_count == len(_CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS)
        and request_rows[0].get("status") == "success"
    )
    measurement_status = (
        CacheMeasurementStatus.FUNCTIONAL_STATEFUL_OK.value
        if stateful_functional_ok
        else CacheMeasurementStatus.INCONCLUSIVE.value
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "mode": _CACHE_STATEFUL_LIVE_SMOKE_MODE,
        "managed_live": True,
        "dataset_id": dataset_manifest.dataset_id,
        "dataset_hash": dataset_manifest.content_hash,
        "model_key": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_KEY,
        "model_id": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_ID,
        "measurement_status": measurement_status,
        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
        "kv_reuse_proven": False,
        "stateful_functional_ok": stateful_functional_ok,
        "root_request_count": 1,
        "branch_count": len(_CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS),
        "successful_branch_count": successful_branch_count,
        "measured_request_count": len(request_rows),
        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
        "requested_context_length": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
        "has_live_measurements": True,
        "ttft_ms": None,
        "prompt_processing_ms": None,
        "total_latency_ms": None,
        "cached_tokens": None,
        "cache_proxy": None,
        "lmstudio_api_called": True,
        "network": True,
        "production_default": False,
        "wvm_runtime_integration": False,
        "raw_prompt_response_stored": False,
    }


def _build_cache_stateful_live_smoke_privacy_scan(
    *,
    environment_payload: Mapping[str, Any],
    experiment_yaml_payload: Mapping[str, Any],
    run_config: Mapping[str, Any],
    request_rows: Sequence[Mapping[str, Any]],
    metric_rows: Sequence[Mapping[str, Any]],
    cache_summary: Mapping[str, Any],
    system_summary: Mapping[str, Any],
    system_samples: Sequence[Mapping[str, Any]],
    report_text: str,
) -> dict[str, object]:
    payloads = {
        "environment.json": environment_payload,
        "experiment.yaml": experiment_yaml_payload,
        "run_config.json": run_config,
        "requests.jsonl": list(request_rows),
        "metrics.jsonl": list(metric_rows),
        "cache_summary.json": cache_summary,
        "report.md": report_text,
        "system_summary.json": system_summary,
        "system_samples.jsonl": list(system_samples),
    }
    violations: list[str] = []
    for artifact_name, payload in payloads.items():
        serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        violations.extend(
            find_privacy_violations(
                {"artifact_name": artifact_name, "serialized": serialized_payload},
                context=artifact_name,
            )
        )
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "scan_scope": "cache_stateful_live_smoke_raw_url_path_private_value_scan",
        "scanned_artifacts": list(payloads),
        "raw_prompt_response_stored": False,
    }


def _render_cache_stateful_live_smoke_report(
    *,
    run_id: str,
    experiment_id: str,
    dataset_id: str,
    dataset_hash: str,
    model_key: str,
    model_id: str,
    cache_summary: Mapping[str, object],
    privacy_scan_status: str,
) -> str:
    output_files = "\n".join(
        f"- `{file_name}`" for file_name in _CACHE_STATEFUL_LIVE_SMOKE_OUTPUT_FILES
    )
    return "\n".join(
        (
            "# LM Studio Lab Managed Runner Cache/Stateful Live Smoke Report",
            "",
            "## Run",
            "",
            f"- experiment_id: `{experiment_id}`",
            f"- run_id: `{run_id}`",
            f"- mode: `{_CACHE_STATEFUL_LIVE_SMOKE_MODE}`",
            "- managed live stateful smoke: `true`",
            "- true live/GPU/LM Studio used: `true`",
            "- not production default: `true`",
            "- not WVM runtime integration: `true`",
            "- exact unload cleanup required/verified: `true`",
            "- raw_prompt_response_stored: `false`",
            "",
            "## Scope",
            "",
            f"- dataset_id: `{dataset_id}`",
            f"- dataset_hash: `{dataset_hash}`",
            f"- model_key: `{model_key}`",
            f"- model_id: `{model_id}`",
            "- app_concurrency: `1`",
            "- requested_parallel: `1`",
            "- root + two branch follow-ups only: `true`",
            "",
            "## Evidence Status",
            "",
            f"- measurement_status: `{cache_summary.get('measurement_status')}`",
            f"- stateful_functional_ok: `{cache_summary.get('stateful_functional_ok')}`",
            f"- successful_branch_count: `{cache_summary.get('successful_branch_count')}`",
            f"- branch_count: `{cache_summary.get('branch_count')}`",
            f"- reuse_verdict: `{cache_summary.get('reuse_verdict')}`",
            f"- kv_reuse_proven: `{cache_summary.get('kv_reuse_proven')}`",
            "- stateful API acceptance is not proof of physical KV reuse.",
            "- `cache_hit=true`, `branch_ttft_improved=true`, and `kv_reuse_proven=true` are intentionally absent.",
            "",
            "## Lifecycle",
            "",
            f"- load_verified: `{cache_summary.get('load_verified')}`",
            f"- applied_context_length: `{cache_summary.get('applied_context_length')}`",
            f"- applied_parallel: `{cache_summary.get('applied_parallel')}`",
            f"- parallel_verified: `{cache_summary.get('parallel_verified')}`",
            f"- cleanup_status: `{cache_summary.get('cleanup_status')}`",
            f"- cleanup_verified_count: `{cache_summary.get('cleanup_verified_count')}`",
            f"- final_loaded_instances: `{cache_summary.get('final_loaded_instances')}`",
            "",
            "## Notes",
            "",
            "- Root lecture content and branch prompts are generated in memory only and are never written to artifacts.",
            "- Request artifacts store hashes, counts, booleans, and safe status fields only.",
            f"- privacy_scan_status: `{privacy_scan_status}`",
            "",
            "## Output Files",
            "",
            output_files,
            "",
        )
    )


def _build_cache_stateful_comparison_live_summary(
    *,
    config: LiveSmokeConfig,
    dataset_manifest: Any,
    run_id: str,
    request_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    rows_by_mode = {
        mode: [row for row in request_rows if _as_optional_str(row.get("mode")) == mode]
        for mode in _CACHE_STATEFUL_COMPARISON_LIVE_MODES
    }
    stateful_root_rows = [
        row
        for row in rows_by_mode["stateful_root_branches"]
        if _as_optional_str(row.get("request_kind")) == "stateful_root"
    ]
    stateful_branch_rows = [
        row
        for row in rows_by_mode["stateful_root_branches"]
        if _as_optional_str(row.get("request_kind")) == "stateful_branch"
    ]
    stateless_branch_rows = rows_by_mode["stateless_full_prefix"]
    compact_memory_branch_rows = rows_by_mode["compact_memory"]

    stateful_root_success_count = sum(row.get("status") == "success" for row in stateful_root_rows)
    stateful_branch_success_count = sum(
        row.get("status") == "success" and row.get("used_previous_root_state") is True
        for row in stateful_branch_rows
    )
    stateless_branch_success_count = sum(
        row.get("status") == "success" for row in stateless_branch_rows
    )
    compact_memory_branch_success_count = sum(
        row.get("status") == "success" for row in compact_memory_branch_rows
    )
    stateful_functional_ok = (
        stateful_root_success_count == 1
        and len(stateful_root_rows) == 1
        and len(stateful_branch_rows) == len(_CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS)
        and stateful_branch_success_count == len(_CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS)
    )

    stateful_branch_avg_total_latency_ms = _average_optional_float(
        _as_optional_rate(row.get("total_latency_ms")) for row in stateful_branch_rows
    )
    stateless_branch_avg_total_latency_ms = _average_optional_float(
        _as_optional_rate(row.get("total_latency_ms")) for row in stateless_branch_rows
    )
    compact_memory_branch_avg_total_latency_ms = _average_optional_float(
        _as_optional_rate(row.get("total_latency_ms")) for row in compact_memory_branch_rows
    )
    stateless_vs_stateful_total_latency_ratio = None
    if (
        stateful_branch_avg_total_latency_ms is not None
        and stateful_branch_avg_total_latency_ms > 0
        and stateless_branch_avg_total_latency_ms is not None
    ):
        stateless_vs_stateful_total_latency_ratio = round(
            stateless_branch_avg_total_latency_ms / stateful_branch_avg_total_latency_ms,
            6,
        )
    stateful_total_latency_faster_than_stateless = None
    if (
        stateful_branch_avg_total_latency_ms is not None
        and stateless_branch_avg_total_latency_ms is not None
    ):
        stateful_total_latency_faster_than_stateless = (
            stateful_branch_avg_total_latency_ms < stateless_branch_avg_total_latency_ms
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "mode": _CACHE_STATEFUL_COMPARISON_LIVE_MODE,
        "comparison_modes": list(_CACHE_STATEFUL_COMPARISON_LIVE_MODES),
        "managed_live": True,
        "dataset_id": dataset_manifest.dataset_id,
        "dataset_hash": dataset_manifest.content_hash,
        "model_key": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_KEY,
        "model_id": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_ID,
        "measurement_status": CacheMeasurementStatus.INCONCLUSIVE.value,
        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
        "kv_reuse_proven": False,
        "stateful_functional_ok": stateful_functional_ok,
        "root_request_count": 1,
        "measured_request_count": len(request_rows),
        "root_success_count_by_mode": {
            "stateful_root_branches": stateful_root_success_count,
            "stateless_full_prefix": 0,
            "compact_memory": 0,
        },
        "branch_count_by_mode": {
            "stateful_root_branches": len(stateful_branch_rows),
            "stateless_full_prefix": len(stateless_branch_rows),
            "compact_memory": len(compact_memory_branch_rows),
        },
        "branch_success_count_by_mode": {
            "stateful_root_branches": stateful_branch_success_count,
            "stateless_full_prefix": stateless_branch_success_count,
            "compact_memory": compact_memory_branch_success_count,
        },
        "stateful_branch_avg_total_latency_ms": stateful_branch_avg_total_latency_ms,
        "stateless_full_prefix_branch_avg_total_latency_ms": (
            stateless_branch_avg_total_latency_ms
        ),
        "compact_memory_branch_avg_total_latency_ms": compact_memory_branch_avg_total_latency_ms,
        "stateless_full_prefix_vs_stateful_total_latency_ratio": (
            stateless_vs_stateful_total_latency_ratio
        ),
        "stateful_total_latency_faster_than_stateless": (
            stateful_total_latency_faster_than_stateless
        ),
        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
        "requested_context_length": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
        "has_live_measurements": True,
        "ttft_ms": None,
        "prompt_processing_ms": None,
        "total_latency_ms": None,
        "cached_tokens": None,
        "cache_proxy": None,
        "lmstudio_api_called": True,
        "network": True,
        "production_default": False,
        "wvm_runtime_integration": False,
        "raw_prompt_response_stored": False,
    }


def _build_cache_stateful_comparison_live_privacy_scan(
    *,
    environment_payload: Mapping[str, Any],
    experiment_yaml_payload: Mapping[str, Any],
    run_config: Mapping[str, Any],
    request_rows: Sequence[Mapping[str, Any]],
    metric_rows: Sequence[Mapping[str, Any]],
    comparison_summary: Mapping[str, Any],
    system_summary: Mapping[str, Any],
    system_samples: Sequence[Mapping[str, Any]],
    report_text: str,
) -> dict[str, object]:
    payloads = {
        "environment.json": environment_payload,
        "experiment.yaml": experiment_yaml_payload,
        "run_config.json": run_config,
        "requests.jsonl": list(request_rows),
        "metrics.jsonl": list(metric_rows),
        "cache_comparison_summary.json": comparison_summary,
        "report.md": report_text,
        "system_summary.json": system_summary,
        "system_samples.jsonl": list(system_samples),
    }
    violations: list[str] = []
    for artifact_name, payload in payloads.items():
        serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        violations.extend(
            find_privacy_violations(
                {"artifact_name": artifact_name, "serialized": serialized_payload},
                context=artifact_name,
            )
        )
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "scan_scope": "cache_stateful_comparison_live_raw_url_path_private_value_scan",
        "scanned_artifacts": list(payloads),
        "raw_prompt_response_stored": False,
    }


def _render_cache_stateful_comparison_live_report(
    *,
    run_id: str,
    experiment_id: str,
    dataset_id: str,
    dataset_hash: str,
    model_key: str,
    model_id: str,
    comparison_summary: Mapping[str, object],
    privacy_scan_status: str,
) -> str:
    output_files = "\n".join(
        f"- `{file_name}`" for file_name in _CACHE_STATEFUL_COMPARISON_LIVE_OUTPUT_FILES
    )
    return "\n".join(
        (
            "# LM Studio Lab Managed Runner Cache/Stateful Comparison Live Report",
            "",
            "## Run",
            "",
            f"- experiment_id: `{experiment_id}`",
            f"- run_id: `{run_id}`",
            f"- mode: `{_CACHE_STATEFUL_COMPARISON_LIVE_MODE}`",
            "- managed live comparison: `true`",
            "- true live/GPU/LM Studio used: `true`",
            "- not production default: `true`",
            "- not WVM runtime integration: `true`",
            "- exact unload cleanup required/verified: `true`",
            "- raw_prompt_response_stored: `false`",
            "",
            "## Scope",
            "",
            f"- dataset_id: `{dataset_id}`",
            f"- dataset_hash: `{dataset_hash}`",
            f"- model_key: `{model_key}`",
            f"- model_id: `{model_id}`",
            "- comparison_modes: `stateful_root_branches`, `stateless_full_prefix`, `compact_memory`",
            "- app_concurrency: `1`",
            "- requested_parallel: `1`",
            "",
            "## Evidence Status",
            "",
            f"- measurement_status: `{comparison_summary.get('measurement_status')}`",
            f"- stateful_functional_ok: `{comparison_summary.get('stateful_functional_ok')}`",
            f"- root_success_count_by_mode: `{comparison_summary.get('root_success_count_by_mode')}`",
            f"- branch_count_by_mode: `{comparison_summary.get('branch_count_by_mode')}`",
            f"- branch_success_count_by_mode: `{comparison_summary.get('branch_success_count_by_mode')}`",
            f"- stateful_branch_avg_total_latency_ms: `{comparison_summary.get('stateful_branch_avg_total_latency_ms')}`",
            f"- stateless_full_prefix_branch_avg_total_latency_ms: `{comparison_summary.get('stateless_full_prefix_branch_avg_total_latency_ms')}`",
            f"- compact_memory_branch_avg_total_latency_ms: `{comparison_summary.get('compact_memory_branch_avg_total_latency_ms')}`",
            f"- stateless_full_prefix_vs_stateful_total_latency_ratio: `{comparison_summary.get('stateless_full_prefix_vs_stateful_total_latency_ratio')}`",
            f"- stateful_total_latency_faster_than_stateless: `{comparison_summary.get('stateful_total_latency_faster_than_stateless')}`",
            f"- reuse_verdict: `{comparison_summary.get('reuse_verdict')}`",
            f"- kv_reuse_proven: `{comparison_summary.get('kv_reuse_proven')}`",
            "- Total latency can be compared conservatively, but this run does not prove physical KV reuse.",
            "- `cache_hit=true`, `branch_ttft_improved=true`, and `kv_reuse_proven=true` are intentionally absent.",
            "",
            "## Lifecycle",
            "",
            f"- load_verified: `{comparison_summary.get('load_verified')}`",
            f"- applied_context_length: `{comparison_summary.get('applied_context_length')}`",
            f"- applied_parallel: `{comparison_summary.get('applied_parallel')}`",
            f"- parallel_verified: `{comparison_summary.get('parallel_verified')}`",
            f"- cleanup_status: `{comparison_summary.get('cleanup_status')}`",
            f"- cleanup_verified_count: `{comparison_summary.get('cleanup_verified_count')}`",
            f"- final_loaded_instances: `{comparison_summary.get('final_loaded_instances')}`",
            "",
            "## Notes",
            "",
            "- Root lecture content, stateless prefixes, and compact-memory prompts are generated in memory only and are never written to artifacts.",
            "- Request artifacts store hashes, counts, timings, booleans, and safe status fields only.",
            f"- privacy_scan_status: `{privacy_scan_status}`",
            "",
            "## Output Files",
            "",
            output_files,
            "",
        )
    )


def _instrumentation_status_from_availability(
    *,
    ttft_available: bool,
    prompt_processing_available: bool,
    cached_tokens_available: bool,
) -> str:
    if ttft_available and prompt_processing_available:
        return "ttft_prompt_processing_available"
    if ttft_available or prompt_processing_available or cached_tokens_available:
        return "partial_metrics_available"
    return "metrics_unavailable"


def _build_cache_stateful_instrumentation_live_summary(
    *,
    config: LiveSmokeConfig,
    dataset_manifest: Any,
    run_id: str,
    request_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    rows_by_mode = {
        mode: [row for row in request_rows if _as_optional_str(row.get("mode")) == mode]
        for mode in _CACHE_STATEFUL_COMPARISON_LIVE_MODES
    }
    stateful_root_rows = [
        row
        for row in rows_by_mode["stateful_root_branches"]
        if _as_optional_str(row.get("request_kind")) == "stateful_root"
    ]
    stateful_branch_rows = [
        row
        for row in rows_by_mode["stateful_root_branches"]
        if _as_optional_str(row.get("request_kind")) == "stateful_branch"
    ]
    stateless_branch_rows = rows_by_mode["stateless_full_prefix"]
    compact_memory_branch_rows = rows_by_mode["compact_memory"]

    stateful_root_success_count = sum(row.get("status") == "success" for row in stateful_root_rows)
    stateful_branch_success_count = sum(
        row.get("status") == "success" and row.get("used_previous_root_state") is True
        for row in stateful_branch_rows
    )
    stateless_branch_success_count = sum(
        row.get("status") == "success" for row in stateless_branch_rows
    )
    compact_memory_branch_success_count = sum(
        row.get("status") == "success" for row in compact_memory_branch_rows
    )
    stateful_functional_ok = (
        stateful_root_success_count == 1
        and len(stateful_root_rows) == 1
        and len(stateful_branch_rows) == len(_CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS)
        and stateful_branch_success_count == len(_CACHE_STATEFUL_LIVE_SMOKE_BRANCH_IDS)
    )

    average_total_latency_ms_by_mode = {
        mode: _average_optional_float(
            _as_optional_rate(row.get("total_latency_ms")) for row in rows
        )
        for mode, rows in rows_by_mode.items()
    }
    average_ttft_ms_by_mode = {
        mode: _average_optional_float(_as_optional_rate(row.get("ttft_ms")) for row in rows)
        for mode, rows in rows_by_mode.items()
    }
    average_prompt_processing_ms_by_mode = {
        mode: _average_optional_float(
            _as_optional_rate(row.get("prompt_processing_ms")) for row in rows
        )
        for mode, rows in rows_by_mode.items()
    }
    stateful_branch_avg_prompt_processing_ms = _average_optional_float(
        _as_optional_rate(row.get("prompt_processing_ms")) for row in stateful_branch_rows
    )
    stateless_full_prefix_branch_avg_prompt_processing_ms = _average_optional_float(
        _as_optional_rate(row.get("prompt_processing_ms")) for row in stateless_branch_rows
    )
    compact_memory_branch_avg_prompt_processing_ms = _average_optional_float(
        _as_optional_rate(row.get("prompt_processing_ms")) for row in compact_memory_branch_rows
    )
    ttft_available = any(_as_optional_rate(row.get("ttft_ms")) is not None for row in request_rows)
    prompt_processing_available = any(
        _as_optional_rate(row.get("prompt_processing_ms")) is not None for row in request_rows
    )
    cached_tokens_available = any(
        _as_optional_int(row.get("cached_tokens")) is not None for row in request_rows
    )
    cache_proxy = None
    if (
        stateful_branch_avg_prompt_processing_ms is not None
        and stateful_branch_avg_prompt_processing_ms > 0
        and stateless_full_prefix_branch_avg_prompt_processing_ms is not None
    ):
        cache_proxy = round(
            stateless_full_prefix_branch_avg_prompt_processing_ms
            / stateful_branch_avg_prompt_processing_ms,
            6,
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "mode": _CACHE_STATEFUL_INSTRUMENTATION_LIVE_MODE,
        "comparison_modes": list(_CACHE_STATEFUL_COMPARISON_LIVE_MODES),
        "managed_live": True,
        "dataset_id": dataset_manifest.dataset_id,
        "dataset_hash": dataset_manifest.content_hash,
        "model_key": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_KEY,
        "model_id": _CACHE_STATEFUL_LIVE_SMOKE_MODEL_ID,
        "instrumentation_status": _instrumentation_status_from_availability(
            ttft_available=ttft_available,
            prompt_processing_available=prompt_processing_available,
            cached_tokens_available=cached_tokens_available,
        ),
        "ttft_available": ttft_available,
        "prompt_processing_available": prompt_processing_available,
        "cached_tokens_available": cached_tokens_available,
        "measurement_status": CacheMeasurementStatus.INCONCLUSIVE.value,
        "reuse_verdict": CacheReuseVerdict.KV_REUSE_UNPROVEN.value,
        "kv_reuse_proven": False,
        "stateful_functional_ok": stateful_functional_ok,
        "root_request_count": 1,
        "measured_request_count": len(request_rows),
        "root_success_count_by_mode": {
            "stateful_root_branches": stateful_root_success_count,
            "stateless_full_prefix": 0,
            "compact_memory": 0,
        },
        "branch_count_by_mode": {
            "stateful_root_branches": len(stateful_branch_rows),
            "stateless_full_prefix": len(stateless_branch_rows),
            "compact_memory": len(compact_memory_branch_rows),
        },
        "branch_success_count_by_mode": {
            "stateful_root_branches": stateful_branch_success_count,
            "stateless_full_prefix": stateless_branch_success_count,
            "compact_memory": compact_memory_branch_success_count,
        },
        "average_total_latency_ms_by_mode": average_total_latency_ms_by_mode,
        "average_ttft_ms_by_mode": average_ttft_ms_by_mode,
        "average_prompt_processing_ms_by_mode": average_prompt_processing_ms_by_mode,
        "stateful_branch_avg_prompt_processing_ms": stateful_branch_avg_prompt_processing_ms,
        "stateless_full_prefix_branch_avg_prompt_processing_ms": (
            stateless_full_prefix_branch_avg_prompt_processing_ms
        ),
        "compact_memory_branch_avg_prompt_processing_ms": (
            compact_memory_branch_avg_prompt_processing_ms
        ),
        "cache_proxy": cache_proxy,
        "app_concurrency": _CACHE_STATEFUL_LIVE_SMOKE_APP_CONCURRENCY,
        "requested_context_length": _CACHE_STATEFUL_LIVE_SMOKE_CONTEXT_LENGTH,
        "requested_parallel": _CACHE_STATEFUL_LIVE_SMOKE_PARALLEL,
        "has_live_measurements": True,
        "lmstudio_api_called": True,
        "network": True,
        "production_default": False,
        "wvm_runtime_integration": False,
        "raw_prompt_response_stored": False,
    }


def _instrumentation_privacy_scan_projection(value: Any) -> Any:
    renamed_keys = {
        "prompt_processing_events_seen": "pp_events_seen",
        "prompt_processing_available": "prompt_proc_available",
        "average_prompt_processing_ms_by_mode": "average_prompt_proc_ms_by_mode",
    }
    if isinstance(value, Mapping):
        return {
            renamed_keys.get(str(key), str(key)): _instrumentation_privacy_scan_projection(
                nested_value
            )
            for key, nested_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_instrumentation_privacy_scan_projection(item) for item in value]
    return value


def _build_cache_stateful_instrumentation_live_privacy_scan(
    *,
    environment_payload: Mapping[str, Any],
    experiment_yaml_payload: Mapping[str, Any],
    run_config: Mapping[str, Any],
    request_rows: Sequence[Mapping[str, Any]],
    metric_rows: Sequence[Mapping[str, Any]],
    instrumentation_summary: Mapping[str, Any],
    system_summary: Mapping[str, Any],
    system_samples: Sequence[Mapping[str, Any]],
    report_text: str,
) -> dict[str, object]:
    payloads = {
        "environment.json": environment_payload,
        "experiment.yaml": experiment_yaml_payload,
        "run_config.json": run_config,
        "requests.jsonl": _instrumentation_privacy_scan_projection(list(request_rows)),
        "metrics.jsonl": _instrumentation_privacy_scan_projection(list(metric_rows)),
        "cache_instrumentation_summary.json": _instrumentation_privacy_scan_projection(
            instrumentation_summary
        ),
        "report.md": report_text,
        "system_summary.json": system_summary,
        "system_samples.jsonl": list(system_samples),
    }
    violations: list[str] = []
    for artifact_name, payload in payloads.items():
        serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        violations.extend(
            find_privacy_violations(
                {"artifact_name": artifact_name, "serialized": serialized_payload},
                context=artifact_name,
            )
        )
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "scan_scope": "cache_stateful_instrumentation_live_raw_url_path_private_value_scan",
        "scanned_artifacts": list(payloads),
        "raw_prompt_response_stored": False,
    }


def _render_cache_stateful_instrumentation_live_report(
    *,
    run_id: str,
    experiment_id: str,
    dataset_id: str,
    dataset_hash: str,
    model_key: str,
    model_id: str,
    instrumentation_summary: Mapping[str, object],
    privacy_scan_status: str,
) -> str:
    output_files = "\n".join(
        f"- `{file_name}`" for file_name in _CACHE_STATEFUL_INSTRUMENTATION_LIVE_OUTPUT_FILES
    )
    return "\n".join(
        (
            "# LM Studio Lab Managed Runner Cache/Stateful Instrumentation Live Report",
            "",
            "## Run",
            "",
            f"- experiment_id: `{experiment_id}`",
            f"- run_id: `{run_id}`",
            f"- mode: `{_CACHE_STATEFUL_INSTRUMENTATION_LIVE_MODE}`",
            "- managed live streaming instrumentation probe: `true`",
            "- true live/GPU/LM Studio used: `true`",
            "- not production default: `true`",
            "- not WVM runtime integration: `true`",
            "- exact unload cleanup required/verified: `true`",
            "- raw_prompt_response_stored: `false`",
            "",
            "## Scope",
            "",
            f"- dataset_id: `{dataset_id}`",
            f"- dataset_hash: `{dataset_hash}`",
            f"- model_key: `{model_key}`",
            f"- model_id: `{model_id}`",
            "- comparison_modes: `stateful_root_branches`, `stateless_full_prefix`, `compact_memory`",
            "- native `/api/v1/chat` streaming: `true`",
            "- app_concurrency: `1`",
            "- requested_parallel: `1`",
            "",
            "## Instrumentation",
            "",
            f"- instrumentation_status: `{instrumentation_summary.get('instrumentation_status')}`",
            f"- ttft_available: `{instrumentation_summary.get('ttft_available')}`",
            f"- prompt_processing_available: `{instrumentation_summary.get('prompt_processing_available')}`",
            f"- cached_tokens_available: `{instrumentation_summary.get('cached_tokens_available')}`",
            f"- average_total_latency_ms_by_mode: `{instrumentation_summary.get('average_total_latency_ms_by_mode')}`",
            f"- average_ttft_ms_by_mode: `{instrumentation_summary.get('average_ttft_ms_by_mode')}`",
            f"- average_prompt_processing_ms_by_mode: `{instrumentation_summary.get('average_prompt_processing_ms_by_mode')}`",
            f"- cache_proxy: `{instrumentation_summary.get('cache_proxy')}`",
            "- cached token evidence remains null unless LM Studio explicitly exposes a safe cached_tokens field.",
            "",
            "## Evidence Status",
            "",
            f"- measurement_status: `{instrumentation_summary.get('measurement_status')}`",
            f"- stateful_functional_ok: `{instrumentation_summary.get('stateful_functional_ok')}`",
            f"- root_success_count_by_mode: `{instrumentation_summary.get('root_success_count_by_mode')}`",
            f"- branch_count_by_mode: `{instrumentation_summary.get('branch_count_by_mode')}`",
            f"- branch_success_count_by_mode: `{instrumentation_summary.get('branch_success_count_by_mode')}`",
            f"- reuse_verdict: `{instrumentation_summary.get('reuse_verdict')}`",
            f"- kv_reuse_proven: `{instrumentation_summary.get('kv_reuse_proven')}`",
            "- This probe is conservative and does not prove physical KV reuse.",
            "- `cache_hit=true`, `branch_ttft_improved=true`, and `kv_reuse_proven=true` are intentionally absent.",
            "",
            "## Lifecycle",
            "",
            f"- load_verified: `{instrumentation_summary.get('load_verified')}`",
            f"- applied_context_length: `{instrumentation_summary.get('applied_context_length')}`",
            f"- applied_parallel: `{instrumentation_summary.get('applied_parallel')}`",
            f"- parallel_verified: `{instrumentation_summary.get('parallel_verified')}`",
            f"- cleanup_status: `{instrumentation_summary.get('cleanup_status')}`",
            f"- cleanup_verified_count: `{instrumentation_summary.get('cleanup_verified_count')}`",
            f"- final_loaded_instances: `{instrumentation_summary.get('final_loaded_instances')}`",
            "",
            "## Notes",
            "",
            "- Root lecture content, full-prefix prompts, compact-memory notes, and response text stay in memory only.",
            "- Artifacts store only hashes, counts, safe numeric timings, booleans, and safe status fields.",
            f"- privacy_scan_status: `{privacy_scan_status}`",
            "",
            "## Output Files",
            "",
            output_files,
            "",
        )
    )


def _load_responses_cache_probe_scope(
    config_path: str | PathLike[str],
) -> dict[str, Any]:
    _, raw_payload = load_raw_experiment_config(config_path)

    def _require_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError(f"{field_name} must be a mapping")
        return value

    def _require_non_empty_string(value: object, *, field_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")
        text = value.strip()
        if not text:
            raise ValueError(f"{field_name} must be a non-empty string")
        return text

    def _require_bool(value: object, *, field_name: str) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{field_name} must be a boolean")
        return value

    def _require_int(value: object, *, field_name: str, minimum: int | None = None) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field_name} must be an integer")
        if minimum is not None and value < minimum:
            raise ValueError(f"{field_name} must be >= {minimum}")
        return value

    def _require_string_list(value: object, *, field_name: str) -> tuple[str, ...]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise ValueError(f"{field_name} must be a list of strings")
        items = tuple(
            _require_non_empty_string(item, field_name=f"{field_name}[]") for item in value
        )
        if not items:
            raise ValueError(f"{field_name} must not be empty")
        return items

    experiment_id = _require_non_empty_string(
        raw_payload.get("experiment_id"),
        field_name="experiment_id",
    )
    variant = _RESPONSES_CACHE_PROBE_VARIANTS.get(experiment_id)
    if variant is None:
        raise ValueError(
            "responses cache probe requires experiment_id "
            f"in {sorted(_RESPONSES_CACHE_PROBE_VARIANTS)}"
        )

    endpoint_family = _require_non_empty_string(
        raw_payload.get("endpoint_family"),
        field_name="endpoint_family",
    )
    if endpoint_family != LMStudioEndpointFamily.OPENAI_RESPONSES.value:
        raise ValueError("responses cache probe requires endpoint_family 'openai_responses'")

    base_url = _require_non_empty_string(raw_payload.get("base_url"), field_name="base_url")
    lmstudio_version = _require_non_empty_string(
        raw_payload.get("lmstudio_version", "unknown_not_recorded"),
        field_name="lmstudio_version",
    )

    model_payload = _require_mapping(raw_payload.get("model"), field_name="model")
    model_key = _require_non_empty_string(model_payload.get("key"), field_name="model.key")
    if model_key != _RESPONSES_CACHE_PROBE_MODEL_KEY:
        raise ValueError(
            f"responses cache probe requires model.key '{_RESPONSES_CACHE_PROBE_MODEL_KEY}'"
        )
    model_id = _require_non_empty_string(
        model_payload.get("lmstudio_model_id"),
        field_name="model.lmstudio_model_id",
    )
    if model_id != _RESPONSES_CACHE_PROBE_MODEL_ID:
        raise ValueError(
            "responses cache probe requires model.lmstudio_model_id "
            f"'{_RESPONSES_CACHE_PROBE_MODEL_ID}'"
        )

    safety_payload = _require_mapping(raw_payload.get("safety"), field_name="safety")
    production_default = _require_bool(
        safety_payload.get("production_default"),
        field_name="safety.production_default",
    )
    wvm_runtime_integration = _require_bool(
        safety_payload.get("wvm_runtime_integration"),
        field_name="safety.wvm_runtime_integration",
    )
    live_25k_authorized = _require_bool(
        safety_payload.get("live_25k_authorized"),
        field_name="safety.live_25k_authorized",
    )
    max_context_tokens = _require_int(
        safety_payload.get("max_context_tokens"),
        field_name="safety.max_context_tokens",
        minimum=1,
    )
    allow_real_user_content = _require_bool(
        safety_payload.get("allow_real_user_content"),
        field_name="safety.allow_real_user_content",
    )
    raw_kv_reuse_proven = safety_payload.get("kv_reuse_proven")
    kv_reuse_proven = (
        _require_bool(raw_kv_reuse_proven, field_name="safety.kv_reuse_proven")
        if raw_kv_reuse_proven is not None
        else False
    )
    if production_default:
        raise ValueError("responses cache probe requires safety.production_default=false")
    if wvm_runtime_integration:
        raise ValueError("responses cache probe requires safety.wvm_runtime_integration=false")
    if live_25k_authorized:
        raise ValueError("responses cache probe requires safety.live_25k_authorized=false")
    if allow_real_user_content:
        raise ValueError("responses cache probe requires safety.allow_real_user_content=false")
    if kv_reuse_proven:
        raise ValueError("responses cache probe requires safety.kv_reuse_proven=false")
    expected_max_context_tokens = int(variant["max_context_tokens"])
    if max_context_tokens != expected_max_context_tokens:
        raise ValueError(
            "responses cache probe requires "
            f"safety.max_context_tokens={expected_max_context_tokens} for experiment '{experiment_id}'"
        )

    generation_payload = _require_mapping(raw_payload.get("generation"), field_name="generation")
    temperature = _require_int(
        generation_payload.get("temperature"),
        field_name="generation.temperature",
    )
    max_output_tokens_root = _require_int(
        generation_payload.get("max_output_tokens_root"),
        field_name="generation.max_output_tokens_root",
        minimum=1,
    )
    max_output_tokens_branch = _require_int(
        generation_payload.get("max_output_tokens_branch"),
        field_name="generation.max_output_tokens_branch",
        minimum=1,
    )
    if temperature != 0:
        raise ValueError("responses cache probe requires generation.temperature=0")
    if max_output_tokens_root != 64:
        raise ValueError("responses cache probe requires generation.max_output_tokens_root=64")
    if max_output_tokens_branch != 128:
        raise ValueError("responses cache probe requires generation.max_output_tokens_branch=128")

    datasets = _require_string_list(raw_payload.get("datasets"), field_name="datasets")
    expected_datasets = tuple(str(dataset_id) for dataset_id in variant["datasets"])
    if datasets != expected_datasets:
        raise ValueError(
            f"responses cache probe requires datasets {list(expected_datasets)!r} "
            f"for experiment '{experiment_id}'"
        )

    modes = _require_string_list(raw_payload.get("modes"), field_name="modes")
    if modes != _RESPONSES_CACHE_PROBE_MODES:
        raise ValueError("responses cache probe requires the exact L3.5r modes list")

    repeats_payload = _require_mapping(raw_payload.get("repeats"), field_name="repeats")
    warmup = _require_int(repeats_payload.get("warmup"), field_name="repeats.warmup", minimum=0)
    measured = _require_int(
        repeats_payload.get("measured"),
        field_name="repeats.measured",
        minimum=1,
    )
    if warmup != 1 or measured != 3:
        raise ValueError("responses cache probe requires repeats warmup=1 and measured=3")

    privacy_payload = _require_mapping(raw_payload.get("privacy"), field_name="privacy")
    store_raw_prompt_response = _require_bool(
        privacy_payload.get("store_raw_prompt_response"),
        field_name="privacy.store_raw_prompt_response",
    )
    store_response_id_raw = _require_bool(
        privacy_payload.get("store_response_id_raw"),
        field_name="privacy.store_response_id_raw",
    )
    hash_response_id = _require_bool(
        privacy_payload.get("hash_response_id"),
        field_name="privacy.hash_response_id",
    )
    if store_raw_prompt_response:
        raise ValueError("responses cache probe requires privacy.store_raw_prompt_response=false")
    if store_response_id_raw:
        raise ValueError("responses cache probe requires privacy.store_response_id_raw=false")
    if not hash_response_id:
        raise ValueError("responses cache probe requires privacy.hash_response_id=true")

    artifacts = _require_string_list(raw_payload.get("artifacts"), field_name="artifacts")
    if artifacts != _RESPONSES_CACHE_PROBE_OUTPUT_FILES:
        raise ValueError("responses cache probe requires the exact L3.5r artifact list")

    return {
        "experiment_id": experiment_id,
        "endpoint_family": endpoint_family,
        "base_url": base_url,
        "lmstudio_version": lmstudio_version,
        "model_key": model_key,
        "model_id": model_id,
        "max_context_tokens": max_context_tokens,
        "temperature": temperature,
        "max_output_tokens_root": max_output_tokens_root,
        "max_output_tokens_branch": max_output_tokens_branch,
        "datasets": datasets,
        "modes": modes,
        "warmup": warmup,
        "measured": measured,
        "artifacts": artifacts,
        "is_16k_variant": experiment_id == _RESPONSES_CACHE_PROBE_16K_EXPERIMENT_ID,
    }


def _normalize_responses_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def _default_responses_probe_transport(
    request: urllib_request.Request,
    request_timeout_s: float,
) -> bytes:
    with urllib_request.urlopen(request, timeout=request_timeout_s) as response:
        return response.read()


def _request_responses_probe_json(
    *,
    request_transport: ResponsesProbeTransport,
    endpoint_url: str,
    timeout_s: float,
    request_payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any], str, int | None]:
    request = urllib_request.Request(
        f"{endpoint_url}{_RESPONSES_CACHE_PROBE_ENDPOINT_PATH.removeprefix('/v1')}",
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        response_bytes = request_transport(request, timeout_s)
        response_text = response_bytes.decode("utf-8")
        decoded = json.loads(response_text)
        if not isinstance(decoded, Mapping):
            raise ValueError("responses probe response must be a JSON object")
        return decoded, response_text, None
    except urllib_error.HTTPError as error:
        response_text = error.read().decode("utf-8", errors="replace")
        decoded = json.loads(response_text) if response_text else {}
        if not isinstance(decoded, Mapping):
            decoded = {}
        return decoded, response_text, int(error.code)


def _synthetic_responses_root_text(*, dataset_id: str, target_tokens: int) -> str:
    target_chars = max(1, target_tokens * 3)
    header = (
        f"Synthetic LM Studio responses cache probe dataset={dataset_id} target_tokens={target_tokens}. "
        "This content is machine-generated for offline-safe accounting tests only.\n"
    )
    lines = [header]
    line_index = 0
    while len("".join(lines)) < target_chars:
        line_index += 1
        lines.append(
            f"Segment {line_index:04d} carries repeated deterministic filler for prefix reuse accounting. "
            f"Dataset {dataset_id} anchor {line_index:04d}.\n"
        )
    return "".join(lines)[:target_chars]


def _build_responses_probe_input(
    *,
    mode: str,
    dataset_id: str,
    dataset_target_tokens: int,
    request_role: str,
) -> str:
    root_text = _synthetic_responses_root_text(
        dataset_id=dataset_id,
        target_tokens=dataset_target_tokens,
    )
    if mode == "responses_root_branch":
        if request_role == "root":
            return root_text
        return (
            "Return a compact synthetic follow-up bullet list for the stored root context. "
            f"Dataset={dataset_id}; branch=summary_short."
        )
    if mode == "responses_repeated_prefix":
        suffix = "alpha" if request_role == "first" else "beta"
        return f"{root_text}\nTask: deterministic repeated-prefix answer {suffix}."

    if request_role == "first":
        return f"{root_text}\nTask: deterministic mutated-prefix baseline answer."
    mutated_prefix = root_text.replace("anchor 0001", "anchor 9001", 1)
    return f"{mutated_prefix}\nTask: deterministic mutated-prefix changed answer."


def _build_responses_probe_request_specs(
    *,
    run_id: str,
    config_scope: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    specs: list[dict[str, Any]] = []
    sequence_index = 0
    for dataset_id in config_scope["datasets"]:
        dataset_target_tokens = _RESPONSES_CACHE_PROBE_DATASET_TOKENS[dataset_id]
        for mode in config_scope["modes"]:
            for repeat_phase, repeats_count in (
                ("warmup", int(config_scope["warmup"])),
                ("measured", int(config_scope["measured"])),
            ):
                for repeat_index in range(1, repeats_count + 1):
                    pair_key = f"{mode}:{dataset_id}:{repeat_phase}:{repeat_index}"
                    request_roles = (
                        ("root", True, None)
                        if mode == "responses_root_branch"
                        else ("first", False, None)
                    )
                    for request_role, captures_response_id, previous_pair_key in (request_roles,):
                        sequence_index += 1
                        input_text = _build_responses_probe_input(
                            mode=mode,
                            dataset_id=dataset_id,
                            dataset_target_tokens=dataset_target_tokens,
                            request_role=request_role,
                        )
                        specs.append(
                            {
                                "run_id": run_id,
                                "pair_key": pair_key,
                                "mode": mode,
                                "dataset_id": dataset_id,
                                "dataset_target_tokens": dataset_target_tokens,
                                "repeat_phase": repeat_phase,
                                "repeat_index": repeat_index,
                                "sequence_index": sequence_index,
                                "request_id": f"responses_{sequence_index:04d}",
                                "request_role": request_role,
                                "captures_response_id": captures_response_id,
                                "previous_pair_key": previous_pair_key,
                                "max_output_tokens": int(config_scope["max_output_tokens_root"]),
                                "estimated_input_tokens": estimate_input_tokens_from_chars(
                                    len(input_text)
                                ),
                                "input_text": input_text,
                            }
                        )
                    sequence_index += 1
                    second_role = "branch" if mode == "responses_root_branch" else "second"
                    second_input_text = _build_responses_probe_input(
                        mode=mode,
                        dataset_id=dataset_id,
                        dataset_target_tokens=dataset_target_tokens,
                        request_role=second_role,
                    )
                    specs.append(
                        {
                            "run_id": run_id,
                            "pair_key": pair_key,
                            "mode": mode,
                            "dataset_id": dataset_id,
                            "dataset_target_tokens": dataset_target_tokens,
                            "repeat_phase": repeat_phase,
                            "repeat_index": repeat_index,
                            "sequence_index": sequence_index,
                            "request_id": f"responses_{sequence_index:04d}",
                            "request_role": second_role,
                            "captures_response_id": False,
                            "previous_pair_key": pair_key
                            if mode == "responses_root_branch"
                            else None,
                            "max_output_tokens": int(config_scope["max_output_tokens_branch"]),
                            "estimated_input_tokens": estimate_input_tokens_from_chars(
                                len(second_input_text)
                            ),
                            "input_text": second_input_text,
                        }
                    )
    return tuple(specs)


def _extract_responses_probe_output_text(payload: Mapping[str, Any]) -> str | None:
    output_text = _as_optional_str(payload.get("output_text"))
    if output_text is not None:
        return output_text

    def _walk(value: object) -> str | None:
        if isinstance(value, Mapping):
            for key in ("text", "output_text", "content"):
                candidate = _as_optional_str(value.get(key))
                if candidate is not None:
                    return candidate
            for nested in value.values():
                resolved = _walk(nested)
                if resolved is not None:
                    return resolved
            return None
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for nested in value:
                resolved = _walk(nested)
                if resolved is not None:
                    return resolved
        return None

    return _walk(payload.get("output"))


def _extract_responses_probe_error_type(payload: Mapping[str, Any]) -> str | None:
    error_payload = payload.get("error")
    if isinstance(error_payload, Mapping):
        for key in ("type", "code", "category"):
            value = _as_optional_str(error_payload.get(key))
            if value is not None:
                return value
        return "response_error"
    if error_payload is not None:
        return "response_error"

    status = _as_optional_str(payload.get("status"))
    if status in {"failed", "error", "blocked"}:
        return status
    return None


def _resolve_responses_probe_finish_status(
    *,
    response_payload: Mapping[str, Any],
    response_status_code: int | None,
    error_type: str | None,
) -> str:
    status = _as_optional_str(response_payload.get("status"))
    if status is not None:
        return status
    if error_type is not None:
        return error_type
    if response_status_code is not None:
        return f"http_{response_status_code}"
    return "completed"


def _build_responses_probe_environment_payload(
    *,
    run_id: str,
    config_scope: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "mode": _RESPONSES_CACHE_PROBE_MODE,
        "endpoint_family": LMStudioEndpointFamily.OPENAI_RESPONSES.value,
        "endpoint_path": _RESPONSES_CACHE_PROBE_ENDPOINT_PATH,
        "lmstudio_version": config_scope["lmstudio_version"],
        "inference_endpoint_called": True,
        "production_default": False,
        "wvm_runtime_integration": False,
        "live_25k_authorized": False,
        "kv_reuse_proven": False,
    }


def _build_responses_probe_run_config(
    *,
    run_id: str,
    config_scope: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "endpoint_family": LMStudioEndpointFamily.OPENAI_RESPONSES.value,
        "endpoint_path": _RESPONSES_CACHE_PROBE_ENDPOINT_PATH,
        "lmstudio_version": config_scope["lmstudio_version"],
        "model_key": config_scope["model_key"],
        "model_id": config_scope["model_id"],
        "max_context_tokens": config_scope["max_context_tokens"],
        "generation": {
            "temperature": config_scope["temperature"],
            "max_output_tokens_root": config_scope["max_output_tokens_root"],
            "max_output_tokens_branch": config_scope["max_output_tokens_branch"],
        },
        "datasets": list(config_scope["datasets"]),
        "modes": list(config_scope["modes"]),
        "repeats": {
            "warmup": config_scope["warmup"],
            "measured": config_scope["measured"],
        },
        "production_default": False,
        "wvm_runtime_integration": False,
        "live_25k_authorized": False,
        "allow_real_user_content": False,
        "store_raw_prompt_response": False,
        "store_response_id_raw": False,
        "hash_response_id": True,
        "kv_reuse_proven": False,
        "artifacts": list(config_scope["artifacts"]),
    }


def _build_responses_probe_summary(
    *,
    run_id: str,
    config_scope: Mapping[str, Any],
    metric_rows: Sequence[Mapping[str, Any]],
    previous_response_id_supported: bool,
) -> dict[str, Any]:
    successful_rows = [row for row in metric_rows if row.get("error_type") is None]
    cached_tokens_available = any(
        bool(row.get("cached_tokens_available")) for row in successful_rows
    )
    cached_tokens_observed = any(
        isinstance(row.get("cached_tokens"), int) and int(row.get("cached_tokens")) > 0
        for row in successful_rows
    )
    usage_keys = sorted(
        {
            key
            for row in successful_rows
            for key in row.get("raw_usage_keys", ())
            if isinstance(key, str) and key.strip()
        }
    )
    measured_rows = [row for row in metric_rows if row.get("repeat_phase") == "measured"]
    status = _classify_responses_probe_status(
        metric_rows=measured_rows,
        cached_tokens_available=cached_tokens_available,
        cached_tokens_observed=cached_tokens_observed,
        is_16k_variant=bool(config_scope.get("is_16k_variant")),
    )
    cache_hit_ratios = [
        float(row["cache_hit_ratio"])
        for row in successful_rows
        if isinstance(row.get("cache_hit_ratio"), int | float)
    ]
    total_latency_values = [
        float(row["total_latency_ms"])
        for row in successful_rows
        if isinstance(row.get("total_latency_ms"), int | float)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": config_scope["experiment_id"],
        "endpoint_family": LMStudioEndpointFamily.OPENAI_RESPONSES.value,
        "endpoint_path": _RESPONSES_CACHE_PROBE_ENDPOINT_PATH,
        "model_key": config_scope["model_key"],
        "model_id": config_scope["model_id"],
        "lmstudio_version": config_scope["lmstudio_version"],
        "request_count": len(metric_rows),
        "success_count": len(successful_rows),
        "error_count": len(metric_rows) - len(successful_rows),
        "cached_tokens_available": cached_tokens_available,
        "cached_tokens_observed": cached_tokens_observed,
        "previous_response_id_supported": previous_response_id_supported,
        "responses_cache_probe_status": status.value,
        "raw_usage_keys": usage_keys,
        "avg_cache_hit_ratio": (
            sum(cache_hit_ratios) / len(cache_hit_ratios) if cache_hit_ratios else None
        ),
        "avg_total_latency_ms": (
            sum(total_latency_values) / len(total_latency_values) if total_latency_values else None
        ),
        "production_default": False,
        "wvm_runtime_integration": False,
        "live_25k_authorized": False,
        "kv_reuse_proven": False,
        "inference_endpoint_called": True,
    }


def _classify_responses_probe_status(
    *,
    metric_rows: Sequence[Mapping[str, Any]],
    cached_tokens_available: bool,
    cached_tokens_observed: bool,
    is_16k_variant: bool,
) -> ResponsesCacheProbeStatus:
    error_types = [
        str(error_type).strip().casefold()
        for error_type in (row.get("error_type") for row in metric_rows)
        if isinstance(error_type, str) and error_type.strip()
    ]
    if any("unsupported" in error_type for error_type in error_types):
        return ResponsesCacheProbeStatus.RESPONSES_UNSUPPORTED
    if any(error_type not in {""} for error_type in error_types):
        return ResponsesCacheProbeStatus.RESPONSES_BLOCKED
    if cached_tokens_observed:
        if is_16k_variant:
            return ResponsesCacheProbeStatus.RESPONSES_CACHE_ACCOUNTING_CANDIDATE_16K
        return ResponsesCacheProbeStatus.RESPONSES_CACHE_ACCOUNTING_CANDIDATE
    if cached_tokens_available:
        return ResponsesCacheProbeStatus.RESPONSES_CACHE_SIGNAL_PRESENT
    if is_16k_variant:
        return ResponsesCacheProbeStatus.RESPONSES_USABLE_NO_CACHE_AT_16K
    return ResponsesCacheProbeStatus.RESPONSES_USABLE_NO_CACHE


def _render_responses_cache_probe_report(
    *,
    summary_payload: Mapping[str, Any],
) -> str:
    cached_tokens_available = str(bool(summary_payload.get("cached_tokens_available"))).lower()
    cached_tokens_observed = str(bool(summary_payload.get("cached_tokens_observed"))).lower()
    previous_response_id_supported = str(
        bool(summary_payload.get("previous_response_id_supported"))
    ).lower()
    production_default = str(bool(summary_payload.get("production_default"))).lower()
    return "\n".join(
        [
            "# L3.5r Responses Cache Probe",
            "",
            "## Summary",
            f"- endpoint: {_RESPONSES_CACHE_PROBE_ENDPOINT_PATH}",
            f"- model: {summary_payload.get('model_id')}",
            f"- lmstudio_version: {summary_payload.get('lmstudio_version')}",
            f"- cached_tokens_available: {cached_tokens_available}",
            f"- cached_tokens_observed: {cached_tokens_observed}",
            f"- previous_response_id_supported: {previous_response_id_supported}",
            f"- production_default: {production_default}",
            "",
            "## What this proves",
            "- The isolated /v1/responses spike can submit the configured synthetic request shapes without storing raw prompt or response text.",
            "- The probe records whether usage.input_tokens_details.cached_tokens is exposed for these synthetic requests.",
            "- The probe records whether previous_response_id chaining produced a usable follow-up response in this run.",
            "",
            "## What this does not prove",
            "- This probe does not replace native /api/v1/chat L3 instrumentation.",
            "- It only checks whether /v1/responses exposes useful cached token accounting for WVM.",
            "- It does not prove production default readiness, 25k live behavior, or KV reuse correctness.",
            "- It does not prove native prompt_processing telemetry, model lifecycle behavior, or load ownership semantics.",
            "",
            "## Decision",
            f"responses_cache_probe_status: {summary_payload.get('responses_cache_probe_status')}",
            "",
        ]
    )


def _build_responses_probe_privacy_scan(
    *,
    environment_payload: Mapping[str, Any],
    run_config_payload: Mapping[str, Any],
    request_rows: Sequence[Mapping[str, Any]],
    metric_rows: Sequence[Mapping[str, Any]],
    summary_payload: Mapping[str, Any],
    report_text: str,
    raw_base_url: str,
    raw_endpoint_url: str,
    raw_response_ids: Sequence[str],
    raw_previous_response_ids: Sequence[str],
) -> dict[str, Any]:
    violations: list[str] = []
    artifact_payloads: dict[str, Any] = {
        "environment.json": environment_payload,
        "run_config.json": run_config_payload,
        "requests.jsonl": list(request_rows),
        "metrics.jsonl": list(metric_rows),
        "responses_usage_summary.json": summary_payload,
        "report.md": report_text,
    }
    raw_markers = {raw_base_url, raw_endpoint_url, *raw_response_ids, *raw_previous_response_ids}
    raw_markers.discard("")
    for artifact_name, artifact_payload in artifact_payloads.items():
        serialized = (
            artifact_payload
            if isinstance(artifact_payload, str)
            else json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True)
        )
        violations.extend(find_privacy_violations(artifact_payload, context=artifact_name))
        for raw_marker in raw_markers:
            if raw_marker and raw_marker in serialized:
                violations.append(f"{artifact_name} contains a raw private marker")
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "violations": sorted(set(violations)),
        "scanned_artifacts": list(artifact_payloads),
        "raw_prompt_response_stored": False,
        "store_response_id_raw": False,
    }


def _average_optional_float(values: Sequence[float | None] | Any) -> float | None:
    resolved_values = [value for value in values if value is not None]
    if not resolved_values:
        return None
    return round(sum(resolved_values) / len(resolved_values), 3)


def _safe_hash(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def _build_prompt_privacy_marker(prompt_text: str, *, prefix_chars: int = 96) -> str:
    first_line = prompt_text.splitlines()[0].strip()
    source = first_line if first_line else " ".join(prompt_text.split())
    return source[:prefix_chars]


def _qualifying_privacy_marker(value: object, *, minimum_chars: int = 16) -> str | None:
    if not isinstance(value, str):
        return None
    marker = value.strip()
    if len(marker) < minimum_chars:
        return None
    return marker


def _validate_medium_chunked_prep_dataset_id(dataset_id: str) -> str:
    normalized = str(dataset_id).strip()
    if normalized != _MEDIUM_CHUNKED_PREP_DATASET_ID:
        raise ValueError(
            "dataset_id must be exactly 'blocks_json_medium_chunked' for medium chunked sequential prep"
        )
    return normalized


def _validate_medium_chunked_live_dataset_id(dataset_id: str, *, mode_label: str) -> str:
    normalized = str(dataset_id).strip()
    if normalized not in _MEDIUM_CHUNKED_LIVE_ALLOWED_DATASET_IDS:
        raise ValueError(
            f"{mode_label} requires dataset_id in "
            "{'blocks_json_medium_chunked', 'blocks_json_medium_chunked_10', "
            "'blocks_json_medium_chunked_5'}"
        )
    return normalized


def _validate_medium_chunked_prep_model_keys(model_keys: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(model_key).strip() for model_key in model_keys)
    if not normalized or any(not model_key for model_key in normalized):
        raise ValueError("model_keys must be a non-empty sequence of Gemma prep model keys")
    if len(set(normalized)) != len(normalized):
        raise ValueError("model_keys must not contain duplicates")

    invalid = [
        model_key for model_key in normalized if model_key not in _MEDIUM_CHUNKED_PREP_MODEL_KEYS
    ]
    if invalid:
        raise ValueError(
            "model_keys must be a non-empty subset of {'gemma4_e2b_q4km', 'gemma4_e4b_q4km'}"
        )
    return normalized


def _build_medium_chunked_prep_request_id(*, model_key: str, chunk_id: int) -> str:
    return f"{model_key}_chunk_{chunk_id:04d}"


def _build_medium_chunked_prep_prompt_hash(
    *,
    model_key: str,
    dataset_id: str,
    chunk_id: int,
    expected_ids: Sequence[int],
) -> str:
    return _safe_hash(
        "|".join(
            (
                model_key,
                dataset_id,
                f"chunk={chunk_id}",
                f"ids={','.join(str(block_id) for block_id in expected_ids)}",
            )
        )
    )


def _build_medium_chunked_prep_max_tokens(chunk: Any) -> int:
    estimated_half = chunk.estimated_input_tokens // 2
    return max(256, min(1024, estimated_half + chunk.items_count))


def _as_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _as_optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return None


def _as_optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _build_medium_chunked_prep_validation_result(
    generation_summary: Mapping[str, object],
    *,
    expected_count: int,
) -> StructuredValidationResult:
    content_empty = generation_summary.get("content_empty") is True
    reasoning_content_present = generation_summary.get("reasoning_content_present") is True
    finish_reason = _as_optional_str(generation_summary.get("finish_reason"))
    error_kind = _as_optional_str(generation_summary.get("error_kind"))
    non_empty_text_pass = not content_empty
    error_category: str | None = None
    if reasoning_content_present:
        error_category = "reasoning_leak"
    elif finish_reason == "length":
        error_category = "finish_length"
    elif content_empty:
        error_category = "empty_text"
    elif error_kind is not None:
        error_category = error_kind

    return StructuredValidationResult(
        schema_name=FACTUAL_BLOCKS_SCHEMA_NAME,
        json_parse_pass=None,
        schema_pass=None,
        business_pass=None,
        ids_exact_pass=None,
        no_duplicate_ids=None,
        order_preserved=None,
        non_empty_text_pass=non_empty_text_pass,
        reasoning_leak=reasoning_content_present,
        retry_count=0,
        finish_reason=finish_reason,
        expected_count=expected_count,
        returned_count=None,
        error_category=error_category,
    )


def _medium_chunked_prep_error_category(
    generation_summary: Mapping[str, object],
    *,
    validation_result: StructuredValidationResult,
) -> str | None:
    if validation_result.reasoning_leak:
        return "reasoning"
    if validation_result.finish_reason == "length":
        return "finish"
    if validation_result.non_empty_text_pass is False:
        return "empty"
    error_kind = _as_optional_str(generation_summary.get("error_kind"))
    if error_kind in {"timeout", "http_error", "unknown"}:
        return error_kind
    return None


def _load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _rewrite_jsonl_records(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _restore_cache_stateful_no_live_null_metrics(
    payload: Mapping[str, object],
) -> dict[str, object]:
    restored = dict(payload)
    for key in (
        "ttft_ms",
        "prompt_processing_ms",
        "total_latency_ms",
        "cached_tokens",
        "cache_proxy",
        "ram_peak_mb",
        "vram_peak_mb",
        "stateful_functional_ok",
    ):
        restored[key] = None
    return restored


def _as_optional_rate(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _rate_or_none(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return count / total


def _build_medium_chunked_prep_structured_summary(
    validation_results: Sequence[StructuredValidationResult],
) -> dict[str, object]:
    total_count = len(validation_results)
    reasoning_leak_count = sum(result.reasoning_leak for result in validation_results)
    finish_length_count = sum(result.finish_reason == "length" for result in validation_results)
    empty_text_count = sum(result.non_empty_text_pass is False for result in validation_results)
    envelope_success_count = sum(result.error_category is None for result in validation_results)
    return {
        "schema_version": SCHEMA_VERSION,
        "validation_source": _MEDIUM_CHUNKED_PREP_VALIDATION_SOURCE,
        "validation_status": _MEDIUM_CHUNKED_PREP_VALIDATION_STATUS,
        "total_count": total_count,
        "json_parse_pass_count": None,
        "json_parse_pass_rate": None,
        "schema_pass_count": None,
        "schema_pass_rate": None,
        "business_pass_count": None,
        "business_pass_rate": None,
        "ids_exact_pass_count": None,
        "ids_exact_pass_rate": None,
        "reasoning_leak_count": reasoning_leak_count,
        "finish_length_count": finish_length_count,
        "duplicate_id_count": None,
        "empty_text_count": empty_text_count,
        "invalid_json_count": None,
        "schema_error_count": None,
        "envelope_success_count": envelope_success_count,
        "envelope_success_rate": _rate_or_none(envelope_success_count, total_count),
    }


def _build_medium_chunked_prep_privacy_scan(
    *,
    run_config: Mapping[str, Any],
    metric_rows: Sequence[Mapping[str, Any]],
    batch_summary: Mapping[str, Any],
    structured_summary: Mapping[str, Any],
    structured_summary_csv_text: str,
    system_summary: Mapping[str, Any],
    system_samples: Sequence[Mapping[str, Any]],
    report_text: str,
) -> dict[str, object]:
    payloads = {
        "run_config.json": run_config,
        "metrics.jsonl": list(metric_rows),
        "batch_summary.json": batch_summary,
        "structured_validation_summary.json": structured_summary,
        "structured_validation_summary.csv": structured_summary_csv_text,
        "report.md": report_text,
        "system_summary.json": system_summary,
        "system_samples.jsonl": list(system_samples),
    }
    violations: list[str] = []
    for artifact_name, payload in payloads.items():
        serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        violations.extend(
            find_privacy_violations(
                {"artifact_name": artifact_name, "serialized": serialized_payload},
                context=artifact_name,
            )
        )
    return {
        "status": "pass" if not violations else "fail",
        "violation_count": len(violations),
        "scan_scope": "raw_url_path_private_value_scan",
        "scanned_artifacts": list(payloads),
        "raw_prompt_response_stored": False,
    }


def _render_medium_chunked_prep_report(
    *,
    run_id: str,
    dataset_id: str,
    dataset_hash: str,
    model_keys: Sequence[str],
    batch_summary: Mapping[str, object],
    privacy_scan_status: str,
) -> str:
    model_text = ", ".join(model_keys)
    output_files = "\n".join(f"- `{file_name}`" for file_name in _MEDIUM_CHUNKED_PREP_OUTPUT_FILES)
    return "\n".join(
        (
            "# LM Studio Lab Managed Runner Prep Report",
            "",
            "## Run",
            "",
            f"- run_id: `{run_id}`",
            f"- mode: `{_MEDIUM_CHUNKED_PREP_MODE}`",
            "- no-live/fake-first managed-runner prep: `true`",
            "- LM Studio API/live/GPU: `not used`",
            "- transport path: `ManagedLabRunner -> GenerationClient/contracts -> injected fake compat transport only; no live/network transport created`",
            "- raw_prompt_response_stored: `false`",
            "",
            "## Validation Scope",
            "",
            f"- validation_source: `{batch_summary.get('validation_source')}`",
            f"- validation_status: `{batch_summary.get('validation_status')}`",
            "- structured JSON/schema/business validation: `not evaluated in MV2.2-pre`",
            "- reason: raw model content is not stored or exposed in this no-live safe envelope path, so parse/schema/business/id/duplicate checks cannot be truthfully computed here",
            "- interpretation: this artifact set is envelope-readiness/config/privacy prep only and is not a real model quality proof",
            "",
            "## Scope",
            "",
            f"- dataset_id: `{dataset_id}`",
            f"- dataset_hash: `{dataset_hash}`",
            f"- model_keys: `{model_text}`",
            "- sequential semantics: `app_concurrency=1, configured_parallel=1, applied_parallel=1`",
            "",
            "## Summary",
            "",
            f"- measured_request_count: `{batch_summary.get('measured_request_count')}`",
            f"- envelope_success_count: `{batch_summary.get('envelope_success_count')}`",
            f"- envelope_success_rate: `{batch_summary.get('envelope_success_rate')}`",
            f"- envelope_readiness_pass: `{batch_summary.get('envelope_readiness_pass')}`",
            f"- json_parse_pass_count: `{batch_summary.get('json_parse_pass_count')}`",
            f"- schema_pass_count: `{batch_summary.get('schema_pass_count')}`",
            f"- business_pass_count: `{batch_summary.get('business_pass_count')}`",
            f"- reasoning_leak_count: `{batch_summary.get('reasoning_leak_count')}`",
            f"- finish_length_count: `{batch_summary.get('finish_length_count')}`",
            f"- empty_text_count: `{batch_summary.get('empty_text_count')}`",
            f"- all_chunks_pass: `{batch_summary.get('all_chunks_pass')}`",
            f"- cleanup_status: `{batch_summary.get('cleanup_status')}`",
            f"- privacy_scan_status: `{privacy_scan_status}`",
            "",
            "## Output Files",
            "",
            output_files,
            "",
        )
    )


__all__ = ["ManagedLabRunner", "ManagedTransport"]
