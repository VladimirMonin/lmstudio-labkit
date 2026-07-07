# LM Studio Lab L3.6c Compact Memory Controlled Live Smoke Report

This is a lab-only compact_memory-only live smoke gate after L3.6b prompt minimization.
production_default=false, wvm_runtime_integration=false, kv_reuse_proven=false.
KV reuse is not proven by this run.

R1 note: the first attempt failed due to a privacy-scan false positive on a public model_id-as-instance marker.
R2 passed after an exact-match-only exemption for that public marker.

| Field | Value |
| --- | --- |
| experiment_id | `l3_6c_25k_compact_memory_live_smoke_gemma4_e2b` |
| run_id | `l3-6c-compact-memory-live-smoke-20260706-r2` |
| mode | `compact_memory_controlled_live_smoke` |
| route | `compact_memory` |
| endpoint_path | `/api/v1/chat` |
| requested_context_length | `32768` |
| applied_context_length | `32768` |
| requested_parallel | `1` |
| applied_parallel | `1` |
| load_verified | `true` |
| generation_called | `true` |
| request_succeeded | `true` |
| non_empty_text_pass | `true` |
| cleanup_verified | `true` |
| final_loaded_instances | `0` |
| ram_peak_mb | `24482.148` |
| vram_peak_mb | `5617.0` |
| max_ram_peak_mb | `131072` |
| max_vram_peak_mb | `32768` |
| memory_safety_pass | `true` |
| production_default | `false` |
| wvm_runtime_integration | `false` |
| kv_reuse_proven | `false` |
| temperature | `0` |
| max_output_tokens | `64` |
| estimated_input_tokens | `22700` |

The run performs exactly one compact-memory `/api/v1/chat` request after an exact native load verification and requires exact unload cleanup proof.
A pass decision also requires a clean privacy scan and memory peaks within the configured lab-only safety thresholds.
No raw prompt, raw response text, raw response identifiers, or raw localhost URLs are stored in artifacts.
