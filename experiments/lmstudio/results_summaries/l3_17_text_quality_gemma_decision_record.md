# L3.17 Gemma Text Quality Decision Record

Date: 2026-07-08

## Scope

Canonical L3.17 Wave 1 ran a controlled live text-only structured-output quality screening for:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`

Wave 2 (`google/gemma-4-12b-qat`) was initially configured but blocked until L3.17.1 Wave 1 reached `hard_fail_count=0`; it was then run as a medium-only 12B follow-up.

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
Wave 1 original attempt_count: 32
Wave 1 original pass_count: 26
Wave 1 original fail_count: 6
Wave 1 original pass_rate: 0.8125
Wave 1 L3.17.1 rerun attempt_count: 16
Wave 1 L3.17.1 rerun pass_count: 16
Wave 1 L3.17.1 rerun hard_fail_count: 0
Wave 1 L3.17.1 rerun warning_count: 4
Wave 2 12B attempt_count: 8
Wave 2 12B pass_count: 0
Wave 2 12B hard_fail_count: 8
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

All Wave 1 failures were `language_mismatch` on strict Russian simple tasks. The failing rows still passed JSON parse, JSON schema, ID exactness/order, missing/extra/duplicate ID checks, markdown-fence, placeholder, reasoning-leak, finish-reason, and business checks.

## L3.17.1 length-ratio policy update

The earlier Wave 1 remote config exposed `length_ratio=too_long` on `ru_ru_simple_single` while JSON structure, schema, ID, language, placeholder, reasoning-leak, and finish-reason checks passed. That case is now treated as a simple-task policy conflict rather than a model JSON failure:

```text
simple structured task + length_ratio violation => diagnostic only
medium/blocks task + length_ratio violation => hard failure by default
```

Implementation notes:

- `ResponseContract.length_ratio_policy` supports `hard` and `diagnostic`.
- Diagnostic length-ratio violations keep the validation row public-safe, but do not flip the whole validation summary to failure.
- Legacy L3.17 remote simple tasks that still carry length-ratio bounds declare `length_ratio_policy: diagnostic` explicitly.
- The canonical L3.17 config does not apply length-ratio bounds to simple flat/items tasks.

L3.17.1 reran canonical Wave 1 after this policy fix. The `too_long` blocker is gone for the canonical Wave 1 path; the remaining accepted-gate failures are the strict-Russian `language_mismatch` rows above.

## 12B interpretation

12B was run only after the L3.17.1 Wave 1 rerun reached `hard_fail_count=0`.

The 12B medium-only Wave 2 did not pass:

```text
attempt_count: 8
pass_count: 0
hard_fail_count: 8
failure_category: schema_error=8
retry1_recovered_count: 0
```

This updates the prior 12B status from blocked-not-run to tested-and-not-accepted for the current medium structured-output contract.

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

Outcome: L3.17.1 Wave 1 rerun passed the hard acceptance gate with visible simple length-ratio warnings; the subsequent 12B Wave 2 failed the medium structured schema contract.

Decision:

```text
Accept L3.17.1 Wave 1 hard gate.
Record simple length-ratio observations as warnings.
Do not scale beyond 12B.
Do not run 26B, Qwen, image, throughput, parallel, stress, or overnight work.
Treat 12B as not accepted for the current medium structured-output contract.
```

Recommended next action:

1. For E2B/E4B, keep the current length-ratio warning policy and public warning visibility.
2. For 12B, run a narrow schema-contract forensic slice using sanitized validation metadata only.
3. Do not broaden the model matrix until the 12B schema mismatch is understood.
