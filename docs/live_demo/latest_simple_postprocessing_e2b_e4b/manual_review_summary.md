# L3.22 Manual Review Summary

Local-only review pack: `/tmp/labkit-l322-review-pack`

Sampled cases: 24

The review pack is local-only and is not committed. This committed latest summary uses validation metadata only, not raw prompts or raw responses.

## Product-useful candidates

All sampled metadata rows come from passing cells in the 80-attempt main run. The strongest product-like default candidate is:

- `transcript_cleanup/simple` with `strict_no_new_facts` for ASR cleanup inputs.

A second accepted candidate is:

- `term_normalization/simple` with `term_glossary` for explicit glossary/noisy technical-term inputs.

## Acceptable failures

The main L3.22 run had no model-quality failures:

- `fail_count=0`
- `hard_fail_count=0`

Diagnostic warnings may still exist for punctuation, filler cleanup, and manual review policy; they are expected diagnostics, not hard gates.

## E2B vs E4B

No meaningful separation in this gate:

- E2B: 40/40 pass
- E4B: 40/40 pass

E4B is not better enough to matter based on this validation-only slice.

## Boundary

This does not unblock blocks, paragraphing, 12B/26B/Qwen models, image, throughput, parallel, or session/warmup.
