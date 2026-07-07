# M0.7 Policy-backed Load Echo — qwen35_9b_q4km

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab lifecycle experiment, not WVM runtime integration
- Candidate lab key: `qwen35_9b_q4km`
- Model key: `qwen/qwen3.5-9b`
- Run ID: `m0_7_policy_backed_smoke_qwen35_9b_001`
- Scenario: `policy_backed_smoke`
- Context length requested: `8192`
- Parallel requested: `1`

## Goal

Prove that the remaining initial text candidate can be safely loaded through the lifecycle policy, verify applied load config, prevent duplicate loads and exact-unload the created instance before M1/M2 screening.

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
download
compat_generation
wildcard_unload
cache/stateful
vision
WVM runtime
```

## Preflight

Run ID: `m0_7_preflight_get_qwen35_9b_001`

| Metric | Value |
| --- | ---: |
| Status | `already_unloaded` |
| Observed loaded count | `0` |
| Load calls | `0` |
| Unload calls | `0` |
| Endpoint kinds used | `native_list` |

GPU before policy smoke:

| VRAM used | GPU util |
| ---: | ---: |
| `2580 MB` | `2%` |

## Observed behavior

| Metric | Value |
| --- | ---: |
| Process exit code | `0` |
| Status | `policy_smoke_ok` |
| Baseline loaded instances | `0` |
| Loaded instances after load | `1` |
| Loaded instances after unload | `0` |
| Policy decisions | `load_required`, `reuse_existing`, `unload_required`, `already_unloaded` |
| Native load calls | `1` |
| Native unload calls | `1` |
| Second load called | `false` |
| Duplicate prevented | `true` |
| Load verified | `true` |
| Context length verified | `true` |
| Applied context length | `8192` |
| Parallel verified | `true` |
| Applied parallel | `1` |
| API token present | `false` |

GPU after cleanup:

| VRAM used | GPU util |
| ---: | ---: |
| `2683 MB` | `2%` |

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

## Registry update

`qwen35_9b_q4km` can now include:

```yaml
load_echo:
  context_length: 8192
  parallel: 1
  context_length_verified: true
  parallel_verified: true
  observed_by: m0_7_policy_backed_smoke_qwen35_9b_001
```

The native identity constraints remain unchanged:

```text
quantization = null
quantization_verified = false
params = null
```

## What this proves

- `qwen/qwen3.5-9b` can be loaded through policy-backed lifecycle control.
- Applied context length and parallel settings are verified for `8192 / 1`.
- The duplicate guard reuses the existing same-config loaded instance instead of issuing a second load.
- Exact unload returns the model to `0` loaded instances.

## What this does not prove

- It does not run structured JSON or plain text generation.
- It does not measure M1/M2 latency, throughput or validation quality.
- It does not test app concurrency beyond the policy smoke path.

## Next gated step

Include `qwen35_9b_q4km` in M1/M2 only through lifecycle-policy-backed loading and exact cleanup.
