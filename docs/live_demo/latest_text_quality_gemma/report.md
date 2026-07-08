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

- pass_count: `12`
- fail_count: `4`
- pass_rate: `0.75`
- failure_categories: `too_long=4`
- model_status: `google/gemma-4-e2b: fail=2, pass=6; google/gemma-4-e4b: fail=2, pass=6`

## Timing summary

- latency_ms_min: `679.146`
- latency_ms_max: `1373.167`
- total_latency_ms_min: `679.146`
- total_latency_ms_max: `1373.167`

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
