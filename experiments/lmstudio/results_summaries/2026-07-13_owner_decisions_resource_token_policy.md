# Owner decisions: resource and token policy

Date: 2026-07-13

Status: recommended owner decisions for O6-O9. Values marked **provisional** are safe startup configuration for offline implementation and later shadow measurement; they are not production admissions. No model load, inference, tokenizer capture, benchmark, cloud request, migration, host change, commit, or push was performed.

Machine-readable companion: `2026-07-13_owner_decisions_resource_token_policy.json`.

## Decision summary

| Decision | Recommendation | Classification |
|---|---|---|
| O6 — output stages, degraded threshold, safety ratio, call ceilings | Approve the bounded task table, `0.85` context safety ratio, `256` token uncalibrated margin, `0.50` degraded-estimate threshold, and cumulative two/three-call ceilings as versioned configurable startup defaults. Escalate output only on independent truncation. | `approve_configurable_default`; all numeric values require shadow calibration before production promotion |
| O7 — memory headroom and estimate policy | Approve independent CUDA VRAM and host-RAM gates, one Apple shared-pool gate, and the provisional reserve formulas below. A static estimate may reject; it may recommend only when an exact profile explicitly permits estimate-only Auto. | `approve_configurable_default`; reserve values require platform/profile calibration |
| O8 — Apple MLX/Metal metrics | Approve three adapter states: `verified`, `degraded_observed_envelope`, and `unavailable`. General Apple Auto is disabled unless the adapter is verified or an exact catalog profile carries a trusted equivalent observed envelope. | `blocked_external_capability` for general Apple Auto |
| O9 — CUDA multi-device/process attribution | Restrict Auto to one exact physical GPU or one exact MIG instance. Do not sum devices. Multi-GPU, sharded, tensor-parallel, layer-split, and ambiguous process-placement profiles are unavailable until exact placement and per-device peak evidence exists. | `approve_now` restriction; multi-device Auto remains `blocked_external_capability` |

The policy is fail-closed: missing exact token evidence, resource evidence, identity, or attribution never becomes an optimistic fit verdict.

## Evidence boundary

### Current static contract

- `AdaptiveOutputBudgetPolicy` derives bounded increasing stages from response-contract shape, but currently permits escalation for `parse_incomplete` without an independent finish/usage truncation signal. Product policy must tighten this behavior.
- `tools/lmstudio_lab/system_metrics.py` samples host RAM and process RSS and parses only the first `nvidia-smi` GPU row. It does not bind GPU memory to an exact LM Studio PID, enumerate every GPU/MIG instance, or prove placement.
- LM Studio's Python documentation describes exact prompt counting by applying the loaded model's prompt template, tokenizing the formatted prompt, and comparing the count with that loaded model's context length.
- LM Studio's load contract accepts `context_length`; model inventory exposes maximum/effective model and loaded-instance facts. The CLI `load --estimate-only` is useful estimate evidence, but it is not an observed loaded peak or admission authority.

### Retained executed evidence

- Four exact loaded-instance tokenizer captures contain 80 frozen request rows; exact formatted-prompt counts range from 925 to 12,797 tokens.
- The retained task-axis fit artifact used fixed reserves of 512 tokens for short work, 2,048 for long work, and a 256-token request-change allowance. All 80 frozen upper bounds fit their configured tiers. This proves the method only for those exact bindings.
- Retained generation evidence includes two extended-context summaries that exhausted 1,024 output tokens and became structurally unusable, and one full-context cleanup that exhausted 4,096 tokens and returned malformed JSON. A larger cap is therefore not a correctness signal.
- Current retained system telemetry is useful experimental evidence but does not establish a production CUDA or Apple memory envelope.

### Runtime-unexecuted recommendations

The host two-phase planner, memory adapters, exact profile envelopes, process attribution, Apple pressure handling, provisional reserves, task stages, and rollback switches below have not been executed end to end.

## Deterministic two-phase algorithm

All arithmetic uses bytes and integer tokens. The application freezes one logical request before candidate selection.

### Phase A — pre-materialization screen

1. Resolve an exact approved task profile and freeze rendered messages, schema, target/reference ownership, request digests, context tiers, output stages, call ceiling, token mode, platform class, and memory policy version.
2. Select the initial output reserve as the smallest task stage not below the contract-derived output estimate. If the estimate exceeds the task hard maximum, split or fail; never widen the policy silently.
3. Compute conservative token demand:

   ```text
   token_required_estimate = E_chat + E_schema + E_task + R0 + M
   token_safe_budget(C) = floor(C * 0.85)
   ```

   With no matching tokenizer calibration, `E_chat` and `E_schema` use at most one token per UTF-8 byte. `E_task` is a versioned non-negative allowance. `M` starts at 256 tokens.
4. Choose the smallest approved context tier for which the estimate fits. Required targets, IDs, schema, and ownership metadata are never truncated. Optional reference context is removed only in task-declared order.
5. Apply platform resource screening using the formulas below. Missing or ambiguous measurements return a typed state; they are never replaced by zero.
6. A static estimate can always reject. It can provisionally pass to materialization only when the exact task profile permits `conservative_estimate_fit`, identity is exact, the adapter is allowed for Auto, and no hard restriction applies. Otherwise return `manual_approved_only` or `unavailable` before load.

### Phase B — post-materialization exact gate

1. Materialize or attach under a lifecycle ownership handle. Read back exact model identity, runtime build, instance ID, effective context, parallelism, placement, and load configuration. A mismatch stops before tokenization or generation.
2. Apply the loaded instance's exact prompt template and tokenizer to the frozen messages. Bind the count to model revision, instance/configuration, effective context, message digest, formatted-prompt digest, token-ID digest, and runtime/tokenizer version.
3. Re-evaluate context fit:

   ```text
   token_required_exact = T_sdk + H_schema + H_task + R0 + M
   token_required_exact <= floor(effective_context * 0.85)
   ```

   Only `T_sdk` is exact until schema/task overhead is observed. Without an exact count, only the bounded degraded policy below may continue.
4. Read a settled post-load resource snapshot. CUDA requires the exact target device/MIG handle and unambiguous LM Studio process/instance attribution. Apple requires a verified shared-pool adapter or an exact trusted catalog envelope. The settled load must remain inside the same reserve policy used in Phase A.
5. Generate only after both token and resource gates pass. Increment the one logical model-call counter before submission.
6. During and after generation, retain immutable attempt telemetry and observed peak/pressure evidence. A hard memory-pressure transition, attribution loss, OOM, stale request, or cancellation makes late output inert.
7. A next output stage is eligible only when independent truncation is observed, the next exact token equation fits, and the cumulative call ceiling remains. Complete malformed JSON, schema/identity/semantic failure, repetition, or reasoning leakage does not get a larger cap.
8. Release only owned resources and require cleanup read-back. Cleanup failure is a typed lifecycle fault and prevents envelope calibration.

## Token and output policy

### Provisional task defaults

| Task profile | Output stages | Hard maximum | Total model-call ceiling | Token mode |
|---|---:|---:|---:|---|
| Short microphone cleanup | 512 → 1,024 | 1,024 | 2 | Conservative estimate allowed only under the degraded rule |
| Microphone command | 512 → 1,024 | 1,024 | 2 | Conservative estimate allowed only under the degraded rule; interactive latency remains unmeasured |
| Long block cleanup | 1,024 → 2,048 → 4,096 | 4,096 | 3 | Exact required; 4,096 is shadow-only until qualified |
| Per-chunk summary | 512 → 1,024 | 1,024 | 2 | Exact required for long or near-budget inputs |
| Direct recording summary | 1,024 → 2,048 | 2,048 | 2 | Exact required |
| Hierarchical summary synthesis | 1,024 → 2,048 → 4,096 | 4,096 | 3 | Exact required; 4,096 is shadow-only until qualified |
| Generic self-contained transform | 512 → 1,024 → 2,048 | 2,048 | 3 | Conservative estimate only for short bounded input |
| Image analysis | 512 → 1,024 | 1,024 | 2 | Provider/runtime-specific planning; image bytes are not text-token estimates |

The library's 8,192 maximum remains a guardrail, not a host task stage.

### Exact-tokenization unavailable

- `exact_required`: return `exact_tokenization_unavailable`; do not generate.
- `conservative_estimate_allowed`: continue only when the conservative total at the task hard maximum is at most 50% of the safe context budget:

  ```text
  E_chat + E_schema + E_task + hard_output_max + M
      <= floor(0.50 * floor(context * 0.85))
  ```

  The attempt is labeled `estimate_only`; usage cannot retroactively make preflight exact.
- Otherwise use the task's non-model fallback or return unavailable.

The `0.85`, `256`, and `0.50` values are provisional configuration, not universal constants.

### Independent truncation

Truncation is observed only when `finish_reason == "length"`, or when finish reason is absent and completion usage is at least the configured cap. An explicit normal stop wins over cap equality. Missing both finish reason and completion usage is `truncation_signal_unavailable`, not permission to escalate.

## Resource policy

All reserves use the stricter absolute/proportional amount:

```text
reserve(total) = max(absolute_reserve, floor(total * proportional_reserve))
available_after_reserve = max(0, current_available - reserve(total))
```

These startup values are deliberately conservative and remain profile/platform configuration:

| Resource | Provisional absolute reserve | Provisional proportional reserve | Rule |
|---|---:|---:|---|
| CUDA target VRAM | 1 GiB | 10% of target-device total | Estimated/observed accelerator requirement must fit current free VRAM after reserve |
| Discrete-host RAM | 2 GiB | 15% of physical RAM | Host/offload/workspace requirement must fit OS available RAM after reserve independently of VRAM |
| Apple unified memory | 4 GiB | 20% of physical memory | One shared CPU/GPU pool; require normal pressure and shared demand below available memory after reserve |
| Apple Metal working set | 1 GiB | 15% of `recommendedMaxWorkingSetSize` | When the verified adapter exposes this bound, predicted/observed Metal demand must remain below it after reserve |

A snapshot is not a guarantee. A catalog envelope must retain exact identity, context, runtime parallelism, application concurrency, KV/cache policy, placement, runtime build, adapter version, sample interval, baseline, settled load, peak, and unload read-back.

### CUDA states and restrictions

- `cuda_single_device_verified`: exact physical device UUID or exact MIG instance handle, per-device memory information, exact LM Studio PID/instance binding, and no placement ambiguity. Eligible under the profile's estimate/observed policy.
- `cuda_single_device_degraded`: per-device total/free memory exists but process attribution or settled peak is absent. Static estimate may reject; Auto is unavailable by default. An approved manual guarded measurement may be offered separately.
- `cuda_multi_device_unverified`: more than one device/instance participates or placement is ambiguous. Auto unavailable; memory must not be summed.
- `cuda_metrics_unavailable`: no trustworthy per-device snapshot. Auto unavailable.

NVML is the preferred adapter because it exposes per-device total/used/free/reserved memory and compute-process memory. Its process list is dynamic; the adapter must retry boundedly when sizing the list and must use the specific MIG device handle for per-instance information. A global device total and a process memory value are complementary, not interchangeable.

### Apple states

- `apple_verified`: physical/available memory, system pressure, exact LM Studio process footprint, and runtime active/cache/peak counters are bound to one load/call interval; peak reset semantics and overlapping counters are tested. Exact catalog profiles may be Auto-eligible.
- `apple_degraded_observed_envelope`: runtime counters are not directly available, but a trusted adapter previously captured an exact profile envelope with pressure, process footprint, identity, shape, and cleanup read-back. Auto may use only that exact pre-approved envelope; no extrapolation upward.
- `apple_unavailable`: any required counter is missing, attribution is ambiguous, pressure is warning/critical, or envelope shape differs. General Auto unavailable; approved manual selection may remain visible with `measurement_required`, but cannot bypass hard pressure or fit failure.

Apple Silicon is one unified pool; RAM and a fictional VRAM amount are never added. MLX documents active, peak, cache, peak reset, limits, and cache clearing, but those APIs describe the MLX runtime in the instrumented process. They do not by themselves prove attribution to an external LM Studio process. Metal's `recommendedMaxWorkingSetSize` is an approximate performance threshold, not guaranteed free memory, while memory-pressure events are system-level safety signals.

## Auto behavior without exact metrics

| Missing evidence | Auto behavior |
|---|---|
| Exact loaded-instance token count | Allowed only for a task explicitly marked `conservative_estimate_allowed` and below the 50% degraded threshold; otherwise unavailable |
| Prompt/completion usage | Keep the predeclared cap and call ceiling, but disable usage reconciliation and usage-based truncation detection |
| CUDA process attribution or exact target device | Static estimate may reject; Auto cannot recommend |
| Matching CUDA peak envelope | A single-device profile may use `conservative_estimate_fit` only when the catalog explicitly authorizes it; otherwise measurement required |
| Verified Apple runtime/process adapter | Use only an exact trusted catalog envelope; otherwise Apple Auto unavailable |
| Apple pressure state | Apple Auto unavailable |
| Multi-GPU/MIG placement | Auto unavailable unless one exact physical device or one exact MIG instance is the complete approved placement |

Manual selection does not bypass exact identity, hard memory failure, pressure, incompatible loaded state, or call/token safety.

## Typed reason codes

### Planning and token

`unresolved_request`, `estimate_unavailable`, `estimate_no_fit`, `exact_tokenization_unavailable`, `exact_no_fit`, `schema_overhead_unobserved`, `usage_unavailable`, `usage_reconciliation_fault`, `truncation_signal_unavailable`, `truncation_observed`, `truncation_next_stage_no_fit`, `truncation_ceiling_reached`, `complete_structural_failure`, `semantic_failure`, `call_ceiling_reached`, `cancelled_or_stale`.

### Resource and lifecycle

`resource_adapter_unsupported`, `resource_metrics_unavailable`, `resource_snapshot_stale`, `headroom_insufficient`, `static_estimate_exceeds_budget`, `observed_peak_exceeds_budget`, `load_identity_mismatch`, `load_shape_mismatch`, `settled_load_not_observed`, `process_attribution_ambiguous`, `cleanup_readback_failed`, `external_instance_not_owned`.

### CUDA

`cuda_device_unresolved`, `cuda_process_not_bound`, `cuda_competing_process_ambiguous`, `cuda_multi_device_unverified`, `cuda_mig_handle_required`, `cuda_placement_unverified`, `cuda_vram_insufficient`, `host_ram_insufficient`.

### Apple

`apple_unified_adapter_unverified`, `apple_pressure_unavailable`, `apple_pressure_warning`, `apple_pressure_critical`, `apple_process_footprint_unavailable`, `apple_runtime_counters_unavailable`, `apple_counter_overlap_unverified`, `apple_envelope_missing`, `apple_envelope_shape_mismatch`, `apple_unified_memory_insufficient`, `apple_metal_working_set_insufficient`.

Every unavailable result retains all applicable reason codes plus one primary user-facing reason.

## Rollback seam

Store this policy in a versioned host-owned profile, separate from code and model catalog admission. Minimum kill switches:

- `auto_selection_enabled`;
- `estimate_only_token_mode_enabled`;
- `conservative_resource_estimate_auto_enabled` per platform/profile;
- `apple_auto_enabled`;
- `cuda_multi_device_auto_enabled` (startup default `false`);
- task-specific output stage/call policy version.

Rollback changes only future request generations, marks in-flight attempts stale at the generation fence, does not unload external instances, and returns to approved manual selection or the existing non-model/original-source path. A policy version change never silently reclassifies retained evidence.

## Minimum acceptance tests

### Offline deterministic tests

1. Freeze-before-estimate: any message/schema/identity change invalidates token evidence.
2. Tier choice: select the smallest fitting approved tier and preserve required targets/IDs.
3. Exact gate: estimate-pass/exact-fail replans without a generation call.
4. Degraded threshold boundaries at one token below/equal/above 50%.
5. Explicit normal stop at cap does not escalate; absent finish reason at cap does.
6. Parse/schema/identity/semantic/repetition failures never increase output budget.
7. Transport, structural, and truncation attempts share one counter; no task exceeds its ceiling.
8. Reserve arithmetic covers equality, underflow, unknown counters, and stale snapshots.
9. CUDA VRAM and host RAM are independent gates; two GPUs are never summed.
10. MIG requires a specific instance handle and exact process/placement binding.
11. Apple counters are not summed when overlapping; warning/critical pressure blocks Auto.
12. Apple missing adapter permits only an exact trusted envelope, never upward extrapolation.
13. Cancellation/stale generation prevents persistence; cleanup releases only owned instances.
14. Rollback disables future Auto and invalidates in-flight publication without mutating source data.

### Later separately authorized shadow calibration

No live work is authorized here. A later plan should capture privacy-safe rows for exact request/profile/platform buckets:

- token estimate, exact `T_sdk`, server usage delta, context tier, schema family, runtime/template version;
- resource baseline, settled load, peak, pressure transitions, process/device attribution, and unload read-back;
- task stage, finish/usage evidence, structural/semantic outcome, latency, cancellation, and call count.

Provisional promotion criteria, themselves configurable, should require at least 30 matching token observations and at least 10 clean load/settle/peak/unload cycles per exact resource envelope, zero OOM/critical-pressure/cleanup faults, no negative token reconciliation, and an observed upper bound that remains below the configured reserve. These sample counts are engineering startup gates, not statistical guarantees. Any runtime, model revision, quantization, context, parallelism, concurrency, placement, KV/cache, adapter, schema family, or policy-version change starts a new bucket.

## Official sources

- LM Studio, loaded-model context and exact prompt-token example: https://lmstudio.ai/docs/python/model-info/get-context-length
- LM Studio, tokenization: https://lmstudio.ai/docs/typescript/tokenization
- LM Studio, model load configuration and context-length semantics: https://lmstudio.ai/docs/typescript/api-reference/llm-load-model-config
- LM Studio, native load endpoint: https://lmstudio.ai/docs/developer/rest/load
- LM Studio, native model inventory: https://lmstudio.ai/docs/developer/rest/list
- LM Studio API changelog, `lms load --estimate-only`: https://lmstudio.ai/docs/developer/api-changelog
- NVIDIA NVML device queries (`nvmlDeviceGetMemoryInfo[_v2]`, `nvmlDeviceGetComputeRunningProcesses_v3`, MIG notes): https://docs.nvidia.com/deploy/nvml-api/group__nvmlDeviceQueries.html
- MLX unified-memory model: https://ml-explore.github.io/mlx/build/html/usage/unified_memory.html
- MLX memory-management counters and controls: https://ml-explore.github.io/mlx/build/html/python/memory_management.html
- Apple Metal `recommendedMaxWorkingSetSize`: https://developer.apple.com/documentation/metal/mtldevice/recommendedmaxworkingsetsize
- Apple system memory-pressure source: https://developer.apple.com/documentation/dispatch/dispatchsourcememorypressure
- Apple process physical-footprint field: https://developer.apple.com/documentation/kernel/task_vm_info_data_t/1553210-phys_footprint

## Non-claims

- No production model, task profile, context tier, memory envelope, latency target, or semantic threshold is approved.
- The provisional reserve percentages/GiB values, sample counts, stage values, 50% threshold, 0.85 ratio, and 256-token margin are not universal hardware facts.
- `lms load --estimate-only`, free memory, file size, and static KV formulas are not observed peak memory.
- MLX process counters are not proven available or attributable through an external LM Studio process.
- `recommendedMaxWorkingSetSize` is not equivalent to OS available memory or a guaranteed allocation.
- Current LabKit first-row `nvidia-smi` telemetry is not sufficient for multi-device or process-safe Auto.
- No live execution or implementation is authorized by this decision report.
