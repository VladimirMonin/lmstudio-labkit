# Qwen 3.5 full-GPU matrix closure

Date: 2026-07-14

Status: capability stop with zero inference. Neither candidate is admitted or recommended by this matrix.

Machine-readable companion: `2026-07-14_qwen35_full_gpu_matrix_closure.json`.

## Decision

The bounded schedule closed safely without entering inference. The final manifest contains 66 candidate rows accounting for 68 planned inference calls. All 66 rows were stop-gated, and 0 of 68 inference calls executed.

This result confirms fail-closed gating, evidence integrity, one bounded lifecycle load, and cleanup. It does not establish model quality, model ranking, or production suitability.

## Exact accounting

| Lane | Candidate rows | Planned inference calls | Actual inference calls | Stop-gated rows |
|---|---:|---:|---:|---:|
| Lifecycle strict canary | 2 | 2 | 0 | 2 |
| Structured text | 18 | 18 | 0 | 18 |
| Context and cache/session | 16 | 16 | 0 | 16 |
| Concurrency | 4 | 6 | 0 | 4 |
| Strict structured vision | 26 | 26 | 0 | 26 |
| **Total** | **66** | **68** | **0** | **66** |

The two `parallel_pair` rows each account for two planned calls, which is why the row and call totals differ. The earlier ceiling of 80 calls was a planning bound, not the final schedule denominator.

Zero successful cells does not mean that model outputs failed. No inference output exists.

## Full-GPU evidence

### Qwen 3.5 4B

The exact `qwen/qwen3.5-4b@q4_k_m` variant and its projector were pinned. One CLI lifecycle load requested maximum GPU placement and completed successfully. The materialized instance reported context length 8192, parallelism 1, and GPU KV-cache placement.

The hard admission gate still failed. The executed snapshot did not expose authoritative `gpu_layers == total_layers > 0`, an authoritative runtime-telemetry record proving all-layer placement, or explicit negative facts for CPU fallback, resource downgrade, and memory thrashing. Requested `--gpu max`, successful materialization, GPU KV placement, and a memory estimate are not proof of full-GPU execution.

Result: 36 of 36 candidate rows stop-gated; 0 of 37 planned inference calls executed.

### Qwen 3.5 9B MTP

The catalog entry identified a Q4_K_S 9B MTP candidate, but it exposed no immutable selected-variant identity. The exact execution identity therefore remained unavailable and the model failed closed before load.

Result: 30 of 30 candidate rows stop-gated; 0 load attempts; 0 of 31 planned inference calls executed.

This is not evidence that the 9B candidate cannot run fully on GPU, and it is not a transport or quality failure.

## Dimension results

| Dimension | Executed denominator | Publication-safe verdict |
|---|---:|---|
| Lifecycle load transport | 1 | One successful 4B CLI load; matrix admission still failed |
| Full-GPU eligibility | 0 admitted models | Not proven for either candidate |
| Inference transport and route | 0 calls | Not evaluated |
| Raw JSON and schema validity | 0 responses | Not evaluated |
| Business and semantic fidelity | 0 responses | Not evaluated |
| 8k inference behavior and 16k context | 0 calls | Not evaluated |
| Cache/session behavior | 0 of 16 planned calls | Not evaluated |
| Concurrency behavior | 0 of 6 planned calls | Not evaluated |
| Vision grounding and OCR | 0 of 26 planned calls | Not evaluated |
| Repeatability | 0 repeat calls | Not evaluated |

## Comparison limits

The candidates stopped at different prerequisite gates: 4B materialized but lacked authoritative full-GPU proof, while 9B MTP lacked immutable execution identity and was not loaded. Neither produced an inference response. The evidence therefore supports no comparison of quality, latency, throughput, schema adherence, context handling, cache behavior, concurrency, vision, or repeatability.

No model ranking is published. A smaller or larger parameter count, quantization, catalog capability, or memory estimate must not be substituted for executed comparative evidence.

## Proven operational facts

- The canonical ledger contains 66 `stop_gated` records and reconciles every candidate row.
- Stop reasons are 1 `full_gpu_materialization_not_proven`, 35 `base_full_gpu_not_proven`, and 30 `execution_identity_unavailable`.
- One 4B CLI load and one unload completed within the bounded lifecycle operation.
- Initial, group-final, matrix-final, and independent review-time dual-source checks all reported zero loaded models.
- All 16 indexed owner-only evidence payloads matched their recorded sizes, modes, and SHA-256 digests.
- Raw requests, responses, runtime details, and local locators remain outside the publication artifact.

## Snapshot provenance

The executed canary used an earlier manifest and production-host snapshot. Runtime-authority repairs made afterward were reviewed but not executed in another authorized canary. They cannot retroactively strengthen the executed evidence or change the zero-inference result.

## Non-claims

This closure does not claim:

- authoritative full-GPU execution for either model;
- successful strict inference transport or response generation;
- schema, semantic, context, cache, concurrency, vision, or repeatability performance;
- that 66 rows or 68 calls produced failed outputs;
- that either model is better, worse, production-ready, deployment-ready, or recommended;
- that catalog capabilities, estimates, or requested load settings are runtime proof.

## Canonical companions

- [Admission matrix](2026-07-14_qwen35_full_gpu_admission_matrix.md)
- [Model cards](2026-07-14_qwen35_full_gpu_model_cards.md)
- [Manual review](2026-07-14_qwen35_full_gpu_manual_review.md)
- [Claim red-team](2026-07-14_qwen35_full_gpu_red_team.md)

## Final bounded conclusion

The matrix protocol behaved safely and cleanup reached global zero, but its full-GPU prerequisites admitted no model. The only defensible result is a zero-inference capability stop: 66 of 66 rows stop-gated and 0 of 68 planned inference calls executed. Quality evaluation and production admission remain open work, not negative model results.
