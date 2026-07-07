# L3.5r — `/v1/responses` 16k cache probe summary

Date: 2026-07-06

## Result

- Status: `responses_blocked_internal_error`.
- Run id: `l3_5r_16k_responses_probe_20260706_senior`.
- Synthetic scope: `16k` root only.
- Requests: `0/24` successful, `24` errors.
- Main error class: `internal_error` for submitted 16k requests.
- Failure coverage: root_branch, repeated_prefix, and mutated_prefix all remained blocked under the same 16k `internal_error` outcome.
- `cached_tokens_available=false`.
- `cached_tokens_observed=false`.
- `previous_response_id_supported=false`.
- `production_default=false`.
- `wvm_runtime_integration=false`.
- `live_25k_authorized=false`.
- `kv_reuse_proven=false`.
- Privacy scan: pass.

## Interpretation

- `/v1/responses` remains a useful 2k/8k cache-accounting candidate, but the 16k synthetic probe is blocked in this live run.
- This result does not invalidate the earlier 2k/8k `responses_cache_accounting_candidate` result.
- This result blocks any escalation toward 25k live through `/v1/responses` until the 16k failure mode is understood.
- The failure pattern points to 16k payload / Responses endpoint behavior on the current build, not only to `previous_response_id` support.
- No production WVM runtime, QueueManager, UI, or 25k live generation step is authorized.

## Route interpretation

- `/api/v1/chat`: native instrumentation / latency-proxy lane.
- `/v1/responses`: small-context cache-accounting research lane; 2k/8k candidate, 16k/25k currently blocked.
- `/v1/chat/completions`: strict JSON lane.
- `/api/v1/models/*`: lifecycle lane.

## Next safe follow-up

- Analyze the 16k `internal_error` without storing raw provider bodies.
- Consider a smaller intermediate synthetic gate before 16k, or an L3.6 no-live tokenized prompt/mode audit, before any 25k discussion.
- Keep `production_default=false`, `wvm_runtime_integration=false`, `live_25k_authorized=false`, and `kv_reuse_proven=false`.
