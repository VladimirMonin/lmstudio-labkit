# L3.17 Text Quality Screening — Wave 1 Decision Record

Date: 2026-07-08

## Scope

L3.17 Wave 1 ran a controlled live text-only structured-output quality screening for:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`

The run used:

- `/v1/chat/completions`
- structured JSON with hardened schema validation
- context tier `8192`
- execution mode `cold_per_request`
- cache mode `none`
- retry policies `off` and `retry1`
- timing-only telemetry
- no image tasks
- no throughput/parallel/stress/overnight mode
- no raw prompt, raw response, raw base URL, host, or token artifacts

12B was intentionally staged after Wave 1 and was not run because Wave 1 did not reach a zero-failure acceptance state.

## Run artifact

Public-safe latest snapshot:

```text
docs/live_demo/latest_text_quality_gemma/
```

The source run directory was retained outside the repository. Only sanitized summary artifacts are committed.

## Result

```text
attempt_count: 16
pass_count: 12
fail_count: 4
pass_rate: 0.75
```

Per model:

```text
google/gemma-4-e2b: pass=6, fail=2
google/gemma-4-e4b: pass=6, fail=2
```

Failure category:

```text
too_long: 4
```

All observed failures were on `ru_ru_simple_single` and were length-ratio failures. The same rows passed JSON parse, JSON schema, ID exactness, language compliance, no-placeholder, no-reasoning-leak, and finish-reason checks.

Retry impact:

```text
off:    attempt_count=8, retry_attempted_count=0
retry1: attempt_count=8, retry_attempted_count=2, recovered_count=0
```

`retry1` did not recover the length-ratio failures.

## Lifecycle and cleanup

The run used cold per-request lifecycle:

```text
load_scope: per_request
cleanup_scope: per_request
final_loaded_instances: 0
session_request_index: 1
session_request_count: 1
```

Post-run LM Studio state was checked for all staged models:

```text
google/gemma-4-e2b loaded_count=0
google/gemma-4-e4b loaded_count=0
google/gemma-4-12b-qat loaded_count=0
```

## Privacy and non-claims

Privacy scan passed with `violation_count=0` for the exported latest snapshot.

This record does not claim:

- production readiness
- host-application integration readiness
- KV-cache reuse
- throughput or parallel speedup
- image readiness
- 12B readiness
- 26B or Qwen readiness
- RAM/VRAM telemetry for timing-only link runs

## Decision

L3.17 Wave 1 is a useful live quality finding, but it is not an acceptance pass.

12B remains blocked until the E2B/E4B text quality gate is adjusted and rerun to a zero-failure acceptance state, or until the acceptance criteria explicitly treat simple-task length-ratio failures as non-blocking diagnostic warnings.

Recommended next action:

1. Decide whether `ru_ru_simple_single` length-ratio should remain a hard quality failure.
2. If hard: tune prompt/schema expectations and rerun Wave 1 only.
3. If diagnostic: encode that rule explicitly in tests/config/reporting before opening the 12B wave.
