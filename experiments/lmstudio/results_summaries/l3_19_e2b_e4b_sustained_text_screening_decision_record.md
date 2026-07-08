# L3.19 — E2B/E4B Sustained Text Screening Decision Record

## Status

L3.19 is a completed bounded live screening slice, but it is **not accepted as a clean sustained gate**.

Reason: the run produced hard failures on the strict Russian simple task.

## Scope

Included:

- models:
  - `google/gemma-4-e2b`
  - `google/gemma-4-e4b`
- modality: text only
- languages:
  - `ru_ru`
  - `ru_en_mixed`
- structure complexity:
  - simple
  - medium
  - complex
- execution mode: `cold_per_request`
- cache mode: `none`
- retry policies:
  - `off`
  - `retry1`
- repeats: `2`
- strict JSON schema runtime: enabled
- telemetry: timing-only remote-link metadata
- artifacts: public-safe summaries and latest snapshot only

Excluded:

- `google/gemma-4-12b-qat`
- 26B generation
- Qwen generation
- image live
- session/warmup
- throughput/parallel
- stress/overnight
- `/v1/responses`
- raw prompt artifacts
- raw response artifacts
- raw base URL artifacts

## Run shape

The first full 96-request sustained shape was treated as too large for this bounded slice because cold per-request lifecycle produced no intermediate artifacts within the short operator wait window. It was stopped and cleaned up before publishing.

The published bounded L3.19 run used 48 live attempts:

- 2 models
- 6 task specs
- 2 retry policies
- 2 repeats

This still covers the requested accepted-family axes: `ru_ru`, `ru_en_mixed`, simple, medium, complex, `cold_per_request`, `retry1`, and repeated execution.

## Result summary

From the latest public-safe snapshot:

```text
attempt_count: 48
pass_count: 40
fail_count: 8
hard_fail_count: 8
warning_count: 0
pass_rate: 0.8333
failure_categories: {"language_mismatch": 8}
```

Per model:

```text
gemma4_e2b: 20 pass / 4 fail
gemma4_e4b: 20 pass / 4 fail
```

Per language:

```text
ru_en_mixed: 24 pass / 0 fail
ru_ru:       16 pass / 8 fail
```

Per complexity:

```text
complex: 16 pass / 0 fail
medium:  16 pass / 0 fail
simple:   8 pass / 8 fail
```

Retry impact:

```text
off:    20 pass / 4 fail
retry1: 20 pass / 4 fail, recovered_count=0
```

Lifecycle:

```text
execution_mode: cold_per_request
load_scope: per_request
cleanup_scope: per_request
final_loaded_instances: [0]
```

## Failure interpretation

All hard failures are language compliance failures on one task family:

```text
task_id: ru_ru_simple_single
failure_category: language_mismatch
affected_models: gemma4_e2b, gemma4_e4b
retry_policy: off and retry1
repeats: both repeats
```

Important negative findings:

- JSON parsing passed.
- JSON schema validation passed.
- ID exact validation passed.
- No length-ratio warnings were emitted.
- Medium tasks passed.
- Complex tasks passed.
- Mixed RU/EN tasks passed.
- Retry did not recover the language mismatch.

This means L3.19 did **not** reveal an E2B/E4B schema/id regression. It revealed a strict-language issue on the Russian simple single contract.

## Decision

E2B/E4B remain accepted candidates for structured JSON schema/id reliability, but L3.19 sustained text screening is **blocked for clean acceptance** until `ru_ru_simple_single` language behavior is addressed or the task is reclassified.

Do not proceed to session/warmup or throughput/parallel from this run as if it were clean.

Recommended next slice:

```text
L3.19.1 — ru_ru simple language contract cleanup
```

Scope:

- only E2B/E4B
- only `ru_ru_simple_single`
- inspect sanitized validation metadata
- decide whether the issue is prompt wording, expected language policy, or model behavior
- at most one rerun after changing exactly one contract variable

Keep blocked:

- 12B
- 26B
- Qwen
- image live
- throughput/parallel
- overnight/stress

## Published artifacts

Latest public-safe snapshot:

```text
docs/live_demo/latest_text_quality_e2b_e4b_sustained/latest_snapshot.json
```

Privacy scan status:

```text
status: pass
violation_count: 0
raw_prompt_response_stored: false
raw_base_url_stored: false
```
