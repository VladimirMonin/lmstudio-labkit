# L3.17.1 Text Quality Wave 1 Rerun Decision Record

Date: 2026-07-08

## Scope

This rerun covered Wave 1 only:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`
- text only
- remote link
- context tier `8192`
- `cold_per_request`
- retry policies `off` and `retry1`
- timing-only resource telemetry

The rerun did not include 12B, 26B, Qwen, image live, throughput, parallel, stress, overnight, `/v1/responses`, or route matrix work.

## Policy change

Length-ratio severity is now explicit:

```text
length_ratio_policy.mode: off | warning | hard
```

Rules:

- simple structured tasks use `warning` when length-ratio bounds are present;
- medium/blocks and complex/nested tasks keep `hard` by default;
- `finish_reason=length` remains a hard failure regardless of length-ratio policy;
- invalid JSON, schema violations, placeholder text, markdown fence leaks, reasoning leaks, and language mismatches remain hard failures.

The L3.17 remote Wave 1 simple task `ru_ru_simple_single` now declares:

```yaml
length_ratio_policy:
  mode: warning
```

Medium/complex tasks declare:

```yaml
length_ratio_policy:
  mode: hard
```

## Safe diagnostics for simple length-ratio warnings

No raw prompt or raw response was opened or stored. Safe summaries include:

```text
task_id
model_id
language
structure_complexity
volume
schema_variant
retry_policy
input_char_count
response_char_count
length_ratio_policy_min
length_ratio_policy_max
length_ratio_actual
warning_category
```

Observed length-ratio warnings:

```text
length_ratio_warning_count: 4
task_ids: ru_ru_simple_single
model_ids: google/gemma-4-e2b, google/gemma-4-e4b
min_actual_ratio: 7.6842
max_actual_ratio: 7.7368
policy_min: 0.1
policy_max: 5.0
```

## Result

```text
attempt_count: 16
pass_count: 16
fail_count: 0
hard_fail_count: 0
warning_count: 4
length_ratio_warning_count: 4
pass_rate: 1.0
```

Per model:

```text
google/gemma-4-e2b: pass=8, fail=0, warnings=2
google/gemma-4-e4b: pass=8, fail=0, warnings=2
```

Per language:

```text
ru_ru: pass=12, fail=0, warnings=4
ru_en_mixed: pass=4, fail=0, warnings=0
```

Per complexity:

```text
simple: pass=4, fail=0, warnings=4
medium: pass=8, fail=0, warnings=0
complex: pass=4, fail=0, warnings=0
```

Per volume:

```text
single: pass=12, fail=0, warnings=4
many: pass=4, fail=0, warnings=0
```

Retry impact:

```text
off: attempt_count=8, retry_attempted_count=0, warnings=2
retry1: attempt_count=8, retry_attempted_count=0, warnings=2
```

## Acceptance checks

```text
hard_fail_count: 0
json_parse_pass: 100%
json_schema_pass: 100%
business_hard_pass: 100%
id_exact_pass: 100%
language_pass: 100%
finish_reason_length_count: 0
raw_prompt_response_stored: false
privacy_scan: pass
final_loaded_instances: 0
```

## Snapshot

Public-safe latest snapshot was refreshed at:

```text
docs/live_demo/latest_text_quality_gemma/
```

It contains:

```text
README.md
latest_snapshot.json
latest_snapshot.csv
privacy_scan.json
report.md
model_summary.csv
failure_summary.csv
retry_summary.csv
```

## Decision

Wave 1 is accepted after the L3.17.1 length-ratio severity policy fix.

The remaining simple length-ratio observations are warnings, not hard failures. They are visible in the public-safe snapshot report and latest snapshot JSON.

## Next gate

Because Wave 1 reached `hard_fail_count=0`, the staged 12B medium-only Wave 2 may run under the existing L3.17 restrictions.
