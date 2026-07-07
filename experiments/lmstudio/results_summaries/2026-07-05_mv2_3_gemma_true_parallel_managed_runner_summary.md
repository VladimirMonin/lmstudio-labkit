# MV2.3 — Gemma true_parallel=2 through ManagedLabRunner

Date: 2026-07-05

## Scope

- Gate: MV2.3 managed-runner true_parallel=2.
- Runner path: `tools.lmstudio_lab.ManagedLabRunner`.
- Lifecycle path: exact native load → live structured generation → exact owned-instance unload.
- Dataset: `blocks_json_medium_chunked` (`sha256:blocks-json-medium-chunked-v1`).
- Mode: `json_schema_single` / `factual_blocks.v1` validation.
- Models:
  - `gemma4_e2b_q4km` (`google/gemma-4-e2b`)
  - `gemma4_e4b_q4km` (`google/gemma-4-e4b`)
- Concurrency: `app_concurrency=2`, `configured_parallel=2`, `applied_parallel=2`.
- Baselines: MV2.2 managed sequential wall times from the same medium chunked workload.
- System metrics: enabled.

## Commands

```powershell
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py run experiments\lmstudio\configs\m1_3_structured_medium_chunked_gemma4_e2b_appconc2.yaml --managed-live-true-parallel --app-concurrency 2 --sequential-baseline-wall-time-ms 37750 --baseline-end-to-end-wall-time-ms 37750 --output-root <local-temp-live-results> --run-id mv2_3_live_gemma_e2b_tp2_20260705
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py run experiments\lmstudio\configs\m1_3_structured_medium_chunked_gemma4_e4b_appconc2.yaml --managed-live-true-parallel --app-concurrency 2 --sequential-baseline-wall-time-ms 76125 --baseline-end-to-end-wall-time-ms 76125 --output-root <local-temp-live-results> --run-id mv2_3_live_gemma_e4b_tp2_20260705
```

Both commands exited successfully.

## Per-model results

| Model | Parse | Schema | Business | IDs | Finish-length | Reasoning leak | Structured errors | true_parallel | Cleanup | Speedup excl. warmup | Effective incl. warmup | VRAM peak |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|
| `gemma4_e2b_q4km` | 4/4 | 4/4 | 4/4 | 4/4 | 0 | 0 | 0 | yes | `cleanup_verified`, final loaded `0` | 1.686x | 1.236x | 10108 MB |
| `gemma4_e4b_q4km` | 4/4 | 4/4 | 4/4 | 4/4 | 0 | 0 | 0 | yes | `cleanup_verified`, final loaded `0` | 1.579x | 1.171x | 11721 MB |

## Lifecycle evidence

Both runs recorded:

- `load_verified=true`
- `applied_context_length=8192`
- `applied_parallel=2`
- `parallel_verified=true`
- `queue_pressure_mode=false`
- `parallel_semantics=true_parallel`
- `cleanup_verified_count=1`
- `final_loaded_instances=0`
- endpoint kinds used: native load/list/unload/list plus compat chat generation.

## Timing and warmup

| Model | Sequential baseline | Parallel batch wall time | Warmup wall time | End-to-end wall time | Speedup excluding warmup | Speedup including warmup |
|---|---:|---:|---:|---:|---:|---:|
| `gemma4_e2b_q4km` | 37.750 s | 22.390 s | 8.157 s | 30.547 s | 1.686x | 1.236x |
| `gemma4_e4b_q4km` | 76.125 s | 48.203 s | 16.797 s | 65.000 s | 1.579x | 1.171x |

Interpretation:

- Throughput-only true_parallel evidence is green for both Gemma models (`speedup_excluding_warmup > 1.2`).
- End-to-end effective speedup including the sequential warmup is green for E2B (`1.236x`) but below the `1.2x` target for E4B (`1.171x`).
- Therefore MV2.3 is **not a fully green release gate** if `effective_speedup` is defined as including warmup. E4B should be treated as validation/lifecycle green but speedup-threshold mixed.

## System metrics

| Model | Samples | RAM peak | VRAM before/peak/after | GPU util peak | GPU power peak |
|---|---:|---:|---:|---:|---:|
| `gemma4_e2b_q4km` | 34 | 31352.793 MB | 7139 / 10108 / 7125 MB | 85% | 124.09 W |
| `gemma4_e4b_q4km` | 68 | 33226.719 MB | 7187 / 11721 / 7122 MB | 97% | 148.26 W |

## Privacy and artifacts

Both runs wrote the managed true_parallel artifact set:

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

Both privacy scans passed:

- `status=pass`
- `violation_count=0`
- `raw_prompt_response_stored=false`
- scan scope includes report, CSV/JSON/JSONL, system metrics, environment and sanitized experiment config.

## What this proves

- ManagedLabRunner can execute true_parallel=2 medium chunked structured workload for both Gemma candidates.
- Exact native load/unload cleanup works for true_parallel=2 and leaves final loaded instances at `0`.
- Real JSON/schema/business/id validation is green for both models.
- Queue-pressure is not involved: `app_concurrency=2` is paired with `applied_parallel=2` and `parallel_verified=true`.
- System metrics are captured and privacy scan passes.

## What this does not prove

- Not a fully green speedup gate for E4B if effective speedup includes warmup.
- Not Qwen recovery evidence.
- Not broad CUDA matrix evidence.
- Not vision, embeddings, cache/stateful or mixed-workload evidence.
- Not WVM runtime integration and not a production default selection.

## Next gates

1. Do not proceed to Qwen recovery or broad matrix on the assumption that MV2.3 is fully green.
2. Decide the speedup semantic gate for MV2.3:
   - throughput-only: both Gemma models pass;
   - end-to-end including warmup: E4B needs follow-up.
3. If end-to-end effective speedup is the required gate, run a narrow MV2.3 follow-up for E4B warmup semantics/no-warmup or repeat evidence before expanding the matrix.
