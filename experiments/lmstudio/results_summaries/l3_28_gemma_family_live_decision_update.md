# L3.28 Gemma Family Live Decision Update

Status: live phased run completed for readiness, 12B/26B load-only, transcript cleanup canaries, structured JSON canary, and vision capability preflight.

This document is sanitized. Raw prompt/response review packs were exported only to a platform temp directory outside the repository and are not committed.

## Run scope

Allowed and executed:

- Phase A readiness/read-only preflight.
- Phase B 12B/26B load-only guards.
- Phase C1 transcript cleanup canary for E2B/E4B/12B.
- Phase C2 tiny transcript cleanup canary for 26B.
- Phase D structured JSON canary for E2B/E4B/12B.
- Phase F vision capability preflight.

Not executed:

- full suite auto-run;
- context screening live;
- image live;
- Qwen/Qwen VL;
- throughput/parallel/session/warmup broad matrices;
- host app integration;
- `/v1/responses` or route matrix.

## Phase A — readiness

Result: pass.

- LM Studio TCP/API reachable.
- `/v1/models` reachable.
- `/api/v1/models` reachable.
- Required Gemma models visible through the compatibility model list.
- Initial loaded count was zero for targeted Gemma models.

## Phase B — 12B/26B load-only

Result: pass.

| model | context | generation called | status | final loaded instances |
|---|---:|---|---|---:|
| google/gemma-4-12b-qat | 8192 | false | pass | 0 |
| google/gemma-4-12b-qat | 16384 | false | pass | 0 |
| google/gemma-4-12b-qat | 32768 | false | pass | 0 |
| google/gemma-4-26b-a4b-qat | 8192 | false | pass | 0 |
| google/gemma-4-26b-a4b-qat | 16384 | false | pass | 0 |

Decision: both 12B and 26B are load-capable for the tested contexts. 26B remains generation-gated to tiny canaries only.

## Phase C1 — transcript cleanup E2B/E4B/12B

Result: pass.

| model | attempts | pass | fail | pass rate | median latency ms | p95 latency ms |
|---|---:|---:|---:|---:|---:|---:|
| google/gemma-4-e2b | 5 | 5 | 0 | 1.0 | 895.713 | 966.604 |
| google/gemma-4-e4b | 5 | 5 | 0 | 1.0 | 957.289 | 996.651 |
| google/gemma-4-12b-qat | 5 | 5 | 0 | 1.0 | 2497.363 | 2847.462 |

Raw review pack: exported local-only outside the repository; raw case count 15.

Decision: E2B, E4B, and 12B pass the bounded transcript cleanup canary and may move to larger transcript-cleanup screening, subject to quality review.

## Phase C2 — 26B tiny transcript cleanup

Result: pass.

| model | attempts | pass | fail | pass rate | median latency ms | p95 latency ms |
|---|---:|---:|---:|---:|---:|---:|
| google/gemma-4-26b-a4b-qat | 3 | 3 | 0 | 1.0 | 3640.424 | 3652.781 |

Raw review pack: exported local-only outside the repository; raw case count 3.

Decision: 26B has tiny generation proof for transcript cleanup only. Do not admit it to broad generation or structured JSON yet.

## Phase D — structured JSON canary

Result: fail.

| model | attempts | pass | fail | pass rate | json parse pass rate | schema pass rate | language pass rate | finish length count |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| google/gemma-4-e2b | 4 | 0 | 4 | 0.0 | 1.0 | 0.5 | 0.0 | 0 |
| google/gemma-4-e4b | 4 | 0 | 4 | 0.0 | 1.0 | 0.5 | 0.0 | 0 |
| google/gemma-4-12b-qat | 4 | 0 | 4 | 0.0 | 0.5 | 1.0 | 0.0 | 2 |

Failure categories:

- `language_mismatch`: 6
- `schema_error`: 4
- `finish_length`: 2

Decision: no Gemma model is admitted to larger structured JSON screening from this canary. Structured JSON needs an L3.28d repair slice before L3.29 admission.

Operational note: the config now uses the supported hardened schema variant `hardened_const`, which is the runtime implementation of prefix-items/per-position const IDs.

## Phase F — vision capability preflight

Result: pass as metadata/config preflight only.

- Planned image cells: 0.
- Image live: not run.
- Current route capability remains unproven.

Decision: `vision_route_status=no_image_route_available_or_unproven`; no Gemma image live is allowed yet.

## Model admission summary

| model | model_admission_status | load_only_status | generation_status | transcript_cleanup_status | structured_simple_status | structured_blocks_status | vision_route_status | allowed_next_phase | blocked_reason |
|---|---|---|---|---|---|---|---|---|---|
| google/gemma-4-e2b | known baseline | not required in B | C1 pass | pass | fail | fail | gated/unproven | transcript cleanup screening only | structured JSON failed |
| google/gemma-4-e4b | quality candidate | not required in B | C1 pass | pass | fail | fail | gated/unproven | transcript cleanup screening only | structured JSON failed |
| google/gemma-4-12b-qat | newly load-capable | pass 8192/16384/32768 | C1 pass | pass | fail | fail | gated/unproven | transcript cleanup screening only | structured JSON failed; 12B blocks hit finish_length |
| google/gemma-4-26b-a4b-qat | newly load-capable | pass 8192/16384 | C2 tiny pass | tiny pass only | not run | not run | gated/unproven | tiny transcript cleanup only | do not broaden before additional approval/evidence |

## L3.29 policy

Admit only transcript-cleanup/simple candidates into the next Gemma text screening:

- E2B: allowed as lightweight baseline/fallback.
- E4B: allowed as quality candidate.
- 12B: allowed for transcript-cleanup screening after load-only pass.
- 26B: allowed only as tiny/controlled transcript-cleanup candidate, not broad matrix by default.

Do not admit structured JSON simple/blocks into L3.29 until an L3.28d repair proves passing structured canaries.

Do not admit image live until route capability is proven.

## Final safety state

- Publication safety for exported snapshots: pass.
- Raw review packs: local-only outside repository.
- Final loaded instances for all targeted Gemma models: 0.
