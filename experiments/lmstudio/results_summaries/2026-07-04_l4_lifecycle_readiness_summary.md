# L4 Lifecycle Readiness Summary — LM Studio Lab

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: Lab-only lifecycle readiness, before host application runtime integration
- Purpose: close the L4 foundation and define the gate for M1/M2 model screening

## Foundation status

| Area | Evidence | Status | Readiness implication |
| --- | --- | --- | --- |
| Download/progress | `acq_live_qwen35_4b_q4km_001` | ✅ pass | Download and ready-on-disk can be measured separately from load. |
| Already-downloaded idempotency | `d3_already_downloaded_qwen35_4b_002` | ✅ pass | `already_downloaded` is terminal success with no polling loop. |
| Primary identity | `qwen35_4b_q4km` registry | ✅ pass | qwen35_4b has compat/native/quant metadata. |
| Second-model identity | `m0_3_identity_gemma4_e4b_002` | ✅ pass | gemma4_e4b is compat/native visible; quantization string not surfaced. |
| Remaining candidate identity | `m0_6_identity_qwen35_9b_001` | ✅ pass | qwen35_9b is compat/native visible; quantization string not surfaced. |
| Load echo | L4b / L4j | ✅ pass for qwen35_4b and gemma4_e4b | Applied context/parallel must be verified, not assumed from request. |
| Exact unload | L4c | ✅ pass | Cleanup targets exact instance identity only. |
| Already gone | L4g | ✅ pass | Missing instance during unload is a success state. |
| External manual unload | L4d | ✅ pass | Observed native state wins over desired transitional state. |
| Duplicate load behavior | L4e | ✅ duplicate risk confirmed | Native load is not idempotent; list-before-load is mandatory. |
| Timeout reconcile | L4h | ✅ fake/offline pass | Lost load responses must reconcile via native list. |
| Idempotent policy layer | L4i | ✅ fake-first pass | `ensure_loaded()` / `ensure_unloaded()` policy is available for Lab runners. |
| Policy-backed smoke | L4j | ✅ live pass | Same-config loaded instance is reused; duplicate load is prevented. |
| Policy-backed two-model swap | L4f | ✅ live pass | Single-model-safe swap works with exact unload and final cleanup. |

## Readiness decision

The L4 lifecycle foundation is ready for M1/M2 screening under these constraints:

```text
use lifecycle_policy before future live screening
no blind native load
no wildcard unload
exact cleanup only
verify applied load config when load echo evidence is required
record final loaded-instance counts after cleanup
keep generation and lifecycle evidence separate
```

## Candidate readiness

| Candidate | Identity | Load echo | Screening readiness |
| --- | --- | --- | --- |
| `gemma4_e2b_q4km` / `google/gemma-4-e2b` | measured baseline | measured baseline | Ready for M1/M2 baseline continuation. |
| `qwen35_4b_q4km` / `qwen3.5-4b` | lab verified | verified | Ready for M1/M2 through lifecycle policy. |
| `gemma4_e4b_q4km` / `google/gemma-4-e4b` | lab verified | verified by L4j | Ready for M1/M2 through lifecycle policy. |
| `qwen35_9b_q4km` / `qwen/qwen3.5-9b` | lab verified | verified by M0.7 | Ready for M1/M2 through lifecycle policy. |

## Production implications

These L4 facts should become the starting doctrine for future `lmstudio_managed` work:

```text
Download != Load.
Compat model id != native lifecycle identity until verified.
Load must be list-before-load.
POST load is not idempotent.
Same-config second load can create duplicate instances.
Unload must use exact instance id.
Wildcard unload is forbidden.
Observed LM Studio state wins over internal transitional state.
Missing instance during unload is already_unloaded success.
Timeout must be reconciled through native list.
Single-model-safe swap is viable.
```

## Next gates

1. M1 structured JSON screening on confirmed visible models.
2. M2 plain text artifact screening on confirmed visible models.
3. Keep app concurrency at `1` then `2`; do not expand to `4` until a separate gate proves it safe.
4. Keep `keepModelInMemory`, `tryMmap`, cache/stateful, vision and embeddings deferred until the text screening matrix is complete.

## Non-goals

```text
no host application runtime integration
no QueueManager/UI changes
no app_concurrency=4
no keepModelInMemory / tryMmap experiments
no cache/stateful experiments
no vision or embedding work
```
