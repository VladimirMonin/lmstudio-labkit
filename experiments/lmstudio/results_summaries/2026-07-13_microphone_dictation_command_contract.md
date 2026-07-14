# Microphone dictation and `MODEL:` command contract

Date: 2026-07-13

Status: read-only architecture recommendation. No model call, prompt change, runtime change, persistence migration, or host-application edit was performed.

Machine-readable companion: `2026-07-13_microphone_dictation_command_contract.json`.

## Decision

A microphone capture has two mutually exclusive product modes selected before any LLM request:

1. **Dictation cleanup** keeps the existing small, task-specific cleanup instruction and treats the transcript as the text to preserve and lightly normalize.
2. **`MODEL:` command** uses a separate command instruction, a separate strict response schema, and a distinct command-result artifact. The transcript after the trigger is a user request, not text to clean up.

The modes must not share prompt files, output fields, fallback behavior, or persistence meaning. Provider selection may change transport headers and local runtime controls, but it must not change classification, prompt role, schema, validation, UI projection, or fallback semantics.

## Evidence level

- **Exact source contract:** current microphone postprocessing selects a microphone prompt, submits the transcript as text, stores accepted output in `postprocessed_text`, and sends that same value to clipboard/auto-paste. The provider-neutral compatibility client is shared by local and cloud routes.
- **Exact source gap:** no `MODEL:` classifier, command artifact, command response schema, or command-specific UI/persistence path exists in the inspected source.
- **Runtime-unexecuted recommendation:** every command behavior below is proposed architecture. No voice recognizer, local model, cloud provider, clipboard target, or persistence round trip was exercised.
- **Estimate:** none. This report gives no latency, token, quality, or capacity estimate.

## Trigger normalization and ownership

Classification is deterministic application logic. It must not be delegated to a model or fuzzy language detector.

1. Preserve `transcript_text` exactly as the immutable transcription artifact.
2. Skip leading Unicode whitespace only for trigger detection.
3. At the first non-whitespace character, match ASCII `MODEL` case-insensitively, followed by optional horizontal whitespace and either `:` or `：`.
4. The delimiter must be present. `MODEL`, `MODEL.`, a later mid-sentence `MODEL:`, a translated word, or an approximate/fuzzy spelling remains normal dictation.
5. Extract the suffix after the delimiter from the original transcript. Trim only its outer whitespace to derive `command_text`; do not case-fold, normalize punctuation, rewrite, summarize, or include the trigger.
6. Once the anchored trigger matches, the capture is command mode even when the suffix is empty. An empty command is an invalid command, not dictation fallback.

`command_text` is application-owned request state. The model may consume it but may not author, replace, or normalize it. The application also owns request ID/generation, transcript identity, source digest, trigger version, attempt state, provider/model provenance, cancellation, and persistence status.

This conservative rule avoids accidental commands while tolerating ordinary case variation, whitespace before the delimiter, and the common full-width colon. Additional spoken aliases require a separately specified product decision and tests; they must not be added as ad hoc fuzzy matches.

## Two-mode state machine

```text
captured -> transcribed -> classified

classified(dictation)
  -> cleanup_requested
  -> cleanup_response_received
  -> cleanup_validated
  -> cleanup_ready
  -> cleanup_fallback_original | cancelled | failed

classified(command)
  -> command_text_validated
  -> command_requested
  -> command_envelope_received
  -> command_envelope_validated
  -> command_ready
  -> command_invalid | command_failed | cancelled

any in-flight state
  -> stale when request generation changes
```

Only the current non-cancelled request generation may publish, copy, paste, or persist an output. Attempts are immutable. Cleanup fallback and command failure are intentionally different terminal outcomes.

## Dictation cleanup contract

### Request

- Use the existing simple microphone-cleanup instruction, not the command instruction.
- Use only the current short transcript as the target. Do not inject a document summary or unrelated recording context.
- Keep any later structured migration minimal: a closed `{text: string}` envelope is sufficient. The prompt itself should remain a small cleanup instruction rather than absorb command behavior.
- During compatibility migration, the current plain-text cleanup response may remain supported behind an explicit `cleanup_plain_v1` contract. That exception must never be reused for command mode.

Recommended strict envelope for the migrated cleanup path:

```json
{
  "text": "Cleaned dictation"
}
```

Application acceptance requires a completed non-length response, raw whole-value JSON parsing for the structured variant, closed-schema validation, and non-empty text after outer-whitespace validation. Task-specific checks must reject destructive omission, unsupported addition, and protected-value changes. A failed cleanup may return the immutable original transcript as `fallback_original` because it is still useful dictation.

### Result artifact

A cleanup result remains transcription-derived:

- `artifact_kind = microphone_cleanup`
- `original_text` remains authoritative fallback
- `cleaned_text` is the accepted model-authored value or null
- `display_text`, `copy_text`, and `paste_text` are application-owned projections
- persistence may continue to use the transcription/postprocessing record during migration

## `MODEL:` command contract

### Request

- Use a separate versioned command prompt and never the cleanup prompt.
- Send only `command_text` plus explicitly approved bounded context. Do not send the trigger, full recording, cleanup prompt, document summary, or clipboard content by default.
- The command prompt may be more capable and detailed than cleanup, but provider-specific instructions must not be embedded in it.
- Bind the response through the provider API's strict JSON Schema capability on both local and cloud compatibility routes.

The model-authored response envelope is deliberately minimal:

```json
{
  "answer_text": "Final plain answer"
}
```

Schema contract:

- root type is object;
- `answer_text` is the only property;
- `answer_text` is a string with `minLength: 1`;
- `required = ["answer_text"]`;
- `additionalProperties = false`.

The envelope is transport/validation structure, not the user-visible artifact. After strict validation, the application extracts `answer_text` and materializes a plain answer. It does not expose braces, JSON quoting, or a Markdown code fence to display/copy/paste consumers.

### No wrapper stripping or repair

Command parsing accepts only a raw JSON object occupying the entire response content. It must not:

- strip `````json`` or other Markdown fences;
- search prose for an embedded object;
- repair truncated JSON;
- remove reasoning tags and then treat the remainder as valid;
- coerce non-string values;
- default a missing field;
- reinterpret plain text as a successful command answer.

A structurally invalid response may receive at most one new model request under the shared bounded structural-retry policy. That is a separate immutable attempt, not local repair. Length exhaustion, repetition, reasoning leakage, semantic failure, cancellation, or stale generation is not eligible for structural retry.

### Distinct command artifact

A command must not write its answer into `postprocessed_text` or `summary`. It produces a distinct artifact such as:

- `artifact_kind = microphone_model_command`
- application-owned `artifact_id`, `transcription_id`, `request_generation`, and `command_text`
- `answer_text` from the validated envelope
- explicit `display_text`, `copy_text`, and `paste_text`
- provider/model/schema/prompt/validator versions or digests
- transport, parse, schema, semantic, attempt, cancellation, and persistence verdicts
- no raw prompt or raw provider output in publication-safe telemetry

The host may persist the source transcript according to its existing ephemeral/persistent policy. If command history is a product feature, persist the command artifact separately and link it to the transcription. Do not make a command answer look like cleaned transcript text, and do not overwrite the source transcript.

## Display, copy, and paste projections

These fields are separate application-owned decisions even when they initially contain identical strings:

| Field | Dictation cleanup | `MODEL:` command |
|---|---|---|
| `display_text` | accepted cleanup, else original transcript with degraded state | validated plain `answer_text`; on failure show a typed error state, not transcript-as-answer |
| `copy_text` | accepted cleanup, else original transcript when clipboard automation is allowed | validated plain `answer_text`; absent on failure |
| `paste_text` | same safe text selected for auto-paste | validated plain `answer_text`; absent on failure |

Initial command policy is `display_text == copy_text == paste_text == answer_text`, but the fields must be materialized independently rather than inferred by downstream consumers from a generic `postprocessed_text`. This prevents a future display-only annotation from leaking into copied or pasted content.

Clipboard/auto-paste is permitted only after mode-specific validation and the existing low-speech/safety gate. An empty command, empty answer, malformed envelope, cancelled request, stale completion, or failed semantic gate must not copy or paste anything.

## Empty and malformed output safety

- **Empty transcript:** no LLM request and no clipboard automation.
- **Trigger plus empty `command_text`:** `command_invalid`; no cleanup request, command request, copy, paste, or command persistence as success.
- **Empty provider content or empty `answer_text`:** command failure; no transcript fallback into the target application.
- **Malformed/fenced/repaired/coerced command output:** parse/schema failure; optional one bounded re-request only, then failure.
- **Cleanup failure:** may use exact original transcript as an explicitly degraded fallback.
- **Command failure:** never paste the original `MODEL:` transcript or `command_text` as though it were an answer.
- **Late completion:** ignored after cancellation or request-generation change.

## Local/cloud parity

Local LM Studio and cloud providers use the same logical command contract:

- identical trigger classifier and `command_text` extraction;
- identical command prompt version and user-message construction;
- identical strict response schema;
- identical raw-parse, local-schema, non-empty, semantic, cancellation, and persistence gates;
- identical final plain-answer projection and UI behavior.

Only transport adapters vary: endpoint/base URL, authorization headers, usage/cache fields, local `cache_prompt`, local thinking controls, readiness, and lifecycle ownership. A provider that cannot enforce the strict schema is not silently downgraded to prompt-only JSON for command mode; it is unsupported for that contract until an explicit compatibility mode is approved.

## Why document summary is not used

A microphone command is a current user request, not a document-summary task. The current host has reserved summary storage but no implemented summary producer, validator, freshness policy, or request owner. Injecting that field would therefore use absent or stale state and would blur summary generation with summary consumption.

Even after a summary pipeline exists, it should not be included by default: it can leak unrelated recording content, alter the user's command scope, increase tokens, and make local/cloud behavior depend on hidden mutable context. A future command that explicitly requests selected document context needs a separate context contract with user-visible scope, source identity, freshness, fit, privacy, and cancellation gates.

## Compatibility and migration implications

1. Add classification before the current microphone cleanup request and before prompt selection.
2. Leave the existing dictation path and microphone prompt behavior unchanged for captures without the anchored trigger.
3. Introduce a dedicated command prompt identifier, strict schema, request kind, result event, and artifact type.
4. Do not overload `PostprocessingCompleteEvent.postprocessed_text`; add a command-complete event or a typed union with explicit mode-specific payloads.
5. Route clipboard consumers through explicit `copy_text`/`paste_text`, not a fallback chain shared across modes.
6. Keep cleanup original-text fallback; command failures are visible typed failures with no clipboard side effect.
7. Add command persistence only after transaction/read-back and retention behavior are specified. Shadow mode should initially keep command candidates out of user-visible output.
8. Rollback disables command classification/execution by a contract-specific feature flag and returns all captures to the existing dictation path; in-flight command generations become stale.

## Tests to add

### Classification and ownership

- exact, lowercase, mixed-case, leading-whitespace, optional pre-colon horizontal whitespace, and full-width-colon triggers;
- reject missing colon, mid-sentence occurrence, translated/fuzzy alias, and lookalike punctuation;
- exact suffix extraction without trigger leakage or internal normalization;
- trigger-only input is `command_invalid`, never dictation;
- immutable original transcript and application-owned `command_text` survive retry/cancellation.

### Prompt and provider parity

- dictation selects only the simple cleanup prompt; command selects only the command prompt;
- local and each cloud builder receive equivalent messages, schema, output budget policy, and request kind;
- command mode never sends document summary, full recording, or clipboard by default;
- schema-incapable provider fails capability admission rather than falling back to prompt-only JSON.

### Parsing and validation

- accept one exact closed object with non-empty `answer_text`;
- reject empty content, whitespace-only answer, plain text, fenced JSON, prose-wrapped JSON, truncated JSON, arrays, missing/extra fields, wrong types, reasoning leakage, length-at-cap, and repetition;
- structural retry is at most one separate request with immutable attempts and a total-call ceiling;
- no local unwrap, extraction, coercion, default, or repair path can produce acceptance.

### UI, clipboard, persistence, and races

- dictation display/copy/paste uses accepted cleanup or explicit original fallback;
- command display/copy/paste uses only validated `answer_text`;
- command failure, empty input, cancellation, stale generation, and semantic rejection perform zero copy/paste operations;
- command result does not mutate `postprocessed_text`, `summary`, or source transcript;
- persisted command artifacts round-trip with mode, linkage, attempts, validator versions, and explicit outcome;
- cancellation before request, during retry/backoff, after validation, and during commit prevents late publication;
- rollback invalidates in-flight command generations and restores ordinary dictation classification.

## Evidence map

Publication-safe `host/` aliases refer to the external read-only source tree:

- microphone/media prompt selection: `host/src/domain/models/config/postprocessing.py:23-25,70-84,93-133`;
- microphone coordinator, model readiness, postprocessing application, and completion event: `host/src/application/services/postprocessing_coordinator.py:118-155,197-223,225-391`;
- plain text request and direct response use: `host/src/application/services/postprocessing_service.py:914-1025`;
- prompt template placeholders and formatting: `host/src/infrastructure/llm/prompt_loader.py:26-28,52-137`;
- transcription persistence before postprocessing: `host/src/services/transcription_service.py:1459-1540`;
- clipboard fallback and auto-paste behavior: `host/src/services/clipboard_service.py:223-306`;
- transcription fields including `postprocessed_text` and reserved `summary`: `host/src/domain/models/transcription.py:171-209,264-318`;
- provider parity and current structured/plain flow inventory: `2026-07-13_host_request_flow_inventory.md`;
- context and schema policy: `2026-07-13_task_specific_context_schema_policy.md`;
- fail-closed migration policy: `2026-07-13_structured_validation_migration_risks.md`.

## Limits and non-claims

- No private prompt text or raw user transcript was inspected or reproduced.
- No command-model semantic rubric or quality threshold is established here.
- No spoken alias beyond the explicit textual trigger is approved.
- No live provider, microphone recognizer, clipboard target, UI, persistence, latency, or cancellation race was exercised.
- The recommended command envelope establishes structure only; it does not prove answer correctness, safety, or production admission.
- This report proposes contracts and tests, not implementation or migration completion.
