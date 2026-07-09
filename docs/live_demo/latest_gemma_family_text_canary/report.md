# Latest remote text live report

## Scope

- run_id: `matrix_l3_28c1_gemma_transcript_cleanup_canary_e2b_e4b_12b`
- models: `google/gemma-4-12b-qat, google/gemma-4-e2b, google/gemma-4-e4b`
- request_count: `15`
- execution_modes: `cold_per_request`
- cache_modes: `none`
- resource_telemetry_modes: `full`

## Lifecycle summary

- session_count: `15`
- load_scopes: `per_request`
- cleanup_scopes: `per_request`
- final_loaded_instances: `0`
- session_cleanup_verified: `True`
- session_request_indices: `1`
- session_request_counts: `1`

## Warmup/cache summary

- warmup_request_count: `0`
- measured_request_count: `15`
- cache_hit_reported: `unknown`
- kv_reuse_proven: `False`

## Validation summary

- pass_count: `15`
- fail_count: `0`
- hard_fail_count: `0`
- warning_count: `30`
- length_ratio_warning_count: `0`
- pass_rate: `1.0`
- failure_categories: `none`
- warning_categories: `punctuation_metrics=15`
- length_ratio_failures: `count=0; task_ids=none; model_ids=none; min_actual_ratio=None; max_actual_ratio=None; policy_min=[]; policy_max=[]`
- model_status: `google/gemma-4-12b-qat: pass=5; google/gemma-4-e2b: pass=5; google/gemma-4-e4b: pass=5`

## Axis summaries

- per_language: `ru_en_mixed:pass=3,warning=6; ru_ru:pass=12,warning=24`
- per_complexity: `simple:pass=15,warning=30`
- per_volume: `single:pass=15,warning=30`
- retry_impact: `off:pass=15,warning=30`

## Timing summary

- latency_ms_min: `838.488`
- latency_ms_max: `2847.462`
- total_latency_ms_min: `838.488`
- total_latency_ms_max: `2847.462`

## Privacy summary

- raw_prompt_response_stored: `False`
- raw_base_url_stored: `False`

## Non-claims

- KV-cache reuse is not proven unless LM Studio reports an explicit cache-hit signal.
- RAM/VRAM telemetry is not claimed for timing-only remote-link runs.
- No image, 26B, Qwen, throughput, parallel, overnight, or stress gate is covered by this snapshot.
- A downstream staged model wave is not accepted when this snapshot has failures.

## Next gate

Downstream staged run status: `open for the next explicitly scoped staged run`.
