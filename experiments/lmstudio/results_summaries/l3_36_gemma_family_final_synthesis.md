# L3.36 Gemma Family Final Synthesis with L3.38 Addendum

Status: reconciled through the bounded L3.38 reasoning-off follow-up. Gemma is not fully closed as a green model family.

Timestamp: 2026-07-10T18:35:36+05:00

This synthesis uses sanitized reports only. It does not add live inference, model load, model download, image request, cache benchmark, stress run, or raw prompt/response artifacts.

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
| L3.31 context windows | `partial_not_accepted` | L3.31a executed 9 cells: E2B/E4B all passed; 12B transcript/simple passed; 12B blocks@16k failed. The single durable capped repair also failed at `finish_reason=length`, `completion_tokens=1024`; this is model-output evidence, not a recorder gap. |
| L3.32 JSON complexity | `accepted_narrow` plus blocked 12B | L3.32a executed 4/4 pass for E2B/E4B complex JSON at 8192. One bounded 12B case escalated `512 -> 1024` and failed at the truncation ceiling. 26B complex and broad screening were not run. |
| L3.33 cache/session | `partial_not_accepted` | L3.33a accepted E4B narrowly and blocked 12B. A focused 12B repeated-16k comparison showed timing improvements but 6/6 invalid length-limited outputs and no reported cached-token accounting. KV reuse and cache benefit remain unproven. |
| L3.34 image route | `partial_route_only` | Compat PNG data URI payloads reached the API but failed structured output. Native E4B `/api/v1/chat` then produced non-empty plain text for one asset; minimal JSON failed malformed without truncation. |
| L3.35 image matrix | `blocked` | The tiny screening gate was correctly skipped after native minimal JSON failed. Image screening attempt count remains 0. |
| L3.36 final model card | `partial_not_green` | Admission can be updated with accepted/blocked evidence, but final family-wide closure is not green. |

## Remaining evidence questions

1. Can 12B structured blocks at 16k return valid output under a bounded strategy after the durable 1024-token capped failure?
2. Can 12B complex JSON return valid output after the bounded `512 -> 1024` failure without widening scope?
3. Can 12B cache/session finish-length failures be repaired without weakening session-loaded cleanup guarantees?
4. Does the runtime expose explicit cache/KV reuse evidence beyond timing-only telemetry?
5. Can the proven native E4B plain-text image route produce valid minimal JSON without malformed output?
6. If minimal JSON passes, which tiny simple-description contracts are stable before L3.35?

## Current recommendations by model

| model | current recommendation | blocked modes |
|---|---|---|
| `google/gemma-4-e2b` | accepted lightweight 8192 text/structured simple/blocks candidate; accepted for the L3.31a 16k canary scope; accepted for L3.32a complex JSON canary | cache/session not run; vision not run after the E4B native minimal-JSON gate failed; 32k not admitted |
| `google/gemma-4-e4b` | strongest current candidate: accepted 8192, L3.31a 16k canary, L3.32a complex JSON, narrow L3.33a session-loaded quality scope, and one-asset native image plain text | KV reuse not proven; native minimal JSON and broader vision blocked; 32k not admitted |
| `google/gemma-4-12b-qat` | accepted 8192 text/structured simple/blocks and 16k transcript/simple only | durable 16k blocks repair, bounded 8192 complex, and repeated-16k cache/session outputs all failed; vision and 32k not admitted |
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
  12b_latest_evidence: bounded_failure_at_1024_token_ceiling
cache_session:
  accepted_narrow:
    - google/gemma-4-e4b session_loaded none/warmup_first quality scope
  blocked:
    - google/gemma-4-12b-qat finish_length hard failures
  kv_reuse_proven: false
  cache_benefit_claimed: false
vision:
  l3_35_eligible_models: []
  native_plain_text_accepted_narrow:
    - google/gemma-4-e4b one-asset gate
  blocked_reason: native minimal JSON failed malformed without truncation
```

## L3.38 affected model cards

The canonical L3.38 evidence pack is
[L3.38 reasoning-off follow-up](l3_38_reasoning_off_followup/report.md).

| model | L3.38 evidence | current recommendation |
|---|---|---|
| `google/gemma-4-e2b` | unchanged | retain the accepted lightweight text/JSON role; no L3.38 cache or vision claim |
| `google/gemma-4-e4b` | native text-only minimal JSON passed; image transport succeeded; the image JSON grounded the verified fixture incorrectly | keep text and transport acceptance narrow; block structured vision; use reasoning off only for bounded native diagnostics, not as a global quality remedy |
| `google/gemma-4-12b-qat` | native reasoning-off repeated-context comparison completed, but 0/6 outputs passed the strict local JSON contract; strict-route confirmation stayed at zero requests | keep timing evidence research-only; native reasoning off is necessary for bounded visible output on diagnosed tasks but is not sufficient for session/cache contract validity; strict-route reasoning remains undetermined |
| `google/gemma-4-26b-a4b-qat` | native blocks JSON passed 4/4 across 8192/16384 and reasoning off/on | accept only the paired native canary scope; prefer reasoning off for this exact bounded task because the visible answer stayed valid with substantially lower reasoning overhead |

Family closure remains `partial_not_green`. The L3.38 evidence does not broaden
the default 8192 product scope, admit E4B structured vision, admit 12B
session/cache, establish OpenAI-compatible reasoning control, or prove physical
KV reuse.

## Non-claims

- This synthesis does not claim final green Gemma-family closure.
- It does not claim 12B 16k blocks, 12B complex JSON, 12B cache/session, 26B structured, or structured/broad Gemma vision as accepted.
- It does not claim physical KV reuse or cache benefit from timing-only/session-loaded evidence.
- It does not commit or summarize raw prompts, raw responses, raw image bytes, private endpoint URLs, or private source-application details.
