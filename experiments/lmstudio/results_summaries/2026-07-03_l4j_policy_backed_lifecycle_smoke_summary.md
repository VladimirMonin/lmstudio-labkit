# L4j Policy-backed Lifecycle Smoke — qwen35_4b_q4km

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab lifecycle experiment, not WVM runtime integration
- Lab key: `qwen35_4b_q4km`
- Model key: `qwen3.5-4b`
- Scenario: `policy_backed_smoke`
- Context length requested: `8192`
- Parallel requested: `1`

## Goal

Prove that the Lab lifecycle runner can use the L4i idempotent policy layer against live LM Studio state:

```text
ensure_loaded absent -> load_required -> native load
ensure_loaded same-config loaded -> reuse_existing -> no second load
ensure_unloaded loaded -> unload_required -> exact unload
ensure_unloaded already gone -> already_unloaded -> no second unload
```

## API boundary

Allowed and used endpoint kinds:

```text
native_list
native_load
native_unload
policy
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

Run ID: `l4j_policy_backed_smoke_qwen35_4b_001`

| Metric | Value |
| --- | ---: |
| Status | `policy_smoke_ok` |
| Baseline loaded instances | `0` |
| Policy decisions | `load_required`, `reuse_existing`, `unload_required`, `already_unloaded` |
| Native load calls | `1` |
| Native unload calls | `1` |
| Duplicate load prevented | `true` |
| Loaded instances after load | `1` |
| Loaded instances after unload | `0` |
| Post-cleanup observed loaded instances | `0` |
| Context length verified | `true` |
| Applied context length | `8192` |
| Parallel verified | `true` |
| Applied parallel | `1` |
| API token present | `false` |

## VRAM observations

| Moment | VRAM used |
| --- | ---: |
| Before live policy smoke | `4894 MB` |
| After live policy smoke | `4868 MB` |
| After post-cleanup GET confirmation | `4894 MB` |

VRAM stayed elevated because unrelated LM Studio/GPU residency was already present before the run. The L4j acceptance proof is based on native loaded instance state and exact lifecycle actions for `qwen3.5-4b`.

## Privacy scan

Accepted artifacts were checked for raw endpoint paths, raw instance IDs, local/process paths, token values, raw provider bodies, chat/download endpoint paths and credential values.

Result:

```text
0 blocking hits
```

Notes:

- Raw instance identity was kept only in memory; artifacts store hashes.
- Artifact summaries use `endpoint_kinds_*`, not raw endpoint path fields.
- The existing environment metadata stores the env-var name `LM_API_TOKEN`, not its value.

## What this proves

- The live Lab lifecycle runner can call the L4i policy layer and record policy decisions.
- When the model is absent, policy returns `load_required` and the runner performs exactly one native load.
- When the same-config test-owned instance is already loaded, policy returns `reuse_existing` and the runner does not issue a duplicate native load.
- When the test-owned instance is loaded, policy returns `unload_required` and the runner unloads the exact instance.
- Once the model is gone, policy returns `already_unloaded` and the runner does not issue another unload.
- This closes the loop between L4e duplicate-risk evidence and L4i fake-first policy.

## What this does not prove

- It does not fix or change WVM runtime behavior.
- It does not test generation quality.
- It does not test downloads or already-downloaded idempotency.
- It does not test two-model swap.
- It does not resolve behavior for external unknown instances beyond the fake-first policy contract.

## Design implication for managed backend

`ensure_loaded()` should become the lifecycle gate for future Lab screening and later managed backend adapters. It must reconcile native observed state before any native load request, and it must treat same-config loaded instances as reusable rather than issuing a blind load.

## Next gated steps

1. Commit this L4j evidence summary.
2. Add D3 already-downloaded idempotency probe if not already covered.
3. Native-verify a second model candidate.
4. Run L4f two-model sequential swap only after the second model is verified.
