# L4 Live Lifecycle Smoke — qwen35_4b_q4km

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio lifecycle smoke
- Model key: `qwen3.5-4b`
- Lab key: `qwen35_4b_q4km`
- Context length requested: `8192`
- Parallel requested: `1`
- Generation/chat: not called
- Download: not called during this lifecycle smoke
- Wildcard unload / unload all: not used
- Registry writes: none

## Goal

Run the first minimal live lifecycle packet after acquisition:

```text
L4b controlled_load_echo
L4e duplicate_load_guard
L4c unload_happy_path
L4g unload_already_gone
```

This packet intentionally leaves the model unloaded at the end.

## GPU snapshots

| Moment | VRAM used | VRAM total | GPU util | Power |
| --- | ---: | ---: | ---: | ---: |
| Before load | `2736 MB` | `16311 MB` | `2%` | `19.49 W` |
| After load | `6707 MB` | `16311 MB` | `2%` | `19.33 W` |
| After unload | `2736 MB` | `16311 MB` | `2%` | `19.45 W` |

Observed VRAM delta for the loaded `qwen3.5-4b` instance was approximately `+3971 MB`, and VRAM returned to baseline after unload.

## L4b controlled_load_echo

Run ID: `l4b_controlled_load_echo_qwen35_4b_001`

| Metric | Value |
| --- | ---: |
| Status | `ok` |
| Echo status | `loaded` |
| Load called | `true` |
| List called | `true` |
| Unload called | `false` |
| Applied context length | `8192` |
| Applied parallel | `1` |
| Context length verified | `true` |
| Parallel verified | `true` |
| Load verified via native list | `true` |
| Observed loaded count | `1` |

## L4e duplicate_load_guard

Run ID: `l4e_duplicate_guard_qwen35_4b_001`

| Metric | Value |
| --- | ---: |
| Status | `ok` |
| List called | `true` |
| Load called | `false` |
| Unload called | `false` |
| Observed loaded count | `1` |
| Duplicate instances | no |

## L4c unload_happy_path

Run ID: `l4c_unload_happy_qwen35_4b_001`

| Metric | Value |
| --- | ---: |
| Status | `ok` |
| List called | `true` |
| Load called | `false` |
| Unload called | `true` |
| Loaded count before unload | `1` |
| Loaded count after unload | `0` |

Unload used an exact loaded instance identity in memory. Persisted artifacts contain only the instance hash.

## L4g unload_already_gone

Run ID: `l4g_unload_already_gone_qwen35_4b_001`

| Metric | Value |
| --- | ---: |
| Status | `already_unloaded` |
| List called | `true` |
| Load called | `false` |
| Unload called | `false` |
| Observed loaded count | `0` |

This directly covers the “already gone” reconciliation invariant: if native state says the target is absent, the manager must clear busy/unloading state rather than keep spinning.

## Privacy check

Artifacts for all four live lifecycle runs were scanned for:

```text
raw loaded-instance identifiers
local/process paths
credential values
chat/download endpoints
```

Result:

```text
0 hits
```

## What this proves

- `qwen3.5-4b` can be explicitly loaded with `context_length=8192` and `parallel=1`.
- The echoed/native-observed config matches the requested values for this smoke.
- Native list reconciliation sees exactly one loaded instance after load.
- Duplicate guard detects no duplicate after one controlled load.
- Exact-instance unload works and native list confirms zero loaded instances.
- Already-unloaded state is treated as a successful reconciliation condition.
- The minimal live packet returns VRAM to baseline.

## What this does not prove yet

- Manual external unload reconciliation was not run.
- Duplicate creation behavior from repeated load was not tested.
- Two-model swap was not run.
- Load-timeout reconciliation was not run.
- No long-context or memory-residency settings were tested.

## Next live lifecycle gates

Only when intended:

```text
L4d external_unload_reconcile
L4e duplicate load behavior with a deliberate second load
L4f two_model_swap_plan
L4h load_timeout_reconcile
```

For the current product bug, the key invariant is already visible: UI/runtime status must reconcile transitional states against observed `GET /api/v1/models` state, especially when an instance is already missing.
