# L3.3 — Gemma E2B cache/stateful live smoke

Date: 2026-07-05

## Scope

- Gate: L3.3 cache/stateful functional live smoke.
- Runner path: `tools.lmstudio_lab.ManagedLabRunner`.
- Lifecycle path: exact native load → native stateful chat root/branches → exact owned-instance unload.
- Dataset: `cache_stateful_smoke` (`sha256:cache-stateful-smoke-v1`).
- Model: `gemma4_e2b_q4km` (`google/gemma-4-e2b`).
- Context: `8192`.
- Parallelism: `parallel=1`, `app_concurrency=1`.
- Mode: `stateful_root_branches`.
- Branches: `summary_short`, `glossary_short`.
- System metrics: enabled.

## Command

```powershell
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py run experiments\lmstudio\configs\l3_3_cache_stateful_gemma4_e2b_live_smoke.yaml --managed-cache-live-smoke --output-root <local-temp-live-results> --run-id l3_3_live_gemma_e2b_stateful_smoke_20260705_r2 --system-sample-interval-s 1
```

The command exited successfully.

## Result

| Model | Root | Branches | Stateful functional | Reuse verdict | KV reuse proven | Cleanup | Final loaded | Privacy |
|---|---:|---:|---|---|---|---|---:|---|
| `gemma4_e2b_q4km` | 1/1 | 2/2 | yes | `kv_reuse_unproven` | `false` | `cleanup_verified` | 0 | pass |

## Evidence

- `measurement_status=functional_stateful_ok`
- `stateful_functional_ok=true`
- `successful_branch_count=2`
- `branch_count=2`
- `measured_request_count=3`
- `reuse_verdict=kv_reuse_unproven`
- `kv_reuse_proven=false`
- `production_default=false`
- `wvm_runtime_integration=false`
- `raw_prompt_response_stored=false`

## Lifecycle evidence

- `load_verified=true`
- `applied_context_length=8192`
- `context_length_verified=true`
- `applied_parallel=1`
- `parallel_verified=true`
- `cleanup_called=true`
- `cleanup_status=cleanup_verified`
- `cleanup_verified_count=1`
- `final_loaded_instances=0`
- endpoint kinds used: native load/list/unload/list plus native stateful chat requests.

## Request evidence

| Request | Kind | Prompt chars | Estimated tokens | Output present | Used previous root |
|---|---|---:|---:|---|---|
| `root_context` | `stateful_root` | 29112 | 7278 | yes | no |
| `summary_short` | `stateful_branch` | 90 | 23 | yes | yes |
| `glossary_short` | `stateful_branch` | 84 | 21 | yes | yes |

All request artifacts store only hashes, counts, booleans and safe status fields.

## System metrics

| Samples | RAM peak | Process RSS peak | VRAM before/peak/after | GPU util peak | GPU power peak |
|---:|---:|---:|---:|---:|---:|
| 16 | 21606.863 MB | 266.656 MB | 2159 / 5128 / 2159 MB | 87% | 126.04 W |

## Privacy and artifacts

The live smoke wrote the managed cache/stateful artifact set:

- `environment.json`
- sanitized `experiment.yaml`
- `run_config.json`
- `requests.jsonl`
- `metrics.jsonl`
- `cache_summary.json`
- `privacy_scan.json`
- `report.md`
- `system_samples.jsonl`
- `system_summary.json`

Privacy scan:

- `status=pass`
- `violation_count=0`
- `raw_prompt_response_stored=false`

Additional artifact check found no raw localhost URL, synthetic lecture text, raw state IDs, raw output sentinels, `cache_hit=true`, `branch_ttft_improved=true` or `kv_reuse_proven=true`.

## What this proves

- The L3.3 Gemma E2B stateful root + two branch live path works functionally.
- LM Studio accepted branch requests that reference the root response state.
- Exact Lab-managed load/unload cleanup leaves final loaded instances at `0`.
- Privacy-safe cache/stateful artifacts and system metrics are produced.

## What this does not prove

- This is not evidence of physical KV/prefix reuse.
- This is not an L3.4 stateful-vs-stateless prefix comparison.
- This is not a 25k lecture gate.
- This is not Qwen recovery evidence.
- This is not broad CUDA, vision, embeddings, WVM runtime integration or production default selection.

## Next gate

Proceed only to L3.4: compare `stateful_root_branches`, `stateless_full_prefix` and `compact_memory` with TTFT / prompt-processing / branch-latency evidence. Do not start L3.5/L3.6 25k work until L3.4 comparison artifacts are green.
