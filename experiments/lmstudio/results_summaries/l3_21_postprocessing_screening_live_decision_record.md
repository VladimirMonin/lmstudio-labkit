# L3.21 — Postprocessing Screening Live Decision Record

## Status

Not accepted as a clean live postprocessing gate.

The run completed successfully at the infrastructure level, but quality/contract gates are red:

- JSON parse passed.
- JSON schema passed.
- Cleanup/final loaded state passed.
- Privacy scan passed.
- Postprocessing metrics are visible.
- Blocks `id_exact`, term normalization, and paragraphing failed enough to block scaling.

## Scope actually run

Models:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`

Included:

- text only;
- context `8192`;
- `cold_per_request`;
- `cache_mode=none`;
- `lmstudio_parallel=1`;
- `app_concurrency=1`;
- `retry_policy=off` and `retry1`;
- `response_schema_complexity=simple` and `blocks`;
- task intents: `punctuation_restore`, `term_normalization`, `transcript_cleanup`, `paragraphing`.

Explicitly not included:

- 12B;
- 26B;
- Qwen;
- image live;
- throughput;
- parallel;
- `session_loaded`;
- `warmup_first`;
- complex schema;
- overnight/stress;
- `/v1/responses`;
- route matrix.

## Run result

```text
attempt_count: 32
pass_count: 10
fail_count: 22
hard_fail_count: 22
pass_rate: 0.3125
```

Failure taxonomy:

```text
id_order_mismatch: 10
paragraphing_mismatch: 6
term_normalization_mismatch: 6
```

Warning taxonomy:

```text
punctuation_metrics: 16
manual_review_required: 16
```

## Acceptance checks

| Check | Result |
|---|---:|
| E2B/E4B live run completes | pass |
| JSON parse | 32/32 pass |
| JSON schema | 32/32 pass |
| blocks id_exact stable | fail: 6/16 pass, 10/16 fail |
| postprocessing metrics visible | pass |
| retry impact measured | pass |
| raw prompt/response not stored | pass |
| privacy scan | pass, violation_count=0 |
| final_loaded_instances=0 | pass |
| decision record explains readiness | this file |

Postprocessing validation result visibility:

```text
term_normalization_status: visible
punctuation_metrics: visible
paragraphing_metrics: visible
filler_cleanup: visible
no_new_facts_manual_review: visible
```

## Per-model result

| Model | Attempts | Pass | Fail | Pass rate |
|---|---:|---:|---:|---:|
| gemma4_e2b | 16 | 6 | 10 | 0.375 |
| gemma4_e4b | 16 | 4 | 12 | 0.25 |

## Per task intent

| Task intent | Attempts | Pass | Fail | Pass rate | Decision |
|---|---:|---:|---:|---:|---|
| punctuation_restore | 8 | 4 | 4 | 0.50 | blocked by blocks id mismatch; simple cells passed |
| term_normalization | 8 | 0 | 8 | 0.00 | blocked |
| transcript_cleanup | 8 | 6 | 2 | 0.75 | most promising, but blocks id mismatch remains |
| paragraphing | 8 | 0 | 8 | 0.00 | blocked |

## Per schema family

| Schema | Attempts | Pass | Fail | Pass rate |
|---|---:|---:|---:|---:|
| simple | 16 | 8 | 8 | 0.50 |
| blocks | 16 | 2 | 14 | 0.125 |

Blocks `id_exact`:

```text
pass: 6
fail: 10
```

## Retry impact

Retry was measured but did not improve the gate:

| Retry policy | Attempts | Pass | Fail | Pass rate |
|---|---:|---:|---:|---:|
| off | 16 | 5 | 11 | 0.3125 |
| retry1 | 16 | 5 | 11 | 0.3125 |

Retry attempted on 11 failing cells and recovered 0 cells.

## Cleanup and privacy

- `final_loaded_instances` was `0` for all rows.
- External LM Studio post-run check confirmed E2B/E4B loaded count `0`.
- Public latest snapshot privacy scan passed with `violation_count=0`.
- Raw fixture text and rendered prompt fragments were not present in `cell_results.jsonl`.

Public latest snapshot:

```text
docs/live_demo/latest_postprocessing_screening_live/
```

Timestamped/private local run artifacts:

```text
/tmp/labkit-l321-live/matrix_l3_21_postprocessing_screening_live
```

Local-only review pack:

```text
/tmp/labkit-l321-review-pack
```

## Interpretation

The new postprocessing validation pipeline is functioning: it produced term, punctuation, paragraphing, filler, and manual-review metrics on live rows.

The model/output behavior is not ready for broader postprocessing runs:

1. `blocks` schema is currently the main contract blocker because `id_exact` is unstable in 10/16 block cells.
2. `term_normalization` is not ready: both simple and blocks variants failed under hard term policy.
3. `paragraphing` is not ready under hard paragraph-count policy.
4. `transcript_cleanup` is the strongest candidate for the next focused slice, especially simple-schema cells.
5. Retry does not help this failure profile.

## Next recommended slice

Do not proceed to throughput, parallel, session/warmup, complex schema, 12B, 26B, Qwen, image, or overnight.

Recommended next task:

```text
L3.21.1 — Focused Postprocessing Failure Forensics
```

Scope:

- no broad rerun;
- use existing sanitized live artifacts first;
- inspect only validation metadata and safe output-derived metrics;
- focus on:
  - blocks `id_exact` mismatch shape;
  - term normalization hard failure counters;
  - paragraphing hard threshold design;
  - whether prompt/schema/task design or model behavior is the dominant cause.

A rerun should be allowed only after one precise config/prompt/schema/validator hypothesis is selected.

## Non-claims

This run does not prove:

- accepted postprocessing live quality;
- production readiness;
- 12B/26B/Qwen readiness;
- image readiness;
- throughput or parallel behavior;
- session/warmup behavior;
- complex-schema readiness;
- KV reuse;
- remote RAM/VRAM telemetry.
