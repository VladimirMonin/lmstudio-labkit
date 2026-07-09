# L3.33 Gemma Cache/Session/Warmup Evidence Import

Status: prepared evidence import. No L3.33 live inference, model load, model download, cache benchmark, stress run, image request, or raw prompt/response artifact has been run for this record.

## Imported source-application-derived evidence

This record imports prior pre-extraction LabKit evidence at the strategy level only. It is intentionally public-safe: it does not name the source application, private workflows, private hosts, local paths, prompts, responses, or credentials.

| strategy | route family | imported status | L3.33 posture |
|---|---|---|---|
| `stateful_root_branches` | native chat | functional and instrumentable in the source-application-derived evidence | experimental; useful for session semantics, not proof of physical KV reuse |
| `stateless_full_prefix` | OpenAI-compatible chat completions | stable baseline fallback | baseline comparator for repeated full-prefix requests |
| `compact_memory` | OpenAI-compatible chat completions | practical production-shaped candidate | preferred product-shaped strategy unless new L3.33 evidence beats it |
| `/v1/responses` cache accounting | responses route | research-only at small context, blocked at larger context until proven | research-only; excluded from first Gemma admission canary |

## Source evidence already present in this repository

These public-safe prior summaries are the local evidence base for the import:

| artifact | relevance |
|---|---|
| `experiments/lmstudio/results_summaries/2026-07-05_l3_cache_stateful_decision_record.md` | canonical cache/stateful posture |
| `experiments/lmstudio/results_summaries/2026-07-05_l3_3_cache_stateful_gemma_e2b_live_smoke_summary.md` | stateful root and branches functional smoke |
| `experiments/lmstudio/results_summaries/2026-07-05_l3_4_cache_stateful_vs_prefix_gemma_e2b_live_summary.md` | three-mode comparison |
| `experiments/lmstudio/results_summaries/2026-07-05_l3_4b_cache_stateful_instrumentation_gemma_e2b_live_summary.md` | TTFT/prompt-processing instrumentation |
| `experiments/lmstudio/results_summaries/2026-07-06_l3_5r_responses_cache_probe_summary.md` | `/v1/responses` small-context cache-accounting candidate |
| `experiments/lmstudio/results_summaries/2026-07-06_l3_5r_16k_responses_cache_probe_summary.md` | `/v1/responses` larger-context blocker |
| `docs/lmstudio_managed_backend_docs/05_prompt_cache_stateful_context_and_reuse.md` | mechanism definitions |
| `docs/lmstudio_managed_backend_docs/07_lmstudio_cache_parallel_benchmark_plan.md` | original experiment matrix and acceptance criteria |

## Imported interpretation rules

- Stateful API success is not a cache/KV proof by itself.
- Native/session instrumentation may expose TTFT, prompt-processing timing, and request index data, but `kv_reuse_proven` must remain `false` until runtime reports a cache/KV signal.
- Timing-only improvements may set `cache_hit_inferred` after analysis, but `cache_hit_reported` remains `unknown` when the runtime does not report cache hits.
- Cache/session work must stay separate from throughput, scheduler pressure, image, stress, Qwen, and broad context-window experiments.
- Raw prompt/response persistence is not required and remains forbidden for L3.33 public artifacts.

## Required telemetry contract

Prepared L3.33 artifacts must preserve these fields in row-level JSON/CSV/report outputs when data is available:

- `execution_mode`
- `cache_mode`
- `cache_group_id`
- `session_id`
- `session_request_index`
- `is_warmup_request`
- `stable_prefix_hash`
- `schema_hash`
- `prompt_template_hash`
- `dynamic_input_hash`
- `same_input_hash`
- `ttft_ms`
- `prompt_processing_ms`
- `total_latency_ms`
- `tokens_per_sec`
- `cache_hit_reported`
- `cache_hit_inferred`
- `kv_reuse_proven`

## Prepared configs

- `experiments/lmstudio/structured_matrix/configs/matrix.l3_33a_gemma_cache_session_canary.yaml`
- `experiments/lmstudio/structured_matrix/configs/matrix.l3_33b_gemma_prompt_prefix_reuse.yaml`

## Non-claims

This import does not claim:

- Gemma cache/KV reuse;
- `/v1/responses` suitability for large-context Gemma closure;
- live latency, TTFT, prompt-processing, or tokens-per-second results;
- model quality for cache/session modes;
- cleanup final-zero proof for L3.33 live runs.

All live admission remains blocked until a later explicitly approved run produces sanitized telemetry and cleanup proof.
