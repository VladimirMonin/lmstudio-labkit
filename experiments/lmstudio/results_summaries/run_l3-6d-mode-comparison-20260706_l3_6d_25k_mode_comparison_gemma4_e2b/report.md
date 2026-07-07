# LM Studio Lab L3.6d Mode Comparison Report

This is a lab-only LM Studio mode comparison gate for a synthetic 25k lecture workload.
production_default=false, wvm_runtime_integration=false, kv_reuse_proven=false.
native_chat_stateful is a research latency candidate only and does not prove KV reuse.

| Field | Value |
| --- | --- |
| experiment_id | `l3_6d_25k_mode_comparison_gemma4_e2b` |
| run_id | `l3-6d-mode-comparison-20260706` |
| mode | `mode_comparison_controlled_live` |
| requested_context_length | `32768` |
| applied_context_length | `32768` |
| requested_parallel | `1` |
| applied_parallel | `1` |
| cleanup_verified | `true` |
| final_loaded_instances | `0` |
| ram_peak_mb | `22859.5` |
| vram_peak_mb | `5942.0` |
| max_ram_peak_mb | `131072` |
| max_vram_peak_mb | `32768` |
| memory_safety_pass | `true` |

## Comparable modes

| Mode | Classification | Success | Non-empty | Prompt ms | TTFT ms | Total latency ms | Tokens/s | Input tokens | Output tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compact_memory | primary_candidate | true | true | None | 2121.0 | 2730.489 | 122.33 | None | None |
| native_chat_stateful | research_latency_candidate | true | true | None | 144.0 | 778.825 | 122.093 | None | None |
| stateless_full_prefix | baseline | true | true | None | 2358.0 | 2978.328 | 121.387 | None | None |

All measured requests use `/api/v1/chat`; only the native_chat_stateful branch uses a hashed previous_response_id in artifacts.
No raw prompt text, raw response text, raw state identifiers, or raw localhost URLs are stored in artifacts.
