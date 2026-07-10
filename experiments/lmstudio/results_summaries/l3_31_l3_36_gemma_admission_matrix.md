# L3.31-L3.37 Gemma Admission Matrix

Status: reconciled after the bounded L3.37 12B reasoning/output-cap diagnostic. Family closure remains partial, not green.

Timestamp: 2026-07-10T20:19:01+05:00

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
| `google/gemma-4-e2b` | accepted | accepted | accepted | accepted | accepted | accepted | accepted | not_run | not_run | not_run | not_run | accepted_text_json_only | vision not run after the required E4B native minimal-JSON gate failed; cache not run for E2B |
| `google/gemma-4-e4b` | accepted | accepted | accepted | accepted | accepted | accepted | accepted | accepted_narrow | accepted_native_narrow | blocked | blocked | partial | native `/api/v1/chat` plain text passed for one asset; minimal JSON failed malformed without truncation; no KV reuse proof for cache despite cache_session quality pass |
| `google/gemma-4-12b-qat` | accepted | accepted | accepted_native_reasoning_off_narrow | blocked | accepted | accepted | accepted_native_reasoning_off_narrow | blocked_research_only | not_run | not_run | not_run | partial_route_specific | L3.37 native reasoning-off produced schema-valid blocks JSON at 1024 for both contexts, but reasoning-on exhausted every cap through 4096 and the strict route remained empty/length-capped; complex and cache/session remain blocked |
| `google/gemma-4-26b-a4b-qat` | accepted_controlled_transcript_only | not_run | not_run | not_run | not_run | not_run | not_run | not_run | not_run | not_run | not_run | research_only_limited | only controlled transcript baseline evidence from earlier 8192 scope; excluded from L3.31a/L3.32a/L3.33a and not run after the E4B native minimal-JSON gate failed |

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
  google/gemma-4-12b-qat: blocked_bounded_512_to_1024
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

The 12B failure is not broad 16k context degradation by current evidence. L3.37
further localizes the earlier `12B + blocks + 16k` failure: the native route with
reasoning explicitly disabled produced schema-valid blocks JSON at 1024 for both
8192 and 16384. This is a narrow native/local-validation acceptance, not proof
that the OpenAI-compatible strict route is repaired.

With native reasoning enabled, visible output remained empty while reasoning
consumed 1021/1024, 2045/2048, 3069/3072, and 4093/4096 output tokens at both
contexts. Increasing the cap did not rescue visible output. The mechanism is
therefore reasoning-dominant cap exhaustion, not simple visible-output budget
insufficiency and not a context-size interaction.

### 12B complex JSON

The E2B/E4B L3.32a result remains 4/4 accepted. One bounded 12B complex case was
then run with adaptive stages `512 -> 1024`; it reached the upper stage with
`finish_reason=length`, empty extracted content, and no parse/schema/business
admission. This changes 12B complex from `not_run` to `blocked` without
authorizing broad L3.32c or 26B expansion.

### L3.37 reasoning and structured-route diagnosis

The bounded L3.37 staircase used the exact installed
`google/gemma-4-12b-qat` variant, whose native capability metadata advertised
`reasoning: off/on` with default `on`. It produced 12 privately retained attempts
and a sanitized companion summary:

```yaml
native_reasoning_off:
  8192: schema_valid_at_1024
  16384: schema_valid_at_1024
native_reasoning_on:
  8192: reasoning_dominant_cap_exhaustion_no_rescue_le_4096
  16384: reasoning_dominant_cap_exhaustion_no_rescue_le_4096
openai_strict_json:
  8192: empty_length_at_1024
  16384: empty_length_at_1024
context_interaction_supported: false
private_records: 12
cleanup_verified_for_every_record: true
final_global_loaded_count: 0
sanitized_summary_sha256: 8d83f83dbabf5ba5a6cb07baaf0fba39fc8bc3044c9299d15c6f707c615ee89e
```

This evidence rules out a general inability to produce the blocks schema and
does not support a runtime/template pathology on the native reasoning-off path.
The strict-route failures remain underdetermined between constrained-route,
chat-template, and default/hidden-reasoning interaction because that route has
no separately proven reasoning-off control in this experiment. They must not be
reported as a simple budget shortage or as broad 12B structured incapability.

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
max_tokens: must_be_explicit_for_repair_or_admission_runs
```

The focused 12B repeated-context follow-up at 16384 also remained blocked. A
reduced exact-repeat/stable-prefix comparison showed 62.08x and 1.58x timing
improvements respectively, but all six outputs were length-limited at the
128-token cap and runtime `cached_tokens` accounting was unavailable. This is
timing-only research evidence, not KV-reuse or cache-benefit proof.

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

The later native E4B gate resolved the route/envelope question. Native
`/api/v1/chat` with `input` text/image `data_url` items and `output[]` extraction
returned 506 characters of non-empty plain text at `max_output_tokens=128`.
The immediately following minimal-JSON gate returned malformed, non-truncated
JSON, so the adaptive policy correctly stopped after one 256-token stage and
the tiny screening gate was skipped. Native plain text is accepted narrowly;
structured vision and L3.35 remain blocked.

## Final admission decision

```yaml
gemma_family_closure: not_green
safe_default_context: 8192
16k:
  accepted:
    - google/gemma-4-e2b canary scope
    - google/gemma-4-e4b canary scope
    - google/gemma-4-12b-qat transcript/simple on the established route
    - google/gemma-4-12b-qat blocks on native reasoning-off with local schema validation only
  blocked:
    - google/gemma-4-12b-qat structured_blocks on OpenAI-compatible strict JSON
structured_json:
  best_current_models:
    - google/gemma-4-e2b
    - google/gemma-4-e4b
  blocked:
    - google/gemma-4-12b-qat bounded 8192 complex case
  route_specific:
    google/gemma-4-12b-qat:
      native_reasoning_off_blocks: accepted_narrow_at_8192_and_16384
      native_reasoning_on_blocks: reasoning_dominant_no_rescue_le_4096
      openai_strict_blocks: blocked_empty_length_at_1024
cache_session:
  accepted_narrow:
    - google/gemma-4-e4b
  blocked:
    - google/gemma-4-12b-qat
  kv_reuse_proven: false
vision:
  eligible_for_l3_35: []
  native_plain_text_accepted_narrow:
    - google/gemma-4-e4b one-asset gate
  blocked_reason: native minimal JSON failed malformed without truncation
next_repair_gates:
  - expose and verify an explicit reasoning-off contract for the production structured route, or keep the native reasoning-off path isolated as a narrow fallback
  - do not broaden 12B complex JSON from the blocks-only L3.37 result
  - repair native minimal JSON before any L3.35 matrix
```
