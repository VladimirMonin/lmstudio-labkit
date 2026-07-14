# Summary artifact and full-text-per-chunk retirement

Date: 2026-07-13

Status: read-only architecture recommendation. No live request, model operation, runtime tokenizer capture, implementation, migration, commit, or push was performed.

Machine-readable companion: `2026-07-13_summary_artifact_full_text_retirement.json`.

## Decision

Retire full-recording text as repeated context for chunk-level requests. Replace it, only for task contracts that need global context, with a persisted and provenance-bound recording summary plus the authoritative current target and narrow boundary context.

Do **not** retire `full_text` from storage. Original transcription text, source blocks, segment timestamps, and accepted postprocessed text remain application-owned records. A summary is a derived, lossy artifact and may never become the source of truth, fallback value, export replacement, or sole recovery surface.

The architecture must remain useful without cache reuse. A current summary is small enough to be a stable request prefix, but retained evidence does not prove physical prefix/KV reuse for changing chunk suffixes.

## Current host contract

Read-only source inspection establishes the following:

- The domain model and SQLite transcription row each have a nullable string `summary` field.
- Normal creation explicitly writes `summary=NULL`, even when the domain object carries a value. General update and postprocessing update do not write the field. No production summary writer, request owner, validator, refresh operation, or read-back state machine was found.
- SQLite load restores `summary` into the domain object.
- FTS5 already indexes `full_text`, `postprocessed_text`, `summary`, and `user_notes`; search can scope specifically to the summary column.
- Processed-data settings transfer exports and imports the bare summary string and rebuilds FTS, but carries no summary provenance, version, strategy, status, or staleness state.
- Plain transcription export selects raw or postprocessed text. It does not export the summary as a separate artifact and does not substitute summary for transcription text.
- The prompt registry recognizes `{chunk}`, `{blocks_json}`, `{full_text}`, `{clipboard}`, and `{context}`. It has no summary placeholder.
- Four inspected bundled prompt templates use `{full_text}`. The formatter can split the user message at `{full_text}` and label the prefix cacheable. Both character-chunk and block-chunk paths pass the complete text to every request when a selected prompt uses that placeholder.

Therefore the existing `summary` column is a reserved projection and search surface, not a safe artifact contract.

## Evidence for retirement

The bounded structured-context study executed 202 heterogeneous requests on one frozen recording and one selected model. For 35 per-chunk summaries:

| Context | Structurally/practically valid | Median input tokens | Median latency |
|---|---:|---:|---:|
| Current chunk only | 35/35 | 786 | 8.04 s |
| Boundary neighbors | 33/35 | 1,040 | 8.22 s |
| Adjacent chunks | 34/35 | 2,107 | 8.60 s |
| Full recording | 35/35 | 23,099 | 20.20 s |

Full-recording context repeated across those 35 calls consumed approximately 807,600 input tokens and 700.7 seconds of summed request time. Current-only consumed approximately 26,700 tokens and 274.9 seconds. Full context did not show proportional semantic benefit and tended to globalize framing.

For block-preserving cleanup, full context caused one first-pass block-attribution defect and one repeated malformed length-exhausted result. Boundary-neighbor context was the best observed balance. A separate 27-output representation slice found 24/27 complete and 26/27 chunk-isolated outputs, with structured full-context representations costing about 28–30% more input tokens than plain text.

Cache evidence does not rescue the repeated-full-text design. In one four-request probe, an exact repeat became faster, while a stable full prefix with a changed chunk did not. No request-linked cached-token count, cache-hit flag, reused-prefix count, or physical KV trace was retained.

These are bounded results, not a production quality threshold. They are sufficient to reject full-text-per-chunk as the default architecture; they do not prove the proposed summary pipeline end to end.

## Artifact model

Use a versioned `SummaryArtifact` record rather than treating `transcriptions.summary` as the canonical object.

Minimum fields:

| Group | Required fields |
|---|---|
| Identity | artifact ID, transcription ID, artifact kind (`chunk` or `recording`), artifact version, state |
| Source binding | source layer (`raw` or accepted postprocessed), source revision, source digest, ordered source-unit digest, source range/count |
| Generation | strategy (`direct` or `hierarchical`), task-contract version, prompt digest/version, response-schema version, validator version |
| Runtime provenance | provider family, model stable ID and revision, runtime/template revision when observed, exact input/output token counts when executed |
| Hierarchy | partition-plan digest, ordered child artifact IDs/digests, exact coverage and ordering verdict |
| Validation | transport, completion, raw-parse, schema, scope/grounding, coverage, and product-state verdicts kept separately |
| Lifecycle | request generation, attempt index, created/accepted timestamps, current/superseded/stale markers and reason |
| Payload | constrained structured summary payload plus a deterministic display/search projection |

The existing `transcriptions.summary` column may remain temporarily as the display/FTS projection of the single current accepted recording-level artifact. It is not authoritative. Stale or failed artifacts must not populate that projection.

## Summary response contracts

### Chunk artifact

A chunk summary contains a bounded local summary, bounded key points, and source-supported uncertainties. Recording ID, chunk ID, ordinal, source range, and timestamps are attached by the application, not generated by the model.

### Recording artifact

A recording summary contains a compact overview, bounded key points, and open questions. The application owns recording identity, chronology, child order, source coverage, and provenance.

Both contracts must use an API-bound closed schema when the transport supports it, followed by local raw parsing, full schema validation, output-length checks, scope/grounding checks, and persistence read-back. Schema success is not semantic acceptance.

## Direct versus hierarchical generation

Perform exact request planning before generation using the selected model revision's runtime tokenizer and chat template.

A direct recording summary is allowed only when all of these are true:

1. the complete authoritative source serialization is bound to one source digest and exact unit order;
2. exact runtime input tokens include system/user messages, chat-template overhead, schema/grammar overhead, and all separators;
3. the configured output reserve and safety reserve fit the admitted runtime context;
4. the direct task requests a compact recording-level overview rather than detailed chronological notes;
5. the request remains within the task's latency/cancellation ceiling.

If exact runtime planning is unavailable, fails, or does not fit, do not estimate upward and try the oversized direct request. Route to hierarchical generation. Static estimates may select a candidate path, but they cannot authorize a direct call.

Hierarchical generation uses this rule:

1. partition the authoritative source into ordered, non-lossy source ranges;
2. generate one constrained current-only summary per range; boundary context is allowed only for a specifically detected interrupted thought and remains reference-only;
3. require exact child coverage, source binding, order, and accepted state for every range;
4. synthesize the ordered accepted child artifacts in one or more bounded levels until the final recording artifact fits exactly;
5. bind every synthesis node to the ordered child digests and preserve the leaf-to-source map.

If all accepted child summaries still do not fit one synthesis request, recursively group adjacent children. Do not drop children, silently truncate, reorder by relevance, or fall back to a partial recording summary. Partial child work may be retained for resume, but no recording-level artifact becomes current until coverage is complete.

## Lifecycle and staleness

Recommended state machine:

```text
absent
  -> planned(source_revision, source_digest, strategy)
  -> generating(attempt_0)
  -> validating
  -> accepted_pending_commit
  -> current

validating -> retrying(attempt_1) -> validating
planned|generating|validating -> cancelled|failed
current -> stale -> refresh_planned
current -> superseded
```

A maximum of one structural retry may follow invalid raw JSON, schema failure, or malformed bounded structure. Length exhaustion, semantic omission/addition, scope leakage, source-grounding failure, cancellation, and stale request generation do not receive a structural retry.

An artifact becomes stale when any content-bearing source revision/digest changes, source-unit order or coverage changes, the selected source layer changes, or an administrative invalidation marks its generator/validator version unsafe. A prompt/schema/model version change alone does not retroactively stale a semantically accepted artifact unless the product policy explicitly invalidates that version; it does make a later refresh a distinct artifact.

Stale artifacts remain auditable but are ineligible for prompt injection, current-summary FTS projection, normal summary display, or ordinary summary export. Refresh creates a new immutable artifact and atomically replaces the current projection only after validation and read-back.

## Prompt placeholder policy

Introduce one explicit placeholder, `{recording_summary}`, with a declared requirement level in prompt metadata:

- `forbidden`: the task must not receive a recording summary;
- `optional`: inject only a current accepted artifact, otherwise omit the entire labeled section;
- `required`: fail request planning when no current accepted artifact exists; optionally schedule summary generation as a separate prerequisite operation.

Do not substitute an empty string for a required summary and do not silently fall back to full text.

Injection policy:

| Task | Recording summary | Authoritative target context |
|---|---|---|
| Short microphone cleanup | Forbidden by default | Current capture only |
| Long block-preserving cleanup | Optional when global terminology/topic context is needed | Previous tail and next head are reference-only; current blocks are the only output targets |
| Character-chunk cleanup during migration | Optional | Current chunk plus explicit boundary context; prefer migration to block identity |
| Per-chunk summary generation | Forbidden | Current chunk only; targeted boundary fallback only |
| Direct recording summary | Forbidden | Complete authoritative source once |
| Hierarchical recording summary | Forbidden at leaf generation; synthesis receives ordered child artifacts | Exact child set for the current synthesis node |
| Self-contained generic transform | Forbidden by default | Current input only |
| Image analysis | Forbidden | Current image and image-task contract only |

The summary is advisory global context. Prompt contracts must state that current targets and application-owned identities override summary wording. A stale or mismatched summary is never injected.

## Compatibility and deprecation plan

1. **Inventory and observe.** Detect `{full_text}` in bundled and user prompt templates without reading or logging prompt content. Record only prompt identity/digest and usage category.
2. **Add the artifact contract.** Implement versioned summary persistence, current projection, exact planner, validation, staleness, refresh, and read-back before changing prompt behavior.
3. **Add `{recording_summary}` explicitly.** Update prompt registry, validator, UI description, and prompt requirement metadata. Do not alias `{full_text}` to it.
4. **Compatibility window.** Existing `{full_text}` prompts continue under an explicit legacy mode with a deprecation warning and call/size telemetry. New or edited prompts cannot add `{full_text}` unless an advanced compatibility flag is enabled.
5. **Migrate by task contract.** Create new prompt revisions that use `{recording_summary}` only where global context is justified, plus `{chunk}` or `{blocks_json}` and `{context}` for authoritative targets. Preserve prior prompt files for rollback during the window.
6. **Shadow comparison.** With separately authorized execution, compare new requests against unchanged source behavior. No user-visible or persistent model output is promoted in shadow mode.
7. **Default retirement.** Disable legacy full-text injection for migrated contracts. A legacy prompt that still requires `{full_text}` fails closed with a clear migration error rather than receiving summary under the old name.
8. **Remove legacy support.** Remove `{full_text}` from the accepted placeholder registry only after installed/user prompt inventory is zero or explicitly waived and rollback artifacts are retained.

The key compatibility rule is semantic: `{full_text}` and `{recording_summary}` are not interchangeable. Automatic aliasing would silently change what a prompt sees and can invalidate its instructions.

## Storage, FTS, and export migration

- Keep `full_text`, segments, blocks, timestamps, and original media references unchanged according to existing retention policy.
- Add canonical summary artifact rows. Backfill no fabricated provenance for existing non-null summary strings. Import each legacy string as `legacy_unverified` or leave it as a compatibility projection; it is not prompt-eligible until regenerated or explicitly reviewed and bound.
- Continue FTS over raw/postprocessed text and the current accepted summary projection. FTS summary scope must exclude stale, failed, partial, and superseded artifacts.
- Extend processed-data transfer with summary artifact records and provenance. Continue importing the legacy bare field during a compatibility version, then rebuild the current projection and FTS deterministically.
- Add a distinct summary export surface that identifies strategy, source revision, artifact version, and staleness. Do not make ordinary transcription export return summary in place of raw or postprocessed text.
- Treat stale-artifact cleanup and history retention as an explicit product retention policy; do not cascade-delete original source merely because a derived summary is removed.

## Cache policy

A current accepted recording summary and stable task instructions may form a small byte-stable prefix. Persist and compare their digests and record runtime-reported cache counters when available. This is an optimization only.

Do not serialize the full recording into a prefix, await one request as proof of materialization, or claim a cache hit from latency alone. Request correctness, fit, cancellation, and fallback must be identical when cache behavior is absent.

## Non-loss guarantees

1. Summary generation never mutates or deletes raw text, segments, blocks, timestamps, accepted postprocessed text, or source files.
2. Every summary artifact is bound to an immutable source revision/digest and exact coverage.
3. Failed, stale, partial, or superseded summaries cannot enter prompts as current context.
4. Hierarchical publication requires complete ordered leaf coverage; no best-effort partial whole summary.
5. Removing `{full_text}` from prompt context does not remove it from storage, FTS raw-text search, recovery, or raw export.
6. Fallback for transform tasks remains the original authoritative target, never the summary.
7. Rollback disables summary injection and returns to current/boundary-only requests without data migration or source loss.

## Implementation order and required gates

1. Offline schema/state-machine tests for direct, hierarchical, retry, cancellation, stale-generation, and partial-commit branches.
2. Exact planner tests with tokenizer/template fixtures, output reserve, and recursive hierarchy planning.
3. Persistence migration, immutable artifact history, current projection, FTS filtering, settings-transfer round trip, and read-back tests.
4. Prompt inventory, requirement metadata, compatibility mode, migration diagnostics, and no-alias tests.
5. Fake-client end-to-end tests proving source retention, complete hierarchy coverage, stale rejection, export behavior, and rollback.
6. Separately authorized shadow execution, then task-specific canary. No current report authorizes those live stages.

## Evidence map

Publication-safe `host/` references denote the read-only external source root.

- Reserved domain field and serialization: `host/src/domain/models/transcription.py:171-218,264-318`.
- SQLite field and normal create/load behavior: `host/src/infrastructure/storage/models.py:146-200`; `host/src/infrastructure/storage/components/crud_repository.py:87-157,274-355,952-979`.
- FTS schema, triggers, and summary-scoped search: `host/src/infrastructure/storage/migrations.py:545-631`; `host/src/infrastructure/storage/components/fts_search_provider.py:374-410`.
- Processed-data import/export: `host/src/infrastructure/storage/sqlite_repository.py:583-686,699-731`.
- Prompt placeholder and formatter/cache seam: `host/src/domain/prompt_placeholders.py:35-68`; `host/src/domain/prompt_validator.py:28-49,83-185`; `host/src/infrastructure/llm/prompt_loader.py:26-202`.
- Full text passed through character/block chunk paths: `host/src/application/services/postprocessing_service.py:278-369,500-664,914-1025`; `host/src/application/services/blocks_post_processor.py:140-289,318-406`.
- Ordinary export retains raw/postprocessed semantics: `host/src/infrastructure/mcp/tools/export_transcription.py:303-355`.
- Executed context/cache evidence: `experiments/lmstudio/results_summaries/2026-07-13_host_application_shaped_structured_context_summary.md`; `experiments/lmstudio/results_summaries/2026-07-12_parallel_cache_gpu_runtime_audit.md`.
- Cross-track policies: `experiments/lmstudio/results_summaries/2026-07-13_task_specific_context_schema_policy.md`; `experiments/lmstudio/results_summaries/2026-07-13_structured_validation_migration_risks.md`.

## Limits and non-claims

- Source findings are static code-contract evidence; no host persistence, FTS, export, UI, or prompt migration was executed.
- The main context comparison covers one recording and one selected model. It supports architecture retirement, not broad summary-quality admission.
- No runtime tokenizer/template measurement was captured for this report; the direct-fit gate is specified but runtime-unexecuted.
- No summary writer, current-artifact table, staleness mechanism, semantic validator, or hierarchical resume path exists in the inspected production source.
- No physical prefix/KV-cache reuse is claimed.
- No existing legacy summary string is claimed trustworthy, current, or provenance-complete.
- No implementation, live call, model load, migration, commit, or push is authorized or completed here.
