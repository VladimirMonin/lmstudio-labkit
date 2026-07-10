# Gemma Family Model Cards

Status: reconciled partial admission after all bounded closure lanes. Final Gemma family closure is not green.

Timestamp: 2026-07-10T18:35:36+05:00

This document records sanitized aggregate admission status only. It does not add live inference, model load, model download, image request, cache benchmark, stress run, or raw prompt/response artifacts.

## Current model cards

| model | load status | max proven context | transcript cleanup | structured simple | structured blocks | structured complex | vision route | cache/session | recommended role |
|---|---|---:|---|---|---|---|---|---|---|
| `google/gemma-4-e2b` | proven in accepted slices | 16384 canary scope | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted narrow for L3.32a E2B/E4B canary | not admitted; no L3.35 eligibility | not run in L3.33a | lightweight baseline |
| `google/gemma-4-e4b` | proven in accepted slices | 16384 canary scope | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted narrow for L3.32a E2B/E4B canary | native plain text accepted for one asset; minimal JSON/broader screening blocked | accepted narrow for `session_loaded` none/warmup_first quality scope; KV reuse not proven | strongest current general candidate |
| `google/gemma-4-12b-qat` | proven in accepted slices | 16384 transcript/simple only | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted at 8192; blocked at 16k blocks after capped repair | blocked after one bounded 8192 case | not admitted; no L3.35 eligibility | blocked by L3.33a plus invalid repeated-16k research comparison | high-quality candidate requiring output-validity repair evidence |
| `google/gemma-4-26b-a4b-qat` | controlled only | 8192 controlled / 16k prepared | accepted controlled only | blocked/not run | blocked/not run | blocked/not run | not admitted; no L3.35 eligibility | not run | research/capacity constrained |

## Current admitted scopes

- Default text/structured scope: 8192 context for E2B, E4B, and 12B on `transcript_cleanup/simple`, `structured_json/simple`, and `structured_json/blocks`.
- 16k canary scope: E2B and E4B passed transcript/simple/blocks; 12B passed transcript/simple but failed blocks.
- Complex JSON scope: E2B and E4B passed the 4-cell L3.32a canary at 8192.
- Cache/session scope: E4B passed the narrow L3.33a `session_loaded` none/warmup_first quality canary, but this is not KV reuse proof.

## Current blocked modes

- 12B `structured_json/blocks` at 16k: blocked by the original failure and one durable 1024-token capped repair that also ended at `finish_reason=length`.
- 12B complex JSON: blocked after one bounded adaptive `512 -> 1024` case ended at the truncation ceiling; no broad screening followed.
- 12B cache/session: blocked by two L3.33a finish-length failures and a later repeated-16k comparison with 6/6 invalid length-limited outputs.
- KV reuse/cache benefit: not claimed; timing-only evidence is signal, not proof.
- Vision/image: native E4B plain text is accepted narrowly for one asset, but minimal JSON failed malformed without truncation; L3.35 therefore has zero eligible models and zero attempts.
- 26B structured/cache/vision: not admitted beyond controlled transcript cleanup.
- Qwen: out of Gemma closure scope.

## Next narrow gates

1. Redesign one-variable 12B output-validity canaries without widening the failed 1024-token blocks/complex bounds.
2. Keep cache/session to `session_loaded`, `parallel=1`, explicit output caps, stable prefixes, and cleanup final zero; do not infer KV reuse from timing.
3. Repair native E4B minimal JSON on the already proven `/api/v1/chat` plain-text route before any L3.35 matrix.

## Non-claims

This document does not claim final family closure, physical KV reuse, cache benefit, structured or broad image support, 12B 16k blocks repair, 12B complex admission, 26B broad admission, or any raw artifact review. It records only sanitized aggregate evidence and public-safe decisions.
