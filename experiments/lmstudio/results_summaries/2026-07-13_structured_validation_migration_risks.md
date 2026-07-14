# Structured validation and migration risks

Date: 2026-07-13

Status: offline, read-only architecture analysis. No model call, model load, network request, benchmark rerun, runtime change, commit, or push was made.

## Decision

A safe migration must treat API-bound JSON Schema as only the runtime grammar gate. Acceptance still requires separate application-owned checks for raw parsing, exact identity and order, semantic ownership, protected values, persistence state, and product behavior.

The host application already sends strict JSON Schema for block processing and image analysis, but its post-generation behavior is not yet consistently fail closed. The block path retries once and can return original blocks, yet it does not reject duplicate or reordered IDs, coerces non-string text, filters extra IDs, and does not preserve an explicit fallback outcome. The image path repairs truncated JSON, supplies defaults for missing required fields, and normalizes unknown enum values; these behaviors convert schema failures into apparently usable results without a semantic image gate.

Migration should therefore start in shadow mode with immutable attempts and no user-visible or persistent model output. Promotion requires the validator, fallback, cancellation, and persistence gates below. Rollback is configuration-only: stop issuing local structured requests, ignore any in-flight result by request generation, and continue with the original application-owned source.

## Evidence boundary

### Host application code contracts inspected

- The compatibility payload builders pass `response_format` through to `/chat/completions`; block and image schemas use `type=json_schema`, `strict=true`, and closed objects (`additionalProperties=false`).
- Block processing owns source blocks and sends compact `{id, text}` items. It performs one parse/identity retry and then substitutes original blocks.
- The block parser accepts either the schema object or a bare array, stringifies non-string text, checks missing IDs, filters extras, but does not reject duplicate IDs or enforce returned order. Results are sorted by numeric ID before merge.
- Generic transport retry is configurable and separate from the block path's structural retry. Timeout, rate-limit, and server errors can therefore consume several transport attempts before a structural retry.
- Text-mode chunk output is plain text and is applied after ordered merge without structured business or protected-value validation.
- Queue cancellation cancels the active task and avoids persistence in covered timeout/cancel tests. Block work checks cancellation before scheduling, but already-started requests may finish; no durable request-generation fence was found in the inspected persistence path.
- Queue success writes the aggregate result and then per-block updates as separate repository operations. No retained evidence demonstrates an atomic transaction or recovery after the first write succeeds and the second fails.
- Image analysis uses API-bound strict JSON Schema, but its parser attempts truncated-JSON repair, defaults missing required fields, maps an unknown scene type to `other`, and then builds a normal result. No post-generation visual grounding/OCR completeness gate is present in that path.

### LabKit evidence reconciled

- Native schema binding improves structure but does not establish semantic quality. In the bounded vision run, all 36 applicable calls passed raw JSON and independent schema validation, while manual semantic dimensions remained mixed.
- Compact generic block schemas plus application-side exact ID/order checks are the strongest tested design. Request-specific positional grammar failed before generation, while the generic repaired design passed its bounded P4 structural run.
- Length/runaway behavior can report a normal stop reason. Usage at the configured output cap must therefore be an independent length signal.
- The recommended one-retry and original-source fallback state machine has not been executed end to end through host persistence and read-back.

## Failure taxonomy

| Layer | Failure examples | Required disposition |
|---|---|---|
| Transport | connection, timeout, HTTP status, missing final text, cancelled request | No parsing or persistence. Retry only under the bounded transport policy and only while the request generation is current. |
| Completion | empty output, explicit length, usage reaches cap, runaway repetition, reasoning leakage | Fail closed. Do not structural-retry length, repetition, or reasoning leakage. |
| Raw parse | invalid JSON, fenced JSON, repaired/truncated JSON | Raw JSON is the default requirement. Recovery, if a product explicitly allows it, remains a distinct non-success transport state and cannot bypass schema validation. |
| Runtime schema | missing/extra field, wrong type, wrong enum, unclosed structure | One structural retry may be eligible. Production uses a full JSON Schema validator even when the server claims strict enforcement. |
| Business identity | missing, duplicate, extra, reordered IDs; count mismatch; empty text | Require exact application-owned count, sequence, uniqueness, and non-empty strings. Never filter, coerce, sort away, or partially accept a defect. |
| Semantic ownership | omission, unsupported addition, cross-block or cross-chunk leakage, summary scope leakage | Fail closed to the original source; no retry by default. |
| Protected values | changed names, numbers, dates, URLs, commands, placeholders, identifiers, timestamps | Fail closed to the original source. The application computes and compares the inventory; the model does not author it. |
| Image semantics | incomplete visible text, OCR mutation, ungrounded object, unsupported warning or claim | Separate manual/automated semantic gate after schema. Schema validity alone never admits an image result. |
| Control flow | stale attempt wins, retry overwrites attempt zero, cancellation races with completion | Immutable attempts plus request-generation fencing. A cancelled or superseded request can never publish or persist. |
| Persistence | aggregate write succeeds but block write fails; fallback recorded as success; partial batch persists | Transactional commit or explicit recoverable state. Read-back must match source IDs/order and accepted attempt. |
| Observability | raw failure collapsed into `unknown`; fallback indistinguishable from model success | Emit privacy-safe categorical outcomes and provenance digests without prompt, response, path, or user text. |

## Fail-closed acceptance gates

Execute the gates in this order and preserve every intermediate result:

1. Verify the request is still current and not cancelled.
2. Accept only a completed transport envelope with final text and safe finish/usage state.
3. Parse raw JSON. Do not silently repair, unwrap, or default malformed output into success.
4. Validate the complete closed JSON Schema locally.
5. Validate exact expected item count, ID sequence, uniqueness, and non-empty string types.
6. Validate task scope and boundaries: only current target units may be changed or summarized.
7. Compare application-derived protected values and placeholders.
8. Apply task-specific semantics. For images, score visible-text fidelity/completeness, object grounding/completeness, and unsupported claims separately.
9. Recheck cancellation/request generation immediately before commit.
10. Persist accepted output and its validator/control-flow record atomically, then read back identity, order, attempt, and state.

Any failed gate returns the original application-owned text/blocks unchanged. A summary or image result with no safe original-text equivalent must remain failed/unavailable rather than publishing a structurally valid guess.

## Retry boundaries

There are two independent budgets and they must not multiply invisibly:

- **Transport retry:** bounded by provider/runtime policy for transient timeout, rate-limit, or server failures. Each attempt checks cancellation and request generation. A lost/unloaded local instance, deterministic HTTP 4xx, and semantic failure are not transport-retry candidates.
- **Structural retry:** maximum one generated retry after a completed response fails raw JSON, full schema, or exact identity/order. It keeps the same source and semantic instruction and adds one terse correction naming only the failed structural gate.

Do not structural-retry length exhaustion, runaway repetition, reasoning leakage, semantic omission/addition, boundary leakage, protected-value change, or image grounding/OCR failure. Attempt zero and retry one are immutable records; retry success does not rewrite the first failure. Define one total-call ceiling per logical request so transport and structural retry cannot exceed the product's latency and cancellation contract.

## Fallback and partial-result policy

- Structural failure after the one allowed retry returns all original target blocks in original application order and marks `fallback_original`.
- Semantic, protected-value, boundary, cancellation, or length failure skips structural retry and returns the original target immediately.
- Do not filter extra IDs, sort a reordered response into apparent correctness, coerce wrong types, default required image fields, or persist only the valid subset.
- Batch acceptance is atomic by default. Per-block partial acceptance requires a separate product contract with independent validation, exact order, explicit unchanged states, and transactional persistence; it is not implied by the current schema.
- Fallback is a degraded product outcome, not model success. User-facing behavior may remain seamless, but telemetry and stored state must distinguish `accepted`, `fallback_original`, `cancelled`, and `failed`.

## Persistence, cancellation, and ordering contract

The application remains authoritative for request ID, request generation, source digest, expected ID sequence, timestamps, protected-value digest, retry state, fallback state, and validator version.

Recommended state machine:

```text
created -> running(attempt_0) -> validating
  -> accepted -> committing -> committed
  -> retrying(attempt_1) -> validating
  -> fallback_original -> committing -> committed_degraded
  -> cancelled | failed
```

Only the current request generation may move to `committing`. Cancellation or replacement advances the generation and makes late completions inert. Persist aggregate text, per-block updates, attempt/control state, and validator summary in one transaction where possible. If the storage boundary cannot be atomic, use an explicit pending/committed marker and deterministic recovery; never infer completion from the aggregate write alone.

Ordering is the original expected sequence, not numeric sorting unless the domain explicitly guarantees those are identical. Timestamps and source locators are reattached by application-owned identity only after exact sequence validation.

## Image semantic gate

The 40-call closure proves compatible image transport and strict-schema conformance for its bounded fixtures, not production semantic admission. A safe host gate must keep these dimensions separate:

- visible text exactness and salient-text completeness;
- object grounding and salient-object completeness;
- unsupported claims and warning relevance;
- forbidden private/person claims;
- scene/language classification validity.

Missing fields, truncated JSON, and unknown enum values must not be defaulted into an accepted result. OCR-like extracted text should require exact or explicitly tolerance-scored comparison when a closed-world reference exists. Open-world descriptions need a reviewed grounding rubric and an abstain/review outcome; sparse allow-lists are not exhaustive gold.

## Rollout and rollback

1. **Offline contract tests:** fake client only; exercise every taxonomy branch, immutable attempt ledger, cancellation fence, and persistence failure.
2. **Shadow mode:** issue local structured requests only under separate authorization; validate and record privacy-safe categories, but never replace or persist user-visible output.
3. **Read-only comparison:** compare accepted candidates with the unchanged source and manual review, stratified by task and source position.
4. **Canary:** one task contract at a time, with original-source fallback, per-contract kill switch, call/latency ceiling, and automatic rollback on safety or persistence defects.
5. **Broader rollout:** only after task-specific semantic and persistence thresholds pass; do not infer text admission from vision structure or vice versa.

Rollback disables new local requests, increments request generation to invalidate in-flight responses, preserves original source and timestamps, and leaves previously committed output traceable to its accepted attempt. Schema and validator versions must remain readable so rollback does not orphan stored records.

## Required privacy-safe observability

Record categorical and numeric metadata only:

- task kind, endpoint family, model revision, request generation, attempt index;
- transport category/status, latency, finish reason, token usage, configured cap;
- raw parse mode, schema result and error category;
- expected/observed count plus missing/duplicate/extra/reordered counts;
- protected-value and boundary verdicts without values;
- semantic gate dimensions and review state;
- cancellation timestamps/stages, fallback reason, persistence state/read-back result;
- request, schema, source, expected-ID, raw-output, envelope, and validator digests.

Do not log prompts, raw outputs, source text, protected values, credentials, local paths, or image bytes.

## Missing tests and instrumentation

Blocking before migration:

- duplicate, extra, reordered, wrong-type, empty-text, and bare-array block responses must all fail closed;
- one structural retry must be distinct from transport retry, have a total-call ceiling, and preserve both attempts;
- fallback must preserve exact original text, ID order, timestamps, and explicit degraded state through persistence/read-back/export;
- cancellation before request, during retry/backoff, during in-flight generation, after validation, and during commit must prevent late persistence;
- aggregate-plus-block persistence needs transaction/failure-injection/recovery tests;
- protected names/numbers/dates/URLs/commands/placeholders and cross-boundary leakage need deterministic validators and fixtures;
- completion-at-cap and runaway repetition must fail despite a normal stop reason;
- image tests must reject repaired/defaulted schema failures and cover grounded OCR/object/unsupported-claim dimensions;
- shadow/canary kill switch, stale request generation, rollback, and schema/validator-version read-back need integration tests;
- metrics must expose attempt, fallback, validator, and persistence outcomes without raw content.

Evidence still missing after those offline tests:

- no retained end-to-end host run demonstrates structural retry, original fallback, persistence, read-back, and export together;
- no cancellation race has been exercised against a real local structured request;
- no valid binary image semantic-admission rubric is established;
- no production threshold exists for protected-value or semantic acceptance;
- no transaction/read-repair evidence exists for partial persistence failure;
- bounded model evidence does not establish broad model ranking, cross-task admission, or production concurrency.

## Evidence sources

Public LabKit evidence:

- `2026-07-12_structured_output_and_scorer_audit.md`
- `2026-07-12_source_application_pipeline_fit.md`
- `2026-07-13_host_application_shaped_structured_context_summary.md`
- `2026-07-13_native_structured_vision_closure.md`
- `2026-07-13_strict_vision_40_call_manual_reconciliation.md`

Host application source classes inspected read-only:

- compatibility request/payload construction;
- block schema, block processor, chunk planning, merge, queue persistence, cancellation, and tests;
- image schema, image processor, structured parser, and tests.

Machine-readable companion: `2026-07-13_structured_validation_migration_risks.json`.
