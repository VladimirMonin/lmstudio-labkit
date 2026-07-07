# M0.3 Second-model Identity — gemma4_e4b_q4km

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: live GET-only LM Studio identity probe, not load/download/generation
- Candidate lab key: `gemma4_e4b_q4km`
- Candidate model key checked: `google/gemma-4-e4b`
- Run ID: `m0_3_identity_gemma4_e4b_002`

## Goal

Find a second candidate that is visible through both LM Studio compatibility and native model lists before attempting any load or two-model swap.

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
WVM runtime
```

## Observed identity facts

| Metric | Value |
| --- | ---: |
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
| Native size bytes | `6326932336` |
| Native quantization string | not exposed by native record |
| Native params string | not exposed by native record |
| Native capability keys | `reasoning`, `trained_for_tool_use`, `vision` |

## Privacy scan

Accepted artifacts were checked for raw endpoint paths, raw instance IDs, local/process paths, token values, raw provider bodies, chat/download endpoint paths and credential values.

Result:

```text
0 blocking hits
```

Notes:

- The identity artifacts use endpoint kinds, not raw endpoint paths.
- Raw response bodies are not stored.
- Raw target lookup evidence is stored as hashes/booleans/field names only.

## What this proves

- `google/gemma-4-e4b` is visible in both compatibility and native LM Studio model lists.
- The native record is currently unloaded.
- Safe native metadata is available for format, bits-per-weight and size.
- This candidate is eligible for a future load-echo probe.

## What this does not prove

- It does not prove load success.
- It does not verify applied context length or parallel config.
- It does not prove a quantization string because LM Studio did not expose one in the native record.
- It does not run generation or quality screening.
- It does not yet make the candidate ready for L4f two-model swap; load echo proof is still required.

## Next gated step

Run a controlled load echo / policy-backed smoke for this second model only after GPU availability is acceptable. The run must unload the exact created instance and verify final loaded count returns to zero.
