# L3.25 — Prompt/Validator Tightening

## Status

This is a non-live tightening slice. It does not claim new LM Studio model-quality results and does not require model load, download, remote calls, or live inference.

## Changes prepared for L3.26 measurement

### Prompt variant

`strict_no_new_facts_v2` is the conservative transcript-cleanup prompt for the next simple-postprocessing benchmark lane.

It keeps the L3.24 no-new-facts invariant and adds explicit cleanup behavior:

- restore punctuation and capitalization when clearly needed;
- remove only obvious filler words and repeated self-corrections;
- preserve language, mixed RU/EN technical style, names, numbers, dates, and uncertainty;
- avoid summarization, translation, external context, or inferred decisions;
- allow identity output only when no safe cleanup is needed, with a warning.

### Diagnostics

L3.26 can now measure these warning-level diagnostics in sanitized artifacts:

- `cleanup_noop_diagnostics` with category `cleanup_noop_when_noise_present`;
- `term_normalization_language_drift` with category `term_normalization_language_drift`.

The diagnostics are intentionally not hard validators. They are quality signals for comparing E2B/E4B behavior after L3.24 showed that validation pass rate can hide near-identity cleanup and term-normalization language drift.

### Report fields

`cell_summary.csv` includes no-op and language-drift fields for per-cell review.

`model_summary.csv` includes warning counts for model-level comparison:

- `cleanup_noop_warning_count`;
- `term_language_drift_warning_count`.

## Raw review pack guard

The raw-output local-only review-pack guard now uses the platform temp directory from `tempfile.gettempdir()` instead of a Linux-only `/tmp` check, while preserving:

- hard rejection for paths inside the repository;
- allowance for explicitly gitignored paths;
- local-only README warnings;
- no export of raw base URLs, tokens, credentials, or secrets.

## L3.26 usage

Use the tightened simple postprocessing configs with `strict_no_new_facts_v2` and inspect sanitized summaries for no-op and language-drift warning counts before making another product-readiness recommendation.
