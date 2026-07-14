# Task-specific context and schema policy

Date: 2026-07-13

Status: read-only architecture recommendation from retained evidence. No live request, model operation, implementation, or production admission is part of this report.

Machine-readable companion: `2026-07-13_task_specific_context_schema_policy.json`.

## Decision

Use task-specific context rather than one universal full-context request:

- **Short microphone cleanup:** current-only. A short capture is the complete target; no neighboring context exists unless the application has already split it into blocks.
- **Long microphone or file cleanup:** current target blocks plus the previous tail block and next head block as reference-only boundary context.
- **Per-chunk summary:** current chunk only. Boundary context is an explicit fallback for an interrupted thought, not the default.
- **Whole-recording summary:** either one direct full-recording request for a compact overview, or hierarchical synthesis over ordered current-only chunk summaries for detailed chronological notes.
- **Generic text postprocessing:** current-only for a self-contained input; boundary-neighbor context for a chunked, identity-preserving transform. Do not send the full document with every chunk by default.
- **Image analysis:** the current image only, with an API-bound strict schema selected for the requested image task. Transcript-neighbor context policies do not transfer to images.

For block-preserving transforms, use a compact generic response containing only application-owned block IDs and model-authored text. The application remains authoritative for recording, document, image, chunk, and block identity; source order; timestamps; protected values; retry and fallback state; and persistence.

**Explicit rejection:** default full-transcript-per-chunk is unsupported. In the bounded context study it was much more expensive, did not provide a stable semantic gain, caused one first-pass block-boundary attribution defect, and produced one repeated malformed length-exhausted cleanup response.

## Evidence boundary and denominators

### Structured text context study

One frozen sanitized recording and one selected model produced 202 heterogeneous calls:

| Evidence group | Calls | HTTP 200 | Parseable or practically valid structured output | Role |
|---|---:|---:|---:|---|
| Primary cleanup, chunk summary, and whole summary | 157 | 157 | 155 | First-pass context comparison |
| Repeat and cache probes | 33 | 33 | 32 | Repeatability and timing signals |
| Short-context parallel screening | 12 | 12 | 12 | Bounded structural and semantic screening |
| **Total** | **202** | **202** | **199** | Mixed tasks; not 202 independent quality observations |

The primary series contained:

- 12 structured cleanup calls: 3 representative positions × 4 context strategies;
- 140 per-chunk summary calls: 35 chunks × 4 context strategies;
- 5 whole-recording summary calls.

Cleanup produced 36 evaluated output blocks with exact source IDs in all 12 first-pass calls. This enabled deterministic external timestamp reattachment, but no persistence/read-back or subtitle-export round trip was executed.

Per-chunk summary practical validity was:

| Context strategy | Valid structured output | Median prompt tokens | Median latency |
|---|---:|---:|---:|
| Current only | 35/35 | 786 | 8.04 s |
| Boundary neighbors | 33/35 | 1,040 | 8.22 s |
| Adjacent chunks | 34/35 | 2,107 | 8.60 s |
| Full recording | 35/35 | 23,099 | 20.20 s |

Full-recording context for every chunk consumed about 807,600 prompt tokens and 700.7 seconds of summed request time across 35 calls. Current-only consumed about 26,700 prompt tokens and 274.9 seconds, without a proportional semantic loss in the reviewed outputs.

### Long-context representation evidence

A separate controlled slice inspected 27 early/middle/late outputs across three models and three full-context representations. Direct review found 24/27 complete outputs and 26/27 chunk-isolated outputs. Structured full-context representations cost about 28–30% more input tokens than plain text. This evidence shows representation and boundary risks; it does not prove that a full document should accompany every chunk.

### Structured vision evidence

The completed vision run executed 40/40 authorized calls across four models and four image fixtures:

- no transport error: 40/40;
- raw JSON and independent schema pass where applicable: 36/36;
- native plain image baselines, non-JSON by design: 4/4;
- exact visible text: 25/39 image rows;
- salient text complete: 31/39;
- no unsupported claim: 36/39;
- no forbidden private claim: 39/39.

This confirms bounded image transport and API-bound schema capability. It does not establish binary semantic admission, comparative model ranking, broad OCR accuracy, or production readiness.

### Source-path evidence versus executed evidence

Read-only host-application source inspection confirms that current block planning already identifies previous-tail and next-head boundary blocks, block requests already use API-bound JSON Schema, and stored blocks carry IDs and timestamps outside the model response. Source inspection is architecture evidence, not an executed model denominator. No retained run covers an audio-grounded short microphone path, the complete source-to-persistence block path, or a generic summary feature in the host application.

## Context policy matrix

| Task | Current only | Boundary neighbors | Adjacent chunks | Full recording | Recommended policy |
|---|---|---|---|---|---|
| Short microphone cleanup | **Default.** The short capture is the complete target. | Not normally applicable; use only if the application has split a boundary. | Reject by default. | Equivalent to current-only only when the capture is genuinely one target. | Current-only structured transform; audio-grounded quality remains untested. |
| Long microphone/file cleanup | Conservative but may leave an interrupted boundary unresolved. | **Default.** Previous tail and next head are reference-only; current blocks are the only output target. | Reject by default; no stable gain and one context-driven questionable correction were observed. | Reject per chunk; boundary leakage, output expansion, latency, and cost outweigh observed benefit. | Boundary-neighbor compact blocks with fail-closed ownership checks. |
| Per-chunk summary | **Default.** Best observed locality, reliability, cost, and coverage. | Targeted fallback only for a clearly interrupted thought. | Reject by default; neighboring material can leak into the summary. | Reject per chunk; it globalizes framing and multiplies cost. | Current-only constrained summary. |
| Whole-recording summary | Used as inputs to hierarchical synthesis, not as the final complete view. | Not useful as the primary whole-recording strategy. | Not useful as the primary whole-recording strategy. | **Allowed once.** Direct full input for a compact overview. | Fast: direct full request. Detailed: ordered current-only chunk summaries followed by synthesis. |
| Generic text postprocessing | **Default for one self-contained input.** | **Default for chunked identity-preserving text.** | Reject by default. | Allowed once only when the task itself is document-level and fits safely; not repeated for every chunk. | Choose by target granularity, not by source label. |
| Image analysis | **Default.** One current image and its explicit task. | Not applicable unless a future multi-image product contract defines relations. | Not applicable by default. | Not applicable to single-image analysis. | Current image plus task-specific strict schema; validate semantics separately. |

## Contract-level schema policy

The examples below describe response contracts, not private prompts or provider-specific payloads. Bind them through the API's strict JSON Schema field when supported. Keep schemas closed with `additionalProperties: false`, but keep request-specific identities out of grammar `const` positions; validate identities after generation.

### Block-preserving cleanup

```json
{
  "blocks": [
    {
      "id": 123,
      "text": "Processed text"
    }
  ]
}
```

Application-side acceptance requires:

1. successful transport and normal completion classification;
2. raw JSON parsing, recorded separately from any full-fence recovery;
3. closed-schema validation;
4. exact expected item count, unique ID set, and order;
5. non-empty text;
6. no output for reference-only neighbor blocks;
7. block ownership, boundary, protected-value, omission, unsupported-addition, and repetition checks.

Do not ask the model to generate timestamps. Reattach source `start` and `end` by the exact accepted ID only after validation.

### Per-chunk summary

```json
{
  "summary": "Short local summary",
  "key_points": ["Bounded point"],
  "uncertainties": ["Source-supported uncertainty"]
}
```

The application attaches `recording_id`, `chunk_id`, ordinal position, source range, and timestamps outside the model response. Limit list lengths and string sizes. Do not use an unconstrained free-form `entities` array by default: it was the weakest evaluated field and participated in cyclic structured-generation failures. If entities are required, constrain type, confidence, source scope, and canonicalization explicitly.

### Whole-recording summary

```json
{
  "overview": "Compact recording-level summary",
  "key_points": ["Recording-level point"],
  "open_questions": ["Unresolved item"]
}
```

For hierarchical synthesis, the application orders and labels accepted chunk summaries before the final call and retains the chunk-to-source mapping. The model does not own recording identity, chunk identity, chronology, or provenance.

### Generic text postprocessing

For a self-contained transform without block identity:

```json
{
  "text": "Processed text"
}
```

For chunked or persistence-sensitive transforms, use the block-preserving contract instead. Plain output remains acceptable only when the caller does not require deterministic item identity and has an explicit boundary/completeness validator.

### Image analysis

```json
{
  "description": "Grounded description",
  "extracted_text": "Visible text only",
  "language": "und",
  "scene_type": "screenshot"
}
```

Use a closed `scene_type` enum appropriate to the product contract. Add object arrays only when the task requires them and the validator can evaluate open-world completeness without treating a partial allow-list as exhaustive gold. Keep image ID, file identity, dimensions, persistence key, request digest, and retry state application-owned. Warning fields should be omitted unless they have a precise product meaning and a valid evaluator; warning quality was weak in the bounded vision evidence.

## Application-owned state

The application, not the model, owns and validates:

- recording, document, image, chunk, and block IDs;
- expected block count, exact ID set, uniqueness, and order;
- original block `start`/`end` timestamps and chunk source ranges;
- protected names, numbers, dates, URLs, commands, and placeholders;
- source/request/schema digests and model/runtime provenance;
- retry eligibility, attempt number, fallback state, and accepted attempt;
- original source text and immutable fallback value;
- persistence status, merge order, idempotence key, and read-back result.

Model-authored IDs are echoes to validate, not authority. Model-authored timestamps should not be used for source attribution in cleanup or summary contracts.

## Layered verdict policy

Never collapse the following into one `accepted` count:

1. **Transport:** request reached the route and returned a usable envelope.
2. **Raw parse:** raw JSON parsed; fenced recovery, if allowed, is a separate serialization outcome.
3. **Schema:** the parsed value satisfies the closed task schema.
4. **Business identity:** expected IDs, count, uniqueness, order, and target/reference separation are exact.
5. **Semantic quality:** content is complete enough, grounded, boundary-safe, and preserves protected values.
6. **Product behavior:** retry, fallback, merge, persistence, export, and read-back behave correctly.

Schema validity proves structure only. The vision run's 36/36 schema result coexisted with mixed semantic dimensions, and the text study's 199/202 parseability does not establish production behavior.

## Limits and non-claims

- Text context recommendations come from one recording and one selected model; cleanup semantics were deeply reviewed only on representative early, middle, and late positions.
- No audio-grounded truth validates short microphone cleanup or uncertain proper names.
- No second recording, blind review, multi-rater score, or exhaustive source-unit alignment establishes generalization.
- No retained execution validates the complete host-application retry, original-value fallback, persistence, export, or read-back path.
- Whole-summary evidence covers five first-pass calls and five identical repeats on one recording; it does not establish broad summarization quality.
- Vision evidence covers four fixtures and mixed open-world semantics; no binary model admission or ranking is supported.
- The three byte-identical vision repeat pairs cover one UI request only.
- Adjacent-chunk and full-recording context remain available only for explicit, separately validated task contracts; they are not defaults.
- Physical prefix-cache reuse with changing chunks remains unproven and must not justify full-recording-per-chunk architecture.
