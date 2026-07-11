# L3.33b — Cache Evidence Import from Source Application

Status: reviewed static and deterministic evidence import; `research_only`.

Timestamp: 2026-07-11T13:05:58+05:00

This report imports a sanitized cache/session architecture contract from a pinned
source-application revision. It changes no Gemma admission verdict and makes no
runtime claim about physical KV reuse or cache benefit. No live inference, model
operation, application run, network call, or source-application mutation was
performed for this publication slice.

## Pinned source and evidence level

```yaml
source_label: source_application
branch: next/modular-backend-lab
commit: b9ead955af6c1a9e27c74c18a8ecac7fc58ae214
evidence_level:
  - static_source_review
  - deterministic_unit_and_owner_path_tests
runtime_cache_or_kv_proof: false
```

The independent review verified that the inspected files were byte-identical to
the pinned commit.

## Exact source references

| contract | source path and symbols | code-proven fact |
|---|---|---|
| Runtime ownership and compatible reuse | `src/services/model_orchestrator.py:308-461` — `ModelOrchestrator.ensure_model`, `_ensure_model_locked` | Lifecycle decisions are serialized. Reuse requires the same model and server plus sufficient context and parallelism; otherwise the owner unloads and loads. |
| Ownership-safe load, unload, and cleanup | `src/services/model_orchestrator.py:471-551,690-768,770-982` — `_do_load`, `_do_unload`, `cleanup` | Successful loads record model, instance, context, server, parallelism, purpose, and ownership. External or preloaded instances remain non-owned and are not unloaded as source-application-owned state. |
| Idle cleanup | `src/services/model_runtime_lifecycle_coordinator.py:202-260` — `ModelRuntimeLifecycleCoordinator.unload_all_if_idle`; `src/services/model_lifecycle_targets.py:171-243` — `LMStudioManagedTarget.request_unload` | Active work blocks idle unload. An unconfirmed unload is reported as failure rather than cleanup success. |
| LM Studio configuration | `src/domain/llm_providers.py:211-271` — `LMStudioConfig` | Application-level explicit caching is disabled for LM Studio: `caching_enabled=false`, threshold `0`, warmup delay `0.0`. Defaults include context `8192`, max output `2048`, and concurrency `1`. |
| First-request sequencing | `src/application/services/postprocessing_service.py:514-589` — `PostProcessingService.improve_text` | Request 1 is awaited before remaining requests. The named cache delay runs only when `use_cache=true`; that explicit-cache branch is false for LM Studio. |
| Final message and payload shape | `src/application/services/postprocessing_service.py:914-980` — `_process_chunk`; `src/infrastructure/llm/payload_builders/lmstudio.py:30-79` — `LMStudioPayloadBuilder.build_messages`, `build_payload` | LM Studio receives ordinary ordered system/user messages, an explicit `max_tokens` value when supplied, and `cache_prompt=true`. The builder ignores `cacheable_user_prefix` and provider-style `cache_control`. |
| Token telemetry | `src/infrastructure/llm/openai_compatible_client.py:929-975,1128-1176` — `OpenAICompatibleClient._do_complete` | Provider-reported prompt, completion, total, and nullable cached-token counts are parsed, aggregated, and logged as counts. Persistence was not established by this review. |
| Per-slot budget | `src/application/services/token_warning_calculator.py:70-155` — token budget calculation | The static input budget uses `context_length // max_concurrent`, then reserves output tokens and a safety buffer. |

## Deterministic test evidence

The pinned source review executed these tests without starting the application or
making a model/API call:

```text
uv run pytest -q tests/test_model_orchestrator.py tests/test_model_orchestrator_lock.py tests/test_model_lifecycle_targets.py tests/test_postprocessing_service.py
134 passed

uv run pytest -q tests/test_e2e_cloud_providers.py::TestT8PayloadBuilders::test_lmstudio_payload_has_cache_prompt tests/test_e2e_cloud_providers.py::TestT8PayloadBuilders::test_lmstudio_messages_no_cache_control
2 passed
```

Named owner-path checks include:

- `TestConcurrentEnsureModel.test_concurrent_ensure_model_serialized`;
- `TestNParallelPassthrough.test_ensure_model_passes_n_parallel`;
- `test_lmstudio_external_preloaded_snapshot_is_loaded_but_not_unloadable`;
- `TestT8PayloadBuilders.test_lmstudio_payload_has_cache_prompt`;
- `TestT8PayloadBuilders.test_lmstudio_messages_no_cache_control`.

The source checkout ended clean at the pinned full commit.

## Corrected interpretation

The earlier import overstated three properties. The corrected contract is:

1. `cache_prompt=true` is emitted independently by the LM Studio payload builder;
   it is not enabled by the application-level chunk-threshold cache branch.
2. The source application's `split_user_for_cache` and
   `cacheable_user_prefix` path does not establish an LM Studio byte-stable
   prefix. LabKit must derive prefix fingerprints and lengths from its own final
   serialized request seam, without publishing prompt content.
3. Awaiting request 1 establishes ordering only. It is not a cache-materialization
   barrier and does not prove that later requests reused physical KV state.

`cold_per_request` remains a valid LabKit comparator, but it is not parity with
the source application's compatible loaded-session lifecycle and intentionally
destroys cross-request session/KV continuity.

## Minimal LabKit import contract

```yaml
source_ref:
  label: source_application
  branch: next/modular-backend-lab
  commit: b9ead955af6c1a9e27c74c18a8ecac7fc58ae214
  evidence: static_plus_136_deterministic_tests
lifecycle:
  record: [selected_model, live_instance_id, purpose, server_identity, context_length, parallelism, ownership]
  ownership_values: [lab_owned, external_preloaded]
  compatible_loaded_runtime_reuse: required_for_source_parity
  unload_external_preloaded: forbidden
request_shape:
  execution_mode: session_loaded
  request_1: serialized_ordering_marker
  messages: ordered_system_then_user
  max_output_tokens: explicit_and_bounded
  cache_prompt_requested: record_boolean
  stable_prefix_evidence: hash_and_lengths_from_final_labkit_request_seam
telemetry:
  record: [request_index, is_warmup_request, input_tokens, output_tokens, total_tokens, cached_tokens_nullable, latency_ms, quality_or_schema_result]
  cache_materialized: false_or_unknown_without_runtime_signal
cleanup:
  record: [unload_requested, ownership_scope, unload_confirmed, read_back_confirmed, final_loaded_state]
  external_preloaded_is_failure: false
```

For LabKit, `warmup_first` means only that the first request is serialized before
the measured remainder. Any cache-materialized verdict needs a separate runtime
signal. Missing or zero `cached_tokens` is telemetry, not proof that caching is
disabled; latency differences are research signals, not physical-KV proof.

## Admission reconciliation

The imported architecture evidence is `research_only`. It does not alter the
L3.33a model outcomes:

```yaml
google/gemma-4-e4b: accepted_narrow_12_of_12
google/gemma-4-12b-qat: blocked_2_finish_length_of_12
kv_reuse_proven: false
cache_benefit_claimed: false
```

The prepared `matrix.l3_33b_gemma_prompt_prefix_reuse.yaml` remains a LabKit
`cold_per_request` comparator and is not relabeled as source-application parity.
L3.31b context forensics and the superseding L3.34.1/L3.39 vision findings are
outside this cache-only import and remain unchanged.

## Non-claims

This report does not claim:

- that LM Studio physically reused KV state or produced a cache benefit;
- that first-request serialization materialized a cache;
- that prefix reuse was proven from the source application's LM Studio path;
- that cache state persists across unload/reload;
- parity across llama.cpp, MLX, LM Studio versions, or API routes;
- that the source application implements a cold-per-request mode;
- that cached-token counts are persisted by the inspected path;
- that cleanup requires unloading external/preloaded instances or reaching a
  global loaded count of zero;
- any model admission change from architecture evidence alone.
