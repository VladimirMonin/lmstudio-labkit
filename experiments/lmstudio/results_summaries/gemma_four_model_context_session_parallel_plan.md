# Four-model Gemma context, loaded-session, and parallelism closure plan

Status: approved execution plan; no new runtime verdicts are implied by this document.

## Purpose

The prior evidence wave resolved structured JSON normalization, reasoning controls,
native PNG vision transport, grounding review, lifecycle cleanup, and narrow 8k/16k
canaries. It did **not** complete the central operational comparison needed for
large-document processing:

- exact context-size effects;
- cold requests versus one compatible loaded session;
- a large stable message followed by changing chunk messages;
- repeat-prefix timing and output quality;
- request parallelism within one loaded model.

A canonical matrix that contains zero-call or stop-gated rows is an evidence
ledger, not an executed operational matrix. Runtime defaults must not be frozen
from those unexecuted rows.

## Supported comparison scope

Only these exact model families are in the current operational plan:

1. `google/gemma-4-e2b`;
2. `google/gemma-4-e4b`;
3. `google/gemma-4-12b-qat`;
4. `google/gemma-4-26b-a4b-qat`.

Unsloth/31B is excluded from the current supported and admission scope. Legacy
31B artifacts remain historical records only.

## Existing evidence that must be preserved

### Context

- E2B and E4B passed the narrow L3.31a 16k transcript, simple JSON, and blocks
  cells.
- 12B passed 16k transcript and simple JSON. Its old compatible-route blocks
  failure was not broad context degradation: native reasoning-off blocks later
  passed at both 8k and 16k.
- 26B native blocks passed at 8k and 16k with reasoning off and on in the narrow
  canary.
- The planned 4k, 12k, and 28k L3.39 rows were zero-call because an exact
  tokenizer-count map was unavailable. They are not runtime evidence.

### Loaded-session and repeated-prefix behavior

- E2B stateful versus full-prefix evidence showed a small timing signal, not a
  physical-KV proof.
- E4B completed the narrow L3.33a loaded-session quality set.
- 12B exact-repeat and stable-prefix/changing-suffix experiments showed strong
  first-to-warm timing signals. The later native reasoning-off records became
  6/6 schema-valid after deterministic removal of one complete Markdown JSON
  fence.
- 26B has no comparable cache/session A/B evidence.

These observations justify testing loaded-session processing as an operational
optimization. They do not identify the internal optimization mechanism. Current
LM Studio APIs do not document a cache-hit flag, reused-token counter, avoided
prefill metric, or physical KV-cache state.

## Prerequisite: exact token-fit assets

For each exact installed model, produce deterministic input payloads targeting:

- 4k;
- 8k;
- 12k;
- 16k;
- 28k tokens, when supported by the model/runtime.

Each payload record must contain only publication-safe metadata:

- model and exact variant;
- tokenizer identity and version;
- serialized-request SHA-256;
- stable-prefix SHA-256;
- byte length;
- exact token count;
- output-token reserve;
- safety margin;
- final fit verdict.

Private source text must not be published. Approximate character-to-token ratios
must not be used as admission evidence.

## Phase A: one-shot context matrix

For every model and supported context tier, execute these task classes:

1. transcript cleanup;
2. simple structured JSON;
3. blocks structured JSON.

Use reasoning off as the primary comparison where the installed capability
supports it. Reasoning-on comparisons are separate rows and must not replace the
reasoning-off baseline.

Record:

- HTTP and terminal status;
- route and installed runtime version;
- model instance identity;
- input, output, and reasoning tokens;
- time to first token and total latency;
- finish reason;
- raw JSON validity;
- deterministic fence-normalized validity;
- fixed-schema validity;
- task-quality verdict;
- cleanup read-back.

A schema failure is a result. It does not automatically suppress unrelated
context or transcript rows. Stop the lane only for load failure, context
rejection, repeated transport failure, privacy failure, or cleanup failure.

## Phase B: large stable message plus changing chunks

Use the application-shaped request sequence:

```text
message 1: large stable instructions/document context
message 2: changing chunk 1, 2, 3, ...
```

For each model, compare three controls under the same route, context, output cap,
and quality rubric:

### Cold full-prefix baseline

Each chunk is processed independently with the complete stable prefix.

### Compatible loaded session

Load one model instance, keep message 1 byte/token stable, and change only
message 2 between sequential requests. Do not unload between chunks.

### Exact-repeat control

Repeat one identical chunk within the same loaded session. This establishes the
upper timing signal for repeatable work but does not by itself prove physical KV
reuse.

Minimum sequence per selected context tier:

1. one cold request;
2. first loaded-session request;
3. three changing chunks;
4. two exact repeats;
5. verified unload and final loaded-state read-back.

Every private output must be reviewed for instruction retention, current-chunk
accuracy, cross-chunk contamination, raw/normalized/schema validity, and semantic
quality. Timing without accepted output quality is not operational admission.

## Phase C: request parallelism

Test requests against one loaded model instance at:

- `n_parallel=1`;
- `n_parallel=2`;
- `n_parallel=4`, only if the runtime and resource preflight accept it.

Do not load different models in parallel. Use the same chunk batch and stable
prefix for each parallelism level.

Record:

- effective load configuration;
- per-request TTFT and latency;
- whole-batch wall time and throughput;
- token and finish accounting;
- quality and schema pass rate;
- timeout/error rate;
- model-instance continuity;
- cleanup outcome.

The result must determine whether concurrency improves useful throughput or only
increases latency, memory pressure, and quality failures.

## Bounded first-pass matrix

Avoid another broad, unbounded research wave. The first operational pass is:

### Per model

- context tiers: 8k, 16k, and 28k;
- tasks: simple JSON and blocks JSON — 6 calls;
- one 16k cold/loaded-session sequence — 7 calls;
- one three-chunk batch at parallelism 1, 2, and 4 — 9 calls.

Maximum first pass:

```text
22 calls per model
88 calls across four models
```

Execution remains serial by model. Any unsupported context or parallelism row is
recorded explicitly without substitution. Expansion to transcript cleanup or 4k
and 12k calibration rows happens only when the first pass exposes a concrete
routing or fit question.

## Required output

Publish one operational comparison table:

| model | context | task | mode | parallelism | first latency | warm latency | speedup signal | batch throughput | quality | schema | cleanup |
|---|---:|---|---|---:|---:|---:|---:|---:|---|---|---|

The decision record must answer:

- which model should process a large document;
- recommended stable-prefix and chunk sizes;
- whether keeping the model loaded improves useful work;
- whether changing chunks retain the observed warm timing signal;
- recommended request parallelism per model and context;
- where quality or schema compliance degrades;
- whether 26B provides enough quality benefit to justify its latency/resources;
- whether E2B/E4B are suitable fast preprocessing tiers;
- whether 12B is the best quality/throughput balance.

## Claim boundary

Use these terms:

- `cold_per_request`;
- `compatible_loaded_session`;
- `native_stateful_continuation`;
- `first_to_warm_timing_signal`.

Do not claim `KV cache hit`, physical KV reuse, cache persistence, or causal cache
acceleration unless a future officially documented server metric or lower-level
request-linked runtime trace establishes it.

## Closure criterion

Only after this matrix is executed may the project freeze:

- default context;
- maximum supported context;
- chunk size;
- loaded-session policy;
- recommended parallelism;
- per-model task routing.

The matrix is complete only when executed cells have private-answer quality review,
all unexecuted cells have concrete unsupported/stop reasons, every model boundary
has verified cleanup, and the final recommendations are derived from useful
throughput rather than latency alone.
