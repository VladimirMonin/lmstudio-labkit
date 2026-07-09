# L3.26 Product Benchmark Decision Record

## Verdict

L3.26 main run is accepted as a clean 60-attempt infrastructure benchmark for `transcript_cleanup/simple`.

Host-app hidden/dev prototype is allowed with a guarded model policy:

1. Use `google/gemma-4-e4b` as the quality candidate by continuity from L3.24 raw review.
2. Keep `google/gemma-4-e2b` as lightweight fallback and possibly conservative/fast mode.
3. Require a future local raw-prose review before any user-facing/default release claim.

## Answers

### 1. E4B or E2B for hidden/dev quality default?

Use E4B as the hidden/dev quality candidate. L3.26 did not disprove it, and prior raw review indicated better visible cleanup. This run shows E4B is reliable but slower.

### 2. Is E2B acceptable as lightweight fallback?

Yes. E2B passed 30/30 main attempts with 0 near-identity warnings and lower median latency.

### 3. Is `strict_no_new_facts_v2` good enough?

For the bounded benchmark infrastructure gate: yes. It produced 60/60 pass with JSON/schema/privacy success. Full prose-quality adequacy still needs local raw review.

### 4. Does the model preserve meaning?

Not proven by raw prose review in this run. The validation contract and schema passed, but raw prose was not persisted.

### 5. Does the model avoid new facts?

No raw-prose new-facts review was committed. The prompt and validator path are aligned with no-new-facts, but this remains a local review requirement before user-facing release.

### 6. How often does near-identity/no-op happen?

In the 60-attempt main run: 0 near-identity warnings.

### 7. Is latency acceptable?

For hidden/dev prototype exploration: yes.

- E2B median latency: 2801.683 ms.
- E4B median latency: 3806.866 ms.

E2B is materially faster in this run.

### 8. Is host-app prototype allowed?

Yes, as L3.27 hidden/dev prototype only. Do not expose broad mode/model UI. Keep term normalization, blocks, paragraphing, complex schema, images, Qwen/12B/26B, throughput, parallel, session/warmup out of scope.

## Evidence

- Canary: 6/6 pass.
- Main: 60/60 pass.
- JSON parse: pass for all main rows.
- Schema: pass for all main rows.
- Privacy scan: pass.
- Final loaded instances: 0 per cell.
- Raw artifacts committed: none.
- Public snapshot: `docs/live_demo/latest_product_benchmark_simple_postprocessing/`.
- Local review pack: `/tmp/labkit-l326-raw-output-review-pack` (`raw_case_count=0`, metadata/sampled cases only).

## Non-claims

- No 120-attempt extended benchmark was run.
- No raw prompt/response was committed.
- No term-normalization product benchmark was run.
- No 12B/26B/Qwen/image/blocks/paragraphing/complex/throughput/parallel/session/warmup route was run.
