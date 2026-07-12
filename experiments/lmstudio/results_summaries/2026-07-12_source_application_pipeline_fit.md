# Source-application pipeline fit audit

Date: 2026-07-12

Status: offline, read-only reconciliation. No model was loaded, no generation or network request was made, and no source-application file was changed.

## Decision

The evidence verifies a useful but narrow subset of the active text-postprocessing pipeline. The strongest match is the long plain-text request shape: a full transcript is supplied as stable reference context, a separately delimited current chunk is the only requested output, the first chunk runs synchronously, later chunks may overlap under a bounded semaphore, and the LM Studio compatibility payload carries a prompt-cache hint with reasoning disabled.

That is not an end-to-end application admission. No retained experiment starts from a real microphone recording or real video and then follows source-specific configuration, chunk planning, retry/fallback, persistence, and final merge through the active application path. Native JSON and parallel probes prove component capabilities, but the active block-mode request combines full context, current block JSON, exact IDs, one parse retry, original-block fallback, persistence, and merge; that complete contract has not been executed as one retained model run. Translation evidence is invalid for the requested Russian-to-English direction because the inspected active translation templates specify the opposite direction.

Machine-readable companion: `2026-07-12_source_application_pipeline_fit.json`.

## Classification scale

- `VERIFIED`: retained generation evidence matches the material active request shape and validates the stated bounded behavior.
- `PARTIAL`: some request or runtime components match, but a material source-path, merge, retry, direction, or end-to-end boundary is absent.
- `NOT_TESTED`: no retained generation traverses the relevant active behavior.
- `INVALID`: the retained or configured evidence answers a different contract and cannot support the requested conclusion.

## Active pipeline contract inspected

Private artifact class inspected: active source-application code for source-aware configuration, prompt loading, text and block chunk planning, request construction, LM Studio payload construction, retry handling, warmup ordering, bounded concurrency, block validation/fallback, persistence, and merge. The audit records behavior only; it does not reproduce private prompts, identifiers, paths, or user text.

Facts from that inspection:

1. Microphone uses a dedicated coordinator; audio and video use the shared queue tail. Both ultimately call the same postprocessing service with a source-specific pipeline snapshot.
2. Microphone has a distinct configuration/prompt view. Every non-microphone text source normalizes to the media view; audio and video do not have separate LLM request constructors.
3. Text mode sends the complete transcript as `full_text` and one current chunk as `chunk`. The first chunk is awaited before later chunks are launched.
4. When caching is admitted, the stable full-text portion is split from the per-chunk suffix. The LM Studio payload still uses the compatibility API's prompt-cache hint rather than provider-specific ephemeral cache controls.
5. Remaining text chunks are bounded by the configured semaphore and start delay. The application fails fast for not-yet-started chunks after a fatal error, while already-started requests may finish.
6. Block mode sends compact `{id, text}` items with native JSON schema, requires the expected IDs, retries a parse/amnesia failure once, filters extra IDs, and falls back to the original blocks after the second invalid response.
7. Text-mode merge is order-preserving concatenation. Block-mode merge sorts updates by ID, joins block text, persists per-block updates, and preserves the chunk-to-block map.
8. The compatibility client retries bounded timeout, rate-limit, and server failures with exponential backoff. This transport retry is separate from block mode's one parse/schema retry and original-block fallback.
9. The inspected translation templates are English-to-Russian in both text and block forms. They do not establish Russian-to-English behavior.

Interpretation: the benchmark should be judged against this combined contract, not merely against generic JSON validity, isolated concurrency, or a prompt containing the words “full transcript.”

## Coverage verdicts

| Surface | Verdict | Evidence and fit |
|---|---|---|
| Microphone one-shot | `NOT_TESTED` | Repository reports explicitly state that transcript-only calls are not audio-grounded microphone evidence. No retained call traverses microphone capture, dedicated coordinator/model ensure, source-specific prompt selection, and final application outcome. |
| Long microphone chunks | `PARTIAL` | Five cold repeats per model used one long plain early chunk with full context and explicit current-chunk isolation. This closely matches text request construction, but it covers one frozen transcript and one chunk, not the dedicated microphone owner path, later parallel chunks, retry, merge, or persistence. |
| Long video | `NOT_TESTED` | No retained real-video early/middle/late chunk-and-merge run exists. Text experiments do not cover extraction, source classification, media configuration, queue ownership, or final merged video transcript behavior. |
| Plain text | `VERIFIED` | The controlled long/plain calls preserve the material `full_text` plus current-chunk separation and direct plain output. All four models completed five cold repeats; quality remained model-dependent. Verification is bounded to the frozen early-chunk cell, not whole-record admission. |
| Timestamped context | `PARTIAL` | Controlled timestamped calls exist, but timestamped full-context representation is not the active plain or block request shape. It also cost 29.6% more input tokens and produced the only observed boundary/length failure. Useful as an adverse control, not as application-path validation. |
| JSON blocks | `PARTIAL` | Native structured calls and compact-schema P2/P4 probes prove JSON/schema/ID capability. The controlled long JSON representation returned plain text, while active block mode requires full context, current block JSON, native schema, exact IDs, parse retry/fallback, persistence, and merge together. That combination is absent. |
| Russian-to-English translation | `INVALID` | No retained translation generation exists, and the inspected active templates implement English-to-Russian. Opposite-direction templates cannot validate Russian-to-English quality or pipeline fit. |
| Warmup | `PARTIAL` | Active code awaits chunk 1, optionally waits a configured delay, then launches remaining work. Loaded-session evidence shows faster follow-ups, but no source-path run binds the event, delay, identical prefix, later requests, and direct cache telemetry. Physical KV reuse remains unproven. |
| P2/P4 | `PARTIAL` | True P2 overlap and repaired compact-schema P4 were measured. P4 passed 80/80 requests after removing request-specific positional grammar. These probes did not use the complete active long-transcript request, source-specific pipeline, retry/fallback, persistence, or merge. P2 is the conservative application rehearsal level; P4 is conditional on compact grammar and strict post-validation. |
| Merge | `NOT_TESTED` | Active text and block merge algorithms exist and are unit-level contracts, but no retained model experiment validates end-to-end early/middle/late output ordering, overlap effects, missing/duplicate block handling, persistence, and final semantic completeness. |

## Request-shape comparison

| Active behavior | Retained evidence | Fit |
|---|---|---|
| Stable full transcript plus separately authoritative current chunk | Long plain and controlled representation calls | Strong for one early plain cell; incomplete across chunks and source paths |
| Source-aware microphone versus media configuration | No source-path generation artifact | Missing |
| Block-mode current items with exact IDs and native schema | Native correction and compact P2/P4 | Component-level only; no full active block request |
| First synchronous chunk before later concurrent chunks | Loaded-session and separate concurrency probes | Components were measured separately, not as one active sequence |
| Prompt-cache hint and stable-prefix construction | Product-shaped compatibility requests and loaded timing | Hint observed; physical reuse not measured |
| Transport retry plus block parse retry/original fallback | No retained controlled failure/recovery sequence | Missing |
| Ordered text merge or ID-sorted block merge with persistence | No complete generated multi-chunk application run | Missing |
| Translation direction | Active templates are opposite to requested direction | Invalid for requested conclusion |

## Minimal remaining calls

Only calls that close a decision-relevant application-shaped gap are recommended.

1. **Plain multi-chunk application rehearsal: three calls.** Use one frozen long source and the active serialized request builder for early, middle, and late chunks. Keep one loaded instance, execute chunk 1 synchronously, then execute chunks 2–3 at P2. Capture exact request/prefix/chunk digests, finish/usage, boundary checks, ordered merge, and zero-loaded cleanup. This closes warmup, P2, later-chunk, and plain merge evidence with three calls.
2. **Block-mode application rehearsal: three calls, plus at most one retry.** Use the same three source ranges through the active compact block schema, exact IDs, persistence projection, and final merge. Permit the application's single parse retry only if an arm is invalid; record both attempts and the original-block fallback decision rather than counting fallback as model success. This closes JSON blocks and block merge without a broad matrix.
3. **Microphone one-shot: one call only after audio-grounded authorization.** Run one real short microphone capture through the dedicated owner path and source-specific prompt. Text-only replay is insufficient. No long-microphone matrix is justified until this route passes.
4. **Long video: three calls only after a real video source is authorized.** Use early/middle/late media chunks plus final merge through the media queue path. Do not infer this from audio or frozen transcript text.
5. **Russian-to-English translation: zero calls now.** First create or select the correct direction-specific active template under a separate application change/review. Calls against the current opposite-direction template would be invalid evidence.

No extra timestamped-context calls are recommended. No additional generic P4 calls are needed: compact-schema P4 capability is already closed, while the missing question is application-shaped block execution and merge.

## Fact, interpretation, and hypothesis boundary

Facts:

- Five cold long/plain calls per model completed on one frozen early chunk.
- The controlled representation set contains 27 retained E4B/12B/26B calls and lacks the other 27 planned rows.
- Compact generic-schema P4 passed 80/80 measured requests; request-specific positional grammar failed before generation.
- No retained microphone-audio, real-video, translation, or complete merge generation belongs to this evidence set.
- The active request builder supplies a prompt-cache hint and disables thinking for LM Studio compatibility requests.

Interpretations:

- Long/plain is the closest verified request-shape match, but it is not full application admission.
- JSON and concurrency capabilities are necessary components, not proof of the combined block pipeline.
- Timing improvement is insufficient to claim physical cache reuse.

Hypotheses:

- The 12B QAT candidate is the strongest next application-shaped block/plain rehearsal candidate because it combined complete long/plain cleanup with the best retained structural result.
- A three-call P2 rehearsal may validate warmup and merge without needing a larger benchmark, provided every request and merge boundary is captured fail-closed.

## Evidence sources

Repository evidence:

- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_last_day_evidence_inventory.md`
- `experiments/lmstudio/results_summaries/2026-07-12_long_context_representation_analysis.md`
- `experiments/lmstudio/results_summaries/2026-07-12_small_gemma_long_context_json_forensics.md`
- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_whisper_structured_parallel_statistics.md`
- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_native_structured_output_correction.md`
- `experiments/lmstudio/source_shaped_rehearsal/v1/README.md`
- `experiments/lmstudio/source_shaped_rehearsal/v1/manifest.json`

Owner-only evidence classes inspected:

- active source-aware configuration and request-construction code;
- active text/block chunk planning, warmup, concurrency, retry/fallback, persistence, and merge code;
- active LM Studio compatibility payload construction;
- active direction-specific translation templates;
- retained private long/plain, representation, native structured, and parallel response artifact classes described by the public reports.

## Unresolved evidence gaps

- No audio-grounded microphone postprocessing result.
- No dedicated microphone owner-path generation artifact.
- No complete active block-mode request with full context, exact IDs, retry/fallback, persistence, and merge.
- No real-video extraction-to-merge result.
- No Russian-to-English active template or generation result.
- No direct physical KV-cache telemetry.
- No application-shaped P4 long-context run; current P4 evidence is compact and bounded.
- No complete generated early/middle/late merge with semantic review.
