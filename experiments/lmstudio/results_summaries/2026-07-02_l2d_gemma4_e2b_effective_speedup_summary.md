# L2d Effective Speedup Evidence — LM Studio Lab

## Scope

- Date: 2026-07-02
- Branch: `next/modular-backend-lab`
- Support commit: `f21c70df`
- Evidence level: controlled live effective-profile probe, not a production benchmark
- Model lab key: `gemma4_e2b_q4km`
- Model ID: `google/gemma-4-e2b`
- Output contract: `factual_blocks.v1`
- Dataset ID: `blocks_json_medium_chunked`
- Chunks: `4 x 25 blocks`
- Endpoint: `/v1/chat/completions`
- Response format: `json_schema`
- Base URL class: localhost loopback
- Native load/unload/download endpoints: not called
- Cache/stateful/vision: not tested
- Raw prompt/response/messages/content stored: no

## Goal

L2b/L2c showed speedup after warmup. L2d checks whether the speedup remains useful when warmup cost is included or when the first chunk is counted as useful work.

The key metrics are:

```text
speedup_excluding_warmup
speedup_including_warmup
effective_speedup
```

## A. Sequential baseline

Run ID: `l2d_effective_baseline_seq_001`

| Metric | Value |
| --- | ---: |
| App concurrency | `1` |
| Warmup policy | `none` |
| Effective profile | `standard` |
| Measured batches | `3` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| All IDs `0..99` covered | yes |
| Structured errors | `0` |
| Finish length count | `0` |
| Reasoning leaks | `0` |
| Total prompt tokens | `15306` |
| Total completion tokens | `11110` |
| Total tokens | `26416` |
| Average end-to-end wall time | `33818 ms` |

This is the L2d same-session end-to-end baseline.

## B. Cheap structured warmup + app concurrency 2

Run ID: `l2d_effective_cheap_warmup_appconc2_001`

| Metric | Value |
| --- | ---: |
| Warmup policy | `sequential_small_structured` |
| Warmup request count | `1` |
| Warmup wall time | `1093 ms` |
| App concurrency | `2` |
| Effective profile | `standard` |
| Measured batches | `3` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| All IDs `0..99` covered | yes |
| Structured errors | `0` |
| Finish length count | `0` |
| Reasoning leaks | `0` |
| Total prompt tokens | `15306` |
| Total completion tokens | `11110` |
| Total tokens | `26416` |
| Average batch wall time excluding warmup | `23083 ms` |
| Average end-to-end wall time including warmup | `23448 ms` |
| Speedup excluding warmup | `1.47x` |
| Effective speedup including warmup | `1.44x` |

## C. Productive first chunk + app concurrency 2

Run ID: `l2d_effective_productive_chunk0_appconc2_001`

| Metric | Value |
| --- | ---: |
| Productive first chunk | yes |
| Warmup policy | `none` |
| Warmup request count | `0` |
| App concurrency | `2` |
| Effective profile | `productive_first_chunk` |
| Measured batches | `3` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| All IDs `0..99` covered | yes |
| Structured errors | `0` |
| Finish length count | `0` |
| Reasoning leaks | `0` |
| Total prompt tokens | `15306` |
| Total completion tokens | `11033` |
| Total tokens | `26339` |
| Average remaining-parallel batch wall time | `19110 ms` |
| Average end-to-end wall time | `27297 ms` |
| Speedup excluding first chunk | `1.77x` |
| Effective speedup including first chunk | `1.24x` |

## Acceptance check

| Profile | Business pass | HTTP/structured errors | Effective speedup | Verdict |
| --- | ---: | ---: | ---: | --- |
| Sequential baseline | `12/12` | `0` | `1.00x` | safe baseline |
| Cheap warmup + concurrency `2` | `12/12` | `0` | `1.44x` | accepted accelerated candidate |
| Productive first chunk + concurrency `2` | `12/12` | `0` | `1.24x` | accepted but weaker candidate |

Both accelerated profiles pass the `>= 1.2x` effective-speedup threshold without validation degradation. The cheap structured warmup profile is the stronger current candidate.

## Best current profile

```text
model_lab_key: gemma4_e2b_q4km
compat_model_id: google/gemma-4-e2b
output_contract: factual_blocks.v1
dataset: blocks_json_medium_chunked
warmup_policy: sequential_small_structured
app_concurrency: 2
requested_parallel: 1
effective_speedup: ~1.44x
business_pass: 100%
native_load_unload: not used
```

## Interpretation

The speedup is not only a post-warmup artifact. With a cheap structured warmup included, the profile still reduces average end-to-end wall time from about `33818 ms` to about `23448 ms`.

The productive first-chunk profile is also viable but weaker in this run: it keeps the first chunk useful, but the end-to-end speedup drops to about `1.24x`.

## What this proves

- `app_concurrency=2` is a real end-to-end acceleration candidate for `factual_blocks.v1` medium chunked processing on `google/gemma-4-e2b`.
- Cheap structured warmup is currently the best measured profile.
- Validation quality stayed intact: parse/schema/business remained `12/12`, with no missing IDs, duplicate IDs, finish-length failures, reasoning leaks, or structured errors.

## What this does not prove yet

- It does not prove this profile generalizes to other models.
- It does not prove long-dataset behavior.
- It does not prove native `parallel` or load/config behavior.
- It does not evaluate plain text artifact workloads.
- It does not evaluate thinking, temperature, prompt-policy variants, cache/stateful, memory residency, or vision.

## Next gated steps

1. Add a Lab model candidates registry before model screening.
2. Add privacy-safe RAM/VRAM/process memory scaffolding.
3. Start model screening with controlled axes:
   - structured JSON baseline;
   - plain text artifact baseline;
   - `temperature=0` first;
   - thinking/reasoning off if available, otherwise record unknown.
4. Keep thinking, temperature sweeps, prompt variants, cache/stateful, and memory-residency experiments for top-2 models after initial screening.
