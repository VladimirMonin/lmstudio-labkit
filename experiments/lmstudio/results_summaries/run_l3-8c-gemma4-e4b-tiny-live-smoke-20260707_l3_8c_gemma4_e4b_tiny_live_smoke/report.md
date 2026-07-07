# LM Studio Lab L3.8c Gemma4 E4B Tiny Live Smoke Report

This is a lab-only controlled tiny live smoke for Gemma4 E4B after L3.8b load-only acceptance.
production_default=false, wvm_runtime_integration=false, kv_reuse_proven=false, final_user_facing_recommendation=false.

| Field | Value |
| --- | --- |
| experiment_id | `l3_8c_gemma4_e4b_tiny_live_smoke` |
| run_id | `l3-8c-gemma4-e4b-tiny-live-smoke-20260707` |
| mode | `candidate_tiny_live_smoke` |
| route | `tiny_live_chat` |
| endpoint_path | `/api/v1/chat` |
| requested_context_length | `16384` |
| applied_context_length | `16384` |
| requested_parallel | `1` |
| applied_parallel | `1` |
| load_verified | `true` |
| generation_called | `true` |
| request_succeeded | `true` |
| non_empty_text_pass | `true` |
| cleanup_verified | `true` |
| final_loaded_instances | `0` |
| temperature | `0` |
| max_output_tokens | `64` |
| estimated_input_tokens | `41` |
| failure_reason | `None` |
| production_default | `false` |
| wvm_runtime_integration | `false` |
| kv_reuse_proven | `false` |
| final_user_facing_recommendation | `false` |

The run performs exactly one `/api/v1/chat` request after an exact native load verification and requires exact unload cleanup proof.
No `/v1/responses` or `/v1/chat/completions` calls are allowed in this gate.
No raw prompt, raw response text, raw response identifiers, or raw localhost URLs are stored in artifacts.

## Output Files

- `environment.json`
- `run_config.json`
- `load_response_sanitized.json`
- `requests.jsonl`
- `metrics.jsonl`
- `system_samples.jsonl`
- `system_summary.json`
- `privacy_scan.json`
- `report.md`
