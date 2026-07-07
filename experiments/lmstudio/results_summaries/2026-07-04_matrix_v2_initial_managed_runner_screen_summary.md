# Matrix v2 Initial Managed-runner Screen Summary

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Execution path: `tools/lmstudio_lab.ManagedLabRunner -> libs/lmstudio_managed client/contracts -> local LM Studio`
- Purpose: first controlled Matrix v2 screen through the managed-backed Lab path after S6.
- This is not the full CUDA matrix: no medium chunked pass, no true-parallel pass, no vision, no embeddings, no cache/stateful settings, no host application runtime integration.

## Model set

| Lab key | Model id | Track |
| --- | --- | --- |
| `gemma4_e2b_q4km` | `google/gemma-4-e2b` | baseline text |
| `gemma4_e4b_q4km` | `google/gemma-4-e4b` | heavier text candidate |
| `qwen35_4b_q4km` | `qwen3.5-4b` | Qwen recovery track |
| `qwen35_9b_q4km` | `qwen/qwen3.5-9b` | Qwen recovery / heavier track |

## Modes executed

For each model:

```text
load echo context=8192 parallel=1
structured small factual-blocks JSON schema
plain small max_tokens=512
exact unload
cleanup verification
```

Preflight and final cleanup:

```text
pre_matrix_loaded_instances=0
final_loaded_instances=0
```

No LM Studio model deletion was required.

## Summary counts

```text
model_count=4
load_ok=4
structured_business_pass=3
structured_no_transport_error=4
plain_non_empty=3
plain_no_error=2
final_loaded_instances=0
```

## Per-model results

| Model | Load echo | Structured small | Plain small | Cleanup | Notes |
| --- | --- | --- | --- | --- | --- |
| `gemma4_e2b_q4km` | ✅ 8192 / 1 | ✅ parse/schema/business pass | ✅ non-empty, finish `stop` | ✅ exact unload | baseline remains green |
| `gemma4_e4b_q4km` | ✅ 8192 / 1 | ✅ parse/schema/business pass | ✅ non-empty, finish `stop` | ✅ exact unload | heavier candidate green in initial screen |
| `qwen35_4b_q4km` | ✅ 8192 / 1 | ❌ empty content with reasoning present; JSON parse failed | ❌ empty content, reasoning present, finish `length` | ✅ exact unload | recovery track: reasoning/content routing and max-token issue |
| `qwen35_9b_q4km` | ✅ 8192 / 1 | ✅ parse/schema/business pass | ⚠️ non-empty but finish `length` at 512 tokens | ✅ exact unload | recovery track: plain-text max-token/verbosity issue |

## Interpretation

### Gemma baseline/candidate

Both Gemma text models passed the initial managed-runner screen:

- load echo matched requested `context=8192`, `parallel=1`;
- structured small passed parse/schema/business validation;
- plain small returned non-empty safe envelopes with finish `stop`;
- exact unload cleanup verified.

`gemma4_e2b_q4km` remains the safest baseline. `gemma4_e4b_q4km` remains a viable heavier text candidate.

### Qwen recovery track

`qwen35_4b_q4km` still shows the known reasoning/content routing split:

- structured request returned empty public content while reasoning content was present;
- validation failed at JSON parse;
- plain request hit `finish_length` at 512 tokens with empty public content.

`qwen35_9b_q4km` improved on structured small but still hit `finish_length` for plain text at 512 tokens.

These are not production-default candidates yet. They should stay on recovery tracks, not be discarded.

## Privacy boundary

The initial Matrix v2 screen stored only safe fields:

- status and enum values;
- echo context/parallel;
- booleans and counts;
- token counts;
- response hashes and char counts;
- parse/schema/business booleans;
- safe validation categories.

Raw prompts, raw responses, raw messages, raw provider bodies, raw instance IDs, raw job IDs, URLs, paths and API keys were not stored in this report.

## Next Matrix v2 gates

Recommended next controlled slices:

1. Gemma-only medium chunked sequential through managed runner.
2. Gemma-only true-parallel=2 only if sequential stays green.
3. Qwen recovery probes:
   - explicit reasoning-routing diagnostics;
   - plain max-token sweep for Qwen 4B/9B;
   - structured recovery prompts with safe validation.
4. System metrics sampling around managed-runner executions.

Still stop before:

- host application runtime integration;
- QueueManager/UI/SQLite changes;
- vision;
- embeddings/reranker;
- cache/stateful LM Studio settings;
- production default selection.
