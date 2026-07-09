# L3.25 — Prompt/Validator Tightening Report

## Status

L3.25 is implemented and verified with a small guarded live canary. This report is sanitized and contains no raw prompts, raw responses, private transcripts, base URLs, or credentials.

## What changed

- Raw review pack local-only guard now uses `tempfile.gettempdir()` instead of Linux-only `/tmp`, while still allowing explicitly gitignored external paths and rejecting repository paths.
- `strict_no_new_facts.md` and `strict_no_new_facts_v2.md` now explicitly describe ASR transcript cleanup, no-new-facts, no-summary, no-translation, technical-term preservation, punctuation/capitalization repair, and Russian language-preservation instructions.
- `term_glossary.md` now restricts normalization to glossary-covered terms actually present in the source and explicitly forbids whole-sentence English translation.
- `ResponseContract` supports `near_identity_policy`, `language_drift_policy`, and `term_language_preservation_policy`.
- Transcript cleanup now emits richer near-identity metrics: `identity_similarity`, `changed_char_ratio`, `punctuation_delta`, `capitalization_delta`, `whitespace_normalization_delta`, `asr_noise_reduction_delta`, and `near_identity_warning`.
- Term normalization can promote language drift from warning to hard failure for canary gates.
- L3.26 product benchmark configs are prepared but were not run.

## Why near-identity diagnostics were added

L3.24 showed that E2B can pass validation while producing safe but weak near-identity transcript cleanup. That is not a JSON/schema failure, but it matters for product quality. L3.25 keeps near-identity as a warning-level diagnostic for transcript cleanup so L3.26 can compare useful cleanup versus no-op behavior without turning the first quality benchmark into a hard gate.

## Quality recommendation entering L3.26

- Quality candidate: `google/gemma-4-e4b`.
- Lightweight fallback: `google/gemma-4-e2b`.
- `transcript_cleanup/simple` is the only mode allowed to proceed to L3.26.
- `term_normalization/simple` remains controlled/dev-only after the canary because E2B had a format hard failure in the term-normalization lane, even though language drift itself was not observed.

## Live canary summary

Source: `/tmp/labkit-l325-live-canary/matrix_l3_25_prompt_tightening_canary_e2b_e4b`.

| Metric | Value |
|---|---:|
| attempt_count | 6 |
| pass_count | 5 |
| fail_count | 1 |
| near_identity_warning_count | 0 |
| term_language_drift_count | 0 |
| raw outputs committed | 0 |
| final loaded instances | 0 per cell |

Per model:

| model | attempts | pass | fail | no-op warnings | language-drift warnings | median latency ms |
|---|---:|---:|---:|---:|---:|---:|
| gemma4_e2b | 3 | 2 | 1 | 0 | 0 | 851.655 |
| gemma4_e4b | 3 | 3 | 0 | 0 | 0 | 923.717 |

Per row:

| model | task | status | json | schema | near_identity | language_drift | final_loaded |
|---|---|---|---|---|---|---|---:|
| gemma4_e2b | l325_canary_transcript_cleanup_simple_ru_fillers | pass | pass | pass | False | - | 0 |
| gemma4_e2b | l325_canary_term_normalization_simple_ru_noise | fail | pass | pass | - | False | 0 |
| gemma4_e2b | l325_canary_term_normalization_simple_mixed | pass | pass | pass | - | False | 0 |
| gemma4_e4b | l325_canary_transcript_cleanup_simple_ru_fillers | pass | pass | pass | False | - | 0 |
| gemma4_e4b | l325_canary_term_normalization_simple_ru_noise | pass | pass | pass | - | False | 0 |
| gemma4_e4b | l325_canary_term_normalization_simple_mixed | pass | pass | pass | - | False | 0 |

## Canary interpretation

The canary passed the infrastructure safety gate:

- JSON parse and schema validation passed for every row.
- Publication privacy scan passed.
- No raw prompt/response artifacts were committed.
- `final_loaded_instances=0` for every row.
- E2B/E4B cleanup rows had no near-identity warnings.
- Term-normalization language drift count was zero.

The canary did not fully pass as a term-normalization product lane:

- E2B failed one `term_normalization/simple` row due to Markdown fence leakage.
- E4B passed all 3 rows.

## L3.26 benchmark permission

Allowed next: L3.26 product benchmark for `transcript_cleanup/simple` only.

Prepared config:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_26_product_benchmark_simple_postprocessing.e2b_e4b.yaml
experiments/lmstudio/structured_matrix/suites/l3_26_product_benchmark_simple_postprocessing.yaml
```

Expected L3.26 shape:

```text
2 models × 6 input profiles × 5 repeats = 60 attempts
models: google/gemma-4-e2b, google/gemma-4-e4b
mode: transcript_cleanup/simple
prompt_variant: strict_no_new_facts_v2
retry_policy: off
context_tier: 8192
execution_mode: cold_per_request
cache_mode: none
```

Do not run L3.26 until the owner explicitly approves it after this canary.
