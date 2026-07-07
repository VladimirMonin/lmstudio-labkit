# L4e Duplicate Load Behavior — qwen35_4b_q4km

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab lifecycle experiment, not WVM runtime integration
- Lab key: `qwen35_4b_q4km`
- Model key: `qwen3.5-4b`
- Scenario: `duplicate_load_behavior`
- Context length requested: `8192`
- Parallel requested: `1`

## Goal

Measure what LM Studio does when the same model is loaded twice with the same config:

```text
baseline list
first native load
native list verify
second native load with same config
native list classify
exact cleanup of owned instances
```

## API boundary

Allowed and used endpoint kinds:

```text
native_list
native_load
native_unload
```

Explicitly not used in this run:

```text
compat_generation
download
wildcard_unload
cache/stateful
vision
WVM runtime
```

## Observed behavior

Run ID: `l4e_duplicate_load_behavior_qwen35_4b_001`

| Metric | Value |
| --- | ---: |
| Status | `duplicate_instances_confirmed` |
| Baseline loaded instances | `0` |
| First load verified | `true` |
| First loaded instances | `1` |
| Second load called | `true` |
| Final loaded instances before cleanup | `2` |
| Distinct instance hashes | `2` |
| Duplicate instance count | `2` |
| Cleanup called | `true` |
| Cleanup verified count | `2` |
| Cleanup remaining count | `0` |
| Post-cleanup observed loaded instances | `0` |
| Context length verified | `true` |
| Applied context length | `8192` |
| Parallel verified | `true` |
| Applied parallel | `1` |
| Elapsed | `7235 ms` |
| API token present | `false` |

## VRAM observations

| Moment | VRAM used |
| --- | ---: |
| Before live duplicate run | `1427 MB` |
| After live duplicate cleanup | `1546 MB` |
| After post-cleanup GET confirmation | `1544 MB` |

Load-phase VRAM peak was not sampled in this run. The lifecycle proof is based on observed native loaded instance count and exact cleanup verification.

## Privacy scan

Accepted artifacts were checked for raw endpoint paths, raw instance IDs, local/process paths, token values, raw provider bodies, chat/download endpoint paths and credential values.

Result:

```text
0 blocking hits
```

Notes:

- Raw instance identities were kept only in memory; artifacts store hashes.
- Artifact summaries use `endpoint_kinds_*`, not raw endpoint path fields.
- The existing environment metadata stores the env-var name `LM_API_TOKEN`, not its value.

## What this proves

- LM Studio does not reject or idempotently reuse a duplicate same-config native load for `qwen3.5-4b` in this environment.
- A second same-config load created a second distinct loaded instance.
- Duplicate instance risk is real and must be guarded by any future managed backend.
- Exact-id cleanup can unload both test-owned instances and verify `loaded_instances=0` afterward.
- No wildcard unload is needed for safe cleanup.

## What this does not prove

- It does not fix or change WVM runtime behavior.
- It does not test generation quality.
- It does not test load timeout reconciliation.
- It does not test two-model swap.
- It does not measure VRAM peak while both duplicate instances were loaded.

## Design implication for managed backend

Future LM Studio backend orchestration must not issue blind duplicate load requests. It should reconcile native observed state first and use a duplicate guard keyed by model/config/loaded instance state before calling native load.

## Next gated steps

1. Commit this L4e evidence summary.
2. Add L4h load-timeout reconciliation fake/offline proof.
3. Keep two-model swap blocked until a second model has native identity and load echo proof.
