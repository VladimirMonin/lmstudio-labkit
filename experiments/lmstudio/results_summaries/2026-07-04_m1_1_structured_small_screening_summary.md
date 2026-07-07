# M1.1 Structured JSON Small Screening — Initial Four Candidates (First Pass)

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab model screening, not WVM runtime integration
- Dataset: `blocks_json_small`
- Mode: `json_schema_single`
- Response format: `json_schema` / `factual_blocks.v1`
- Temperature: `0`
- App concurrency: `1`
- Repeats: `3` independent repeat-1 runs per candidate
- Lifecycle pattern: preflight native list, controlled native load echo, compat generation runs, exact unload cleanup
- Result status: preliminary first-pass screening, not a production model verdict

## Non-goals

```text
no WVM runtime integration
no QueueManager/UI
no app_concurrency=4
no cache/stateful
no vision
no embeddings
no medium/long dataset in this gate
```

## Candidate results

| Candidate | Runs | JSON parse | Schema | Business | Reasoning leak | Finish length | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `gemma4_e2b_q4km` / `google/gemma-4-e2b` | `3` | `3/3` | `3/3` | `3/3` | `0/3` | `0/3` | ✅ pass |
| `qwen35_4b_q4km` / `qwen3.5-4b` | `3` | `0/3` | `0/3` | `0/3` | n/a | `0/3` | ❌ fail: empty structured content |
| `gemma4_e4b_q4km` / `google/gemma-4-e4b` | `3` | `3/3` | `3/3` | `3/3` | `0/3` | `0/3` | ✅ pass |
| `qwen35_9b_q4km` / `qwen/qwen3.5-9b` | `3` | `3/3` | `3/3` | `3/3` | `0/3` | `0/3` | ✅ pass |

## Run IDs

```text
gemma4_e2b:  m1_1_structured_small_gemma4_e2b_r01..r03
qwen35_4b:   m1_1_structured_small_qwen35_4b_r01..r03
gemma4_e4b:  m1_1_structured_small_gemma4_e4b_r01..r03
qwen35_9b:   m1_1_structured_small_qwen35_9b_r01..r03
```

## Timing and resource observations

| Candidate | Total elapsed ms per run | Completion tokens | VRAM peak observed |
| --- | --- | ---: | ---: |
| `gemma4_e2b_q4km` | `1313`, `1203`, `1172` | `95` | `5633 MB` |
| `qwen35_4b_q4km` | `2219`, `2141`, `2125` | `153` | `6639 MB` |
| `gemma4_e4b_q4km` | `1859`, `1812`, `1703` | `91` | `7102 MB` |
| `qwen35_9b_q4km` | `2890`, `2906`, `2703` | `135` | `9090 MB` |

## qwen35_4b first-pass failure classification

`qwen35_4b_q4km` returned `finish_reason=stop` and non-zero token usage, but the stored structured content was empty in all three runs:

```text
response_chars = 0
json_parse_pass = false
schema_pass = false
business_pass = false
error_category = empty
```

This is treated as a first-pass screening failure for the current `factual_blocks.v1` profile. It does not prove the model is inherently unable to produce structured output: the next triage slice should separate model capability from profile issues such as content routing, reasoning/content split, response format handling and prompt policy.

## Lifecycle cleanup

Each candidate run group was surrounded by native lifecycle control:

```text
preflight loaded count = 0
controlled load echo verified context_length=8192 parallel=1
exact unload cleanup after generation
final loaded count = 0
```

Final GPU state after the screening batch returned near baseline:

```text
VRAM used = 2589 MB
GPU util = 1%
```

## Privacy notes

- Prompt text and response text were not stored.
- Artifacts keep hashes, counts, validation flags and timing/resource metrics.
- No raw instance ids are stored; lifecycle artifacts use hashes.
- No WVM runtime, UI or application queues were involved.

## First-pass gate decision

Proceed to M1.2 medium chunked sequential only for M1.1 passing candidates:

```text
gemma4_e2b_q4km
gemma4_e4b_q4km
qwen35_9b_q4km
```

Hold `qwen35_4b_q4km` out of structured JSON medium screening until M1r failure triage explains the empty-output behavior. Do not treat this as a production rejection.
