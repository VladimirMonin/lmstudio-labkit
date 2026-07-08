# Latest remote text live report

## Scope

- run_id: `matrix_l3_22_simple_postprocessing_product_like_e2b_e4b`
- models: `google/gemma-4-e2b, google/gemma-4-e4b`
- request_count: `80`
- execution_modes: `cold_per_request`
- cache_modes: `none`
- resource_telemetry_modes: `timing_only`

## Lifecycle summary

- session_count: `80`
- load_scopes: `per_request`
- cleanup_scopes: `per_request`
- final_loaded_instances: `0`
- session_cleanup_verified: `True`
- session_request_indices: `1`
- session_request_counts: `1`

## Warmup/cache summary

- warmup_request_count: `0`
- measured_request_count: `80`
- cache_hit_reported: `unknown`
- kv_reuse_proven: `False`

## Validation summary

- pass_count: `80`
- fail_count: `0`
- hard_fail_count: `0`
- warning_count: `120`
- length_ratio_warning_count: `0`
- pass_rate: `1.0`
- failure_categories: `none`
- warning_categories: `manual_review_required=40, punctuation_metrics=40`
- length_ratio_failures: `count=0; task_ids=none; model_ids=none; min_actual_ratio=None; max_actual_ratio=None; policy_min=[]; policy_max=[]`
- model_status: `google/gemma-4-e2b: pass=40; google/gemma-4-e4b: pass=40`

## Axis summaries

- per_language: `ru_en_mixed:pass=20,warning=20; ru_ru:pass=60,warning=100`
- per_complexity: `simple:pass=80,warning=120`
- per_volume: `single:pass=80,warning=120`
- retry_impact: `off:pass=40,warning=60; retry1:pass=40,warning=60`

## Timing summary

- latency_ms_min: `641.314`
- latency_ms_max: `962.51`
- total_latency_ms_min: `641.314`
- total_latency_ms_max: `962.51`

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
