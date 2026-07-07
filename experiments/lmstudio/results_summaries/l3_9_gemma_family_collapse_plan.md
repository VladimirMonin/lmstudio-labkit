# L3.9 Gemma Family Collapse Plan

Status: preliminary first-pass comparison. E2B/E4B are confirmed working baselines; 12B QAT is unresolved and requires an L3.10 ID Drift Appeal before any final exclusion or promotion.

- L3.9 uses one common product-shaped Blocks JSON dataset: `blocks_json_medium_chunked`.
- Dataset contract: synthetic/privacy-safe, 100 blocks, 4 chunks, 25 blocks per chunk, expected ids `0..99`.
- L3.9b runs `gemma4_e2b_q4km` / `google/gemma-4-e2b` and `gemma4_e4b_q4km` / `google/gemma-4-e4b` through the same sequential `--managed-live` path.
- L3.9c 12B is conditionally allowed on the same sequential `--managed-live` path only after its executable load-only 8k/16k evidence guard passes; the first-pass result is not final because the model passed parse/schema `4/4` but failed one ID/business chunk.
- Trackable E2B Blocks JSON artifact dir: `experiments/lmstudio/results_summaries/run_l3-9b-gemma-family-blocks-json-e2b-20260707_l3_9b_gemma_family_blocks_json_gemma4_e2b/`
- Trackable E4B Blocks JSON artifact dir: `experiments/lmstudio/results_summaries/run_l3-9b-gemma-family-blocks-json-e4b-20260707_l3_9b_gemma_family_blocks_json_gemma4_e4b/`
- Trackable 12B load-only artifact dir: `experiments/lmstudio/results_summaries/run_l3-9c-gemma4-12b-qat-load-only-20260707_l3_9c_gemma4_12b_qat_load_only_8k_16k/`
- Trackable 12B Blocks JSON artifact dir: `experiments/lmstudio/results_summaries/run_l3-9c-gemma-family-blocks-json-12b-qat-20260707_l3_9c_gemma_family_blocks_json_gemma4_12b_qat/`
- Trackable 26B load-only artifact dir: `experiments/lmstudio/results_summaries/run_l3-9d-gemma4-26b-a4b-load-only-20260707_l3_9d_gemma4_26b_a4b_qat_load_only_8k/`
- L3.9d 26B remains load-only/capacity-only and is not allowed on the managed-live generation path.

## Guardrails

- production_default: `false`
- wvm_runtime_integration: `false`
- kv_reuse_proven: `false`
- final_user_facing_recommendation: `false`
- no `/v1/responses`
- no route matrix
- no host application runtime integration

## Expected comparison columns

- model
- load status
- blocks json pass rate
- ids exact pass rate
- duplicate count
- reorder count
- empty count
- reasoning leak count
- median latency (if available)
- p95 latency (if available)
- tokens/sec (if available)
- RAM peak
- VRAM peak
- cleanup
- privacy status
- role

## Observed live/load outcomes

- E2B live Blocks JSON (`l3_9b_gemma_family_blocks_json_gemma4_e2b`): passed `4/4`; business rate `1.0`; ids exact `1.0`; cleanup remaining `0`; privacy `pass`; total latency about `31.735 s`; VRAM peak `5756 MB`; RAM peak `22369.617 MB`.
- E4B live Blocks JSON (`l3_9b_gemma_family_blocks_json_gemma4_e4b`): passed `4/4`; business rate `1.0`; ids exact `1.0`; cleanup remaining `0`; privacy `pass`; total latency about `65.891 s`; VRAM peak `7310 MB`; RAM peak `24661.16 MB`.
- 12B QAT load-only (`l3_9c_gemma4_12b_qat_load_only_8k_16k`): `8192` and `16384` passed; cleanup remaining `0`; privacy `pass`; VRAM peak `10730 MB`; RAM peak `26029.629 MB`.
- 12B QAT live Blocks JSON (`l3_9c_gemma_family_blocks_json_gemma4_12b_qat`): parse/schema `4/4`, business `3/4`, ids exact `3/4`, duplicate id count `1`, structured error count `1`, failed chunk `0`, cleanup remaining `0`, privacy `pass`, total latency about `81.406 s`, VRAM peak `10669 MB`, RAM peak `28547.059 MB`. This is `requires_id_drift_appeal`, not final exclusion.
- 26B A4B QAT load-only (`l3_9d_gemma4_26b_a4b_qat_load_only_8k`): `8192` passed; cleanup remaining `0`; privacy `pass`; VRAM peak `6362 MB`; RAM peak `31960.055 MB`; no live generation run in this plan slice.

## L3.10 follow-up

Do not start E2B/E4B sustained comparison or 26B generation before the 12B appeal closes. L3.10 should check failed chunk forensics, deterministic reruns, prompt hardening, schema hardening with fixed IDs, chunk-size sensitivity, and business-fail retry recovery.
