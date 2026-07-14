# LabKit Package Reuse Assessment

## Scope and evidence level

This is a read-only static and offline-test assessment. It does not claim live transport compatibility, model quality, product acceptance, or completed host integration.

Evidence inspected:

- package/build metadata and both public facades;
- request, generation, lifecycle, validation, registry, context, and cache contracts;
- managed text executor and strict structured-vision runner;
- architecture and focused offline tests;
- the host application's existing structured text and vision request seams, read only.

The assessment keeps five outcomes separate: transport, raw parsing, schema validation, semantic quality, and product behavior.

## Executive recommendation

Reuse a small, dependency-light contract kernel. Do not embed the benchmark harness or strict-vision experiment controller in the host application.

Dependency direction must be one-way:

```text
host application -> LabKit contract kernel
host-owned adapters -> host transport, lifecycle, cancellation, persistence, UI
LabKit -X-> host application
```

The host application must never be imported by LabKit. Host-specific prompts, IDs, timestamps, ordering, persistence, retries, cancellation, model selection, and user-facing fallback remain host-owned.

## Classification

### Direct reuse

| LabKit seam | Exact reusable contracts | Why direct | Boundary |
|---|---|---|---|
| Request DTOs | `TextInput`, `ImageInput`, `ChatMessage`, `RequestEnvelope`, `ExecutionOptions`, `RequestPlan`, `RequestResult` in `lmstudio_labkit/requests.py` | Frozen DTOs, no host imports, privacy-safe metadata, text/image/chat shapes | Use DTOs as interchange objects; do not make them the host's persistence model |
| Response contract core | `ResponseContract.mode`, `schema`, `expected_ids`, `id_paths`, `id_field_names`, `preserve_order`, language policy, and safe metadata | Expresses API-bound schema and deterministic invariants without transport | Host builds task-specific contracts and owns business meaning |
| Conservative JSON parsing | `parse_json_response`, `JsonNormalizationResult`, `JsonParseStage` in `lmstudio_labkit/json_normalization.py` | Pure, auditable, separates raw parse from a narrowly allowed fence unwrap, performs no semantic repair | Default to `strict`; normalization is a separately reported parse path, not schema or semantic success |
| Generic schema builders | `build_simple_flat_schema`, `build_blocks_schema` in `lmstudio_labkit/schema_builders.py` | Pure JSON Schema construction; hardened block variant binds exact IDs by position | Host wraps the returned schema in its provider request format and owns schema versioning |
| Structural validation primitives | `validate_json_schema`, `validate_exact_ids`, `collect_ids_by_path`, `validate_finish_reason`, `ValidationResult`, `ValidationSummary` in `lmstudio_labkit/validation.py` | Pure, deterministic checks that distinguish parse/schema/ID/finish failures | Treat the in-tree validator as the supported schema-keyword subset, not a complete JSON Schema implementation |
| Lifecycle policy | `LoadConfig`, `LoadedInstance`, `ObservedModelState`, `LifecycleDecision`, `decide_lifecycle_action`, `decide_unload_action`, `classify_load_timeout_reconcile` in `libs/lmstudio_managed/lifecycle/` | Side-effect-free ownership and compatibility decisions; architecture tests enforce a pure-local boundary | Host observes reality and executes decisions; ownership tokens stay host-owned |
| Context fit | `ContextFitResult`, `evaluate_context_fit` in `tools/lmstudio_lab/context_fit.py` | Small pure budget calculation with explicit safety ratio | Repackage into the contract kernel before depending on it; its current `tools` location is not a stable production API |
| Output budget observation | `AdaptiveOutputBudgetPolicy`, `observe_output_budget`, `decide_output_budget` in `lmstudio_labkit/output_budget.py` | Pure bounded decision logic already used by the managed executor | Host controls retry budget, cancellation, and whether a second call is product-safe |

### Reuse through host adapters

| LabKit seam | Classification | Required adapter seam | Reason |
|---|---|---|---|
| `ManagedLMStudioExecutor` | Adapt | Host implements a request transport/lifecycle port and maps host requests to `RequestPlan` | Current executor is synchronous, text-only, OpenAI-compatible only, structured-JSON only, temperature zero, parallel one, fixed context tiers, requires initially empty state, and owns load/cleanup per request or session |
| `ManagedHostRunner` protocol | Adapt | Implement with host-native async transport, cancellation, timeout, readiness, lifecycle ownership, and error taxonomy | The protocol is a useful narrow test seam, but its synchronous method set does not cover host product behavior |
| `ManagedLMStudioTransport` | Adapt | Translate `ManagedExecutionResult` into host result/error objects; parse and validate afterward | It returns raw text plus privacy-safe metrics but does not establish semantic acceptance |
| `ResponseContract` semantic fields | Adapt | Host task policy maps cleanup, terminology, punctuation, paragraphing, language, and manual-review rules | These fields are useful evidence vocabulary but are coupled to lab validators and are not a universal product policy model |
| `lmstudio_labkit.validation` semantic validators | Adapt | Select validators per host task and map warning/fail outcomes into host fallback policy | Mechanical language/quality heuristics are evidence aids; they cannot decide product correctness alone |
| Lifecycle REST clients in `libs/lmstudio_managed/client/` | Adapt | Host transport implements the injected transport and materializes real request bodies | The clients are fake-first/privacy-safe contract clients; the generation client sends request identity hashes rather than production prompt/schema bodies |
| Registry identity DTOs | Adapt | Host-owned model catalog maps its stable model IDs/capabilities to `ModelIdentity`/`ModelCandidate`-like records | Identity/capability vocabulary is reusable; LabKit candidate status and recommendation evidence must not become runtime truth |
| Cache contracts | Adapt | Host context planner maps current/neighbor/chunk/full-recording policy to `StatelessPrefixRequest`, `StatefulRootRequest`, `StatefulBranchRequest`, or `CompactMemoryRequest` | These contracts describe experiments and evidence; they do not prove cache reuse or prescribe product context selection |
| Vision payload and outcome ideas | Adapt | A small host vision adapter constructs multipart messages, binds strict JSON Schema, and reports transport/parse/schema/semantic outcomes separately | The useful seam is the payload/outcome contract, not the strict-vision controller |
| Schema wrapping | Adapt | Host creates `{type: json_schema, json_schema: {name, strict: true, schema}}` around a LabKit schema | LabKit schema builders return inner schemas while existing host clients accept the full provider response format |

### Exclude from host runtime

| Area | Examples | Why exclude |
|---|---|---|
| Benchmark orchestration | `benchmarks.py`, `suites.py`, `datasets.py`, `artifacts.py`, `reports.py`, `review_pack.py`, `snapshots.py`, CLI and matrix runners | Experiment planning, artifact writing, reporting, and resume behavior are not request-core responsibilities |
| Strict-vision controllers | `StrictStructuredVisionRunner`, launch/continuation manifests and controllers in `strict_vision.py` | Large experiment-specific model allowlists, fixture manifests, owner-only forensics, preflight gates, global-zero assumptions, and launch accounting |
| Lab host implementation | `LocalLMStudioHostRunner` | Useful for bounded experiments, but duplicates host networking/lifecycle and would bypass host cancellation, queue, ownership, and error handling |
| Candidate/recommendation registry | candidate intake/execution, structured matrix, recommendation drafts and route guidance | Evidence and admission records are lab artifacts, not dynamic product configuration |
| Lab tools | `tools/lmstudio_lab/**` except the pure context-fit function after relocation | Config parsing, probes, model acquisition, live smoke, metrics/report writing, and cache-plan generation are experiment scaffolding |
| Failure forensics and private artifact capture | `failure_forensics.py` and strict-vision capture machinery | Owner-only experiment diagnostics have different retention, privacy, and support obligations from product telemetry |
| Generic host adapter facade | `HostApplicationAdapter.consume_report` in `adapters.py` | It selects a benchmark model and consumes Markdown reports; it is not the request execution seam needed by a host application |

## Proposed adapter seams

These are architecture seams, not an implementation proposal.

1. **Host request mapper**
   - Converts a host operation into `RequestEnvelope` + `ResponseContract` + `ExecutionOptions`.
   - Keeps prompts, source records, chunk IDs, timestamps, and persistence objects in host memory only.

2. **Structured transport port**
   - Accepts model ID, messages, full API-bound response format, output budget, timeout, and optional image parts.
   - Is async/cancellable in the host.
   - Returns the untouched response surface, finish reason, usage, and typed transport error.

3. **Lifecycle port**
   - Observes loaded instances, applies pure LabKit lifecycle decisions, and returns an ownership handle.
   - Releases only instances owned by that handle; it never assumes global zero unless the host operation explicitly reserves the runtime.

4. **Validation pipeline**
   - Stage A: transport.
   - Stage B: untouched raw JSON parse.
   - Stage C: optional bounded normalization, reported separately.
   - Stage D: schema and exact ID/order validation.
   - Stage E: task-specific semantic checks and, where needed, human review.
   - Stage F: host product decision, fallback, and persistence.

5. **Context planner**
   - Host chooses current-only, boundary-neighbor, adjacent-chunk, compact-memory, or full-recording context.
   - LabKit only evaluates fit and carries privacy-safe context/cache evidence.

6. **Registry adapter**
   - Maps host configuration to stable package-level model identity/capability records.
   - Lab candidate recommendations remain evidence inputs, never automatic runtime promotion.

## Packaging and import risks

1. The wheel currently publishes three top-level trees: `lmstudio_labkit`, `libs/lmstudio_managed`, and `tools/lmstudio_lab`. `libs.lmstudio_managed` and `tools.lmstudio_lab` expose repository layout as import API.
2. The `lmstudio_labkit` facade eagerly re-exports benchmark, live bridge, managed execution, strict vision, artifact, and report symbols. A host importing one DTO receives a broad and unstable surface.
3. The project is alpha (`0.1.0a0`); public compatibility is not yet demonstrated by semantic-version guarantees.
4. Core request and lifecycle contracts are mostly standard-library-only, but the wheel requires the LM Studio SDK, Pillow, and YAML for all consumers. This unnecessarily couples a host to lab dependencies.
5. The pure context-fit helper lives under `tools`, while registry and lifecycle contracts live under `libs`; this prevents one obvious stable package namespace.
6. `ResponseContract` mixes universal response structure with experiment-specific quality policy. Depending on the entire dataclass would couple host product policy to lab evolution.
7. The custom schema validator implements a deliberate subset. Unsupported schema keywords can be silently treated as unconstrained, so accepted schemas must be limited to the tested subset or validated by a complete host-side engine.
8. Strict vision is a very large module that combines payload construction, fixture verification, lifecycle, private captures, semantic grounding, and launch control. Importing its controller would couple product behavior to experiment policy.
9. Static inspection found no host-application imports in LabKit, and the managed-library architecture test forbids host, UI, HTTP-library, and lab-tool imports. Preserve and expand this direction guard.
10. Parallel copies of managed/lab modules exist in the separately inspected source tree and already show drift in selected registry/tool files. Copy-based integration would recreate split ownership; use one installed package plus host adapters instead.

## Smallest extraction strategy

1. Define one stable `lmstudio_labkit.core` surface containing only:
   - request/result DTOs and safe hashing;
   - response contract structural fields;
   - JSON normalization;
   - tested schema builders;
   - structural validators;
   - lifecycle state/policy;
   - context-fit and bounded output-budget decisions.
2. Define `lmstudio_labkit.ports` with protocols only. The host implements transport, lifecycle execution, cancellation, image materialization, registry mapping, and persistence.
3. Keep `lmstudio_labkit.lab` or an optional extra for benchmarks, strict-vision controllers, artifacts, reports, datasets, forensics, and live runners.
4. Make the host depend on the package contract kernel. Never add host imports, host field names, host prompts, or host persistence types to LabKit.
5. Add import-boundary tests for the new core surface and a focused compatibility test that uses a fake host adapter. Live integration remains a later explicit gate.

This is the smallest safe route because it reuses already-tested pure contracts while avoiding a second transport stack, duplicate lifecycle ownership, and experiment-policy leakage into product runtime.

## Evidence map

- Public facade breadth: `lmstudio_labkit/__init__.py`.
- Wheel topology and dependencies: `pyproject.toml`.
- Request/privacy contracts: `lmstudio_labkit/requests.py`; facade privacy tests in `tests/libs/test_lmstudio_labkit_public_facade.py`.
- Parsing and validation separation: `lmstudio_labkit/json_normalization.py`, `lmstudio_labkit/validation.py` and focused tests under `tests/lmstudio_labkit/`.
- API-bound strict schema payload: `lmstudio_labkit/managed_executor.py` and `lmstudio_labkit/strict_vision.py`; exact payload assertions in `tests/lmstudio_labkit/test_managed_executor_mocked.py` and `test_strict_structured_vision_runner.py`.
- Lifecycle purity and ownership: `libs/lmstudio_managed/lifecycle/`; import guard in `tests/architecture/test_lmstudio_managed_boundaries.py`.
- Lab-only boundary: `tests/architecture/test_lmstudio_lab_core_contracts.py`.
- Host source inspection confirmed existing provider payload, structured text, and structured vision seams, but those private implementation paths and names are intentionally not reproduced here.

## Non-claims

- No live endpoint was called.
- No model was loaded, downloaded, or benchmarked.
- No transport compatibility or throughput claim was established.
- Schema validity is not claimed to prove semantic quality.
- No host integration, prompt change, migration, commit, or push is proposed as completed.
