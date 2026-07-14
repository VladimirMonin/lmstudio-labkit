# GPU Telemetry, Memory Recommendations, and Package Boundary

## Purpose

This document defines the publication-safe boundary between reusable managed-runtime contracts and LabKit experiment orchestration. It also defines how lifecycle telemetry and versioned memory recommendation catalogs may be consumed without turning experimental evidence into an unsupported runtime claim.

This is a contract and extraction proposal. It does not claim that a standalone distribution has already been published, that a model has been physically placed fully on GPU, or that any recommendation is valid beyond its exact measured identity and workload.

## Ownership boundary

Reusable contracts remain under `libs/lmstudio_managed/`:

- lifecycle state, compatibility, ownership, and unload policy;
- request and transport contract types that do not perform lab orchestration;
- privacy-safe telemetry DTOs and evidence levels;
- exact model and runtime identity records;
- memory observation, reserve, recommendation, and catalog validation contracts.

Lab-only responsibilities remain outside the reusable library:

- matrix planning, promotion, attempt reservation, and resume;
- datasets, workload fixtures, benchmark runners, and CLI entry points;
- raw or owner-only evidence capture;
- report rendering and cross-format artifact generation;
- live calibration policy, watchdogs, and experiment-specific admission gates.

The dependency direction is one-way:

```text
host consumer -> installed managed-contract package
LabKit orchestration -> managed-contract package
managed-contract package -X-> host consumer or LabKit tools
```

A consumer owns transport execution, cancellation, persistence, user-facing policy, and task-specific semantic validation. LabKit evidence can inform those decisions, but it is not runtime configuration by itself.

## Lifecycle and telemetry semantics

A complete private measurement record is valid only when it binds the exact model artifact and revision, checksum, quantization, context length, runtime parallelism, application concurrency, workload class, placement requirement, KV placement, runtime identity, and schema/runner revisions. The current reusable `MemoryCellObservation` and v1 catalog row carry the artifact/workload/runtime-shape fields and an evidence digest, but they do not carry runtime identity or schema/runner revisions directly. That distinction is a compatibility limitation of v1, not permission to drop those fields from the owner evidence.

Lifecycle sampling starts before load and continues through cleanup. The meaningful checkpoints are:

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

A phase may be marked by a direct event or derived from an attributable request interval. Derived phase labels must retain their derivation method and confidence. Coarse polling must not be described as exact prefill/decode timing.

Telemetry evidence levels are ordered by what they prove, not by convenience:

| Evidence level | Permitted claim |
|---|---|
| `nvml_process_attributed` | Device and process memory were attributable for the sample |
| `nvml_device_only` | Device metrics were observed; process ownership is unproven |
| `nvidia_smi_device_only` | Fallback device metrics were observed; process ownership is unproven |
| `unavailable` | No memory recommendation may be inferred from the sample |

Unknown and unavailable values are `null` or an explicit unavailable/error state. Zero is reserved for a measured zero. A sampler failure does not rewrite the request result, but it invalidates telemetry-based recommendation evidence for the affected attempt.

## Full-GPU claim ladder

GPU placement must be represented as separate facts:

1. `full_gpu_requested`: the caller requested the strongest supported GPU placement policy.
2. `full_gpu_config_applied`: runtime read-back matched that requested configuration.
3. `full_gpu_runtime_observed`: attributable runtime telemetry observed GPU activity and memory for the loaded instance.
4. `full_gpu_physical_placement_unproven`: the available runtime schema did not prove complete layer residency or absence of CPU fallback.

The first three facts do not automatically negate the fourth. A request such as `gpu=max`, an echoed ratio, successful inference, or high device-memory use is not sufficient proof that every model layer and relevant cache allocation remained physically on GPU. When layer placement or negative CPU fallback is not exposed, reports must retain the unproven limitation.

## Memory recommendation semantics

The canonical reusable schema revision is:

```text
model-memory-recommendation-catalog.v1
```

For each exact cell, repeated observations keep these values separate:

```text
fixed_model_cost_vram_mb = loaded_idle - clean_baseline
context_concurrency_overhead_vram_mb = measured_peak - loaded_idle
recommended_vram_mb = repeated measured peak envelope + safety reserve
```

These are measured and derived values, not a linear scaling law. A P1 observation must not be multiplied to predict P2 or P4. Each context/concurrency/workload shape requires its own evidence.

The current reusable status vocabulary is:

- `approved`: all approval gates passed for the exact cell;
- `manual_only`: evidence is usable only with an explicit consumer decision, commonly because process attribution or physical placement is unproven;
- `rejected`: runtime, capacity, response-integrity, thrash, or cleanup evidence failed;
- `insufficient_evidence`: repeats, identity, runtime shape, metrics, or telemetry are incomplete.

At least three independent observations are required before approval is possible. The reusable builder enforces the minimum count and unique `attempt_id` values; it cannot prove that the attempts came from independent load/unload cycles. The LabKit or consumer orchestration layer must preserve that proof, and evidence without it remains `insufficient_evidence` regardless of the serialized status. A consumer must still match the catalog row to its exact artifact, runtime shape, workload, and hardware capacity. `approved` is not a global model endorsement.

## Versioned catalog consumption

A consumer must fail closed at the package boundary:

1. Parse the document as data, not executable configuration.
2. Require the exact top-level `schema_revision` supported by the installed package.
3. Validate the complete payload with `MemoryRecommendationCatalog.validate_payload` or an equivalent validator from the pinned package version.
4. Reject unknown revisions, missing or extra fields, duplicate identities, invalid digests, invalid status values, and unsorted rows.
5. Select only by the full cell identity; never fall back to a model display name.
6. Re-check local capacity and runtime identity before applying an `approved` row.
7. Route `manual_only` to an explicit operator/consumer policy; never auto-promote it.
8. Treat `rejected` and `insufficient_evidence` as ineligible for automatic selection.
9. Preserve `measured_peak_vram_mb`, reserve, and `recommended_vram_mb` as distinct fields in logs and UI.
10. Keep the catalog immutable for a running operation; reload only at a controlled configuration boundary.

Schema revision and Python package version are independent compatibility dimensions. A package release may support one or more catalog revisions, but support must be explicit and tested. Consumers must not guess that a newer catalog is backward compatible.

### Current v1 provenance limitation

The v1 catalog row does not serialize runtime identity, runner revision, telemetry schema revision, hardware identity, or the independent-cycle proof. `evidence_revision` is an integrity digest of the supplied observations; by itself it is not a dereferenceable provenance record and does not prove that those omitted identities were checked.

Until a later catalog revision carries that provenance or a separately reviewed immutable manifest binds it to the digest, a standalone consumer cannot promote a v1 row to automatic runtime selection from the catalog alone. It must bind the row to owner evidence that supplies the omitted identities and cycle proof; otherwise it must downgrade an `approved` row to `manual_only` or `insufficient_evidence`. The same rule applies to `full_gpu_required`: `placement_observed` may be true only when evidence beyond ordinary device/process activity proves the required placement; high VRAM use or process attribution alone is insufficient.

## Proposed standalone Python distribution

### Distribution shape

Extract `libs/lmstudio_managed/` into a dedicated distribution with:

```text
Distribution name: lmstudio-managed
Import package:    lmstudio_managed
Initial version:   an explicit pre-release chosen at extraction time
Layout:            src/lmstudio_managed/
Build backend:     hatchling
```

The extracted wheel should contain only the reusable contract kernel. It must not contain `tools/lmstudio_lab`, benchmark datasets, experiment manifests, report generators, raw evidence, or experiment-specific runners.

The current repository layout import, `libs.lmstudio_managed`, is transitional and must not become the consumer-facing API. The extraction should establish `lmstudio_managed` as the stable import namespace and provide a bounded in-repository compatibility phase while LabKit imports are migrated.

### Dependency policy

The base wheel should remain standard-library-only where the current contracts allow it. Optional integrations belong behind extras or consumer adapters, for example:

```text
lmstudio-managed[nvml]
lmstudio-managed[lmstudio-sdk]
```

Optional integrations must preserve explicit unavailable/degraded states when absent. Installing the base contract package must not silently install benchmark, image, YAML, or report dependencies.

### Public API

The supported public surface should be an explicit `lmstudio_managed.__all__` covering:

- lifecycle state and pure policy decisions;
- privacy-safe client/transport protocols and response types;
- model identity and registry contract types;
- telemetry DTOs and evidence enums;
- memory recommendation DTOs, schema revision constants, builders, and validators.

Internal helpers, lab planners, serializers for private evidence, and experimental controllers remain non-public. Public API changes follow semantic versioning once the first stable release is declared; before then, pre-release version changes remain explicit to consumers.

### Consumer pinning

A host consumer should pin an exact package version in its project metadata and lockfile and declare the catalog revisions it accepts. During a pre-release phase, the dependency should be exact rather than ranged, for example:

```text
lmstudio-managed==0.1.0a1
```

The version above is illustrative, not a claim that this release exists. The consumer upgrade procedure is:

1. update the exact package pin;
2. regenerate the lockfile;
3. run package contract and fake-adapter compatibility tests;
4. verify the accepted catalog revision set;
5. run opt-in live compatibility checks only under a separate authorization gate;
6. promote the new pin only after those checks pass.

Copying package files into a consumer repository is not supported because it creates two drifting owners.

### Extraction sequence

1. Freeze and test the intended public symbols currently under `libs/lmstudio_managed/`.
2. Create the standalone `src/lmstudio_managed/` distribution metadata without lab dependencies.
3. Add wheel-content and import-boundary tests.
4. Publish an immutable pre-release artifact to the chosen package channel.
5. Pin LabKit to that exact artifact and migrate imports from the transitional repository namespace.
6. Verify all offline LabKit gates against the installed wheel rather than an in-tree shadow copy.
7. Have each consumer pin the same reviewed version and implement its own adapters.
8. Remove the transitional copy only after no consumer imports it and rollback remains possible through the prior package pin.

### Release gates

A standalone wheel is releasable only when:

- wheel contents include only the declared reusable package;
- importing the base package does not import LabKit tools or optional integrations;
- public symbols and catalog schema constants are contract-tested;
- privacy-safe serialization tests pass;
- lifecycle ownership and unload policy tests pass;
- recommendation status and fail-closed catalog validation tests pass;
- a fake consumer adapter passes without network or model operations;
- the publication-safety audit passes;
- the artifact digest and version are recorded in release metadata.

## Publication boundary

Publication-safe documentation and recommendation catalogs may contain exact public model artifact identity, quantization, workload class, aggregate memory measurements, schema revisions, and opaque evidence digests when policy permits.

They must not contain prompts, responses, raw user text, credentials, local filesystem paths, usernames, command lines, machine identifiers, process IDs, or private product vocabulary. Device and process identity must remain hashed or omitted. Raw append-only evidence stays outside the published source tree unless it is separately curated and sanitized.

## Non-claims

- This document does not publish or install `lmstudio-managed`.
- No model download, load, unload, inference, or live telemetry action is performed by this documentation slice.
- A requested or applied GPU configuration does not prove complete physical GPU residency.
- Device-only telemetry does not prove process attribution.
- A recommendation catalog does not replace consumer-side capacity, identity, semantic-quality, or lifecycle checks.
- A package pin does not prove live compatibility until the consumer's separately authorized integration gate passes.
