# L2a Concurrency Diagnostics Evidence — LM Studio Lab

## Scope

- Date: 2026-07-02
- Branch: `next/modular-backend-lab`
- Diagnostics harness commit: `cdb3525f`
- Evidence level: controlled live concurrency diagnostics, not a production benchmark
- Model ID: `google/gemma-4-e2b`
- Main dataset ID: `blocks_json_medium_chunked`
- Endpoint: `/v1/chat/completions`
- Base URL class: localhost loopback
- Native load/unload/download endpoints: not called
- Cache/stateful/vision: not tested
- Raw prompt/response/messages/content stored: no

## Correct interpretation

The initial L2a failure must not be interpreted as “LM Studio parallel is broken” or “the model cannot run parallel.” The precise failed scenario was narrower:

```text
medium_chunked structured JSON
+ /v1/chat/completions
+ app_concurrency=2
+ concurrent full-batch warmup
= HTTP errors during warmup
```

Differential diagnostics show that structured concurrency itself works, medium chunk pairs work, and full medium batches work with `app_concurrency=2` after a sequential warmup.

## Diagnostic matrix

| Case | Result | Key evidence | Meaning |
| --- | --- | --- | --- |
| `plain_text_pair` | mixed | HTTP `500` on one request, `finish_reason=length` on one request | Noisy diagnostic; not the target production profile |
| `structured_small_pair` | pass | `2/2` parse/schema/business, `0` structured errors | Structured JSON concurrency can work |
| `medium_pair` chunks `0+1` | pass | `2/2` parse/schema/business, `0` structured errors | Medium chunks can run concurrently in pairs |
| full batch `app_concurrency=2` with concurrent full-batch warmup | fail | HTTP `500` during warmup; measured batches did not start | Concurrent warmup full batch is unsafe |
| full batch `app_concurrency=2` after sequential chunk-0 warmup | pass | `12/12` parse/schema/business, speedup about `1.42x` | Current best parallel candidate |
| full batch `app_concurrency=4` after sequential chunk-0 warmup | fail | HTTP `400` on `12/12` measured chunk requests | Too aggressive for current profile |

## Structured small pair

Run ID: `l2a_diag_structured_small_pair_001`

| Metric | Value |
| --- | ---: |
| Requests | `2` |
| App concurrency | `2` |
| `json_parse_pass` | `2/2` |
| `schema_pass` | `2/2` |
| `business_pass` | `2/2` |
| Structured errors | `0` |
| Finish length count | `0` |
| Reasoning leaks | `0` |
| Total prompt tokens | `196` |
| Total completion tokens | `190` |
| Total tokens | `386` |
| Total wall time | `1609 ms` |

## Medium pair

Run ID: `l2a_diag_medium_pair_001`

| Metric | Value |
| --- | ---: |
| Requests | `2` |
| Chunks | `0` and `1` |
| App concurrency | `2` |
| `json_parse_pass` | `2/2` |
| `schema_pass` | `2/2` |
| `business_pass` | `2/2` |
| Structured errors | `0` |
| Finish length count | `0` |
| Reasoning leaks | `0` |
| Total prompt tokens | `2546` |
| Total completion tokens | `1842` |
| Total tokens | `4388` |
| Total wall time | `10812 ms` |

## Full medium batch, app concurrency 2, sequential warmup

Run ID: `l2a_chunked_gemma4_e2b_appconc2_seqwarm_001`

| Metric | Value |
| --- | ---: |
| Warmup policy | sequential `chunk_0000` |
| App concurrency | `2` |
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
| Average batch wall time | `22953 ms` |
| Sequential baseline used for comparison | `32562 ms` |
| Speedup vs sequential baseline | `1.42x` |

## Full medium batch, app concurrency 4, sequential warmup

Run ID: `l2a_chunked_gemma4_e2b_appconc4_seqwarm_001`

| Metric | Value |
| --- | ---: |
| App concurrency | `4` |
| Measured batches | `3` |
| Measured chunk requests | `12` |
| HTTP errors | `12/12` |
| Error status | `http_400` |
| `json_parse_pass` | `0/12` |
| `schema_pass` | `0/12` |
| `business_pass` | `0/12` |
| Structured errors | `12` |
| Reported wall-time speedup | not useful; all requests failed |

## Working candidate profile

The current candidate profile is:

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

- LM Studio compat structured-output concurrency is possible for this model.
- `app_concurrency=2` can process the medium chunked workload with valid `factual_blocks.v1` output after sequential warmup.
- Concurrent full-batch warmup is unsafe in this profile.
- `app_concurrency=4` is too aggressive for the current profile.

## What this does not prove yet

- It does not prove that `app_concurrency=2` is stable across repeated same-session A/B runs.
- It does not prove that concurrency generalizes to longer datasets.
- It does not prove native `parallel`/continuous-batching configuration, because native load/config echo remains blocked by unresolved native load identity.
- It does not evaluate cache, stateful chat, prefix reuse, or vision/frame workflows.

## Next gated steps

1. **L2b same-session A/B repeatability**:
   - same loaded runtime;
   - sequential chunk-0 warmup;
   - sequential baseline `app_concurrency=1`, three measured batches;
   - candidate `app_concurrency=2`, three measured batches;
   - compare speedup using same-session numbers.
2. **L2c warmup policy matrix**:
   - no warmup;
   - sequential small structured warmup;
   - sequential chunk-0 warmup;
   - sequential full-batch warmup;
   - concurrent full-batch as known-bad regression.
3. Do not retry `app_concurrency=4` until there is a new reason to do so.
