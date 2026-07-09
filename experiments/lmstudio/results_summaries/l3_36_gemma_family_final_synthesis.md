# L3.36 Gemma Family Final Synthesis

Status: blocked pending phase evidence. This is a scaffold and current admission summary, not the final closure verdict.

No live inference, model load, model download, image request, cache benchmark, stress run, or raw prompt/response artifact was produced for this synthesis scaffold.

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
| `google/gemma-4-12b-qat` | accepted | accepted | accepted | high-quality candidate pending runtime cost/context evidence |
| `google/gemma-4-26b-a4b-qat` | accepted controlled only | blocked/not run | blocked/not run | research/capacity constrained |

Structured JSON is not currently classified as a Gemma weakness after the L3.28d.1 repair and L3.29 72/72 structured pass.

## Current admission matrix summary

| phase | current status | evidence |
|---|---|---|
| L3.31 context windows | `runner_blocked_runtime_unavailable` for live launch; configs/preflight ready | L3.31a preflight passes with 9 planned requests; runtime endpoint unavailable, no applied-context proof yet |
| L3.32 JSON complexity | `prepared_only` / blocked after L3.31a not accepted | L3.32a preflight passes with 4 planned requests; no live complex JSON output yet |
| L3.33 cache/session | `prepared_only` | evidence import, telemetry fields, configs, and report placeholders prepared; no cache/KV proof |
| L3.34 image route | `no_image_route_available` from committed metadata; runtime unavailable | all committed Gemma specs are text-only; no image request sent |
| L3.35 image matrix | `blocked_unsupported_modality` | blocked because L3.34 has not proven an eligible image-capable route |
| L3.36 final model card | `blocked_pending_phase_evidence` | final synthesis needs accepted/blocked evidence from L3.31-L3.35 |

## Open questions still requiring evidence

1. Which higher context windows are safe beyond 8192?
2. Does complex JSON pass for E2B/E4B, then 12B?
3. Do cache/session/warmup strategies improve latency without quality regression?
4. Does the runtime expose explicit cache/KV reuse evidence?
5. Does any Gemma model expose an image-capable route in LM Studio metadata/runtime?
6. If image route exists, which image tasks/schemas are stable?

## Current recommendations by model

| model | current recommendation | blocked modes |
|---|---|---|
| `google/gemma-4-e2b` | accepted lightweight 8192 text/structured simple/blocks candidate | 16k/32k, complex JSON, cache/session, vision pending evidence |
| `google/gemma-4-e4b` | accepted 8192 quality candidate for text/structured simple/blocks | 16k/32k, complex JSON, cache/session, vision pending evidence |
| `google/gemma-4-12b-qat` | accepted 8192 high-quality candidate for text/structured simple/blocks | 16k/32k, complex JSON after E2B/E4B, cache/session, vision pending evidence |
| `google/gemma-4-26b-a4b-qat` | controlled transcript-cleanup research/capacity candidate | broad context, structured JSON, complex JSON, vision pending separate proof |

## Required evidence before final closure

The final L3.36 model card may be marked complete only after:

- L3.31a is accepted or explicitly classified with durable runner/runtime blocker evidence;
- L3.32a is accepted or classified with durable complex-JSON blocker evidence;
- L3.33 has live or intentionally waived cache/session evidence;
- L3.34 has metadata/route evidence and L3.35 is either run or closed as unsupported modality;
- all reports pass publication safety and Git gates;
- raw artifacts are not tracked.
