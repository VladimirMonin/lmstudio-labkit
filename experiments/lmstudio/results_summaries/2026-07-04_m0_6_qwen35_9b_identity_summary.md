# M0.6 Native Identity — qwen35_9b_q4km

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: live GET-only LM Studio identity probe, not load/download/generation
- Candidate lab key: `qwen35_9b_q4km`
- Candidate model key checked: `qwen/qwen3.5-9b`
- Run ID: `m0_6_identity_qwen35_9b_001`

## Goal

Resolve the remaining registry candidate before M1/M2 screening without loading it into RAM/VRAM or calling generation endpoints.

## API boundary

Allowed and used endpoint kinds:

```text
compat_models
native_models
```

Explicitly not used in this run:

```text
native_load
native_unload
download
compat_generation
wildcard_unload
cache/stateful
vision
host application runtime
```

## Observed identity facts

| Metric | Value |
| --- | ---: |
| Process exit code | `0` |
| Status | `ok` |
| Resolution status | `resolved` |
| Target found in compat list | `true` |
| Target found in native list | `true` |
| Compat model id verified | `true` |
| Native model key verified | `true` |
| Native load id resolved | `true` |
| Native loaded instances count | `0` |
| Native format | `gguf` |
| Native bits per weight | `4` |
| Native size bytes | `6548927711` |
| Native quantization string | not exposed by native record |
| Native params string | not exposed by native record |
| Native capability keys | `reasoning`, `trained_for_tool_use`, `vision` |

## Registry update

`qwen35_9b_q4km` can now move from `pending_safe_resolution` to `lab_verified` for identity visibility.

Important constraints:

```text
quantization = null
quantization_verified = false
params = null
load_echo absent
```

The `Q4_K_M` string appears in the configured source id, but it was not surfaced by the native record and must not be inferred into verified metadata.

## Privacy scan

Accepted artifacts were checked for raw endpoint paths, raw instance IDs, local paths, token values, raw provider bodies, raw model file names and credential values.

Result:

```text
0 blocking hits
```

Notes:

- The identity artifacts use endpoint kinds, not raw endpoint paths.
- Raw response bodies are not stored.
- Raw target lookup evidence is stored as hashes/booleans/field names only.

## What this proves

- `qwen/qwen3.5-9b` is visible in both compatibility and native LM Studio model lists.
- The native record is currently unloaded.
- Safe native metadata is available for format, bits-per-weight, size and capability keys.
- The registry no longer has unresolved compatible IDs for the four initial text candidates.

## What this does not prove

- It does not prove load success.
- It does not verify applied context length or parallel config.
- It does not prove a quantization string because LM Studio did not expose one in the native record.
- It does not run structured JSON or plain text screening.

## Follow-up completed

Focused policy-backed load echo was completed in `m0_7_policy_backed_smoke_qwen35_9b_001`. The registry now records applied `context_length=8192` and `parallel=1` proof for this candidate.
