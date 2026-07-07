# L4d External Manual Unload — qwen35_4b_q4km

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab lifecycle experiment, not host application runtime integration
- Lab key: `qwen35_4b_q4km`
- Model key: `qwen3.5-4b`
- Scenario: `external_unload_reconcile`
- Context length requested: `8192`
- Parallel requested: `1`
- Echo/applied config verification: yes

## Manual action

The Lab loaded `qwen3.5-4b`, verified the loaded instance through the native model list, then emitted:

```text
MANUAL_ACTION_REQUIRED
```

The user manually unloaded `qwen3.5-4b` in LM Studio UI while the Lab continued polling native model state.

## API boundary

Allowed and used endpoint kinds:

```text
native_load
native_list
```

Explicitly not used in this run:

```text
native_unload
compat_generation
download
wildcard_unload
cache/stateful
vision
host application runtime
```

## Observed state before/after

Run ID: `l4d_external_unload_qwen35_4b_001`

| Metric | Value |
| --- | ---: |
| Status | `externally_unloaded` |
| Load called | `true` |
| Load verified | `true` |
| Unload called by Lab | `false` |
| Context length verified | `true` |
| Applied context length | `8192` |
| Parallel verified | `true` |
| Applied parallel | `1` |
| Initial loaded instances | `1` |
| Final loaded instances | `0` |
| Poll count | `93` |
| Elapsed | `98687 ms` |
| API token present | `false` |

## VRAM observations

| Moment | VRAM used |
| --- | ---: |
| Before L4d preflight/load | `1123 MB` |
| During loaded wait | not sampled in this manual run |
| After manual unload observed | `1209 MB` |

The key L4d proof is native `loaded_instances` reconciliation, not memory profiling. A load-phase VRAM sample should be added to a later dedicated telemetry run if needed.

## Privacy scan

Accepted artifacts were checked for raw endpoint paths, raw instance IDs, local/process paths, token values, raw provider bodies, chat/download endpoint paths and credential values.

Result:

```text
0 blocking hits
```

Notes:

- Raw instance identity was kept only in memory; artifacts store `instance_id_hash`.
- Artifact summaries use `endpoint_kinds_*`, not raw endpoint path fields.
- The existing environment metadata stores the env-var name `LM_API_TOKEN`, not its value.

## What this proves

- LM Studio native list state is sufficient to observe an external/manual unload.
- The Lab can transition from a loaded state to `externally_unloaded` based on observed server state.
- Lab did not call native unload during L4d.
- Manual unload cleared `loaded_instances` from `1` to `0`.
- Applied load config was echoed and verified before the manual action.
- Observed LM Studio state wins over internal transitional state.

## What this does not prove

- It does not fix or change host application runtime behavior.
- It does not test generation quality or compat generation calls.
- It does not test duplicate load behavior.
- It does not test load timeout reconciliation.
- It does not test two-model swap.
- It does not measure loaded VRAM peak for this specific manual-unload run.

## Next gated steps

1. Commit this L4d evidence summary.
2. Run deliberate duplicate load behavior probe after confirming a clean unloaded baseline.
3. Add load-timeout reconciliation fake/offline proof.
4. Keep two-model swap blocked until a second model has native identity and load echo proof.
