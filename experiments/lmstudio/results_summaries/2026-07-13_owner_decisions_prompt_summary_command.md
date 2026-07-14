# Owner decisions: summary placeholder, legacy prompts, and command retention

Date: 2026-07-13

Status: read-only owner-decision recommendation. No host or LabKit runtime code, prompt, configuration, database, model, provider, clipboard, migration, commit, or push was changed or exercised.

Machine-readable companion: `2026-07-13_owner_decisions_prompt_summary_command.json`.

## Executive decision

Approve the following bounded policy now:

| Decision | Classification | Recommended default |
|---|---|---|
| O1 — canonical summary placeholder | `approve_now` | Use `{document_summary}` as the only summary-consumption placeholder. Recording scope belongs in `SummaryArtifact.scope_kind`, never in a second placeholder name. |
| O11 — command history persistence and retention | `approve_configurable_default` | Start with `shadow_ephemeral`: no durable command history, FTS, export, display, copy, paste, or mutation of transcription fields. Durable command artifacts remain disabled until transaction/read-back, retention, privacy, and deletion behavior pass offline gates and receive separate approval. |
| O12 — legacy custom prompt disposition | `approve_now` | Every prompt gets an explicit manifest state: `native`, `legacy`, or `blocked`. Existing prompts import as `legacy` unless an exact manifest and compatibility preview prove native behavior. Unknown or contradictory prompts fail closed as `blocked`. |

These decisions close the vocabulary and initial safety defaults. They do not approve summary generation, summary injection, command execution, durable command history, prompt migration, or live shadow traffic.

## Evidence boundary

### Current static host contract

- The prompt registry and loader recognize exactly `{chunk}`, `{blocks_json}`, `{full_text}`, `{clipboard}`, and `{context}`. There is no summary placeholder or prompt manifest.
- Prompt files are loaded from a writable user directory with a bundled fallback; a user file with the same filename wins. Filename and placeholder inference currently select behavior.
- The current repository prompt set contains 10 files: 7 text-shaped, 2 block-shaped, and 1 vision-shaped. Four use `{full_text}`. The two block prompts both ask for a bare JSON array, while the bound runtime schema requires a closed object containing `blocks`; the parser currently tolerates both shapes.
- `TranscriptionResult` and SQLite rows contain a nullable bare `summary`. Normal create writes `NULL`; load restores it. No production summary request, validator, lifecycle, refresh, or read-back owner exists.
- FTS5 indexes `full_text`, `postprocessed_text`, `summary`, and `user_notes`; summary-scoped search uses the summary column. Settings transfer includes the bare summary and rebuilds FTS. Ordinary transcription export still selects raw or postprocessed text and never substitutes summary.
- Current microphone cleanup emits `postprocessing_complete` with generic `postprocessed_text`; clipboard automation copies that value or falls back to the original transcript. Errors also copy/paste the original transcript for microphone flows. There is no command classifier, command event, command artifact, or command-specific persistence path.
- Persisted microphone transcriptions are saved before postprocessing; ephemeral captures are not saved. The existing event contract cannot safely express a command result without overloading transcription semantics.

### Retained executed evidence

- The retained structured-context study executed 202 heterogeneous calls on one recording and one selected model. Full-recording-per-chunk context was materially more expensive without stable proportional benefit; this supports retiring `{full_text}` as a default repeated context, not deleting authoritative full text.
- The retained structured-vision closure showed that raw/schema success and semantic acceptance are separate. It does not validate command answers, summary quality, or prompt migration.

### Recommendations and live-unverified assumptions

- The three decisions below are target policy derived from static contracts and retained bounded evidence. None has run end to end in the host application.
- Installed user prompt inventories outside the inspected repository were not scanned. Their counts, digests, placeholders, and compatibility states remain deployment-local facts.
- No external documentation was required to resolve these product-owned naming, migration, and retention choices.

## O1 — one canonical summary placeholder

### Alternatives

| Alternative | Result | Reason |
|---|---|---|
| `{document_summary}` only | **Approve** | Provider-neutral across recordings, files, and future document kinds; scope stays in typed artifact metadata. |
| `{recording_summary}` only | Reject | Couples prompt vocabulary to one source kind and conflicts with the provider-neutral contract already selected by the synthesis. |
| Support both names | Reject | Creates synonym drift, two migration paths, ambiguous digests, and accidental task/provider differences. |
| Reuse or alias `{full_text}` | Reject | Full source and lossy summary differ in authority, size, provenance, fallback, and freshness. |

### Contract

`{document_summary}` has a manifest-owned requirement level:

- `forbidden`: any supplied summary is a planning error;
- `optional`: inject only a current accepted provenance-bound artifact; otherwise remove the whole manifest-owned section deterministically;
- `required`: absence or ineligibility fails before transport, or creates a separate prerequisite plan; it never substitutes full text or an empty required value.

The value is advisory reference context. The request retains the artifact ID/version, source revision/digest, scope kind, and prompt digest outside model-visible text. Only `current` accepted artifacts are eligible. `legacy_unverified`, `stale`, `partial`, `failed`, and `superseded` are ineligible.

### Typed zero-side-effect failures

- `prompt_placeholder_unknown`: an unrecognized placeholder is present; no request, persistence, or clipboard action.
- `summary_forbidden_supplied`: a manifest forbids summary context but one was attached; no request.
- `summary_required_unavailable`: a required current artifact is absent; no fallback to `{full_text}`, no request.
- `summary_ineligible`: the artifact is stale, unverified, partial, failed, superseded, or source-mismatched; no request.
- `summary_provenance_mismatch`: artifact/source revision or digest does not match the frozen request; no request.
- `prompt_placeholder_leak`: rendering leaves a literal placeholder; no request.

### Rollback seam

A versioned task/manifest kill switch disables summary consumption and increments request generation so in-flight results cannot commit. Rollback returns the task to current-target plus approved boundary context. It does not rewrite prompt history, mutate summary artifacts, restore `{full_text}` automatically, or delete authoritative source/search/export data.

### Minimum acceptance tests

1. Registry and loader have one summary token only; `{recording_summary}` and any alias fail admission.
2. Forbidden, optional-present, optional-absent, required-present, and required-absent render deterministically with no literal placeholder leakage.
3. Only current source-matching artifacts are injected; every ineligible lifecycle/provenance state fails before transport.
4. Local/cloud fake adapters receive byte-equivalent rendered logical messages and the same summary provenance digest.
5. `{full_text}` is never populated from a summary and `{document_summary}` is never populated from full text.
6. Kill-switch and stale-generation tests prove no late persistence or clipboard effect.
7. Raw/postprocessed FTS and ordinary export remain unchanged when summary injection is disabled.

## O12 — legacy prompt inventory and migration states

### State model

- `native`: an explicit manifest fixes task kind/version, input shape, output contract, placeholders, context/translation policy, schema digest, validators, fallback, and provider-neutral parity. Native is never inferred from filename or one placeholder.
- `legacy`: existing behavior remains available behind an explicit compatibility manifest and kill switch. It is not silently promoted to structured output. `{full_text}` remains deprecated and size/context gated.
- `blocked`: no transport is allowed because structure, placeholders, task intent, translation target, or output contract is unknown or contradictory.

Unknown state, missing manifest, digest mismatch, changed file after inventory, or an unreadable prompt all resolve to `blocked`; they never fall through to the old inferred path after manifest enforcement is enabled.

### Inspected bundled inventory

The following inventory records only source filenames, SHA-256 identities, and structural compatibility; prompt content is not reproduced.

| Prompt | Placeholders | Initial migration state | Native target / blocker |
|---|---|---|---|
| `lecture_notes.md` | `chunk` | `legacy_plain_text` | Candidate `native` only after explicit text manifest, structured/plain output choice, semantic policy, and preview. |
| `mic_cloud.md` | `chunk` | `legacy_plain_text` | Keep ordinary microphone cleanup unchanged initially; later native text migration is separate. |
| `mic_local.md` | `chunk` | `legacy_plain_text` | Same logical task as cloud must use one provider-neutral manifest before native admission. |
| `sk.md` | `chunk`, `clipboard` | `legacy_plain_text` | Clipboard use needs an explicit user-selected auxiliary-context policy and absent/present fixtures. |
| `tg_style.md` | `chunk` | `legacy_plain_text` | Candidate native text only after manifest and compatibility preview. |
| `test_translate.md` | `chunk`, `full_text` | `legacy_full_text` | Must remove repeated full-text context, add typed translation metadata, and choose a new prompt revision. |
| `translate.md` | `chunk`, `full_text` | `legacy_full_text` | Same migration requirements; no alias to summary. |
| `corrector_blocks.md` | `blocks_json`, `full_text` | `legacy_full_text_blocks` | **Blocked for native admission** until bare-array instructions become the closed `{blocks:[...]}` envelope and repeated full-text context is removed or explicitly legacy-gated. |
| `translate_blocks.md` | `blocks_json`, `full_text` | `legacy_full_text_blocks` | Same object-envelope blocker plus typed translation metadata. |
| `vision_default.md` | none; vision-specialized | `legacy_vision` | Candidate native only under an explicit vision task/schema manifest; absence of text target is valid only for that task. |

Observed denominators: 10 prompts total; 7 text-shaped, 2 block-shaped, 1 vision-shaped; 4/10 use `{full_text}`; 2/10 have a prompt/schema shape contradiction for native block admission.

Installed custom prompts must be inventoried locally without publishing content. Store a safe local identity, full content digest, source (`bundled` or `custom`), section presence, placeholder set, override relationship, and disposition. A custom override inherits nothing from the bundled file with the same name except presentation linkage; its digest receives its own decision.

### Admission and migration rules

1. Freeze an inventory generation and prompt digest before compatibility analysis.
2. Block unknown placeholders, both target placeholders, no target placeholder except an explicit vision task, missing sections, target-language conflict, and schema/output-shape conflict.
3. Import existing `{chunk}` prompts as legacy plain text by default.
4. Import `{blocks_json}` prompts as legacy until their output instructions and exact schema agree; a tolerant current parser does not confer native trust.
5. Keep `{full_text}` only in deprecated legacy manifests with context-fit and call telemetry; never reinterpret it as `{document_summary}`.
6. Create a new immutable prompt revision for every native migration. Preserve the prior revision and manifest for rollback during the compatibility window.
7. Run offline present/absent optional rendering, digest, placeholder-leak, schema-binding, fake-adapter parity, and fallback tests before activation.
8. Remove `{full_text}` from the accepted legacy registry only after installed inventory is zero or an explicit owner waiver is recorded.

### Typed zero-side-effect failures

- `prompt_inventory_stale`, `prompt_digest_mismatch`, `prompt_unreadable`;
- `prompt_sections_invalid`, `prompt_placeholder_unknown`, `prompt_target_shape_ambiguous`, `prompt_target_missing`;
- `prompt_task_manifest_mismatch`, `prompt_translation_target_conflict`, `prompt_schema_contract_mismatch`;
- `prompt_legacy_disabled`, `prompt_manifest_blocked`.

Every failure occurs before provider selection and produces no model request, prompt rewrite, summary substitution, persistence update, clipboard copy, or auto-paste.

### Rollback seam

Activation is by immutable prompt/manifest revision. Rollback selects the previous admitted revision and advances request generation; it never rewrites a custom file, aliases placeholders, or reclassifies a changed digest. Disabling a native manifest leaves the original source authoritative and either selects an explicitly admitted legacy revision or returns a typed unavailable outcome.

### Minimum acceptance tests

1. Inventory detects bundled/custom override pairs and digest changes without logging raw prompt content.
2. Every prompt has exactly one `native`, `legacy`, or `blocked` state; unknown states fail closed.
3. Unknown/both/missing target placeholders, section errors, vision exception, translation conflict, and schema mismatch cover all admission branches.
4. Bare-array block instructions cannot bind the native closed object schema.
5. Existing `{chunk}` prompts are not auto-promoted; native opt-in requires an immutable manifest and preview.
6. `{full_text}` retirement and `{document_summary}` introduction have an explicit no-alias test.
7. Local/cloud fake payloads preserve the same admitted manifest and logical request.
8. Rollback restores the exact previous revision while stale in-flight generations remain inert.

## O11 — initial command history mode

### Alternatives

| Mode | Result | Behavior |
|---|---|---|
| `disabled` | Safe bootstrap / global kill switch | No command request and no command artifact. Before classifier activation, the application retains its existing dictation behavior. |
| `shadow_ephemeral` | **Initial configurable default after offline gates and separate live authorization** | Build and validate a distinct command candidate in memory only; emit privacy-safe categorical/count/digest telemetry; no durable history, FTS, export, user-visible answer, copy, paste, or transcription mutation. |
| `persisted` | Not initially approved | Requires a distinct durable command table/artifact, transaction/read-back, retention/deletion/export policy, UI history contract, privacy review, and promotion approval. Never use `postprocessed_text` or `summary`. |

`shadow_ephemeral` means no command-history retention. Candidate content lives only for the bounded current request/session and is discarded on terminal outcome or restart. Raw command text, prompt, and provider output are not publication-safe telemetry.

### Command contract and side-effect fence

Classification precedes prompt selection. A valid anchored command uses a separate prompt, strict closed `{answer_text: string}` response, separate event/artifact type, immutable attempts, and generation/cancellation fences. It does not send the trigger, full recording, summary, cleanup prompt, or clipboard by default.

Only a current, strictly validated, semantically accepted command may materialize `display_text`, `copy_text`, and `paste_text` in a later user-visible canary. In initial shadow mode all three projections remain unavailable even for a valid candidate.

### Typed zero-side-effect failures

- `command_disabled`: classifier/execution kill switch is off; no command request.
- `command_invalid_empty`: anchored trigger has no command text; no cleanup fallback, request, copy, paste, or success artifact.
- `command_route_unsupported`: strict schema capability is not verified; no prompt-only downgrade.
- `command_transport_failed`, `command_completion_unsafe`, `command_raw_parse_failed`, `command_schema_failed`, `command_semantic_rejected`.
- `command_cancelled`, `command_stale_generation`, `command_persistence_disabled`.

For every command failure, the original `MODEL:` transcript and extracted command text are never copied or pasted as an answer. No command path mutates source transcript, `postprocessed_text`, summary, summary FTS, or ordinary transcription export.

### Promotion requirements for persisted history

Durable command history remains disabled until all of these are approved and tested:

1. distinct command artifact/table and command-specific completion/error/cancel events;
2. atomic commit or explicit recoverable pending/committed state;
3. read-back of transcript linkage, request generation, accepted attempt, prompt/schema/validator versions, outcome, and projections;
4. explicit retention duration, deletion semantics, export/import behavior, FTS inclusion or exclusion, and privacy-safe telemetry;
5. no cascade from deleting a command artifact to source transcription/media;
6. cancellation and rollback races at every pre-commit boundary;
7. separately authorized shadow evidence and task-specific semantic acceptance.

### Rollback seam

A command-contract kill switch advances request generation and makes every in-flight command inert. Future captures return to the pre-existing dictation classifier behavior. Shadow state is discarded. Previously durable command artifacts, if a later stage ever approves them, remain readable under their schema/validator versions until the approved retention/deletion policy acts; rollback does not relabel them as transcription cleanup.

### Minimum acceptance tests

1. Trigger classifier matrix and exact suffix ownership; trigger-only input is invalid command, never cleanup.
2. Separate dictation and command prompt/event/artifact paths; command cannot write transcription fields.
3. Strict raw object/schema checks reject empty, plain, fenced, wrapped, repaired, coerced, extra/missing-field, reasoning-leak, repetition, and length-exhausted outputs.
4. Zero copy/paste/display/history on invalid, failed, cancelled, stale, unsupported, or shadow-only outcomes.
5. Initial `shadow_ephemeral` mode leaves database, FTS, transfer, ordinary export, and clipboard unchanged.
6. Kill switch invalidates in-flight requests and restores ordinary dictation behavior without replaying a command result.
7. Any future persisted mode passes transaction failure injection, deterministic recovery, read-back, retention/delete/export, and no-cascade tests before promotion.

## Cross-decision order

1. Approve O1 vocabulary and O12 state model.
2. Inventory all installed prompts by digest; do not migrate content automatically.
3. Implement summary artifact ownership, current projection, staleness, FTS filtering, transfer/export, and read-back before populating `{document_summary}`.
4. Add manifests and fake-adapter parity; keep all existing prompt behavior legacy until each prompt is explicitly admitted.
5. Add command classification and artifact/event boundaries offline with history disabled.
6. Permit only separately authorized `shadow_ephemeral` command execution after offline side-effect and cancellation gates pass.
7. Consider prompt activation, summary injection, user-visible command output, and durable command history as separate promotions.

## Evidence map

Publication-safe `host/` paths alias the read-only external source tree.

- Placeholder registry, validation, formatting, cache split, and custom override: `host/src/domain/prompt_placeholders.py:35-68`; `host/src/domain/prompt_validator.py:83-185`; `host/src/infrastructure/llm/prompt_loader.py:26-202,205-365`.
- Source-aware prompt selection and legacy config fields: `host/src/domain/models/config/postprocessing.py:23-31,70-84,100-133,148-206`.
- Summary storage, create/load, FTS, transfer, and ordinary export: `host/src/domain/models/transcription.py:171-209`; `host/src/infrastructure/storage/components/crud_repository.py:87-157,952-973`; `host/src/infrastructure/storage/migrations.py:545-631`; `host/src/infrastructure/storage/components/fts_search_provider.py:374-410`; `host/src/infrastructure/storage/sqlite_repository.py:583-731`; `host/src/infrastructure/mcp/tools/export_transcription.py:303-355`.
- Microphone persistence, events, and clipboard behavior: `host/src/services/transcription_service.py:1459-1540`; `host/src/application/services/postprocessing_coordinator.py:167-195,225-409`; `host/src/domain/events/postprocessing_events.py:31-99`; `host/src/services/clipboard_service.py:193-306`; `host/tests/test_clipboard_service.py:1240-1357`.
- Current block prompt/schema contradiction and tolerant parser: two inspected bundled block prompts; `host/src/domain/schemas/block_schema.py:19-63`; `host/src/application/services/blocks_post_processor.py:462-590`.
- Retained architecture/evidence reports: `2026-07-13_provider_neutral_prompt_structured_contracts.md`; `2026-07-13_summary_artifact_full_text_retirement.md`; `2026-07-13_microphone_dictation_command_contract.md`; `2026-07-13_host_request_flow_inventory.md`; `2026-07-13_task_specific_context_schema_policy.md`; `2026-07-13_structured_validation_migration_risks.md`; `2026-07-13_local_structured_integration_red_team.md`.

## Non-claims

- No installed user-prompt population outside the inspected repository was inventoried.
- No current prompt was migrated, rewritten, enabled, disabled, or proven semantically correct.
- No summary producer, current-artifact lifecycle, prompt injection, command classifier, command artifact, retention policy, or durable command history exists as a result of this report.
- No live model/provider request, clipboard action, FTS round trip, persistence migration, or cancellation race was executed.
- The recommendations do not approve command answer quality, summary quality, a provider/model route, or production rollout.
