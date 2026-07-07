# LM Studio Lab L3.8d Gemma4 E4B Strict JSON Smoke Report

This is a lab-only managed strict JSON chat-completions smoke gate for the current Gemma E4B candidate.
live_25k_authorized=false, production_default=false, wvm_runtime_integration=false, kv_reuse_proven=false, final_user_facing_recommendation=false.
Public assistant content is required; reasoning-only JSON or reasoning_content leakage is a failure.

| Field | Value |
| --- | --- |
| experiment_id | `l3_8d_gemma4_e4b_strict_json_smoke` |
| run_id | `l3-8d-gemma4-e4b-strict-json-smoke-20260707` |
| mode | `strict_json_smoke` |
| route | `strict_json_chat_completions` |
| helper_mode | `json_schema_single` |
| endpoint_path | `/v1/chat/completions` |
| requested_context_length | `8192` |
| applied_context_length | `8192` |
| requested_parallel | `1` |
| applied_parallel | `1` |
| load_verified | `true` |
| generation_called | `true` |
| request_succeeded | `true` |
| public_content_pass | `true` |
| reasoning_content_present | `false` |
| json_parse_pass | `true` |
| schema_pass | `true` |
| business_pass | `true` |
| structured_gate_status | `passed` |
| cleanup_verified | `true` |
| final_loaded_instances | `0` |
| live_25k_authorized | `false` |
| production_default | `false` |
| wvm_runtime_integration | `false` |
| kv_reuse_proven | `false` |
| final_user_facing_recommendation | `false` |
| temperature | `0` |
| max_tokens | `512` |

Exactly one `/v1/chat/completions` structured JSON request runs after exact owned native load verification and before exact unload cleanup verification.
No `/api/v1/chat` or `/v1/responses` calls are allowed in this gate.
No raw prompt text, raw response text, raw state identifiers, or raw localhost URLs are stored in artifacts.
