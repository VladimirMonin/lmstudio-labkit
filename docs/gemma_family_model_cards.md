# Gemma Family Model Cards

Status: partial admission update after L3.31-L3.35 evidence. Final Gemma family closure is not green.

Timestamp: 2026-07-10T11:13:04+05:00

This document records sanitized aggregate admission status only. It does not add live inference, model load, model download, image request, cache benchmark, stress run, or raw prompt/response artifacts.

## Current model cards

| model | load status | max proven context | transcript cleanup | structured simple | structured blocks | structured complex | vision route | cache/session | recommended role |
|---|---|---:|---|---|---|---|---|---|---|
| `google/gemma-4-e2b` | proven in accepted slices | 16384 canary scope | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted narrow for L3.32a E2B/E4B canary | not admitted; no L3.35 eligibility | not run in L3.33a | lightweight baseline |
| `google/gemma-4-e4b` | proven in accepted slices | 16384 canary scope | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted narrow for L3.32a E2B/E4B canary | blocked after empty image output at explicit cap | accepted narrow for `session_loaded` none/warmup_first quality scope; KV reuse not proven | strongest current general candidate |
| `google/gemma-4-12b-qat` | proven in accepted slices | 16384 transcript/simple only | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted at 8192; blocked at 16k blocks | not admitted | not admitted; no L3.35 eligibility | blocked by 2 finish-length hard failures in L3.33a | high-quality candidate requiring repair evidence |
| `google/gemma-4-26b-a4b-qat` | controlled only | 8192 controlled / 16k prepared | accepted controlled only | blocked/not run | blocked/not run | blocked/not run | not admitted; no L3.35 eligibility | not run | research/capacity constrained |

## Current admitted scopes

- Default text/structured scope: 8192 context for E2B, E4B, and 12B on `transcript_cleanup/simple`, `structured_json/simple`, and `structured_json/blocks`.
- 16k canary scope: E2B and E4B passed transcript/simple/blocks; 12B passed transcript/simple but failed blocks.
- Complex JSON scope: E2B and E4B passed the 4-cell L3.32a canary at 8192.
- Cache/session scope: E4B passed the narrow L3.33a `session_loaded` none/warmup_first quality canary, but this is not KV reuse proof.

## Current blocked modes

- 12B `structured_json/blocks` at 16k: blocked by `finish_reason=length` with empty extracted content; the one optional capped repair probe is inconclusive because recorder persistence failed after inference.
- 12B complex JSON: not admitted; gated after the E2B/E4B L3.32a green result and 12B max-token/recorder repair.
- 12B cache/session: blocked by two finish-length hard failures across 12 L3.33a attempts.
- KV reuse/cache benefit: not claimed; timing-only evidence is signal, not proof.
- Vision/image: blocked. PNG data URI payload reached HTTP/API acceptance, but Gemma produced no parseable/non-empty accepted route output; L3.35 has zero eligible models and zero attempts.
- 26B structured/cache/vision: not admitted beyond controlled transcript cleanup.
- Qwen: out of Gemma closure scope.

## Next narrow gates

1. Re-run the 12B 16k blocks repair only after explicit `max_tokens` forwarding and recorder-safe persistence are in place.
2. Test 12B complex JSON only after the repair gate or an explicit owner decision to isolate complex JSON separately.
3. Keep cache/session to `session_loaded`, `parallel=1`, explicit output caps, stable prefixes, and cleanup final zero; do not mix it with broad context, image, or throughput work.
4. For image, test the native `/api/v1/chat` route with `input[].type=image`, `data_url`, `max_output_tokens`, and `output[]` extraction before any L3.35 matrix.

## Non-claims

This document does not claim final family closure, physical KV reuse, cache benefit, accepted image support, 12B 16k blocks repair, 12B complex admission, 26B broad admission, or any raw artifact review. It records only sanitized aggregate evidence and public-safe decisions.
