# Qwen 3.5 full-GPU admission matrix

Date: 2026-07-14

Status: no admission. This matrix records a zero-inference capability stop, not model-quality failures.

Machine-readable companion: `2026-07-14_qwen35_full_gpu_admission_matrix.json`.

## Legend

- `confirmed`: directly established by executed evidence.
- `not_proven`: the required positive runtime evidence was unavailable; fail closed.
- `not_evaluated`: no inference denominator or response exists.
- `not_applicable`: the prerequisite gate prevented the operation.
- `no_admission`: production or matrix admission is not supported.

## Candidate accounting

| Candidate | Exact execution identity | Rows | Planned calls | Actual calls | Stop-gated rows | Admission |
|---|---|---:|---:|---:|---:|---|
| `qwen/qwen3.5-4b` | `qwen/qwen3.5-4b@q4_k_m` pinned | 36 | 37 | 0 | 36 | `no_admission` |
| `qwen3.5-9b-mtp` | selected variant unavailable | 30 | 31 | 0 | 30 | `no_admission` |
| **Total** | — | **66** | **68** | **0** | **66** | **no_admission** |

## Admission dimensions

| Candidate | Identity | Lifecycle load | Full-GPU execution | 8k inference | 16k context | Strict route/schema | Cache/session | Concurrency | Vision | Repeatability | Production |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `qwen/qwen3.5-4b` | confirmed | confirmed once | not_proven | not_evaluated | not_evaluated | not_evaluated | not_evaluated | not_evaluated | not_evaluated | not_evaluated | no_admission |
| `qwen3.5-9b-mtp` | not_proven | not_applicable | not_evaluated | not_evaluated | not_evaluated | not_evaluated | not_evaluated | not_evaluated | not_evaluated | not_evaluated | no_admission |

The 4B lifecycle load reported the requested 8192 context and parallelism 1, but this is materialization-shape evidence only. It is not 8k inference evidence. The 9B MTP candidate was not loaded, so its full-GPU state is not evaluated rather than failed.

## Full-GPU gate detail

| Required fact | 4B | 9B MTP |
|---|---|---|
| Immutable execution identity | confirmed | unavailable; fail closed |
| Maximum GPU placement requested | confirmed | not_applicable |
| Materialized exact instance | confirmed | not_applicable |
| Context 8192 / parallel 1 materialized | confirmed | not_applicable |
| GPU KV cache observed | confirmed | not_applicable |
| Authoritative all-layer GPU placement | not_proven | not_evaluated |
| Explicit `cpu_fallback=false` | not_proven | not_evaluated |
| Explicit `resource_downgrade=false` | not_proven | not_evaluated |
| Explicit `memory_thrash=false` | not_proven | not_evaluated |
| Eligible for inference matrix | no | no |

## Lane closure

| Lane | 4B rows/calls | 9B MTP rows/calls | Actual calls | Verdict |
|---|---:|---:|---:|---|
| Lifecycle strict canary | 1 / 1 | 1 / 1 | 0 | stop-gated |
| Structured text | 12 / 12 | 6 / 6 | 0 | not_evaluated |
| Context and cache/session | 10 / 10 | 6 / 6 | 0 | not_evaluated |
| Concurrency | 2 / 3 | 2 / 3 | 0 | not_evaluated |
| Strict structured vision | 11 / 11 | 15 / 15 | 0 | not_evaluated |
| **Total** | **36 / 37** | **30 / 31** | **0** | **66 rows stop-gated** |

## Comparison and deployment boundary

The candidates are not comparable from this matrix. They stopped at different gates and produced no inference outputs. No claim is made about relative quality, speed, memory efficiency, schema following, context, cache, concurrency, vision, or repeatability.

Neither candidate is admitted for production, deployment, unattended processing, or a narrower model-quality lane. Re-entry requires a new reviewed run that satisfies exact identity and authoritative full-GPU evidence before any inference call.
