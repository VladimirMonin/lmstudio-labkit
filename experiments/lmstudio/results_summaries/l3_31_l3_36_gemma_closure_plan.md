# L3.31-L3.36 Gemma Family Closure Plan

Status: planning/specification artifact. This document defines the phased closure plan for Gemma as a benchmarked model line.

No live inference was run for this plan.

## Strategic goal

Close the Gemma family with an evidence-backed admission matrix, not a single yes/no verdict.

Models in scope:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`
- `google/gemma-4-12b-qat`
- `google/gemma-4-26b-a4b-qat`

Final answer must cover:

1. Best Gemma model for transcript cleanup.
2. Best Gemma model for structured JSON.
3. Safe context windows.
4. Stable JSON structures.
5. Language degradation.
6. Retry requirements.
7. Cache/session/warmup usefulness.
8. Image route support, if any.
9. Stable image tasks/schemas.
10. Remaining blocked modes.

## Admission status taxonomy

Use this taxonomy for every model x task x schema x language x context x runtime mode cell.

| status | meaning |
|---|---|
| `accepted` | A real or sufficiently narrow approved run passed the defined gates. |
| `blocked` | The mode is intentionally blocked by policy or prior failure and must not run without a new repair/admission step. |
| `research_only` | The mode may be explored in prepared/offline form but is not eligible for live benchmark admission. |
| `runner_blocked` | The model/task is not judged; the harness/executor currently cannot run the cell safely. |
| `unsupported_modality` | The model/runtime does not support the requested modality. This is not a quality failure. |
| `prepared_only` | Configs/tests/docs exist, but no live inference has been executed or approved for that cell. |
| `needs_capability_proof` | Runtime metadata and a tiny route probe must pass before any quality benchmark can run. |

## Current accepted evidence

L3.29 live report:

- file: `experiments/lmstudio/results_summaries/l3_29_gemma_family_bounded_matrix_live_results_report.md`
- executed_attempt_count: 113
- pass_count: 113
- fail_count: 0
- hard_fail_count: 0
- privacy_scan_status: pass
- final_loaded_like_count: 0

Accepted at `context_tier=8192`:

| model | transcript_cleanup/simple | structured_json/simple | structured_json/blocks | 26B control |
|---|---|---|---|---|
| `google/gemma-4-e2b` | accepted | accepted | accepted | n/a |
| `google/gemma-4-e4b` | accepted | accepted | accepted | n/a |
| `google/gemma-4-12b-qat` | accepted | accepted | accepted | n/a |
| `google/gemma-4-26b-a4b-qat` | accepted controlled only | blocked | blocked | accepted |

Structured JSON is not currently classified as a Gemma weakness after L3.28d.1 repair and L3.29 72/72 pass.

## Known runner boundary

The managed executor now admits only the explicit context allowlist `8192`, `16384`, and `32768`, and requires the plan `context_tier` to match the executor context exactly.

Observed guards:

```text
managed executor supported context lengths: 8192, 16384, 32768
managed executor context_tier must match executor context
operator live managed requires exactly one context_tier
```

Sources:

```text
lmstudio_labkit/managed_executor.py::ManagedLMStudioExecutor.__post_init__
lmstudio_labkit/managed_executor.py::_validate_plan
lmstudio_labkit/cli.py::_single_managed_context_length
```

Implication: L3.31a can be admitted as a single 16k managed-live canary after non-live gates and explicit live approval. Mixed-context configs such as L3.31b remain prepared-only or `runner_blocked` until they are split by context tier or the runner gains explicit homogeneous grouping.

## Phase plan

### L3.31 — context windows closure

Goal: close 16k/32k for text + structured as either `accepted` or `runner_blocked` with precise cause.

Scope:

- E2B/E4B/12B transcript cleanup at 16k/32k where model registry allows it.
- E2B/E4B/12B structured JSON simple/blocks at 16k/32k where registry allows it.
- 26B only 16k controlled transcript cleanup unless explicitly admitted later.

Required work:

1. Inspect the managed executor context guard.
2. Decide whether to extend executor support safely or produce a prepared-only/context-blocked config pack.
3. Add tests that prevent silently treating runner-blocked as model failure.
4. Publish `l3_31_gemma_context_windows_report.md`.

Live rule: no broad live run until the executor path supports the requested context tier and the user explicitly approves live execution.

### L3.32 — JSON complexity closure

Goal: separate JSON structure complexity from task quality.

Scope:

- simple: already accepted at 8192 for E2B/E4B/12B.
- blocks: already accepted at 8192 for E2B/E4B/12B using hardened contract.
- complex: prepared/research-only until a narrow canary proves runtime/schema stability.
- 26B structured JSON remains blocked until a controlled admission step.

Required work:

1. Prepare bounded complex JSON configs.
2. Keep complex isolated from broad model/context/language cartesian expansion.
3. Add validators/tests/report templates.
4. Publish `l3_32_gemma_json_complexity_report.md`.

### L3.33 — cache/session/warmup closure

Goal: evaluate runtime strategy without mixing it with throughput/parallel/stress.

Planning prerequisite: import the prior source-application-derived LM Studio cache evidence before designing new work.

Evidence import artifact:

```text
experiments/lmstudio/results_summaries/l3_33_gemma_cache_session_warmup_evidence_import.md
```

Prior pre-extraction LabKit cache work already tested three strategy families:

- `stateful_root_branches` via native `/api/v1/chat`;
- `stateless_full_prefix` via `/v1/chat/completions`;
- `compact_memory` via `/v1/chat/completions`.

Accepted imported posture:

- stateful root/branches are functional but remain experimental because physical KV reuse is unproven;
- native streaming instrumentation can expose TTFT and prompt-processing timing, but not cached tokens;
- compact memory is the practical production-shaped candidate;
- `/v1/responses` is research-only cache-accounting: useful at 2k/8k, blocked at 16k by internal errors;
- no prior evidence authorizes 25k live, host-application runtime integration, or production default selection.

Scope:

- cold_per_request baseline.
- stateless full-prefix baseline.
- compact-memory practical candidate.
- stateful root/branches experimental lane.
- small-context `/v1/responses` cache-accounting as research-only, if retained.

Forbidden in this phase:

- throughput benchmarking;
- parallel/stress testing;
- mixed image/text experiments;
- 25k live cache run;
- treating stateful API functionality as proven KV reuse.

Required work:

1. Start from the L3.33 evidence import, not a fresh hypothesis.
2. Prepare cache/session/warmup configs around the three prior strategies.
3. Add result fields for accepted/runner_blocked/research_only/experimental.
4. Publish `l3_33_gemma_runtime_strategy_report.md`.

### L3.34 — image route capability closure

Goal: prove or reject Gemma image route capability per model before any quality benchmark.

Scope:

- metadata capability check;
- runtime accepts image payload;
- tiny image request succeeds;
- cleanup final zero;
- privacy scan.

Status mapping:

- metadata false: `unsupported_modality` or `no_image_route_available`;
- metadata true but route fails: `needs_capability_proof` or `runner_blocked` depending on failure;
- tiny route succeeds: eligible for L3.35 tiny matrix.

Required work:

1. Convert existing direct probe knowledge into a repo-supported capability harness or report.
2. Keep max requests tiny.
3. Publish `l3_34_gemma_image_route_capability_report.md`.

### L3.35 — image matrix closure

Goal: run or prepare the first image quality matrix only after L3.34 proves capability.

Scope:

- simple schema first;
- medium schema only after simple passes;
- complex remains prepared-only/research-only;
- resize `max_side_1024` primary, `max_side_512` fallback;
- task_intent axis from L3.30e.

Forbidden:

- full 480-cell cartesian;
- complex schema live;
- Qwen/Qwen-VL;
- raw prompt/response/image artifacts in Git.

Required work:

1. Promote only eligible models from L3.34.
2. Keep configs capability-gated.
3. Publish `l3_35_gemma_image_matrix_report.md`.

### L3.36 — final Gemma model card synthesis

Goal: publish the final model-line admission matrix.

Required artifact:

```text
experiments/lmstudio/results_summaries/l3_36_gemma_family_model_card.md
```

Must answer the 10 strategic questions listed above.

## Kanban execution graph

Board: `lmstudio-labkit`.

Cards created:

- `t_7b49d992` — L3.31-L3.36 Gemma closure: plan/spec.
- `t_0a10da04` — L3.31 context windows closure.
- `t_2220ac93` — L3.32 JSON complexity closure.
- `t_e56d8fc9` — L3.33 cache session warmup closure.
- `t_3dfa1c37` — L3.34 image route capability closure.
- `t_e930df10` — L3.35 image matrix closure.
- `t_54efb182` — L3.36 final Gemma model card synthesis.

Execution should remain phased. Do not run later live phases just because a prepared config exists.

## Immediate next action

Start L3.31 by closing the executor/context-window gap:

1. If safe, implement executor support for non-8192 context tiers with explicit lifecycle validation.
2. If not safe in the current slice, publish L3.31 as `runner_blocked` with tests that prevent misclassification.

Either path must leave a public-safe report in `experiments/lmstudio/results_summaries/` and must not claim model failure without executable evidence.
