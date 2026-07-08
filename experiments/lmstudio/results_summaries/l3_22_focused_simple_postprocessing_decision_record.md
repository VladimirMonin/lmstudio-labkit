# L3.22 — Focused Product-Like Simple Postprocessing Decision Record

## Status

Accepted as a clean focused simple postprocessing live slice.

## Scope

Included:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`
- `transcript_cleanup/simple`
- `term_normalization/simple`
- `ru_ru` and `ru_en_mixed`
- `retry_policy`: `off`, `retry1`
- `repeats`: 2
- cold per request, no cache, timing-only telemetry

Excluded:

- blocks schema tasks
- paragraphing hard gate
- Qwen/12B/26B model families
- image live
- complex schema
- throughput/parallel
- session/warmup
- raw prompt/response artifacts

## Result

- attempt_count: 32
- pass_count: 32
- fail_count: 0
- hard_fail_count: 0
- pass_rate: 1.0
- models: google/gemma-4-e2b, google/gemma-4-e4b
- execution_modes: cold_per_request
- cache_modes: none
- final_loaded_instances: [0]


Per task:

- `screen_transcript_cleanup_simple`: 8/8 pass
- `screen_transcript_cleanup_ru_fillers_simple`: 8/8 pass
- `screen_term_normalization_simple`: 8/8 pass
- `screen_term_normalization_mixed_simple`: 8/8 pass

Per model:

- `gemma4_e2b`: 16/16 pass
- `gemma4_e4b`: 16/16 pass

Per retry:

- `off`: 16/16 pass
- `retry1`: 16/16 pass, retry_attempted_count=0, recovered_count=0

## Decision

L3.22 supports proceeding with the product-like simple path for E2B/E4B: `transcript_cleanup/simple` and `term_normalization/simple` only.

Do not infer readiness for blocks, paragraphing, Qwen/12B/26B, image, throughput, parallel, or session/warmup.
