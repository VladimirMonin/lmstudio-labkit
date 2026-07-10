# L3.31 Gemma Context Screening Decision Record

Status: historical preparation record, reconciled with the completed bounded evidence below.

## Prepared configs

- `matrix.l3_31a_gemma_context_canary.yaml` — 9-request 16k canary.
- `matrix.l3_31b_gemma_context_screening.yaml` — 36-request 16k/32k screening, run only after L3.31a passes.
- `matrix.l3_31c_gemma_26b_context_controlled.yaml` — prepared-only 26B 16k controlled policy, requires prior 26B load-only at 16384.

## Required live report fields

- per-model context table;
- per-lane context table;
- requested/applied context verification;
- latency by context;
- runner-blocked cells;
- model-failed cells;
- cleanup proof;
- privacy proof.

## Current decision

Higher contexts are no longer rejected by the constructor/plan guard in tests. The managed executor now has an explicit context allowlist for `8192`, `16384`, and `32768`, and the CLI managed-live path passes a single homogeneous config `context_tier` into the executor.

Live admission still requires the L3.31a canary to prove exact applied context and cleanup final zero. Do not mark 16k/32k as live-accepted from offline tests alone.

## Non-live verification recorded

Recorded on 2026-07-09 UTC, non-live only:

```text
uv run pytest -q tests/lmstudio_labkit/test_managed_executor_mocked.py tests/lmstudio_labkit/test_managed_executor_lifecycle_safety.py tests/lmstudio_labkit/test_cli_live_profile_guards.py tests/lmstudio_labkit/test_l3_31_l3_32_gemma_closure_configs.py
28 passed
python scripts/audit_publication_safety.py
Publication safety audit passed.
```

No live LM Studio calls, model loads, downloads, remote inference, stress runs, raw prompt artifacts, or raw response artifacts are claimed by this record.

## Status taxonomy for L3.31

| scope | status | reason |
|---|---|---|
| 8192 inherited Gemma text/structured baseline | accepted | Prior sanitized L3.29 evidence accepted 8192 transcript cleanup and simple/blocks structured JSON for E2B/E4B/12B. |
| L3.31a 16k E2B/E4B/12B canary | prepared_only | Config is the only initial live candidate, but acceptance requires an approved live run with applied-context proof. |
| L3.31b 16k/32k screening | runner_blocked | Mixed `context_tier` values cannot be sent through the current managed-live CLI path; split by context tier or add explicit homogeneous grouping before live execution. |
| L3.31c 26B 16k controlled policy | prepared_only | 26B remains gated on explicit owner approval and prior 26B load-only proof at 16384. |
| L3.31 model failures | none_claimed | No L3.31 live model outputs were generated in this non-live slice, so there is no model-failure evidence. |
| L3.31 live acceptance | not_claimed | Acceptance remains blocked until live applied-context proof and cleanup proof exist. |

## Launch attempt status

Recorded on 2026-07-10, after owner approval to follow the staged live order:

```yaml
config: experiments/lmstudio/structured_matrix/configs/matrix.l3_31a_gemma_context_canary.yaml
preflight_status: pass
planned_request_count: 9
live_attempt_count: 0
runtime_status: unavailable
classification: runner_blocked_runtime_unavailable
model_failure: false
```

The local LM Studio API endpoint was not listening at `http://127.0.0.1:1234`:

```text
GET /v1/models -> connection refused
GET /api/v1/models -> connection refused
```

L3.31a therefore remains not accepted. It must not be converted into a model
failure because no model output was produced and `applied_context=16384` could
not be proven.

## Closure evidence update — 2026-07-10

The runtime-unavailable launch attempt above was later superseded by a bounded
live rerun and one narrowly approved 12B repair attempt:

```yaml
l3_31a:
  attempts: 9
  pass: 8
  fail: 1
  accepted:
    - E2B transcript/simple/blocks at 16384
    - E4B transcript/simple/blocks at 16384
    - 12B transcript/simple at 16384
  blocked:
    - 12B blocks at 16384
  privacy: pass
  final_loaded_count: 0
l3_31c_12b_blocks_repair:
  attempts: 1
  max_tokens: 1024
  finish_reason: length
  completion_tokens: 1024
  status: fail
  final_loaded_count: 0
```

The capped repair result is durable model-output evidence, not a recorder
failure and not a runner blocker. It does not admit the failed 12B blocks cell.
No 32k, broad L3.31b, 26B context, parallel, or stress run was performed.
