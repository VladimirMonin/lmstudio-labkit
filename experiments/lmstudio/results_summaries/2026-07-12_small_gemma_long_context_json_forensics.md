# Small Gemma long-context JSON forensics

Date: 2026-07-12

Status: offline evidence reconciliation; no model calls or model loads were performed.

## Question and evidence boundary

This report asks whether Gemma 4 E2B and E4B fail from the combination of a large full-transcript prefix, a current chunk, and a JSON response contract. It separates transport, load/lifecycle, context fit, output budget, reasoning, schema complexity, JSON serialization, and text quality.

Evidence inspected:

- public correction and statistical reports listed below;
- owner-only long-transcript request envelopes and outputs for the five cold plain-text repeats per model;
- owner-only native structured-output envelopes and raw outputs for five repeats of M01, M05, and L02-L per model;
- owner-only E4B/M05 8,192- and 16,384-token boundary artifacts;
- historical process evidence for the failed initial long-context E2B attempts.

No private text, path, or response body is reproduced here.

## Executive finding

**Fact:** neither small model has a demonstrated general failure at large context. Both completed five byte-stable cold plain-text requests using a 32,768-token load context, 23,354 reported prompt tokens, a 1,620-token output cap, zero reasoning tokens, and `finish=stop`.

**Fact:** E2B also produced exact-schema JSON in all five M05 calls and extractable exact-schema JSON in all five L02-L calls under a 28,672-token context. E4B produced extractable exact-schema JSON in all five M01 and L02-L calls, but failed M05 deterministically.

**Interpretation:** E2B's earlier “crash” is not model evidence. The first relevant attempt used `/v1/responses`, returned HTTP 500 before any completed call, and the server removed the loaded instance. An earlier preflight also stopped before generation because duplicate inventory records were mistaken for multiple loaded instances. The later product-shaped `/v1/chat/completions` path completed 5/5 long/plain calls. This reconciles the apparent contradiction as transport and runner/lifecycle defects, not E2B context collapse.

**Interpretation:** E4B's M05 failure is task-specific runaway generation, not a general large-context, load, reasoning, or schema-capability failure. The same model completed long/plain, M01, L02-L, P2, and compact-schema P4 cells. M05 alone reproduced one malformed prefix while exhausting 4,096, 8,192, and 16,384 output tokens.

**Unresolved:** no existing call changes only the response contract from plain text to compact JSON while holding the same 23k-token full transcript, current chunk, prompt, model instance policy, and output budget constant. Therefore the exact three-way interaction “full large context + current chunk + JSON response” remains untested as a controlled A/B.

## E2B: earlier failure versus later success

### Observed facts

1. Initial full-matrix attempts produced zero completed model calls:
   - one stopped in lifecycle preflight because one loaded instance appeared in duplicate inventory records;
   - the next used `/v1/responses`, received HTTP 500 on the first request, and then encountered a secondary cleanup error because the server had already removed the instance.
2. The product-shaped retry changed transport to `/v1/chat/completions`, used `cache_prompt=true`, disabled thinking, extracted the final assistant message, and made cleanup tolerant of prior server removal.
3. Five later cold long/plain repeats all completed:
   - load context: 32,768;
   - measured input: 23,359 driver tokens / 23,354 envelope prompt tokens;
   - output cap: 1,620;
   - output: 874 tokens in every repeat;
   - reasoning: 0 tokens;
   - finish: `stop` in 5/5;
   - request digest: identical in 5/5;
   - output digest: identical in 5/5.
4. Text review found content/order/chunk isolation preserved in 5/5 but full cleanup failed in 5/5: punctuation and paragraphing were not improved adequately.

### Interpretation

The crash cannot be attributed to E2B's ability to process the long prompt. No model output exists from the failing attempt. The successful route later processed a prompt occupying roughly 71% of the loaded context and stopped well below its output cap. E2B's remaining issue is text transformation quality, not context, transport, or output length.

### JSON evidence by axis

| Cell | Context | Input / output cap | Raw JSON | Extractable JSON | Exact schema | Text/retention interpretation |
|---|---:|---:|---:|---:|---:|---|
| M01, 5 repeats | 28,672 | 737 / 512; output 362 | 5/5 | 5/5 | 5/5 | lexical text was useful, but strict target/placeholder metadata gates failed |
| M05, 5 repeats | 28,672 | 1,170 / 4,096; output 554 | 5/5 | 5/5 | 5/5 | task understood, but inspected outputs did not consistently remove all repeated-tail material |
| L02-L, 5 repeats | 28,672 | 12,060 / 512; output 155 | 0/5 | 5/5 | 5/5 | model reported 318/428 retained units; not a source-aligned retention proof |

E2B therefore does not show a general raw-JSON or schema failure at either 1.2k or 12k input tokens. Its defects are cell-specific text quality and incomplete long structural retention.

## E4B: good cells versus deterministic M05 runaway

### Long/plain control

Five cold long/plain repeats all completed:

- load context: 32,768;
- measured input: 23,359 driver tokens / 23,354 envelope prompt tokens;
- output cap: 1,620;
- output: 897 tokens in every repeat;
- reasoning: 0 tokens;
- finish: `stop` in 5/5;
- request and output digests: each identical across five repeats.

This directly rules out a general inability to load or process the full transcript at this size. Private text review nevertheless found that other representation-sensitive E4B cells can make harmful silent deletions, so transport success is not quality admission.

### JSON evidence by axis

| Cell | Context | Input / output cap | Raw JSON | Extractable JSON | Exact schema | Text/retention interpretation |
|---|---:|---:|---:|---:|---:|---|
| M01, 5 repeats | 28,672 | 737 / 512; output 268 | 0/5 | 5/5 | 5/5 | fenced wrapper only; lexical text was useful while strict metadata/target gates failed |
| M05, 5 repeats | 28,672 | 1,170 / 4,096; output 4,096 | 0/5 | 0/5 | 0/5 | malformed deterministic runaway; no usable JSON |
| L02-L, 5 repeats | 28,672 | 12,060 / 512; output 215 | 0/5 | 5/5 | 5/5 | model reported 43/428 retained units; not a source-aligned retention proof |

### Output-budget and reasoning controls

The M05 request was repeated under the same native strict schema, temperature zero, and reasoning disabled:

| Output cap | Reported input | Output tokens | Context arithmetic | Result |
|---:|---:|---:|---|---|
| 4,096 | 1,170 | 4,096 | ample headroom in 28,672 | malformed; no extractable JSON |
| 8,192 | same request | 8,192 | ample headroom | preserved the entire 4k prefix and continued |
| 16,384 | 1,170 native / 1,175 SDK-formatted | 16,384 | 19,607 required including 2,048 safety; 9,065 remained | preserved the full 4k and 8k prefixes and continued |

All three calls reported zero reasoning tokens. `finish_reason=stop` was misleading because output token usage reached the configured cap exactly.

### Interpretation

- **Not transport-general:** M01 and L02-L returned extractable exact-schema JSON on the same endpoint and strict-schema mechanism.
- **Not load-general:** long/plain completed 5/5 at a much larger 23k-token input.
- **Not context pressure:** M05 used only about 1.2k input tokens, and the 16k-output control still had 9,065 tokens of safety-adjusted context headroom.
- **Not reasoning:** all evidence reports zero reasoning tokens.
- **Not merely a small output cap:** longer caps extended the identical malformed prefix.
- **Not schema capability in general:** E4B passed exact schema after extraction on M01 and L02-L, and compact generic structured P2/P4 cells passed.
- **Most supported attribution:** a deterministic interaction between E4B and the M05 normalization prompt/content/schema task. The evidence does not isolate which element inside that task triggers the loop.

## Schema complexity and runtime failures

A separate P4 failure affected all models before generation when the runtime grammar used 25 position-specific `const` ID constraints. Reducing context did not repair it. Replacing that grammar with a compact generic 25-item schema and checking exact IDs/order after generation produced 20/20 successful requests for E2B and 20/20 for E4B across five P4 batches.

This is evidence that schema complexity can cause runtime rejection, but it is not the cause of E4B/M05: M05 generated tokens and ran to the cap, whereas the const-heavy P4 case returned HTTP 400 before generation.

## Causal classification

| Candidate cause | E2B | E4B M05 | Evidence status |
|---|---|---|---|
| General large-context failure | contradicted by 5/5 long/plain | contradicted by 5/5 long/plain | fact |
| Load configuration failure | affected early preflight only | no | fact |
| Wrong transport | caused E2B zero-call HTTP 500 attempt | no evidence for M05 | fact |
| Output budget too small | no length hit in relevant cells | contradicted by 4k/8k/16k continuation | fact |
| Reasoning leakage | no, zero tokens | no, zero tokens | fact |
| General JSON/schema inability | contradicted by M01/M05/L02-L | contradicted by M01/L02-L and compact parallel schemas | fact |
| Const-heavy schema complexity | separate pre-generation P4 failure | separate pre-generation P4 failure | fact, not M05 cause |
| Task-specific behavior | E2B quality varies by task | strongest M05 explanation | interpretation |
| Exact large-prefix + chunk + JSON interaction | not controlled | not controlled | unresolved |

## Smallest additional live experiment

No additional call is needed to classify the historical E2B crash or the E4B/M05 runaway. Those are already resolved at the level supported by retained evidence.

If the owner needs the unanswered product-shaped interaction, the smallest controlled experiment is **four cold calls**:

1. E2B, frozen 23k-token full transcript + identical current chunk, plain-text response;
2. E2B, same serialized request content and budget, changing only response format to a compact generic JSON object;
3. E4B, the same plain-text control;
4. E4B, the same compact-JSON variant.

Required controls: `/v1/chat/completions` product-shaped transport, 32,768 context, reasoning disabled with verified zero reasoning tokens, temperature zero, one cold load per call, output cap 1,620 (or the same contract-derived cap for both arms), complete envelope/raw capture, exact request/prefix/chunk digests, raw/extracted/schema/text scoring, and zero-loaded read-back. Do not use M05's larger native schema for this A/B; that would confound response format with the already known task-specific trigger.

A fifth call is justified only if one JSON arm fails: repeat that exact arm once to distinguish deterministic behavior from a single transient. No broad matrix is warranted.

## Evidence gaps and non-claims

- Existing long/plain calls did not request JSON output.
- Existing native JSON calls did not use the same 23k-token full-transcript-plus-current-chunk request.
- The long/plain quality review covers one frozen recording and one early chunk; it is not broad production admission.
- L02-L retention counts are model-reported structural fields, not independent source alignment.
- E4B M05's trigger is localized to the task contract but not decomposed among prompt wording, source text, and schema fields.
- Successful transport/schema does not imply safe text editing; E2B under-edits and E4B has observed representation-sensitive deletions.

## Public evidence sources

- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_native_structured_output_correction.md`
- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_native_structured_output_correction.json`
- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_whisper_structured_parallel_statistics.md`
- `experiments/lmstudio/results_summaries/2026-07-12_gemma4_whisper_structured_parallel_statistics.json`
- `experiments/lmstudio/results_summaries/2026-07-12_gemma_whisper_benchmark_retrospective.md`
- `experiments/lmstudio/source_shaped_rehearsal/v1/load_config.json`
