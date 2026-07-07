# L1c-alt Medium Chunked Evidence — LM Studio Lab

## Scope

- Date: 2026-07-02
- Branch: `next/modular-backend-lab`
- Commit after runner hardening: `9a4738ca`
- Evidence level: controlled live chunked compat probe, not a production benchmark
- Model ID: `google/gemma-4-e2b`
- Dataset ID: `blocks_json_medium_chunked`
- Source dataset ID: `blocks_json_medium`
- Blocks: `100`
- Chunks: `4 x 25 blocks`
- Endpoint: `/v1/chat/completions`
- Base URL class: localhost loopback
- Response format: `json_schema`
- Mode: sequential chunked structured JSON
- Temperature: `0`
- Requested context length in Lab config: `8192`
- Requested parallel in Lab config: `1`
- App concurrency: `1`
- Native load/unload/download endpoints: not called
- Raw prompt/response/messages/content stored: no

## First controlled chunked probe

Run ID: `l1c_alt_chunked_gemma4_e2b_001`

| Metric | Value |
| --- | ---: |
| Warmup requests | `1` |
| Measured batches | `1` |
| Measured chunk requests | `4` |
| Planned requests | `5` |
| `json_parse_pass` | `4/4` |
| `schema_pass` | `4/4` |
| `business_pass` | `4/4` |
| All IDs `0..99` covered | yes |
| Duplicate IDs | `0` |
| Missing IDs | `0` |
| Reasoning leaks | `0` |
| `finish_reason=length` | `0` |
| Structured errors | `0` |
| Total prompt tokens | `5102` |
| Total completion tokens | `3703` |
| Total tokens | `8805` |
| Total latency | `32984 ms` |
| Average chunk latency | `8246 ms` |
| Max chunk latency | `8500 ms` |

After this first probe, the Lab artifact sanitizer was hardened because the safe aggregate fields `total_prompt_tokens` and `raw_prompt_response_stored` were over-redacted in `batch_summary.json`. Raw prompt/response data was not stored.

## Repeat-3 controlled chunked probe

Run ID: `l1c_alt_chunked_gemma4_e2b_repeat3_001`

| Metric | Value |
| --- | ---: |
| Warmup requests | `1` |
| Measured batches | `3` |
| Measured chunk requests | `12` |
| Planned requests | `13` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| All IDs `0..99` covered | yes |
| Duplicate IDs | `0` |
| Missing IDs | `0` |
| Reasoning leaks | `0` |
| `finish_reason=length` | `0` |
| Structured errors | `0` |
| Total prompt tokens | `15306` |
| Total completion tokens | `11110` |
| Total tokens | `26416` |
| Total latency | `97687 ms` |
| Average chunk latency | `8141 ms` |
| Max chunk latency | `8500 ms` |

Per measured chunk, the current run stayed in a narrow token/latency band:

| Chunk | Prompt tokens | Completion tokens | Total tokens | Latency range |
| --- | ---: | ---: | ---: | ---: |
| `chunk_0000` | `1268` | `911` | `2179` | `7719..8047 ms` |
| `chunk_0001` | `1278` | `931` | `2209` | `8046..8140 ms` |
| `chunk_0002` | `1278` | `930..931` | `2208..2209` | `8188..8485 ms` |
| `chunk_0003` | `1278` | `931` | `2209` | `8062..8500 ms` |

## Interpretation

`blocks_json_medium` failed as a single structured request in the current observed `8192` total-token runtime profile. The chunked mode changes the practical conclusion:

```text
medium_single = blocked by effective context cap
medium_chunked_sequential = works in current runtime
```

For `google/gemma-4-e2b`, `blocks_json_medium_chunked` is a viable current-runtime strategy for medium structured JSON postprocessing when requests are split into four sequential 25-block chunks.

## What this proves

- The Lab can process the 100-block medium dataset through the LM Studio compat endpoint using sequential chunks.
- The `factual_blocks.v1` validation pipeline stayed green across `12/12` measured chunk requests.
- Whole-batch ID coverage remained exact: `0..99`, no missing IDs, no duplicates.
- The run did not hit `finish_reason=length` and did not show reasoning leaks.
- The artifact path remained privacy-safe: raw prompts, raw responses, messages, content, paths, native load IDs, and provider bodies were not stored.

## What this does not prove yet

- It does not prove that medium single-request mode works.
- It does not prove that `32768` context is actually applied; native load/config echo remains blocked by unresolved native load identity.
- It does not prove app-concurrency speedup for `2` or `4` parallel chunk requests.
- It does not evaluate cache, KV reuse, stateful chat, long datasets, vision/frame workflows, or production profile readiness.

## Next gated steps

1. **L2a app-concurrency probe** on the already-green medium chunked workload:
   - compat `/v1/chat/completions` only;
   - start with app concurrency `2`;
   - one warmup batch plus three measured batches;
   - no native load/unload/download;
   - no cache/stateful/vision;
   - compare batch wall time and validation stability against this sequential baseline.
2. **L2a app concurrency `4`** only if concurrency `2` remains valid and useful.
3. **L4b controlled load/config echo** remains blocked until a native/load ID is resolved or provided safely.
