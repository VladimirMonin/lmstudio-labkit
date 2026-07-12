# Long-context representation analysis

Date: 2026-07-12

## Decision

Use **plain text as the default full-context representation** for the current plain-text cleanup pipeline. It had the lowest measured input cost, preserved the requested chunk boundary in every available controlled output, and was the safest representation for E4B. Use **JSON Whisper blocks as an opt-in alternative** when downstream block identity or deterministic merge validation is required; the available run did not ask the model to return block IDs, so it does not prove block-preserving output. Do not select **timestamped paragraphs** as the default: they had the highest token overhead and produced the only observed cross-boundary/output-limit failure.

The answer is model- and position-sensitive:

- **E4B:** prefer plain text. Timestamped and JSON context both silently shortened the early chunk.
- **12B QAT:** plain text and JSON blocks are both credible. JSON preserved the early chunk's protected digit surfaces better; timestamped late context crossed the chunk boundary and exhausted its output budget.
- **26B MoE:** no representation wins consistently. Plain text is the practical default because extra structure added cost without stable quality gain.
- **E2B:** no complete three-representation early/middle/late matrix is available. Five repeated plain/early outputs support plain-text lexical preservation, but not a cross-representation recommendation for this model.

Across positions, the middle chunks were the most representation-stable. Early chunks exposed the clearest cleanup differences and the most harmful omissions. Late chunks were often returned almost unchanged; timestamped late context was uniquely unsafe for 12B in this run.

## Evidence boundary

### Repository evidence

- `experiments/lmstudio/source_shaped_rehearsal/v1/README.md` defines the controlled comparison: identical full transcript, identical early/middle/late chunks, plain output, no retry, and representation as the isolated variable.
- `experiments/lmstudio/source_shaped_rehearsal/v1/manifest.json` and the private frozen plan bind the model, representation, chunk, request digest, and serial order.
- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_whisper_structured_parallel_statistics.md` supplies the independently published repeat and structured-output context, including the five-repeat plain/early findings.
- `experiments/lmstudio/results_summaries/2026-07-12_gemma_whisper_benchmark_retrospective.md` establishes why prior M01/M05/L02-L scores cannot substitute for the controlled representation comparison.

### Owner-only evidence inspected

The analysis directly inspected these private artifact classes without copying their text or locators into this report:

- one frozen sanitized long Russian Whisper transcript with 229 ordered blocks;
- three byte-bound early/middle/late chunks from that transcript;
- three full-context representations with bound digests;
- the frozen 54-request plan;
- 27 controlled raw response envelopes and final texts for E4B, 12B QAT, and 26B MoE;
- 20 independent cold plain/early response envelopes for E2B, E4B, 12B QAT, and 26B MoE.

No model was loaded and no generation or network request was made for this analysis.

## Coverage

| Model | Plain | Timestamped paragraphs | JSON blocks | Coverage verdict |
|---|---|---|---|---|
| E2B | Five independent early repeats | Missing | Missing | Partial; no representation A/B |
| E4B | Early, middle, late | Early, middle, late | Early, middle, late | Complete 3 × 3 controlled slice |
| 12B QAT | Early, middle, late | Early, middle, late | Early, middle, late | Complete 3 × 3 controlled slice |
| 26B MoE | Early, middle, late | Early, middle, late | Early, middle, late | Complete 3 × 3 controlled slice |

The missing E2B cells are **missing evidence, not model failure**. The broader six-model plan also contains two non-Gemma rows that were not executed; they are outside this report's four-model question.

## Token overhead

The 27 controlled calls used model-formatted request token counts from the response artifacts.

| Representation | Calls | Mean input tokens | Range | Overhead versus plain |
|---|---:|---:|---:|---:|
| Plain text | 9 | 23,419.7 | 23,263–23,636 | baseline |
| Timestamped paragraphs | 9 | 30,344.7 | 30,188–30,561 | +6,925.0 / +29.6% |
| JSON blocks | 9 | 29,935.7 | 29,779–30,152 | +6,516.0 / +27.8% |

**Fact:** both structured context forms consumed roughly 28–30% more input tokens for the same transcript and chunk.

**Interpretation:** timestamps and JSON syntax spend context capacity without a demonstrated general quality advantage in this plain-output task.

**Hypothesis:** JSON may still repay its cost in a block-preserving output contract with exact ID/order validation. That contract was not exercised here.

## Quality findings by model

### E2B

**Fact:** five cold plain/early repeats were byte-stable, semantically complete, chunk-isolated, and exact on protected values. They performed little useful cleanup: punctuation was reduced rather than improved and the result remained one paragraph.

**Missing evidence:** E2B has no controlled timestamped or JSON early/middle/late outputs in the recovered phase-one result set. Therefore neither representation can be called better or worse for E2B.

### E4B

| Position | Plain | Timestamped | JSON blocks |
|---|---|---|---|
| Early | Complete and conservative; little cleanup | Harmful silent tail deletion; one protected digit surface lost | Harmful silent tail deletion; one protected digit surface lost |
| Middle | Complete; useful punctuation; one paragraph | Similar useful cleanup | Similar useful cleanup |
| Late | Nearly unchanged | Unchanged | Stronger punctuation and casing, complete in the inspected output |

**Fact:** the early timestamped and JSON outputs stopped normally rather than hitting their output budgets, yet each omitted the same substantial tail. This is silent semantic deletion, not truncation reported by transport.

**Interpretation:** plain text is the only defensible default for E4B. JSON can improve a specific late chunk, but that local gain does not offset the early deletion risk.

### 12B QAT

| Position | Plain | Timestamped | JSON blocks |
|---|---|---|---|
| Early | Complete, useful punctuation and paragraphs; protected digits rendered semantically rather than exactly | Similar cleanup; protected digits rendered semantically rather than exactly | Complete cleanup and exact protected digit surfaces in the inspected output |
| Middle | Complete and usefully punctuated | Similar | Similar |
| Late | Complete and usefully punctuated | Output-budget exhaustion with content beyond the requested chunk boundary | Complete and usefully punctuated |

**Fact:** the timestamped late output consumed its full 2,031-token budget and ended with `finish_reason=length`. It was materially longer than the authoritative chunk and included content outside the requested boundary. This is the only controlled chunk-isolation failure in the recovered 27-call set.

**Interpretation:** JSON blocks are the strongest 12B representation when exact protected surfaces and future block identity matter. Plain text remains a lower-cost safe choice. Timestamped context should be blocked until boundary validation is fail-closed.

### 26B MoE

| Position | Plain | Timestamped | JSON blocks |
|---|---|---|---|
| Early | Best paragraphing and useful cleanup | Similar semantic coverage, but no stable advantage | Complete, useful punctuation, weaker paragraph structure |
| Middle | Complete and usefully punctuated | Similar | Similar |
| Late | Almost unchanged | Almost unchanged | Almost unchanged |

**Fact:** all nine controlled outputs remained Russian, chunk-isolated, and free of runaway repetition or wrappers. All protected numeric surfaces were present. Representation changed style more than substantive retention.

**Interpretation:** plain text wins operationally by cost and paragraphing, not by a large semantic margin. The 26B model did not demonstrate a quality gain sufficient to justify structured-context overhead.

## Cross-cutting axes

| Axis | Finding |
|---|---|
| Chunk completeness | 24/27 controlled outputs were complete by direct private review; two E4B early structured-context outputs silently deleted a tail, and one 12B timestamped-late output crossed the boundary and hit length. |
| Chunk-only isolation | Passed in 26/27 controlled outputs; failed once for 12B timestamped late. |
| Semantic units | Plain and timestamped outputs could create useful paragraphs, but paragraphing was model-dependent. JSON input did not guarantee block-aligned output because output was plain text. |
| Protected values | 12B plain/timestamped early preserved numeric meaning but not exact digit surfaces; its JSON output preserved the inspected digit surfaces exactly. E4B's two early structured-context deletions removed one protected item. 26B preserved inspected numeric surfaces. |
| ASR corrections | 12B and 26B made the most consistent punctuation/casing corrections. E4B corrections varied by chunk; E2B plain/early largely copied lexical content. Technical-name corrections were not backed by acoustic truth and are semantic edits, not verified ASR repairs. |
| Harmful guesses | No unsupported new factual episode was found in the 27 controlled outputs. Some model edits normalized uncertain technical names; without audio or an authoritative spelling inventory, those edits remain unverified rather than accepted corrections. |
| Punctuation | 12B improved punctuation across plain and JSON. 26B improved early/middle but not late. E4B improved selected middle/late cells. E2B plain/early did not. |
| Paragraphs | 12B and 26B sometimes added useful paragraphs, but not consistently across representations. E4B remained one paragraph in all inspected cells. |
| Language | All inspected outputs remained Russian; no translation was observed. |
| Repetition | No runaway repetition was found in the controlled representation outputs. This does not erase the separate E4B M05 runaway evidence, which used a different workload. |
| Output wrapper | All 27 controlled outputs were direct plain text without Markdown fences or JSON wrappers, matching this experiment's output contract. |

## Recommendation

1. **Default:** plain full context plus an explicit authoritative current-chunk delimiter and a fail-closed chunk-only validator.
2. **Structured alternative:** JSON Whisper blocks for 12B or a future merge-sensitive pipeline, but only if output also carries exact IDs and post-generation validation checks order, missing, duplicate, and extra IDs.
3. **Do not default to timestamps:** they cost the most and provided the only observed boundary/length failure.
4. **Per-model:** use plain for E4B and 26B; allow plain or JSON for 12B; keep E2B undecided beyond plain/early until its missing six cells are actually executed.
5. **Per-position:** validate early outputs for silent deletion and late outputs for copy-through or boundary expansion. Do not infer whole-record quality from a strong middle chunk.

## Unresolved evidence gaps

- E2B timestamped and JSON outputs for early/middle/late are absent.
- The controlled matrix has one attempt per E4B/12B/26B cell; repeatability is known only for plain/early cold repeats.
- No block-preserving output contract was used, so JSON input's merge advantage is hypothetical.
- No audio truth, WER/CER, timestamp-accuracy, or authoritative technical-name spelling check exists.
- No manually aligned source-unit-to-output map was produced for all 27 cells; completeness conclusions come from direct semantic review plus protected-value and boundary checks.
- The run does not establish physical cache reuse, production concurrency, translation quality, or microphone behavior.
