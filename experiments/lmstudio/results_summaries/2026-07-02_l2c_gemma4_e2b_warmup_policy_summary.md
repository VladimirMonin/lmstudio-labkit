# L2c Warmup Policy Evidence — LM Studio Lab

## Scope

- Date: 2026-07-02
- Branch: `next/modular-backend-lab`
- Evidence level: controlled live warmup policy matrix, not a production benchmark
- Model ID: `google/gemma-4-e2b`
- Dataset ID: `blocks_json_medium_chunked`
- Chunks: `4 x 25 blocks`
- Endpoint: `/v1/chat/completions`
- Response format: `json_schema`
- App concurrency: `2`
- Requested parallel in Lab config: `1`
- Baseline reference: same-session sequential average batch wall time `32469 ms`
- Native load/unload/download endpoints: not called
- Cache/stateful/vision: not tested
- Raw prompt/response/messages/content stored: no

## Why this slice exists

L2b proved that `app_concurrency=2` can beat sequential on measured batches after warmup. L2c checks whether the warmup itself is mandatory, cheap, productive, or state-dependent.

The key distinction is:

```text
measured speedup after warmup != effective production speedup including warmup
```

L2c is diagnostic evidence for runtime warmup behavior, not a final production-profile decision.

## Warmup policy matrix

| Policy | Result | Average batch wall time | Speedup vs baseline | Notes |
| --- | --- | ---: | ---: | --- |
| `none` first run | partial fail | `22766 ms` | `1.43x` | `11/12` chunks passed; one HTTP `500` on first measured `chunk_0000` |
| `none` retry | pass | `23344 ms` | `1.39x` | `12/12` chunks passed after runtime was already warm |
| `sequential_small_structured` | pass | `22807 ms` | `1.42x` | cheap structured warmup candidate |
| `sequential_chunk_0` | pass | `22906 ms` | `1.42x` | previous working candidate |
| `sequential_full_batch` | pass | `22813 ms` | `1.42x` | more expensive warmup with no clear batch-wall advantage |
| `concurrent_full_batch` | pass in this run | `23062 ms` | `1.41x` | previously failed; behavior is runtime-state dependent |

## Per-policy evidence

### `none`, first run

Run ID: `l2c_warmup_none_appconc2_001`

| Metric | Value |
| --- | ---: |
| Warmup request count | `0` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `11/12` |
| `schema_pass` | `11/12` |
| `business_pass` | `11/12` |
| Structured errors | `1` |
| Error | HTTP `500` on first measured `batch_0001_chunk_0000` |
| Average batch wall time | `22766 ms` |

### `none`, retry after runtime was warm

Run ID: `l2c_warmup_none_appconc2_retry_002`

| Metric | Value |
| --- | ---: |
| Warmup request count | `0` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| Structured errors | `0` |
| Average batch wall time | `23344 ms` |
| Speedup vs baseline | `1.39x` |

### `sequential_small_structured`

Run ID: `l2c_warmup_small_structured_appconc2_001`

| Metric | Value |
| --- | ---: |
| Warmup request count | `1` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| Structured errors | `0` |
| Average batch wall time | `22807 ms` |
| Speedup vs baseline | `1.42x` |

### `sequential_chunk_0`

Run ID: `l2c_warmup_chunk0_appconc2_001`

| Metric | Value |
| --- | ---: |
| Warmup request count | `1` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| Structured errors | `0` |
| Average batch wall time | `22906 ms` |
| Speedup vs baseline | `1.42x` |

### `sequential_full_batch`

Run ID: `l2c_warmup_fullseq_appconc2_001`

| Metric | Value |
| --- | ---: |
| Warmup request count | `4` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| Structured errors | `0` |
| Average batch wall time | `22813 ms` |
| Speedup vs baseline | `1.42x` |

### `concurrent_full_batch`

Run ID: `l2c_warmup_fullconcurrent_appconc2_001`

| Metric | Value |
| --- | ---: |
| Warmup request count | `4` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| Structured errors | `0` |
| Average batch wall time | `23062 ms` |
| Speedup vs baseline | `1.41x` |

## Interpretation

L2c shows that runtime state matters.

Do not conclude that one warmup policy is universally required. After the runtime was warm, several policies produced similar measured batch wall times around `22.8..23.3 s` with `12/12` validation passes.

The first no-warmup run produced one HTTP `500`, then a later no-warmup retry passed. The previously bad concurrent full-batch warmup also passed later. This indicates a stateful/runtime-readiness component rather than a simple static rule.

## Practical candidate after L2c

The safest cheap candidate remains:

```text
warmup_policy: sequential_small_structured
app_concurrency: 2
```

It passed, costs only one small structured request, and avoids spending a full medium chunk as non-productive warmup.

The existing stable candidate remains:

```text
warmup_policy: sequential_chunk_0
app_concurrency: 2
```

But its warmup cost must be counted if the warmup output is discarded.

## What this proves

- `app_concurrency=2` remains viable once the runtime is warm.
- Cheap structured warmup is a promising candidate.
- Warmup policy and runtime state both matter.

## What this does not prove yet

- It does not prove the end-to-end production speedup after warmup cost is included.
- It does not prove whether chunk `0` can serve as productive warmup and count as useful output.
- It does not prove long-dataset behavior.
- It does not evaluate cache/stateful/prefix reuse.

## Next gated step

Run **L2d effective production warmup profile**:

1. Sequential baseline end-to-end.
2. Cheap warmup + `app_concurrency=2`, measuring warmup plus parallel batch.
3. Productive first chunk: chunk `0` sequential, then chunks `1..3` with `app_concurrency=2`, counting chunk `0` as useful output.

Acceptance should use effective speedup including warmup, not only measured speedup after warmup.
