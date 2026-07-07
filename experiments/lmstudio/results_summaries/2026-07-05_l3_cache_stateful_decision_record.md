# L3 Decision Record — cache/stateful/prefix posture

Date: 2026-07-05

## Status

Accepted for current Lab direction.

## Context

L3 tested LM Studio cache/stateful/prefix assumptions in staged gates:

- L3.0: no-live cache/stateful plan.
- L3.1: pure `lmstudio_managed` cache/stateful contracts.
- L3.2: managed no-live cache runner artifacts.
- L3.3: Gemma E2B functional stateful live smoke.
- L3.4: Gemma E2B stateful vs stateless full-prefix vs compact-memory live comparison.
- L3.4b: Gemma E2B native streaming instrumentation probe.

The important rule remains: successful stateful API usage is not proof of physical KV/prefix reuse.

## Evidence

### L3.3

- Stateful root + two branch requests completed successfully.
- Branches referenced the root response state and were accepted by LM Studio.
- `measurement_status=functional_stateful_ok`.
- `reuse_verdict=kv_reuse_unproven`.
- `kv_reuse_proven=false`.
- Cleanup was verified and final loaded instances were `0`.

### L3.4

- Stateful root: `1/1`.
- Stateful branches: `2/2`.
- Stateless full-prefix branches: `2/2`.
- Compact-memory branches: `2/2`.
- Stateful average branch total latency: `3664.066 ms`.
- Stateless full-prefix average branch total latency: `3820.077 ms`.
- Compact-memory average branch total latency: `3655.695 ms`.
- Stateless/stateful total-latency ratio: `1.042579`.
- `measurement_status=inconclusive`.
- `reuse_verdict=kv_reuse_unproven`.
- `kv_reuse_proven=false`.

The total-latency difference is too small to treat as cache proof. It may be noise, request ordering, runtime warm state, response variability, or another LM Studio/runtime factor.

### L3.4b

- Native streaming instrumentation is available for the small Gemma E2B probe.
- `ttft_available=true`.
- `prompt_processing_available=true`.
- `cached_tokens_available=false`.
- Branch-only prompt-processing averages:
  - stateful branches: `10.098 ms`.
  - stateless full-prefix branches: `16.916 ms`.
  - compact-memory branches: `38.749 ms`.
- Branch-only `cache_proxy=1.675183`.
- `measurement_status=inconclusive`.
- `reuse_verdict=kv_reuse_unproven`.
- `kv_reuse_proven=false`.

The L3.4b prompt-processing signal is useful and promising, but cached-token evidence is still unavailable. Therefore L3.4b does not promote stateful/cache to proven KV reuse.

## Decision

Current L3 posture:

- `stateful_root_branches`: functional and experimental.
- `compact_memory`: practical candidate.
- `stateless_full_prefix`: baseline.
- `kv_reuse`: unproven.

Do not move to a 25k live cache/stateful gate on the basis of L3.3/L3.4/L3.4b alone.

## Next step

L3.4b is complete. The next allowed step is L3.5 no-live 25k prep:

- prepare a 25k lecture manifest and prompt contracts;
- estimate context fit for target context windows;
- keep artifacts privacy-safe;
- keep stateful/cache marked experimental;
- use compact-memory-first posture unless future evidence strengthens KV reuse proof.

Stop before any 25k live run.

## Consequences

- Stateful/cache remains experimental until stronger repeated instrumentation and/or cached-token evidence proves reuse.
- Compact memory should be treated as the production-practical candidate because it does not depend on hidden server-side state or unproven KV reuse.
- L3.5 may proceed as no-live 25k prep.
- L3.6 live 25k remains blocked until no-live prep and resource/privacy gates are green.

## Non-goals

- No host application runtime integration.
- No QueueManager/UI/SQLite changes.
- No production default selection.
- No Qwen recovery.
- No broad CUDA, vision, or embeddings work.
