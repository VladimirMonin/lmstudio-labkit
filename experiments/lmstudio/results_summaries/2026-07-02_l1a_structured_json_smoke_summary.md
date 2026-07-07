# L1a Structured JSON Smoke Summary

## Evidence

- Date: 2026-07-02
- Branch: `next/modular-backend-lab`
- Commit: `1183a5c2`
- Evidence level: first controlled live smoke, not a production benchmark
- Model ID: `google/gemma-4-e2b`
- Endpoint: `/v1/chat/completions`
- Base URL class: localhost loopback
- Dataset ID: `blocks_json_small`
- Mode: `json_schema_single`
- Response format: `json_schema`
- Temperature: `0`
- Context length: `8192`
- Parallel: `1`
- App concurrency: `1`
- Warmup policy for this evidence: first run treated as warmup during analysis
- Raw prompt/response/messages/content: not stored

## Result

| Metric | Value |
| --- | ---: |
| Runs | `3` |
| Successful structured runs | `3/3` |
| `json_parse_pass` | `3/3` |
| `schema_pass` | `3/3` |
| `business_pass` | `3/3` |
| `reasoning_leak` | `0/3` |
| `finish_reason` | `stop` |
| Structured errors | `0` |
| Prompt tokens | `98` |
| Completion tokens | `95` |
| Total tokens | `193` |
| Average latency, all runs | `2614.3 ms` |
| Median latency | `1219.0 ms` |
| Steady-state average latency, excluding first run | `1211.0 ms` |
| Steady-state completion throughput, excluding first run | `78.5 tok/s` |

## Per-run safe metrics

| Run | Total elapsed | Approx. completion throughput | Status |
| --- | ---: | ---: | --- |
| `l1a_gemma_4_e2b_personal_001` | `5421.0 ms` | `17.5 tok/s` | `ok` |
| `l1a_gemma_4_e2b_personal_002` | `1203.0 ms` | `79.0 tok/s` | `ok` |
| `l1a_gemma_4_e2b_personal_003` | `1219.0 ms` | `77.9 tok/s` | `ok` |

## Privacy and artifact handling

- Live artifacts were written to a temporary workspace only, not into the repository.
- The repository was not modified by the live runs.
- Safe leak scan found no raw synthetic source text, raw messages, raw content, raw prompt field, or raw response field in metrics, structured errors, or report artifacts.
- `environment.json` contained only safe platform/run fields; it did not contain base URL, current working directory, environment variables, user names, or local paths.
- Prompt and response were represented only by hashes/character counts in metrics.

## What this proves

- LM Studio accepted one structured-output compat request for the baseline dataset.
- The model returned non-empty JSON content that passed parse, schema-shape, and business validation.
- The Lab harness produced privacy-safe metrics and report artifacts for the live path.
- The first measured steady-state baseline for this tiny structured dataset is about `1.21 s` / `78.5 completion tok/s` after excluding the first run.

## What this does not prove yet

- Stability on `blocks_json_medium` or `blocks_json_long`.
- Production reliability over 10-20 repeated runs.
- Parallel request benefit or degradation.
- Long-context, cache, stateful, load/unload, or vision behavior.
- Production model/profile selection.

## Warmup discipline for next Lab slices

The first run showed much higher latency than the next two runs. Future benchmark-style slices should treat the first run as warmup and report both all-run and steady-state metrics:

```yaml
warmup_runs: 1
repeats: 3
```

Required report fields for comparable measurements:

- `average_all_ms`
- `median_all_ms`
- `average_steady_state_ms_excluding_warmup`
- `steady_state_completion_tok_s`
- pass rates for JSON parse, schema-shape validation, business validation, reasoning leak, and finish reason

## Next gated steps

1. **L1b repeatability**: same model, same `blocks_json_small`, `temperature=0`, 10-20 measured runs after one warmup, no raw prompt/response storage.
2. **L1c bigger structured datasets**: add `blocks_json_medium` and `blocks_json_long` only after repeatability is green.
3. **L2 parallel probes**: try `parallel=2` before `parallel=4`, only after repeatability and bigger-dataset JSON proof.
