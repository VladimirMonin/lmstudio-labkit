# L3.4b — Gemma E2B cache/stateful instrumentation probe

Date: 2026-07-05

## Scope

- Gate: L3.4b cache/stateful streaming instrumentation probe.
- Runner path: `tools.lmstudio_lab.ManagedLabRunner`.
- Lifecycle path: exact native load → native `/api/v1/chat` streaming requests → exact owned-instance unload.
- Dataset: `cache_stateful_smoke` (`sha256:cache-stateful-smoke-v1`).
- Model: `gemma4_e2b_q4km` (`google/gemma-4-e2b`).
- Context: `8192`.
- Parallelism: `parallel=1`, `app_concurrency=1`.
- Modes probed: `stateful_root_branches`, `stateless_full_prefix`, `compact_memory`.
- System metrics: enabled.

## Command

```powershell
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py run experiments\lmstudio\configs\l3_4b_cache_stateful_instrumentation_gemma4_e2b_live.yaml --managed-cache-instrument-live --output-root <local-temp-live-results> --run-id l3_4b_live_gemma_e2b_instrumentation_20260705_r2 --system-sample-interval-s 1
```

The command exited successfully.

## Instrumentation availability

| Signal | Result |
|---|---|
| Native streaming events | available |
| TTFT signal | available |
| Prompt-processing timing | available |
| Cached-token field | not exposed |
| Privacy scan | pass |

Summary fields:

- `instrumentation_status=ttft_prompt_processing_available`
- `ttft_available=true`
- `prompt_processing_available=true`
- `cached_tokens_available=false`
- `measurement_status=inconclusive`
- `reuse_verdict=kv_reuse_unproven`
- `kv_reuse_proven=false`

## Branch metrics

| Mode | Branches | Avg total latency | Avg TTFT | Avg prompt-processing |
|---|---:|---:|---:|---:|
| `stateful_root_branches` | 2/2 | 4200.279 ms | 3267.967 ms | 10.098 ms |
| `stateless_full_prefix` | 2/2 | 4520.610 ms | 4113.104 ms | 16.916 ms |
| `compact_memory` | 2/2 | 3250.144 ms | 2534.186 ms | 38.749 ms |

Derived branch prompt-processing ratio:

- `cache_proxy=1.675183`
- Formula: stateless full-prefix branch avg prompt-processing / stateful branch avg prompt-processing.

Interpretation:

- Streaming instrumentation can capture TTFT and prompt-processing timing from LM Studio native events.
- Stateful branch prompt-processing was lower than stateless full-prefix in this run.
- Cached-token evidence was not exposed, so KV reuse remains unproven.
- Compact memory remained the fastest branch path by total latency and TTFT in this run.

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
- endpoint kinds used: native load/list/unload/list plus native streaming chat requests.

## Privacy and artifacts

The live instrumentation probe wrote the managed artifact set:

- `environment.json`
- sanitized `experiment.yaml`
- `run_config.json`
- `requests.jsonl`
- `metrics.jsonl`
- `cache_instrumentation_summary.json`
- `privacy_scan.json`
- `report.md`
- `system_samples.jsonl`
- `system_summary.json`

Privacy scan:

- `status=pass`
- `violation_count=0`
- `raw_prompt_response_stored=false`

Additional artifact check found no raw localhost URL, synthetic lecture text, branch prompt text, compact memory text, raw state IDs, raw output sentinels, `cache_hit=true`, `branch_ttft_improved=true`, `kv_reuse_proven=true`, or `[REDACTED]` placeholders.

## What this proves

- LM Studio native streaming can expose TTFT and prompt-processing timing for the small L3 cache/stateful probe.
- The L3.4b Lab path captures those signals in privacy-safe artifacts.
- The stateful path remains functionally green.
- Exact Lab-managed load/unload cleanup leaves final loaded instances at `0`.

## What this does not prove

- This is not definitive physical KV/prefix reuse proof.
- Cached-token evidence was not exposed.
- The prompt-processing ratio is promising but should be treated as a candidate signal, not a production claim.
- This is not a 25k lecture gate.
- This is not Qwen recovery evidence.
- This is not broad CUDA, vision, embeddings, WVM runtime integration or production default selection.

## Decision update

Keep current posture:

- `stateful_root_branches`: functional, instrumentable, still experimental for KV reuse.
- `compact_memory`: practical candidate and fastest branch path in this small run.
- `stateless_full_prefix`: baseline.
- `kv_reuse`: unproven without cached-token or stronger repeated instrumentation evidence.

Next allowed step: L3.5 no-live 25k prep. Stop before any 25k live run.
