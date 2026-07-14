# Provider-neutral prompt and structured task contracts

Date: 2026-07-13

Status: read-only architecture recommendation. The host source and retained LabKit evidence were inspected statically; no model request, provider call, tokenizer capture, model operation, persistence round trip, implementation, commit, or push was performed.

Machine-readable companion: `2026-07-13_provider_neutral_prompt_structured_contracts.json`.

## Decision

Local and cloud execution should share one application-owned `TaskRequest` assembled before provider selection:

```text
task definition + prompt manifest + rendered messages + response contract
+ validation/fallback policy + application-owned invocation metadata
```

A provider adapter may translate only transport concerns: endpoint and authentication, provider-specific cache controls, output-limit spelling, local thinking controls, timeout/cancellation wiring, and response-envelope extraction. It must receive the already selected task contract and must not choose a different prompt, schema, output shape, translation target, validator, or fallback.

The initial task set should be deliberately small:

1. `postprocess_text_v1` -> closed `{text: string}` output;
2. `postprocess_blocks_v1` -> closed `{blocks: [{id, text}]}` output;
3. `translate_text_v1` -> the same text envelope plus required translation metadata;
4. `translate_blocks_v1` -> the same block envelope plus required translation metadata.

Plain free text remains a named compatibility contract, `legacy_plain_text_v0`; it is not an implicit fallback from structured execution. Summary production is a separate future task. An existing, application-owned document summary may be consumed as optional reference context through `{document_summary}`.

## Evidence boundary

### Exact source-contract findings

- The current host routes local and cloud generation through the same OpenAI-compatible chat-completions client. Provider payload builders pass `response_format` unchanged when present and otherwise differ in headers, cache/usage fields, output limits, and local thinking controls.
- Current prompt loading recognizes exactly five placeholders: `{chunk}`, `{blocks_json}`, `{full_text}`, `{clipboard}`, and `{context}`. It infers blocks mode from `{blocks_json}` and supports user prompt files overriding bundled files by filename.
- Current generic text and translation text paths accept free message text without an API-bound schema. Current block processing binds a strict closed JSON Schema, but post-generation parsing does not yet enforce exact sequence, uniqueness, strict string type, or an explicit fallback outcome.
- Current built-in translation behavior encodes its target language in prompt prose rather than application-owned request metadata. There is no provider capability registry that proves strict-schema support for a selected provider/model/route combination.
- Recording, queue, chunk, block, and persistence identities and timestamps are application-owned. Blocks send only an echoed block ID and model-authored text.

### Executed retained evidence

- The structured text context study executed 202 calls on one sanitized recording and one selected model; 199/202 were parseable or practically valid. This is structural/context evidence, not production admission.
- The structured vision closure executed 40/40 authorized calls. All 36 applicable structured calls passed raw JSON and independent schema validation, while semantic dimensions remained mixed. Schema success therefore does not imply semantic or product acceptance.
- The strongest retained block design uses compact generic schemas plus application-side exact ID/order validation. Request-specific positional grammar failed before generation in an earlier bounded path.

### Runtime-unexecuted recommendations

Everything below concerning the new manifests, capability handshake, custom-prompt migration, validators, persistence state, and rollout is proposed architecture. It has not been exercised end to end in the host application.

## Layering and ownership

```text
TaskDefinitionRegistry
  -> PromptManifest + ResponseContract + TaskPolicy
  -> PromptRenderer(values)
  -> TaskRequest(rendered messages, exact schema, metadata digests)
  -> CapabilityNegotiator(provider/model/route)
  -> ProviderAdapter(transport only)
  -> RawProviderResult
  -> SharedValidatorPipeline
  -> Host persistence/fallback decision
```

The dependency direction is one-way: the host application may consume a small LabKit contract kernel through host-owned adapters; LabKit must not import host code, prompts, persistence models, or private field names.

## Provider-neutral request contract

A logical `TaskRequest` should contain these fields before transport selection:

| Field | Contract |
|---|---|
| `request_id`, `request_generation`, `attempt_index` | Application-owned control identity; never model-authored. |
| `task_kind`, `task_version` | Stable task contract, not a provider name or prompt filename. |
| `prompt_manifest_id`, `prompt_manifest_version` | Resolves the prompt text, allowed placeholders, context policy, output contract, and validator policy. |
| `messages` | Fully rendered system/user messages; byte-equivalent logical content across local and cloud, except adapter-added transport annotations. |
| `response_contract_id`, `response_schema` | Exact closed schema and business identity rules. The adapter binds this unchanged when structured output is required. |
| `translation` | Required only for translation tasks; application-owned target/source policy described below. |
| `expected_ids` | Exact ordered application-owned block IDs for block tasks. Not encoded as provider-specific grammar constants by default. |
| `context_policy` | Current-only, boundary-reference, or optional summary-reference. Full-document-per-chunk is not a default. |
| `output_budget`, `timeout`, `total_call_ceiling` | Logical request limits selected before transport. |
| `source_digest`, `prompt_digest`, `schema_digest`, `expected_ids_digest` | Privacy-safe provenance; raw source and prompt are not logged. |
| `validator_version`, `fallback_policy_id` | Stable application policies, independent of provider. |

The provider result returned to the shared validator should preserve raw final content in memory, finish reason, usage, latency, provider/model revision, response-envelope category, and typed transport failure. Provider adapters must not parse task JSON, repair it, coerce values, fill defaults, or persist results.

## Task and response matrix

| Task kind | Required input placeholder | Optional reference placeholders | Structured response | Identity rule | Fallback |
|---|---|---|---|---|---|
| `postprocess_text_v1` | `{chunk}` | `{context}`, `{document_summary}`, `{clipboard}` | `{text: string}` | One application-owned target; no model ID/timestamp | Original target text unchanged |
| `postprocess_blocks_v1` | `{blocks_json}` | `{context}`, `{document_summary}`, `{clipboard}` | `{blocks: [{id, text}]}` | Exact count, unique ID sequence, original order; reference blocks cannot appear | All original target blocks unchanged |
| `translate_text_v1` | `{chunk}` | `{context}`, `{document_summary}`; clipboard only if the manifest explicitly permits it | `{text: string}` | Required translation target metadata; no model ID/timestamp | Original source text unchanged and outcome marked degraded |
| `translate_blocks_v1` | `{blocks_json}` | `{context}`, `{document_summary}`; clipboard only if explicitly permitted | `{blocks: [{id, text}]}` | Translation target plus exact ordered IDs | All original source blocks unchanged and outcome marked degraded |
| `legacy_plain_text_v0` | `{chunk}` | Existing legacy placeholders according to its compatibility profile | Plain message text | No deterministic item identity | Existing caller behavior; never selected as silent structured fallback |

Text and block tasks should use the same response envelopes for cleanup and translation. Translation changes semantic policy and required metadata, not transport or structural shape.

### Closed text schema

```json
{
  "type": "object",
  "required": ["text"],
  "additionalProperties": false,
  "properties": {
    "text": {"type": "string", "minLength": 1}
  }
}
```

### Closed blocks schema

```json
{
  "type": "object",
  "required": ["blocks"],
  "additionalProperties": false,
  "properties": {
    "blocks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "text"],
        "additionalProperties": false,
        "properties": {
          "id": {"type": "integer"},
          "text": {"type": "string", "minLength": 1}
        }
      }
    }
  }
}
```

The runtime schema may bind array count limits derived from the request, but exact IDs and order should remain application-side business checks rather than request-specific positional grammar unless a selected model/route has separately passed that exact grammar profile.

## Prompt manifest

A prompt file should no longer define task behavior by filename or placeholder inference alone. Each built-in prompt and each admitted custom prompt needs a sidecar or registry manifest with:

| Manifest field | Meaning |
|---|---|
| `manifest_id`, `version`, `source` | Stable identity; source is `bundled` or `custom`. |
| `task_kind`, `task_version` | One of the explicit task contracts above. |
| `input_shape` | `text` or `blocks`; it must agree with the required content placeholder. |
| `output_contract_id` | `structured_text_v1`, `structured_blocks_v1`, or explicit `legacy_plain_text_v0`. |
| `required_placeholders`, `optional_placeholders` | Closed allow-list for rendering. Unknown placeholders fail admission. |
| `context_policy` | Which optional reference values may be populated and their target/reference semantics. |
| `translation_policy` | Whether translation metadata is forbidden, optional, or required. |
| `validator_policy_id`, `fallback_policy_id` | Shared post-generation behavior. |
| `schema_digest` | Digest of the exact inner schema expected by the manifest. |
| `compatibility_mode` | `native_v1`, `legacy_text_v0`, or `blocked`. |

Prompt loading validates the manifest and template before a job starts. Rendering accepts a typed value map and fails closed on missing required values, unknown placeholders, incompatible input/output shapes, or a task/manifest mismatch. The renderer should escape data by treating placeholders as message content, never as format instructions supplied by a provider adapter.

## Placeholder policy

Canonical placeholders for new contracts:

| Placeholder | Role | Rules |
|---|---|---|
| `{chunk}` | Current text target | Required for text tasks; mutually exclusive with `{blocks_json}`. |
| `{blocks_json}` | Current target blocks serialized as compact JSON | Required for block tasks; contains application-owned IDs and source text only. |
| `{context}` | Small reference-only boundary context | Optional; must be labeled reference-only by the manifest; never returned as a target. |
| `{document_summary}` | Existing application-owned document/recording summary | Optional; absent renders as an empty/omitted section according to the manifest. It is reference-only, never authority, and must carry a source/version digest outside prompt text. |
| `{clipboard}` | Explicit user-selected auxiliary context | Optional and task-manifest gated; its use must be surfaced to the caller. |
| `{target_language}` | Canonical display value derived from validated translation metadata | Allowed only for translation manifests; applications should prefer rendering it from the typed `translation.target` object rather than accepting arbitrary free text. |

`{full_text}` is legacy only. It must not be silently aliased to `{document_summary}`: full source and summary have different trust, size, and semantic contracts. Existing custom prompts using `{full_text}` can remain on `legacy_text_v0` or an explicitly budgeted legacy structured profile during migration, but new manifests reject it. Default full-document-per-chunk behavior remains rejected.

For an absent optional value, the renderer must remove the manifest-owned optional section or render an empty value deterministically; it must never emit the literal placeholder. The manifest records which behavior applies so prompt digests remain stable.

## Translation target metadata

Translation intent belongs in the task request, not only in prompt prose:

```json
{
  "source": {"language_tag": "en", "mode": "declared_or_detected"},
  "target": {"language_tag": "ru", "display_name": "Russian"},
  "preserve": {
    "code_identifiers": true,
    "technical_terms": "task_policy",
    "protected_values": true
  }
}
```

`target.language_tag` is required and canonicalized as a BCP 47-style tag before rendering. `display_name` is derived from an application-owned language registry, not accepted from model output. Source language may be explicit, detected, or `und`, but its provenance is recorded. The model does not return the target language as authority. Language compliance, protected terms, and no-source-language-leak checks are application validators selected by the translation task policy.

A custom prompt that hard-codes a target language can be admitted only to a manifest pinned to that same target. A runtime target that disagrees with the pin is rejected before transport; the adapter never rewrites the prompt to compensate.

## Application-owned IDs, order, and timestamps

The model may echo only the minimal block `id` needed for deterministic reattachment. The application owns:

- request, recording, document, image, chunk, block, queue, and persistence identities;
- request generation, attempt index, idempotence key, accepted attempt, and fallback state;
- source order, expected item count, exact ID sequence, uniqueness, and target/reference separation;
- all source ranges and start/end timestamps;
- source, prompt, schema, expected-ID, validator, and output digests;
- protected values and their comparison inventory;
- persistence transaction state and read-back verdict.

Model-authored IDs are echoes to verify, never authority. Model-authored timestamps are forbidden in cleanup and translation response contracts. Reattachment occurs only after exact identity/order acceptance.

## Shared validator and fallback pipeline

All adapters feed the same ordered pipeline:

1. **Current-generation gate:** request is current and not cancelled.
2. **Transport/completion:** usable final content, safe finish reason, output usage below the hard cap, and no runaway/reasoning leakage.
3. **Raw parse:** exact raw JSON only for native structured contracts. Optional fence normalization, if a product later permits it, remains a separately classified non-raw path.
4. **Full local schema:** validate with a complete supported validator; provider enforcement is not trusted as proof.
5. **Business identity:** exact count, sequence, uniqueness, no extras, non-empty strict strings, and no reference-only unit in output.
6. **Task semantics:** omission/addition, boundary leakage, protected values, translation target compliance, and task-specific quality.
7. **Commit fence:** cancellation and request generation rechecked immediately before persistence.
8. **Atomic persistence/read-back:** accepted output, attempt, validator summary, fallback state, IDs, order, and timestamps agree after read-back.

Retry budgets are separate but bounded by one logical total-call ceiling:

- transport retry is only for transient timeout, rate-limit, or server failures and is cancellation/generation aware;
- at most one structural retry is eligible for invalid raw JSON, closed-schema failure, or identity/order failure;
- semantic omission/addition, protected-value mutation, boundary leakage, length exhaustion, repetition, or translation-language failure does not receive a structural retry.

After structural exhaustion, text tasks return the original target text and block tasks return the complete original target block sequence. Fallback is recorded as `fallback_original`, not model success. Tasks without a safe original equivalent remain failed/unavailable. Structured execution never falls through to plain text merely because a provider lacks schema support.

## Provider capability negotiation

Capability negotiation occurs after task assembly and before any request. The key is the selected `(provider, model revision, endpoint family)` and the value is observed or administratively pinned capability evidence, not a provider-wide assumption.

Required capability fields:

| Capability | Why it matters |
|---|---|
| `chat_messages` | Required for all four task contracts. |
| `strict_json_schema` | Must be `verified` for native structured tasks; `claimed` or `unknown` is insufficient for promotion. |
| `schema_profile` | Names the tested JSON Schema subset/limits: closed objects, arrays, required fields, string length, enums, and size limits. |
| `finish_reason`, `usage_tokens` | Needed for length/completion gates; missing evidence must be handled explicitly by policy. |
| `max_output_tokens` | Must satisfy the task budget. |
| `reasoning_control` | Whether thinking can be disabled or reliably separated without treating reasoning as final content. |
| `cache_mode` | Transport optimization only; cannot alter logical messages or validation. |
| `cancellation` | Whether in-flight cancellation is supported; the application generation fence remains mandatory regardless. |

Negotiation outcomes:

- `native_structured`: bind the exact response format unchanged and use the shared validator;
- `legacy_plain_text`: allowed only when the selected manifest explicitly declares `legacy_plain_text_v0`;
- `unsupported`: fail before transport with the original source retained;
- `shadow_only`: capability is structurally plausible but lacks product evidence; output cannot replace or persist user-visible data.

Do not silently downgrade `structured_*_v1` to prompt-only JSON or free text. Do not let adapters modify schemas to suit a provider. A provider-specific schema variant is a separately versioned response contract with its own evidence and manifest binding.

## Custom-prompt compatibility

Current user prompts override bundled prompts by filename and are classified largely by placeholders. Migration must preserve access without granting accidental structured trust:

1. Inventory custom files without publishing their content; record only filename-safe identity, content digest, sections, and placeholder set locally.
2. Parse existing `# System`/`# User` files with the current five-placeholder grammar.
3. If a file has unknown placeholders, both content placeholders, no content placeholder, or a target-language conflict, mark it `blocked` until edited.
4. Existing `{chunk}` prompts default to `legacy_plain_text_v0`. They may opt into `structured_text_v1` only through an explicit manifest and compatibility preview.
5. Existing `{blocks_json}` prompts do not automatically qualify for `structured_blocks_v1`; their stated output must be compatible with the closed object envelope. Prompt-only bare-array instructions are incompatible and must be migrated, not normalized silently.
6. Existing `{full_text}` remains a deprecated legacy capability subject to context-fit checks. It is never reinterpreted as `{document_summary}`.
7. Provider switching preserves the same admitted custom manifest. A prompt that works only because one provider repairs or ignores a contract is not provider-neutral.
8. Before activation, run offline render fixtures for present/absent optional values, schema digest checks, placeholder leak checks, and fake-adapter payload equality. No raw custom prompt content enters public telemetry.

The UI should show task kind, output contract, required/optional placeholders, translation target policy, legacy status, and blocking diagnostics. Filename remains presentation metadata, not task identity.

## Migration boundaries

1. **Contract kernel:** introduce provider-neutral task DTOs, prompt manifests, schemas, capability records, and validator outcome types without changing current execution.
2. **Manifest inventory:** attach manifests to bundled prompts; classify custom prompts locally as native, legacy, or blocked. Add `{document_summary}` and typed translation metadata, but do not populate summaries yet.
3. **Fake-adapter parity:** prove that local and cloud adapters receive identical rendered messages, response contract, IDs, translation metadata, and budgets while adding only approved transport fields.
4. **Shadow structured text:** add `{text}` schema paths without replacing or persisting current output. Keep blocks and plain text behavior unchanged.
5. **Harden blocks:** exact raw parse, schema, ID/count/order/type checks, immutable attempt records, explicit fallback state, cancellation generation fence, atomic persistence, and read-back.
6. **Translation canary:** one target pair and one task shape at a time after protected-term and language validators pass. Text and blocks are separate canaries.
7. **Summary consumption:** only after a separate summary lifecycle owns generation, versioning, stale detection, and fallback may `{document_summary}` be populated. Its absence must remain valid.
8. **Retire legacy:** deprecate `{full_text}` and prompt-inferred task kind only after every custom prompt has an explicit disposition and rollback path.

Every stage is independently reversible by task/manifest kill switch. Disabling a structured task invalidates in-flight generations and leaves the original application-owned source authoritative.

## Required offline evidence before implementation promotion

- manifest parsing, closed placeholder allow-lists, optional-section rendering, and no literal placeholder leakage;
- local/cloud fake-adapter payload parity excluding an explicit transport-only allow-list;
- exact schema binding and schema-digest mismatch rejection;
- text and block raw/schema/identity validator branches, including duplicate, extra, missing, reordered, wrong-type, empty, fenced, and repaired output;
- target-language conflict, protected-term mutation, source-language leakage, and custom hard-coded-target rejection;
- capability outcomes for verified, unknown, unsupported, and shadow-only routes with no silent downgrade;
- separate transport/structural retry accounting under one total-call ceiling;
- stale-generation/cancellation fences and original-source fallback;
- atomic persistence failure injection and ID/order/timestamp read-back;
- legacy custom prompt inventory and reversible compatibility preview.

Live model/provider behavior, tokenizer fit, semantic thresholds, and persistence product behavior remain separate explicit gates.

## Evidence map

Public LabKit evidence:

- `experiments/lmstudio/results_summaries/2026-07-13_host_request_flow_inventory.md`
- `experiments/lmstudio/results_summaries/2026-07-13_labkit_package_reuse_assessment.md`
- `experiments/lmstudio/results_summaries/2026-07-13_task_specific_context_schema_policy.md`
- `experiments/lmstudio/results_summaries/2026-07-13_structured_validation_migration_risks.md`
- `lmstudio_labkit/requests.py`
- `lmstudio_labkit/schema_builders.py`
- `lmstudio_labkit/json_normalization.py`
- `lmstudio_labkit/validation.py`

Publication-safe aliases for read-only host evidence:

- `host/src/infrastructure/llm/prompt_loader.py`
- `host/src/domain/prompt_placeholders.py`
- `host/src/domain/prompt_validator.py`
- `host/src/domain/models/config/postprocessing.py`
- `host/src/application/services/postprocessing_service.py`
- `host/src/application/services/blocks_post_processor.py`
- `host/src/domain/schemas/block_schema.py`
- `host/src/infrastructure/llm/openai_compatible_client.py`
- `host/src/infrastructure/llm/payload_builders/{openrouter,polza,lmstudio}.py`
- `host/src/domain/llm_providers.py`
- focused prompt, postprocessing, block, payload, and provider tests under `host/tests/`

## Limits and non-claims

- No provider/model route has been newly capability-tested by this report.
- No new prompt, schema, validator, persistence transaction, summary lifecycle, translation target registry, or custom-prompt migration exists yet.
- The proposal does not approve any model, context size, semantic threshold, concurrency level, or rollout percentage.
- Byte-equivalent logical messages across adapters remain an offline test requirement, not an executed result here.
- Translation quality is not established by schema validity or language-character heuristics.
- `{document_summary}` is a consumption contract only; this report does not create or validate summary generation.
- Private prompt text and raw user content are not reproduced in this publication-safe artifact.
