# Qwen 3.5 full-GPU matrix claim red-team

Date: 2026-07-14

Status: PASS WITH MANDATORY CLAIM BOUNDARIES. The manual review is internally consistent and correctly reports a capability stop, but downstream reporting must preserve the distinctions below.

Machine-readable companion: `2026-07-14_qwen35_full_gpu_red_team.json`.

## Bottom line

The evidence supports a safe fail-closed lifecycle result, not a model-quality result. The candidate schedule contains 66 rows accounting for 68 planned inference calls. All 66 rows were stop-gated and actual inference remained 0 of 68 calls. One Qwen 3.5 4B CLI load succeeded and materialized the requested 8192-context, parallel-1 shape, but authoritative all-layer GPU placement and explicit negative fallback, downgrade, and thrash facts were unavailable. Qwen 3.5 9B MTP was not loaded because immutable execution identity was unavailable.

No strict inference route, schema, semantic, cache, concurrency, vision, repeatability, model-comparison, or production claim is supported by this run.

## Classification rules

- **Confirmed:** directly established by the canonical evidence.
- **Overstated:** a narrower fact is established, but the broader wording exceeds the evidence.
- **Unsupported:** the required executed denominator or raw response does not exist.
- **Contradicted:** the claim conflicts with the canonical ledger or admission result.

## Claim audit

| Dimension | Classification | Evidence-backed statement | Invalid stronger claim |
|---|---|---|---|
| Full-GPU | Contradicted for any positive eligibility claim | The 4B model loaded with maximum GPU requested, but full-GPU execution was not proven; 9B had no load attempt. | Either model was proven fully GPU-resident or admitted to the matrix. |
| Route | Overstated if CLI load success is generalized; inference route unsupported | One CLI lifecycle load returned success. | The API-bound strict route, inference transport, or response surface worked. No inference request was sent. |
| Schema | Unsupported | Schema denominator is 0. | JSON Schema or business validation passed or failed for either model. |
| Context | Overstated beyond materialization shape | The 4B loaded instance reported context 8192 and parallel 1. | 8k inference quality, 16k admission, long-context retention, or context performance was tested. |
| Cache/session | Unsupported | Cache/session denominator is 0 of 16 planned calls. | Prefix, warm, cold, or session reuse behavior was measured. |
| Concurrency | Unsupported | Concurrency denominator is 0 of 6 planned calls across 4 rows. | Sequential or parallel-2 throughput, stability, or full-GPU behavior was measured. |
| Vision | Unsupported | Vision response denominator is 0 of 26 planned calls. | Vision transport, schema, grounding, OCR, or pixel fidelity was evaluated. |
| Repeatability | Unsupported | Neither repeat source nor repeat call executed. | Output stability or repeatability was measured. |
| Model comparison | Unsupported | The models stopped at different prerequisite gates and produced no inference outputs. | 4B is better or worse than 9B in quality, speed, schema adherence, context, cache, concurrency, or vision. |
| Production | Contradicted for any admission or recommendation claim | Stage 4 authorized 0 models, 0 rows, and 0 calls. | Either model is production-ready, recommended, ranked, or approved by this matrix. |

Cleanup is separately **confirmed**: captured initial, group-final, matrix-final, and review-time checks all reported zero loaded models from both sources.

## Denominator reconciliation

| Scope | Candidate rows | Planned inference calls | Actual inference calls | Stop-gated rows |
|---|---:|---:|---:|---:|
| Lifecycle strict canary | 2 | 2 | 0 | 2 |
| Structured text | 18 | 18 | 0 | 18 |
| Context and cache/session | 16 | 16 | 0 | 16 |
| Concurrency | 4 | 6 | 0 | 4 |
| Strict structured vision | 26 | 26 | 0 | 26 |
| **Total** | **66** | **68** | **0** | **66** |

The row/call difference is entirely due to the two `parallel_pair` rows, each representing two planned inference calls. Per model, 4B accounts for 36 rows and 37 planned calls; 9B MTP accounts for 30 rows and 31 planned calls.

The 66 ledger records contain 66 `stop_gated` statuses, zero capture references, zero non-null acceptance verdicts, and zero actual inference calls. Therefore, `0 successful cells` must not be rewritten as `all model outputs failed`: there were no model outputs.

## Mandatory corrections for downstream reports

1. Use **66 candidate rows / 68 planned inference calls / 0 actual inference calls**. Do not use the earlier 80-call ceiling as the executed plan denominator.
2. Say **0 of 68 calls executed** and **66 of 66 rows stop-gated**. Do not say 68 rows, 66 calls, or 68 failed calls.
3. Keep the single successful CLI load outside inference denominators. It is 1 successful lifecycle load transport, not one successful strict canary or inference cell.
4. Describe 4B as **materialized at the requested 8192/parallel-1 shape but not proven full-GPU**. Do not infer all-layer GPU placement from `--gpu max`, load success, GPU KV placement, or reported memory size.
5. Describe 9B as **not loaded because immutable execution identity was unavailable**. Do not label it a full-GPU failure, transport failure, or lower-quality model.
6. Mark route, schema, semantic, cache, concurrency, vision, and repeatability results as **not evaluated**, not failed.
7. Preserve snapshot provenance: the executed canary used an earlier manifest and host snapshot. Later runtime-authority repairs were not executed and cannot retroactively strengthen the canary evidence.
8. Publish no model ranking, capability comparison, production admission, or deployment recommendation from this run.

## Independent checks

The red-team independently recomputed the final manifest as 66 rows and 68 planned calls, including lane and per-model counts. It parsed all 66 canonical ledger records and reproduced the three stop-reason totals: 1 `full_gpu_materialization_not_proven`, 35 `base_full_gpu_not_proven`, and 30 `execution_identity_unavailable`. All 16 files in the owner-only evidence index matched their recorded size, mode, and SHA-256 digest, and the evidence root retained owner-only permissions.

## Verdict

The manual review's core conclusion is confirmed: this is a capability-stop result with zero inference, not evidence about model quality. The only publication-safe positive operational claims are bounded lifecycle facts, evidence integrity, fail-closed gating, and cleanup. Every quality or production claim listed above must remain explicitly unadjudicated or rejected as an inference from this run.
