# MV2.3b — Gemma E4B true_parallel no-warmup follow-up

Date: 2026-07-05

## Why this follow-up exists

MV2.3 proved true_parallel=2 validation and lifecycle for both Gemma models, but E4B missed the `effective_speedup >= 1.2` gate when the non-productive sequential warmup was included:

- E4B with warmup: `speedup_excluding_warmup=1.579x`, `effective_speedup=1.171x`.
- E4B validation/lifecycle were green, but the end-to-end warmup-inclusive speedup was mixed.

This MV2.3b run isolates E4B without warmup to test whether the speedup miss was warmup semantics rather than true_parallel throughput.

## Scope

- Model: `gemma4_e4b_q4km` (`google/gemma-4-e4b`).
- Dataset: `blocks_json_medium_chunked` (`sha256:blocks-json-medium-chunked-v1`).
- Mode: `json_schema_single` / `factual_blocks.v1` validation.
- Config: `m1_3_structured_medium_chunked_gemma4_e4b_appconc2_nowarmup.yaml`.
- Concurrency: `app_concurrency=2`, `configured_parallel=2`, `applied_parallel=2`.
- Warmup: `warmup_runs=0`, `warmup_policy=none`.
- Baseline: MV2.2 E4B managed sequential wall time `76125 ms`.
- System metrics: enabled.

## Command

```powershell
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py run experiments\lmstudio\configs\m1_3_structured_medium_chunked_gemma4_e4b_appconc2_nowarmup.yaml --managed-live-true-parallel --app-concurrency 2 --sequential-baseline-wall-time-ms 76125 --baseline-end-to-end-wall-time-ms 76125 --output-root <local-temp-live-results> --run-id mv2_3b_live_gemma_e4b_tp2_nowarmup_20260705
```

The command exited successfully.

## Result

| Metric | Value |
|---|---:|
| JSON parse | 4/4 |
| Schema | 4/4 |
| Business | 4/4 |
| IDs exact | 4/4 |
| Finish-length | 0 |
| Reasoning leak | 0 |
| Structured errors | 0 |
| Parallel semantics | `true_parallel` |
| Parallel verified | `true` |
| Queue pressure | `false` |
| Cleanup | `cleanup_verified` |
| Final loaded instances | 0 |
| Parallel batch wall time | 51.594 s |
| Effective speedup | 1.475x |
| VRAM peak | 11477 MB |

## System metrics

- samples: `55`
- RAM peak: `35569.496 MB`
- VRAM before/peak/after: `6987 / 11477 / 6749 MB`
- GPU util peak: `97%`
- GPU power peak: `146.26 W`

## Privacy and artifacts

The run wrote the managed true_parallel artifact set:

- `environment.json`
- sanitized `experiment.yaml`
- `run_config.json`
- `metrics.jsonl`
- `structured_errors.jsonl`
- `batch_summary.json`
- `structured_validation_summary.json`
- `structured_validation_summary.csv`
- `privacy_scan.json`
- `report.md`
- `system_samples.jsonl`
- `system_summary.json`

Privacy scan passed:

- `status=pass`
- `violation_count=0`
- `raw_prompt_response_stored=false`

## Conclusion

E4B true_parallel throughput is green when the non-productive warmup is removed:

- validation/lifecycle: green;
- exact cleanup: green;
- effective speedup without warmup: `1.475x`, above the `1.2x` threshold.

MV2.3 should therefore distinguish two claims:

1. true_parallel throughput gate: green for Gemma E2B and E4B;
2. warmup-inclusive end-to-end gate: E4B needs warmup policy semantics before it can be called green.

This does not authorize Qwen recovery, broad CUDA matrix, vision, embeddings, cache/stateful, production default selection or host application runtime integration.
