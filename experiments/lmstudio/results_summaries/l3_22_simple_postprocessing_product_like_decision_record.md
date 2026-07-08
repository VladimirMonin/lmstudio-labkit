# L3.22 — Simple Postprocessing Product-Like Decision Record

## Scope

This is the first bounded product-like simple postprocessing matrix for small Gemma E2B/E4B candidates.

Included:

- models: `google/gemma-4-e2b`, `google/gemma-4-e4b`
- schema: `simple` only
- task intents: `transcript_cleanup`, `term_normalization`
- input profiles: `raw_asr_ru_no_punctuation`, `raw_asr_ru_fillers`, `raw_asr_ru_term_noise`, `ru_en_mixed_tech`
- output policies: `preserve_input_language`, `preserve_mixed_language`
- prompt variants: `strict_no_new_facts`, `term_glossary`
- runtime: context 8192, cold per request, cache none, parallel 1, app concurrency 1, queue pressure off, temperature 0
- retry policies: `off`, `retry1`
- repeats: 5

Excluded:

- blocks schema
- paragraphing hard gate
- punctuation as a hard gate
- 12B, 26B, Qwen model family
- image live
- complex schema
- throughput, parallel, session/warmup
- `/v1/responses` and route matrix
- raw prompt/response/base URL/host/token artifacts

## Commands used

`preflight-suite` was used for the canonical suite. The current `run-suite` CLI does not accept live/operator/base-url flags, so canary and main were run as separate `run` commands and this boundary is documented here.

Canary command shape:

```bash
uv run lmstudio-benchmark run \
  --config experiments/lmstudio/structured_matrix/configs/matrix.l3_22_simple_postprocessing_canary.e2b_e4b.yaml \
  --output-root /tmp/labkit-l322-product-like-canary-* \
  --profile live-screening \
  --live \
  --operator-live-managed \
  --allow-model-loads \
  --allow-remote-base-url \
  --base-url <redacted-local-or-link-url>
```

Main command shape:

```bash
uv run lmstudio-benchmark run \
  --config experiments/lmstudio/structured_matrix/configs/matrix.l3_22_simple_postprocessing_product_like.e2b_e4b.yaml \
  --output-root /tmp/labkit-l322-product-like-main-* \
  --profile live-screening \
  --live \
  --operator-live-managed \
  --allow-model-loads \
  --allow-remote-base-url \
  --base-url <redacted-local-or-link-url>
```

## Canary result

- run dir: `/tmp/labkit-l322-product-like-canary-20260709005235/matrix_l3_22_simple_postprocessing_canary_e2b_e4b`
- attempt_count: 4
- pass_count: 4
- fail_count: 0
- cleanup final loaded values: [0]

| task_id | status | count |
| --- | --- | --- |
| l322_term_normalization_simple_ru_noise | pass | 2 |
| l322_transcript_cleanup_simple_ru_no_punctuation | pass | 2 |

Canary allowed the main run: infrastructure, schema/privacy, and cleanup were healthy.

## Main result

- run dir: `/tmp/labkit-l322-product-like-main-20260709005312/matrix_l3_22_simple_postprocessing_product_like_e2b_e4b`
- attempt_count: 80
- pass_count: 80
- fail_count: 0
- hard_fail_count: 0
- pass_rate: 1.0
- failure_categories: `{}`
- final_loaded_instances: `[0]`

## Per-model summary

| model_key | status | count |
| --- | --- | --- |
| gemma4_e2b | pass | 40 |
| gemma4_e4b | pass | 40 |

## Per-task summary

| task_id | status | count |
| --- | --- | --- |
| l322_term_normalization_simple_mixed | pass | 20 |
| l322_term_normalization_simple_ru_noise | pass | 20 |
| l322_transcript_cleanup_simple_ru_fillers | pass | 20 |
| l322_transcript_cleanup_simple_ru_no_punctuation | pass | 20 |

## Per-task-intent summary

| task_intent | status | count |
| --- | --- | --- |
| term_normalization | pass | 40 |
| transcript_cleanup | pass | 40 |

## Per-input-profile summary

| input_profile | status | count |
| --- | --- | --- |
| raw_asr_ru_fillers | pass | 20 |
| raw_asr_ru_no_punctuation | pass | 20 |
| raw_asr_ru_term_noise | pass | 20 |
| ru_en_mixed_tech | pass | 20 |

## Per-prompt-variant summary

| prompt_variant | status | count |
| --- | --- | --- |
| strict_no_new_facts | pass | 40 |
| term_glossary | pass | 40 |

## Retry impact

| retry_policy | status | count |
| --- | --- | --- |
| off | pass | 40 |
| retry1 | pass | 40 |

`retry1` attempted no recoveries because no first-pass failures occurred in retry-enabled rows.

## Postprocessing metrics

- term normalization status: `{'pass': 60, 'skip': 20}`
- punctuation diagnostic status: `{'warning': 40, 'skip': 40}`
- filler cleanup diagnostic status: `{'pass': 40, 'skip': 40}`
- manual review status: `{'warning': 80}`

Detailed public-safe aggregation is in:

```text
docs/live_demo/latest_simple_postprocessing_e2b_e4b/postprocessing_summary.csv
```

## Manual review summary

Local-only review pack:

```text
/tmp/labkit-l322-review-pack
```

Committed manual summaries:

```text
docs/live_demo/latest_simple_postprocessing_e2b_e4b/manual_review_summary.md
experiments/lmstudio/results_summaries/l3_22_manual_review_summary.md
```

The review remains metadata-only because raw outputs are not committed.

## Privacy proof

- `allow_raw_prompt_response_artifacts=false`
- latest export contains `privacy_scan.json`
- publication safety audit passed before commit
- raw prompt, raw response, base URL, host, tokens, and local private paths are not committed

## Cleanup proof

- canary final loaded values: `[0]`
- main final loaded values: `[0]`
- external post-run checks showed E2B/E4B loaded_count=0

## Telemetry note

This run uses timing-only telemetry and does not claim RAM/VRAM or throughput/parallel performance.

## Decision

Accepted as a clean product-like simple postprocessing gate for E2B/E4B:

- `transcript_cleanup/simple`: accepted as default candidate
- `term_normalization/simple`: accepted as explicit glossary/noisy-term candidate

Still blocked/not inferred:

- blocks schema tasks
- paragraphing hard gate
- 12B/26B/Qwen model families
- image live
- throughput/parallel/session/warmup

## Next gate recommendation

Move toward product integration only for `transcript_cleanup/simple` first, with `term_normalization/simple` as a controlled glossary mode. The next gate should add a small set of more realistic ASR fixtures and a raw-output local-only human quality review, while keeping public artifacts sanitized.
