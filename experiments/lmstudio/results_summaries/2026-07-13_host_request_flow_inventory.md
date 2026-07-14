# Host structured request-flow inventory

Date: 2026-07-13

Status: read-only source inventory. No live request, model operation, implementation, prompt inspection, or private artifact publication was performed.

Machine-readable companion: `2026-07-13_host_request_flow_inventory.json`.

## Decision

The current host application has two API-bound structured-output paths:

1. block-preserving text postprocessing, using strict `response_format.type=json_schema` on the OpenAI-compatible chat-completions route;
2. image analysis, using a separate strict vision schema on the same provider-neutral chat-completions client.

Current text-mode cleanup—including the normal short-microphone path and character-chunk fallback for long microphone or media text—returns free text. It does not bind a response schema and does not run JSON, completeness, protected-value, or semantic validation. The prompt system may shape the text, but the caller treats the result as plain text.

There is no implemented per-chunk or whole-recording summary request flow. A nullable `summary` field exists in the domain and database, but normal create currently writes `NULL`; this is reserved storage, not a summary pipeline.

Provider selection does not change the response contract. OpenRouter, Polza-compatible cloud, and LM Studio all use `POST {compat_base}/chat/completions`; provider builders vary headers, usage/cache fields, output limits, and local thinking controls. Both structured paths pass the same `response_format` object through all three builders.

## Classification vocabulary

- **API-bound JSON Schema:** the request contains `response_format={type: json_schema, ...}`.
- **Plain text:** the request omits `response_format`; the returned message content is accepted as text.
- **Prompt-only JSON:** a prompt asks for JSON but the request does not bind an API schema. No dedicated current request class was found; an arbitrary text-mode prompt could still do this, in which case the framework would treat the response as plain text.
- **Partially validated:** application parsing checks part of the business contract but is intentionally tolerant or does not enforce all closed-schema/business invariants.
- **Not implemented:** no production request owner or endpoint call exists.

## Current-state matrix

| Request class | Provider / endpoint | Request shape | Response contract | Validation | Retry / fallback | Persistence verdict |
|---|---|---|---|---|---|---|
| Generic existing-text postprocessing, text mode | OpenRouter, Polza-compatible cloud, or LM Studio; OpenAI-compatible `POST {compat_base}/chat/completions` | Independent system/user messages; optional cache prefix; no `response_format` | Free message text | Transport envelope and message-content extraction only; thinking tags are stripped. No JSON, schema, exact-boundary, protected-value, or semantic validator | Client retries timeout, rate-limit, and server classes with exponential backoff; LM Studio may receive one additional readiness retry. Failure is surfaced; caller retains original text as the explicit degraded value | Existing record is updated in `postprocessed_text` with usage/config metadata; raw `full_text` remains authoritative fallback |
| Short microphone cleanup | Same provider-neutral chat-completions route; direct microphone coordinator, not the shared file queue | Usually one current-text chunk under the microphone source view; no `response_format` | Free message text | Same plain-text validation gap as generic text mode | Same transport retry; model-load or request failure emits a degraded postprocessing error and keeps raw transcription text without labeling it LLM success | Transcription owns UUID and creation time before LLM work. Persisted captures are saved before postprocessing and later updated; ephemeral captures are not written |
| Long microphone cleanup, character-chunk fallback | Same provider-neutral chat-completions route | Character chunks using configured size/overlap; each request is independent; prompt may also include full text or context placeholders; no `response_format` | One free-text result per chunk, then ordered trim-and-join merge | No structural or cross-chunk completeness validation; merge preserves request index, not source IDs or timestamps | Same transport retry per request; orchestration is fail-fast for fatal errors. Original recording text remains available on failure | One application-owned transcription record; merged result updates `postprocessed_text`. Source segment timestamps stay outside model output |
| Long audio/video/file cleanup, text mode | Same provider-neutral chat-completions route through the shared queue tail | Media source view; character chunks only when stored blocks are unavailable or prompt does not select blocks mode; no `response_format` | Free text per chunk, merged in application order | Same plain-text validation gap | Transport retry plus queue-level timeout budget; failed optional LLM tail leaves the already saved transcription available for later reprocess | Whisper result is saved first; LLM tail updates the existing record. Queue job ID and transcription ID remain separate application-owned handles |
| Block-preserving postprocessing and reprocess | Same provider-neutral chat-completions route; used when the selected prompt is blocks-mode and blocks exist | `{blocks:[{id,text}]}` content plus strict closed JSON Schema in `response_format`; timestamps are omitted; chunks are planned on block boundaries | Intended `{blocks:[{id:int,text:string}]}` | API-bound schema plus application raw JSON parse and expected-ID coverage. Partial business validation: accepts a bare list, coerces `text` to string, filters extra IDs, but does not explicitly reject duplicate IDs or enforce returned order | Transport retry; then one extra application retry for invalid JSON or missing IDs; final fallback returns original blocks unchanged | Application-owned block indices select rows; start/end timestamps remain in storage. Accepted text updates per-block fields and merged `postprocessed_text`; metadata records chunk-to-block mapping |
| Per-chunk summary | No production endpoint owner | No production request shape | No production response contract | Not implemented | No summary-specific retry or fallback | No writer found. The reserved `summary` column is not populated by a request flow |
| Whole-recording summary | No production endpoint owner | No production request shape | No production response contract | Not implemented | No summary-specific retry or fallback | Domain/database field exists, but normal create writes `NULL`; no synthesis, update, or read-back owner was found |
| Image / vision analysis | OpenRouter, Polza-compatible cloud, or LM Studio; OpenAI-compatible `POST {compat_base}/chat/completions` | System message plus user multipart content containing text and one image data URI; strict closed vision JSON Schema in `response_format` | `{description, extracted_text, language, scene_type}` | API-bound schema plus application parse. Partial/tolerant post-parse policy: rejects extra fields and non-string values, defaults missing fields, maps an unknown scene type to `other`, and can recover some truncated JSON | Same transport retry; LM Studio has a narrow fallback from empty content to parseable structured JSON in `reasoning_content`; parser may attempt truncated-JSON recovery. Otherwise the image job fails; no plain-text vision fallback | Vision result receives application-owned UUID/creation time, is saved directly, and links to the queue job. Image jobs deliberately skip the text LLM tail |

## Provider payload seams

All text and vision generation reaches one client seam and one compat endpoint. The selected payload builder changes transport details, not task ownership:

| Provider family | Shared fields | Provider-specific fields | Structured-output handling |
|---|---|---|---|
| OpenRouter-compatible cloud | `model`, `messages`, optional `max_tokens` | authorization and attribution headers; `usage.include`; optional ephemeral cache-control message parts | Copies `response_format` unchanged when supplied |
| Polza-compatible cloud | `model`, `messages`, optional `max_tokens` | authorization; optional ephemeral cache-control message parts; usage returned without `usage.include` | Copies `response_format` unchanged when supplied |
| LM Studio local compat | `model`, `messages`, optional `max_tokens` | optional authorization; `cache_prompt=true`; `chat_template_kwargs.enable_thinking=false`; local compat base is normalized to `/v1` | Copies `response_format` unchanged when supplied |

The native LM Studio `/api/v1/*` namespace belongs to health and model lifecycle, not content generation. Generation remains on `/v1/chat/completions`.

## Validation boundaries

### Transport

The common client verifies HTTP success, parses the OpenAI-compatible envelope, extracts message content and usage, and classifies retryable transport errors. This is not task validation.

### Raw parse and schema

- Text mode: not applicable; output is accepted as text.
- Blocks mode: API-bound strict schema plus `json.loads` in the application.
- Vision: API-bound strict schema plus `json.loads`; recovery is separately observable only through logs, not a persisted parse verdict.

### Business identity

Block IDs are echoes of application-owned block indices. The parser checks missing expected IDs and removes extras, but exact count, uniqueness, and returned order are not fully enforced. Timestamps never enter the model response. Vision identity and persistence keys also remain outside the schema.

### Semantic quality

No current production path establishes groundedness, protected-value preservation, completeness, boundary safety, or summary quality. Schema validity therefore cannot be promoted to semantic or product acceptance.

## Persistence and ownership inventory

- `TranscriptionResult` generates a UUID and `created_at` in application code before persistence unless an ID is already supplied.
- Queue jobs own a separate UUID and queue timestamps; completion links a job to a transcription record.
- Speech segment IDs/timestamps and persisted block indices/start/end timestamps are application/storage state.
- Blocks-mode requests send only block `id` and `text`; accepted model text is reattached by application-owned ID.
- Postprocessing preserves `full_text` and writes `postprocessed_text`, processing mode, provider/model/prompt metadata, usage, and optional chunk-to-block mapping.
- Vision creates a new transcription-shaped record with application-owned identity and image metadata, then saves it directly.
- The summary field is reserved but not generated. Normal record creation explicitly stores `NULL`, even if a domain object happened to carry a summary value.

## Code seam inventory

Publication-safe evidence references use `host/` as the external source root.

| Concern | Evidence |
|---|---|
| Source-aware microphone/media routing and chunk settings | `host/src/domain/models/config/postprocessing.py:23-25,34-50,93-133` |
| Text-vs-blocks route | `host/src/application/services/postprocessing_service.py:232-386` |
| Plain-text request omits `response_format` | `host/src/application/services/postprocessing_service.py:930-1025` |
| Character chunk fallback | `host/src/application/services/postprocessing_service.py:843-890` |
| Blocks schema and request binding | `host/src/domain/schemas/block_schema.py:19-63`; `host/src/application/services/blocks_post_processor.py:175-196,394-445` |
| Blocks post-parse checks and tolerance | `host/src/application/services/blocks_post_processor.py:462-590` |
| Direct microphone coordinator, failure fallback, and persisted/ephemeral handling | `host/src/application/services/postprocessing_coordinator.py:118-155,167-223,225-391`; `host/src/services/transcription_service.py:1474-1540` |
| Shared queue text tail and persistence update | `host/src/services/queue_workers/llm_postprocess_executor.py:444-625` |
| Common compat client, retry policy, and endpoint | `host/src/infrastructure/llm/openai_compatible_client.py:547-720,885-976,1108-1176` |
| Cloud and local payload differences | `host/src/infrastructure/llm/payload_builders/openrouter.py:15-98`; `host/src/infrastructure/llm/payload_builders/polza.py:16-96`; `host/src/infrastructure/llm/payload_builders/lmstudio.py:17-79` |
| Vision schema, request, parse, and result construction | `host/src/domain/schemas/vision_schema.py:17-98`; `host/src/application/services/vision_processor.py:217-334,392-476` |
| Vision queue persistence and no text tail | `host/src/services/queue_workers/queue_worker.py:559-691`; `host/src/services/queue_workers/llm_postprocess_executor.py:479-491` |
| Domain identity, timestamps, and reserved summary | `host/src/domain/models/transcription.py:164-218,264-318` |
| Database summary reservation and create behavior | `host/src/infrastructure/storage/models.py:146-200`; `host/src/infrastructure/storage/components/crud_repository.py:87-157,950-979` |
| Per-block persistence by application-owned index | `host/src/infrastructure/storage/components/block_manager.py:251-296` |

## Gaps that matter for migration

1. Plain-text cleanup has no deterministic response contract or semantic acceptance layer.
2. Blocks mode is API-bound but its post-parser is less strict than the request schema: duplicate IDs, exact returned order, and strict text typing are not enforced explicitly.
3. Vision is API-bound but deliberately tolerant after generation; missing fields can become defaults and malformed output can be recovered without a persisted raw-parse classification.
4. Summary persistence exists without a request, validator, retry, fallback, or synthesis owner.
5. No current path persists separate transport, raw-parse, schema, business-identity, semantic, and product-behavior verdicts.
6. The same provider-neutral builders can carry future schemas, but builder capability does not itself define a safe application contract.

## Limits and non-claims

- This is source-contract evidence, not executed model evidence.
- Prompt files and private user content were not inspected or reproduced; therefore arbitrary prompt-only JSON instructions are not enumerated.
- No live endpoint, model, cloud provider, persistence round trip, or UI flow was exercised.
- The inventory does not claim summary support, semantic correctness, model admission, audio accuracy, OCR accuracy, or migration readiness.
