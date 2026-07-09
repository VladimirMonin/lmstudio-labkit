# L3.33 Gemma Cache / Session / Warmup Evidence Import

Status: planning prerequisite for L3.33. No live inference was run for this import.

## Why this exists

LM Studio LabKit was extracted from earlier source-application managed backend work. Cache/session/warmup planning must therefore start from the already accepted pre-extraction LabKit L3 cache evidence instead of re-discovering the same modes.

This document imports the public-safe conclusions that should govern L3.33.

## Source evidence already present in this repository

| artifact | source status | relevance |
|---|---|---|
| `experiments/lmstudio/results_summaries/2026-07-05_l3_cache_stateful_decision_record.md` | accepted | canonical cache/stateful posture |
| `experiments/lmstudio/results_summaries/2026-07-05_l3_3_cache_stateful_gemma_e2b_live_smoke_summary.md` | completed | stateful root + branches functional smoke |
| `experiments/lmstudio/results_summaries/2026-07-05_l3_4_cache_stateful_vs_prefix_gemma_e2b_live_summary.md` | completed | three-mode comparison |
| `experiments/lmstudio/results_summaries/2026-07-05_l3_4b_cache_stateful_instrumentation_gemma_e2b_live_summary.md` | completed | TTFT/prompt-processing instrumentation |
| `experiments/lmstudio/results_summaries/2026-07-06_l3_5r_responses_cache_probe_summary.md` | completed | `/v1/responses` small-context cache-accounting candidate |
| `experiments/lmstudio/results_summaries/2026-07-06_l3_5r_16k_responses_cache_probe_summary.md` | completed | `/v1/responses` 16k blocker |
| `docs/lmstudio_managed_backend_docs/05_prompt_cache_stateful_context_and_reuse.md` | planning doc | mechanism definitions and lecture-context motivation |
| `docs/lmstudio_managed_backend_docs/07_lmstudio_cache_parallel_benchmark_plan.md` | planning doc | original experiment matrix and acceptance criteria |

## Three cache/session strategies already examined

| strategy | route | pre-extraction LabKit evidence | L3.33 planning status |
|---|---|---|---|
| `stateful_root_branches` | native `/api/v1/chat` | functional root + branch requests passed; stateful API accepted previous-state branches | experimental, instrumented, not production default |
| `stateless_full_prefix` | OpenAI-compatible `/v1/chat/completions` | baseline completed; total latency close to stateful in L3.4 | baseline and JSON-compatible fallback |
| `compact_memory` | OpenAI-compatible `/v1/chat/completions` | completed; practical and fastest/simplest branch path in the small L3.4b run | practical candidate / preferred production-shaped mode |

## Accepted conclusions from prior evidence

1. Stateful API functionality is proven for a small Gemma E2B probe.
2. Physical KV/prefix reuse is **not** proven.
3. `cached_tokens` were not exposed by the native `/api/v1/chat` instrumentation path.
4. TTFT and prompt-processing timing are available through native streaming instrumentation.
5. Stateful branch prompt-processing was lower than stateless full-prefix in L3.4b, but this is a candidate signal, not sufficient KV proof.
6. Compact memory remained the practical candidate because it does not depend on hidden server-side state or unproven KV reuse.
7. `/v1/responses` exposed cached-token accounting in the 2k/8k probe and should remain a research-only cache-accounting lane.
8. `/v1/responses` 16k failed with internal errors and blocks any 16k/25k escalation through that route until understood.
9. No prior cache evidence authorizes a 25k live run, host-application runtime integration, or production default selection.

## L3.33 admission posture

| mode | admission status before new L3.33 work | reason |
|---|---|---|
| `cold_per_request` | accepted baseline | existing Gemma text/structured work uses it as conservative baseline |
| `stateless_full_prefix` | accepted baseline for comparison | JSON-compatible, no hidden server state dependency |
| `compact_memory` | preferred candidate | practical, fast in small probe, robust production shape |
| `stateful_root_branches` | experimental | functional, but KV reuse remains unproven |
| `/v1/responses` cache accounting | research_only | cached-token accounting candidate at 2k/8k; 16k blocked |
| 25k long-context cache/session | blocked | no-live prep only; live not authorized and 16k Responses route blocked |
| parallel/cache mixing | blocked for L3.33 | parallel/stress must remain separate from cache/session/warmup closure |

## Required L3.33 planning step

Before any new cache/session/warmup config or live probe, L3.33 must:

1. cite this evidence import;
2. preserve the three-strategy taxonomy: stateful root/branches, stateless full-prefix, compact memory;
3. keep `/v1/responses` as research-only cache accounting;
4. avoid treating stateful functionality as proven KV reuse;
5. avoid mixing cache/session/warmup with parallel/stress;
6. keep compact memory first as the production-practical candidate;
7. label 16k/25k Responses cache escalation as blocked until the internal-error path is understood.

## L3.33 next safe artifact

The next L3.33 implementation artifact should be a prepared-only Gemma runtime-strategy matrix that compares:

- `cold_per_request` baseline;
- `stateless_full_prefix` baseline;
- `compact_memory` practical candidate;
- `stateful_root_branches` experimental;
- optional `/v1/responses` research-only cache-accounting row for small context only.

No live inference should be started by this evidence-import step.
