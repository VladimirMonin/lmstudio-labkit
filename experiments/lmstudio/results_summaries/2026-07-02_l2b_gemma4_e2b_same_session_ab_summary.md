# L2b Same-session A/B Evidence — LM Studio Lab

## Scope

- Date: 2026-07-02
- Branch: `next/modular-backend-lab`
- Evidence level: controlled live same-session A/B probe, not a production benchmark
- Model ID: `google/gemma-4-e2b`
- Dataset ID: `blocks_json_medium_chunked`
- Chunks: `4 x 25 blocks`
- Endpoint: `/v1/chat/completions`
- Response format: `json_schema`
- Base URL class: localhost loopback
- Native load/unload/download endpoints: not called
- Cache/stateful/vision: not tested
- Raw prompt/response/messages/content stored: no

## Design

Both sides used the same model, dataset, chunk size, loaded runtime, and safety contract.

```text
baseline:  app_concurrency=1, warmup chunk_0, 3 measured batches
candidate: app_concurrency=2, warmup chunk_0, 3 measured batches
```

The candidate speedup was computed against the baseline average batch wall time measured in the same session.

## Baseline — sequential chunked

Run ID: `l2b_ab_gemma4_e2b_baseline_seq_001`

| Metric | Value |
| --- | ---: |
| App concurrency | `1` |
| Warmup policy | sequential `chunk_0000` |
| Measured batches | `3` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| All IDs `0..99` covered | yes |
| Duplicate IDs | `0` |
| Missing IDs | `0` |
| Structured errors | `0` |
| Finish length count | `0` |
| Reasoning leaks | `0` |
| Total prompt tokens | `15306` |
| Total completion tokens | `11110` |
| Total tokens | `26416` |
| Total batch wall time | `97407 ms` |
| Average batch wall time | `32469 ms` |
| Max batch wall time | `33015 ms` |
| Average chunk latency | `8117 ms` |

## Candidate — app concurrency 2

Run ID: `l2b_ab_gemma4_e2b_appconc2_001`

| Metric | Value |
| --- | ---: |
| App concurrency | `2` |
| Warmup policy | sequential `chunk_0000` |
| Measured batches | `3` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| All IDs `0..99` covered | yes |
| Duplicate IDs | `0` |
| Missing IDs | `0` |
| Structured errors | `0` |
| Finish length count | `0` |
| Reasoning leaks | `0` |
| Total prompt tokens | `15306` |
| Total completion tokens | `11109` |
| Total tokens | `26415` |
| Total batch wall time | `72657 ms` |
| Average batch wall time | `24219 ms` |
| Max batch wall time | `25563 ms` |
| Average chunk latency | `12063 ms` |
| Same-session speedup vs baseline | `1.34x` |

## Interpretation

The same-session A/B probe confirms the L2a candidate profile:

```text
medium_chunked + sequential chunk_0 warmup + app_concurrency=2 = viable candidate
```

It preserved structured-output quality while reducing average full-batch wall time from about `32469 ms` to about `24219 ms`, a same-session speedup of about `1.34x`.

The average per-request chunk latency increased under concurrency (`8117 ms` -> `12063 ms`), but batch wall time improved because chunks overlapped.

## Acceptance check

| Criterion | Result |
| --- | --- |
| `business_pass_rate` | `100%` |
| Reasoning leaks | `0` |
| `finish_reason=length` | `0` |
| HTTP errors | `0` |
| Same-session speedup >= `1.2x` | yes, `1.34x` |

## Working profile after L2b

```text
model_id: google/gemma-4-e2b
dataset: blocks_json_medium_chunked
chunks: 4 x 25 blocks
endpoint: /v1/chat/completions
response_format: json_schema
warmup_policy: sequential chunk_0
app_concurrency: 2
requested_parallel: 1
native load/unload: not used
```

## What this proves

- The `app_concurrency=2` candidate remains valid in a same-session A/B comparison.
- The speedup is real enough to exceed the `1.2x` acceptance threshold for this dataset and model.
- The candidate did not degrade parse/schema/business validation in this run.

## What this does not prove yet

- It does not prove the best warmup policy; `chunk_0` warmup may be more expensive than necessary.
- It does not prove the candidate generalizes to long datasets.
- It does not prove native `parallel` settings or controlled load/config behavior.
- It does not evaluate cache/stateful/prefix reuse.

## Next gated steps

1. **L2c warmup policy matrix** for the same medium chunked workload:
   - no warmup;
   - sequential small structured warmup;
   - sequential chunk-0 warmup;
   - sequential full-batch warmup;
   - concurrent full-batch as known-bad regression.
2. **L1d long chunked sequential** after warmup policy is better understood.
3. **L2d long chunked app_concurrency=2** only after long sequential is green.
