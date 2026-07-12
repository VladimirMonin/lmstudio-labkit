# Parallel, cache/session, and GPU runtime audit

Date: 2026-07-12

## Scope and evidence boundary

This audit independently checks the published parallel, cache/session, stable-prefix,
and GPU-placement claims. No model was loaded and no inference was run.

Public evidence is cited by repository path. Private inspection was limited to
owner-only P2 batch summaries and request metrics, P4 positional-schema errors,
twenty repaired P4 batch records, system samples, and the 12B GPU load read-back.
No private prompt or completion text is reproduced here.

Classification used for cache claims:

- `PROVEN`: directly established by retained code, deterministic tests, or runtime
  evidence for the bounded claim;
- `TIMING_SIGNAL`: measured timing is consistent with reuse, but the mechanism is
  not identified;
- `UNPROVEN`: the retained evidence does not establish the claim.

## Executive conclusion

True request overlap is established for the inspected P2 and P4 batches. The
runtime applied the admitted parallelism, application concurrency matched it, and
concurrent batch wall time was close to the longest request rather than the sum of
request durations. This proves overlap, not cache reuse.

P2 is the safe default. P4 is bounded evidence only for the compact generic
25-item schema plus strict post-generation ID/order validation. The repaired P4
lane passed 80/80 structurally, but its generated text was neither retained nor
semantically reviewed. It therefore proves transport, termination, grammar, item
count, and identity/order behavior—not text fidelity or cleanup quality.

The 12B automatic-versus-maximum-GPU comparison proves 2/2 structural success in
both modes and no observed gross allocation increase. It does not prove equivalent
layer placement or a speed regression: generated-token totals differed and no
per-layer or physical VRAM telemetry was retained.

## 1. Parallel overlap and denominators

### P1

The positional P4 workload has successful sequential warmups, so a single request
could generate with that schema. The inspected closure does not retain a repeated,
denominator-matched P1 throughput matrix for the repaired generic-schema workload.
P1 viability is therefore partial evidence, not a P1/P2/P4 scaling curve.

### P2

| Model | Measured requests | Business pass | Batch wall | Audit result |
|---|---:|---:|---:|---|
| E2B | 4 | 4 | 30.8 s | pass; two admitted slots |
| E4B | 4 | 4 | 45.5 s | pass; two admitted slots |
| 12B, 1,875 output tokens | 2 | 0 | 43.2 s | 2/2 valid length failures |
| 12B, 4,096 output tokens | 2 | 2 | 57.4 s | repaired to 2/2 pass |
| 26B, 4,096 output tokens | 2 | 2 | 127.5 s | pass |

The E2B and E4B four-request runs completed as two-slot work: summed request time
was approximately twice batch wall time. In each direct two-request 12B/26B run,
mean request latency was close to pair wall time. Those relationships are
incompatible with wholly serial execution and independently support real overlap.

The P2 evidence is in the private metric-only batch class summarized by
`experiments/lmstudio/results_summaries/2026-07-12_gemma4_whisper_structured_parallel_statistics.json`.
Raw prompt/response storage was disabled.

### P4: const-heavy failure

The initial schema bound each of 25 array positions to a separate request-specific
`const` ID. Sixteen measured requests—four per model family—returned HTTP 400
before useful generation. The failure is correctly classified as configuration or
runtime-grammar failure, not model-quality failure.

The diagnosis is supported by controls:

- one sequential warmup generated successfully for each model family;
- plain P4 requests passed;
- a minimal JSON-schema P4 passed;
- reducing context did not repair the positional schema;
- replacing per-position constraints with a generic 25-item schema repaired P4.

The evidence supports “const-heavy positional grammar caused this bounded P4
failure.” It does not establish a universal grammar-complexity threshold.

### P4: generic-schema repair

| Model | Batches | Requests | Structural pass | Mean request latency | Range |
|---|---:|---:|---:|---:|---:|
| E2B | 5 | 20 | 20/20 | 15.584 s | 15.368–15.681 s |
| E4B | 5 | 20 | 20/20 | 18.103 s | 17.683–18.291 s |
| 12B | 5 | 20 | 20/20 | 19.340 s | 18.943–19.525 s |
| 26B | 5 | 20 | 20/20 | 64.725 s | 60.432–69.234 s |

Each retained repaired request records HTTP 200, `finish=stop`, zero reasoning
tokens, exactly 25 items, and exact IDs/order. Across twenty four-request batches,
that is 80/80 structural success.

Semantic review status: **not performed**. The repaired batch records contain no
raw output text or source-alignment verdict. “Business pass” in this lane is an
identity/order contract, not a manual judgment of meaning. Text fidelity,
completeness, harmful deletion, hallucination, and source alignment remain unknown.

### Latency denominator rules

- Request latency is one measured request. P4 means/ranges use 20 requests per
  model.
- Batch wall is one concurrent measured batch and excludes sequential warmup.
- End-to-end time, where retained, is warmup plus measured batch.
- Request latencies overlap and must not be added to batch wall as serial time.
- The repaired P4 repeat-five set has no denominator-matched P1 baseline, so it
  supports bounded reliability and overlap but not a P4-versus-P1 speedup claim.

## 2. Output-budget repairs

The 12B P2 pair at 1,875 output tokens ended `finish=length` in 2/2 measured
requests. Holding the workload and concurrency fixed while increasing the cap to
4,096 repaired the cell to 2/2 business pass. The 26B P2 pair also passed at 4,096.
This is valid evidence that the smaller cap was insufficient for those cells.

A separate 12B loaded-session canary preserved its explicit 128-token caller cap,
but all six requests ended at length with empty visible output. That artifact
proves budget propagation, not successful cache/session processing. See
`experiments/lmstudio/results_summaries/t_ebbc0256_gemma_12b_session_cache_comparison.md`.

## 3. Cache/session and stable-prefix claims

| Claim | Class | Evidence and boundary |
|---|---|---|
| The source application serializes lifecycle ownership and reuses a compatible loaded runtime | `PROVEN` | Pinned static review and deterministic owner-path tests in `l3_33b_cache_evidence_import_from_source_application.md` |
| The source application emits `cache_prompt=true` for LM Studio payloads | `PROVEN` | Pinned payload-builder review and deterministic payload tests in the same report |
| The source application creates a byte-stable LM Studio prefix | `UNPROVEN` | The inspected builder ignores the provider-style cacheable-prefix seam |
| Awaiting request one materializes a cache | `UNPROVEN` | It proves ordering only; no cache-materialization signal exists |
| E2B native stateful root/branch operation works in the small probe | `PROVEN` | Requests completed and lifecycle cleanup was verified in `2026-07-05_l3_4_cache_stateful_vs_prefix_gemma_e2b_live_summary.md` |
| E2B stateful execution benefited from reuse | `TIMING_SIGNAL` | One run was 4.3% faster than full-prefix; another had lower prompt-processing timing, but no cached-token signal |
| 12B exact repeats benefited from session/runtime reuse | `TIMING_SIGNAL` | Follow-ups were much faster than the first request, but all outputs failed and `cached_tokens` was unavailable |
| 12B stable-prefix/changing-suffix benefited from reuse | `TIMING_SIGNAL` | Follow-ups were faster, but all outputs failed and no runtime cache counter existed |
| Physical KV reuse, a cache hit, cache persistence, or avoided prefill occurred | `UNPROVEN` | No positive request-linked cached/reused-token count, cache-hit flag, or physical KV trace was retained |

The E2B instrumentation probe did expose TTFT and prompt-processing timing, which
is useful observability. It did not expose cached tokens. See
`2026-07-05_l3_4b_cache_stateful_instrumentation_gemma_e2b_live_summary.md`.

For 12B, the exact-repeat first request was 193.8 s and follow-ups were about 3.1 s;
the stable-prefix first request was 26.6 s and follow-ups about 16.8 s. These are
large timing signals, but all six responses were empty length terminations. Timing
without valid output is not operational admission. The public aggregate is
`experiments/lmstudio/live_runs/t_ebbc0256/sanitized_aggregate.json`.

There is no comparable cache/session A/B for 26B.

## 4. GPU automatic placement versus maximum GPU

| Mode | Structural result | Load report | Process read-back | Batch wall | Completion tokens |
|---|---:|---:|---:|---:|---:|
| automatic | 2/2 | 6.66 GiB | not retained in the comparison summary | 57.4 s | 4,960 |
| maximum GPU | 2/2 | 6.66 GiB | 7.15 GB | 66.3 s | 5,396 |

Facts:

- both modes passed the same 12B P2 task class at a 4,096-token cap;
- the model load report remained 6.66 GiB;
- maximum-GPU wall time was longer in this single pair.

Interpretation: there is no demonstrated benefit from maximum-GPU placement.

Non-claim: the comparison does not prove automatic placement is faster or optimal.
Completion totals differ by 436 tokens, and retained evidence lacks per-layer
placement, physical VRAM allocation, request-level TTFT/prefill, and normalized
throughput. The process read-back is not a layer map.

## 5. Operational recommendation

Use P2 as the conservative default.

Admit P4 only when all of the following hold:

1. the runtime schema is compact and generic;
2. application validation enforces exact identity, order, duplicates, missing and
   extra items;
3. the specific task has semantic review evidence, not only structural validation;
4. resource and timeout preflight passes for the exact model/context;
5. cleanup and loaded-state read-back remain verified.

Do not admit const-heavy positional schemas at P4. Do not advertise physical cache
reuse. Do not force maximum-GPU placement on the current evidence.

## 6. Observability and evidence gaps

1. Request start and finish timestamps tied to worker slots are absent from the
   repaired P4 records; overlap is established indirectly from concurrency and
   wall-time arithmetic rather than a retained interval trace.
2. A denominator-matched P1/P2/P4 useful-throughput comparison is absent for the
   repaired generic schema.
3. P4 output text was not retained and was not semantically reviewed.
4. Request-linked cached/reused input-token telemetry is absent.
5. Parallel TTFT and prompt-processing measurements are not consistently retained.
6. Per-layer GPU placement, physical VRAM, utilization, and power are absent from
   the auto/max comparison.
7. The GPU comparison is not output-token normalized.
8. 26B has no cache/session A/B.

## Fact, interpretation, and hypothesis

Facts: P2 requests overlap; the bounded generic P4 lane passed 80/80 structural
checks; the positional const-heavy P4 lane failed before generation; both 12B GPU
modes passed; runtime cache counters were absent.

Interpretation: P2 is the defensible default, generic-schema P4 is a bounded
structural option, and maximum-GPU placement has no proven benefit.

Hypothesis: generic schemas reduce concurrent grammar pressure, and some loaded
session/prefix timings may reflect prefix or KV reuse. Neither mechanism is proven
without request-linked runtime telemetry.
