# L3.31b — 16k Context Failure Forensics

Status: evidence-only forensics complete; optional repair probe was attempted once but is not admissible because the recorder failed after inference and before summary persistence.

Timestamp: 2026-07-10T10:27:39+05:00

Source artifacts inspected:

```text
experiments/lmstudio/live_runs/l3_31a_gemma_context_canary_20260710/matrix_l3_31a_gemma_context_canary/
```

No broad rerun was performed. No 26B, Qwen, image, parallel, session/warmup, full context matrix, or 32k run was performed.

## L3.31a aggregate

```yaml
cell_count: 9
result_count: 9
pass_count: 8
fail_count: 1
hard_fail_count: 1
privacy_scan: pass
context_tier: 16384
request_timeout_s: 600
retry_policy: off
```

Model summary from `model_summary.csv`:

| model | attempts | pass | fail | finish_length | json_parse_pass_rate | schema_pass_rate | id_exact_pass_rate | language_pass_rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `google/gemma-4-e2b` | 3 | 3 | 0 | 0 | 1.0 | 1.0 | 1.0 | 1.0 |
| `google/gemma-4-e4b` | 3 | 3 | 0 | 0 | 1.0 | 1.0 | 1.0 | 1.0 |
| `google/gemma-4-12b-qat` | 3 | 2 | 1 | 1 | 0.6667 | 1.0 | blank | 1.0 |

Axis summary:

| axis | value | attempts | pass | fail | pass_rate |
|---|---|---:|---:|---:|---:|
| complexity | simple | 6 | 6 | 0 | 1.0 |
| complexity | medium | 3 | 2 | 1 | 0.6667 |
| schema_variant | hardened_const | 9 | 8 | 1 | 0.8889 |
| cache_mode | none | 9 | 8 | 1 | 0.8889 |

## Required answers

### 1. Did E2B pass all 16k cells?

Yes.

```yaml
google/gemma-4-e2b:
  attempts: 3
  pass: 3
  fail: 0
  status: accepted_for_l3_31a_16k_canary_scope
```

E2B passed:

- transcript cleanup simple;
- structured JSON simple;
- structured JSON blocks.

### 2. Did E4B pass all 16k cells?

Yes.

```yaml
google/gemma-4-e4b:
  attempts: 3
  pass: 3
  fail: 0
  status: accepted_for_l3_31a_16k_canary_scope
```

E4B passed:

- transcript cleanup simple;
- structured JSON simple;
- structured JSON blocks.

### 3. Did 12B fail only blocks or also simple/transcript?

12B failed only the blocks cell.

```yaml
google/gemma-4-12b-qat:
  transcript_cleanup_simple: pass
  structured_json_simple: pass
  structured_json_blocks: fail_finish_length
```

The failed 12B cell was:

```yaml
model_id: google/gemma-4-12b-qat
task_id: l328d1_repair_blocks_ru_ru
context_tier: 16384
response_schema_complexity: blocks
structure_complexity: medium
task_intent: id_preservation
prompt_variant: structured_json_repair_exact_blocks
validation_policy: auto_schema_business
```

### 4. What max_tokens was used?

No explicit `max_tokens` was sent by the managed executor for L3.31a.

The request plan carried:

```yaml
context_tier: 16384
request_timeout_s: 600
```

The managed executor forwards `response_format`, `temperature`, messages, and timeout, but does not currently forward an explicit `max_tokens` field. The observed failed response consumed nearly the full 16k generation side:

```yaml
completion_tokens: 16261
prompt_tokens: 123
finish_reason: length
```

Therefore the forensic classification is:

```yaml
explicit_max_tokens: unset
runtime_effective_generation_cap: approximately_16k_completion_tokens
```

### 5. How many output chars/tokens before finish_length?

For the failed 12B blocks cell:

```yaml
response_char_count: 0
completion_tokens: 16261
prompt_tokens: 123
total_latency_ms: 331612.1
tokens_per_sec: 49.0362
finish_reason: length
```

The OpenAI-compatible payload reported token usage, but the extracted message content was empty.

### 6. Was JSON partial?

No persisted partial JSON was available in the sanitized artifact.

The failed result had:

```yaml
response_char_count: 0
response_hash: empty_string_sha256
json_parse: fail
markdown_fence_leak: pass
```

This means the committed/sanitized result contains no partial JSON body to recover or inspect.

### 7. Did schema/id parse happen before finish_length?

No.

Validation stopped at JSON parse failure:

```yaml
finish_reason_length: fail
markdown_fence_leak: pass
json_parse: fail_invalid_json
schema_validation: not_reached
id_exact_validation: not_reached
```

The model summary `schema_pass_rate=1.0` for 12B is aggregate over parseable schema rows only; it must not be read as schema success for the failed blocks cell.

### 8. Is 12B blocked for all 16k, or only blocks@16k?

Only `blocks@16k` is blocked by this evidence.

```yaml
google/gemma-4-12b-qat:
  blocked_for_all_16k: false
  blocked_for_16k_transcript_cleanup: false
  blocked_for_16k_structured_simple: false
  blocked_for_16k_structured_blocks: true
  blocked_reason: finish_length_empty_content_after_16261_completion_tokens
```

## Hypothesis

The failure is not broad 12B context degradation. It is a narrow interaction:

```yaml
model: google/gemma-4-12b-qat
task_shape: structured_json_blocks
context_tier: 16384
runtime_generation_cap: implicit_or_effective_large_cap
failure: finish_length with empty extracted content
```

Most likely hypotheses, in priority order:

1. max-token/runtime generation cap pathology: no explicit `max_tokens` allowed the runtime to generate until an effective 16k cap and still return empty content;
2. blocks schema + structured runtime interaction specific to 12B;
3. prompt/schema interaction for `structured_json_repair_exact_blocks`;
4. true 16k context degradation is not supported by current evidence because 12B simple/transcript and E2B/E4B all passed.

## Optional tiny repair probe

Allowed probe shape was:

```yaml
model: google/gemma-4-12b-qat
task: structured_json_blocks
context_tier: 16384
max_tokens: 1024
retry_policy: off
attempts: 1
```

A single direct guarded probe was attempted with this shape. The request reached the runtime and cleanup was verified afterward, but the local recorder failed after inference while calling validation with an incorrect argument order, before writing a sanitized summary. Final loaded state after the failed recorder was checked separately:

```yaml
loaded_count: 0
```

Because the only allowed attempt did not produce a durable sanitized summary, no acceptance or rejection is claimed from the optional probe.

```yaml
l3_31b_optional_probe_status: inconclusive_recorder_error
acceptance_claimed: false
rerun_repeated: false
```

## Decision

```yaml
l3_31b_decision:
  e2b_16k_canary_scope: accepted
  e4b_16k_canary_scope: accepted
  12b_16k_transcript_cleanup: accepted
  12b_16k_structured_simple: accepted
  12b_16k_structured_blocks: blocked
  blocked_reason: finish_length_empty_content_after_16261_completion_tokens
  broad_16k_family_acceptance: false
  true_context_degradation: not_proven
  max_tokens_repair_candidate: plausible_but_unproven
```
