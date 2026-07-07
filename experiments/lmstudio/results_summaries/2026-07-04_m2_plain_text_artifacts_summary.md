# M2 Plain Text Artifacts — Initial Candidate Screening (First Pass)

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab plain-text artifact screening, not WVM runtime integration
- Diagnostic kind: `plain_text_artifacts_normalized`
- Tasks: `summary_short`, `lecture_notes`, `mic_command_answer`, `freeform_rewrite`
- Temperature: `0`
- Max tokens: `512`
- Lifecycle pattern: preflight native list, controlled native load echo, compat generation runs, exact unload cleanup
- Result status: preliminary first-pass screening, not a production model verdict

## Candidate results

| Candidate | app_concurrency | Requests pass | Finish length | Wall time | VRAM peak | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `gemma4_e2b_q4km` | `1` | `4/4` | `0` | `11641 ms` | `5559 MB` | ✅ pass |
| `gemma4_e2b_q4km` | `2` | `4/4` | `0` | `11250 ms` | `5559 MB` | ✅ pass, slight wall-clock gain |
| `qwen35_4b_q4km` | `1` | `0/4` | `4` | `21031 ms` | not accepted | ❌ fail |
| `gemma4_e4b_q4km` | `1` | `3/4` | `1` | `19344 ms` | not accepted | ❌ fail |
| `qwen35_9b_q4km` | `1` | `0/4` | `4` | `31828 ms` | not accepted | ❌ fail |

`app_concurrency=2` was skipped for candidates that failed the sequential `app_concurrency=1` gate.

## Methodology correction for app_concurrency=2

The accepted `gemma4_e2b_q4km` `app_concurrency=2` run used client-side concurrency while the model was loaded with `parallel=1`.

That means it measured queue pressure / serialized service behavior, not a true loaded-model `parallel=2` throughput profile. Treat the slight wall-clock gain as preliminary queueing evidence only.

The utility now requires `probe-concurrency --loaded-parallel 2` for true app_concurrency=2 probes, or explicit `--allow-queue-pressure` for queued/serialized behavior. A real M2 parallel gate must load the model with `parallel=2` and pass matching `--loaded-parallel 2` metadata.

## Run IDs

```text
gemma4_e2b appconc1: m2_plain_norm_gemma4_e2b_appconc1_001
gemma4_e2b appconc2: m2_plain_norm_gemma4_e2b_appconc2_001
qwen35_4b appconc1:  m2_plain_norm_qwen35_4b_appconc1_001
gemma4_e4b appconc1: m2_plain_norm_gemma4_e4b_appconc1_001
qwen35_9b appconc1:  m2_plain_norm_qwen35_9b_appconc1_001
```

## First-pass interpretation

`gemma4_e2b_q4km` is the only accepted M2 plain-text artifact candidate in this first-pass gate.

- `gemma4_e2b_q4km` passed all four artifact tasks at both app concurrency levels.
- `app_concurrency=2` over `parallel=1` for `gemma4_e2b_q4km` improved total wall time only slightly (`11641 ms -> 11250 ms`) while increasing average per-request latency (`2910 ms -> 4832 ms`).
- `qwen35_4b_q4km` and `qwen35_9b_q4km` hit `finish_reason=length` on all four tasks.
- `gemma4_e4b_q4km` hit `finish_reason=length` on `lecture_notes` and therefore failed the strict first-pass gate.

These failures are profile failures, not production model verdicts. M2r should test constrained output length and max-token/prompt policy before ruling out these candidates for plain text.

## Lifecycle cleanup

Each candidate was run under native lifecycle control:

```text
native preflight loaded count = 0
controlled load echo verified context_length=8192 parallel=1
plain text compat generation batch
exact native unload cleanup
final loaded count = 0
```

Final GPU state after the M2 batch:

```text
VRAM used = 2598 MB
GPU util = 0%
```

## Privacy scan

Accepted M2 artifacts were scanned for raw endpoint paths, raw instance IDs, localhost base URL fragments, local paths, token values and raw provider/body sentinel text.

Result:

```text
0 blocking hits
```

Prompt text and response text were not stored. Metrics store hashes, counts, validation flags, timing and resource observations.

## First-pass gate decision

Use `gemma4_e2b_q4km` sequential/plain `app_concurrency=1` as the current first-pass plain-text artifact baseline.

Do not promote `qwen35_4b_q4km`, `gemma4_e4b_q4km` or `qwen35_9b_q4km` for plain-text artifacts without M2r max-token/prompt triage, because their current M2 failures are strict `finish_reason=length` gate failures.
