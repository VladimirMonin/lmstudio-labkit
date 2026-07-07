# L3.10g — Gemma 12B QAT ID Drift Appeal Decision Record

Date: 2026-07-07

Branch: `next/modular-backend-lab`

Scope: lab-only LM Studio structured-output appeal for `google/gemma-4-12b-qat`.

## Decision

12B QAT is **conditionally viable**, not excluded.

The original L3.9 failure was real and deterministic under the baseline
prompt/schema/chunk setup, but it was not proof that 12B cannot hold the Blocks
JSON contract. L3.10 showed two viable containment paths:

- **Schema hardening** with `structured_schema_variant=per_position_id_const`
  passed `4/4`.
- **One-shot sanitized business-fail retry** recovered the deterministic baseline
  ID drift and passed `4/4`.

12B QAT must **not** be promoted as a loose baseline-schema production default.
It may enter a later sustained comparison only under a hardened contract:

1. preferred: `structured_schema_variant=per_position_id_const`;
2. optional fallback: one-shot business-fail retry with sanitized numeric
   violation summary;
3. artifacts remain sanitized and cleanup must prove `final_loaded_instances=0`.

Guardrail status remains unchanged:

- `production_default=false`
- `wvm_runtime_integration=false`
- `kv_reuse_proven=false`
- `final_user_facing_recommendation=false`

## Evidence summary

| Step | Variant | Result | Interpretation |
|---|---:|---:|---|
| L3.10a | baseline forensic rerun, 25 blocks/chunk | business `3/4`, ids exact `3/4`, duplicate `1`, failed chunk `[0]` | Reproduced the L3.9 ID drift without storing raw response text. |
| L3.10b | 3 deterministic baseline reruns | same failed chunk, same response hash, same missing/duplicate IDs | Failure is deterministic under current baseline setup. |
| L3.10c | strict ID prompt | business `2/4`, ids exact `2/4`, finish length `2` | Prompt hardening alone worsened completion stability. |
| L3.10c | ultra-minimal transform prompt | business `2/4`, ids exact `2/4`, finish length `2` | Prompt simplification alone did not fix ID fidelity. |
| L3.10d | per-position ID-const schema, 25 blocks/chunk | business `4/4`, ids exact `4/4`, duplicate `0` | Physical schema constraints can make 12B hold the contract. |
| L3.10e | baseline schema, 25 blocks/chunk | business `3/4`, ids exact `3/4`, duplicate `1` | Reconfirmed baseline drift. |
| L3.10e | baseline schema, 10 blocks/chunk | business `6/10`, ids exact `6/10`, duplicate `2` | Smaller chunks did not solve the issue; baseline schema remains unstable. |
| L3.10e | baseline schema, 5 blocks/chunk | business `15/20`, ids exact `15/20`, duplicate `1` | Chunk pressure alone is not the primary fix. |
| L3.10f | baseline schema + one-shot business retry | business `4/4`, ids exact `4/4`, retry attempts `1`, recovered `1` | Retry can recover the deterministic baseline ID drift without raw response storage. |

All controlled live runs in this appeal recorded `privacy_scan.status=pass`,
`violation_count=0`, and `final_loaded_instances=0`.

## Deterministic baseline failure

The failing baseline chunk was `batch_0001_chunk_0000`.

Sanitized ID diagnostics:

- expected IDs: `0..24`
- returned IDs: `[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,11,22,23,24]`
- duplicate IDs: `[11]`
- missing IDs: `[21]`
- extra IDs: `[]`
- failed position: `21`, expected `21`, returned `11`
- repeated response hash across L3.10a/L3.10b baseline reruns:
  `sha256:aed190389f285e69e5a4c53488f46c54f888d248fbfb79e97d7addb268c21c6b`

This proves a deterministic baseline contract failure, not random noise.

## Prompt hardening outcome

Prompt-only hardening was not sufficient.

Both L3.10c variants failed by `finish_reason=length` on two chunks:

- `strict_id_contract`: business `2/4`, failed chunks `[2,3]`
- `ultra_minimal_transform`: business `2/4`, failed chunks `[0,3]`

Therefore, stronger prose alone is not the recommended recovery path for 12B.

## Schema hardening outcome

L3.10d used a lab-only schema variant:

- `structured_schema_variant=per_position_id_const`

Outcome:

- business `4/4`
- ids exact `4/4`
- duplicate `0`
- failed chunks `[]`
- cleanup `final_loaded_instances=0`
- privacy pass

This is the strongest evidence that 12B can satisfy the contract when the schema
physically prevents ID drift.

## Chunk-size sensitivity outcome

L3.10e isolated chunk size while keeping baseline prompt and baseline schema.

| Chunk size | Chunks | Business | IDs exact | Failed chunks | Notes |
|---:|---:|---:|---:|---|---|
| 25 | 4 | `3/4` | `3/4` | `[0]` | Same deterministic ID drift pattern. |
| 10 | 10 | `6/10` | `6/10` | `[2,3,4,5]` | Missing/duplicate IDs and shortened returned arrays. |
| 5 | 20 | `15/20` | `15/20` | `[0,1,5,15,18]` | Smaller chunks still failed under loose schema. |

Conclusion: chunk pressure is not the primary root cause. The loose baseline schema
allows 12B to drift even on small chunks.

## Retry outcome

L3.10f enabled one retry only when the first attempt passed JSON parse/schema but
failed business validation. The retry prompt used only sanitized numeric/enum
diagnostics and did not include prior raw response text.

Outcome:

- business `4/4`
- ids exact `4/4`
- retry attempts `1`
- retry recovered `1`
- retry failed `0`
- failed chunks `[]`
- cleanup `final_loaded_instances=0`
- privacy pass

The retry recovery is recorded in the L3.10f aggregate artifacts:
`retry_attempt_count=1`, `retry_recovered_count=1`, `retry_failed_count=0`, and
`business_pass_count=4`.

## Final 12B role

12B QAT should be classified as:

> **Conditionally viable with stricter schema and/or retry recovery; unsafe as a
> loose baseline-schema default for Blocks JSON ID fidelity.**

This closes the L3.10 appeal and changes the L3.9 preliminary conclusion:

- E2B/E4B remain confirmed working baselines.
- 12B is no longer merely `unresolved`; it is conditionally viable under hardening.
- 26B remains capacity/research only until separate generation proof exists.

## Recommended next actions

1. If sustained model comparison resumes, include 12B only under a hardened
   profile:
   - `structured_schema_variant=per_position_id_const`; or
   - baseline schema plus `business_failure_retry_limit=1` as a recovery profile.
2. Do not make 12B a production default without a sustained hardened-profile run.
3. Keep `/v1/responses`, route matrix, 26B generation, and WVM runtime integration
   out of scope until sustained lab evidence exists.

## Artifact index

- `run_l3-10a-gemma4-12b-qat-id-forensics-20260707_l3_10a_gemma4_12b_qat_id_forensics/`
- `run_l3-10b-gemma4-12b-qat-deterministic-rerun-1-20260707_l3_10a_gemma4_12b_qat_id_forensics/`
- `run_l3-10b-gemma4-12b-qat-deterministic-rerun-2-20260707_l3_10a_gemma4_12b_qat_id_forensics/`
- `run_l3-10b-gemma4-12b-qat-deterministic-rerun-3-20260707_l3_10a_gemma4_12b_qat_id_forensics/`
- `run_l3-10c-gemma4-12b-qat-prompt-strict-id-contract-20260707_l3_10c_gemma4_12b_qat_prompt_strict_id_contract/`
- `run_l3-10c-gemma4-12b-qat-prompt-ultra-minimal-transform-20260707_l3_10c_gemma4_12b_qat_prompt_ultra_minimal_transform/`
- `run_l3-10d-gemma4-12b-qat-schema-per-position-id-const-20260707_l3_10d_gemma4_12b_qat_schema_per_position_id_const/`
- `run_l3-10e-gemma4-12b-qat-chunk-size-25-20260707_l3_10e_gemma4_12b_qat_chunk_size_25/`
- `run_l3-10e-gemma4-12b-qat-chunk-size-10-20260707_l3_10e_gemma4_12b_qat_chunk_size_10/`
- `run_l3-10e-gemma4-12b-qat-chunk-size-5-20260707_l3_10e_gemma4_12b_qat_chunk_size_5/`
- `run_l3-10f-gemma4-12b-qat-business-retry-20260707_l3_10f_gemma4_12b_qat_business_retry/`
