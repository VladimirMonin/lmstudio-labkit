# L1b Repeatability Evidence — LM Studio Lab

## Scope

- Date: 2026-07-02
- Branch: `next/modular-backend-lab`
- Commit: `f8f4e0ef`
- Evidence level: controlled live repeatability probe, not a production benchmark
- Model ID: `google/gemma-4-e2b`
- Endpoint: `/v1/chat/completions`
- Base URL class: localhost loopback
- Dataset ID: `blocks_json_small`
- Mode: live structured JSON repeatability
- Response format: `json_schema`
- Temperature: `0`
- Context length: `8192`
- Parallel: `1`
- App concurrency: `1`
- Warmup runs: `1`
- Measured runs: `10`
- Raw prompt/response/messages/content stored: no

## Results

| Metric | Value |
| --- | ---: |
| Live CLI commands exit `0` | `11/11` |
| Measured `json_parse_pass` | `10/10` |
| Measured `schema_pass` | `10/10` |
| Measured `business_pass` | `10/10` |
| All-runs parse/schema/business pass | `11/11` |
| Reasoning leak | `0` |
| `finish_reason` | `stop` on all runs |
| Structured errors | `0` |
| Prompt tokens | `98` |
| Completion tokens | `95` |
| Total tokens | `193` |

## Timing

| Metric | Value |
| --- | ---: |
| Warmup latency | `5969 ms` |
| Measured average latency | `1135.8 ms` |
| Measured median latency | `1140.0 ms` |
| Best measured latency | `1110.0 ms` |
| Worst measured latency | `1156.0 ms` |
| P95 shortcut, max of 10 measured runs | `1156.0 ms` |
| Average completion throughput | `83.65 tok/s` |
| Best completion throughput | `85.59 tok/s` |
| Worst completion throughput | `82.18 tok/s` |
| Aggregate completion throughput | `83.64 tok/s` |

Compared with L1a steady state (`~1211 ms` / `~78.5 tok/s`), L1b measured runs were about `75.2 ms` faster on average and about `5.15 tok/s` faster.

## Privacy and artifact handling

- Live artifacts were written to a temporary workspace only, not into the repository.
- The repository was not modified by the live repeatability run.
- Safe artifact scan covered `33` files: metrics, structured errors, and report files across all repeatability run directories.
- Safe leak scan found no raw synthetic source text, raw messages, raw content, raw prompt field, or raw response field.
- `environment.json` contained no base URL, current working directory, environment variables, user names, or local paths.
- Prompt and response were represented only by hashes/character counts in metrics.

## What this proves

- The small structured JSON baseline is repeatable for `google/gemma-4-e2b` under the current Lab contract.
- The LM Studio compat structured-output path returned valid `factual_blocks.v1` data for 10 measured runs after warmup.
- The validation pipeline remained stable: parse, schema-shape, business checks, finish reason, and reasoning leak checks all stayed green.
- The privacy-safe metrics/report path remained clean during repeated live calls.

## What this does not prove yet

- Stability on `blocks_json_medium` or `blocks_json_long`.
- 32k/64k context stability.
- `parallel=2` or `parallel=4` benefit.
- Cache or KV reuse behavior.
- Model load/unload correctness.
- Vision/frame behavior.
- Production profile readiness.

## Next gated steps

1. **L1c-pre medium dataset**: add `blocks_json_medium` offline with 100 synthetic blocks, stable IDs, manifest metrics, and privacy/tests.
2. **L1c live medium probe**: run 1 warmup + 3 measured first, not 10 measured immediately.
3. **L1c live repeatability**: only if the 3-run medium probe is green, run 1 warmup + 10 measured.
4. **Parallel/cache/vision**: do not start until medium/long structured JSON proof is available.
