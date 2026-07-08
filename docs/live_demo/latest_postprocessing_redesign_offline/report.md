# Latest remote text live report

## Scope

- run_id: `matrix_l3_20_postprocessing_redesign_offline`
- models: `google/gemma-4-e2b, google/gemma-4-e4b`
- request_count: `20`
- execution_modes: `offline_fake`
- cache_modes: `none`
- resource_telemetry_modes: `none`

## Lifecycle summary

- session_count: `0`
- load_scopes: ``
- cleanup_scopes: ``
- final_loaded_instances: ``
- session_cleanup_verified: ``
- session_request_indices: ``
- session_request_counts: ``

## Warmup/cache summary

- warmup_request_count: `0`
- measured_request_count: `20`
- cache_hit_reported: `unknown`
- kv_reuse_proven: `False`

## Validation summary

- pass_count: `20`
- fail_count: `0`
- hard_fail_count: `0`
- warning_count: `0`
- length_ratio_warning_count: `0`
- pass_rate: `1.0`
- failure_categories: `none`
- warning_categories: `none`
- length_ratio_failures: `count=0; task_ids=none; model_ids=none; min_actual_ratio=None; max_actual_ratio=None; policy_min=[]; policy_max=[]`
- model_status: `google/gemma-4-e2b: pass=10; google/gemma-4-e4b: pass=10`

## Axis summaries

- per_language: `en_en:pass=4,warning=0; ru_en_mixed:pass=4,warning=0; ru_ru:pass=12,warning=0`
- per_complexity: `complex:pass=8,warning=0; medium:pass=4,warning=0; simple:pass=8,warning=0`
- per_volume: `many:pass=12,warning=0; single:pass=8,warning=0`
- retry_impact: `off:pass=10,warning=0; retry1:pass=10,warning=0`

## Timing summary

- latency_ms_min: `0.007`
- latency_ms_max: `0.023`
- total_latency_ms_min: `0.007`
- total_latency_ms_max: `0.023`

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
