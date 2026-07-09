# L3.29 Gemma Family Bounded Matrix Live Results Report

Status: live run completed for the currently executable 8192 context slice.

Run timestamp: 2026-07-09T17:00:19+05:00 to 2026-07-09T17:10:23+05:00.

Local artifact root, not committed: `/tmp/labkit-l329-l330-20260709-165850`.

## Scope actually executed

The original L3.29 target matrix remains 149 planned attempts:

| lane | config | intended attempts |
|---|---|---:|
| A | `matrix.l3_29a_gemma_transcript_cleanup_screening.yaml` | 72 |
| B | `matrix.l3_29b_gemma_structured_json_screening.yaml` | 72 |
| C | `matrix.l3_29c_gemma_26b_transcript_cleanup_controlled.yaml` | 5 |

The live execution path used the current managed executor. That executor currently accepts only `context_tier=8192`. Attempts that require higher context tiers are therefore runner-blocked, not model failures.

Observed guard:

```text
managed executor v1 requires context_tier=8192
```

Executed live slice:

| lane | executed context | attempts | result |
|---|---:|---:|---|
| A transcript cleanup screening | 8192 | 36 | pass |
| B structured JSON screening | 8192 | 72 | pass |
| C 26B controlled transcript cleanup | 8192 | 5 | pass |

Total executed: **113/113 pass**.

## Overall result

| metric | value |
|---|---:|
| executed_attempt_count | 113 |
| pass_count | 113 |
| fail_count | 0 |
| hard_fail_count | 0 |
| finish_length_count | 0 |
| privacy_scan_status | pass |
| final_loaded_like_count | 0 |

## Lane A — transcript cleanup screening

Config slice: `matrix_l3_29a_gemma_transcript_cleanup_screening_8192_live`.

Models: E2B, E4B, 12B.

| model | attempts | pass | fail | hard fail | json parse | schema | language | finish_length | median latency ms | p95 latency ms | warnings |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `google/gemma-4-e2b` | 12 | 12 | 0 | 0 | 1.0 | 1.0 | 1.0 | 0 | 808.937 | 857.184 | 24 |
| `google/gemma-4-e4b` | 12 | 12 | 0 | 0 | 1.0 | 1.0 | 1.0 | 0 | 887.544 | 1013.741 | 24 |
| `google/gemma-4-12b-qat` | 12 | 12 | 0 | 0 | 1.0 | 1.0 | 1.0 | 0 | 2363.102 | 3113.652 | 24 |

Language/status breakdown:

| language | schema | context | status | count |
|---|---|---:|---|---:|
| `ru_ru` | simple | 8192 | pass | 24 |
| `ru_en_mixed` | simple | 8192 | pass | 6 |
| `en_en` | simple | 8192 | pass | 6 |

Interpretation: transcript cleanup remained green for E2B/E4B/12B on the executable 8192 slice. Warnings are diagnostic review warnings, not failed checks.

## Lane B — structured JSON screening

Config slice: `matrix_l3_29b_gemma_structured_json_screening_8192_live`.

Models: E2B, E4B, 12B.

| model | attempts | pass | fail | hard fail | json parse | schema | id exact | language | finish_length | median latency ms | p95 latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `google/gemma-4-e2b` | 24 | 24 | 0 | 0 | 1.0 | 1.0 | 1.0 | 1.0 | 0 | 428.0 | 543.898 |
| `google/gemma-4-e4b` | 24 | 24 | 0 | 0 | 1.0 | 1.0 | 1.0 | 1.0 | 0 | 531.528 | 711.42 |
| `google/gemma-4-12b-qat` | 24 | 24 | 0 | 0 | 1.0 | 1.0 | 1.0 | 1.0 | 0 | 965.476 | 1106.035 |

Axis/status breakdown:

| language | schema | context | status | count |
|---|---|---:|---|---:|
| `ru_ru` | simple | 8192 | pass | 12 |
| `ru_ru` | blocks | 8192 | pass | 12 |
| `ru_en_mixed` | simple | 8192 | pass | 12 |
| `ru_en_mixed` | blocks | 8192 | pass | 12 |
| `en_en` | simple | 8192 | pass | 12 |
| `en_en` | blocks | 8192 | pass | 12 |

Interpretation: L3.28d.1 structured JSON repair held under the L3.29 matrix. On the executable 8192 slice, structured JSON simple and blocks are fully green for E2B/E4B/12B.

## Lane C — 26B controlled transcript cleanup

Config slice: `matrix_l3_29c_gemma_26b_transcript_cleanup_controlled_8192_live`.

Model: 26B only.

| model | attempts | pass | fail | hard fail | json parse | schema | language | finish_length | median latency ms | p95 latency ms | warnings |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `google/gemma-4-26b-a4b-qat` | 5 | 5 | 0 | 0 | 1.0 | 1.0 | 1.0 | 0 | 3610.393 | 4073.823 | 10 |

Language/status breakdown:

| language | schema | context | status | count |
|---|---|---:|---|---:|
| `ru_ru` | simple | 8192 | pass | 4 |
| `ru_en_mixed` | simple | 8192 | pass | 1 |

Interpretation: 26B controlled cleanup passed the limited L3.29 admission slice. 26B structured JSON remains outside this run by policy.

## Privacy and artifact policy

Privacy scan passed for all three committed-safe result sets:

| lane | privacy status | violation_count |
|---|---|---:|
| A transcript cleanup | pass | 0 |
| B structured JSON | pass | 0 |
| C 26B cleanup | pass | 0 |

Raw local artifacts were not committed:

- `raw_cases.jsonl` remains local-only under `/tmp`;
- raw prompt/response text is not included in this report;
- local PNG/image route probe artifacts are not included in this L3.29 report.

Final runtime check after the run showed no loaded model instances via the LM Studio metadata endpoint:

```text
loaded_like_count: 0
```

## Decisions

1. E2B, E4B, and 12B are admitted for the 8192 text/structured JSON green lane.
2. Structured JSON should not be treated as a Gemma weakness after the L3.28d.1 repair; L3.29 produced 72/72 pass for simple/blocks on E2B/E4B/12B.
3. 26B is admitted only for controlled transcript cleanup in this slice; 26B structured JSON remains blocked.
4. 16384 and any higher-context L3.29 cells are currently blocked by the managed executor implementation, not by observed model failures.
5. No image live conclusion belongs to L3.29; image capability is handled by L3.30.

## Follow-up

- Add or extend a managed live executor path that can run context tiers above 8192, then execute the remaining intended L3.29 context coverage.
- Keep L3.30 image work capability-gated and separate from L3.29 text/structured results.
