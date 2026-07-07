# MV2.3 — Gemma profile decision

Date: 2026-07-05

## Decision

Gemma E2B is the current structured baseline candidate for the LM Studio Lab managed-runner track.

Gemma E4B remains a heavier candidate, not a production default. It is green for validation, lifecycle and true_parallel throughput, but mixed for one-shot end-to-end speedup when a non-productive warmup is included.

`production_default=false` for all profiles in this decision.

## Evidence used

- MV2.2 managed sequential evidence: `2026-07-05_mv2_2_gemma_medium_sequential_managed_runner_summary.md`.
- MV2.3 true_parallel evidence: `2026-07-05_mv2_3_gemma_true_parallel_managed_runner_summary.md`.
- MV2.3b E4B no-warmup follow-up: `2026-07-05_mv2_3b_gemma_e4b_nowarmup_true_parallel_summary.md`.

## Profile classification

| Profile | Structured medium | Lifecycle cleanup | true_parallel throughput | End-to-end with warmup | Decision |
|---|---|---|---|---|---|
| `gemma4_e2b_q4km` | green | green | green | green | baseline structured candidate |
| `gemma4_e4b_q4km` | green | green | green | mixed | heavier candidate |

## Speedup semantics

Two speedup gates are tracked separately:

| Gate | Formula | Meaning |
|---|---|---|
| `throughput_speedup` | sequential batch wall time / parallel batch wall time | Already-loaded or already-warm batch throughput. |
| `end_to_end_speedup` | sequential total wall time / warmup-plus-parallel total wall time | One-shot user-visible run from a cold/non-warm state. |

Gemma E2B passes both gates in MV2.3.

Gemma E4B passes the throughput gate. Its warmup-inclusive MV2.3 run is mixed (`effective_speedup=1.171x`), while MV2.3b no-warmup is green (`effective_speedup=1.475x`). Therefore E4B must not be summarized as universally green without the warmup qualifier.

## What this decision does not authorize

- No broad CUDA matrix.
- No Qwen conclusions changed yet.
- No vision/image matrix.
- No embeddings/search work.
- No cache/stateful/prefix-cache work.
- No host application runtime integration.
- No QueueManager/UI/SQLite changes.
- No production default selection.

## Next approved track

Proceed to MV2.4 Qwen recovery as a controlled recovery track:

1. MV2.4a capability/routing probe, GET-only.
2. MV2.4b Qwen 4B structured small reasoning/routing probe.
3. MV2.4c Qwen 9B timeout/chunk policy probe.
4. MV2.4d Qwen plain max_tokens/verbosity probe.

Rules for MV2.4:

- sequential first;
- no Qwen true_parallel until sequential is green;
- safe envelopes/artifacts only;
- system metrics enabled for live runs;
- no broad matrix.
