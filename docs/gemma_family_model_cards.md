# Gemma Family Model Cards

Status: reconciled partial admission after the bounded L3.37 12B reasoning/output-cap diagnostic. Final Gemma family closure is not green.

Timestamp: 2026-07-10T20:19:01+05:00

This document records sanitized aggregate admission status only. It does not publish raw prompt/response artifacts or authorize additional live inference, model load/download, image requests, cache benchmarks, or stress runs.

## Current model cards

| model | load status | max proven context | transcript cleanup | structured simple | structured blocks | structured complex | vision route | cache/session | recommended role |
|---|---|---:|---|---|---|---|---|---|---|
| `google/gemma-4-e2b` | proven in accepted slices | 16384 canary scope | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted narrow for L3.32a E2B/E4B canary | not admitted; no L3.35 eligibility | not run in L3.33a | lightweight baseline |
| `google/gemma-4-e4b` | proven in accepted slices | 16384 canary scope | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted narrow for L3.32a E2B/E4B canary | native plain text accepted for one asset; minimal JSON/broader screening blocked | accepted narrow for `session_loaded` none/warmup_first quality scope; KV reuse not proven | strongest current general candidate |
| `google/gemma-4-12b-qat` | proven in accepted slices | 16384 transcript/simple plus native reasoning-off blocks | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | native reasoning-off accepted narrowly at 8192/16384; native reasoning-on and OpenAI strict route blocked | blocked after one bounded 8192 case | not admitted; no L3.35 eligibility | blocked by L3.33a plus invalid repeated-16k research comparison | route-specific candidate; use only where reasoning can be explicitly disabled and locally validated |
| `google/gemma-4-26b-a4b-qat` | controlled only | 8192 controlled / 16k prepared | accepted controlled only | blocked/not run | blocked/not run | blocked/not run | not admitted; no L3.35 eligibility | not run | research/capacity constrained |

## Current admitted scopes

- Default text/structured scope: 8192 context for E2B, E4B, and 12B on `transcript_cleanup/simple`, `structured_json/simple`, and `structured_json/blocks`.
- 16k canary scope: E2B and E4B passed transcript/simple/blocks; 12B passed transcript/simple on the established route and blocks only on the native reasoning-off diagnostic path.
- Complex JSON scope: E2B and E4B passed the 4-cell L3.32a canary at 8192.
- Cache/session scope: E4B passed the narrow L3.33a `session_loaded` none/warmup_first quality canary, but this is not KV reuse proof.
- 12B blocks diagnostic scope: native `/api/v1/chat` with reasoning explicitly `off` produced schema-valid output at the first 1024-token cap for both 8192 and 16384. This is local schema validation, not strict-route admission.

## Current blocked modes

- 12B `structured_json/blocks` on OpenAI-compatible strict JSON remains blocked. L3.37 native reasoning-off succeeded, but native reasoning-on consumed every cap through 4096 entirely in reasoning and both strict confirmation cells were empty/length-capped at 1024.
- 12B complex JSON: blocked after one bounded adaptive `512 -> 1024` case ended at the truncation ceiling; no broad screening followed.
- 12B cache/session: blocked by two L3.33a finish-length failures and a later repeated-16k comparison with 6/6 invalid length-limited outputs.
- KV reuse/cache benefit: not claimed; timing-only evidence is signal, not proof.
- Vision/image: native E4B plain text is accepted narrowly for one asset, but minimal JSON failed malformed without truncation; L3.35 therefore has zero eligible models and zero attempts.
- 26B structured/cache/vision: not admitted beyond controlled transcript cleanup.
- Qwen: out of Gemma closure scope.

## Next narrow gates

1. Verify an explicit reasoning-off contract on the production structured route, or keep native reasoning-off as an isolated narrow fallback with local schema validation. Do not treat larger output caps as a repair: they did not rescue reasoning-on through 4096.
2. Keep cache/session to `session_loaded`, `parallel=1`, explicit output caps, stable prefixes, and cleanup final zero; do not infer KV reuse from timing.
3. Repair native E4B minimal JSON on the already proven `/api/v1/chat` plain-text route before any L3.35 matrix.

## Non-claims

This document does not claim final family closure, physical KV reuse, cache benefit, structured or broad image support, OpenAI-compatible strict-route repair, 12B complex admission, 26B broad admission, or publication of raw artifacts. L3.37 privately reviewed all 12 raw attempts outside the repository; only sanitized aggregate evidence and public-safe decisions are recorded here.
