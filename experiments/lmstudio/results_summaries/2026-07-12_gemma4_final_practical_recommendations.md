# Gemma 4 final practical recommendations

Date: 2026-07-13

Status: evidence synthesis after the bounded closure runs. No model is production-admitted.

## Plain-language decision

Use **Gemma 4 12B QAT** as the first quality-oriented transcript-cleanup candidate.

Use workload-qualified concurrency:

- **Full approximately 23k-token prefix in the tested 32k runtime:** run sequentially at P1. The two concurrent middle/late requests were rejected before generation in both plain and block lanes.
- **Bounded approximately 8k compact generic-schema workload:** P2 passed, and repaired P4 passed structurally. Do not transfer that admission to the 23k shape.

Use plain full context by default. Use compact generic JSON blocks when application-owned IDs and merge identity are required. Keep request-specific IDs out of the runtime grammar and validate count, uniqueness, exact set, and order after generation.

Retry policy must distinguish two failure classes:

- A pre-generation capacity rejection may be rescheduled once sequentially. This recovery was observed.
- A generated malformed/schema-invalid response may receive one structural retry as policy, but that path was not validated by the closure run.

Never present fallback as model success.

## Closure evidence boundary

The new closure contains 15 attempts:

| Group | Attempts | HTTP 200 | HTTP 400 | `stop` | `length` |
|---|---:|---:|---:|---:|---:|
| E2B/E4B same-prompt plain-output vs schema-output A/B | 4 | 4 | 0 | 3 | 1 |
| E2B exact schema-output repeat | 1 | 1 | 0 | 0 | 1 |
| 12B plain warmup, P2, and sequential recovery | 5 | 3 | 2 | 3 | 0 |
| 12B blocks warmup, P2, and sequential recovery | 5 | 3 | 2 | 3 | 0 |
| **Total** | **15** | **11** | **4** | **9** | **2** |

The A/B changed the **response contract**, not the full-context input representation. Both arms used the same plain full context and current chunk. It must not be cited as plain-context versus JSON-context evidence.

The semantic audits read the successful 12B plain and block outputs against the frozen source and manual gold. Private text and locators are not reproduced here.

## Model recommendations

### E2B

**Proven**

- Long plain cleanup at about 23.4k prompt tokens completed 5/5 with one byte-identical output. Meaning and chunk isolation were preserved, but useful punctuation and paragraph cleanup were weak.
- In the closure, the long compact schema-output arm failed 2/2 with the same visible output and usage outcome: HTTP 200, `finish=length`, 1,620/1,620 completion tokens, and 1,227 reasoning tokens. The JSON was partial and unparseable.
- This is a reasoning/output-budget interaction under the tested contract, not a general 23k-context collapse.
- E2B remains the strongest observed raw-JSON follower on bounded M01/M05 tasks and passed repaired generic-schema P4 structurally.

**Recommendation**

Use E2B only as a speed-first conservative copier or bounded JSON helper. Do not use the tested 23k compact schema-output contract. Keep semantic completeness and cleanup-gain checks mandatory.

**Unresolved**

No JSON-input early/middle/late matrix exists. A larger-budget or independently verified zero-reasoning E2B long schema-output run is unnecessary unless E2B remains an operational candidate for that lane.

### E4B

**Proven**

- Long plain input completed at about 23.4k tokens; a general large-context failure claim is false.
- One same-prompt long compact schema-output arm completed with `stop`, zero reasoning, parseable raw JSON, exact narrow schema, and complete current-chunk content.
- This is feasibility evidence for one schema-output cell, not repeated operational admission.
- JSON/timestamped **input representation** still caused a silent early-tail deletion in the separate controlled representation slice.
- M05 remains a deterministic malformed-runaway failure through 4,096, 8,192, and 16,384 output-token caps.

**Recommendation**

Keep plain input as the default. A compact schema-output wrapper may be tested only with semantic and completeness validation. Block M05 and equivalent repeated-tail shapes.

### 12B QAT

**Proven**

- 12B produced the strongest overall cleanup among the retained candidates on the frozen recording.
- The closure plain lane completed all three positions after sequential recovery. The semantic audit found all chunks complete and chunk-only, 13/13 exact protected numeric values, no large harmful deletion or unsupported addition, and an exact ordered merge. The result is a useful editorial draft, not publication-ready text.
- The closure block lane completed all three positions after sequential recovery and mechanically merged 24/24 expected IDs in exact order, with no missing, duplicate, or extra IDs. Semantic content and protected values were retained, but cleanup remained conservative and inconsistent.
- Initial middle/late P2 requests failed 0/4 across plain and block lanes with pre-generation context-capacity HTTP 400 errors. The same positions succeeded sequentially.
- Therefore, individual approximately 23k requests fit the tested 32k runtime, but two such requests do not fit concurrently in that configuration.
- Bounded 8k P2 passed at a 4,096-token output budget; repaired generic-schema P4 passed structurally. Those results do not admit full-23k P2/P4.

**Recommendation**

Use 12B QAT first. For the tested full-prefix shape, run P1/sequential. Use plain input when lower token cost and stronger editorial cleanup matter. Use compact blocks when exact application-owned identity and deterministic merge matter, while accepting weaker cleanup. Human review remains required for uncertain ASR terms and paragraphing.

**Unresolved**

No second recording, exhaustive source-unit alignment, audio truth, application persistence read-back, original-block fallback merge, or generated-output structural-retry validation exists.

### 26B MoE

**Proven**

- 26B did not demonstrate a stable quality advantage over 12B on the controlled source-shaped slice.
- It passed bounded P2 and repaired generic-schema P4 structurally, but was far slower in that lane.
- Some outputs retained content but under-edited late chunks; other cells damaged a critical item or technical names.

**Recommendation**

Use only when review on the exact workload demonstrates a quality gain worth the latency. Do not choose it merely because it is larger.

## Long context: plain, timestamps, and JSON input

Across the complete 27-output controlled representation slice, structured representations cost about 28–30% more input tokens than plain text.

- Plain input was the most conservative default on the single frozen recording.
- Timestamped input produced the only 12B cross-boundary continuation and added the greatest overhead.
- JSON input preserved identity structure but did not show a stable quality advantage. E4B lost the same early tail under timestamped and JSON input.

The closure A/B does not modify this conclusion because it changed only the output contract.

## Structured output

Use a compact generic schema such as an array of `{id, text}` objects. Keep expected IDs, source digests, protected values, retry state, and fallback state application-owned.

Validation order:

1. Require HTTP success and normal termination.
2. Parse raw JSON first; optionally recover one fully fenced document while recording that it was not raw JSON.
3. Validate the closed generic schema.
4. Validate exact item count, ID set, uniqueness, and order.
5. Validate chunk boundaries, protected values, omissions, unsupported additions, and repetition.
6. Accept only when every required gate passes.

A 25-position request-specific `const` grammar failed before generation at P4. The compact generic 25-item schema plus post-validation passed 80/80 structural requests. That P4 evidence retained no text and is not semantic-quality evidence.

## Concurrency

| Workload | Result | Recommendation |
|---|---|---|
| Bounded 8k compact generic schema | P2 passed; repaired P4 passed structurally | P2 conservative default; P4 allowed only after workload-specific structural and semantic qualification |
| Full approximately 23k prefix, plain and blocks | P2 middle/late failed 0/4 before generation; sequential recovery passed | P1/sequential in the tested 32k runtime |

Concurrency is a property of the combined model, context allocation, parallel slots, prompt size, schema, and output budget. Do not publish one global P2 or P4 admission.

## Retry, merge, and fallback

Observed:

- Four full-prefix P2 attempts were rejected before generation.
- Sequential rescheduling recovered all four positions.
- Plain merge was an exact ordered concatenation of three successful outputs.
- Block merge contained 24/24 exact IDs in order.

Not observed:

- Retry after malformed JSON, schema mismatch, reordered IDs, semantic omission, or length termination.
- Original-block fallback merge.
- Persistence projection and read-back through the active application.
- Merge idempotence.

Call the observed behavior **sequential capacity recovery** and **mechanical in-memory merge**, not complete end-to-end fallback validation.

## Cache and loaded sessions

Lifecycle reuse and a cache hint exist. Some loaded follow-ups were faster. Physical KV reuse, avoided prefill, persistence, and request-linked cache hits remain unproven. Use a byte-stable prefix as an optimization opportunity, not as a published cache guarantee.

## GPU placement

Automatic and maximum-GPU placement both passed the bounded 12B P2 pair and showed no proven maximum-GPU benefit. Per-layer placement and physical VRAM telemetry were absent. Keep automatic placement until output-normalized, layer-aware evidence exists.

## Source-specific surfaces

- Microphone processing is not validated against audio truth and the active owner path.
- The frozen long recording is real transcript evidence, but the complete source extraction-to-persistence application path was not executed.
- Requested Russian-to-English translation remains untested; the inspected template direction was incompatible.

## Remaining minimal gaps

No further model call is required to choose the current safe default: 12B, plain or compact blocks as needed, sequential at the tested full-prefix size.

Only run additional calls for a concrete product decision:

1. A second recording to test generalization.
2. The active application persistence/fallback path.
3. An audio-grounded microphone path.
4. A reviewed Russian-to-English path.
5. A controlled capacity change only if full-23k P2 is operationally required.

## Final bounded recommendation

Use **Gemma 4 12B QAT** for the next integration rehearsal. Use **plain input and sequential execution** for the tested approximately 23k full-prefix workload. Use **compact generic blocks** when exact IDs and merge identity matter, with application-side validation. Treat outputs as reviewable drafts, preserve the original source, and fail closed on semantic or structural safety failures.

Nothing in the evidence establishes unattended production admission, semantic P4 quality, physical cache reuse, superior maximum-GPU placement, or source-specific microphone/translation readiness.
