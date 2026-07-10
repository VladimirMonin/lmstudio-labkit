# L3.36 Gemma Family Final Synthesis

Status: partial final synthesis after L3.31-L3.35 evidence. Gemma is not fully closed as a green model family; the accepted scope is text/structured at 8192 plus selected canaries below.

Timestamp: 2026-07-10T11:13:04+05:00

This synthesis uses committed sanitized reports only. It does not add live inference, model load, model download, image request, cache benchmark, stress run, or raw prompt/response artifacts.

## Current accepted evidence

L3.29 accepted the executable 8192 slice:

```yaml
executed_attempt_count: 113
pass_count: 113
fail_count: 0
hard_fail_count: 0
privacy_scan_status: pass
final_loaded_like_count: 0
```

Accepted at 8192:

| model | transcript cleanup/simple | structured JSON/simple | structured JSON/blocks | current role |
|---|---:|---:|---:|---|
| `google/gemma-4-e2b` | accepted | accepted | accepted | lightweight baseline |
| `google/gemma-4-e4b` | accepted | accepted | accepted | quality candidate |
| `google/gemma-4-12b-qat` | accepted | accepted | accepted | high-quality candidate pending repair evidence |
| `google/gemma-4-26b-a4b-qat` | accepted controlled only | blocked/not run | blocked/not run | research/capacity constrained |

Structured JSON is not currently classified as a Gemma weakness after the L3.28d.1 repair and L3.29 72/72 structured pass.

## Current admission matrix summary

| phase | current status | evidence |
|---|---|---|
| L3.31 context windows | `partial_not_accepted` | L3.31a executed 9 cells: E2B/E4B all passed; 12B transcript/simple passed; 12B blocks@16k failed with `finish_reason=length` and empty extracted content. The optional 12B max-token repair probe is inconclusive because recorder persistence failed after inference. |
| L3.32 JSON complexity | `accepted_narrow` | L3.32a executed 4/4 pass for E2B/E4B complex JSON at 8192 after owner override to continue probes despite red L3.31a. 12B/26B complex remain not admitted. |
| L3.33 cache/session | `partial_not_accepted` | Source-application evidence import is complete. L3.33a second attempt executed 24 cells: E4B accepted narrowly for `session_loaded` none/warmup_first; 12B had 2 finish-length hard failures. KV reuse is not proven and cache benefit is not claimed. |
| L3.34 image route | `blocked` | PNG data URI image payloads reached HTTP/API acceptance, but structured route probe failed for all Gemma models with `finish_reason=length`; the narrower E4B plain-text repair probe also returned empty output at explicit `max_tokens=256`. |
| L3.35 image matrix | `blocked` | No model is eligible because L3.34/L3.34.1 produced no non-empty plain-text or JSON/schema-pass image route. Image screening attempt count remains 0. |
| L3.36 final model card | `partial_not_green` | Admission can be updated with accepted/blocked evidence, but final family-wide closure is not green. |

## Remaining evidence questions

1. Can 12B structured blocks at 16k pass after the explicit `max_tokens` repair, with durable recorder output?
2. Does 12B complex JSON pass after the E2B/E4B L3.32a green canary?
3. Can 12B cache/session finish-length failures be repaired without weakening session-loaded cleanup guarantees?
4. Does the runtime expose explicit cache/KV reuse evidence beyond timing-only telemetry?
5. Does native `/api/v1/chat` image input with `data_url` and `output[]` extraction produce non-empty text for Gemma?
6. If the native image route passes plain text, which minimal JSON/simple-description image contracts are stable?

## Current recommendations by model

| model | current recommendation | blocked modes |
|---|---|---|
| `google/gemma-4-e2b` | accepted lightweight 8192 text/structured simple/blocks candidate; accepted for the L3.31a 16k canary scope; accepted for L3.32a complex JSON canary | cache/session not run; vision not eligible until a route passes; 32k not admitted |
| `google/gemma-4-e4b` | strongest current candidate: accepted 8192, accepted L3.31a 16k canary scope, accepted L3.32a complex JSON canary, accepted narrow L3.33a session-loaded cache/warmup quality scope | KV reuse not proven; vision blocked by empty output; 32k not admitted |
| `google/gemma-4-12b-qat` | accepted 8192 text/structured simple/blocks and 16k transcript/simple only | 16k blocks, L3.33a cache/session, 12B complex, and vision remain blocked or not admitted pending explicit max-token/recorder-safe evidence |
| `google/gemma-4-26b-a4b-qat` | controlled transcript-cleanup research/capacity candidate only | broad context, structured JSON, complex JSON, cache/session, and vision remain not admitted |

## Final admission decision

```yaml
gemma_family_closure: partial_not_green
safe_default_context: 8192
accepted_default_scope:
  models:
    - google/gemma-4-e2b
    - google/gemma-4-e4b
    - google/gemma-4-12b-qat
  tasks:
    - transcript_cleanup/simple
    - structured_json/simple
    - structured_json/blocks
  context_tier: 8192
best_current_general_candidate: google/gemma-4-e4b
16k:
  accepted:
    - google/gemma-4-e2b L3.31a canary scope
    - google/gemma-4-e4b L3.31a canary scope
    - google/gemma-4-12b-qat transcript_cleanup/simple
    - google/gemma-4-12b-qat structured_json/simple
  blocked:
    - google/gemma-4-12b-qat structured_json/blocks
structured_complex:
  accepted_narrow:
    - google/gemma-4-e2b
    - google/gemma-4-e4b
  not_admitted:
    - google/gemma-4-12b-qat
    - google/gemma-4-26b-a4b-qat
cache_session:
  accepted_narrow:
    - google/gemma-4-e4b session_loaded none/warmup_first quality scope
  blocked:
    - google/gemma-4-12b-qat finish_length hard failures
  kv_reuse_proven: false
  cache_benefit_claimed: false
vision:
  l3_35_eligible_models: []
  blocked_reason: no non-empty plain-text or JSON/schema-pass image route evidence
```

## Non-claims

- This synthesis does not claim final green Gemma-family closure.
- It does not claim 12B 16k blocks, 12B complex JSON, 12B cache/session, 26B structured, or any Gemma image mode as accepted.
- It does not claim physical KV reuse or cache benefit from timing-only/session-loaded evidence.
- It does not commit or summarize raw prompts, raw responses, raw image bytes, private endpoint URLs, or private source-application details.
