# L3.33b — Cache Evidence Import from Source Application

Status: source-architecture import complete from the active source-application branch.

Timestamp: 2026-07-10T10:27:39+05:00

Source evidence:

```text
active source-application branch: next/modular-backend-lab
source commit: b9ead955
```

This report imports design evidence only. No source-application files were modified.

## Files inspected

```text
src/application/services/postprocessing_service.py
src/application/services/blocks_post_processor.py
src/application/services/postprocessing_coordinator.py
src/services/model_orchestrator.py
src/application/services/token_warning_calculator.py
src/infrastructure/llm/prompt_loader.py
src/infrastructure/llm/payload_builders/lmstudio.py
src/infrastructure/llm/openai_compatible_client.py
```

## What source application already solved

### 1. Cache is an application-level request ordering strategy, not a separate benchmark axis

source application enables cache only when chunk count exceeds a threshold:

```yaml
use_cache: pipeline.caching_enabled and chunks > pipeline.cache_threshold
```

The first chunk is sent synchronously as warmup. Only after that does source application dispatch remaining chunks with controlled concurrency and staggered starts.

Architecture shape:

```text
load/ensure LM Studio model
→ chunk 1 synchronously with full_text/stable prefix
→ optional warmup delay
→ remaining chunks with same stable prefix and dynamic suffix
→ aggregate usage.cached_tokens as telemetry
```

LabKit implication:

```yaml
cache_session_strategy:
  do_not_mix_with: [parallel_matrix, broad_model_matrix, context_sweep]
  required_shape: session_loaded_or_owner_loaded_model
  warmup_shape: first_request_then_measured_followups
  acceptance_signal: quality_pass_plus_cleanup_zero
  cache_signal: cached_tokens_if_runtime_reports_it
```

### 2. LM Studio cache in source application is not implemented through `cache_control` blocks

the source application's LM Studio payload builder explicitly does not use provider-style cache-control blocks:

```text
LM Studio does not use cache_control; LM Studio caches through llama.cpp/runtime KV cache behavior.
```

The `cacheable_user_prefix` is meaningful for providers that support explicit cache blocks, but for LM Studio the effective strategy is stable messages + same loaded runtime + request ordering.

LabKit implication:

```yaml
lmstudio_cache_control_blocks: unsupported_or_ignored
lmstudio_cache_evidence_source: runtime_usage_cached_tokens_if_reported
kv_reuse_proven_by_prompt_shape_alone: false
```

### 3. Prompt split still matters

source application still computes a stable cacheable prefix by splitting the prompt at `{full_text}`:

```text
prefix = everything through {full_text}
suffix = dynamic chunk / clipboard / context / blocks_json
```

For LM Studio this does not become explicit `cache_control`, but it gives a stable request prefix across chunk requests. That is the right shape for llama.cpp-style prefix/KV cache reuse if the runtime supports/report it.

LabKit implication:

```yaml
prompt_prefix_reuse_axis:
  useful: true
  must_use_same_loaded_model: true
  must_keep_prefix_byte_stable: true
  must_measure_cached_tokens_or_latency_only_as_signal: true
```

### 4. Lifecycle ownership is mandatory

source application has a single `ModelOrchestrator` owner for LM Studio lifecycle. It implements context-aware LRU:

```text
same model + same server + current context >= requested + current parallel >= requested → no-op / LRU hit
same model + context too small → reload upward
model/server changed → unload old, load new
cleanup unloads source-application-owned models
```

LabKit implication:

```yaml
cache_session_probe_requires:
  pre_loaded_count: 0_or_known_compatible_owner_loaded
  load_once: true
  dirty_external_loaded_state: reject_or_record_external_preloaded
  cleanup_final_zero: required_for_lab_runs
```

The previous LabKit `cold_per_request + warmup_first` combination was invalid because it destroys the loaded runtime between requests. source application confirms the fix: warmup evidence only makes sense under an owner-loaded/session-loaded model.

### 5. Token budgeting must include output cap and per-slot context

the source application's token warning calculator treats the usable budget as per-slot:

```text
per_slot_context = context_length // max_concurrent
available_input = per_slot_context - max_tokens - safety_buffer
```

LabKit implication:

```yaml
max_tokens_must_be_explicit: true
parallel_reduces_effective_context: true
cache_probe_parallelism: 1
session_probe_context_budget: input + max_tokens + safety_buffer <= context_tier
```

This directly explains why unbounded/implicit generation caps are dangerous for LabKit structured probes: finish-length can consume the context-side generation budget and produce no useful JSON.

### 6. Cached-token telemetry is tracked, but not treated as proof by itself

source application logs and persists:

```text
prompt_tokens
completion_tokens
cached_tokens
total_tokens
```

LabKit should import this as an evidence field, not as automatic acceptance.

```yaml
kv_reuse_proven:
  true_only_if: runtime_reports_cached_tokens_or_equivalent_and_quality_passes
cache_benefit_claimed:
  false_if: timing_only_or_mixed_failures
```

## Answer: what was wrong in LabKit L3.33a before repair

The bad shape was:

```yaml
execution_mode: [cold_per_request, session_loaded]
cache_mode: [none, warmup_first]
```

`warmup_first` under `cold_per_request` is semantically invalid. It cannot preserve a warm runtime or stable KV state across requests.

The corrected LabKit L3.33a shape:

```yaml
execution_mode: session_loaded
cache_mode:
  - none
  - warmup_first
context_tier: 8192
parallel: 1
```

This matches the source application's architecture more closely, but the L3.33a result remains only partial:

```yaml
google/gemma-4-e4b: accepted_narrow_12_of_12
google/gemma-4-12b-qat: blocked_2_finish_length_of_12
kv_reuse_proven: false
cache_benefit_claimed: false
```

## Imported rules for future LabKit cache work

```yaml
l3_33b_imported_rules:
  - cache/session probes must use session_loaded or explicit owner-loaded model lifecycle
  - warmup_first is invalid with cold_per_request
  - do not mix cache probes with parallelism, broad model sweeps, context sweeps, or image probes
  - keep max_tokens explicit and bounded
  - keep stable prefix byte-identical across warmup and measured requests
  - record cached_tokens when runtime reports them
  - timing-only differences are signal, not proof
  - acceptance requires quality pass and cleanup final zero
  - dirty loaded state must be rejected or classified as external_preloaded, not silently reused
```

## LabKit action items

```yaml
recommended_changes:
  - add an explicit max_tokens axis to managed text probes
  - record max_tokens in planner/result artifacts
  - add cache/session docs that cite session_loaded-only semantics
  - keep L3.33 accepted only for E4B narrow scope until 12B finish_length is repaired
```
