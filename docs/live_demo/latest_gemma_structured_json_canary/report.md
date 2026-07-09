# Latest remote text live report

## Scope

- run_id: `matrix_l3_28d_gemma_structured_json_canary`
- models: `google/gemma-4-12b-qat, google/gemma-4-e2b, google/gemma-4-e4b`
- request_count: `12`
- execution_modes: `cold_per_request`
- cache_modes: `none`
- resource_telemetry_modes: `full`

## Lifecycle summary

- session_count: `12`
- load_scopes: `per_request`
- cleanup_scopes: `per_request`
- final_loaded_instances: `0`
- session_cleanup_verified: `True`
- session_request_indices: `1`
- session_request_counts: `1`

## Warmup/cache summary

- warmup_request_count: `0`
- measured_request_count: `12`
- cache_hit_reported: `unknown`
- kv_reuse_proven: `False`

## Validation summary

- pass_count: `0`
- fail_count: `12`
- hard_fail_count: `12`
- warning_count: `0`
- length_ratio_warning_count: `0`
- pass_rate: `0.0`
- failure_categories: `finish_length=2, language_mismatch=6, schema_error=4`
- warning_categories: `none`
- length_ratio_failures: `count=0; task_ids=none; model_ids=none; min_actual_ratio=None; max_actual_ratio=None; policy_min=[]; policy_max=[]`
- model_status: `google/gemma-4-12b-qat: fail=4; google/gemma-4-e2b: fail=4; google/gemma-4-e4b: fail=4`

## Axis summaries

- per_language: `ru_en_mixed:fail=6,hard_fail=6,warning=0; ru_ru:fail=6,hard_fail=6,warning=0`
- per_complexity: `medium:fail=6,hard_fail=6,warning=0; simple:fail=6,hard_fail=6,warning=0`
- per_volume: `single:fail=12,hard_fail=12,warning=0`
- retry_impact: `off:fail=12,hard_fail=12,warning=0`

## Timing summary

- latency_ms_min: `738.963`
- latency_ms_max: `165209.6`
- total_latency_ms_min: `738.963`
- total_latency_ms_max: `165209.6`

## Privacy summary

- raw_prompt_response_stored: `False`
- raw_base_url_stored: `False`

## Non-claims

- KV-cache reuse is not proven unless LM Studio reports an explicit cache-hit signal.
- RAM/VRAM telemetry is not claimed for timing-only remote-link runs.
- No image, 26B, Qwen, throughput, parallel, overnight, or stress gate is covered by this snapshot.
- A downstream staged model wave is not accepted when this snapshot has failures.

## Next gate

Downstream staged run status: `blocked until fail_count is zero`.
