# Gemma 12B session-cache repair and bounded comparison

Status: bounded residual gap documented after a focused telemetry repair and two sequential live phases.

## Scope

- Model: `google/gemma-4-12b-qat`
- Context allocation: `16384`
- Parallelism: `1`
- Execution: one loaded session per phase, three sequential requests per session
- Compared shapes:
  - exact same-input session reuse;
  - byte-stable synthetic prefix with a small dynamic suffix.
- Excluded: 32k, parallel/stress execution, Cartesian matrices, image, Qwen, 26B, downloads, and raw artifact publication.

## Smallest justified repair

The managed executor previously discarded cache accounting returned by the compatible chat endpoint. It now preserves `cached_tokens` from these privacy-safe usage shapes:

- `usage.cached_tokens`;
- `usage.prompt_tokens_details.cached_tokens`;
- `usage.input_tokens_details.cached_tokens`.

The value is propagated through `RequestResult.token_counts`, JSONL rows, cell CSV, and resource CSV. A positive runtime-reported value is marked as a reported cache hit; `kv_reuse_proven` becomes true only when that signal accompanies a valid response. Missing runtime accounting remains `unknown`, not an inferred hit.

Focused automated verification after the repair: `27 passed`.

## Reproduction and bounded live evidence

### Oversized first reproduction

A first 16k-session request used a 49,009-character deterministic synthetic prefix and the bounded adaptive output stages `512 -> 1024`. The first request did not complete within the 600-second request timeout. The executor cleanup path unloaded the model, and the verified loaded count returned to zero.

This reproduces the narrow large-repeated-context stall without widening into 32k or stress work.

### Reduced bounded comparison

The comparison was reduced to a 19,779-character synthetic prefix. Each request reported approximately 6,475-6,480 prompt tokens and used a fixed 128-token output cap.

| phase | requests | valid | finish=length | warm/first latency | measured median latency | reported cached tokens | final loaded count |
|---|---:|---:|---:|---:|---:|---|---:|
| exact same input | 3 | 0 | 3 | 193,756.593 ms | 3,121.186 ms | unavailable | 0 |
| stable prefix + dynamic suffix | 3 | 0 | 3 | 26,590.621 ms | 16,831.566 ms | unavailable | 0 |

Timing-only observations:

- Exact same-input follow-ups were 62.08x faster than the first request, a 98.39% latency reduction.
- Stable-prefix follow-ups were 1.58x faster than their first request, a 36.70% latency reduction.
- The stable-prefix measured median was 5.39x slower than exact same-input follow-ups.

These differences support a strong session/runtime reuse signal for byte-identical requests and a weaker prefix-shaped reuse signal when only the suffix changes. They do not prove physical KV reuse because the runtime returned no `cached_tokens` field.

## Output validity, truncation, and consistency

All six bounded comparison requests ended with `finish_reason=length`, consumed the full 128-token cap, and returned no visible response content. Therefore:

- JSON/schema validity: failed for all six requests;
- truncation: observed for all six requests;
- semantic consistency: not assessable;
- identical empty response hashes: an artifact of absent visible output, not model consistency.

The output-budget repair is functioning as designed: the explicit caller cap was preserved and reported as `caller_override`. The residual gap is model/runtime behavior under repeated large context, not silent omission of the requested cap.

## Privacy and cleanup

Raw prompts and response payloads were retained only under the gitignored `experiments/lmstudio/live_runs/` tree. Six raw records were captured for local inspection. This committed summary contains only aggregate timings, token counts, hashes, statuses, and conclusions.

Each live phase used cleanup-once session ownership. Both phase-level final loaded counts were zero, and an independent final global loaded-model check also returned zero.

## Conclusion

Gemma 12B repeated large-context behavior is not admitted. The narrow stall is reproducible at the larger synthetic input, while the reduced canary exposes substantial timing reuse but still truncates every output and supplies no runtime cache accounting. Exact request reuse and stable-prefix reuse therefore remain timing-only research signals; neither is sufficient for a production/cache acceptance claim.

A future canary should change one variable only: use a runtime/model setting that suppresses hidden reasoning or otherwise returns a valid tiny JSON object within the bounded output cap. Do not increase context, parallelism, request count, or output budget until that one-request validity gate passes.
