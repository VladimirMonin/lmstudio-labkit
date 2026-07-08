# L3.17 Gemma Text Quality Decision Record

Date: 2026-07-08

## Scope

Canonical L3.17 Wave 1 ran a controlled live text-only structured-output quality screening for:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`

Wave 2 (`google/gemma-4-12b-qat`) was configured but was not run because Wave 1 did not pass.

Configs:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_17_text_quality.e2b_e4b.yaml
experiments/lmstudio/structured_matrix/configs/matrix.l3_17_text_quality.12b.yaml
experiments/lmstudio/structured_matrix/suites/l3_17_text_quality_gemma.yaml
```

Run shape:

```text
modality: text
context_tier: 8192
schema_variant: hardened_const
retry_policy: off, retry1
execution_mode: cold_per_request
cache_mode: none
lmstudio_parallel: 1
app_concurrency: 1
queue_pressure_mode: false
text_interaction_mode: single_question
```

Forbidden scopes were not run: image, 26B, Qwen, throughput, parallel, stress, overnight.

## Request counts

```text
Wave 1 planned_request_count: 32
Wave 1 attempt_count: 32
Wave 1 pass_count: 26
Wave 1 fail_count: 6
Wave 1 pass_rate: 0.8125
Wave 2 12B: not run
```

## Validation summary

Per model:

```json
{
  "google/gemma-4-e2b": {
    "attempt_count": 16,
    "pass_count": 12,
    "fail_count": 4,
    "pass_rate": 0.75
  },
  "google/gemma-4-e4b": {
    "attempt_count": 16,
    "pass_count": 14,
    "fail_count": 2,
    "pass_rate": 0.875
  }
}
```

Per language:

```json
{
  "ru_en_mixed": {
    "attempt_count": 16,
    "pass_count": 16,
    "fail_count": 0,
    "pass_rate": 1.0
  },
  "ru_ru": {
    "attempt_count": 16,
    "pass_count": 10,
    "fail_count": 6,
    "pass_rate": 0.625
  }
}
```

Per complexity:

```json
{
  "medium": {
    "attempt_count": 16,
    "pass_count": 16,
    "fail_count": 0,
    "pass_rate": 1.0
  },
  "simple": {
    "attempt_count": 16,
    "pass_count": 10,
    "fail_count": 6,
    "pass_rate": 0.625
  }
}
```

Per volume:

```json
{
  "many": {
    "attempt_count": 16,
    "pass_count": 14,
    "fail_count": 2,
    "pass_rate": 0.875
  },
  "single": {
    "attempt_count": 16,
    "pass_count": 12,
    "fail_count": 4,
    "pass_rate": 0.75
  }
}
```

Retry impact:

```json
{
  "off": {
    "attempt_count": 16,
    "pass_count": 13,
    "fail_count": 3,
    "pass_rate": 0.8125
  },
  "retry1": {
    "attempt_count": 16,
    "pass_count": 13,
    "fail_count": 3,
    "pass_rate": 0.8125
  }
}
```

Retry summary CSV:

```text
retry_policy,attempt_count,retry_attempted_count,recovered_count,recovery_rate
off,16,0,0,
retry1,16,3,0,0.0
```

## Failure taxonomy

```json
{
  "language_mismatch": 6
}
```

All Wave 1 failures were `language_mismatch` on strict Russian simple tasks. The failing rows still passed JSON parse, JSON schema, ID exactness/order, missing/extra/duplicate ID checks, markdown-fence, placeholder, reasoning-leak, and finish-reason checks.

## 12B interpretation

12B remains blocked. It was not run because the required E2B/E4B gate had failures.

Previous L3.10 evidence suggested 12B can be conditionally viable under hardened schema and/or retry. L3.17 does not update that conclusion yet because the staged 12B config did not execute.

## Cleanup proof

Wave 1 used `cold_per_request` lifecycle. Completed rows exported:

```text
load_scope: per_request
cleanup_scope: per_request
final_loaded_instances: 0
session_request_index: 1
session_request_count: 1
```

Post-run model state was checked:

```text
google/gemma-4-e2b loaded_count=0
google/gemma-4-e4b loaded_count=0
google/gemma-4-12b-qat loaded_count=0
```

## Privacy proof

Public-safe snapshot target:

```text
docs/live_demo/latest_text_quality_gemma/
```

The exported snapshot includes:

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

Privacy scan result:

```text
status: pass
violation_count: 0
```

No raw prompt, raw response, raw URL, secret headers, or local temp paths are committed.

## Timing-only telemetry note

This is a timing-only link run:

```text
resource_telemetry_mode: timing_only
resource_telemetry_reason: remote_link_not_measured
```

Missing RAM/VRAM/GPU telemetry is not a failure for this mode.

## Decision

Outcome: E2B/E4B Wave 1 failed.

Decision:

```text
Stop scaling.
Do not run 12B.
Do not run throughput/parallel.
Do not run image live.
Fix schema/tasks/runner validation before more models.
```

Recommended next action:

1. Inspect the strict-Russian language validator against flat/simple JSON schemas with Latin field names (`id`, `title`, `summary`, `tags`, `language`).
2. Decide whether language compliance should evaluate user-visible string values only, not schema key names.
3. Rerun canonical Wave 1 only after that rule is explicit and covered by tests.
