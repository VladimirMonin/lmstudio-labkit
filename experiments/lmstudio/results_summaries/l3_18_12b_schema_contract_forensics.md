# L3.18 12B Schema Contract Forensics

Date: 2026-07-08

## Scope

This is a narrow artifact-only forensic slice for the L3.17.1 12B Wave 2 failure.

Model:

```text
google/gemma-4-12b-qat
```

Source artifacts:

```text
L3.17.1 12B medium-only Wave 2 sanitized run artifacts
```

No new live generation was run for this forensic record. The existing sanitized validation metadata was sufficient, so the allowed one-rerun budget remains unused.

Forbidden scopes were not run: E2B/E4B reruns, 26B, Qwen, image live, throughput, parallel, stress, overnight, route matrix, `/v1/responses`, raw prompt export, raw response export.

## Original 12B Wave 2 result

```text
attempt_count: 8
pass_count: 0
fail_count: 8
hard_fail_count: 8
warning_count: 0
length_ratio_warning_count: 0
failure_category: schema_error
retry1_recovered_count: 0
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

## Forensic question

Why did 12B fail `json_schema` and `id_exact` on medium structured tasks?

The target contract was:

```text
top-level object with blocks array
blocks[*].id must exactly match expected ids in order
single tasks: expected ids [0, 1, 2]
many tasks: expected ids [0, 1, 2, 3, 4, 5, 6, 7]
strict hardened_const schema with per-position id const
```

## Findings

### 1. The failure is not top-level shape collapse

The sanitized id metrics show `seen_count == expected_count` for every failed row and `unexpected_count == 0`.

That means the model produced the expected number of id-bearing block-like items, and the validator could collect ids at `blocks[*].id`. The failure is not primarily “missing blocks array” or “different top-level object”.

### 2. The failure is deterministic id drift inside `blocks[*].id`

Every row failed with:

```text
id_category: id_order_mismatch
order_mismatch: true
unexpected_count: 0
```

The model appears to repeat existing expected ids and omit other expected ids, instead of inventing out-of-range ids.

Aggregated id metrics:

| task pattern | expected ids | first mismatch | duplicate count | missing count | seen count | unexpected count |
|---|---:|---:|---:|---:|---:|---:|
| medium single | 3 | 1 | 2 | 2 | 3 | 0 |
| ru_ru medium many | 8 | 3 | 3 | 3 | 8 | 0 |
| ru_en_mixed medium many | 8 | 2 | 1 | 1 | 8 | 0 |

Interpretation: 12B can keep the container count, but does not preserve the per-position id constants.

### 3. The JSON schema errors align with id const failures

Schema first-error paths:

```text
$.blocks[1].id:const  -> 4 rows
$.blocks[2].id:const  -> 2 rows
$.blocks[3].id:const  -> 2 rows
```

These are exactly per-position id-const failures, not text-field, required-field, language, or finish-reason failures.

By task shape:

| task | retry | schema first error | schema error count | id mismatch summary |
|---|---|---|---:|---|
| ru_ru_medium_single | off | $.blocks[1].id:const | 2 | first mismatch 1, duplicate 2, missing 2 |
| ru_ru_medium_single | retry1 | $.blocks[1].id:const | 2 | first mismatch 1, duplicate 2, missing 2 |
| ru_ru_medium_many | off | $.blocks[3].id:const | 5 | first mismatch 3, duplicate 3, missing 3 |
| ru_ru_medium_many | retry1 | $.blocks[3].id:const | 5 | first mismatch 3, duplicate 3, missing 3 |
| ru_en_mixed_medium_single | off | $.blocks[1].id:const | 2 | first mismatch 1, duplicate 2, missing 2 |
| ru_en_mixed_medium_single | retry1 | $.blocks[1].id:const | 2 | first mismatch 1, duplicate 2, missing 2 |
| ru_en_mixed_medium_many | off | $.blocks[2].id:const | 6 | first mismatch 2, duplicate 1, missing 1 |
| ru_en_mixed_medium_many | retry1 | $.blocks[2].id:const | 6 | first mismatch 2, duplicate 1, missing 1 |

### 4. Retry does not change the failure class

Retry summary:

```text
off:    attempt_count=4, fail_count=4, retry_attempted_count=0
retry1: attempt_count=4, fail_count=4, retry_attempted_count=4, recovered_count=0
```

The same first-error path pattern appears for `off` and `retry1` rows. Retry did not repair id drift.

### 5. This is not the L3.17.1 length-ratio issue

Length-ratio counters:

```text
warning_count: 0
length_ratio_warning_count: 0
```

The 12B failure is independent of the simple length-ratio policy fix. It is a hard schema/id contract failure.

## Diagnosis

12B is producing valid JSON in the expected broad shape, but does not reliably preserve strict positional ids in `blocks[*].id` under `hardened_const` medium tasks.

Best current classification:

```text
model/schema-contract failure: id drift inside otherwise parseable blocks JSON
```

This is not currently evidence of:

```text
- endpoint unreachable
- raw JSON parse failure
- language failure
- finish_reason length/truncation
- top-level shape collapse
- retry recoverability
- length-ratio policy issue
```

## Decision

Keep 12B blocked for this structured-output family.

Do not run broader 12B matrices, 26B, Qwen, image live, throughput, parallel, stress, or overnight on the basis of this contract.

The allowed one-rerun budget was not consumed. If the owner later wants to spend it, the only useful rerun should be a single tiny 12B contract experiment that changes exactly one variable, for example:

```text
A. prompt-level id anchoring rewrite while keeping hardened_const schema
or
B. schema contract rewrite to reduce positional id const pressure
```

If that one rerun still shows id drift, 12B should remain blocked without further retries.

## Recommended next gate

Prefer product momentum after this forensic note:

```text
Proceed with E2B/E4B sustained text screening.
Keep 12B blocked unless a one-shot contract experiment is explicitly approved.
```

For sustained E2B/E4B screening, expand only within the already accepted family:

```text
models: E2B/E4B
languages: ru_ru + ru_en_mixed
complexity: simple + medium + complex
execution: cold_per_request
retry: retry1
more tasks
more repeats
then separate session/warmup
then throughput/parallel
```
