# L3.8d Gemma4 E4B Strict JSON Smoke Plan

- model_key: `gemma4_e4b_q4km`
- model_id: `google/gemma-4-e4b`
- gate: `l3_8d_gemma4_e4b_strict_json_smoke`
- status_before_live: `structured_json_pending`
- status_after_live: `structured_json_passed`
- accepted_artifact_dir: `experiments/lmstudio/results_summaries/run_l3-8d-gemma4-e4b-strict-json-smoke-20260707_l3_8d_gemma4_e4b_strict_json_smoke`

## Preconditions

- L3.8a no-live feasibility is accepted.
- L3.8b load-only 16k/32k is accepted.
- L3.8c tiny live smoke is accepted.
- This document now preserves both the original plan intent and the accepted live result.

## Accepted result

- L3.8d passed.
- exact owned native load stayed `context_length=8192`, `parallel=1`
- exactly one managed `/v1/chat/completions` request succeeded
- `request_succeeded=true`, `public_content_pass=true`, `reasoning_content_present=false`
- `json_parse_pass=true`, `schema_pass=true`, `business_pass=true`, `structured_gate_status=passed`
- `cleanup_verified=true` with final loaded instances `0`
- privacy pass retained with no raw prompt/response, no raw state ids, no raw localhost URLs in artifacts

## Artifact chain

- L3.8b accepted artifact dir: `experiments/lmstudio/results_summaries/run_l3-8b-gemma4-e4b-load-only-20260707-r2_l3_8b_gemma4_e4b_load_only_16k_32k`
- L3.8c accepted artifact dir: `experiments/lmstudio/results_summaries/run_l3-8c-gemma4-e4b-tiny-live-smoke-20260707_l3_8c_gemma4_e4b_tiny_live_smoke`
- L3.8d accepted artifact dir: `experiments/lmstudio/results_summaries/run_l3-8d-gemma4-e4b-strict-json-smoke-20260707_l3_8d_gemma4_e4b_strict_json_smoke`

## Intended live contract

- exact owned native load: `context_length=8192`, `parallel=1`
- exactly one managed `/v1/chat/completions` request
- route classification: `strict_json_chat_completions`
- helper mode may stay `json_schema_single`
- public assistant content must be non-empty
- `reasoning_content_present` must be `false` or absent
- exact unload cleanup proof required with final loaded instances `0`
- privacy-safe artifacts only; no raw prompt/response, no raw state ids, no raw localhost URLs

## Promotion guardrails

- production_default: `false`
- wvm_runtime_integration: `false`
- kv_reuse_proven: `false`
- final_user_facing_recommendation: `false`

## Release intent after acceptance

- E4B is now eligible for L3.9 product-shaped viability gates.
- This is not production.
- This is not host application runtime integration.
- This is not route matrix approval.
- This is not a final user-facing recommendation.
- Route matrix remains blocked/deferred because the next gate is L3.9a Blocks JSON functional viability, not route-matrix expansion.
- Next gate: L3.9a Blocks JSON functional viability.
