# L3.16.1 latest live session warmup report

## Scope

- run_id: `matrix_live_small_text_remote_warmup_e2b_e4b`
- models: `google/gemma-4-e2b, google/gemma-4-e4b`
- request_count: `6`
- execution_modes: `session_loaded`
- cache_modes: `warmup_first`
- resource_telemetry_modes: `timing_only`

## Session lifecycle proof

- session_count: `not exported`
- load_scopes: `not exported`
- cleanup_scopes: `not exported`
- final_loaded_instances: `not exported`
- session_cleanup_verified: `not exported`

Expected L3.16.1 shape on newly exported runs: two model sessions, each loaded once, three requests, cleanup once, final loaded instances zero.

## Warmup/measured split

- warmup_request_count: `not exported`
- measured_request_count: `not exported`
- cache_hit_reported: `not exported`
- kv_reuse_proven: `not exported`

## Validation summary

- pass_count: `6`
- fail_count: `0`
- pass_rate: `1.0`

## Timing summary

- latency_ms_min: `2537.202`
- latency_ms_max: `4128.283`
- total_latency_ms_min: `2537.202`
- total_latency_ms_max: `4128.283`

## Privacy summary

- raw_prompt_response_stored: `False`
- raw_base_url_stored: `False`

## Non-claims

- KV-cache reuse is not proven unless LM Studio reports an explicit cache-hit signal.
- RAM/VRAM telemetry is not claimed for timing-only remote-link runs.
- No image, 12B, 26B, Qwen, throughput, parallel, overnight, or stress gate is covered by this snapshot.

## Next allowed gate

L3.17 small text quality screening only after L3.16.1 gates remain green.
