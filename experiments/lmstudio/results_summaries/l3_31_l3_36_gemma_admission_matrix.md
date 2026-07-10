# L3.31-L3.36 Gemma Admission Matrix

Status: updated after L3.31b forensics, L3.33b source application cache evidence import, and L3.34.1 vision repair probe.

Timestamp: 2026-07-10T10:27:39+05:00

Legend:

- `accepted` — passed in the stated narrow evidence scope.
- `blocked` — executed/probed and failed, or gated by prior failed phase.
- `not_run` — not executed in this series/scope.
- `partial` — some cells accepted, some blocked.
- `research_only` — architecture/evidence imported, not direct model acceptance.
- `unsupported_or_unusable` — route/API may exist, but current runtime shape is not usable for admission.

## Matrix

| model | 8192_transcript_cleanup | 8192_structured_simple | 8192_structured_blocks | 8192_complex | 16k_transcript_cleanup | 16k_structured_simple | 16k_structured_blocks | cache_session | vision_plain | vision_min_json | vision_simple_description | status | blocked_reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `google/gemma-4-e2b` | accepted | accepted | accepted | accepted | accepted | accepted | accepted | not_run | not_run | not_run | not_run | accepted_text_json_only | vision not eligible because E4B Phase 1 failed before other models; cache not run for E2B |
| `google/gemma-4-e4b` | accepted | accepted | accepted | accepted | accepted | accepted | accepted | accepted_narrow | blocked | blocked | blocked | partial | vision plain text failed with `finish_reason=length` at explicit `max_tokens=256`; no KV reuse proof for cache despite cache_session quality pass |
| `google/gemma-4-12b-qat` | accepted | accepted | accepted | not_run | accepted | accepted | blocked | blocked | not_run | not_run | not_run | partial_blocked | 16k blocks failed with `finish_reason=length` after 16261 completion tokens and empty content; L3.33a cache/session had 2 finish_length hard failures; complex 8192 not run in L3.32a |
| `google/gemma-4-26b-a4b-qat` | accepted_controlled_transcript_only | not_run | not_run | not_run | not_run | not_run | not_run | not_run | not_run | not_run | not_run | research_only_limited | only controlled transcript baseline evidence from earlier 8192 scope; excluded from L3.31a/L3.32a/L3.33a; vision follow-up not eligible because E4B Phase 1 failed |

## Evidence notes

### 8192 text/JSON baseline

Earlier accepted baseline remains:

```yaml
8192:
  E2B:
    transcript_cleanup: accepted
    structured_simple: accepted
    structured_blocks: accepted
  E4B:
    transcript_cleanup: accepted
    structured_simple: accepted
    structured_blocks: accepted
  12B:
    transcript_cleanup: accepted
    structured_simple: accepted
    structured_blocks: accepted
  26B:
    transcript_cleanup: accepted_controlled_only
    structured_simple: not_run
    structured_blocks: not_run
```

L3.32a adds:

```yaml
8192_complex:
  google/gemma-4-e2b: accepted
  google/gemma-4-e4b: accepted
  google/gemma-4-12b-qat: not_run
  google/gemma-4-26b-a4b-qat: not_run
```

### 16k context

L3.31b forensics narrows the L3.31a red result:

```yaml
E2B: all 3 L3.31a 16k cells passed
E4B: all 3 L3.31a 16k cells passed
12B:
  transcript_cleanup_simple: pass
  structured_simple: pass
  structured_blocks: blocked_finish_length_empty_content
26B: not_run
```

The 12B failure is not broad 16k context degradation by current evidence; it is `12B + blocks + 16k` specific.

### Cache/session

L3.33a result:

```yaml
E4B: 12/12 pass, accepted_narrow
12B: 10/12 pass, 2 finish_length hard failures, blocked
E2B: not_run
26B: not_run
kv_reuse_proven: false
cache_benefit_claimed: false
```

L3.33b source application import changes the interpretation, not the model result:

```yaml
warmup_first_requires: session_loaded_or_owner_loaded_model
cold_per_request_plus_warmup_first: invalid_shape
cached_tokens: telemetry_if_reported_not_proof_by_itself
```

### Vision

L3.34 established that PNG data URI image payloads are accepted at API route level, but structured JSON failed with `finish_reason=length` for all four target models.

L3.34.1 repair probe then tested E4B plain text first:

```yaml
model: google/gemma-4-e4b
phase: plain_text
max_tokens: 256
http_status: 200
finish_reason: length
completion_tokens: 256
response_char_count: 0
final_loaded_count: 0
status: blocked
```

Because Phase 1 failed, minimal JSON, simple_description, and other models were not run. No Gemma model is eligible for L3.35.

## Final admission decision

```yaml
gemma_family_closure: not_green
safe_default_context: 8192
16k:
  accepted:
    - google/gemma-4-e2b canary scope
    - google/gemma-4-e4b canary scope
    - google/gemma-4-12b-qat transcript/simple only
  blocked:
    - google/gemma-4-12b-qat structured_blocks
structured_json:
  best_current_models:
    - google/gemma-4-e2b
    - google/gemma-4-e4b
cache_session:
  accepted_narrow:
    - google/gemma-4-e4b
  blocked:
    - google/gemma-4-12b-qat
  kv_reuse_proven: false
vision:
  eligible_for_l3_35: []
  blocked_reason: E4B plain text image sanity failed with finish_length_empty_content
```
