# GPU Memory and Concurrency Recommendation Matrix — Technical Specification

**Status:** DRAFT FOLLOW-UP; documentation only; no live model load, download, inference, dispatch, commit, or push is authorized by this document.

**Repository:** LM Studio LabKit

**Goal:** Extend the existing LM Studio telemetry and concurrency runners just enough to produce reproducible recommendations of the form:

```text
exact model artifact + quantization + context tier + parallel shape + workload
→ measured memory envelope
→ approved / manual_only / rejected recommendation
```

The work must reuse the existing lifecycle, concurrency, metrics, reporting, and full-GPU controller seams. It must not create a second benchmark framework.

## 1. Why additional work is required

The repository already provides:

- load/unload and loaded-instance verification;
- exact model and quantization identity contracts;
- configured/applied parallel fields;
- distinction between runtime slots and application request concurrency;
- host RAM, LM Studio RSS, first-GPU VRAM/utilization/power samples;
- before/peak/after summaries;
- append-only run artifacts and cleanup/global-zero gates;
- a bounded full-GPU controller contract.

The current evidence is insufficient for a product recommendation matrix because:

1. the existing NVIDIA sampler is not a complete per-device/per-process attribution layer;
2. before/peak/after does not identify load-idle, prefill, decode, concurrent peak, post-batch idle, and post-unload phases independently;
3. requested `--gpu max` or a load echo does not by itself prove physical full-GPU placement;
4. memory cost is not yet calibrated across exact context and concurrency cells;
5. no canonical recommendation artifact converts repeated peaks into approved, conditional, or rejected profiles.

## 2. Scope

### In scope

- NVIDIA device enumeration and process-aware memory telemetry where NVML exposes it;
- deterministic `nvidia-smi` fallback with an explicit degraded evidence state;
- phase-aware sampling around existing lifecycle/concurrency runners;
- exact runtime and application concurrency attribution;
- a bounded P1 → P2 → P4 memory matrix;
- exact context tiers and workload classes;
- repeatable memory-envelope aggregation;
- publication-safe Markdown, JSON, and CSV reports;
- candidate recommendation catalog generation;
- offline unit/contract tests and opt-in live gates;
- documentation of lifecycle, placement, download, and recommendation boundaries.

### Out of scope

- a new generic benchmark framework;
- silent model downloads;
- live model execution without an explicit user gate;
- production admission based on one run;
- claiming exact layer placement when the installed runtime does not expose it;
- summing VRAM across GPUs without an explicitly verified sharding plan;
- Apple/Metal Auto recommendations before an equivalent measured adapter exists;
- changing a source/host application;
- publishing private prompts, responses, machine paths, credentials, or raw private artifacts.

## 3. Existing owners to extend

Implementation must begin with owner recon and prefer these current files:

```text
tools/lmstudio_lab/system_metrics.py
tools/lmstudio_lab/metrics.py
tools/lmstudio_lab/model_lifecycle.py
tools/lmstudio_lab/managed_runner.py
tools/lmstudio_lab/report.py
libs/lmstudio_managed/metrics/models.py
libs/lmstudio_managed/lifecycle/state.py
libs/lmstudio_managed/lifecycle/policy.py
libs/lmstudio_managed/registry/profiles.py
libs/lmstudio_managed/registry/recommendations.py
lmstudio_labkit/qwen35_full_gpu.py
lmstudio_labkit/qwen35_full_gpu_host.py
tests/tools/test_lmstudio_lab_system_metrics.py
```

New modules are allowed only when one of these owners cannot hold the responsibility without mixing reusable backend contracts with lab orchestration.

## 4. Required runtime identity

Every measured cell must bind:

```text
model catalog key
+ exact artifact/repository/revision identity when available
+ exact quantization / bits-per-weight / format
+ loaded instance ID
+ device identifier
+ requested load config
+ applied/read-back load config
+ context length
+ runtime parallel slots
+ application concurrency
+ endpoint family
+ workload ID and content hashes
+ runner and schema revisions
```

A model-name-only row is invalid evidence.

## 5. Telemetry requirements

### 5.1. NVIDIA primary adapter

Add an optional NVML-backed sampler that records all visible devices and, where supported:

- stable GPU index/UUID hash;
- total, used, and free device memory;
- compute/graphics process entries;
- per-process used GPU memory;
- GPU and memory utilization;
- power draw;
- MIG identity/state when present;
- sampler timestamp and adapter status.

The adapter must not expose usernames, private paths, command lines, or unredacted machine identifiers in publication-safe artifacts.

### 5.2. Fallback adapter

Retain `nvidia-smi` as a fallback. The fallback must report an explicit evidence level such as:

```text
nvml_process_attributed
nvml_device_only
nvidia_smi_device_only
unavailable
```

A device-only sample must not be promoted to a process-attributed claim.

### 5.3. Host/process telemetry

Continue collecting:

- total/available/used host RAM;
- LM Studio process RSS where safely attributable;
- CPU utilization;
- sampling errors and unavailable states.

Unknown values remain `null`/explicit state. Zero is reserved for a real measured zero.

### 5.4. Phase markers

The runner must emit and retain samples for:

```text
clean_baseline
load_started
loaded_idle
request_dispatched
prefill_active
first_token
decode_active
concurrent_peak
batch_completed
post_batch_idle
unload_started
after_unload_global_zero
```

When LM Studio does not expose a phase directly, derive it only from attributable request intervals and label the derivation method. Do not fabricate prefill/decode precision from coarse polling.

### 5.5. Sampling behavior

- Start before model load.
- Continue through confirmed global zero.
- Use a configurable sampling interval with the actual interval stored in the artifact.
- Sampling failure must not change the model business result, but it invalidates memory recommendation evidence for the affected cell.
- Sampler overhead must be measured on a short control and reported.

## 6. Matrix definition

### 6.1. Cell identity

```text
exact model artifact
× exact quant
× context tier
× runtime parallel
× application concurrency
× GPU placement policy
× KV placement
× workload class
```

### 6.2. Initial bounded axes

| Axis | Initial values |
|---|---|
| Context | 8K baseline; then 16K, 32K, 48K, 64K only after prior-tier admission |
| Runtime parallel | 1, 2, 4 |
| Application concurrency | 1, 2, 4, matching the measured lane |
| GPU placement | runtime auto; explicit max/full-GPU intent where supported |
| KV placement | runtime default; GPU KV only as a separate admitted A/B |
| Workload | short plain, long text, simple structured output, production-shaped structured output; vision separate |

Do not combine vision with the first text-memory calibration matrix.

### 6.3. Promotion order

For each exact model/quant/context/workload shape:

```text
load-only materialization
→ sequential P1 baseline
→ P2 only after P1 passes
→ P4 only after P2 passes
```

A failed higher-concurrency lane does not invalidate a lower verified lane.

### 6.4. Repeats

- Minimum three independent load/unload cycles for memory calibration.
- Minimum five request executions for cells used to make quality/concurrency recommendations.
- Preserve call executions, unique output hashes, and independently reviewed semantic cases as separate denominators.
- Never overwrite failed attempts.

## 7. Metrics per cell

### Memory

- clean baseline VRAM/RAM;
- loaded-idle VRAM/RAM/RSS;
- prefill peak;
- decode peak;
- concurrent batch peak;
- post-batch idle;
- after-unload value;
- peak delta from clean baseline;
- peak delta from loaded idle;
- per-device and per-process attribution level;
- memory-thrash/page-fault evidence when available.

### Runtime

- load and unload duration;
- time to first token;
- prompt/prefill speed;
- generation speed;
- per-request latency;
- batch wall time;
- attributable start/end intervals;
- configured and applied parallel;
- queue-pressure versus true-parallel classification;
- timeout, cancellation, crash, OOM, and admission errors;
- cleanup/global-zero status.

### Response integrity

Memory success does not equal production admission. Retain separate results for:

- transport completion;
- finish reason and output-budget use;
- raw/normalized JSON and schema;
- task isolation and cross-request sentinel contamination;
- protected values;
- semantic completeness;
- runaway/repetition.

## 8. Memory envelope and recommendation policy

### 8.1. Derived values

```text
fixed_loaded_cost = loaded_idle - clean_baseline
cell_peak_delta = concurrent_peak - clean_baseline
active_overhead = concurrent_peak - loaded_idle
```

These values are observations, not a linear model. The implementation must not assume `P4 == P1 × 4`.

### 8.2. Recommended memory

For an admitted profile:

```text
recommended_memory
= repeated observed peak envelope
+ evidence-backed safety reserve
```

The report may evaluate candidate reserves such as a percentage floor and an absolute floor, but must not freeze a product default until repeated cells justify it.

### 8.3. Recommendation states

```text
approved
manual_only
rejected_capacity
rejected_runtime
insufficient_evidence
```

A candidate profile is `approved` only when:

- exact identity and applied runtime shape are verified;
- required repeats complete;
- memory samples are attributable at the required evidence level;
- no OOM/crash/thrash is observed;
- response integrity gates pass;
- unload/global-zero succeeds;
- the safety reserve still fits the target hardware class.

### 8.4. Candidate catalog output

```json
{
  "model_identity": "opaque-stable-id",
  "artifact_identity": "opaque-stable-revision",
  "quantization": "Q4_K_M",
  "context_tokens": 32768,
  "runtime_parallel": 2,
  "application_concurrency": 2,
  "placement_policy": "full_gpu_required",
  "kv_placement": "gpu",
  "workload_class": "structured_text",
  "measured_peak_vram_mb": null,
  "recommended_vram_mb": null,
  "recommended_ram_mb": null,
  "safety_reserve_policy": "candidate",
  "telemetry_evidence": "nvml_process_attributed",
  "evidence_revision": "sha256:...",
  "status": "insufficient_evidence"
}
```

Exact public identifiers may be retained only when publication rules permit them; machine/user identity remains redacted.

## 9. Full-GPU evidence boundary

`--gpu max`, a requested ratio of `1.0`, or echoed load config expresses intent. It is not sufficient physical placement evidence by itself.

The report must separate:

```text
full_gpu_requested
full_gpu_config_applied
full_gpu_runtime_observed
full_gpu_physical_placement_unproven
```

If the installed LM Studio/runtime schema cannot prove layer placement or negative CPU fallback, the matrix may still report measured device memory and runtime success, but must retain the placement limitation. It must not claim physically complete GPU residency.

## 10. Model download boundary

This matrix never silently downloads a model.

A later acquisition flow may use the existing download owners, but requires an independent user-approved action with:

- exact repository/revision/file/quantization;
- license/source decision;
- disk and memory preflight;
- resumable progress;
- checksum/identity verification;
- atomic installation;
- cancellation and temporary-file cleanup;
- post-install discovery/read-back.

Download, install, load, and recommend remain separate state transitions.

## 11. Artifact layout

Private append-only evidence remains outside Git:

```text
<private-root>/<matrix-id>/<cell-id>/<attempt-id>/
├── request.json
├── runtime_identity.json
├── applied_load_config.json
├── telemetry.jsonl
├── intervals.json
├── response_envelope.json
├── outcome.json
└── cleanup.json
```

Publication-safe outputs:

```text
experiments/lmstudio/results_summaries/<date>_gpu_memory_matrix.md
experiments/lmstudio/results_summaries/<date>_gpu_memory_matrix.json
experiments/lmstudio/results_summaries/<date>_gpu_memory_matrix.csv
experiments/lmstudio/results_summaries/<date>_model_memory_recommendations.json
```

## 12. Implementation slices

### M1 — Telemetry contracts and NVML adapter

- Extend canonical metrics DTOs with per-device/per-process samples and evidence level.
- Add optional NVML adapter and deterministic `nvidia-smi` fallback.
- Preserve current public-safe serialization.
- Add fixtures for multi-GPU, MIG, disappearing processes, unavailable counters, measured zero, and malformed command output.

### M2 — Phase-aware runner integration

- Start sampling before load and stop after global zero.
- Bind samples to load/request/unload phase markers and request intervals.
- Preserve current runner outputs and add fields additively.
- Prove sampler failure cannot change request outcome.

### M3 — Bounded matrix planner and resume

- Materialize exact cells before live execution.
- Enforce P1 → P2 → P4 promotion.
- Persist an append-only attempt reservation before each side effect.
- Resume only missing cells/attempts.
- Keep live gates opt-in and downloads forbidden.

### M4 — Aggregation and recommendation artifacts

- Aggregate repeated peaks without assuming linear scaling.
- Emit Markdown, JSON, CSV, and candidate catalog artifacts.
- Keep approved/manual/rejected/insufficient-evidence states explicit.
- Validate cross-format consistency.

### M5 — Documentation and independent review

- Update lifecycle/metrics documentation with measured semantics.
- Document telemetry and full-GPU non-claims.
- Run independent runtime, statistics, and publication-safety reviews.
- Apply accepted findings before any recommendation is promoted.

## 13. Offline tests

Required focused coverage:

- NVML all-device enumeration;
- per-process attribution and disappearing PID;
- MIG and unsupported-field behavior;
- fallback/degraded evidence states;
- unknown versus measured zero;
- phase ordering and timestamp monotonicity;
- peak selection by phase and cell;
- runtime parallel versus app concurrency mismatch;
- P4 blocked until P2 passes;
- nonlinear aggregation fixtures;
- recommendation-state transitions;
- JSON/CSV/Markdown consistency;
- privacy-safe serialization;
- sampler-error isolation;
- append-only resume/idempotency;
- final unload/global-zero proof.

Default gates:

```bash
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
uv run ruff check .
uv run ruff format --check .
python scripts/audit_publication_safety.py
git diff --check
```

## 14. Opt-in live gates

Live execution requires a separate explicit user approval after:

1. the exact model/quant/context/concurrency manifest is reviewed;
2. expected call count and duration are bounded;
3. model downloads are confirmed unnecessary or separately approved;
4. exclusive execution and global-zero preflight pass;
5. private evidence root and watchdog are verified;
6. the active repository plan allows the lane without overlapping writers.

A live gate must stop and preserve evidence on identity mismatch, unapplied runtime shape, telemetry failure, unexpected loaded instances, OOM/crash/thrash, cleanup failure, or missing progress.

## 15. Acceptance criteria

The technical work is complete when:

- the existing runner captures phase-aware samples from pre-load through global zero;
- every sample states its device/process attribution level;
- runtime slots and actual overlapping application requests are both proven;
- exact model/quant/context/workload identity is bound to every cell;
- P1/P2/P4 cells are repeatable and resumable;
- measured peaks and safety-reserve candidates are reported separately;
- recommendation states are generated without linear-memory assumptions;
- full-GPU requested/applied/observed/unproven states are not conflated;
- publication-safe MD/JSON/CSV/catalog outputs agree;
- offline tests and publication audit pass;
- live evidence, if authorized, ends with unload and global loaded count zero;
- no host-application changes or silent downloads occur.

## 16. Documentation references

### Internal

- [Model lifecycle, context, KV cache, and parallelism](../lmstudio_managed_backend_docs/03_model_lifecycle_load_unload_context_kv.md)
- [Benchmark harness technical specification](../lmstudio_managed_backend_docs/08_benchmark_harness_technical_spec.md)
- [Metrics schema and result format](../lmstudio_managed_backend_docs/09_metrics_schema_and_result_format.md)
- [Qwen 3.5 full-GPU matrix plan](2026-07-13-qwen35-full-gpu-matrix.md)
- [Adaptive model recommendation policy](../../experiments/lmstudio/results_summaries/2026-07-13_adaptive_model_recommendation_policy.md)
- [Parallel/cache/GPU runtime audit](../../experiments/lmstudio/results_summaries/2026-07-12_parallel_cache_gpu_runtime_audit.md)

### Official LM Studio

- [Model download REST API](https://lmstudio.ai/docs/developer/rest/download)
- [Model download status REST API](https://lmstudio.ai/docs/developer/rest/download-status)
- [Model load REST API](https://lmstudio.ai/docs/developer/rest/load)
- [Model list REST API](https://lmstudio.ai/docs/developer/rest/list)
- [Parallel requests](https://lmstudio.ai/docs/app/advanced/parallel-requests)
- [REST API overview](https://lmstudio.ai/docs/developer/rest)
- [LM Studio API changelog](https://lmstudio.ai/docs/developer/api-changelog)

### Official NVIDIA

- [NVML API Reference Guide](https://docs.nvidia.com/deploy/nvml-api/)
- [NVML device and process queries](https://docs.nvidia.com/deploy/nvml-api/group__nvmlDeviceQueries.html)

## 17. Recommended execution order

Do not activate this plan in parallel with another active shared-checkout experiment wave.

Recommended order:

```text
current active wave reaches a safe terminal boundary
→ M1 telemetry contracts
→ M2 phase integration
→ offline review
→ M3 bounded planner/resume
→ one short approved live calibration canary
→ M4 aggregation/recommendation
→ independent review
→ broader matrix only after the canary proves attributable telemetry
```

## 18. Independent review adjudication

The five independent review handoffs were adjudicated against this plan before closure.

Accepted blockers and bounded repairs:

- catalog payload validation now requires exact top-level fields, non-empty status reasons, and status/evidence coherence; an impossible `approved` row is rejected;
- the live-capable matrix plan requires at least three attempts and cannot promote a lane from one load/unload result;
- timestamp order and GPU memory-evidence validity are reported separately from sampler execution validity; missing/regressing timestamps, typed adapter errors, unavailable samples, and partial device errors invalidate memory evidence;
- recommendation observations now require overlap, phase, independent-cycle, and immutable owner-evidence proofs before approval, and the matrix journal retains those proofs per attempt;
- recommendation identity fields reject POSIX absolute paths at any root, Windows drive/UNC paths, `file://` values, and home-relative values before any public artifact is written;
- the static publication audit now detects generic POSIX user-profile/private-root paths and Windows user-profile paths, with isolated regression fixtures;
- packaged LabKit modules use their installed `lmstudio_managed` namespace, and an isolated wheel smoke test imports the managed package, affected lab modules, and console module without the repository source roots.

Rejected as a blocker for this plan:

- treating the current `lmstudio-labkit` wheel as if it were already the proposed standard-library-only `lmstudio-managed` distribution. The current package metadata describes LabKit, while this plan and the package-boundary document explicitly classify standalone extraction as future work and make no release claim.

Follow-up work, not silently absorbed into this repair:

- define the standalone distribution's exact public-symbol/module allowlist, move or exclude experiment-specific registry/report owners, and add standalone wheel-content/dependency gates during the separately planned extraction;
- if pseudonymous device/process telemetry is published beyond the current sanitized summaries, define an explicit linkability/rotation policy; deterministic hashes are pseudonyms, not anonymity.

No model download, load, unload, inference, network call, commit, or push was performed while applying these repairs.
