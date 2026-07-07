# M1.2 Structured JSON Medium Chunked — Sequential Screening (First Pass)

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab structured screening, not host application runtime integration
- Dataset: `blocks_json_medium_chunked`
- Shape: `4` chunks × `25` blocks
- Mode: `json_schema_single`
- Response format: `json_schema` / `factual_blocks.v1`
- Temperature: `0`
- App concurrency: `1`
- Warmup policy: `none`
- Candidates: M1.1 pass candidates only
- Result status: preliminary first-pass screening, not a production model verdict

## Non-goals

```text
no host application runtime integration
no QueueManager/UI
no app_concurrency=4
no cache/stateful
no vision
no embeddings
no qwen35_4b structured medium run after M1.1 failure
```

## Candidate results

| Candidate | Run ID | Chunks pass | Business pass | Missing IDs | Duplicate IDs | Reasoning leaks | Finish length | Wall time | VRAM peak | Result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `gemma4_e2b_q4km` | `m1_2_structured_medium_chunked_gemma4_e2b_001` | `4/4` | `4/4` | `0` | `0` | `0` | `0` | `32625 ms` | `5663 MB` | ✅ pass |
| `gemma4_e4b_q4km` | `m1_2_structured_medium_chunked_gemma4_e4b_001` | `4/4` | `4/4` | `0` | `0` | `0` | `0` | `68781 ms` | `7190 MB` | ✅ pass |
| `qwen35_9b_q4km` | `m1_2_structured_medium_chunked_qwen35_9b_001` | `4/4` | `4/4` | `0` | `0` | `0` | `0` | `87922 ms` | `9190 MB` | ✅ pass |

## Token totals

| Candidate | Prompt tokens | Completion tokens | Total tokens |
| --- | ---: | ---: | ---: |
| `gemma4_e2b_q4km` | `5102` | `3704` | `8806` |
| `gemma4_e4b_q4km` | `5102` | `5423` | `10525` |
| `qwen35_9b_q4km` | `4878` | `5144` | `10022` |

## Lifecycle cleanup

Each candidate was run under the same safety envelope:

```text
native preflight loaded count = 0
controlled load echo verified context_length=8192 parallel=1
compat generation batch
exact native unload cleanup
final loaded count = 0
```

Final GPU state after the M1.2 batch:

```text
VRAM used = 2598 MB
GPU util = 3%
```

## Privacy scan

Accepted M1.2 artifacts were scanned for raw endpoint paths, raw instance IDs, localhost base URL fragments, local paths, token values and raw provider/body sentinel text.

Result:

```text
0 blocking hits
```

Prompt text and response text were not stored. Metrics store hashes, counts, validation flags, timing and resource observations.

## First-pass gate decision

All three M1.2 candidates are eligible for M1.3 accelerated structured screening with `app_concurrency=2`, but practical priority should start with:

```text
1. gemma4_e2b_q4km — fastest and lowest VRAM among M1.2 pass candidates
2. gemma4_e4b_q4km — pass but much slower
3. qwen35_9b_q4km — pass but slowest/heaviest
```

`qwen35_4b_q4km` remains excluded from structured JSON medium screening after the M1.1 empty-output first-pass failure, pending M1r triage.
