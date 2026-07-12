# Host-application-shaped structured context and summary decision

Date: 2026-07-13

Status: bounded single-recording qualification for Gemma 4 12B QAT. This report does not grant production admission.

## Decision

Use separate local-model context policies for separate tasks:

- **Block-preserving cleanup:** current blocks plus the previous tail and next head boundary blocks.
- **Per-chunk summary:** current chunk only.
- **Fast whole-recording summary:** one direct full-transcript request.
- **Detailed whole-recording notes:** hierarchical synthesis over current-only chunk summaries.
- **Do not send the full transcript with every cleanup or chunk-summary request.** It was much more expensive, did not provide a stable quality gain, and introduced block-boundary risk.

The model returns only application-owned block IDs and processed text. Original timestamps remain outside the model contract and are restored deterministically by ID.

## Evidence scope

The source was one frozen, sanitized Whisper recording partitioned with the source application's 3,000-character whole-block planner into 35 chunks.

Measured model calls:

- 12 representative structured cleanup calls: 3 positions x 4 context strategies.
- 140 per-chunk summary calls: 35 chunks x 4 context strategies.
- 5 whole-recording summary calls.
- 24 reverse-order repeats of representative cleanup and chunk-summary cells.
- 5 repeat whole-summary calls.
- 4 cache/repeat probes.
- 12 P2/P4 qualification requests on the selected short-context contracts.
- **Total: 202 calls.** These calls are heterogeneous and are not treated as 202 independent quality observations.

Technical denominators:

| Series | Calls | HTTP 200 | Parseable structured output | Main caveat |
|---|---:|---:|---:|---|
| Primary | 157 | 157 | 155 | Two truncated chunk summaries |
| Repeat and cache | 33 | 33 | 32 | One truncated repeated full-context cleanup |
| Parallel screening | 12 | 12 | 12 | Unmatched P2/P4 chunk sets and separate loads |
| **Total** | **202** | **202** | **199** | Mixed tasks and evidence roles |

The four context strategies were:

1. `current_only`: current chunk or current blocks only.
2. `boundary_neighbors`: the previous chunk's last block and the next chunk's first block.
3. `adjacent_chunks`: complete previous and next chunks.
4. `full_transcript`: the full recording as reference context plus the current target.

All live calls used Gemma 4 12B QAT, temperature zero, disabled thinking/reasoning controls, and application-compatible chat payloads. Private source text and raw envelopes remain owner-only.

## Structured cleanup and timestamps

### Response contract

Use a compact generic schema:

```json
{
  "blocks": [
    {
      "id": 123,
      "text": "Processed text"
    }
  ]
}
```

Do not ask the model to generate `start` or `end`. Keep this source-owned mapping:

```text
block ID -> original start/end -> processed text
```

Acceptance must require:

- normal HTTP and finish status;
- zero reasoning leakage;
- valid raw JSON;
- exact expected item count;
- exact ID set and order;
- zero missing, duplicate, or extra IDs;
- non-empty strings;
- semantic ownership of each text by its original block;
- protected-value and boundary checks.

### Technical result

All 12 first-pass cleanup calls returned HTTP 200, `finish=stop`, zero reasoning, valid JSON, and exact IDs/order.

The 36 evaluated output blocks retained exact source IDs, enabling deterministic external reattachment of original timestamps. The model did not generate or normalize timestamps. This was not an end-to-end persistence or subtitle-export round trip.

### Semantic comparison

| Strategy | Result | Decision |
|---|---|---|
| Current only | Conservative, local, low-cost; sometimes leaves an interrupted boundary unresolved | Safe conservative option |
| Boundary neighbors | Best observed balance; one useful boundary repair without observed external-text leakage in the first pass | Default cleanup context |
| Adjacent chunks | No stable quality gain; one context-driven questionable correction | Do not use by default |
| Full transcript | One first-pass block-boundary leak; one repeat reached 4,096 output tokens and returned malformed JSON | Reject for block-preserving cleanup |

The full-context boundary leak moved text between IDs and included following material under the wrong block identity. Because timestamps remain fixed by ID, this is also a timing-attribution defect.

The recommended local cleanup request therefore contains:

```text
previous boundary block (reference only)
current blocks (the only output target)
next boundary block (reference only)
```

The reference blocks must be visibly separated from the target and explicitly forbidden from appearing in output.

## Per-chunk summaries

### First-pass reliability

| Strategy | HTTP 200 | `finish=stop` | Practically valid structured output |
|---|---:|---:|---:|
| Current only | 35/35 | 35/35 | 35/35 |
| Boundary neighbors | 35/35 | 34/35 | 33/35 |
| Adjacent chunks | 35/35 | 34/35 | 34/35 |
| Full transcript | 35/35 | 35/35 | 35/35 |
| **Total** | **140/140** | **138/140** | **137/140** |

Two extended-context calls degenerated inside structured generation, reached the 1,024-token cap, and returned unparseable JSON. A third boundary-neighbor response was JSON-parseable at `finish=stop` but contained structured-field garbage and was not practically valid. Increasing the token cap is not the appropriate repair for cyclic schema-field generation.

### Cost and latency

Medians:

| Strategy | Prompt tokens | Completion tokens | Request latency |
|---|---:|---:|---:|
| Current only | 786 | 373 | 8.04 s |
| Boundary neighbors | 1,040 | 381 | 8.22 s |
| Adjacent chunks | 2,107 | 377 | 8.60 s |
| Full transcript | 23,099 | 390 | 20.20 s |

Current-only summaries had the best combination of locality, schema reliability, cost, and faithful coverage. Boundary context sometimes helped an interrupted thought but also introduced neighboring material. Complete adjacent chunks increased leakage without a stable quality gain. Full context was far more expensive and tended to globalize entities and framing.

### Summary schema guidance

The evaluated `entities` field was the weakest part of the schema and participated in the two runaway responses. Prefer either removing it or replacing free-form strings with a constrained structure such as:

```json
{
  "text_as_heard": "...",
  "canonical": null,
  "type": "person|product|organization|technology|other",
  "confidence": "high|medium|low",
  "source": "current_chunk"
}
```

Separate source uncertainty from model uncertainty. Limit summary length and key-point count. Require raw JSON parsing even when `finish=stop`.

## Whole-recording summaries

All five first-pass whole-summary calls and all five repeats completed normally. Every repeated whole-summary output was byte-identical to its first-pass counterpart.

### Direct full summary

Use when one compact executive overview is sufficient. It was simple and fast as a pipeline, but compressed the beginning and late practical material and sometimes elevated a discussed option into a decision.

### Hierarchical summary

Use current-only chunk summaries followed by one final synthesis when chronological coverage and practical detail matter. On this one recording, expert review preferred this result for coverage of early, middle, and late material. No blind or multi-rater semantic score was used.

Do not provide the full transcript to every chunk-summary call. Across 35 chunks, full-context chunk summarization consumed about 807,600 prompt tokens and about 700.7 seconds of summed request time, without a proportional semantic gain. Current-only chunk summarization used about 26,700 prompt tokens and about 274.9 seconds.

## Repeatability

The reverse-order representative repeat contained 24 cleanup and chunk-summary calls:

- HTTP 200: 24/24.
- Zero reasoning: 24/24.
- `finish=stop`: 23/24.
- Byte-identical to first pass: 22/24.
- All 12 repeated representative chunk summaries were byte-identical.
- All 5 repeated whole summaries were byte-identical.

The non-identical current-only cleanup remained valid. The non-identical full-context cleanup reached 4,096/4,096 output tokens and returned malformed JSON. This repeat strengthens the rejection of full context for block-preserving cleanup.

## Cache and repeated requests

The four probes used one loaded model and `cache_prompt=true`:

| Probe | Result | Latency |
|---|---|---:|
| First full-prefix request | Passed | 22.4 s |
| Exact request repeat | Passed | 11.8 s |
| Same prefix, changed chunk | Passed | 22.2 s |
| One-byte-changed prefix, same changed chunk | Passed | 23.2 s |

The exact repeat was substantially faster in one fixed sequence. The same stable full prefix with a changed suffix was not. The runtime returned no request-linked `cached_tokens`, cache-hit flag, or reused-prefix count. The probe did not randomize order, repeat cold/warm cycles, or capture TTFT/prompt-evaluation telemetry.

Classification:

- **Proven:** all four requests completed; exact-repeat timing improved in this sequence.
- **Timing signal:** exact-request reuse or warm runtime behavior may exist.
- **Unproven:** stable-prefix reuse for changing chunks, physical KV-cache reuse, avoided prefill, and persistent cache semantics.

Do not make full-transcript-per-chunk architecture depend on an unverified cache effect.

## P2 and P4 qualification

Selected short-context contracts were tested without retries:

| Task | P2 | P4 |
|---|---:|---:|
| Boundary-neighbor structured cleanup | 2/2 accepted | 4/4 accepted |
| Current-only chunk summary | 2/2 accepted | 4/4 accepted |

All 12 requests returned HTTP 200, `finish=stop`, zero reasoning, and accepted structure. Cleanup responses also preserved exact IDs/order.

Measured batch wall times:

- cleanup P2: 17.19 s;
- cleanup P4: 23.39 s;
- summary P2: 9.73 s;
- summary P4: 11.61 s.

Semantic review found no cross-request contamination or critical protected-value damage in the 12 parallel outputs. The six current-only summaries remained useful. The six cleanup outputs retained block identity but remained conservative editorial drafts, and some P4 cleanup wording was weaker than P1/P2.

This is a P2/P4 screening result only for these bounded short-context contracts and this runtime configuration. P2 and P4 used different chunk sets, separate model loads, and no matched P1 baseline or GPU telemetry. It does not establish a production concurrency default and does not qualify full-transcript P2/P4.

## Recommended future local-model behavior

### Block-preserving cleanup

```text
model: Gemma 4 12B QAT
context: current blocks + previous tail + next head
output: generic structured {id, text}
parallelism: P2 conservative screening candidate; P4 requires matched repeated qualification before production use
reasoning/thinking: disabled
retry: one structured retry only after a generated invalid response
fallback: original source block text
```

The application remains authoritative for IDs, timestamps, expected cardinality, protected values, retry state, and fallback state.

### Per-chunk summaries

```text
context: current chunk only
output: short constrained structured summary
parallelism: P2 conservative screening candidate; P4 requires matched repeated qualification before production use
```

Boundary context should be an explicit targeted fallback for interrupted boundaries, not a default summary context.

### Whole-recording summary

```text
fast overview: direct full-transcript summary
rich notes: current-only chunk summaries -> hierarchical synthesis
```

## Remaining evidence limits

- One recording and one selected model were evaluated.
- Cleanup semantics were deeply reviewed on early/middle/late representatives, not all 35 chunks.
- Parallel outputs passed structural gates and bounded semantic review, but P2/P4 chunk sets and loads were unmatched and production concurrency remains unqualified.
- No audio-grounded truth was available for uncertain proper names.
- No persistence/read-back or subtitle-export integration was executed in the source application.
- No physical cache telemetry was available.
- No blind or multi-rater semantic scoring was performed.

These limits do not require more broad model-family testing. The next implementation proof should be a source-application integration test using a fake structured client for ID/timestamp persistence, retry, fallback, and export, followed by a bounded live canary on the selected 12B contracts.
