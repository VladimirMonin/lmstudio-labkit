# LM Studio Lab L3.8c Gemma4 E4B Tiny Live Smoke Plan and Accepted Result

Status: accepted controlled live proof under the managed reusable core. This document preserves the pre-live plan and records the accepted result.

## Candidate

- model_key: `gemma4_e4b_q4km`
- model_id: `google/gemma-4-e4b`
- gate: `l3_8c_gemma4_e4b_tiny_live_smoke`
- route: `tiny_live_chat`
- endpoint_path: `/api/v1/chat`
- requested_context_length: `16384`
- requested_parallel: `1`
- app_concurrency: `1`

## Guardrails before senior live gate

- generation_allowed: `true`
- live_25k_authorized: `false`
- production_default: `false`
- wvm_runtime_integration: `false`
- kv_reuse_proven: `false`
- final_user_facing_recommendation: `false`

## Original pre-live success criteria

- Abort before POST load if any Gemma E4B instance is already loaded.
- Verify exact native load echo for `context_length=16384` and `parallel=1`.
- Execute exactly one managed `/api/v1/chat` request with synthetic-only input.
- Store only prompt/response hashes and character counts in artifacts.
- Unload the exact owned instance and verify final loaded instances return to `0`.
- Keep route matrix, structured JSON, and any production promotion blocked until senior runs the authorized live gate.

## Accepted result

- decision: `tiny_live_smoke_passed`
- prerequisite load-only artifact dir: `experiments/lmstudio/results_summaries/run_l3-8b-gemma4-e4b-load-only-20260707-r2_l3_8b_gemma4_e4b_load_only_16k_32k`
- accepted tiny live artifact dir: `experiments/lmstudio/results_summaries/run_l3-8c-gemma4-e4b-tiny-live-smoke-20260707_l3_8c_gemma4_e4b_tiny_live_smoke`
- Exact native load verification passed at `context_length=16384` and `parallel=1`.
- Exactly one managed `/api/v1/chat` request succeeded with synthetic-only input.
- Cleanup verified and final loaded instances returned to `0`.
- structured_json remains pending.
- route matrix remains blocked until structured JSON closure.
- No production promotion guardrail changed as part of this accepted result.

## Promotion policy

- This accepted result does **not** promote Gemma E4B to production default.
- This accepted result does **not** enable WVM runtime integration.
- This accepted result does **not** prove KV reuse.
- This accepted result does **not** create a user-facing recommendation.

## Historical pre-live plan statement

- This plan originally did **not** mark L3.8c passed.
- This plan does **not** promote Gemma E4B to production default.
- This plan does **not** enable WVM runtime integration.
- This plan does **not** prove KV reuse.
- This plan does **not** create a user-facing recommendation.
