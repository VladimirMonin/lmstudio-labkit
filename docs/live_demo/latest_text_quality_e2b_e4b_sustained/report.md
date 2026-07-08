# Latest remote text live report

## Scope

- run_id: `matrix_l3_19_sustained_text_quality_e2b_e4b`
- models: `google/gemma-4-e2b, google/gemma-4-e4b`
- request_count: `48`
- execution_modes: `cold_per_request`
- cache_modes: `none`
- resource_telemetry_modes: `timing_only`

## Lifecycle summary

- session_count: `48`
- load_scopes: `per_request`
- cleanup_scopes: `per_request`
- final_loaded_instances: `0`
- session_cleanup_verified: `True`
- session_request_indices: `1`
- session_request_counts: `1`

## Warmup/cache summary

- warmup_request_count: `0`
- measured_request_count: `48`
- cache_hit_reported: `unknown`
- kv_reuse_proven: `False`

## Validation summary

- pass_count: `40`
- fail_count: `8`
- hard_fail_count: `8`
- warning_count: `0`
- length_ratio_warning_count: `0`
- pass_rate: `0.8333`
- failure_categories: `language_mismatch=8`
- warning_categories: `none`
- length_ratio_failures: `count=0; task_ids=none; model_ids=none; min_actual_ratio=None; max_actual_ratio=None; policy_min=[]; policy_max=[]`
- model_status: `google/gemma-4-e2b: fail=4, pass=20; google/gemma-4-e4b: fail=4, pass=20`

## Axis summaries

- per_language: `ru_en_mixed:pass=24,warning=0; ru_ru:fail=8,hard_fail=8,pass=16,warning=0`
- per_complexity: `complex:pass=16,warning=0; medium:pass=16,warning=0; simple:fail=8,hard_fail=8,pass=8,warning=0`
- per_volume: `many:pass=16,warning=0; single:fail=8,hard_fail=8,pass=24,warning=0`
- retry_impact: `off:fail=4,hard_fail=4,pass=20,warning=0; retry1:fail=4,hard_fail=4,pass=20,warning=0`

## Timing summary

- latency_ms_min: `660.556`
- latency_ms_max: `7058.219`
- total_latency_ms_min: `660.556`
- total_latency_ms_max: `7058.219`

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
