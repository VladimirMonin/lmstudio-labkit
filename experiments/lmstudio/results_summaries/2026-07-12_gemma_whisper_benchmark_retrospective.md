# Gemma 4 / Whisper postprocessing benchmark retrospective

Status: independent evidence reconciliation. This document does not report new model calls.

Date: 2026-07-12

## Decision

The completed work validates several bounded model and runtime behaviors, but it does not close the original application-shaped postprocessing goal.

The 64-cell, 80-call overlay was a real and complete execution of its frozen M01/M05/L02-L plan. Its `accepted=0` aggregate means only that no call passed every strict transport, schema, target, placeholder-metadata, and task gate simultaneously. It does **not** mean that every response lacked valid JSON or useful text, and it does not mean that all four models failed semantic postprocessing.

The remaining central gap is an end-to-end sequence that repeats one real full Whisper transcript as a stable prefix while processing real early, middle, and late chunks, compares plain text with JSON blocks on identical content, merges the results, and reviews semantic quality. The minimal closure experiment for that gap is 18 calls, defined below.

## Evidence boundary

This retrospective reconciles:

- the original cache/context/parallelism plan and benchmark harness specification;
- the published 16-view private benchmark pack and its explicit semantic limits;
- the frozen 64-cell, 80-call four-model execution bundle, ledgers, scorecards, and sanitized synthesis;
- the focused native structured-output correction and E4B/M05 output-budget follow-ups;
- independent inspection of available owner-only raw outputs and envelopes, without publishing private text or paths.

No audio, model generation, model load, download, network request, or external-runtime mutation was performed for this document. Owner-only evidence is used only for aggregate qualitative findings that can be stated without private content.

## Status vocabulary

- **VERIFIED** — relevant model calls and artifacts support the stated narrow claim.
- **PARTIAL** — only a subset, proxy, model subset, or narrower task was executed.
- **NOT TESTED** — a plan, fixture, or load probe may exist, but the relevant generation experiment does not.
- **INVALID** — the execution may be real, but its design or evidence cannot support the stated interpretation.

## Original-goal gap matrix

| Original goal or inference | Status | Reconciled evidence and limit |
|---|---|---|
| Simple structured JSON across E2B, E4B, 12B QAT, and 26B MoE | **VERIFIED** | Real simple structured calls exist for all four models. The native correction separately records raw JSON, extracted/fenced JSON, exact schema, and quality axes. |
| Medium blocks/array structured JSON | **VERIFIED** | Blocks workloads with order, IDs, missing/duplicate detection, and business validation were executed in earlier bounded matrices. This proves task execution, not broad family admission. |
| Complex nested structured JSON across the full family | **PARTIAL** | E2B/E4B passed a narrow complex canary; 12B reached bounded truncation; broad expansion and the 26B complex lane were not completed. |
| Native strict JSON Schema behavior | **VERIFIED** | The focused 12-call correction used `/v1/responses`, native `json_schema`, `strict=true`, temperature 0, and reasoning off for M01, M05, and L02-L on all four models. |
| Interpret the historical `accepted=0` as no JSON/schema capability | **INVALID** | The 80-call overlay embedded schema instructions in the prompt rather than binding native structured output. It also collapsed transport, schema, exact-target, placeholder metadata, and task quality into one strict verdict. Later native calls demonstrate JSON and schema capability on multiple rows. |
| M01 semantic postprocessing quality | **VERIFIED** | Owner-only output review found that all 12 M01 outputs preserved lexical content, order, meaning, placeholders in `normalized_text`, and Russian language, without added facts, deletion, rearrangement, or translation. M01 strict rejection was therefore largely transport/schema/metadata/exact-target failure, not poor text. |
| M05 postprocessing quality as one family-wide failure | **INVALID** | Quality was model-specific. 26B was the most stable M05 cleanup and 12B was close: both generally removed the ASR repetition while preserving the substantive sequence. E2B understood the task but inconsistently retained portions of the repeated tail. E4B had a severe reproducible runaway/repetition failure. |
| E4B/M05 was merely output-choked by a small budget | **INVALID** | Under the same native schema contract with reasoning disabled, E4B exhausted exact 4,096-, 8,192-, and context-safe 16,384-token budgets. Each longer output retained the previous output prefix and continued malformed repetition. |
| Placeholder preservation in output text | **PARTIAL** | In many rejected M01/M05 rows, placeholders remained physically intact in `normalized_text` while the separate `preserved_placeholders` metadata array was incomplete or incorrect. Text corruption and metadata-contract failure must be reported separately. |
| L02-L proves complete long-record retention | **INVALID** | L02-L produced summaries and model-reported retention counts, not an independently aligned source-unit-to-output map. The 12B `428/428` result is a model self-report under a structural contract; it is not proof that every source detail survived. |
| L02-L as a long-context structural probe | **VERIFIED** | A 428-unit large-prefix workload was executed in a seven-call cold/loaded/changing-suffix/exact-repeat sequence for each model. It supports bounded structural and timing observations only. |
| Short real microphone-derived transcript views | **PARTIAL** | The public pack contains ten microphone views, but the final four-model overlay used only M01 and M05. Inputs were sanitized transcript text, not audio. |
| Long real recording/video postprocessing | **PARTIAL** | The overlay used L02-L as a large structural-retention view. It did not normalize and merge real early/middle/late Whisper chunks. M05 was a much shorter one-shot normalization task. |
| Audio-grounded Whisper quality, WER/CER, VAD, diarization, timestamps | **NOT TESTED** | The benchmark pack contains no audio and explicitly establishes no speech-accuracy ground truth. Claims about acoustic correctness would be invalid. |
| 8,192-token generation | **VERIFIED** | Multiple real 8k generation series exist, including the four-model overlay and earlier bounded matrices. |
| 16,384-token generation | **VERIFIED** | Real 16k calls exist across context, loaded-session, and P1/P2/P4 lanes. |
| Exact 32,768-token generation | **NOT TESTED** | Exact 32k load/capability probes and prepared plans are not a 32k generation matrix. The final overlay used 28,672, not 32,768. |
| 28,672-token practical near-32k behavior | **PARTIAL** | The overlay and native correction contain real 28,672-context calls. This is useful near-32k evidence but neither exact 32k admission nor proof that payloads filled the full context. |
| Different output budgets | **VERIFIED** (bounded) | Real experiments used several bounded caps, including 512, 1,024, 2,048, 4,096, 8,192, and 16,384. There was no complete budget-by-model-by-task cross-product. |
| Reasoning off/on effects | **PARTIAL** | Paired reasoning experiments and a reasoning-off native correction exist, but reasoning was not crossed comprehensively with M01/M05/L02-L, all context tiers, loaded processing, and P1/P2/P4. |
| Full context followed by sequential processing of real chunks | **PARTIAL** | The overlay verified a stable large prefix, changing suffixes, and exact repeats. Its suffixes were structural probes, not real application chunks, and no end-to-end merged transcript was produced. |
| Cold versus compatible loaded-session timing | **VERIFIED** as a timing signal | The four-model synthesis records first-to-follow-up latency ratios of 2.03–3.79× for the seven-call sequence. Quality and mechanism remain separate questions. |
| Physical KV-cache reuse | **INVALID / unproven** | No documented request-linked cache-hit flag, reused-token count, avoided-prefill trace, or physical KV telemetry was captured. Loaded-session speedup is not proof of physical reuse. |
| Stable prefix with changing suffixes | **VERIFIED** | The frozen plan binds stable-prefix and suffix digests for the loaded sequence on all four models. |
| Exact-repeat reproducibility | **VERIFIED** with a warning | Exact-repeat controls ran for all four models. The first repeat differed from its predecessor while the second repeat matched the first repeat; byte identity cannot be assumed. Semantic repeat stability on real chunks was not established. |
| P1/P2/P4 concurrent execution | **VERIFIED** | Each model executed P1, P2, and P4 M05 cells against one loaded instance. These are measured throughput signals. |
| Production parallelism recommendation from the overlay | **INVALID** | The corresponding strict M05 rows were rejected, so timing alone cannot select a production concurrency policy. |
| JSON blocks and plain-text cleanup as separate workloads | **VERIFIED** | Both workload classes were executed in different bounded series. |
| Controlled JSON-blocks versus plain-text A/B | **NOT TESTED** | No four-model experiment held source text, full prefix, chunk boundaries, semantics, context, output budget, reasoning, and execution order constant while changing only plain text versus JSON blocks. |
| Translation quality | **NOT TESTED** | A translation fixture and prompt exist, but no relevant Gemma live-result artifact closes this goal. Fixture presence is not execution evidence. |
| At least three measured repeats plus a separate warmup for every matrix cell | **PARTIAL** | Some session and repeat lanes contain warm/repeat controls, but many context/task cells are one-shot. The original repeatability rule was not applied uniformly. |
| Full application-shaped real-video chunk pipeline | **NOT TESTED** | No published run combines a real full Whisper transcript, real early/middle/late chunks, identical plain/JSON boundaries, sequential processing, exact repeat, merge, and semantic review. |

## Corrected model interpretation

### E2B

E2B is the strongest raw-JSON/schema-following baseline and the lowest-latency candidate in the bounded evidence. Its M01 text is semantically sound. On M05 it is inconsistent: some outputs remove the repeated ASR tail correctly, while others retain a variable amount. It is suitable for the first application-shaped rehearsal, not production-admitted.

### E4B

E4B's M01 text is semantically sound, but M05 exposes a reproducible runaway failure that survives disabled reasoning and 4k/8k/16k output budgets. Existing evidence does not establish a quality advantage over E2B, so E4B is excluded from the minimal closure plan unless a new explicit quality hypothesis justifies it.

### 12B QAT

12B has the strongest bounded structural result and generally good M05 cleanup, close to 26B, with useful punctuation and paragraphing. Its raw transport/schema/ID discipline is less reliable. It is the justified quality challenger for an application-shaped rehearsal.

### 26B MoE

26B produced the most stable M05 text cleanup in the inspected outputs, but it is slower, its exact-schema behavior is inconsistent, and L02-L was one unit short in the focused correction. Existing evidence does not prove that its M05 advantage survives the real chunk pipeline or justifies its cost. It remains a conditional follow-up, not part of the first 18 calls.

## Minimal 18-call closure plan

The closure plan deliberately tests only the two currently non-dominated candidates:

- E2B as the speed/raw-JSON baseline;
- 12B QAT as the structural and text-quality challenger.

E4B is excluded because of the established M05 runaway. 26B is deferred until E2B and 12B fail the product-shaped gate or a specific quality hypothesis justifies its additional cost.

### Asset A: one real long recording transcript

Use one owner-only real sanitized Whisper transcript with preserved block boundaries. Select three representative chunks from the same recording:

- early;
- middle;
- late.

The set must include difficult disfluency/noise and critical names, numbers, commands, dates, URLs, or placeholders where available. The full transcript is repeated byte-identically as the stable prefix for every long request.

For each model, execute eight long-record calls:

| Call | Lane | Suffix |
|---:|---|---|
| 1 | plain text | early chunk; cold/warm-up observation |
| 2 | plain text | middle chunk |
| 3 | plain text | late chunk |
| 4 | plain text | exact repeat of late chunk |
| 5 | JSON blocks | early blocks with identical semantic boundary |
| 6 | JSON blocks | middle blocks with identical semantic boundary |
| 7 | JSON blocks | late blocks with identical semantic boundary |
| 8 | JSON blocks | exact repeat of late blocks |

This is 16 calls across two models. Process each model in one compatible loaded-instance sequence, then unload it and require a zero-loaded read-back. Do not describe the sequence as a stateful conversation unless the transport actually uses a documented continuation mechanism.

### Asset B: one real short microphone transcript

Execute one production-shaped short microphone postprocessing call per model, adding two calls. Cache reuse is not a goal for this short case.

Total: `8 long calls × 2 models + 1 microphone call × 2 models = 18 calls`.

### Required quality gates

For every unique chunk and microphone result:

- preserve 100% of manually identified critical facts;
- preserve names, numbers, dates, URLs, commands, placeholders, and source language;
- add zero unsupported facts;
- produce non-empty output without runaway repetition or output-budget exhaustion;
- record useful corrections and harmful edits separately;
- detect boundary loss and overlap duplication;
- require semantic, not necessarily byte-identical, stability for exact repeats.

For the JSON lane:

- raw JSON parses;
- exact schema passes;
- block IDs and order match exactly;
- missing, duplicate, and extra IDs are zero;
- fallback-to-original and retries are reported as distinct outcomes;
- merging early/middle/late outputs loses no blocks.

For the plain-text lane:

- merged output has no boundary omission or overlap duplication;
- every critical fact remains present;
- useful Whisper corrections and introduced errors are counted.

### Timing and cache claim boundary

Record input/output tokens, TTFT when available, prompt-processing time when available, total latency, prefix/suffix digests, and exact loaded-instance identity. Record provider cache telemetry only if the endpoint actually returns it.

A faster follow-up is a loaded-prefix timing signal. Physical KV reuse remains unproven unless documented request-linked telemetry or a lower-level trace directly establishes reuse. Quality must not degrade in exchange for a timing improvement.

## Evidence sources

Primary public sources:

- `docs/lmstudio_managed_backend_docs/07_lmstudio_cache_parallel_benchmark_plan.md`
- `docs/lmstudio_managed_backend_docs/08_benchmark_harness_technical_spec.md`
- `experiments/lmstudio/results_summaries/gemma_four_model_context_session_parallel_plan.md`
- `experiments/lmstudio/private_benchmark_pack/v1/README.md`
- `experiments/lmstudio/four_model_overlay/v1/README.md`
- `experiments/lmstudio/four_model_overlay/v1/execution_bundle/frozen-plan.json`
- `experiments/lmstudio/results_summaries/2026-07-12_four_model_real_asset_benchmark_synthesis.md`
- `experiments/lmstudio/results_summaries/2026-07-12_four_model_real_asset_benchmark_synthesis.json`
- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_native_structured_output_correction.md`
- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_native_structured_output_correction.json`
- `experiments/lmstudio/results_summaries/l3_31_l3_36_gemma_admission_matrix.md`

## Non-claims

This retrospective does not claim:

- end-to-end production admission for any model;
- exact 32,768-token generation coverage;
- translation coverage;
- audio-grounded Whisper accuracy;
- complete long-record detail retention from L02-L;
- a controlled plain-text-versus-JSON result;
- a completed real-video chunk-and-merge pipeline;
- physical KV-cache reuse;
- a production parallelism recommendation;
- any new live execution.
