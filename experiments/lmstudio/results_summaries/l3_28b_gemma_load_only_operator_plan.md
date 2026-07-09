# L3.28b Gemma Load-Only Operator Plan

Status: prepared-only. No live load-only operation has been executed by this slice.

## Purpose

Phase B must prove 12B/26B load capacity and cleanup behavior before any 12B/26B generation canary.

## Important guard

Do **not** execute Phase B through `lmstudio-benchmark run`.
The ordinary matrix runner is a generation runner. The Phase B YAML is a manifest for lifecycle tooling, not a generation config.

## Required command shape

A dedicated operator command must exist before live Phase B, with this shape:

```bash
uv run lmstudio-benchmark load-only \
  --config experiments/lmstudio/structured_matrix/configs/matrix.l3_28b_gemma_load_only_12b_26b.yaml \
  --output-root /tmp/labkit-l328-load-only \
  --live \
  --operator-live-managed \
  --allow-model-loads \
  --allow-remote-base-url \
  --base-url <LM_STUDIO_LINK_URL>
```

Current status: this prepared-only slice documents the required path; it does not add or run a live load-only implementation.
If the command is absent, the next slice must implement L3.28b lifecycle tooling before Phase C generation.

## Acceptance

| model | context | required result |
|---|---:|---|
| google/gemma-4-12b-qat | 8192 | load-only pass or clean block |
| google/gemma-4-12b-qat | 16384 | load-only pass or clean block |
| google/gemma-4-12b-qat | 32768 | load-only pass or clean block |
| google/gemma-4-26b-a4b-qat | 8192 | load-only pass or clean block |
| google/gemma-4-26b-a4b-qat | 16384 | load-only pass or clean block |

Every row must prove:

- no generation call was made;
- requested context equals applied context;
- applied parallel equals 1;
- cleanup proves `final_loaded_instances=0`;
- no model download was required;
- privacy/publication safety passes.

## Stop conditions

Stop immediately on model download required, endpoint unreachable, target model invisible, load verification failure, context mismatch, parallel mismatch, cleanup final-zero failure, privacy scan failure, or any generation call.
