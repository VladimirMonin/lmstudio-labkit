# Structured output and scorer audit

Date: 2026-07-12

Status: offline evidence audit. No model call, model load, network request, runner change, or test change was made.

## Decision

Use native strict JSON Schema when available, but keep the runtime grammar compact and generic. For block workloads, require a closed `{schema_version, status, blocks, warnings}` object whose blocks contain only `{block_id, normalized_text, status, warnings}`. Keep request digests, expected IDs/order, protected values, and placeholder inventories application-owned; validate them after generation.

Treat raw JSON, fenced-but-recovered JSON, exact schema, business identity, semantic text, and fallback as separate outcomes. The evidence does not support collapsing them into one `accepted` count. The current exact-reference normalization scorer is useful for conformance tests, but it is too strict to stand alone as a semantic-quality scorer.

One retry is justified only for parse/schema/ID defects. Length exhaustion, runaway repetition, semantic omission, unsupported additions, boundary leakage, and protected-value changes must fail closed directly to the original source blocks.

## Evidence boundary

### Repository evidence

- The historical 80-call overlay embedded schema instructions in the prompt and recorded zero strict acceptances; the correction explicitly says this is not evidence of absent JSON/schema capability (`2026-07-12_four_model_real_asset_benchmark_synthesis.md:3-14`).
- The focused correction bound native structured output through `/v1/responses`, `text.format.type=json_schema`, and `strict=true` (`2026-07-12_gemma4_native_structured_output_correction.md:9-17`; `tools/lmstudio_lab/structured_output_correction.py:114-133`).
- The correction parser accepts either raw JSON or exactly one full Markdown fence (`tools/lmstudio_lab/structured_output_correction.py:172-182`).
- The normalization scorer's hard gates and metrics are implemented in `tools/lmstudio_lab/private_benchmark_pack.py:233-324`.
- The overlay binds scorer inputs to prompt, schema, target, rubric, and task digests before recomputation (`tools/lmstudio_lab/private_benchmark_overlay.py:74-124`).
- The factual-block validator requires a closed shape and checks IDs, duplicates, order, non-empty text, statuses, reasoning leakage, and length (`tools/lmstudio_lab/structured.py:170-229`, `531-657`). Its own contract states that schema validation is minimal shape validation, not full JSON Schema Draft validation (`tools/lmstudio_lab/structured.py:1-5`, `21-27`).

### Owner-only evidence inspected

I inspected 60 repeated native structured-output raw final texts and their 60 matching response envelopes. I also reconciled the retained 8,192- and 16,384-token E4B/M05 boundary artifact class. No private body, locator, prompt, or transcript is reproduced here.

Privacy-safe recomputation over the 60 repeated outputs found:

| View | Raw JSON | Fenced JSON | Invalid |
|---|---:|---:|---:|
| M01 | 5 | 15 | 0 |
| M05 | 5 | 10 | 5 |
| L02-L | 0 | 20 | 0 |

The private shape audit also found 15 outputs where the count declared in `preserved_placeholders` differed from the placeholder count physically present in `normalized_text`. This confirms that text preservation and model-authored metadata are separate axes.

## Findings by contract axis

### 1. Prompt-embedded versus native schema

**Fact.** The historical 80-call matrix used prompt-embedded schema instructions. Its zero strict acceptances combine transport, exact schema, target, placeholder metadata, and task gates (`2026-07-12_four_model_real_asset_benchmark_synthesis.md:12-28`).

**Fact.** The native correction used a schema field on the wire. Across the repeated native matrix, raw or fenced JSON was recoverable in 55/60 outputs. Exact-schema behavior remained model/task-specific (`2026-07-12_gemma4_whisper_structured_parallel_statistics.md:66-100`).

**Interpretation.** Prompt-embedded schema is instruction text, not native structured output. Native binding improves structural compliance but does not guarantee raw serialization, semantic correctness, metadata correctness, or bounded generation.

### 2. Raw, fenced, extracted, and exact schema

**Fact.** E2B supplied all five raw M01 and all five raw M05 outputs. Every L02-L output was fenced. The remaining valid M01/M05 outputs were fenced, except five malformed E4B/M05 outputs.

**Fact.** The repeated private shapes show deterministic exact-schema additions: 12B M01 added `title`, 26B M01 added `type`, and 26B L02-L added `output_schema`. These explain the published exact-schema failures without implying invalid semantic text.

**Interpretation.** A fenced full JSON document is a recoverable serialization defect, not raw native-schema success. Log both facts. Recovery should require exactly one fence containing exactly one JSON document and no surrounding prose.

### 3. Semantic text and placeholder metadata

**Fact.** The scorer defines semantic fidelity as exact `normalized_text` equality to semantic gold or a reference candidate. It gives punctuation/casing and disfluency scores of 2 only for exact equality, otherwise 0 (`tools/lmstudio_lab/private_benchmark_pack.py:287-308`).

**Fact.** Placeholder success requires equality among placeholders in the target text, placeholders physically found in generated text, and the model-declared metadata array (`tools/lmstudio_lab/private_benchmark_pack.py:276-286`).

**Fact.** Direct private review in the retrospective found useful M01 text even when strict metadata/target gates rejected it, and it separately identified cases where text placeholders survived but metadata was wrong (`2026-07-12_gemma_whisper_benchmark_retrospective.md:41-47`).

**Interpretation.** The current scorer measures exact-reference conformance, not broad semantic equivalence. `target_text_mismatch` should not be renamed semantic failure. Model-authored input digests and duplicated placeholder inventories are avoidable failure surfaces because the application already knows both values.

### 4. Output-budget failures

**Fact.** E4B/M05 exhausted 4,096, 8,192, and 16,384 output tokens, preserving the shorter prefixes while continuing malformed repetition. The envelope still reported `finish_reason=stop` and zero reasoning tokens (`2026-07-12_gemma4_native_structured_output_correction.md:22-26`).

**Interpretation.** Length classification must use both the native reason and usage. `output_tokens >= configured cap` is a length candidate even when the reason says `stop` (`tools/lmstudio_lab/structured_output_correction.py:162-169`). This failure is not retryable: a larger cap extended the same runaway.

### 5. Positional-const grammar and generic P4 repair

**Fact.** A schema with 25 position-specific `const` IDs returned HTTP 400 before generation on all four models. A generic exactly-25-item `{id, text}` schema plus application-side exact ID/order checks passed 80/80 repaired P4 requests (`2026-07-12_gemma4_whisper_structured_parallel_statistics.md:117-152`).

**Interpretation.** Keep request-specific identity out of runtime grammar. The application should own expected IDs and compare exact set, count, uniqueness, and order after generation. This is the strongest tested structured architecture in the evidence.

### 6. Retry and fallback evidence

**Fact.** The retained matrices mostly used no retry; the statistical recommendation permits one retry for parse/schema failures (`2026-07-12_gemma4_whisper_structured_parallel_statistics.md:165-179`). The current validator records a retry count but does not implement a retry or fallback state machine (`tools/lmstudio_lab/structured.py:531-547`).

**Interpretation.** Retry/fallback is a recommended policy, not an executed end-to-end result. It must remain explicitly logged and must not overwrite attempt zero.

## Recommended runtime schema

Use native strict JSON Schema with a compact closed object:

- `schema_version`: constant `factual_blocks.v1`;
- `status`: `success`, `partial`, or `failed`;
- `blocks`: array of closed objects containing:
  - `block_id`: integer;
  - `normalized_text`: non-empty string;
  - `status`: `success`, `unchanged`, or `uncertain`;
  - `warnings`: string array;
- `warnings`: top-level string array.

Do not ask the model to reproduce:

- input or request digests;
- a placeholder inventory already derivable from source text;
- request-specific per-position `const` IDs.

The application owns source/request/schema digests, expected IDs/order, protected values, placeholder inventory, retry state, and fallback state.

## Post-generation validator

Run these steps in order and preserve every intermediate outcome:

1. Reject HTTP errors, missing final text, reasoning content, and empty output.
2. Classify length if the native reason is `length`/`max_output_tokens` or output usage reaches the configured cap.
3. Parse raw JSON first. Optionally recover exactly one full fenced JSON document and record `fenced_recovered`, never `raw_json`.
4. Validate the closed schema with a full JSON Schema validator in production.
5. Compare returned IDs with application-owned expected IDs: exact set, count, uniqueness, and order.
6. Require non-empty block text and allowed statuses.
7. Check authoritative chunk boundaries, protected names/numbers/dates/URLs/commands/placeholders, unsupported additions, omissions, and runaway repetition.
8. Record semantic review separately from exact-reference mismatch.
9. Accept only when transport, schema, business identity, boundary, protected-value, and semantic-safety gates all pass.

## One-retry policy

Maximum: one retry.

Eligible failures:

- invalid JSON;
- a fenced JSON wrapper when raw JSON is required;
- schema mismatch;
- missing, duplicate, extra, or reordered IDs.

The retry keeps the same source and semantic instruction, uses the compact native generic schema, and adds one terse correction naming only the failed structural gate.

Do not retry:

- length hit or runaway repetition;
- semantic omission or unsupported addition;
- chunk-boundary leakage;
- protected-value or placeholder-text change;
- transport failure that removed the loaded instance.

Attempt zero and retry one are immutable distinct records. Retry success does not erase the original failure.

## Fallback policy

- After retryable structural failure is exhausted, return the original source blocks unchanged with application-owned IDs and mark `fallback_original`.
- On semantic or safety failure, skip retry and immediately return original blocks unchanged.
- Fail the requested batch closed unless the caller explicitly supports per-block partial results while preserving exact order.
- Never silently strip fences and call the response native-raw success, drop invalid blocks, trust malformed model metadata, or report fallback as model success.

## Logging taxonomy

| Axis | Values |
|---|---|
| Transport | `http_error`, `missing_final_text`, `raw_json`, `fenced_recovered`, `invalid_json`, `reasoning_leak` |
| Completion | `stop`, `length_explicit`, `length_usage_cap`, `runaway_repetition`, `empty_output` |
| Schema | `schema_valid`, `schema_missing_field`, `schema_extra_field`, `schema_wrong_type`, `schema_wrong_enum` |
| Business | `ids_exact`, `ids_missing`, `ids_duplicate`, `ids_extra`, `ids_reordered`, `empty_block_text`, `status_invalid` |
| Semantic safety | `semantic_pass`, `omission`, `unsupported_addition`, `boundary_leak`, `protected_value_change`, `placeholder_text_change`, `reference_mismatch_only`, `review_required` |
| Control flow | `attempt_0`, `retry_1`, `retry_exhausted`, `fallback_original`, `accepted` |
| Provenance | model revision plus request, schema, source, expected-ID, raw-output, envelope, and validator digests |

## Hypotheses

- Removing model-authored digests and duplicated placeholder inventories should reduce false rejection without weakening safety because the application can compute them deterministically.
- Compact generic schemas should remain more robust at P4 than positional const grammars, but the safe complexity boundary beyond the tested 25-item case is unknown.

## Unresolved evidence gaps

- No controlled product-shaped plain-versus-native-JSON A/B holds the same approximately 23k-token prefix and current chunk constant.
- No block-preserving end-to-end merge validates real early, middle, and late chunks.
- No retained execution demonstrates the proposed one-retry and fallback policy end to end.
- Semantic completeness relies on direct private review, not exhaustive source-unit alignment or audio truth.
- The current factual-block validator performs minimal shape checks, not full JSON Schema Draft validation.
- Generic-schema P4 is proven only for the tested compact 25-item workload and hardware/runtime shape.

Machine-readable companion: `2026-07-12_structured_output_and_scorer_audit.json`.
