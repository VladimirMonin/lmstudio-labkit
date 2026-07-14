# Adaptive Local Request Product Architecture

Date: 2026-07-13

Status: proposed architecture for owner approval before implementation. This document does not approve a model, authorize implementation, or authorize live local/cloud execution.

Machine-readable companion: `experiments/lmstudio/results_summaries/2026-07-13_adaptive_local_request_product_architecture.json`.

## Executive decision

Approve one application-owned request architecture with these boundaries:

1. A versioned task profile defines prompt, context, response, validation, fallback, retry, and capability requirements before a provider is selected.
2. Local and cloud adapters are transport-only. Local execution additionally uses host-owned runtime discovery, lifecycle, hardware, and exact-token ports.
3. Auto model selection is limited to exact discovered identities intersected with a product-owned approved task-profile catalog and a platform-specific memory verdict.
4. Every local request uses conservative pre-load planning followed by a loaded-instance exact prompt-token gate. Only the formatted-prompt count is exact until other overhead is observed or calibrated.
5. Output budget increases only on independent truncation evidence. Transport, structural, and budget retries share one logical call ceiling.
6. Structured acceptance preserves separate transport, raw-parse, full-schema, business-identity, semantic, and product-behavior outcomes.
7. Full text remains authoritative in storage but is retired as repeated per-chunk context. A current provenance-bound summary artifact may be consumed only by a task profile that explicitly permits it.
8. Microphone input is classified before prompt selection into ordinary dictation cleanup or anchored `MODEL:` command mode. The modes have separate prompts, response contracts, artifacts, fallback, and clipboard behavior.

The architecture is coherent enough to approve for staged offline implementation, but production promotion remains blocked by the owner decisions and evidence gates in this document.

## Evidence boundary

The synthesis combines:

- static read-only host request, prompt, persistence, and provider contracts;
- retained exact-token evidence for 80 frozen requests over four loaded-instance bindings, with formatted prompts ranging from 925 to 12,797 tokens;
- a 202-call structured context study on one recording and one selected model;
- a bounded 40-call structured vision closure over four models and four fixtures;
- five runtime-unexecuted architecture recommendations and a red-team correction pass.

Evidence labels:

- **exact:** observed for the exact stated artifact, runtime, request, or source contract;
- **estimate:** a conservative calculation, never relabeled as an observation;
- **bounded executed:** real retained execution with limited denominators and no general product admission;
- **runtime-unexecuted:** proposed product behavior not exercised end to end.

No live request, model operation, cloud call, tokenizer capture, migration, host edit, commit, or push was performed for this synthesis.

## Decision matrix

| Concern | Approved architecture | Evidence class | Not approved / fail-closed behavior |
|---|---|---|---|
| Approval unit | Versioned task profile bound to exact model identity, capabilities, context, concurrency, and evidence | Runtime-unexecuted policy informed by static identity contracts | Model family, parameter count, filename, file size, or lab candidate status as production approval |
| Auto recommendation | Hard-filter approved catalog × exact runtime identity × capability × context shape × memory verdict, then rank | Runtime-unexecuted | Guessing on missing digest, quantization, metrics, or task evidence |
| Manual selection | Show only approved profiles whose exact installed identity is reconciled; retain typed unavailable reasons | Runtime-unexecuted | Manual bypass of identity, capability, or hard memory failure |
| CUDA resources | Evaluate device VRAM and host RAM independently with absolute and proportional reserves | Static design; current multi-device attribution incomplete | Summing GPUs without proven placement or treating unused VRAM as RAM |
| Apple resources | Treat unified memory as one pool; require a verified adapter or pre-approved equivalent observed envelope | Runtime-unexecuted; adapter unresolved | General Apple Auto recommendation from overlapping or unverified counters |
| Request contract | One application-owned `TaskRequest` with task, manifest, rendered messages, schema, context, budgets, digests, validators, and fallback | Static source contract plus bounded schema evidence | Provider adapter choosing prompts, schemas, target language, validation, or fallback |
| Structured schema | Compact generic closed schema; exact IDs/count/order validated after generation | Stronger bounded executed evidence | Request-specific positional `const` grammar; silent schema rewrite |
| Parsing | Untouched raw JSON is the native structured success path; normalization is a separate non-raw outcome | Static and offline-tested primitives | Fence stripping, embedded-object extraction, repair, coercion, or defaults counted as native success |
| Validation | Transport → completion → raw parse → complete local schema → identity → semantics → commit fence → atomic persistence/read-back | Target architecture; current host is incomplete | API-bound schema presence described as full post-response validation |
| Context planning | Canonical task assembly, conservative estimate, materialization, exact loaded-instance prompt count, then generation | Exact retained token method; host flow runtime-unexecuted | Generating because an estimate alone fits |
| Output budget | Task-specific bounded stages; escalate only on independent truncation; one cumulative model-call ceiling | Bounded executed failure evidence; exact stage values provisional | More tokens for complete malformed JSON, schema/identity/semantic failure, repetition, or reasoning leakage |
| Per-chunk context | Current target plus task-declared reference-only context; never repeated full text by default | Bounded executed; task defaults remain provisional | Default full-recording-per-chunk context or reference units appearing as output targets |
| Summary | Immutable versioned summary artifacts with source binding, lifecycle, coverage, validation, and current projection | Runtime-unexecuted; current storage is only reserved | Bare summary string as authority, fallback, or prompt-eligible artifact |
| `full_text` | Retain in storage/search/export; deprecate as prompt context with explicit legacy inventory and no alias | Static source plus bounded context evidence | Deleting authoritative text or silently mapping `full_text` to a summary |
| Local/cloud parity | Same task, messages, schema, validators, budgets, and product outcomes above transport adapters | Static source plumbing; parity tests not yet executed | Structured-to-plain silent downgrade or provider-specific business contract |
| Microphone dictation | Existing small cleanup behavior initially; current capture only; original transcript may be explicit degraded fallback | Exact current source contract; structured migration runtime-unexecuted | Command behavior folded into cleanup prompt or hidden summary context |
| Microphone command | Deterministic anchored `MODEL:` classification; strict `{answer_text}` envelope; separate command artifact and plain answer projections | Runtime-unexecuted | Writing command answer to `postprocessed_text`/summary, or pasting malformed/fallback command text |
| Rollback | Becomes configuration-driven only after kill switch, request-generation fence, accepted-attempt traceability, and readable versions exist | Runtime-unexecuted correction | Claiming current rollback is configuration-only |
| Package reuse | Candidate dependency-light core plus protocols, consumed through host adapters | Static/offline assessment; extraction not implemented | Importing benchmark/strict-vision controllers or copying package code into the host |

## Canonical contracts

### Task profile

A product-owned `ApprovedTaskProfile` is the approval and policy unit. It binds:

- task kind and contract version;
- prompt-manifest and response-contract versions;
- required capabilities and endpoint family;
- exact model identity requirements and approved context/concurrency shapes;
- context policy and summary requirement;
- output stages, hard maximum, timeout, and total call ceiling;
- exact-tokenization mode;
- validator and fallback policies;
- semantic/product evidence references;
- platform memory envelopes and whether conservative estimate-only Auto is allowed.

Lab candidate metadata and benchmark ranking may inform catalog governance but never update the catalog automatically.

### Provider-neutral task request

The application freezes one logical request before transport selection:

```text
request identity/generation + task profile + prompt manifest
+ rendered ordered messages + response contract
+ target/reference ownership + optional summary reference
+ translation metadata when applicable
+ output/timeout/call budgets + validation/fallback policy
+ privacy-safe provenance digests
```

All model-visible placeholders must be resolved before hashing, estimating, or exact tokenization. Provider adapters may add only an explicit transport allow-list: endpoint/authentication, provider cache annotations, output-limit spelling, local reasoning controls, timeout/cancellation wiring, and response-envelope extraction.

### Response contracts

Initial native structured task set:

- `postprocess_text_v1` → closed `{text: string}`;
- `postprocess_blocks_v1` → closed `{blocks: [{id: integer, text: string}]}`;
- `translate_text_v1` → the text envelope plus application-owned translation metadata;
- `translate_blocks_v1` → the block envelope plus translation metadata;
- `microphone_command_v1` → closed `{answer_text: string}`.

`legacy_plain_text_v0` remains explicit compatibility behavior only. It is never selected because a structured provider capability is missing.

For block tasks, keep request-specific IDs out of positional schema constants. Bind a compact generic closed grammar and require exact application-side count, unique sequence, original order, strict non-empty strings, and no reference-only IDs.

### Summary reference naming

Use one canonical prompt placeholder, `{document_summary}`, for the provider-neutral manifest contract. A recording-level `SummaryArtifact` is one allowed source for that slot and carries `scope_kind=recording` outside the prompt. Do not introduce a second synonymous `{recording_summary}` placeholder.

The summary slot is `forbidden`, `optional`, or `required` per manifest. Missing optional summary removes the manifest-owned section deterministically. Missing required summary fails planning or schedules a separate prerequisite; it never falls back to full text.

This naming choice requires explicit owner confirmation before implementation because one input report proposed `{recording_summary}`. The architecture otherwise assumes `{document_summary}` as the single canonical token.

## Target data flow

```text
0. Classify product operation
   ├─ microphone dictation
   ├─ microphone MODEL command
   └─ postprocess / translate / summarize / image task

1. Resolve TaskDefinition + PromptManifest + ResponseContract
   -> classify target units and reference-only units
   -> attach current accepted summary only when permitted
   -> freeze rendered messages, schema, policies, and digests

2. Resolve execution candidates
   -> intersect approved task-profile catalog with exact runtime/provider capabilities
   -> for local: reconcile native key, compat ID, artifact digest, format, quantization
   -> for cloud: reconcile provider/model/route capability evidence

3. Preflight planning
   -> conservative token/context estimate per approved candidate/tier
   -> derive task output reserve and total call ceiling
   -> for local: platform memory screen using the same proposed request shape
   -> hard-filter; select one candidate or return typed unavailable

4. Materialize execution boundary
   -> local: load/reuse only a compatible instance under an ownership handle
   -> cloud: bind the approved provider/model/route
   -> read back effective local identity/context before generation

5. Exact/local or conservative/cloud token gate
   -> local: apply exact loaded-instance chat template and tokenize frozen messages
   -> classify schema/non-chat overhead separately as observed or estimated
   -> cloud: use exact provider tokenizer only if equivalently bound; otherwise task-approved conservative mode
   -> if no fit, deterministically shed optional context, split, choose another approved tier, or fail

6. Generate under one logical call counter
   -> increment before every submission
   -> preserve immutable attempts
   -> output escalation only on independent truncation and only if next reserve fits

7. Validate in layers
   -> current generation / cancellation
   -> transport and safe completion
   -> untouched raw parse
   -> complete local closed-schema validation
   -> exact business identity and target/reference ownership
   -> task semantics and protected values
   -> pre-commit generation/cancellation fence

8. Commit product outcome
   -> accepted output + attempt/control/validator state atomically
   -> read back identity, order, state, and accepted attempt
   -> otherwise explicit fallback_original, failed, unavailable, cancelled, abstain, or review_required

9. Release owned local lifecycle resources
   -> never unload externally owned instances
   -> retain privacy-safe categorical/count/digest telemetry only
```

The apparent circular dependency between model recommendation and exact token planning is resolved by two phases: conservative candidate/tier planning before load, then an exact gate after one approved local instance materializes. Exact-gate failure causes deterministic replanning without a generation call.

## Context and output policy

The following values are proposed starting policies, not production admissions:

| Task | Context policy | Initial / next output reserve | Call ceiling | Exact-token mode |
|---|---|---:|---:|---|
| Short microphone cleanup | Current capture only | 512 → 1,024 | 2 | Conservative estimate allowed only for short bounded requests below the approved degraded threshold |
| Long block cleanup | Current targets + reference-only boundary tail/head; summary optional only when manifest permits | 1,024 → 2,048 → 4,096 | 3 | Exact required; 4,096 remains unqualified |
| Per-chunk summary | Current chunk only; targeted boundary fallback requires a new plan | 512 → 1,024 | 2 | Exact required for long/near-budget input |
| Direct recording summary | Complete authoritative source once | 1,024 → 2,048 | 2 | Exact required |
| Hierarchical synthesis | Ordered accepted child summaries | 1,024 → 2,048 → 4,096 | 3 | Exact required; 4,096 remains unqualified |
| Generic self-contained transform | Current input only | 512 → 1,024 → 2,048 | 3 | Conservative mode only for short bounded requests |
| Image analysis | Current image + task schema | 512 → 1,024 | 2 | Provider/runtime-specific planning; image bytes are not text-token estimates |
| Microphone command | Current command text only by default | Owner decision required; must remain within interactive ceiling | 2 proposed | Conservative short-request mode unless an exact tokenizer is available |

Independent truncation means explicit `finish_reason=length`, or absent finish reason with completion usage at the configured cap. An explicit normal stop wins over cap equality. A normal stop is not sufficient when repetition/reasoning leakage or other completion gates fail.

## Summary lifecycle and `full_text` retirement

### Summary artifact

A canonical summary is an immutable versioned artifact, not the existing bare string projection. It binds:

- artifact and source identity, source layer, revision, digest, exact ordered coverage;
- direct or hierarchical strategy and ordered child provenance;
- task, prompt, schema, validator, provider/model/runtime versions;
- token/usage evidence labels;
- separate transport, parse, schema, semantic, coverage, and product verdicts;
- request generation, immutable attempt, current/stale/superseded lifecycle;
- structured payload plus deterministic display/search projection.

A direct recording summary is eligible only after exact fit of the complete authoritative source and output reserve. Otherwise use ordered non-lossy leaf ranges and hierarchical synthesis. A recording artifact cannot become current until every leaf range is covered and accepted in exact order.

### Storage, FTS, and export

- Keep raw/full text, accepted postprocessed text, blocks, timestamps, source media references, and raw-text search/export unchanged.
- Use the existing summary column only as a temporary projection of the single current accepted recording artifact.
- Exclude stale, failed, partial, and superseded summaries from current-summary FTS and prompt injection.
- Import legacy bare summaries as `legacy_unverified` or compatibility projections; they are not prompt-eligible by default.
- Add a separate summary export surface with source revision, strategy, artifact version, and staleness.

### Legacy prompt retirement

1. Inventory `{full_text}` usage by local prompt identity/digest without publishing content.
2. Add summary artifact ownership and read-back before adding summary consumption.
3. Add `{document_summary}` with explicit requirement metadata; never alias it to `{full_text}`.
4. Keep existing `{full_text}` prompts in an explicit deprecated compatibility mode.
5. Migrate one task contract at a time with reversible prompt revisions.
6. Remove `{full_text}` from the accepted registry only after inventory is zero or explicitly waived.

Correctness cannot depend on prefix/KV cache reuse. Cache counters may be observed as an optimization only.

## Microphone dual mode

Classification occurs before prompt selection:

- Preserve the original transcript.
- Skip leading Unicode whitespace only for detection.
- Match ASCII `MODEL` case-insensitively at the first non-whitespace position, optional horizontal whitespace, then required `:` or `：`.
- Extract the original suffix and trim outer whitespace only.
- An empty suffix is `command_invalid`; it does not fall back to dictation.

Dictation keeps the existing simple cleanup path initially. A later structured migration may use `{text}`, but the original transcript remains the explicit degraded fallback.

Command mode uses a separate prompt and `{answer_text}` schema. It sends no trigger, cleanup prompt, full recording, document summary, or clipboard content by default. After strict raw/schema/semantic validation, the application materializes separate display, copy, and paste projections. Command failure has no transcript-as-answer fallback and performs no copy/paste. Command results use a distinct artifact and never mutate transcription source, `postprocessed_text`, or summary state.

Local and cloud command routes share classification, messages, schema, validation, output budget, and product behavior. A schema-incapable route is unsupported; no prompt-only JSON downgrade is allowed.

## Candidate package boundary

Treat a dependency-light LabKit core as a candidate architecture, not an existing stable product API. Extract or adapt only:

- privacy-sanitized request/result structural DTOs;
- raw JSON parse outcomes;
- compact schema builders excluding positional-const host use;
- structural validation with a complete validator or fail-closed keyword allow-list;
- lifecycle decision types and pure policy;
- context-fit and output-budget decisions;
- protocols for transport, lifecycle execution, tokenization, metrics, capability, and persistence.

Keep benchmark orchestration, strict-vision controllers, live runners, candidate registries, reports, forensics, and host implementations outside the product core. The host owns prompts, source/persistence types, IDs/timestamps, cancellation, UI, catalog governance, semantic policy, and side effects.

## Staged migration

### Stage 0 — owner policy closure

Approve the canonical summary placeholder, identifier/digest telemetry policy, complete-schema validation strategy, task output/call defaults, headroom policy, catalog governance, and command persistence/retention behavior.

Gate: every decision has an owner, versioned policy record, and fail-closed default.

### Stage 1 — contract kernel and boundaries

Create the candidate dependency-light core and protocol-only ports. Sanitize identifiers before telemetry. Exclude positional-const grammar and lab controllers.

Gate: install/import compatibility, dependency-direction tests, no host imports, and no broad optional lab dependencies for core consumers.

### Stage 2 — task manifests and adapter parity

Introduce task definitions, prompt manifests, canonical placeholders, response contracts, capability records, and fake local/cloud adapters without changing current output.

Gate: exact rendered-message/schema/budget parity except a closed transport allow-list; no unknown placeholder or silent structured downgrade.

### Stage 3 — validator and control plane

Add untouched raw parsing, complete local schema validation, exact identity/order, immutable attempts, generation/cancellation fences, one call counter, explicit fallback states, atomic persistence/recovery, and read-back.

Gate: adversarial block/text/command fixtures, retry interactions, persistence failure injection, stale completion, export, and rollback tests all pass offline.

### Stage 4 — local selection, lifecycle, and token planning

Add approved catalog, runtime identity reconciliation, hardware adapters, memory evaluator, lifecycle ownership, conservative estimate, exact loaded-instance token gate, and usage reconciliation.

Gate: fake/runtime-simulated state transitions prove no unapproved selection, incompatible reuse, unsafe unload, estimate-as-exact promotion, or generation after exact no-fit.

### Stage 5 — structured text and translation shadow paths

Run structured text/blocks and one translation target/shape only after separate live authorization. Candidate output remains non-persistent and non-user-visible.

Gate: task-specific transport, structure, semantic, latency, and fallback evidence; no cross-task admission.

### Stage 6 — summary artifact lifecycle

Implement direct/hierarchical planning, immutable artifact persistence, staleness/current projection, FTS, transfer/export, complete coverage, resume, and read-back. Summary consumption remains disabled until this stage passes.

Gate: fake-client end-to-end direct/hierarchical tests and source-retention/non-loss guarantees.

### Stage 7 — microphone command shadow mode

Add deterministic classification, separate command prompt/schema/artifact/events/projections, and zero-side-effect failure behavior. Keep ordinary dictation unchanged.

Gate: classifier matrix, provider parity, malformed-output rejection, cancellation fences, clipboard zero-side-effect failures, and command artifact read-back.

### Stage 8 — task canaries and legacy retirement

Under separate owner authorization, canary one task/route/shape at a time. Only after task evidence passes may summary injection or user-visible command output be enabled. Retire `{full_text}` and prompt inference only after custom prompt disposition and rollback readiness.

Gate: contract kill switch, traceable accepted attempt, readable schema/validator versions, task-specific thresholds, and proven rollback.

## Unresolved owner decisions

| ID | Decision owner must make | Recommended default | Why unresolved / blocking effect |
|---|---|---|---|
| O1 | Canonical summary placeholder | Use `{document_summary}` only; recording scope lives in artifact metadata | One report proposed `{recording_summary}`; two synonyms would create migration ambiguity. Blocks manifest implementation. |
| O2 | Production approved task-profile catalog governance | Signed/versioned host-owned catalog with explicit review and no lab auto-promotion | This analysis approves no model or profile. Blocks Auto selection. |
| O3 | Artifact digest resolution | Require privacy-safe immutable digest or trusted manifest digest | Current discovery does not prove this for every installation. Blocks exact Auto identity. |
| O4 | Identifier and digest telemetry policy | Persist counts/categories and keyed digests; never raw request/cell/expected IDs by default | Current LabKit safe metadata can expose identifiers. Blocks product telemetry reuse. |
| O5 | Complete JSON Schema strategy | Use a complete validator, or a closed tested keyword allow-list that rejects unknown keywords | Current host parser and LabKit subset are insufficient. Blocks native structured promotion. |
| O6 | Output stages, 50% degraded threshold, safety ratio, and call ceilings | Start with the proposed bounded values only in offline/shadow configuration | Values are evidence-informed but runtime-unexecuted product policy. Blocks production defaults. |
| O7 | Memory headroom and estimate policy | Version absolute + proportional reserves by platform/profile | No universal thresholds were established. Blocks estimate-based Auto. |
| O8 | Apple MLX/Metal metrics | No general Apple Auto recommendation until adapter semantics are verified | Allocation/cache/process attribution is unresolved. |
| O9 | CUDA multi-device/process attribution | Restrict Auto to proven single-device profiles until placement evidence exists | Current sampling is insufficient for multi-GPU/MIG/sharding. |
| O10 | Semantic validators and thresholds by task | Fail closed or abstain/review when thresholds are absent | Structure does not establish cleanup, translation, command, summary, or vision quality. Blocks canary promotion. |
| O11 | Command history persistence and retention | Shadow artifacts only until transaction/read-back and retention are approved | Command answers must not overload transcription fields. Blocks persistent command history. |
| O12 | Legacy custom prompt disposition | Explicit native, legacy, or blocked manifest per prompt | Filename/placeholder inference and `{full_text}` cannot be retired safely without inventory. |

## Proposed implementation cards

These are proposed cards only; none is dispatched by this report.

1. **Approve policy records and schema vocabulary**
   - Own O1–O7 and define versioned task/profile/telemetry policy documents.
   - Done: JSON Schemas and decision records parse; unknown policy states fail closed.

2. **Extract candidate core and ports**
   - Create dependency-light structural DTOs, parse outcomes, generic schemas, lifecycle/context/output decisions, and protocol-only ports.
   - Done: install/import and architecture tests prove one-way dependency; identifier sanitization tests pass.

3. **Implement task definitions, manifests, and provider parity fixtures**
   - Add canonical placeholders, explicit legacy mode, translation metadata, capability negotiation, and fake adapters.
   - Done: logical messages/schema/budgets match across adapters except the transport allow-list; no silent downgrade.

4. **Implement full validation and logical-attempt control plane**
   - Add complete schema validation, exact block identity/order, immutable attempts, cumulative call counter, stale/cancel fences, and explicit outcomes.
   - Done: adversarial response matrix and retry-interaction tests pass.

5. **Make persistence atomic or recoverable**
   - Bind aggregate/per-unit writes, accepted attempt, validators, fallback, export, and read-back.
   - Done: failure injection proves deterministic recovery and exact identity/order after read-back.

6. **Implement approved catalog and local recommendation adapters**
   - Add identity reconciliation, artifact digest, CUDA/Apple metrics adapters, memory envelopes, reason codes, and Auto/manual presenter.
   - Done: all missing/ambiguous/insufficient paths return typed unavailable; no unapproved fallback.

7. **Implement local lifecycle and exact-token planner**
   - Add compatible materialization, ownership, loaded-instance template/tokenize binding, overhead labels, exact no-fit replan, and truncation-only budgeting.
   - Done: simulated and offline integration tests prove cleanup and call-ceiling behavior.

8. **Implement summary artifact lifecycle**
   - Add direct/hierarchical planner, immutable artifacts, coverage, staleness/current projection, FTS, transfer/export, resume, and non-loss tests.
   - Done: fake-client end-to-end paths pass; summary injection remains disabled.

9. **Implement microphone command shadow path**
   - Add deterministic classifier, command manifest/schema, separate artifact/event/projections, and zero clipboard side effects on failure.
   - Done: classifier, parity, validation, cancellation, persistence-disabled, and rollback tests pass.

10. **Inventory and migrate legacy prompts**
    - Classify custom prompts without publishing content; add compatibility previews and `{full_text}` deprecation state.
    - Done: every prompt has native/legacy/blocked disposition and rollback metadata.

11. **Design separately authorized shadow and canary evidence plan**
    - Define exact tasks, models/routes, denominators, privacy-safe metrics, semantic review, stop gates, and rollback.
    - Done: owner approval exists before any live request; no implementation card itself performs live execution.

## Approval gates and non-claims

Architecture approval authorizes only staged offline design/implementation after the owner decisions are closed. It does not establish:

- any approved model, task profile, context size, concurrency, headroom threshold, or rollout percentage;
- end-to-end host integration, exact host-request token counts, or platform memory calibration;
- Apple MLX/Metal or multi-GPU recommendation safety;
- structured short-microphone quality, command answer quality, translation quality, summary quality, or vision admission;
- complete local/cloud capability parity;
- transactional persistence, rollback, cache reuse, or production readiness;
- permission for live inference, model load/download, cloud calls, migration, commit, or push.
