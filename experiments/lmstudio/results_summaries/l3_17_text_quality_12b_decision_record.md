# L3.17 Gemma 12B Text Quality Decision Record

Date: 2026-07-08

## Scope

This Wave 2 run was opened only after the L3.17.1 Wave 1 rerun reached `hard_fail_count=0`.

Model:

```text
google/gemma-4-12b-qat
```

Run shape:

```text
language: ru_ru, ru_en_mixed
structure_complexity: medium
volume: single, many
schema_variant: hardened_const
retry_policy: off, retry1
context_tier: 8192
execution_mode: cold_per_request
cache_mode: none
resource_telemetry_mode: timing_only
planned_request_count: 8
```

The run did not include simple diagnostic tasks, image live, 26B, Qwen, throughput, parallel, stress, overnight, `/v1/responses`, or route matrix work.

## Result

```text
attempt_count: 8
pass_count: 0
fail_count: 8
hard_fail_count: 8
warning_count: 0
length_ratio_warning_count: 0
pass_rate: 0.0
```

Failure taxonomy:

```text
schema_error: 8
```

Per retry:

```text
off: attempt_count=4, fail_count=4, retry_attempted_count=0
retry1: attempt_count=4, fail_count=4, retry_attempted_count=4, recovered_count=0
```

All rows passed:

```text
json_parse
language_compliance
business_status
finish_reason_length
```

All rows failed:

```text
json_schema
id_exact
```

No `finish_reason=length` was observed.

## Privacy and cleanup

No raw prompt, raw response, raw base URL, host, tokens, or secrets were committed.

Public-safe run artifacts were retained under `/tmp` and summarized only through sanitized CSV/JSON/Markdown metrics.

Privacy scan:

```text
status: pass
violation_count: 0
```

Cleanup proof in run artifacts:

```text
load_scope: per_request
cleanup_scope: per_request
final_loaded_instances: 0
session_request_index: 1
session_request_count: 1
```

## Decision

12B Wave 2 is not accepted.

This is a model/schema-contract failure for the current medium structured task shape, not a length-ratio policy failure:

- length-ratio warnings: 0
- hard failures: 8
- failure category: `schema_error`
- retry1 did not recover any row

## Next recommended action

Do not scale to broader models or throughput.

Recommended next step is a narrow 12B schema-contract forensic slice using sanitized validation errors only:

1. inspect schema paths from safe `json_schema` failure metadata;
2. compare expected `blocks[*].id` contract to the model's parsed JSON structure;
3. decide whether the 12B prompt/schema needs a medium-task rewrite or whether 12B remains blocked for this structured-output family.
