# Qwen 3.5 full-GPU matrix manual review

Date: 2026-07-14

Status: capability stop. This report does not establish full-GPU eligibility or model quality for either candidate.

Machine-readable companion: `2026-07-14_qwen35_full_gpu_manual_review.json`.

## Decision

The reviewed evidence is complete for the bounded canary and empty for inference. The final candidate matrix contains 66 rows accounting for 68 planned inference calls, but Stage 4 authorized 0 models, 0 rows, and 0 calls. The canonical canary ledger reconciles all 66 rows as stop-gated and contains 0 inference attempts, 0 raw inference responses, and 0 successful cells.

This is a runtime-capability result, not a transport, schema, semantic-quality, cache, concurrency, repeatability, or vision-quality result.

## Evidence boundary

The owner-only evidence index lists 16 payload files. All 16 files matched their recorded sizes, SHA-256 digests, and owner-only file modes; the evidence root had the required owner-only directory mode. The index itself was also reviewed, for 17 files read in total.

The canonical server-log delta exactly matched the content-addressed slice beginning at the recorded pre-run byte offset. Events outside that slice were treated as foreign or unattributed to this canary and were not used to support admission or quality claims.

The executed canary snapshot and the current final manifest have different content hashes because the runtime-authority implementation was repaired after the canary. No later canary was authorized: the installed runtime contract cannot explicitly attest both `cpu_fallback=false` and `resource_guardrail_downgrade=false`. The later snapshot therefore remains a reviewed zero-call capability stop rather than retroactively changing the executed evidence.

## Exact accounting

| Scope | Planned rows | Planned calls | Actual inference calls | Stop-gated rows |
|---|---:|---:|---:|---:|
| Lifecycle strict canary | 2 | 2 | 0 | 2 |
| Structured text | 18 | 18 | 0 | 18 |
| Context and cache/session | 16 | 16 | 0 | 16 |
| Concurrency | 4 | 6 | 0 | 4 |
| Strict structured vision | 26 | 26 | 0 | 26 |
| **Total** | **66** | **68** | **0** | **66** |

The concurrency lane has four rows but six planned calls because each of the two parallel-pair rows accounts for two calls.

Stop reasons across the row ledger:

- 1 row: `full_gpu_materialization_not_proven`;
- 35 rows: `base_full_gpu_not_proven`;
- 30 rows: `execution_identity_unavailable`.

## Per-model runtime review

### Qwen 3.5 4B

The exact Q4_K_M artifact and multimodal projector were immutably pinned. One lifecycle load was reserved before execution and completed successfully through the CLI in 25.44 seconds. The requested shape was maximum GPU placement, context 8192, and parallelism 1.

The native runtime then exposed one exact model instance with the expected selected variant, context 8192, parallelism 1, and GPU KV placement. The server log also exposed an immutable instance reference for the materialized instance.

Admission still failed closed. The canonical capture had no authoritative `gpu_layers` or `total_layers`, no authoritative runtime-telemetry record, and no explicit evidence that CPU fallback, resource downgrade, and memory thrashing were false. Requested maximum-GPU placement and successful materialization are not execution proof. All 36 rows for this model were therefore stop-gated before inference.

### Qwen 3.5 9B MTP

No immutable device-bound local artifact identity was available for the exact candidate. The model had 0 load attempts, 0 materialized instances, and 0 inference calls. All 30 rows were stop-gated before model operation.

## Dimension verdicts

| Dimension | Executed denominator | Verdict |
|---|---:|---|
| Lifecycle load transport | 1 | 1 successful CLI load; admission still failed |
| Inference transport | 0 | Not evaluated |
| Raw response parse | 0 | Not evaluated |
| JSON Schema | 0 | Not evaluated |
| Business validation | 0 | Not evaluated |
| Semantic quality | 0 | Not evaluated |
| Repeatability | 0 | Not evaluated |
| Cache/session behavior | 0 | Not evaluated |
| Concurrency behavior | 0 | Not evaluated |
| Vision grounding against pixels | 0 | Not applicable: no vision response exists |

The vision fixtures were planned but never sent. There are no raw vision responses to compare with PNG pixels, so validators and direct pixel review both have a true zero-call denominator.

## Runtime-log attribution

Inside the exact canary window, the log shows catalog and loaded-state reads, one 4B load, model and projector materialization, one immutable-instance lookup, no inference request, one unload request, and final loaded-state reads.

The same server-log file also contains earlier Qwen loads, an earlier inference attempt ending in a Vulkan device-loss error, other loads, and failed guest-client operations. Those events are outside the pinned canary delta. They remain separate historical runtime evidence and are not attributed to this run.

## Cleanup

Dual-source loaded-state captures passed at initial state, after the 4B load group, and at matrix-final state: CLI loaded total 0 and native API loaded total 0 in every capture. A fresh read-only review-time check also returned zero from both sources.

## Conclusion

The runner and evidence protocol behaved safely: exact evidence was preserved, all rows reconciled, no disallowed retry occurred, and cleanup reached global zero. The result does not admit either model and supports no quality ranking or production recommendation. Full matrix execution remains 0 of 68 planned inference calls.
