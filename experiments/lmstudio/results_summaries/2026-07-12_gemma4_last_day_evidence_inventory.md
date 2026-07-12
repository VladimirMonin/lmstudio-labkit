# Gemma 4 last-day evidence inventory

Date: 2026-07-12

Status: read-only evidence reconciliation. No model was loaded and no generation was performed for this report.

## Decision

The last-day evidence is substantial but heterogeneous. It contains complete model results, negative model results, pre-generation configuration failures, superseded retries, and unexecuted plan rows. These categories must not be collapsed into one success rate.

The strongest closed sets are:

- the canonical 64-cell / 80-call prompt-embedded overlay;
- the 12-call native structured-output correction plus two E4B/M05 boundary calls;
- 20 cold long-plain repeats;
- 60 native structured-output repeats;
- 80 successful repaired P4 requests using a compact generic schema.

The largest unresolved execution gap is the frozen 54-call long-representation plan: 27 phase calls are retained, while 27 planned calls have no execution artifact. The later repeat-5 study closes only one long plain early-chunk cell, not the full plain/JSON/timestamped representation matrix.

Machine-readable companion: `2026-07-12_gemma4_last_day_evidence_inventory.json`.

## Classification rules

- `VALID_MODEL_RESULT`: generation reached the model and enough evidence survives for a bounded conclusion. A quality, schema, semantic, or length failure may still be a valid result.
- `CONFIGURATION_FAILURE`: load, context, timeout, request grammar, or request configuration prevented useful measured generation.
- `RUNNER_FAILURE`: supervision or runner behavior failed independently of the model.
- `PREFLIGHT_ONLY`: readiness, token-fit, load, or cleanup evidence exists without a measured generation.
- `SUPERSEDED_RESULT`: a retained real result was replaced as current authority by a corrected or canonical run.
- `NOT_TESTED`: no retained generation evidence exists for the relevant cell.

No retained cell required `RUNNER_FAILURE` as its final classification. A watchdog interruption occurred during the long-representation phase, but later call artifacts continued through the retained partial sequence. It is process evidence, not evidence that a completed cell failed.

## Chronology and call inventory

### 0. Frozen plans, token fit, load configurations, and process evidence

Repository evidence:

- `experiments/lmstudio/four_model_overlay/v1/execution_bundle/frozen-plan.json`
- `experiments/lmstudio/four_model_overlay/v1/execution_bundle/load-configs/`
- `experiments/lmstudio/source_shaped_rehearsal/v1/manifest.json`

Private artifact class inspected: four tokenizer-capture records, the long-source freeze, representation assets, a manual rubric, a 20-row repeat progress ledger, and a watchdog marker from the partial long-representation execution.

| Run/cell group | Calls | Classification | Raw outputs | Evidence interpretation |
|---|---:|---|---:|---|
| Four-model tokenizer and load-contract preparation | 0 | `PREFLIGHT_ONLY` | 0 | Token-fit and load configuration evidence prepares execution but is not generation evidence. |
| Source-shaped rehearsal bundle and manual rubric | 0 | `PREFLIGHT_ONLY` | 0 | The bundle was prepared, but no rehearsal result exists in this evidence window. |

Fact: load configuration, token fit, process supervision, and frozen plans establish provenance and readiness boundaries. They cannot upgrade an unexecuted row into a model result.

### 1. Prompt-embedded four-model overlay

Repository evidence:

- `experiments/lmstudio/four_model_overlay/v1/execution_bundle/frozen-plan.json`
- `experiments/lmstudio/results_summaries/2026-07-12_four_model_real_asset_benchmark_synthesis.json`

Private artifact class inspected: owner-only call ledgers, scorecards, response envelopes, and raw text files.

| Run/cell group | Calls | Classification | Raw outputs | Evidence interpretation |
|---|---:|---|---:|---|
| Initial E2B execution | 20 | `SUPERSEDED_RESULT` | 20 | Complete retained run, superseded by the canonical task-budget slice. |
| E2B reasoning-off execution | 20 | `SUPERSEDED_RESULT` | 20 | Complete retained run, not the slice used by the final synthesis. |
| Canonical E2B slice | 20 | `VALID_MODEL_RESULT` | 20 | All frozen cells executed; 0/20 strict acceptance does not erase transport, structure, and timing evidence. |
| Canonical E4B slice | 20 | `VALID_MODEL_RESULT` | 20 | Complete slice; 0/20 strict acceptance. |
| Canonical 12B QAT slice | 20 | `VALID_MODEL_RESULT` | 20 | Complete slice; 0/20 strict acceptance. |
| Canonical 26B MoE slice | 20 | `VALID_MODEL_RESULT` | 20 | Complete slice; 0/20 strict acceptance. |

Fact: the authoritative historical denominator is 64 cells and 80 canonical calls, not 120. The additional 40 E2B calls are retained superseded executions and must not be folded into the canonical denominator.

Interpretation: strict rejection means the complete end-to-end contract failed. It does not mean that no JSON, structure, useful text, or timing evidence exists.

### 2. Native structured-output correction and E4B boundary work

Repository evidence:

- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_native_structured_output_correction.json`
- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_native_structured_output_correction.md`

Private artifact class inspected: raw text and full response envelopes for each model/view and both larger-budget boundary calls.

| Run/cell group | Calls | Classification | Raw outputs | Evidence interpretation |
|---|---:|---|---:|---|
| Earlier four-model × three-view transport pass | 12 | `SUPERSEDED_RESULT` | 12 | Retained, but superseded by the Responses API native-schema run. |
| Authoritative native M01/M05/L02-L matrix | 12 | `VALID_MODEL_RESULT` | 12 | One measured call per model/view with strict native schema and reasoning disabled. |
| E4B/M05 8,192-output boundary | 1 | `VALID_MODEL_RESULT` | 1 | Exact budget exhaustion with malformed continued generation is a valid negative result. |
| E4B/M05 16,384-output boundary | 1 | `VALID_MODEL_RESULT` | 1 | Context-safe exact exhaustion confirms the same runaway continuation. |

Fact: the authoritative native matrix is 12 calls. The two larger-budget E4B calls are diagnostic follow-ups. The earlier 12-call transport set is retained but superseded.

### 3. Long-transcript representation matrix

Repository evidence:

- `experiments/lmstudio/results_summaries/2026-07-12_gemma_whisper_benchmark_retrospective.md`

Private artifact class inspected: a frozen 54-call plan, source freeze, plain/JSON-block/timestamped representation assets, three canary envelopes, 27 phase envelopes, a watchdog marker, and manual review material.

| Run/cell group | Calls | Classification | Raw outputs | Evidence interpretation |
|---|---:|---|---:|---|
| One-call canaries | 3 | `SUPERSEDED_RESULT` | 3 | Followed by retained phase execution. |
| Partial phase sequence, calls c10-c36 | 27 | `VALID_MODEL_RESULT` | 27 | Per-call envelopes survive. |
| Remaining rows of frozen 54-call plan | 27 | `NOT_TESTED` | 0 | No per-call execution artifacts survive because those rows were not executed. |

Representation status:

- Plain text: executed in the partial matrix and later in one repeat-5 cell.
- JSON blocks: executed in the partial matrix, but not repeated five times under the later closure.
- Timestamped paragraphs: executed in the partial matrix; one earlier boundary-crossing result remains a warning.
- Controlled repeat-5 plain-versus-JSON A/B on identical content: `NOT_TESTED`.

Interpretation: this evidence supports representation-sensitive observations, but it does not close the full 54-call plan or a complete early/middle/late merged transcript pipeline.

### 4. Long plain repeat-5

Repository evidence:

- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_whisper_structured_parallel_statistics.json`

Private artifact class inspected: 20 per-call envelopes and a 20-row process progress ledger.

| Run/cell group | Calls | Classification | Raw outputs | Evidence interpretation |
|---|---:|---|---:|---|
| One long plain early-chunk cell, five cold repeats per model | 20 | `VALID_MODEL_RESULT` | 20 | All subprocess rows returned success and all envelopes survive. |

Fact: every model produced one byte-stable output across its five repeats. This establishes deterministic behavior for this one cell, not family-wide repeatability across representations and chunk positions.

### 5. Native structured-output repeat-5

Repository evidence:

- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_whisper_structured_parallel_statistics.json`

Private artifact class inspected: five complete 12-call reports, 60 response envelopes, and 60 raw text extracts.

| Run/cell group | Calls | Classification | Raw outputs | Evidence interpretation |
|---|---:|---|---:|---|
| Four models × M01/M05/L02-L × five repeats | 60 | `VALID_MODEL_RESULT` | 60 | Every model/task/repeat has retained evidence. Negative schema, retention, and length outcomes remain valid model results. |

Fact: E4B/M05 exhausted 4,096 output tokens in 5/5. Other deterministic failures include exact-schema misses and incomplete L02-L retention. These are model-result classifications, not runner failures.

### 6. P2 and GPU placement

Repository evidence:

- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_whisper_structured_parallel_statistics.json`

Private artifact class inspected: batch summaries, request metrics, structured-error ledgers, system samples, and one GPU load read-back. These probes explicitly disabled raw prompt/response storage.

| Run/cell group | Calls or attempts | Classification | Raw outputs | Evidence interpretation |
|---|---:|---|---:|---|
| E2B P2 warmup plus measured requests | 5 | `VALID_MODEL_RESULT` | 0 | Four measured requests passed. |
| E4B P2 warmup plus measured requests | 5 | `VALID_MODEL_RESULT` | 0 | Four measured requests passed. |
| Three 12B managed-runner attempts ending during warmup | 3 | `CONFIGURATION_FAILURE` | 0 | No measured requests; context verification and inherited timeout configuration blocked the measured phase. |
| 12B P2 at 1,875 output tokens | 2 | `VALID_MODEL_RESULT` | 0 | Both calls reached generation and hit the output limit. |
| 12B P2 at 4,096 output tokens | 2 | `VALID_MODEL_RESULT` | 0 | Both calls passed. |
| 26B P2 at 4,096 output tokens | 2 | `VALID_MODEL_RESULT` | 0 | Both calls passed. |
| 12B P2 with gpu-max placement | 2 | `VALID_MODEL_RESULT` | 0 | Both calls passed; no timing or reported-footprint benefit was observed. |

GPU placement fact: the available load text reports the same broad footprint class for automatic and gpu-max placement.

GPU placement gap: no reliable offloaded-layer read-back or complete physical VRAM telemetry exists. Therefore layer placement remains `NOT_TESTED`, even though the P2 generation comparison is valid.

### 7. P4 diagnosis and repair

Repository evidence:

- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_whisper_structured_parallel_statistics.json`

Private artifact class inspected: positional-schema batch summaries and request metrics, context-reduction control results, and 20 compact-schema repaired batch artifacts.

| Run/cell group | Calls or attempts | Classification | Raw outputs | Evidence interpretation |
|---|---:|---|---:|---|
| Positional-schema measured P4 requests | 16 | `CONFIGURATION_FAILURE` | 0 | HTTP 400 before useful generation on four models. |
| Positional-schema sequential warmups | 4 | `VALID_MODEL_RESULT` | 0 | Warmup generation passed, helping isolate the measured failure. |
| First 26B P4 attempt ending before measured requests | 1 | `CONFIGURATION_FAILURE` | 0 | Retained summary contains no measured request. |
| E2B context-reduction warmup | 1 | `VALID_MODEL_RESULT` | 0 | Sequential warmup completed. |
| E2B context-reduction measured P4 requests | 4 | `CONFIGURATION_FAILURE` | 0 | Lower context did not repair the positional grammar failure. |
| Compact generic-schema repaired P4 | 80 | `VALID_MODEL_RESULT` | 0 | Five four-request batches per model: 80/80 HTTP 200, stop, zero reasoning, and exact IDs/order. |

Fact: compact generic grammar plus post-generation exact-ID validation repaired the bounded P4 lane.

Interpretation: the failed positional lane is a configuration failure, not evidence that the models or runtime cannot execute any P4 workload.

Hypothesis: compact generic schemas reduce grammar pressure enough to make this bounded P4 shape viable. The evidence does not establish P4 for arbitrary schema complexity, context size, or hardware placement.

## Denominator reconciliation

| Evidence set | Correct denominator | Do not mix in |
|---|---:|---|
| Historical canonical overlay | 64 cells / 80 calls | 40 superseded E2B calls |
| Native correction | 12 matrix calls | 12 superseded transport calls and two boundary diagnostics |
| Long representation plan | 54 planned; 27 retained phase calls | three canaries and 27 unexecuted plan rows |
| Long plain repeat-5 | 20 calls | partial representation-matrix calls |
| Structured repeat-5 | 60 calls | the earlier one-shot native correction |
| Repaired P4 | 20 batches / 80 calls | positional-schema failures, warmups, and controls |

These experiments answer different questions. Adding them into one acceptance percentage would be mathematically tidy and scientifically wrong.

## Raw-output availability

Physically retained call-level output is available for 256 call executions:

- 120 prompt-embedded overlay calls: 80 canonical plus 40 superseded E2B executions;
- 26 native-correction executions: 12 superseded transport calls, 12 authoritative calls, and two boundary calls;
- 30 long-representation executions: three canaries plus 27 phase calls;
- 20 long plain repeat calls;
- 60 native structured repeat calls.

A call with both a raw-text file and a response envelope is counted once. File presence proves retention, not semantic correctness.

Raw outputs are unavailable by design for the P2/P4 metric-only probes and repaired P4 requests. Their retained evidence consists of hashes, statuses, timings, token counts, validation fields, and system measurements. Pre-generation configuration failures have no useful model output to retain.

## Cache and session evidence

Facts:

- The historical overlay includes compatible loaded-session sequences with stable-prefix and exact-repeat controls.
- Earlier cache/session studies report loaded-follow-up timing improvements.
- The last-day P2/P4 probes establish bounded concurrent execution.

Interpretation:

- Faster loaded follow-ups are timing evidence only.
- No request-linked cache-hit flag, reused-token count, avoided-prefill trace, or physical KV telemetry was retained.

Classification:

- Loaded-session generation and timing: `VALID_MODEL_RESULT` in their bounded cells.
- Physical KV-cache reuse: `NOT_TESTED`.

## Explicit gaps

| Topic | Classification | Gap |
|---|---|---|
| Microphone | `NOT_TESTED` | No new production-shaped microphone call in the statistical closure; transcript text is not audio-grounded evidence. |
| Video | `NOT_TESTED` | No complete real-video early/middle/late chunk, merge, and semantic-review pipeline. |
| Translation | `NOT_TESTED` | Fixture or prompt presence is not a Gemma generation result. |
| Vision | `NOT_TESTED` | No last-day vision generation belongs to this closure; earlier narrow route evidence does not establish broad image understanding. |
| Exact 32,768 generation | `NOT_TESTED` | Authoritative last-day matrices used 28,672 or lower contexts. |
| Controlled plain-versus-JSON repeat-5 | `NOT_TESTED` | No A/B holds content, boundaries, context, budget, and order constant while changing only representation. |
| Physical cache reuse | `NOT_TESTED` | No direct provider or runtime telemetry. |
| GPU layer placement | `NOT_TESTED` | No reliable per-layer offload read-back. |

## Fact, interpretation, and hypothesis boundary

Facts:

- The canonical overlay executed 80 calls.
- The authoritative native correction executed 12 matrix calls plus two boundary calls.
- The frozen long-representation plan has 54 rows, but only 27 phase call artifacts survive, plus three canaries.
- The two repeat-5 closures retain 20 long-plain and 60 structured calls.
- The compact P4 repair retains 80 successful request summaries.

Interpretations:

- Complete negative generations are valid model results.
- Positional P4 HTTP 400 rows are configuration failures because useful generation did not occur and compact grammar repaired the lane.
- Timing improvements do not prove cache reuse.

Hypotheses:

- Compact generic schemas are the likely reason bounded P4 became viable.
- 12B QAT is the strongest next rehearsal candidate, conditional on product-shaped boundary, exact-surface, and semantic validation.

## Evidence limits

This inventory confirms repository claims only where they reconcile with frozen plans, retained call artifacts, ledgers, reports, process markers, or load/read-back evidence. It does not republish private text, prompts, completions, local paths, or identifiers. It does not claim production admission, audio accuracy, broad vision capability, translation quality, exact-32k generation, physical cache reuse, or completion of the full long-transcript representation plan.
