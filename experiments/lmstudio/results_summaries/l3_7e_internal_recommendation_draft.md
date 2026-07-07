# LM Studio Lab L3.7e Internal Recommendation Draft

Status: internal-only lab draft built from L3.7b registry, L3.7c candidate intake, and L3.7d structured JSON evidence with no new live work.

## Guardrails

- Internal only.
- No production/default/runtime/UI implication.
- No final user-facing recommendation.
- `production_default=false`.
- `wvm_runtime_integration=false`.
- `kv_reuse_proven=false`.
- Audience stays `not_user_facing`.

## Evidence used from L3.6 and L3.7

- `experiments/lmstudio/results_summaries/run_l3-6c-compact-memory-live-smoke-20260706-r2_l3_6c_25k_compact_memory_live_smoke_gemma4_e2b/report.md`
- `experiments/lmstudio/results_summaries/run_l3-6d-mode-comparison-20260706_l3_6d_25k_mode_comparison_gemma4_e2b/report.md`
- `experiments/lmstudio/results_summaries/l3_6e_decision_record.md`
- `experiments/lmstudio/results_summaries/l3_7b_model_registry_profile_map.md`
- `experiments/lmstudio/results_summaries/l3_7c_candidate_model_intake_and_hardware_feasibility.md`
- `experiments/lmstudio/results_summaries/l3_7d_structured_json_validation_matrix.md`

## Draft model status

| Model key | Model id | Overall status | Notes |
| --- | --- | --- | --- |
| `gemma4_e2b_q4km` | `google/gemma-4-e2b` | `internal_primary_candidate` | Internal primary draft only: no production default, no host application runtime integration, no KV reuse proof, and no final user-facing recommendation. |
| `qwen35_4b` | `qwen3.5-4b` | `blocked_current_evidence` | Blocked current-evidence recovery note only; not eligible for promotion or user-facing advice. |
| `qwen35_9b` | `qwen/qwen3.5-9b` | `recovery_experimental_only` | Recovery/experimental only; keep separated from internal-primary and user-facing guidance. |
| `gemma4_e4b_q4km` | `google/gemma-4-e4b` | `unverified_candidate` | Unverified candidate only; requires no-live, load-only, live-smoke, and structured-json gates before any route recommendation. |
| `gemma4_12b_qat` | `google/gemma-4-12b-qat` | `unverified_candidate` | Unverified candidate only; requires no-live, load-only, live-smoke, and structured-json gates before any route recommendation. |
| `gemma4_26b_a4b_qat` | `google/gemma-4-26b-a4b-qat` | `unverified_candidate` | Unverified candidate only; requires no-live, load-only, live-smoke, and structured-json gates before any route recommendation. |
| `qwen3_6_35b_a3b` | `qwen/qwen3.6-35b-a3b` | `unverified_candidate` | Unverified candidate only; requires no-live, load-only, live-smoke, and structured-json gates before any route recommendation. |

## Route guidance

| Model key | Route | Draft status | Pending gates | Notes |
| --- | --- | --- | --- | --- |
| `gemma4_e2b_q4km` | `compact_memory` | `internal_primary_candidate` | `-` | Primary internal route for compact-memory reuse in the current lab draft. |
| `gemma4_e2b_q4km` | `native_chat_stateful` | `research_accelerator` | `-` | Research accelerator only for one-root-many-branches experiments. |
| `gemma4_e2b_q4km` | `stateless_full_prefix` | `internal_fallback` | `-` | Baseline fallback route kept for deterministic comparison and recovery. |
| `gemma4_e2b_q4km` | `openai_responses` | `cache_accounting_candidate_small_context` | `-` | Scoped only: small-context cache-accounting candidate, current exact-build long-context block, future retest still lab-only. |
| `gemma4_e2b_q4km` | `strict_json_chat_completions` | `internal_primary_candidate` | `-` | Current internal strict JSON draft candidate after the L3.7d Gemma E2B pass; still lab-only and not a user-facing recommendation. |
| `qwen35_4b` | `strict_json_chat_completions` | `blocked_current_evidence` | `-` | Strict JSON remains blocked because public assistant content stayed empty while reasoning-only JSON appeared under current evidence. |
| `qwen35_9b` | `strict_json_chat_completions` | `recovery_experimental_only` | `-` | Recovery/experimental only. Exact-build and long-context gaps keep this route out of any promotion path. |
| `gemma4_e4b_q4km` | `compact_memory` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; staged gates must pass before any compact-memory recommendation. |
| `gemma4_e4b_q4km` | `native_chat_stateful` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; stateful research routing stays blocked pending staged gates. |
| `gemma4_e4b_q4km` | `stateless_full_prefix` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; baseline/fallback comparison waits on staged gates. |
| `gemma4_e4b_q4km` | `openai_responses` | `needs_live_smoke` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Responses route remains unverified for this candidate and requires staged no-live, load-only, live-smoke, and structured-json closure before recommendation. |
| `gemma4_e4b_q4km` | `strict_json_chat_completions` | `needs_structured_json` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Strict JSON route stays pending until the staged candidate matrix completes. |
| `gemma4_12b_qat` | `compact_memory` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; staged gates must pass before any compact-memory recommendation. |
| `gemma4_12b_qat` | `native_chat_stateful` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; stateful research routing stays blocked pending staged gates. |
| `gemma4_12b_qat` | `stateless_full_prefix` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; baseline/fallback comparison waits on staged gates. |
| `gemma4_12b_qat` | `openai_responses` | `needs_live_smoke` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Responses route remains unverified for this candidate and requires staged no-live, load-only, live-smoke, and structured-json closure before recommendation. |
| `gemma4_12b_qat` | `strict_json_chat_completions` | `needs_structured_json` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Strict JSON route stays pending until the staged candidate matrix completes. |
| `gemma4_26b_a4b_qat` | `compact_memory` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; staged gates must pass before any compact-memory recommendation. |
| `gemma4_26b_a4b_qat` | `native_chat_stateful` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; stateful research routing stays blocked pending staged gates. |
| `gemma4_26b_a4b_qat` | `stateless_full_prefix` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; baseline/fallback comparison waits on staged gates. |
| `gemma4_26b_a4b_qat` | `openai_responses` | `needs_live_smoke` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Responses route remains unverified for this candidate and requires staged no-live, load-only, live-smoke, and structured-json closure before recommendation. |
| `gemma4_26b_a4b_qat` | `strict_json_chat_completions` | `needs_structured_json` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Strict JSON route stays pending until the staged candidate matrix completes. |
| `qwen3_6_35b_a3b` | `compact_memory` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; staged gates must pass before any compact-memory recommendation. |
| `qwen3_6_35b_a3b` | `native_chat_stateful` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; stateful research routing stays blocked pending staged gates. |
| `qwen3_6_35b_a3b` | `stateless_full_prefix` | `needs_load_only` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Unverified candidate route; baseline/fallback comparison waits on staged gates. |
| `qwen3_6_35b_a3b` | `openai_responses` | `needs_live_smoke` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Responses route remains unverified for this candidate and requires staged no-live, load-only, live-smoke, and structured-json closure before recommendation. |
| `qwen3_6_35b_a3b` | `strict_json_chat_completions` | `needs_structured_json` | `needs_no_live_feasibility, needs_load_only, needs_live_smoke, needs_structured_json` | Strict JSON route stays pending until the staged candidate matrix completes. |

## Scoped `openai_responses` policy

This route is not globally blocked:
- `future_models_or_new_builds` -> `needs_live_smoke`; pending gates: `needs_live_smoke`.
- `long_context::l3_7b_current_gemma_e2b_evidence_build` -> `blocked_current_evidence`.
- `small_context` -> `cache_accounting_candidate_small_context`.

## Current internal draft conclusions

- `gemma4_e2b_q4km` is the internal primary candidate for `compact_memory` and `strict_json_chat_completions`, but it remains lab-only.
- `native_chat_stateful` remains a research accelerator only.
- `stateless_full_prefix` remains the internal fallback/baseline.
- `qwen35_4b` remains blocked for strict JSON under current evidence.
- `qwen35_9b` remains recovery/experimental only.
- L3.7c future candidates remain unverified and need staged no-live/load-only/live-smoke/structured-json gates before any route recommendation.

## Next L3.7f decision record

L3.7f should record whether this internal draft stays lab-only, what exact evidence is still missing for any promotion discussion, and why no user-facing recommendation is emitted yet.
