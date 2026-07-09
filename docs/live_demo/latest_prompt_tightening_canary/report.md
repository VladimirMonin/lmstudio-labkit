# Latest remote text live report

## Scope

- run_id: `matrix_l3_25_prompt_tightening_canary_e2b_e4b`
- models: `google/gemma-4-e2b, google/gemma-4-e4b`
- request_count: `6`
- execution_modes: `cold_per_request`
- cache_modes: `none`
- resource_telemetry_modes: `timing_only`

## Lifecycle summary

- session_count: `6`
- load_scopes: `per_request`
- cleanup_scopes: `per_request`
- final_loaded_instances: `0`
- session_cleanup_verified: `True`
- session_request_indices: `1`
- session_request_counts: `1`

## Warmup/cache summary

- warmup_request_count: `0`
- measured_request_count: `6`
- cache_hit_reported: `unknown`
- kv_reuse_proven: `False`

## Validation summary

- pass_count: `5`
- fail_count: `1`
- hard_fail_count: `1`
- warning_count: `8`
- length_ratio_warning_count: `0`
- pass_rate: `0.8333`
- failure_categories: `markdown_fence=1`
- warning_categories: `manual_review_required=4, punctuation_metrics=2`
- length_ratio_failures: `count=0; task_ids=none; model_ids=none; min_actual_ratio=None; max_actual_ratio=None; policy_min=[]; policy_max=[]`
- model_status: `google/gemma-4-e2b: fail=1, pass=2; google/gemma-4-e4b: pass=3`

## Axis summaries

- per_language: `ru_en_mixed:pass=2,warning=2; ru_ru:fail=1,hard_fail=1,pass=3,warning=6`
- per_complexity: `simple:fail=1,hard_fail=1,pass=5,warning=8`
- per_volume: `single:fail=1,hard_fail=1,pass=5,warning=8`
- retry_impact: `off:fail=1,hard_fail=1,pass=5,warning=8`

## Timing summary

- latency_ms_min: `760.636`
- latency_ms_max: `1950.327`
- total_latency_ms_min: `760.636`
- total_latency_ms_max: `1950.327`

## Privacy summary

- raw_prompt_response_stored: `False`
- raw_base_url_stored: `False`

## Non-claims

- KV-cache reuse is not proven unless LM Studio reports an explicit cache-hit signal.
- RAM/VRAM telemetry is not claimed for timing-only remote-link runs.
- No image, 12B, 26B, Qwen, throughput, parallel, overnight, or stress gate is covered by this snapshot.
- A downstream staged model wave is not accepted when this snapshot has failures.

## Next gate

Downstream staged run status: `blocked until fail_count is zero`.
