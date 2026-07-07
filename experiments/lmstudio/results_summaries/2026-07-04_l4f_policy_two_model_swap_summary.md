# L4f Policy-backed Two-model Swap — qwen35_4b_q4km → gemma4_e4b_q4km

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab lifecycle experiment, not host application runtime integration
- Primary Lab key: `qwen35_4b_q4km`
- Primary model key: `qwen3.5-4b`
- Secondary Lab key: `gemma4_e4b_q4km`
- Secondary model key: `google/gemma-4-e4b`
- Scenario: `policy_two_model_swap`
- Context length requested: `8192`
- Parallel requested: `1`

## Goal

Prove the Lab policy layer can execute a safe sequential two-model swap without blind duplicate loads or wildcard unloads:

```text
clean baseline for primary and secondary
primary ensure_loaded -> load_required -> native load
primary ensure_unloaded -> unload_required -> exact unload
secondary ensure_loaded -> load_required -> native load
verify primary remains unloaded while secondary is loaded
secondary cleanup -> exact unload
verify both models unloaded
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
host application runtime
```

## Accepted live evidence

Run ID: `l4f_policy_two_model_swap_qwen35_4b_to_gemma4_e4b_002`

The earlier `001` live run also reached `status=policy_swap_ok`, but exposed a CLI success-status mapping gap and returned process exit `2`. The tooling was fixed and covered by fake CLI regressions before accepting `002` as the exit-code-clean evidence run.

| Metric | Value |
| --- | ---: |
| Process exit code | `0` |
| Status | `policy_swap_ok` |
| Error category | `None` |
| Baseline primary loaded count | `0` |
| Baseline secondary loaded count | `0` |
| Policy decisions | `primary_load_required`, `primary_unload_required`, `secondary_load_required`, `secondary_cleanup_unload_required` |
| Native load calls | `2` |
| Native unload calls | `2` |
| Primary load calls | `1` |
| Primary unload calls | `1` |
| Secondary load calls | `1` |
| Secondary unload calls | `1` |
| Primary loaded after primary load | `1` |
| Primary loaded after primary unload | `0` |
| Secondary loaded after secondary load | `1` |
| Primary loaded after secondary load | `0` |
| Primary loaded after cleanup | `0` |
| Secondary loaded after cleanup | `0` |
| Single-model safe verified | `true` |
| `single_model_safe_verified` | `true` |
| `wildcard_unload_used` | `false` |
| `final_primary_loaded_count` | `0` |
| `final_secondary_loaded_count` | `0` |
| Cleanup called | `true` |
| Cleanup secondary verified count | `1` |
| Cleanup secondary remaining count | `0` |
| Context length verified | `true` |
| Applied context length | `8192` |
| Parallel verified | `true` |
| Applied parallel | `1` |
| API token present | `false` |

## GPU and cleanup observations

| Moment | VRAM used | GPU util |
| --- | ---: | ---: |
| Preflight before live swap | `2486 MB` | `1%` |
| After accepted live swap cleanup | `2486 MB` | `1%` |

Load-phase VRAM peak was not sampled in this run. Acceptance is based on native loaded-instance state, exact unload calls and final cleanup verification.

## Privacy scan

Accepted artifacts were checked for raw endpoint paths, raw instance IDs, localhost base URL fragments, local paths, token values and raw provider/body sentinel text.

Result:

```text
0 blocking hits
```

Notes:

- Raw instance identity was kept only in memory; artifacts store hashes.
- Artifact summaries use `endpoint_kinds_*`, not raw endpoint path fields.
- No prompts, transcripts, chat/completion calls or download endpoints were used.

## What this proves

- A policy-backed two-model swap can run against live LM Studio state in a clean baseline.
- The primary model is loaded once, verified, then exact-unloaded before the secondary model is loaded.
- The secondary model is loaded once, while the primary remains unloaded.
- Final cleanup exact-unloads the secondary test-owned instance and verifies both models return to `0` loaded instances.
- No wildcard unload and no duplicate second load are needed for the swap.
- The lifecycle CLI now treats `policy_swap_ok` as a successful terminal state.

## What this does not prove

- It does not fix or change host application runtime behavior.
- It does not test generation quality.
- It does not test concurrent generation while swapping.
- It does not test cache/stateful, `keepModelInMemory`, `tryMmap`, vision or embeddings.
- It does not resolve `qwen35_9b_q4km`.

## Design implication for managed backend

Future `lmstudio_managed` work should stage model switches through policy decisions and observed native state:

```text
list both involved models
reject or defer if baseline contains external/preloaded instances
load current target only when policy returns load_required
unload only host application-owned exact instances
verify old model is unloaded before loading the new model
verify final cleanup state before declaring success
```

This closes the main L4 lifecycle foundation needed before M1/M2 candidate screening uses policy-backed load/swap behavior.
