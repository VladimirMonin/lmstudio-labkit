# Latest remote text live report

## Scope

- run_id: `matrix_l3_21_postprocessing_screening_live`
- models: `google/gemma-4-e2b, google/gemma-4-e4b`
- request_count: `32`
- execution_modes: `cold_per_request`
- cache_modes: `none`
- resource_telemetry_modes: `timing_only`

## Lifecycle summary

- session_count: `32`
- load_scopes: `per_request`
- cleanup_scopes: `per_request`
- final_loaded_instances: `0`
- session_cleanup_verified: `True`
- session_request_indices: `1`
- session_request_counts: `1`

## Warmup/cache summary

- warmup_request_count: `0`
- measured_request_count: `32`
- cache_hit_reported: `unknown`
- kv_reuse_proven: `False`

## Validation summary

- pass_count: `10`
- fail_count: `22`
- hard_fail_count: `22`
- warning_count: `48`
- length_ratio_warning_count: `0`
- pass_rate: `0.3125`
- failure_categories: `id_order_mismatch=10, paragraphing_mismatch=6, term_normalization_mismatch=6`
- warning_categories: `manual_review_required=16, punctuation_metrics=16`
- length_ratio_failures: `count=0; task_ids=none; model_ids=none; min_actual_ratio=None; max_actual_ratio=None; policy_min=[]; policy_max=[]`
- model_status: `google/gemma-4-e2b: fail=10, pass=6; google/gemma-4-e4b: fail=12, pass=4`

## Axis summaries

- per_language: `ru_en_mixed:fail=2,hard_fail=2,pass=6,warning=16; ru_ru:fail=20,hard_fail=20,pass=4,warning=32`
- per_complexity: `medium:fail=14,hard_fail=14,pass=2,warning=24; simple:fail=8,hard_fail=8,pass=8,warning=24`
- per_volume: `many:fail=14,hard_fail=14,pass=2,warning=24; single:fail=8,hard_fail=8,pass=8,warning=24`
- retry_impact: `off:fail=11,hard_fail=11,pass=5,warning=24; retry1:fail=11,hard_fail=11,pass=5,warning=24`

## Timing summary

- latency_ms_min: `645.647`
- latency_ms_max: `1699.079`
- total_latency_ms_min: `645.647`
- total_latency_ms_max: `1699.079`

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
