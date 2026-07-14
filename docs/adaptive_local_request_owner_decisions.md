# Adaptive Local Request Owner Decisions

Date: 2026-07-13

Status: recommended Stage-0 decision register for owner approval. This document closes policy choices for offline implementation; it does not approve a model or task profile and does not authorize implementation, migration, model operations, local or cloud requests, commit, or push.

Machine-readable companion: `experiments/lmstudio/results_summaries/2026-07-13_adaptive_local_request_owner_decisions.json`.

## Executive recommendation

Approve the application-owned adaptive request architecture now, with three practical boundaries:

1. Build one provider-neutral task contract and layered validator before adding selection, lifecycle, summary, or command features.
2. Treat numeric token, memory, semantic, and rollout thresholds as versioned startup configuration requiring matching shadow evidence before production promotion.
3. Return typed unavailable/review/fallback outcomes whenever exact identity, resource attribution, evaluator authority, or platform capability is missing. Do not guess or silently downgrade.

The only capability-level blocks are general Apple Auto without a verified adapter or exact trusted envelope, multi-device CUDA Auto without exact placement evidence, production semantic admission without task-specific shadow/canary evidence, and automatic acceptance of arbitrary microphone commands without an external authority such as explicit user confirmation.

## Evidence boundary

### Current static contract

- The host currently infers prompt behavior from filenames/placeholders, has plain-text and partially structured paths, and has no complete provider-neutral task manifest, complete JSON Schema validator, approved profile catalog, immutable summary lifecycle, or separate command artifact.
- Native and OpenAI-compatible model discovery are separate planes. Current identity facts do not provide an immutable artifact digest on every installation.
- Current resource telemetry does not prove multi-device placement or exact process attribution, and no verified Apple shared-memory adapter for the external runtime exists.

### Retained executed evidence

- Exact formatted-prompt token counts exist for 80 frozen requests across four loaded-instance bindings, ranging from 925 to 12,797 tokens. They are exact only for those bindings.
- A heterogeneous 202-call text/context study supports retiring repeated full-text-per-chunk context and keeping transport/structure/semantics separate, but it does not admit a production task.
- A bounded 40-call vision run achieved raw/schema success for 36/36 applicable calls while semantic dimensions remained mixed. Schema success is therefore not semantic acceptance.

### Recommendation versus live-unverified assumption

All target host behavior below is runtime-unexecuted. The architecture and fail-closed defaults are recommendations. Artifact resolution, resource envelopes, provider capabilities, semantic thresholds, persistence/read-back, rollback under real concurrency, and latency remain live- or platform-unverified until separately authorized evidence exists.

## Decision register

| ID | Status | Recommended default | Rationale | Typed failure behavior | Minimum verification |
|---|---|---|---|---|---|
| O1 | `approve_now` | `{document_summary}` is the only summary placeholder; scope lives in artifact metadata. | One vocabulary avoids alias drift and keeps lossy summary distinct from authoritative full text. | Unknown token, missing required current summary, provenance mismatch, or placeholder leak fails before transport with zero persistence/clipboard effects. | Requirement-level rendering matrix; no-alias; provenance/staleness; local/cloud logical-message parity; generation-fence tests. |
| O2 | `approve_now` | Host-owned versioned integrity-protected `ApprovedTaskProfile` catalog; explicit approval and separate `auto_eligible`; no LabKit auto-promotion. | Approval is task/shape/evidence-specific, not a property of a model family. | Missing, invalid, expired, revoked, unapproved, rollback, or chain-mismatched catalog disables Auto. | Schema/signature/revision-chain tests; atomic activation/read-back; crash recovery; signed higher-revision rollback; proof lab data cannot mutate catalog. |
| O3 | `approve_now` | Bind native key, compat ID, format, verified quantization, and immutable SHA-256 artifact identity from bytes or a trusted signed manifest. | Names, sizes, and loaded-instance IDs are not immutable artifact authority. | Missing/ambiguous facts or unavailable/untrusted/mismatched digest returns typed unavailable; only `identity_exact` reaches Auto. | Each missing/mismatch branch; ambiguous mapping; symlink/out-of-root/TOCTOU rejection; no path leakage; multi-file scope handling. |
| O4 | `approve_now` | Raw identities remain local; exported telemetry uses bounded categories/counts and purpose-separated HMAC-SHA-256 pseudonyms. | Stable raw IDs and unkeyed low-entropy digests are correlatable. | Missing telemetry key omits identity correlation; it never falls back to unkeyed hashing or blocks the product request. | Serialization leak scan; purpose/epoch separation; missing-key behavior; bounded validator errors; retention removal with aggregate preservation. |
| O5 | `approve_now` | JSON Schema Draft 2020-12, complete validator, recursive fail-closed product admission profile, local/preloaded references only, untouched raw JSON. | Provider `strict` claims and current subset validators do not establish complete local validation. | Unknown keyword/dialect, remote or unresolved reference, invalid schema/digest, unavailable validator, invalid raw JSON, or invalid instance fails closed; no repair/coercion/defaulting. | Meta-schema and keyword matrix; boolean schemas; arrays/local refs; deterministic privacy-safe errors; schema success cannot bypass business/semantic/control gates. |
| O6 | `approve_configurable_default` | `0.85` context safety ratio, `256` uncalibrated token margin, `0.50` degraded-estimate threshold, task stages of 512/1,024 for short tasks and bounded 1,024/2,048/4,096 stages for long tasks, with total call ceilings of two or three. Escalate only on independent truncation. | Retained evidence supports bounded planning and disproves “more output tokens means correctness”; exact numeric values are not universal. | Exact-required tasks fail with `exact_tokenization_unavailable`; no fit, missing truncation signal, structural/semantic failure, or exhausted ceiling never widens the budget. | Freeze/invalidation; threshold boundaries; estimate-pass/exact-fail; truncation signal matrix; one cumulative retry counter; no escalation for non-truncation defects. |
| O7 | `approve_configurable_default` | Independent CUDA VRAM and host-RAM gates; Apple as one shared pool. Startup reserves use `max(absolute, proportional)`: CUDA 1 GiB/10%, host RAM 2 GiB/15%, Apple unified 4 GiB/20%, Metal working set 1 GiB/15%. | Static estimates may reject, but current evidence does not establish universal safe headroom. | Missing/stale/ambiguous metrics, insufficient headroom, unattributed peak, incompatible load shape, or cleanup-read-back failure returns unavailable; no optimistic zero/default. | Reserve arithmetic; independent resource gates; stale/unknown metrics; exact envelope binding; cancellation and owned-only cleanup. |
| O8 | `blocked_external_capability` | `apple_auto_enabled=false` unless a verified shared-pool adapter or exact trusted observed envelope matches identity and request shape. | Overlapping MLX/Metal/process/system counters are not yet verified for an external runtime. | Missing pressure, attribution, counters, adapter semantics, or exact envelope returns Apple Auto unavailable; manual selection cannot bypass hard pressure or fit failure. | Adapter counter/reset/overlap tests plus separately authorized exact load/settle/peak/unload evidence. |
| O9 | `approve_now` | CUDA Auto is restricted to one exact physical GPU or one exact MIG instance; never sum devices. Multi-GPU/sharded/layer-split Auto stays disabled. | Current first-device sampling cannot prove placement or per-device peaks. | Unresolved device, missing process binding, ambiguous placement, multi-device use, or missing MIG handle returns unavailable. | Device/MIG identity and process binding; per-device peak fixtures; two-device no-sum regression; cleanup/read-back. |
| O10 | `requires_shadow_calibration` | Approve the layered, task-specific acceptance policy now: deterministic, semantic, and product verdicts remain separate; outcomes are `accepted`, `fallback_original`, `abstain`, `review_required`, `unavailable`, `failed`, or `cancelled`. Keep sample floors and pass thresholds configurable. | Retained transport/structure evidence is heterogeneous and does not establish production semantic admission for any task. | Missing evaluator authority routes to review or unavailable; cleanup/translation may return immutable original; summary/vision never substitute stale/partial artifacts; non-accepted outcomes never count as success. | At least 30 offline fixtures and a frozen rubric before shadow; denominator tests; separately authorized per-task shadow/canary review and stop-gate evidence before production. |
| O11 | `approve_configurable_default` | Bootstrap `disabled`; after offline gates and separate live authorization use `shadow_ephemeral` with no durable history, FTS, export, display, copy, paste, or transcription mutation. | Command candidates need a distinct artifact and privacy/transaction policy; transcription fields are the wrong authority. | Invalid/unsupported/failed/cancelled/stale command has zero user-visible, clipboard, persistence, or transcript side effects. | Classifier and strict-envelope matrix; side-effect fence; database/FTS/export unchanged; kill-switch races; future persistence requires transaction/read-back/retention/delete tests. |
| O12 | `approve_now` | Every prompt has an immutable manifest state: `native`, `legacy`, or `blocked`. Existing unmanifested prompts start legacy; unknown or contradictory prompts are blocked. | Filename and placeholder inference cannot safely confer native structured trust. | Stale inventory, digest mismatch, unknown placeholder, target/schema conflict, missing manifest, or disabled legacy state fails before transport and does not rewrite prompts. | Bundled/custom override inventory; exactly-one-state invariant; placeholder/shape/translation matrix; no auto-promotion; exact-revision rollback and stale-generation tests. |

## Immediate recommended architecture

Use one dependency direction:

```text
host-owned TaskDefinition / PromptManifest / ApprovedTaskProfile
  -> frozen provider-neutral TaskRequest
  -> capability and local identity/resource planning
  -> transport-only local or cloud adapter
  -> immutable RawProviderResult
  -> shared raw/schema/business/semantic/control validator pipeline
  -> typed ProductOutcome
  -> atomic or recoverable persistence and read-back
```

Hard rules:

- Freeze task, rendered messages, schema, ownership, budgets, validators, and digests before provider selection.
- Keep provider adapters transport-only and reject silent structured-to-plain downgrade.
- Pre-screen local candidates conservatively, then read back the loaded instance and run the exact prompt-token gate before generation.
- Use one logical call counter across transport retry, structural retry, and truncation escalation.
- Preserve immutable attempts and recheck request generation immediately before publication.
- Keep full text authoritative. Summary is a versioned derived artifact and is never an automatic fallback.
- Keep dictation cleanup and anchored `MODEL:` command mode separate in prompts, schemas, artifacts, fallback, persistence, and clipboard behavior.

## Staged implementation order

1. **Policy and contract kernel, offline only.** Add versioned enums/DTOs for task definitions, prompt manifests, response contracts, typed outcomes, generations, attempts, and kill-switch state. Add complete schema admission/validation without transport or persistence.
2. **Manifest rendering and fake-adapter parity.** Implement canonical placeholders, native/legacy/blocked prompt states, frozen logical requests, translation metadata, and fake local/cloud payload parity.
3. **Attempt control and persistence.** Add raw parsing, business identity/order, one call counter, cancellation/generation fences, immutable attempts, explicit fallback, atomic/recoverable persistence, and read-back.
4. **Catalog and local planning.** Add integrity-protected catalog loading, exact identity resolver, capability records, resource adapters, lifecycle ownership, conservative planning, exact loaded-instance token gate, and typed unavailable outcomes using fakes/simulations first.
5. **Task-specific offline paths.** Harden one structured cleanup task before translation; implement summary artifact lifecycle before summary consumption; implement command classification/artifact boundaries while command execution remains disabled.
6. **Separately authorized evidence.** Shadow one exact task/profile/route/shape at a time, then canary only after task-specific semantic, latency, persistence, rollback, and stop-gate thresholds pass.
7. **Legacy retirement.** Retire `{full_text}` prompt use and inference only after installed prompt inventory is resolved and rollback metadata exists.

## Smallest next implementation slice

Implement an offline, dependency-light **contract-admission kernel** for one task, `postprocess_text_v1`, with no provider, model discovery, lifecycle, persistence migration, or host behavior change.

The slice should contain only:

- immutable `TaskDefinition`, `PromptManifest`, `ResponseContract`, `LogicalAttempt`, and typed `ProductOutcome` records;
- `native`/`legacy`/`blocked` manifest admission and the canonical `{document_summary}` vocabulary with no `{full_text}` alias;
- Draft 2020-12 schema admission plus complete local validation of untouched raw JSON;
- a generation fence and one cumulative call-counter decision as pure state transitions;
- fake fixtures proving unknown states/keywords/placeholders fail closed and that non-accepted outcomes cannot publish.

Done means offline tests prove deterministic parse/admission/outcome behavior and the package remains independent of host types and live transports. This slice deliberately excludes adapters, catalog signing, artifact hashing, resource metrics, tokenization, database writes, summary generation, command execution, and all live calls.

## Kill switches and rollback seams

Minimum independent switches:

- `adaptive_request_enabled` — global target path; off returns existing approved behavior or typed unavailable.
- `native_structured_task_enabled[task_contract]` — disables new structured submissions for one task.
- `auto_selection_enabled` — disables Auto without changing approved manual records.
- `estimate_only_token_mode_enabled[profile]` — disables degraded token admission.
- `conservative_resource_estimate_auto_enabled[platform, profile]` — disables estimate-based Auto.
- `apple_auto_enabled` — startup `false` without verified evidence.
- `cuda_multi_device_auto_enabled` — startup `false`.
- `summary_consumption_enabled[manifest]` — startup `false` until lifecycle/read-back gates pass.
- `command_execution_enabled` and `command_persistence_enabled` — startup `false`; persistence is a later independent promotion.
- `legacy_prompt_enabled[manifest]` — reversible per immutable prompt revision.

Every switch change advances the applicable generation so late results are inert. Rollback selects a previously admitted immutable contract/catalog/prompt revision, preserves historical readability and authoritative source data, performs no model-authored repair, and never unloads an externally owned instance.

## Explicit non-goals

This decision register does not:

- approve any model, artifact, task profile, context tier, concurrency shape, language pair, image class, memory envelope, latency ceiling, quality threshold, or rollout percentage;
- prove an artifact resolver, Apple adapter, multi-device placement, provider schema capability, exact host token count, persistence transaction, or rollback under live concurrency;
- authorize model discovery, hashing, loading, inference, cloud calls, tokenizer capture, shadow traffic, canary traffic, migration, implementation cards, commit, or push;
- replace authoritative full text with summary, migrate existing prompts automatically, or persist/show/copy/paste command candidates;
- claim that provider schema enforcement, parse success, or complete schema validation establishes semantic correctness.

## Primary external references

- LM Studio native model inventory: https://lmstudio.ai/docs/developer/rest/list
- LM Studio OpenAI-compatible model list: https://lmstudio.ai/docs/developer/openai-compat/models
- LM Studio loaded-model prompt-token method: https://lmstudio.ai/docs/python/model-info/get-context-length
- JSON Schema Draft 2020-12 core and validation: https://json-schema.org/draft/2020-12/json-schema-core.html and https://json-schema.org/draft/2020-12/json-schema-validation.html
- `python-jsonschema` validation guidance: https://python-jsonschema.readthedocs.io/en/stable/validate/
- NVIDIA NVML device/process/MIG queries: https://docs.nvidia.com/deploy/nvml-api/group__nvmlDeviceQueries.html
- Apple Metal working-set and memory-pressure APIs: https://developer.apple.com/documentation/metal/mtldevice/recommendedmaxworkingsetsize and https://developer.apple.com/documentation/dispatch/dispatchsourcememorypressure
- HMAC and JSON canonicalization: https://www.rfc-editor.org/rfc/rfc2104 and https://www.rfc-editor.org/rfc/rfc8785
- The Update Framework specification: https://theupdateframework.github.io/specification/latest/

External facts and URLs are inherited from the four owner-decision reports retrieved on 2026-07-13 UTC. No external source was contacted by this synthesis.
