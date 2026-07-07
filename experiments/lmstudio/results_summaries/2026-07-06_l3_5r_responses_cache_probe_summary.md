# L3.5r — `/v1/responses` cache probe closure summary

Date: 2026-07-06

## Result

- Status: PASS / candidate.
- Synthetic scope: `2k` and `8k` roots only.
- Requests: `48/48` successful, `0` errors.
- `cached_tokens_available=true`.
- `cached_tokens_observed=true`.
- `previous_response_id_supported=true`.
- Average cache hit ratio: `0.7868497357983353`.
- Average total latency: `1125.2708333340706 ms`.
- `production_default=false`.
- `wvm_runtime_integration=false`.
- `live_25k_authorized=false`.
- `kv_reuse_proven=false`.
- Privacy scan: pass.

## Route interpretation

- `/api/v1/chat`: native instrumentation / latency-proxy lane.
- `/v1/responses`: cache-accounting research lane.
- `/v1/chat/completions`: strict JSON lane.
- `/api/v1/models/*`: lifecycle lane.

## Notes

- `/v1/responses` is retained as a research-only cache-accounting lane and not a production default.
- This slice does not prove physical KV reuse and does not authorize 25k live or host application runtime integration.
- Stored summary content remains privacy-safe and excludes raw prompt/response text, raw response IDs, raw URLs, and filesystem paths.
