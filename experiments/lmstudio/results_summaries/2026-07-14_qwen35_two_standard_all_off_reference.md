# Qwen 3.5 two-standard-model all-off reference

Date: 2026-07-14

Status: completed with recorded transport and row failures.

This reference executed the standard non-MTP Qwen 3.5 4B and 9B candidates with reasoning forced off. Raw request and response captures remain in owner-only storage; this document contains only publication-safe aggregate evidence.

## Execution accounting

| Model | Rows | Actual calls | Expected calls | HTTP 200 | HTTP 400 | Row exceptions |
|---|---:|---:|---:|---:|---:|---:|
| `qwen3.5-4b` | 36 | 35 | 37 | 16 | 19 | 2 |
| `qwen/qwen3.5-9b` | 30 | 31 | 31 | 28 | 3 | 0 |
| **Total** | **66** | **66** | **68** | **44** | **22** | **2** |

The two absent 4B calls were session-reuse rows that had no bound previous-response identifier. They failed before issuing an HTTP request. A parallel-pair row accounts for two calls, so row and call totals differ.

## Artifact accounting

- 66 request artifacts.
- 66 response artifacts.
- 14 load records.
- 177 owner-only artifact files in total.
- Final loaded-model count at run completion: 0.

The owner-only summary is bound by SHA-256 `bdb8fb9f88de3d4c5bd40f216ec03b3031d869ec4fcc307504d4bddae2905fd4`. The frozen matrix manifest is bound by SHA-256 `46264eda0caef52a0634832fa69013c42e1a44926007c704c8542e24c867b5fc`.

## Interpretation limits

HTTP 200 indicates transport success, not automatic semantic acceptance. HTTP 400 and row exceptions remain preserved as failures; they are not rewritten or excluded. This summary publishes no prompts, responses, local paths, usernames, command lines, credentials, or raw machine identifiers.
