# L3 Endpoint Policy Decision Record

Date: 2026-07-06

## Status

Accepted for the current LM Studio Lab L3/L3.5b/L3.5r slice.

## Endpoint policy

| Endpoint family | Role now | Policy |
| --- | --- | --- |
| `/api/v1/chat` | native L3 instrumentation route | native stateful instrumentation, `prompt_processing`, TTFT, latency proxy, L3 research |
| `/v1/responses` | small-context cache-accounting research lane | small-context cache-accounting candidate, blocked for 16k/25k long-context on current build |
| `/v1/chat/completions` | strict structured output path | strict JSON Schema / factual blocks |
| `/api/v1/models/load`, `/api/v1/models`, `/api/v1/models/unload` | lifecycle path | lifecycle, 32k load-only smoke |

## Required interpretation rules

- Native /api/v1/chat stateful branches prove server-side conversation state, not physical KV reuse.
- Prompt-processing reduction is a latency proxy, not KV proof.
- KV reuse may only be marked proven when direct cache-hit telemetry is present, such as cached_tokens or equivalent runtime signal.
- For current L3, /v1/responses is an isolated small-context cache-accounting research lane and not the native L3 default.

## 2026-07-06 live evidence update

### L3.5b 32k load-only smoke

Result: PASS.

- Run id: `l3_5b_32k_load_only_20260706_senior`.
- Model: `google/gemma-4-e2b` (`gemma4_e2b_q4km`).
- Requested/applied context length: `32768` / `32768`.
- Endpoint family: `model_lifecycle`.
- Endpoint sequence: `GET /api/v1/models` -> `POST /api/v1/models/load` -> `GET /api/v1/models` -> `POST /api/v1/models/unload` -> `GET /api/v1/models`.
- Inference endpoints called: `false`.
- Cleanup verified: `true`.
- Final owned instances: `0`.
- Privacy scan: `pass`.

Interpretation: 32k lifecycle ownership is green for this model/profile. This does not authorize 25k live generation and does not prove generation quality, structured output correctness, or KV reuse.

### L3.5r /v1/responses cache-accounting probe

Result: PASS / candidate.

- Run id: `l3_5r_responses_probe_20260706_senior`.
- Endpoint family/path: `openai_responses` / `/v1/responses`.
- Model: `google/gemma-4-e2b` (`gemma4_e2b_q4km`).
- Scope: synthetic `2k`/`8k` roots only, no real user content.
- Request count: `48`.
- Success/error count: `48` / `0`.
- `cached_tokens_available`: `true`.
- `cached_tokens_observed`: `true`.
- `previous_response_id_supported`: `true`.
- Average cache hit ratio: `0.7868497357983353`.
- Average total latency: `1125.2708333340706 ms`.
- Probe status: `responses_cache_accounting_candidate`.
- `production_default`: `false`.
- `wvm_runtime_integration`: `false`.
- `kv_reuse_proven`: `false`.
- Privacy scan: `pass`.

Interpretation: `/v1/responses` is promoted from a speculative future idea to an official cache-accounting research lane. It remains isolated from production host application runtime and does not replace native `/api/v1/chat` L3 instrumentation.

### L3.5r 16k /v1/responses probe

Result: BLOCKED.

- Run id: `l3_5r_16k_responses_probe_20260706_senior`.
- Endpoint family/path: `openai_responses` / `/v1/responses`.
- Model: `google/gemma-4-e2b` (`gemma4_e2b_q4km`).
- Scope: synthetic `16k` root only, no real user content.
- Request count: `24`.
- Success/error count: `0` / `24`.
- Main error class: `internal_error` for submitted 16k requests.
- `cached_tokens_available`: `false`.
- `cached_tokens_observed`: `false`.
- `previous_response_id_supported`: `false`.
- Probe status: `responses_blocked_internal_error`.
- `production_default`: `false`.
- `wvm_runtime_integration`: `false`.
- `kv_reuse_proven`: `false`.
- Privacy scan: `pass`.

Interpretation: the 2k/8k `/v1/responses` cache-accounting candidate remains valid, but the 16k live synthetic probe is blocked and does not authorize any 25k live escalation. The same `internal_error` failure affected root_branch, repeated_prefix, and mutated_prefix variants, so the current blocker is most likely 16k payload / Responses endpoint behavior on this build, not only `previous_response_id` handling.

## Current routing after L3.5b/L3.5r

| Route / strategy | Current status |
| --- | --- |
| `compact_memory_primary` | Practical primary candidate |
| `/api/v1/chat` stateful | Native L3 instrumentation / latency-proxy lane |
| `/v1/responses` | Small-context cache-accounting lane; blocked for 16k/25k long-context |
| `/v1/chat/completions` | Strict JSON / factual-blocks lane |
| `/api/v1/models/*` | Lifecycle ownership lane |
| 25k live generation | Still blocked |
| Production host application integration | Still blocked |
| Qwen strict JSON | Still blocked / recovery only |
| Vision | Out of scope |

## Status matrix

| Item | Status |
| --- | --- |
| L3.5b 32k load-only | `passed` |
| L3.5r responses 2k/8k | `cache_accounting_candidate` |
| L3.5r responses 16k | `responses_blocked_internal_error` |
| L3.6 25k no-live preflight | `pending_artifact_generation` |
| L3.6 25k live | `blocked` |
| host application runtime integration | `blocked` |
| Qwen strict JSON | `blocked/recovery_only` |
| Vision | `out_of_scope` |

## Next allowed gates

- Analyze 16k synthetic `/v1/responses` `internal_error` without storing raw provider bodies.
- Optional smaller intermediate synthetic `/v1/responses` gate before retrying 16k.
- Optional per-mode `/v1/responses` latency/cache-accounting breakdown from `metrics.jsonl`.
- Generate and review the L3.6 no-live preflight artifacts before any further 25k discussion.

Not authorized by this record:

- 25k live generation.
- Production default switch to `/v1/responses`.
- host application runtime/QueueManager integration.
- Qwen strict JSON default restoration.
- Claiming physical KV reuse as proven.

## Notes

- `/api/v1/chat` remains the native L3 instrumentation path because it exposes stateful branch behavior, TTFT, and `prompt_processing.*` instrumentation.
- `/v1/chat/completions` remains the strict factual-blocks / JSON-schema path for structured-output lab work.
- `/api/v1/models/load` + `/api/v1/models` + `/api/v1/models/unload` own the L3.5b 32k load-only smoke because that slice must prove load echo and cleanup only, without generation.
- `/v1/responses` remains a small-context cache-accounting candidate only; it must not be promoted as the L3.6 25k route while 16k stays blocked.
- `compact_memory` remains the stable/default candidate; native stateful remains experimental.
