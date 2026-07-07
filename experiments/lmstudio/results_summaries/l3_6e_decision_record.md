# LM Studio Lab L3.6e Decision Record

Status: accepted decision record, no new live inference in this step.

## Decision

L3.6 closes with `compact_memory` as the primary practical candidate for the next managed LM Studio architecture slice.

`native_chat_stateful` remains a promising research latency accelerator for one-root-many-branches scenarios, but it is not KV proof and is not yet a production default.

`stateless_full_prefix` remains the expensive baseline/fallback.

`/v1/responses` remains limited to small-context cache-accounting research and stays blocked for long-context production planning because previous 16k probing returned `internal_error`.

Production policy remains unchanged:

- `production_default=false`
- `wvm_runtime_integration=false`
- `kv_reuse_proven=false`

## Evidence summary

### L3.6b — prompt minimization

Prompt minimization succeeded.

- Baseline compact input estimate: `25000` tokens.
- Minimized compact input estimate: `22700` tokens.
- Estimated reduction: `2300` tokens.
- Output reserve: `2048` tokens.
- Conservative margin became positive, allowing the controlled 32k live smoke path to proceed.

### L3.6c — compact_memory live smoke

`compact_memory` controlled live smoke passed.

- Model: `google/gemma-4-e2b`.
- Applied `context_length=32768`.
- Applied `parallel=1`.
- One `/api/v1/chat` request succeeded.
- Output was non-empty.
- Cleanup was verified.
- Final loaded instances: `0`.
- Privacy scan: `pass`.

Note: the first L3.6c attempt failed due to a privacy-scan false positive when LM Studio returned the public model id as the native instance marker. The accepted r2 run passed after an exact-match-only exemption for public `model_id` / `model_key` markers.

### L3.6d — mode comparison

All three comparable modes passed under the same controlled lab constraints.

| Mode | Classification | TTFT ms | Total latency ms | Result |
| --- | --- | ---: | ---: | --- |
| `compact_memory` | `primary_candidate` | `2121.0` | `2730.489` | passed |
| `native_chat_stateful` | `research_latency_candidate` | `144.0` | `778.825` | passed |
| `stateless_full_prefix` | `baseline` | `2358.0` | `2978.328` | passed |

L3.6d gate evidence:

- Applied `context_length=32768`.
- Applied `parallel=1`.
- Cleanup verified: `true`.
- Final loaded instances: `0`.
- Privacy scan: `pass`.
- Memory safety: `pass`.
- `kv_reuse_proven=false` for every mode.

## Native chat interpretation

The `native_chat_stateful` branch latency is strong:

- comparable branch TTFT: `144 ms`;
- comparable branch total latency: `778.825 ms`.

However, that branch depends on a setup root request first:

- setup total latency: about `3197 ms`.

Therefore `native_chat_stateful` is promising for one-root-many-branches workloads, where the setup cost can be amortized across multiple branches. It is not proven superior for one-off tasks, and it is still not proof of physical KV reuse.

## Production policy

Do not promote any L3.6 result directly into WVM runtime defaults.

- `compact_memory` may be carried forward as the primary practical candidate for a reusable managed core.
- `native_chat_stateful` may be carried forward only as a research latency accelerator.
- `stateless_full_prefix` remains a baseline/fallback.
- `kv_reuse_proven` remains false until direct cache-hit telemetry or an equivalent runtime signal exists.

## Responses policy

`/v1/responses` remains blocked for long context after the previous 16k `internal_error` result.

It may stay in the lab only for small-context cache-accounting research. It must not be used as the next long-context integration path.

## Recommended next architecture

Use the L3.6 evidence to start a reusable LM Studio managed core, not WVM runtime integration.

Recommended roles:

- `compact_memory`: primary practical candidate.
- `native_chat_stateful`: research latency accelerator for one-root-many-branches.
- `stateless_full_prefix`: baseline/fallback.
- `/v1/responses`: small-context cache-accounting research only.

Do not touch WVM runtime, UI, QueueManager, Vision, Qwen, or long-context `/v1/responses` retry as part of this decision record.

## Next series proposal — L3.7 reusable LM Studio managed core

Proposed L3.7 scope:

- stable experiment runner contracts;
- artifact schema;
- model profile registry;
- hardware profile collection;
- structured JSON model validation;
- recommendation engine draft.

L3.7 should continue in the lab layer first. Production integration should remain blocked until the managed core contracts, model profiles, hardware profiles, and structured-output validation are explicitly proven.
