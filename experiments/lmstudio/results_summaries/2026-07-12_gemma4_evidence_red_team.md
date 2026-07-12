# Gemma 4 evidence red-team

Date: 2026-07-12

Status: offline adversarial review. No model was loaded, no generation or network request was made, and no runner, configuration, prompt, test, or unrelated document was changed.

## Decision

The reports are strongest on execution accounting, negative-result preservation, and explicit non-claims. They do not support production admission for any model or pipeline. The main corrections are narrower than a wholesale rejection but materially change the operational conclusions:

1. downgrade parallel overlap from `PROVEN` to a strong indirect timing signal until request intervals tied to worker slots are retained;
2. replace “grammar complexity caused the P4 failure” with a bounded association between the positional-const request grammar and pre-generation HTTP 400 responses;
3. report positive provider `cached_tokens` fields that are present in the native correction, while keeping physical KV reuse unproven;
4. stop treating five byte-identical repeats as five independent semantic confirmations;
5. downgrade 12B selection and plain-text pipeline fit from admission-like language to a single-recording, single-early-chunk hypothesis;
6. distinguish retained call artifacts from unique outputs and from independently reviewed semantic units;
7. keep all P4 repair claims structural because output text was not retained.

Machine-readable companion: `2026-07-12_gemma4_evidence_red_team.json`.

## Method and evidence boundary

Repository evidence checked:

- `2026-07-12_gemma4_last_day_evidence_inventory.{md,json}`;
- `2026-07-12_long_context_representation_analysis.{md,json}`;
- `2026-07-12_parallel_cache_gpu_runtime_audit.{md,json}`;
- `2026-07-12_structured_output_and_scorer_audit.{md,json}`;
- `2026-07-12_source_application_pipeline_fit.{md,json}`;
- `2026-07-12_small_gemma_long_context_json_forensics.{md,json}`;
- `2026-07-12_gemma4_whisper_structured_parallel_statistics.{md,json}`;
- `2026-07-12_gemma_whisper_benchmark_retrospective.md`;
- `2026-07-12_four_model_real_asset_benchmark_synthesis.json`;
- `2026-07-12_gemma4_native_structured_output_correction.json`;
- the frozen overlay plan, source-shaped rehearsal manifest, and cited scorer/validator implementations.

Owner-only artifact classes previously inspected by the parent audits were cross-checked through their retained aggregate fields: overlay call ledgers and outputs; long-representation envelopes and final texts; cold-repeat envelopes; repeated native structured-output envelopes and extracts; P2/P4 batch summaries and request metrics; GPU load read-back; and active pipeline code. Private bodies and locators are not reproduced.

Classification meanings:

- `CONFIRMED`: the bounded claim follows from retained evidence.
- `OVERSTATED`: evidence supports a narrower claim.
- `UNDERSTATED`: retained evidence is stronger or more specific than reported.
- `UNSUPPORTED`: the required evidence is absent.
- `CONTRADICTED`: retained evidence directly conflicts with the claim.

## Claim audit

| Claim | Class | Falsification result | Mandatory correction |
|---|---|---|---|
| The canonical historical overlay is 64 cells and 80 calls, with 40 additional superseded E2B calls. | `CONFIRMED` | Frozen-plan/synthesis accounting reports 64 planned and executed cells, 80 planned and executed calls, and zero accepted calls. The inventory keeps the two 20-call E2B runs outside the canonical denominator. | Keep these denominators separate; never publish 120 as the canonical run. |
| The native correction is 12 authoritative matrix calls plus two E4B/M05 boundary calls. | `CONFIRMED` | The correction JSON contains 12 rows and two explicitly separate follow-ups. | Do not merge the earlier superseded 12-call transport pass into this denominator. |
| There are 256 retained call-level outputs. | `OVERSTATED` | The arithmetic is internally consistent, but “outputs” conflates call artifacts with independent output content. The 20 long repeats contain only four unique outputs, and each of the 12 structured model/task cells has one unique output across five repeats. File presence also does not prove semantic review. | Say “256 retained call executions with call-level output artifacts”; separately report unique-output and semantic-review denominators. |
| Five cold repeats per model establish repeatability. | `OVERSTATED` | They establish deterministic byte stability for one frozen early-chunk request at temperature zero. They do not provide five independent semantic samples or family-wide behavior. | Report `N=5 executions, N=1 unique output per model, one recording, one position, one prompt`. |
| 12B QAT achieved semantically complete long cleanup in 5/5 and is the strongest operational candidate. | `OVERSTATED` | The five calls repeat one byte-identical result. Review lacks exhaustive source-unit alignment, audio truth, and additional recordings/positions. The recommendation is plausible but not independently replicated. | Rephrase as “best next rehearsal hypothesis from one early-chunk cell”; do not use admission language. |
| Plain text is verified as the closest active pipeline fit. | `OVERSTATED` | One frozen early-chunk request approximates full-context/current-chunk separation, but no call traverses the active source owner, exact serialization, warmup/concurrency sequence, persistence, or merge. The source-fit report itself lists these missing components. | Classify active-pipeline fit as `PARTIAL`; reserve `VERIFIED` for the bounded laboratory request shape only. |
| The 27-call representation slice proves plain text is the default. | `OVERSTATED` | The recommendation is supported only for one recording, one attempt per E4B/12B/26B cell, incomplete E2B coverage, plain output for every arm, and manual review without exhaustive alignment. Prompt representations also differ by thousands of tokens, so this is a representation package comparison, not a token-matched prompt A/B. | Call plain text the conservative hypothesis for this recording and output contract; require replication before a general default. |
| JSON blocks are a demonstrated merge-sensitive alternative. | `UNSUPPORTED` | JSON was used as input representation while output remained plain text; exact output block identity and merge were not exercised. | Label the merge advantage as a hypothesis only. |
| Repaired compact-schema P4 passed 80/80. | `CONFIRMED` for structure only | Retained metrics support HTTP 200, stop, zero reasoning, 25 items, and exact IDs/order. Raw text and semantic review are absent. | Always append “structural only; semantic quality unknown.” |
| True P2/P4 overlap is proven. | `OVERSTATED` | Applied parallelism plus summed request-duration versus batch-wall arithmetic strongly rejects wholly serial execution, but repaired P4 records lack request start/finish intervals tied to worker slots and instance identity. | Use `STRONG_TIMING_SIGNAL`; require interval traces before `PROVEN`. |
| Positional `const` grammar caused the P4 HTTP 400 failure. | `OVERSTATED` | Controls localize the failure to the positional-const request/runtime interaction: sequential warmup, plain P4, minimal schema, and generic schema passed, while context reduction did not help. They do not isolate grammar complexity from concurrency, server implementation, schema serialization, or request interaction. | Say “associated with and repaired by replacing the positional-const grammar”; do not claim a universal causal threshold. |
| Physical cache reuse is unproven. | `CONFIRMED` | No validated request-linked reuse semantics, avoided-prefill trace, or physical KV trace exists. Timing alone is insufficient. | Keep physical reuse unproven. |
| No positive request-linked cached-token count was retained. | `CONTRADICTED` | The public native-correction JSON contains `usage.input_tokens_details.cached_tokens` values of `1` on multiple M05/L02-L rows and `0` on M01 rows. The meaning and reliability of those values were not validated, and they do not prove physical reuse. | Report that a positive provider field exists but is uninterpreted; distinguish “counter present” from “reuse proven.” |
| Maximum-GPU placement has no proven benefit. | `CONFIRMED` | Both pairs passed, reported load size was unchanged, completion-token totals differed, and no layer/VRAM telemetry isolates placement. | Keep the no-proven-benefit conclusion; do not infer automatic placement is faster. |
| Native strict schema improves structural compliance but guarantees neither raw JSON nor semantics. | `CONFIRMED` | Repeated outputs include raw, fenced, malformed, extra-field, metadata, target, and length failure classes. | Keep transport, extraction, exact schema, business identity, and semantics separate. |
| Sixty repeated structured outputs provide 60 semantic observations. | `OVERSTATED` | There are 60 call artifacts but only 12 unique model/task outputs across repeats. Re-reading duplicates confirms determinism, not 60 independent semantic cases. | Publish both denominators: 60 executions, 12 unique outputs; semantic review denominator must use unique outputs or explicitly state duplicate weighting. |
| L02-L retention proves complete source retention. | `CONFIRMED` as rejected | The reports correctly identify retention values as model self-report rather than source alignment. | Do not use 428/428 as semantic retention evidence without independent alignment. |
| E4B/M05 is a task-specific deterministic runaway, not general context or JSON failure. | `CONFIRMED` with a boundary | The 4k/8k/16k outputs share prefixes and exhaust each cap while other E4B cells succeed. The evidence localizes the failure to the M05 contract but does not isolate prompt, source, schema, or their interaction. | Preserve the narrow attribution; do not name a single internal trigger. |
| Retry/fallback policy is validated. | `UNSUPPORTED` | The policy is a design recommendation; no retained end-to-end attempt-zero/retry/fallback execution exists. | Label it proposed and require immutable attempt records in a future test. |
| Production concurrency up to P4 is admitted. | `UNSUPPORTED` | P4 evidence is compact-schema, metric-only, semantically unreviewed, lacks an application-shaped long request, and has no matched useful-throughput P1 baseline. | Keep P2 as a rehearsal ceiling; treat P4 as a structural capability probe only. |
| Microphone, video, translation, and merge are closed. | `UNSUPPORTED` | No audio-grounded microphone result, real-video extraction-to-merge result, requested-direction translation generation, or generated early/middle/late merge exists. | Keep these surfaces `NOT_TESTED`; translation direction remains `INVALID` for the inspected active templates. |

## Duplication, retry, fallback, and cherry-picking risks

Facts:

- The inventory correctly separates canonical, superseded, diagnostic, configuration-failure, and unexecuted rows.
- Repeat-five datasets are deliberately deterministic and heavily duplicate output content.
- The long representation recommendation uses only the executed half of a frozen 54-call plan: 27 phase rows are retained and 27 are absent.
- P4 repair evidence has no raw text by design.
- Retry and fallback are proposed, not demonstrated.

Interpretation:

- There is no evidence that superseded rows were silently counted in the canonical 80-call overlay denominator.
- There is a selection risk in elevating 12B and plain text from one recording/early cell while the full E2B representation matrix, multi-recording replication, merge, and active owner path remain absent.
- Failure-to-success repair narratives are useful only when both attempts remain visible. Current reports generally preserve them, but operational summaries sometimes foreground the repaired denominator and compress the failed grammar/configuration history.

Hypothesis:

- A second recording and a complete early/middle/late active-path rehearsal could reverse the model or representation ranking because current semantic differences are position-sensitive and mostly single-shot.

## Markdown/JSON consistency

No arithmetic contradiction was found between each parent Markdown report and its JSON companion for the principal denominators: 64/80 overlay, 12+2 native correction, 27/54 representation phase, 20 long repeats, 60 structured repeats, and 80 repaired P4 requests.

Material semantic inconsistencies remain:

1. The parallel audit labels overlap `PROVEN` while its own Markdown and JSON acknowledge absent worker-slot interval traces.
2. The cache audit says no positive request-linked cached-token count was retained, while the public native-correction JSON contains positive `cached_tokens` fields.
3. The source-fit JSON classifies plain text `VERIFIED`, while the same report says the active source path, later chunks, retry, persistence, and merge were not exercised.
4. The statistics JSON exposes `max_concurrency: 4`, while the Markdown operational text says P2 is conservative and P4 is bounded. Consumers reading JSON alone may misread a structural P4 result as admission.
5. The statistics reports use execution counts (`5/5`, `60`) without colocating unique-output counts (`1/5` per cell), which can inflate apparent semantic replication.

## Mandatory corrections

1. Change parallel overlap to `STRONG_TIMING_SIGNAL` until worker-slot request intervals are retained.
2. Replace causal P4 grammar language with bounded association/repair language.
3. Amend cache sections to acknowledge positive but uninterpreted provider `cached_tokens` fields.
4. Add `unique_outputs` beside every repeat execution denominator.
5. Downgrade active plain-text pipeline fit from `VERIFIED` to `PARTIAL`; optionally add a separate `LAB_REQUEST_SHAPE_VERIFIED` field.
6. Downgrade 12B from primary/admitted candidate wording to “preferred next rehearsal candidate from one frozen early-chunk result.”
7. Remove or qualify JSON `max_concurrency: 4`; represent P4 as `structural_probe_only` and P2 as the rehearsal default.
8. State that the 27-call representation matrix is one recording, one attempt per complete cell, plain-output only, and not token-matched.
9. State that repaired P4 has no semantic evidence and cannot support cleanup quality, business acceptance, or production concurrency.
10. Keep retry/fallback, block merge, microphone, video, requested-direction translation, physical cache reuse, exact layer placement, and full active-path admission explicitly untested.

## Unresolved evidence gaps

- No independently captured request interval trace for repaired P4.
- No documented interpretation or validation of the provider `cached_tokens` field.
- No unique-output-aware semantic review ledger with source-unit alignment.
- No second recording or repeated early/middle/late representation matrix.
- No complete E2B representation matrix.
- No controlled same-content plain-versus-native-JSON response-format A/B.
- No block-preserving output, retry/fallback, persistence, and merge execution.
- No audio truth, microphone owner-path run, real-video pipeline, or requested-direction translation run.
- No application-shaped P1/P2/P4 useful-throughput comparison.
- No request-linked physical cache, per-layer GPU placement, or complete VRAM telemetry.
