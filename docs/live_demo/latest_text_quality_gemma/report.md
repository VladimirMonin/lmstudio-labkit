# Latest remote text live report

## Scope

- run_id: `matrix_l3_17_text_quality_remote_e2b_e4b`
- models: `google/gemma-4-e2b, google/gemma-4-e4b`
- request_count: `16`
- execution_modes: `cold_per_request`
- cache_modes: `none`
- resource_telemetry_modes: `timing_only`

## Lifecycle summary

- session_count: `16`
- load_scopes: `per_request`
- cleanup_scopes: `per_request`
- final_loaded_instances: `0`
- session_cleanup_verified: `True`
- session_request_indices: `1`
- session_request_counts: `1`

## Warmup/cache summary

- warmup_request_count: `0`
- measured_request_count: `16`
- cache_hit_reported: `unknown`
- kv_reuse_proven: `False`

## Validation summary

- pass_count: `16`
- fail_count: `0`
- hard_fail_count: `0`
- warning_count: `4`
- length_ratio_warning_count: `4`
- pass_rate: `1.0`
- failure_categories: `none`
- warning_categories: `too_long=4`
- length_ratio_failures: `count=4; task_ids=ru_ru_simple_single; model_ids=google/gemma-4-e2b,google/gemma-4-e4b; min_actual_ratio=7.6842; max_actual_ratio=7.7368; policy_min=[0.1]; policy_max=[5.0]`
- model_status: `google/gemma-4-e2b: pass=8; google/gemma-4-e4b: pass=8`

## Axis summaries

- per_language: `ru_en_mixed:pass=4,warning=0; ru_ru:pass=12,warning=4`
- per_complexity: `complex:pass=4,warning=0; medium:pass=8,warning=0; simple:pass=4,warning=4`
- per_volume: `many:pass=4,warning=0; single:pass=12,warning=4`
- retry_impact: `off:pass=8,warning=2; retry1:pass=8,warning=2`

## Timing summary

- latency_ms_min: `676.586`
- latency_ms_max: `1428.75`
- total_latency_ms_min: `676.586`
- total_latency_ms_max: `1428.75`

## Privacy summary

- raw_prompt_response_stored: `False`
- raw_base_url_stored: `False`

## Non-claims

- KV-cache reuse is not proven unless LM Studio reports an explicit cache-hit signal.
- RAM/VRAM telemetry is not claimed for timing-only remote-link runs.
- No image, 12B, 26B, Qwen, throughput, parallel, overnight, or stress gate is covered by this snapshot.
- A downstream staged model wave is not accepted when this snapshot has failures.

## Next gate

Downstream staged run status: `open for the next explicitly scoped staged run`.
