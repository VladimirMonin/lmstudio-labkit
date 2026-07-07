# MV2.2 — Gemma medium sequential through ManagedLabRunner

Date: 2026-07-05

## Scope

- Gate: MV2.2-live managed-runner medium sequential.
- Runner path: `tools.lmstudio_lab.ManagedLabRunner`.
- Lifecycle path: exact native load → live structured generation → exact owned-instance unload.
- Dataset: `blocks_json_medium_chunked` (`sha256:blocks-json-medium-chunked-v1`).
- Mode: `json_schema_single` / `factual_blocks.v1` validation.
- Models:
  - `gemma4_e2b_q4km` (`google/gemma-4-e2b`)
  - `gemma4_e4b_q4km` (`google/gemma-4-e4b`)
- Concurrency: `app_concurrency=1`, `configured_parallel=1`, `applied_parallel=1`.
- System metrics: enabled.

## Commands

```powershell
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py run experiments\lmstudio\configs\m1_2_structured_medium_chunked_gemma4_e2b.yaml --managed-live --output-root <local-temp-live-results> --run-id mv2_2_live_gemma_e2b_20260705
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py run experiments\lmstudio\configs\m1_2_structured_medium_chunked_gemma4_e4b.yaml --managed-live --output-root <local-temp-live-results> --run-id mv2_2_live_gemma_e4b_20260705
```

Both commands exited successfully.

## Per-model results

| Model | Parse | Schema | Business | IDs | Finish-length | Reasoning leak | Structured errors | Cleanup | VRAM peak | Wall time |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| `gemma4_e2b_q4km` | 4/4 | 4/4 | 4/4 | 4/4 | 0 | 0 | 0 | `cleanup_verified`, final loaded `0` | 8167 MB | 37.75 s |
| `gemma4_e4b_q4km` | 4/4 | 4/4 | 4/4 | 4/4 | 0 | 0 | 0 | `cleanup_verified`, final loaded `0` | 9576 MB | 76.125 s |

## Lifecycle evidence

Both runs recorded:

- `load_verified=true`
- `applied_context_length=8192`
- `applied_parallel=1`
- `parallel_verified=true`
- `queue_pressure_mode=false`
- `parallel_semantics=sequential`
- `cleanup_verified_count=1`
- `final_loaded_instances=0`
- endpoint kinds used: native load/list/unload/list plus compat chat generation.

## System metrics

| Model | Samples | RAM peak | VRAM before/peak/after | GPU util peak | GPU power peak |
|---|---:|---:|---:|---:|---:|
| `gemma4_e2b_q4km` | 43 | 33716.426 MB | 4995 / 8167 / 4996 MB | 88% | 119.89 W |
| `gemma4_e4b_q4km` | 80 | 36453.656 MB | 5004 / 9576 / 4996 MB | 92% | 141.43 W |

## Privacy and artifacts

Both runs wrote the managed-live artifact set:

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

- ManagedLabRunner can execute the real medium chunked structured workload for both Gemma candidates.
- The managed-live Lab path performs exact native load, live compat chat generation, real JSON/schema/business/id validation and exact unload cleanup.
- Sequential Gemma medium workload is green for both E2B and E4B at context `8192`, parallel `1`.
- System metrics are captured in the managed-runner artifact set.
- The artifact set remains privacy-safe under the current scanner.

## What this does not prove

- Not true-parallel evidence.
- Not queue-pressure evidence.
- Not Qwen recovery evidence.
- Not broad CUDA matrix evidence.
- Not vision, embeddings, cache/stateful or mixed-workload evidence.
- Not host application runtime integration and not a production default selection.

## Next gates

1. Commit the MV2.2-live managed-runner code and this summary.
2. MV2.3: Gemma true_parallel=2 through ManagedLabRunner only after this sequential gate.
3. Keep Qwen recovery, broad matrix, vision, embeddings, cache/stateful and host application runtime integration out of scope until their own gates.
