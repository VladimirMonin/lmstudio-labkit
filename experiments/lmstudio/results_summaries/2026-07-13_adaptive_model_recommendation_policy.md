# Adaptive model recommendation policy

Date: 2026-07-13

Status: read-only architecture recommendation. No model was loaded, downloaded, hashed, tokenized, or called. No production model is approved by this report.

Machine-readable companion: `2026-07-13_adaptive_model_recommendation_policy.json`.

## Decision

The product must recommend only from the intersection of:

1. a host-owned, versioned task-profile catalog whose entries are explicitly approved;
2. models discovered from the current LM Studio runtime and local inventory;
3. an exact model identity binding, including artifact digest and quantization;
4. a platform-specific memory-fit decision for the requested context and concurrency.

A model name, parameter count, file size, or currently free memory is never enough to select a model. If exact identity or usable memory evidence is missing, Auto mode returns a typed unavailable or needs-measurement state instead of guessing.

The approved unit is a **task profile**, not a model family. One artifact may be approved for structured cleanup at 8K/P2 and remain unapproved for vision, 32K, or P4. Lab candidate status and benchmark ranking are evidence inputs only; they must not become production defaults automatically.

## Evidence boundary

This policy combines static source contracts and retained offline/runtime summaries:

- native model discovery exposes native model key, format, bits per weight, size, quantization, and loaded-instance context/parallel shape;
- compat discovery exposes the inference-visible model ID;
- the current host settings surface merges native, compat, and CLI identifiers into an editable manual selector, but does not intersect them with an approved catalog or memory-fit policy;
- LabKit can sample host RAM, LM Studio process RSS, and first-GPU NVIDIA VRAM through `psutil` plus `nvidia-smi`;
- LabKit has before/peak/after DTOs, but current retained evidence does not establish physical VRAM placement or a complete product admission envelope;
- a bounded 12B comparison reported the same 6.66 GiB load estimate under automatic and maximum-GPU placement and did not prove a maximum-GPU benefit;
- existing identity records contain exact visible IDs and some size/quantization facts, but they do not provide immutable artifact hashes for every candidate.

Evidence labels used below:

- **exact:** observed for the exact artifact digest, runtime build, platform adapter, context, parallelism, and workload phase;
- **estimate:** conservative calculation from catalog facts; useful only for cold screening;
- **runtime-unexecuted:** required production behavior or measurement that has not been exercised by this analysis.

## Recommendation state machine

```text
START
  -> discover_runtime
      -> runtime_unavailable | discovery_incomplete
      -> reconcile_catalog
          -> no_approved_profile
          -> artifact_missing
          -> identity_ambiguous
          -> identity_unverified
          -> identity_mismatch
          -> collect_hardware_snapshot
              -> metrics_unavailable
              -> cold_static_screen
                  -> incompatible_platform
                  -> insufficient_memory
                  -> estimate_only
                  -> evaluate_observed_envelope
                      -> observation_missing
                      -> observation_stale_or_wrong_shape
                      -> observed_insufficient
                      -> eligible
                          -> rank
                              -> recommended
                              -> manual_approved_only
```

Every transition produces a stable reason code and preserves the evidence class. `estimate_only` must never be serialized as observed fit. `recommended` requires all hard gates; `manual_approved_only` means the artifact is approved for the task but Auto mode lacks sufficient evidence or policy permission.

## Algorithm

### 1. Resolve the request profile

Build a `TaskRequestShape` owned by the application:

- task kind and schema/contract version;
- modality and required capabilities;
- requested context tokens and reserved output tokens;
- requested runtime parallelism and application concurrency;
- runtime family and platform class;
- latency/quality preference, if the product exposes one.

Context fit and memory fit are separate gates. Exact tokenizer accounting belongs to the context-planning track; this policy consumes its accepted context and output reserve rather than estimating tokens from characters.

### 2. Discover runtime and inventory

Read native `/api/v1/models` and compat `/v1/models` separately. Use CLI/on-disk discovery only as a third inventory plane. Preserve per-plane status instead of flattening all strings into one list.

For each native record retain safe facts: native key, format, bits per weight, size bytes, quantization, loaded instances, context length, parallelism, and a hashed instance reference. For each compat record retain the exact inference-visible ID. Runtime discovery must not infer one ID from another.

The product also needs a local artifact digest adapter. The approval key should use a cryptographic digest of the immutable model artifact or a trusted manifest digest. Hashing may run only against a safely resolved model artifact; do not log or persist the filesystem path. If the runtime cannot expose a stable artifact reference and the host cannot resolve one without unsafe path discovery, identity is `hash_unavailable` and is not Auto-eligible.

### 3. Intersect with the approved task-profile catalog

A profile matches only when all of these are equal or explicitly allowed by the profile:

- task profile ID and version;
- native model key;
- compat model ID;
- format;
- artifact digest and digest algorithm;
- quantization label and verified status;
- capability set;
- runtime family/build constraint;
- context tier;
- runtime parallelism and application concurrency.

A family name, approximate parameter count, equivalent-looking filename, or equal file size is not identity. Unknown quantization does not match an approval that names a quantization. A digest mismatch is a hard `identity_mismatch`, not a lower-confidence candidate.

### 4. Collect a platform memory snapshot

Use bytes internally; UI may display GiB. Capture timestamp, adapter, adapter version, sample quality, and per-resource totals/available values.

**CUDA discrete memory**

- Prefer NVML for all visible devices, process attribution, and per-device total/used/free memory.
- `nvidia-smi` CSV is an acceptable degraded adapter when NVML is unavailable.
- Capture host RAM total/available through the OS.
- Never sum VRAM across devices unless the exact approved profile and observed load prove a supported sharding/placement plan. Otherwise evaluate the target device independently.
- Existing LabKit collection reads only the first NVIDIA row and process RSS by process name; that is useful experiment telemetry but insufficient for multi-GPU product recommendation.

**Apple unified memory**

- Capture physical memory and current available/pressure state from supported OS APIs.
- Treat CPU and GPU allocations as one shared pool; do not add a fictional VRAM pool to RAM.
- Capture LM Studio process resident/physical footprint where available.
- For an MLX-backed runtime, an adapter must also capture runtime allocated bytes, active bytes, cache bytes, peak allocated bytes, and peak cache bytes, with reset/scope semantics tied to the exact load/call interval.
- The MLX/Metal adapter is unresolved. Until its fields and LM Studio process attribution are verified on supported macOS builds, Apple Auto mode may use only a catalog envelope already observed and approved through an equivalent trusted adapter; otherwise it returns `metrics_unavailable` or `observation_missing`.

### 5. Cold/static screening

Cold screening is estimate-only and must be conservative.

For CUDA evaluate two independent budgets:

```text
accelerator_required = static_accelerator_bytes
                     + estimated_kv_bytes(context, parallel)
                     + estimated_runtime_workspace_bytes
                     + accelerator_headroom_bytes

host_required = static_host_bytes
              + estimated_host_workspace_bytes
              + host_headroom_bytes
```

For unified memory evaluate one shared budget:

```text
unified_required = static_resident_bytes
                 + estimated_kv_bytes(context, parallel)
                 + estimated_runtime_workspace_bytes
                 + unified_headroom_bytes
```

`static_*` values come from the approved profile, not from a universal file-size multiplier. A file size may be a lower-bound input, never an exact loaded-memory claim. KV and workspace estimates must identify the formula/version and all inputs. Context and parallel scaling may be used to reject an obviously impossible profile, but must not promote an unobserved larger shape to exact fit.

Available memory is a snapshot, not a guarantee. Apply both:

- an absolute reserve for the OS, UI, audio/vision pipelines, and transient allocations;
- a proportional reserve against the usable pool.

The profile must pass the stricter reserve. Headroom policy is product configuration with a versioned rationale; this report does not invent universal percentages or GiB constants.

### 6. Evaluate observed loaded peak

Prefer an approved envelope measured for the exact identity and request shape:

- baseline before load;
- settled loaded state before generation;
- peak during the approved canary/workload phase;
- after-unload read-back;
- host RAM, process footprint, and accelerator/unified-memory channels;
- context, runtime parallelism, application concurrency, KV/cache policy, placement mode, runtime build, adapter/version, and sample interval;
- workload phase and observation count.

For CUDA, compute incremental peak per resource relative to the baseline. For Apple, compute one unified incremental peak and retain process/runtime subcomponents only as attribution evidence; do not add overlapping counters together.

An observation is reusable only when its exact shape matches. Smaller context, lower concurrency, another quantization, another runtime build, or another placement mode does not prove the requested shape. A larger observed envelope may bound a smaller request only when the profile explicitly permits monotonic downscaling and the runtime contract confirms that the smaller shape will be loaded, not silently reused from a larger incompatible instance.

The current session may refine safety after a guarded load, but it must not load arbitrary unapproved models merely to discover whether they fit. Any canary/load is a separate user-authorized lifecycle operation and must preserve ownership and cleanup rules.

### 7. Rank eligible profiles

Hard-filter first; rank second. An eligible set contains only exact approved identities with compatible capability, context, concurrency, runtime, and memory gates.

Recommended ordering:

1. task-profile approval tier and semantic evidence;
2. exact observed fit over estimate-only fit;
3. greater residual headroom on the limiting resource;
4. lower expected latency or lower resource use, according to explicit user preference;
5. deterministic catalog priority and profile ID as final tie-breakers.

Do not rank by parameter count alone. Do not silently substitute an unapproved model when the preferred model is absent. If no candidate passes, return the most actionable typed reason, not the nearest-looking model.

## Auto and manual selection

### Auto mode

Auto may select only a profile with:

- `approval_status=approved` and `auto_eligible=true`;
- exact artifact digest, quantization, native key, and compat ID match;
- required task capability and semantic/product evidence;
- compatible runtime build, context, parallelism, and concurrency;
- platform metrics available;
- memory verdict `observed_fit`, or a catalog-authorized `conservative_estimate_fit` policy for that exact platform class;
- no incompatible preloaded instance or unresolved external lifecycle ownership.

If multiple profiles pass, Auto displays the selected profile and concise reason. It never changes the catalog, approves a new model, downloads a model, or increases context/concurrency to chase quality.

### Manual approved selection

The manual selector lists only approved profiles intersected with discovered exact identities. It groups them as:

- recommended now;
- approved but not recommended for the current request shape;
- unavailable, with a reason such as missing artifact, insufficient memory, incompatible runtime, or missing metrics.

Manual choice does not bypass identity, capability, or hard memory failure. It may choose an approved estimate-only profile only if product policy explicitly allows a guarded, user-confirmed load/canary. The UI must show that the selection is not yet observed, and a failed materialization or memory gate returns to the original state without substituting another model.

A free-text model ID may remain an advanced diagnostic field, but it is outside approved selection and must never be treated as Auto or as an approved manual profile.

## Platform matrix

| Platform | Cold inputs | Exact/observed inputs | Fit rule | Auto fallback |
|---|---|---|---|---|
| NVIDIA, one discrete GPU | Per-device total/free VRAM; host RAM available; approved static/KV/workspace envelopes | Baseline, settled load, workload peak, unload read-back; per-device and host deltas | Both accelerator and host budgets pass their independent reserves | Estimate-only only when profile policy allows; otherwise manual approved or needs measurement |
| NVIDIA, multiple GPUs | Per-device metrics and placement capability | Exact device/layer/shard placement plus per-device peaks | Never sum devices without approved placement evidence | Restrict to one proven device/placement or unavailable |
| CPU/offload on non-unified host | Host RAM plus any discrete accelerator channel | Host/process and accelerator peaks for exact offload policy | Every independently limited resource passes | No assumption that unused VRAM becomes general RAM |
| Apple unified memory | Physical/available memory and pressure; approved unified estimate | Exact unified peak plus process/runtime attribution from verified adapter | One shared-pool reserve; overlapping counters are not summed | Catalog-observed equivalent only; otherwise metrics unavailable |
| Unknown/unsupported adapter | None trustworthy | None | No fit decision | No recommendation |

## Confidence and fallback policy

| Confidence | Required evidence | Auto status | User-facing wording |
|---|---|---|---|
| `exact_observed` | Exact identity and exact request shape; trusted platform adapter; retained peak and cleanup read-back | Eligible if all other gates pass | Recommended for this task and hardware shape |
| `conservative_estimate` | Exact identity; approved static/KV/workspace formulas; current hardware snapshot; explicit profile permission | Eligible only when catalog policy allows | Expected to fit; not measured on this exact shape |
| `runtime_unexecuted` | Design or static contract only; no matching peak | Not eligible by default | Approved model, measurement required |
| `unknown` | Missing identity, quantization, metrics, or formula | Never eligible | Cannot recommend safely |

Fallback order is deterministic:

1. reduce to another **approved** profile for the same task with a smaller exact context/concurrency shape;
2. offer an approved manual profile with a clear estimate-only warning, if policy allows;
3. keep the original application-owned source/output path and report local model unavailable;
4. never choose an unapproved model or mutate the task contract silently.

## Data contract

```json
{
  "request_shape": {
    "task_profile_id": "string",
    "task_contract_version": "string",
    "required_capabilities": ["string"],
    "context_tokens": 0,
    "output_reserve_tokens": 0,
    "runtime_parallel": 1,
    "app_concurrency": 1
  },
  "catalog_profile": {
    "catalog_version": "string",
    "approval_status": "approved",
    "auto_eligible": false,
    "identity": {
      "native_model_key": "string",
      "compat_model_id": "string",
      "format": "gguf",
      "artifact_digest": "sha256:...",
      "quantization": "string",
      "quantization_verified": true
    },
    "runtime_constraints": {},
    "memory_envelopes": []
  },
  "runtime_discovery": {
    "native_status": "ok|failed",
    "compat_status": "ok|failed",
    "inventory_status": "complete|partial|failed",
    "identity_match": "exact|ambiguous|missing|mismatch"
  },
  "hardware_snapshot": {
    "platform_class": "cuda_discrete|apple_unified|cpu_offload|unsupported",
    "adapter": "string",
    "adapter_version": "string",
    "captured_at": "RFC3339",
    "resources": []
  },
  "memory_decision": {
    "evidence_class": "exact|estimate|runtime-unexecuted",
    "verdict": "observed_fit|estimate_fit|insufficient|unknown",
    "limiting_resource": "string|null",
    "required_bytes": 0,
    "available_after_reserve_bytes": 0,
    "headroom_bytes": 0,
    "reason_codes": ["string"]
  },
  "recommendation": {
    "state": "recommended|manual_approved_only|unavailable",
    "selected_profile_id": "string|null",
    "confidence": "exact_observed|conservative_estimate|runtime_unexecuted|unknown",
    "alternatives": [],
    "reason_codes": ["string"]
  }
}
```

Persist only privacy-safe identities, digests, numeric measurements, categorical verdicts, and adapter/runtime versions. Do not persist local model paths, prompts, responses, credentials, or raw user text.

## Required reason codes

At minimum:

- `runtime_unavailable`, `native_discovery_failed`, `compat_discovery_failed`, `inventory_partial`;
- `no_approved_profile`, `artifact_missing`, `hash_unavailable`, `identity_ambiguous`, `identity_mismatch`, `quantization_unknown`, `quantization_mismatch`;
- `platform_unsupported`, `metrics_unavailable`, `mlx_metrics_adapter_unresolved`;
- `static_estimate_exceeds_budget`, `observed_peak_exceeds_budget`, `headroom_insufficient`;
- `observation_missing`, `observation_stale`, `context_shape_unobserved`, `concurrency_shape_unobserved`, `kv_policy_unobserved`;
- `preloaded_incompatible`, `external_instance_not_owned`, `approved_manual_only`, `recommended_exact_observed`.

## Implementation seams

Host-owned seams:

1. `ApprovedTaskProfileCatalog`: signed/versioned policy data and explicit promotion process.
2. `RuntimeInventoryAdapter`: native, compat, CLI/on-disk, loaded-instance, and artifact-digest reconciliation.
3. `HardwareMetricsAdapter`: CUDA, Apple unified memory, and unsupported typed outcomes.
4. `MemoryEnvelopeEvaluator`: pure estimate/observed fit calculation with versioned reserve policy.
5. `ModelRecommendationService`: hard-filter, rank, reason codes, Auto/manual projection.
6. `LifecyclePort`: materialization proof, ownership handle, incompatible-preload detection, and safe cleanup.
7. `RecommendationPresenter`: never hides confidence, degraded state, or why a model is unavailable.

LabKit's pure identity/lifecycle vocabulary and system-summary DTOs are useful inputs, but the current lab candidate registry and benchmark recommender must not be embedded as product truth.

## Unresolved gates

1. **MLX/Metal metrics adapter:** exact supported APIs, counter semantics, cache reset, process attribution, sampling overhead, and behavior under LM Studio remain unverified. This blocks general Apple Auto recommendation without a pre-approved equivalent envelope.
2. **Artifact digest resolution:** current discovery contracts do not prove a privacy-safe immutable digest for every installed model. Auto requires this seam.
3. **CUDA process/device attribution:** current first-row `nvidia-smi` sampling does not cover multiple GPUs, MIG, sharding, or robust process attribution.
4. **Memory envelope calibration:** no retained matrix binds exact loaded peaks to every approved task/context/concurrency/quantization shape.
5. **KV/workspace formulas:** estimates need runtime-specific, versioned formulas and conservative validation against observed peaks.
6. **Headroom policy:** absolute and proportional reserves need product thresholds and stress evidence; no universal constants are asserted here.
7. **Lifecycle integration:** Auto selection, guarded materialization, ownership, cancellation, and fallback have not been executed end to end in the host application.
8. **Approval catalog:** this report defines the contract but does not approve models or convert current lab candidates into production profiles.

## Non-claims

- No model is approved, ranked, or made a production default by this report.
- No live hardware, LM Studio, CUDA, MLX, Metal, tokenizer, load, or inference operation was executed.
- Existing model file sizes and reported load estimates are not claimed to be exact resident or peak memory.
- Available memory at recommendation time does not guarantee a later allocation.
- Larger parameter count is not claimed to mean better task quality.
- Maximum-GPU placement, physical KV reuse, multi-GPU aggregation, and Apple MLX metrics are not proven.
