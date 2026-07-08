# L3.21.1 — Manual Review Summary

## Status

A local-only review pack was exported from L3.21 sanitized artifacts:

```text
/tmp/labkit-l3211-review-pack-20260709002909
```

It is intentionally not committed. The committed summary below uses only validation metadata and hashes/counters. The pack did not include raw model outputs, so this is a metadata-driven manual review, not a semantic review of raw text.

## Answers

1. Product-useful outputs by metadata: `transcript_cleanup_simple` and `transcript_cleanup_blocks` are the strongest L3.21 candidates; `punctuation_restore_simple` also passed structurally, though punctuation metrics were diagnostic warnings.
2. The clearest case where the model likely did useful work but the validator/task design was too strict is `term_normalization`: strict failures normalized 5 source-present terms, while the fixture glossary contained terms absent from the input.
3. Real task failures remain in `blocks` and `paragraphing`: blocks duplicate/miss ids; paragraphing returns one paragraph despite a hard `min=2` requirement.
4. Promising prompt variants by metadata: `strict_no_new_facts` for transcript cleanup and `term_glossary` after source-aware filtering. `strict_same_language` simple punctuation is usable, but blocks remain unreliable.
5. Do not include `paragraphing` or `blocks`-schema tasks in a larger run yet. Do not include 12B/26B/Qwen/image/throughput/parallel/session/warmup.

## Review pack composition

Sampled cases: 24.

The sample includes pass/fail rows across:

- punctuation restore simple/blocks;
- paragraphing simple/blocks;
- term normalization simple/blocks;
- transcript cleanup simple/blocks;
- E2B and E4B.

## Privacy boundary

Because raw outputs are deliberately absent, this review cannot score prose quality directly on the `0..2` rubric. It can only assess validator behavior, failure modes, and whether a task family is worth a smaller follow-up matrix.
