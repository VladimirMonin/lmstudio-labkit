# L3.21.1 — Next Matrix Recommendation

## Recommendation

Choose **Option B — Keep only transcript_cleanup/simple for product-like path**, with a small addition: term-normalization simple can be re-tested as a focused strict task after the L3.21.1 source-aware validator fix.

## Why not the other options

- Option A is premature: canary still failed blocks and paragraphing.
- Option C is promising later, but the canary shows stronger `prefixItems` turns blocks failures into schema errors rather than fixing model behavior.
- Option D is too strong: E2B/E4B still pass transcript cleanup simple and term normalization simple after fixes.

## Next corrected matrix shape

Allowed next slice:

- models: `google/gemma-4-e2b`, `google/gemma-4-e4b`
- task intents: `transcript_cleanup`, `term_normalization`
- schemas: `simple` only
- retry: `off`, `retry1`
- context: `8192`
- execution: `cold_per_request`
- cache: `none`
- no images, no Qwen/12B/26B, no throughput/parallel/session/warmup/complex/overnight.

Keep blocked:

- blocks schema tasks until a blocks-specific prompt/schema redesign is tested;
- paragraphing hard gate until paragraph-specific schema or diagnostic-first policy is chosen.

## Decision by morning

Selected: **Option B**.
