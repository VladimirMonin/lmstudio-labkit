# L3.9e Gemma Family Collapse Decision Record

Status: preliminary lab decision record, based on final trackable `results_summaries` artifacts only.

## Decision

L3.9 is a **lab-only product-shaped comparison**, not a production promotion.

The common evaluation dataset is `blocks_json_medium_chunked`: synthetic/privacy-safe, 100 blocks, 4 chunks, 25 blocks per chunk.

Preliminary decision outcome:

- `gemma4_e2b_q4km` stays in the top-2 as the **fallback/light baseline** and the **fastest successful Blocks JSON candidate**.
- `gemma4_e4b_q4km` stays in the top-2 as the **same-quality but slower/heavier practical candidate**; it is acceptable for sustained comparison/product-integration rehearsal, but not a production default.
- `gemma4_12b_qat` is **load-capable** and **unresolved for product-shaped viability**: the first-pass Blocks JSON run showed ID/business drift, but parse/schema passed `4/4`, so this is an appeal case rather than a final exclusion.
- `gemma4_26b_a4b_qat` remains **capacity/research only** because only an 8k load-only guard passed; no live generation proof exists in this slice.

## Evidence summary

| Model | Load status | Blocks JSON status | ID/business quality | Latency | VRAM/RAM peak | Cleanup/privacy | Role |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `gemma4_e2b_q4km` / `google/gemma-4-e2b` | live load verified at 8k, parallel=1 | passed `4/4` | business `4/4`, ids exact `4/4`, duplicate `0` | total `31.735 s` | `5756 MB` / `22369.617 MB` | cleanup verified, privacy pass | fallback/light baseline; fastest successful Blocks JSON candidate |
| `gemma4_e4b_q4km` / `google/gemma-4-e4b` | live load verified at 8k, parallel=1 | passed `4/4` | business `4/4`, ids exact `4/4`, duplicate `0` | total `65.891 s` | `7310 MB` / `24661.16 MB` | cleanup verified, privacy pass | top-2 practical candidate; same quality as E2B but slower/heavier |
| `gemma4_12b_qat` / `google/gemma-4-12b-qat` | load-only passed at `8192` and `16384`; live Blocks JSON load verified at 8k | parse/schema `4/4`; first-pass product-shaped quality unresolved | business `3/4`, ids exact `3/4`, duplicate `1`, structured errors `1`, failed chunk `0` | total `81.406 s` | `10669 MB` / `28547.059 MB` | cleanup verified, privacy pass | requires ID drift appeal; not a final exclusion |
| `gemma4_26b_a4b_qat` / `google/gemma-4-26b-a4b-qat` | load-only passed at `8192` | not run by guardrail | no live generation evidence | not applicable | `6362 MB` / `31960.055 MB` | cleanup verified, privacy pass | capacity/research only; excluded from live generation pending separate decision |

## Interpretation

The family collapse result is a first-pass comparison, not a final judgment on every model:

- E2B and E4B are the only models in this slice with matching product-shaped Blocks JSON success (`4/4`) and exact cleanup/privacy proof.
- E2B is the faster and lighter successful option.
- E4B does not beat E2B on quality in these artifacts, but it reproduces the same quality envelope and therefore remains worth carrying as the second sustained candidate.
- 12B QAT cannot join sustained comparison yet, but it is **not proven incapable**: the live product-shaped run failed one chunk on duplicate/order/ID fidelity while parse/schema stayed clean. This points to an unresolved prompt/schema/chunking or retry question.
- 26B A4B QAT cannot be promoted beyond capacity probing because this slice intentionally contains no live generation evidence for it.

## Recommended next top-2

Carry forward these two models for sustained series work and product-integration rehearsal:

1. `gemma4_e2b_q4km`
2. `gemma4_e4b_q4km`

Explicit deferrals for now:

- `gemma4_12b_qat`: deferred to L3.10 ID Drift Appeal before any final role decision; it is not promoted, but it is also not finally excluded.
- `gemma4_26b_a4b_qat`: excluded from live generation until a separate generation decision record exists.

## L3.10 appeal requirement

The 12B result needs a dedicated appeal before the family decision can become final for that model:

- failed chunk forensics without raw response storage;
- deterministic reruns on the same dataset/profile;
- stricter ID-contract prompt variants;
- schema hardening with per-position `id` constants where possible;
- chunk-size sensitivity (`25`, `10`, `5` blocks per chunk);
- lab-only retry-on-business-fail recovery measurement.

Until that appeal closes, 12B status is `requires_id_drift_appeal / unresolved_product_shaped_viability`.

## Guardrails remain unchanged

- `production_default=false`
- `wvm_runtime_integration=false`
- `kv_reuse_proven=false`
- `final_user_facing_recommendation=false`
- no `/v1/responses`
- no route matrix

## Cleanup and privacy

All artifact groups used in this decision record show:

- explicit cleanup verification;
- final target loaded instances returned to `0`;
- privacy scan status `pass`;
- `raw_prompt_response_stored=false`.

## Artifact basis

- E2B live Blocks JSON: `experiments/lmstudio/results_summaries/run_l3-9b-gemma-family-blocks-json-e2b-20260707_l3_9b_gemma_family_blocks_json_gemma4_e2b/`
- E4B live Blocks JSON: `experiments/lmstudio/results_summaries/run_l3-9b-gemma-family-blocks-json-e4b-20260707_l3_9b_gemma_family_blocks_json_gemma4_e4b/`
- 12B load-only: `experiments/lmstudio/results_summaries/run_l3-9c-gemma4-12b-qat-load-only-20260707_l3_9c_gemma4_12b_qat_load_only_8k_16k/`
- 12B live Blocks JSON: `experiments/lmstudio/results_summaries/run_l3-9c-gemma-family-blocks-json-12b-qat-20260707_l3_9c_gemma_family_blocks_json_gemma4_12b_qat/`
- 26B load-only: `experiments/lmstudio/results_summaries/run_l3-9d-gemma4-26b-a4b-load-only-20260707_l3_9d_gemma4_26b_a4b_qat_load_only_8k/`
