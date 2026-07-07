# L3.4 — Gemma E2B stateful vs stateless prefix comparison

Date: 2026-07-05

## Scope

- Gate: L3.4 cache/stateful comparison live run.
- Runner path: `tools.lmstudio_lab.ManagedLabRunner`.
- Lifecycle path: exact native load → native stateful chat comparison requests → exact owned-instance unload.
- Dataset: `cache_stateful_smoke` (`sha256:cache-stateful-smoke-v1`).
- Model: `gemma4_e2b_q4km` (`google/gemma-4-e2b`).
- Context: `8192`.
- Parallelism: `parallel=1`, `app_concurrency=1`.
- Modes compared: `stateful_root_branches`, `stateless_full_prefix`, `compact_memory`.
- System metrics: enabled.

## Command

```powershell
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py run experiments\lmstudio\configs\l3_4_cache_stateful_vs_prefix_gemma4_e2b_live.yaml --managed-cache-compare-live --output-root <local-temp-live-results> --run-id l3_4_live_gemma_e2b_stateful_vs_prefix_20260705 --system-sample-interval-s 1
```

The command exited successfully.

## Result

| Model | Stateful root | Stateful branches | Stateless branches | Compact branches | Cleanup | Privacy |
|---|---:|---:|---:|---:|---|---|
| `gemma4_e2b_q4km` | 1/1 | 2/2 | 2/2 | 2/2 | `cleanup_verified`, final loaded `0` | pass |

## Evidence status

- `measurement_status=inconclusive`
- `stateful_functional_ok=true`
- `reuse_verdict=kv_reuse_unproven`
- `kv_reuse_proven=false`
- `has_live_measurements=true`
- `measured_request_count=7`
- `production_default=false`
- `wvm_runtime_integration=false`
- `raw_prompt_response_stored=false`

## Latency comparison

| Mode | Branch count | Success count | Avg total latency |
|---|---:|---:|---:|
| `stateful_root_branches` | 2 | 2 | 3664.066 ms |
| `stateless_full_prefix` | 2 | 2 | 3820.077 ms |
| `compact_memory` | 2 | 2 | 3655.695 ms |

Derived comparison:

- `stateless_full_prefix_vs_stateful_total_latency_ratio=1.042579`
- `stateful_total_latency_faster_than_stateless=true`
- Stateful branch total latency was only about **4.3%** faster than stateless full-prefix in this run.
- Compact memory was effectively tied/slightly faster than stateful on total latency in this run.

Important limitation:

- `ttft_ms=null`
- `prompt_processing_ms=null`
- `cached_tokens=null`
- `cache_proxy=null`

Therefore this L3.4 run **does not prove physical KV/prefix reuse**. It is a conservative total-latency comparison only.

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

| Request group | Request count | Prompt shape |
|---|---:|---|
| `stateful_root_branches` | 3 | root prompt once, then two short branches using previous root state |
| `stateless_full_prefix` | 2 | full root prefix repeated in each branch request |
| `compact_memory` | 2 | short synthetic memory plus branch task |

All request artifacts store only hashes, counts, timings, booleans and safe status fields.

## System metrics

| Samples | RAM peak | Process RSS peak | VRAM before/peak/after | GPU util peak | GPU power peak |
|---:|---:|---:|---:|---:|---:|
| 31 | 22205.383 MB | 269.414 MB | 2159 / 5128 / 2159 MB | 84% | 119.19 W |

## Privacy and artifacts

The live comparison wrote the managed cache/stateful comparison artifact set:

- `environment.json`
- sanitized `experiment.yaml`
- `run_config.json`
- `requests.jsonl`
- `metrics.jsonl`
- `cache_comparison_summary.json`
- `privacy_scan.json`
- `report.md`
- `system_samples.jsonl`
- `system_summary.json`

Privacy scan:

- `status=pass`
- `violation_count=0`
- `raw_prompt_response_stored=false`

Additional artifact check found no raw localhost URL, synthetic lecture text, branch prompt text, compact memory text, raw state IDs, raw output sentinels, `cache_hit=true`, `branch_ttft_improved=true` or `kv_reuse_proven=true`.

## What this proves

- The L3.4 Lab path can run a controlled live comparison for Gemma E2B.
- The stateful path is functionally green under the same root + branch setup as L3.3.
- Stateless full-prefix and compact-memory branches also complete successfully.
- Exact Lab-managed load/unload cleanup leaves final loaded instances at `0`.
- Privacy-safe comparison artifacts and system metrics are produced.

## What this does not prove

- This is not evidence of physical KV/prefix reuse.
- This is not TTFT or prompt-processing proof.
- This is not a 25k lecture gate.
- This is not Qwen recovery evidence.
- This is not broad CUDA, vision, embeddings, WVM runtime integration or production default selection.

## Next gate

Before L3.5/L3.6, decide whether L3 needs a second L3.4 instrumentation pass that can capture TTFT/prompt-processing/cached-token signals. If those metrics remain unavailable, treat `compact_memory` as the practical path and keep stateful/cache marked experimental.
