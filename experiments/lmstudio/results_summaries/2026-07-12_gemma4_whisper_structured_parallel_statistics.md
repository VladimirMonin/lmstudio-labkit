# Gemma 4 Whisper, structured-output, and parallel statistics

Date: 2026-07-12

## Scope

This closure study covers four locally available Gemma 4 variants:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`
- `google/gemma-4-12b-qat`
- `google/gemma-4-26b-a4b-qat`

The 31B model and non-Gemma models are out of scope. Private source transcripts, prompts, completions, response envelopes, and local runtime paths remain outside Git. This document contains only sanitized aggregates.

The study combines:

- 20 independent cold repeats of one real long-transcript plain-text chunk workload;
- 60 independent native structured-output calls (`5 repeats × 4 models × 3 tasks`);
- true-parallel P2 and P4 structured-block probes;
- one 12B GPU-placement comparison (`auto` versus `--gpu max`);
- direct forensic reading of private outputs, separated from transport/schema scoring.

All accepted statistical calls used reasoning disabled. Cleanup verification ended with zero loaded model instances.

## Executive conclusion

`Gemma 4 12B QAT` is the strongest candidate for the host application's long-transcript cleanup and structured-block pipeline. It produced semantically complete long cleanup in all five cold repeats and passed true P2 structured requests when given a sufficient output budget. It is not yet an unconditional production admission: one earlier timestamped-context result crossed the current-chunk boundary, and exact digit surface preservation requires an explicit contract.

`Gemma 4 E2B` is the best raw-JSON follower and the fastest model in this comparison, but on the repeated long plain-text cleanup cell it deterministically copied lexical content without performing the requested punctuation and paragraph cleanup.

`Gemma 4 E4B` is not recommended for long unattended cleanup. Its M05 structured cleanup entered deterministic output exhaustion in all five repeats, and independent long-transcript review found silent harmful deletions in representation-sensitive cells.

`Gemma 4 26B MoE` did not provide a consistent quality advantage over 12B. It was slower, failed exact schema in two of the three repeated structured cells, and several long-transcript outputs either removed a critical item, damaged technical names, or performed little cleanup.

P4 is supported when the runtime JSON grammar is compact. The original positional
schema encoded a separate `const` ID constraint for every one of 25 array positions;
that grammar produced HTTP 400 before generation. Replacing it with a generic
25-item `{id, text}` schema and validating exact IDs and order after generation
repaired P4 on every model: 5/5 batches and 20/20 requests passed per model.

## 1. Long real-transcript cold repeats

One real sanitized Russian transcript was frozen privately. The same early chunk and the same full plain-text context were executed five times per model, with a separate load/generate/unload lifecycle for every attempt.

### Transport and repeatability

| Model | Transport | `finish=stop` | Reasoning tokens | Unique outputs |
|---|---:|---:|---:|---:|
| E2B | 5/5 | 5/5 | 0 in 5/5 | 1/5 |
| E4B | 5/5 | 5/5 | 0 in 5/5 | 1/5 |
| 12B QAT | 5/5 | 5/5 | 0 in 5/5 | 1/5 |
| 26B MoE | 5/5 | 5/5 | 0 in 5/5 | 1/5 |

Every model was byte-stable across its five repeats at temperature zero. Repeatability therefore exposes systematic behavior rather than stochastic outliers.

### Text-quality interpretation

- **E2B:** semantic content, ordering, chunk isolation, and exact protected values were preserved in 5/5. Full cleanup success was 0/5: punctuation was removed rather than improved and the response remained one undivided paragraph.
- **12B QAT:** semantic completeness, isolation, punctuation improvement, and useful paragraphing passed 5/5. Exact protected-surface preservation was 0/5 because several digits were deterministically rendered as words; semantic numeric values remained correct.
- **E4B:** prior independent review of the same product-shaped family of cells found five strong results, two usable-with-caveats results, and two harmful silent deletions. Plain context was its most conservative representation.
- **26B MoE:** prior independent review found no stable representation advantage. One cell lost a critical list item, one damaged technical names, and all three late cells performed almost no cleanup.

These text-quality conclusions are based on private-output review, not merely exact-reference scoring.

## 2. Native structured-output repeats

Each model ran five independent passes over:

- `M01`: short/simple structured JSON;
- `M05`: long transcript normalization in JSON;
- `L02-L`: long/complex structured-retention response.

Each of the 12 model/task cells produced one unique output across five repeats.

### Results (`N/5`)

| Model | Task | Raw JSON | Extractable JSON | Exact schema | Structural retention | Length hit |
|---|---|---:|---:|---:|---:|---:|
| E2B | M01 | 5 | 5 | 5 | n/a | 0 |
| E2B | M05 | 5 | 5 | 5 | n/a | 0 |
| E2B | L02-L | 0 | 5 | 5 | 0 | 0 |
| E4B | M01 | 0 | 5 | 5 | n/a | 0 |
| E4B | M05 | 0 | 0 | 0 | n/a | 5 |
| E4B | L02-L | 0 | 5 | 5 | 0 | 0 |
| 12B QAT | M01 | 0 | 5 | 0 | n/a | 0 |
| 12B QAT | M05 | 0 | 5 | 5 | n/a | 0 |
| 12B QAT | L02-L | 0 | 5 | 5 | 5 | 0 |
| 26B MoE | M01 | 0 | 5 | 0 | n/a | 0 |
| 26B MoE | M05 | 0 | 5 | 5 | n/a | 0 |
| 26B MoE | L02-L | 0 | 5 | 0 | 0 | 0 |

The old aggregate semantic/placeholder scorer returned zero in these cells because it combines exact reference text, metadata inventories, and strict serialization. It must not be interpreted as “all generated text was semantically wrong.” The private-output review separates semantic value, exact surface form, harmful deletion, and wrapper/schema defects.

### Deterministic failure modes

- E4B M05 exhausted exactly 4096 output tokens in 5/5 and remained malformed. Earlier 8192 and 16384 controls preserved the same prefix and continued the same malformed generation.
- 12B M01 consistently returned extractable JSON but not the exact requested schema.
- 26B M01 and L02-L consistently returned extractable JSON but not exact schema.
- E2B consistently followed exact M01/M05 schema but did not perform adequate long plain-text cleanup.

## 3. True parallelism

### P2

True overlap was verified by the runner with two loaded inference slots and two concurrent application requests.

| Model | P2 result | Notes |
|---|---:|---|
| E2B | 4/4 blocks pass | exact IDs, schema, and business validation; parallel batch 30.8 s |
| E4B | 4/4 blocks pass | exact IDs, schema, and business validation; parallel batch 45.5 s |
| 12B QAT | 2/2 pass | 1875 tokens caused 2/2 length failures; 4096 repaired the cell to 2/2 pass; wall 57.4 s |
| 26B MoE | 2/2 pass | 4096 tokens; wall 127.5 s |

The two 12B preflight/warmup attempts that ended before measured requests are configuration failures, not model failures: one lacked explicit verified context and one inherited a 30-second legacy timeout.

### P4 diagnosis and repair

The initial P4 workload used a positional schema with 25 separate per-position
`const` ID constraints. Its sequential warmup passed, but all four measured requests
received HTTP 400 before generation on every model. Controls then isolated the
failure:

- short plain P4: 4/4 HTTP 200;
- medium plain P4 at roughly 1,173 prompt tokens per request: 4/4 HTTP 200;
- minimal JSON-schema P4: 4/4 HTTP 200;
- the positional 25-`const` schema still failed after reducing context from 8,192 to
  4,096;
- a generic 25-item blocks schema passed while preserving exact IDs and order through
  post-generation validation.

The repair keeps runtime grammar constraints generic (`id` integer, `text` string,
exactly 25 items) and moves request-specific ID/order/duplicate/missing/extra checks
to the application validator.

Five independent P4 batches were then executed per model. Each batch contained four
simultaneous requests.

| Model | Batches | HTTP 200 | `finish=stop` | Reasoning zero | Exact IDs/order | Mean request latency | Observed range |
|---|---:|---:|---:|---:|---:|---:|---:|
| E2B | 5/5 | 20/20 | 20/20 | 20/20 | 20/20 | 15.6 s | 15.4-15.7 s |
| E4B | 5/5 | 20/20 | 20/20 | 20/20 | 20/20 | 18.1 s | 17.7-18.3 s |
| 12B QAT | 5/5 | 20/20 | 20/20 | 20/20 | 20/20 | 19.3 s | 18.9-19.5 s |
| 26B MoE | 5/5 | 20/20 | 20/20 | 20/20 | 20/20 | 64.7 s | 60.4-69.2 s |

The repaired P4 closure adds 80 successful concurrent requests. P4 is therefore not
a general runtime or memory limit in this setup; the blocker was the complexity of
the request-specific grammar.

**Operational recommendation:** P2 remains the conservative default. P4 is admitted
for compact generic schemas with strict post-generation ID/order validation. Do not
use const-heavy positional schemas at P4.

## 4. GPU placement

A focused 12B P2 comparison used the same workload and 4096-token output budget.

| Load mode | Reported model footprint | P2 result | Wall time |
|---|---:|---:|---:|
| automatic placement | 6.66 GiB load report | 2/2 pass | 57.4 s |
| `--gpu max` | 6.66 GiB load report; 7.15 GB in `lms ps` | 2/2 pass | 66.3 s |

`--gpu max` neither increased the reported allocation nor improved this run. This does not prove that automatic placement is optimal: the available read-back does not expose a reliable offloaded-layer count, and remote-device accounting may differ from physical VRAM telemetry. GPU placement remains a separate observability/tuning gap, not a blocker for the quality conclusion.

## 5. Practical admission

### Recommended candidate

Use `Gemma 4 12B QAT` for the next host-application rehearsal with:

- reasoning disabled;
- plain full-transcript context or JSON-block context;
- explicit current-chunk boundaries;
- output budget derived from the current chunk and not artificially capped at 1875;
- P2 maximum concurrency;
- one application retry only for parse/schema failures;
- fail-closed checks for finish reason, chunk-only output, exact IDs, URLs, commands, placeholders, and critical digits.

Do not use retry to conceal semantic deletion, context leakage, changed identifiers, or hallucinated content.

### Not promoted

- **E2B:** useful as a fast raw-JSON follower, but not admitted for long cleanup without prompt-specific evidence that punctuation and paragraph cleanup is actually performed.
- **E4B:** blocked for unattended long cleanup by deterministic M05 runaway and observed silent deletions.
- **26B MoE:** not promoted because it is slower and did not demonstrate a stable quality or schema advantage over 12B.

## 6. Evidence limits and non-claims

- The benchmark evaluates post-processing of frozen Whisper-derived text, not acoustic recognition, WER/CER, diarization, VAD, or timestamp accuracy against audio.
- L02 retention fields are model-produced structured values; they are not a source-to-output alignment proof for every transcript unit.
- Loaded-session or parallel timing does not prove physical KV-cache reuse without server-side cache telemetry.
- GPU load text does not prove physical per-layer placement or complete VRAM utilization.
- Const-heavy positional schemas were blocked at P4; compact generic schemas passed
  80/80 repaired requests. This does not establish P4 for every schema complexity,
  context size, or hardware placement.

## 7. Closure

The statistical experiment is closed with these operational choices:

- primary model: Gemma 4 12B QAT;
- supported concurrency: P1/P2 and bounded P4 with compact generic schemas;
- rejected P4 contract: request-specific positional schemas with 25 separate `const`
  constraints;
- preferred long-context representations: plain text or JSON blocks;
- timestamped full context requires additional boundary controls;
- all private raw evidence remains outside version control.
