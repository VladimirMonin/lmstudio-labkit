# L3.21.1 — Canary Decision Record

## Status

Targeted live canary completed. It is not accepted as a broader postprocessing gate.

## Scope

- models: `google/gemma-4-e2b`, `google/gemma-4-e4b`
- tasks: `screen_punctuation_restore_blocks`, `screen_term_normalization_simple`, `screen_paragraphing_simple`
- retry: `off`
- attempts: 6
- no Qwen/12B/26B/image/throughput/parallel/session/warmup/complex/overnight

## Result

- attempt_count: 6
- pass_count: 2
- fail_count: 4
- failure_categories: `schema_error=2`, `paragraphing_mismatch=2`
- final_loaded_instances: 0

## Per hypothesis

1. Blocks id contract: schema hardening worked as a detector, not a fix. The duplicate/missing id behavior now fails `json_schema` at `$.blocks[0].id:const` and also fails `id_exact`.
2. Term normalization: source-aware/path-aware validation fixed strict simple term normalization; both E2B and E4B passed.
3. Paragraphing: longer fixture did not fix behavior; both E2B and E4B still returned one paragraph.

## Decision

- Accept the term normalization validator/task fix for the next simple-schema slice.
- Keep blocks blocked.
- Keep paragraphing blocked.
- Do not broaden to a larger live matrix.
