# R2 M1r/M2r Failure Triage — Corrected Measurement Semantics

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab triage, not WVM runtime integration
- Prerequisite: R0 measurement semantics repair and R1 Gemma E2B true-parallel rescreen
- Non-goals: no `src/**`, no QueueManager/UI, no SQLite/migrations, no production model verdict

## Tooling note

R2 M2r required controlled `max_tokens=512` vs `768` comparisons. The Lab `probe-concurrency` command now supports a plain-text-only safe override:

```text
--max-tokens 512|768
```

The override is limited to plain-text diagnostics and is recorded as safe metadata in environment/summary artifacts. Prompt and response text remain unstored.

## M1r structured triage

### qwen35_4b_q4km — sequential small structured

| Field | Value |
| --- | ---: |
| Load run | `r2_qwen35_4b_load_parallel1_001` |
| Triage run | `r2_qwen35_4b_structured_small_seq_001` |
| Cleanup run | `r2_qwen35_4b_cleanup_001` |
| `applied_parallel` | `1` |
| `parallel_semantics` | `sequential` |
| `content_empty` | `true` |
| `reasoning_content_present` | `true` |
| `finish_reason` | `stop` |
| `completion_tokens` | `153` |
| `response_chars` | `0` |
| `error_category` | `empty` |
| Cleanup | `1 -> 0` |

Classification:

```text
content/reasoning routing split
```

The model did not simply produce no tokens: it produced reasoning-side output while compat message content was empty. Do not treat this as a normal structured JSON candidate until response routing / reasoning-off policy is solved.

### gemma4_e4b_q4km — corrected structured true parallel

| Field | Value |
| --- | ---: |
| Load run | `r2_gemma4_e4b_load_parallel2_001` |
| Triage run | `r2_gemma4_e4b_structured_appconc2_true_001` |
| Cleanup run | `r2_gemma4_e4b_cleanup_001` |
| `applied_parallel` | `2` |
| `parallel_verified` | `true` on load echo |
| `parallel_semantics` | `true_parallel` |
| `queue_pressure_mode` | `false` |
| `json_parse_pass_count` | `4/4` |
| `schema_pass_count` | `4/4` |
| `business_pass_count` | `4/4` |
| `finish_length_count` | `0` |
| `structured_error_count` | `0` |
| `effective_speedup` | `1.2962` |
| `vram_peak_mb` | `9814` |
| Cleanup | `1 -> 0` |

Classification:

```text
old appconc2 failure was queue-pressure/methodology, not a model rejection
```

### qwen35_9b_q4km — corrected structured true parallel

Full 4-chunk run:

| Field | Value |
| --- | ---: |
| Load run | `r2_qwen35_9b_load_parallel2_001` |
| Triage run | `r2_qwen35_9b_structured_appconc2_true_001` |
| Cleanup run | `r2_qwen35_9b_cleanup_001` |
| `applied_parallel` | `2` |
| `parallel_verified` | `true` on load echo |
| `parallel_semantics` | `true_parallel` |
| `queue_pressure_mode` | `false` |
| `structured_error_count` | `4` |
| `error_category` | `timeout` |
| `finish_length_count` | `0` |
| `response_chars` | `0` for timeout rows |
| `vram_peak_mb` | `11955` |
| Cleanup | `1 -> 0` |

Follow-up `medium_pair` with wider timeout:

| Field | Value |
| --- | ---: |
| Run | `r2_qwen35_9b_medium_pair_true_timeout120_001` |
| `loaded_parallel` | `2` |
| `parallel_verified` | `true` |
| `parallel_semantics` | `true_parallel` |
| `queue_pressure_mode` | `false` |
| `json_parse_pass_count` | `2/2` |
| `schema_pass_count` | `2/2` |
| `business_pass_count` | `2/2` |
| `finish_length_count` | `0` |
| `structured_error_count` | `0` |
| `avg_request_latency_ms` | `29632.50` |
| `vram_peak_mb` | `12255` |

Classification:

```text
not schema/content instability; full 4-chunk appconc2 exceeds the default timeout envelope
```

Qwen 9B can produce valid true-parallel structured output with a wider timeout on a smaller pair, but the full 4-chunk profile is too slow/heavy for the current default Lab timeout profile.

## M2r plain-text triage

Diagnostic kind:

```text
plain_text_artifacts_normalized
```

Prompt policy remained the normalized concise plain-text envelope. The exact prompt text is intentionally not reproduced in this summary.

```text
120-160 words; plain text only; no JSON/markdown/reasoning/introduction
```

### Sequential `max_tokens=512` vs `768`

| Model | Run max512 | Result max512 | Run max768 | Result max768 | Classification |
| --- | --- | --- | --- | --- | --- |
| `qwen35_4b_q4km` | `r2_m2r_plain_qwen35_4b_seq_max512_001` | `0/4`, `finish_length=4` | `r2_m2r_plain_qwen35_4b_seq_max768_001` | `0/4`, `finish_length=4` | ignores/overruns concise plain-text envelope |
| `gemma4_e4b_q4km` | `r2_m2r_plain_gemma4_e4b_seq_max512_001` | `3/4`, `finish_length=1` | `r2_m2r_plain_gemma4_e4b_seq_max768_001` | `4/4`, `finish_length=0` | fixed by larger token envelope |
| `qwen35_9b_q4km` | `r2_m2r_plain_qwen35_9b_seq_max512_001` | `0/4`, `finish_length=4` | `r2_m2r_plain_qwen35_9b_seq_max768_001` | `0/4`, `finish_length=4` | ignores/overruns concise plain-text envelope |

The Qwen family failures are not fixed by increasing `max_tokens` from `512` to `768`; both variants run into the configured cap on all four tasks. Do not run appconc2 for them under this prompt policy.

### Gemma E4B true-parallel plain text after green baseline

| Field | Value |
| --- | ---: |
| Load run | `r2_m2r_gemma4_e4b_load_parallel2_appconc2_001` |
| Triage run | `r2_m2r_plain_gemma4_e4b_appconc2_max768_001` |
| Cleanup run | `r2_m2r_gemma4_e4b_cleanup_appconc2_001` |
| `loaded_parallel` | `2` |
| `parallel_verified` | `true` |
| `parallel_semantics` | `true_parallel` |
| `queue_pressure_mode` | `false` |
| `max_tokens` | `768` |
| `business_pass_count` | `4/4` |
| `finish_length_count` | `0` |
| `structured_error_count` | `0` |
| `total_wall_time_ms` | `14797` |
| `total_completion_tokens` | `1597` |
| `vram_peak_mb` | `10205` |
| Cleanup | `1 -> 0` |

Token-normalized comparison against Gemma E4B sequential `max_tokens=768`:

| Profile | Wall time | Completion tokens | ms/completion token |
| --- | ---: | ---: | ---: |
| Sequential max768 | `19969 ms` | `1696` | `11.7742` |
| True parallel max768 | `14797 ms` | `1597` | `9.2655` |

Token-normalized speedup:

```text
1.2708x
```

Classification:

```text
Gemma E4B is a valid plain-text candidate only with max_tokens=768; true_parallel=2 is green and exceeds the 1.2x token-normalized threshold.
```

## Current R2 verdicts

| Model | Structured JSON | Plain text | Candidate bucket |
| --- | --- | --- | --- |
| `gemma4_e2b_q4km` | R1 green true-parallel | R1 green true-parallel | baseline candidate |
| `gemma4_e4b_q4km` | R2 green true-parallel | R2 green with `max_tokens=768` | heavier candidate |
| `qwen35_4b_q4km` | reasoning/content split | finish-length at 512 and 768 | needs reasoning/response-routing and prompt policy work |
| `qwen35_9b_q4km` | valid only under wider timeout/smaller pair; full batch timeout | finish-length at 512 and 768 | too heavy / needs timeout and prompt-policy work |

## Next step

Proceed to R3 compact corrected screening matrix, keeping old queue-pressure rows separate from corrected true-parallel evidence.
