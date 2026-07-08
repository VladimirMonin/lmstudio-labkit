# Latest remote text live report

## Scope

- run_id: `matrix_l3_22_focused_simple_postprocessing_live`
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

- pass_count: `32`
- fail_count: `0`
- hard_fail_count: `0`
- warning_count: `48`
- length_ratio_warning_count: `0`
- pass_rate: `1.0`
- failure_categories: `none`
- warning_categories: `manual_review_required=16, punctuation_metrics=16`
- length_ratio_failures: `count=0; task_ids=none; model_ids=none; min_actual_ratio=None; max_actual_ratio=None; policy_min=[]; policy_max=[]`
- model_status: `google/gemma-4-e2b: pass=16; google/gemma-4-e4b: pass=16`

## Axis summaries

- per_language: `ru_en_mixed:pass=16,warning=24; ru_ru:pass=16,warning=24`
- per_complexity: `simple:pass=32,warning=48`
- per_volume: `single:pass=32,warning=48`
- retry_impact: `off:pass=16,warning=24; retry1:pass=16,warning=24`

## Timing summary

- latency_ms_min: `642.748`
- latency_ms_max: `984.493`
- total_latency_ms_min: `642.748`
- total_latency_ms_max: `984.493`

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
