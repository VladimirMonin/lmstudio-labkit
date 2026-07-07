# LM Studio Lab L3.7b Model Registry Profile Map

Status: accepted lab-only registry slice, no new live inference.

## Scope

- Build the first reusable internal model registry/profile layer on top of L3.7a contracts.
- Keep all recommendations internal to the LM Studio Lab.
- Do not promote any model profile to WVM runtime defaults or final user-facing guidance.

## Registry map

| Model key | Model id | Status | Structured output | Long context | Notes |
| --- | --- | --- | --- | --- | --- |
| `gemma4_e2b_q4km` | `google/gemma-4-e2b` | `primary_lab_candidate` | `supported` | `passed_32k` | Current primary internal lab candidate. |
| `qwen35_4b` | `qwen3.5-4b` | `blocked_structured_output` | `blocked` | `unverified` | Reasoning/public-content routing remains unresolved. |
| `qwen35_9b` | `qwen/qwen3.5-9b` | `recovery_experimental` | `supported` | `unverified` | Recovery/experimental only; exact-build promotion remains blocked. |

## Route policy

Gemma E2B current internal route roles:

- `compact_memory` = primary internal default.
- `native_chat_stateful` = research latency accelerator.
- `stateless_full_prefix` = baseline/fallback.
- `openai_responses` small-context = `cache_accounting_candidate_small_context`.
- `openai_responses` long-context for current `google/gemma-4-e2b` + current LM Studio build = `blocked_by_current_evidence` after the 16k `internal_error` probe.
- That current-evidence block is model/build-scoped only; future models or newer LM Studio builds remain `unverified_for_this_model` until tested and then `needs_retest_on_new_model_or_build` is closed by fresh evidence.

Blocked routes are not recommended routes.

## Structured-output policy

- Strict JSON requires public assistant `content`.
- JSON visible only in `reasoning_content` is a failure, not a pass.
- Qwen 4B remains blocked for strict structured output under the current evidence set.
- Qwen 9B stays recovery/experimental only unless exact-build evidence closes the remaining gaps.
- Gemma E2B remains the current primary lab candidate.

## Evidence refs

Primary Gemma route and safety evidence:

- `experiments/lmstudio/results_summaries/2026-07-06_l3_5b_32k_load_only_summary.md`
- `experiments/lmstudio/results_summaries/2026-07-06_l3_5r_responses_cache_probe_summary.md`
- `experiments/lmstudio/results_summaries/2026-07-06_l3_5r_16k_responses_cache_probe_summary.md`
- `experiments/lmstudio/results_summaries/run_l3-6c-compact-memory-live-smoke-20260706-r2_l3_6c_25k_compact_memory_live_smoke_gemma4_e2b/report.md`
- `experiments/lmstudio/results_summaries/run_l3-6d-mode-comparison-20260706_l3_6d_25k_mode_comparison_gemma4_e2b/report.md`
- `experiments/lmstudio/results_summaries/l3_6e_decision_record.md`

Qwen recovery evidence used by the registry:

- `experiments/lmstudio/results_summaries/2026-07-04_m1_1_structured_small_screening_summary.md`
- `experiments/lmstudio/results_summaries/2026-07-05_mv2_4b_qwen35_4b_structured_small_baseline_summary.md`
- `experiments/lmstudio/results_summaries/2026-07-05_mv2_4b_qwen35_4b_anti_reasoning_summary.md`
- `experiments/lmstudio/results_summaries/2026-07-04_m0_6_qwen35_9b_identity_summary.md`
- `experiments/lmstudio/results_summaries/2026-07-04_m0_7_qwen35_9b_load_echo_summary.md`
- `experiments/lmstudio/results_summaries/2026-07-04_m1_2_structured_medium_chunked_summary.md`

## Production block

Registry profiles remain conservative:

- `production_default=false`
- `wvm_runtime_integration=false` by omission from this lab-only slice
- `kv_reuse_proven=false`
- `is_final_user_facing_recommendation=false`

The registry is an internal lab contract only.

## Next slice

L3.7c should add hardware profile capture and mapping without changing the current production block.
