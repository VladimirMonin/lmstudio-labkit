# R1 True Parallel Rescreen — Gemma E2B

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab rescreen, not WVM runtime integration
- Model key: `gemma4_e2b_q4km`
- Model ID: `google/gemma-4-e2b`
- Goal: validate corrected R0 measurement semantics before wider M1r/M2r triage
- Non-goals: no WVM runtime integration, no QueueManager/UI, no `src/**`, no production model verdict

## Lifecycle envelope

| Step | Run ID | Status | Key evidence |
| --- | --- | --- | --- |
| Preflight native state | `r1_preflight_models_gemma4_e2b_001` | ✅ ok | `loaded_instance_total=0` |
| Controlled load echo | `r1_structured_load_gemma4_e2b_parallel2_001` | ✅ ok | `applied_parallel=2`, `parallel_verified=true`, `observed_loaded_count=1` |
| Exact cleanup | `r1_cleanup_gemma4_e2b_parallel2_001` | ✅ ok | `observed_loaded_count_before=1`, `observed_loaded_count_after=0`, `unload_called=true` |

The generation runs used compat chat only. Native lifecycle calls were limited to preflight/load/unload safety steps. No wildcard unload was used.

## R1.1 Structured JSON true-parallel rescreen

Config added for this rescreen:

```text
experiments/lmstudio/configs/r1_structured_medium_chunked_gemma4_e2b_appconc2_repeat3.yaml
```

Run ID:

```text
r1_structured_gemma4_e2b_appconc2_repeat3_001
```

| Metric | Value |
| --- | ---: |
| `configured_parallel` | `2` |
| `applied_parallel` | `2` |
| `parallel_semantics` | `true_parallel` |
| `parallel_verified` | `null` generation-only summary; load echo verified separately |
| `queue_pressure_mode` | `false` |
| `measured_batches` | `3` |
| `measured_request_count` | `12` |
| `json_parse_pass_count` | `12` |
| `schema_pass_count` | `12` |
| `business_pass_count` | `12` |
| `finish_length_count` | `0` |
| `reasoning_leak_count` | `0` |
| `structured_error_count` | `0` |
| `avg_batch_wall_time_ms` | `26302.33` |
| `avg_end_to_end_wall_time_ms` | `26750.00` |
| `effective_speedup` | `1.2196` |
| `vram_peak_mb` | `8884` |
| `gpu_util_peak_percent` | `99` |

Acceptance result:

```text
PASS — corrected true-parallel structured path stayed valid across 3 measured batches.
```

## R1.2 Plain-text artifact true-parallel rescreen

Diagnostic kind:

```text
plain_text_artifacts_normalized
```

Runs:

| Run ID | Requests pass | Wall time | Completion tokens | Finish length | Parallel semantics | Queue pressure |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `r1_plain_norm_gemma4_e2b_appconc2_true_01` | `4/4` | `8797 ms` | `1425` | `0` | `true_parallel` | `false` |
| `r1_plain_norm_gemma4_e2b_appconc2_true_02` | `4/4` | `8688 ms` | `1515` | `0` | `true_parallel` | `false` |
| `r1_plain_norm_gemma4_e2b_appconc2_true_03` | `4/4` | `8688 ms` | `1445` | `0` | `true_parallel` | `false` |

All three runs reported:

```text
loaded_parallel = 2
applied_parallel = 2
parallel_verified = true
queue_pressure_mode = false
reasoning_leak_count = 0
structured_error_count = 0
raw_prompt_response_stored = false
```

Token-normalized comparison uses the previous valid sequential M2p.1 baseline (`m2p1_plain_norm_gemma4_e2b_seq_01..03`), which remains sequential evidence and did not depend on the broken appconc2 methodology.

| Profile | Avg wall time | Avg completion tokens | ms/completion token |
| --- | ---: | ---: | ---: |
| Sequential baseline | `13302.00 ms` | `1466.00` | `9.0737` |
| R1 true parallel | `8724.33 ms` | `1461.67` | `5.9688` |

Token-normalized speedup:

```text
1.5202x
```

Acceptance result:

```text
PASS — corrected true-parallel plain-text artifact path stayed valid across 3 measured batches.
```

## Interpretation

R1 restores trust in the corrected measurement path for `gemma4_e2b_q4km`:

- `parallel=2` was verified by controlled native load echo before generation.
- Structured JSON true-parallel rescreen passed `12/12` measured requests with `effective_speedup >= 1.2`.
- Plain-text normalized artifact rescreen passed `12/12` measured requests with token-normalized speedup above `1.2x`.
- Old `app_concurrency=2` over `parallel=1` rows remain queue-pressure evidence only and are not reused as true-parallel throughput proof.

This is still a Lab profile validation, not a WVM runtime integration or production model verdict.

## Next step

Proceed to R2 M1r/M2r failure triage with the repaired measurement semantics:

1. `qwen35_4b_q4km` structured sequential triage first.
2. `gemma4_e4b_q4km` and `qwen35_9b_q4km` corrected true-parallel structured triage only after explicit load `parallel=2`.
3. Plain-text M2r `app_concurrency=2` only with matching `loaded_parallel=2`; otherwise mark as explicit queue-pressure.
