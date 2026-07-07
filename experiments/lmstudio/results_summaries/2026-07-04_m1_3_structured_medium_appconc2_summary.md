# M1.3 Structured JSON Medium Chunked — True Parallel app_concurrency=2 Gate (First Pass)

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab structured screening, not WVM runtime integration
- Dataset: `blocks_json_medium_chunked`
- Shape: `4` chunks × `25` blocks
- Mode: `json_schema_single`
- Response format: `json_schema` / `factual_blocks.v1`
- Temperature: `0`
- App concurrency: `2`
- Loaded model parallel: `2` for accepted true-parallel run
- Warmup policy: `sequential_small_structured`
- Candidates: M1.2 pass candidates only
- Result status: preliminary first-pass screening, not a production model verdict

## Methodology correction and guardrail fix

The original M1.3 runs used client-side `app_concurrency=2` while LM Studio was loaded with `parallel=1`. LM Studio correctly showed `1 processing + 1 queued`, so those rows measured queue pressure / serialized service behavior, not true native parallelism.

The benchmark utility was fixed after this was observed:

```text
run/chunked structured: app_concurrency > configured load parallel is rejected by default
probe-concurrency: app_concurrency > 1 requires --loaded-parallel or --allow-queue-pressure
queue-pressure mode must be explicit
M1.3 appconc2 configs now request load parallel=2
```

Corrected true-parallel sanity evidence below is based on `google/gemma-4-e2b` loaded with `parallel=2`, confirmed visually in LM Studio and by load echo. It proves the repaired measurement path, not a final production profile.

## Acceptance criteria

```text
business_pass_count = 4/4
json_parse_pass_count = 4/4
schema_pass_count = 4/4
reasoning_leak_count = 0
finish_length_count = 0
effective_speedup >= 1.2
HTTP/errors = 0
```

## Corrected true-parallel sanity result

| Candidate | Run ID | Loaded parallel | App concurrency | Queue pressure | Chunks pass | Business pass | Effective speedup | VRAM peak | Result |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |
| `gemma4_e2b_q4km` | `m1r_true_parallel_gemma4_e2b_appconc2_001` | `2` | `2` | `false` | `4/4` | `4/4` | `1.34` | `6053 MB` | ✅ pass |

Load echo for corrected sanity run:

```text
applied_parallel = 2
parallel_verified = true
configured_parallel = 2
queue_pressure_mode = false
```

## Superseded queue-pressure rows

The following rows are retained as first-pass queue-pressure evidence only. They must not be interpreted as native `parallel=2` throughput evidence.

| Candidate | Run ID | Chunks pass | Business pass | Structured errors | Effective speedup | VRAM peak | Result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `gemma4_e2b_q4km` | `m1_3_structured_medium_chunked_gemma4_e2b_appconc2_001` | `4/4` | `4/4` | `0` | `0.94` | `5642 MB` | superseded: queued parallel=1 |
| `gemma4_e4b_q4km` | `m1_3_structured_medium_chunked_gemma4_e4b_appconc2_001` | `1/4` | `1/4` | `3` | `1.11` | `7182 MB` | superseded: queued parallel=1 |
| `qwen35_9b_q4km` | `m1_3_structured_medium_chunked_qwen35_9b_appconc2_001` | `2/4` | `2/4` | `2` | `1.40` | `9165 MB` | superseded: queued parallel=1 |

## First-pass interpretation

True `parallel=2` is confirmed as a corrected Lab sanity proof for the current `gemma4_e2b_q4km` structured JSON candidate:

- `gemma4_e2b_q4km` stayed valid (`4/4`) and reached `1.34x` effective speedup.
- `gemma4_e4b_q4km` and `qwen35_9b_q4km` need true-parallel re-runs before any appconc2 conclusion; their previous rows were queue-pressure only.

This does not create a production default or a settled profile decision. It only restores trust that the Lab can measure true-parallel behavior after the guard fix.

## Lifecycle cleanup

Each candidate was run under the same safety envelope:

```text
native preflight loaded count = 0
controlled load echo verified context_length=8192 parallel=2 for accepted true-parallel run
compat generation batch
exact native unload cleanup
final loaded count = 0
```

Final GPU state after the corrected true-parallel sanity check:

```text
VRAM used = 3002 MB
GPU util = 1%
```

## Privacy scan

Corrected M1.3 sanity artifacts were scanned for raw endpoint paths, raw instance IDs, localhost base URL fragments, local paths, token values and raw provider/body sentinel text.

Result:

```text
0 blocking hits
```

Prompt text and response text were not stored.

## First-pass gate decision

For M1 structured JSON, the current evidence buckets are:

```text
sequential candidate: gemma4_e2b_q4km chunked
corrected true-parallel sanity proof: gemma4_e2b_q4km parallel=2 / app_concurrency=2
sequential candidate: gemma4_e4b_q4km chunked
sequential candidate: qwen35_9b_q4km chunked
```

`gemma4_e2b_q4km` remains the current first-pass structured JSON baseline because it passed M1.1/M1.2 and provided the first corrected true-parallel sanity proof. Gemma E4B and Qwen 9B still require corrected true-parallel triage before any production conclusion.
