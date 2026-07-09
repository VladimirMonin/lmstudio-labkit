# L3.28a Gemma Family Readiness Report

Status: read-only metadata snapshot; no generation, no model load.

## Required models

| model_id | visible in compat `/v1/models` | native metadata match | loaded instances | max context | type | vision capability |
|---|---:|---:|---:|---:|---|---|
| `google/gemma-4-e2b` | yes | metadata present, exact id not reported | 0 | not reported | text via current route | not reported |
| `google/gemma-4-e4b` | yes | metadata present, exact id not reported | 0 | not reported | text via current route | not reported |
| `google/gemma-4-12b-qat` | yes | metadata present, exact id not reported | 0 | not reported | text via current route | not reported |
| `google/gemma-4-26b-a4b-qat` | yes | metadata present, exact id not reported | 0 | not reported | text via current route | not reported |

## Interpretation

All four target Gemma model IDs are visible through the compatibility model list. The native metadata endpoint exposes model records and loaded-instance state, but does not report the exact compatibility IDs in the same field shape. No model is loaded after this read-only check. No model metadata in this snapshot proves image input capability, so image live is blocked until a dedicated capability check says otherwise.

## Decisions

- E2B/E4B remain ready for small text canaries.
- 12B/26B require explicit load-only guards before generation.
- Vision/image remains capability-gated; do not force image live on text-only route evidence.
