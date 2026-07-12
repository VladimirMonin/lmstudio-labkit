# Gemma 4 Family Model Cards

Status: statistical closure. 12B QAT is the primary bounded rehearsal candidate; no tested model has unconditional unattended-production admission.

This document records sanitized aggregate evidence only. The benchmark used
publication-safe M01, M05, and L02-L views derived from real sanitized Whisper
assets; it does not publish raw private transcripts, prompts, or responses. The
exact tested family was `google/gemma-4-e2b`, `google/gemma-4-e4b`,
`google/gemma-4-12b-qat`, and `google/gemma-4-26b-a4b-qat`. Gemma 4 31B variants
were excluded.

## Statistical closure update

The later closure study executed 20 independent long/plain calls, 60 native
structured-output calls, true P2/P4 probes, and one 12B GPU-placement comparison.
See [the statistical closure report](../experiments/lmstudio/results_summaries/2026-07-12_gemma4_whisper_structured_parallel_statistics.md).

Current practical roles:

- **12B QAT:** primary candidate for long transcript cleanup and structured blocks;
  use an adequate output budget, explicit chunk boundaries, and reasoning disabled.
  Use sequential P1 for the tested approximately 23k full-prefix shape. Bounded 8k
  P2 and structural P4 results must not be transferred to that larger workload.
- **E2B:** fast raw-JSON/schema follower, but its five deterministic long/plain
  results preserved words without performing the required punctuation and paragraph
  cleanup.
- **E4B:** not recommended for unattended long cleanup because M05 runaway repeated
  in 5/5 statistical calls and at larger 8k/16k output controls.
- **26B MoE:** slower and did not show a stable quality/schema advantage over 12B.

P2 passed on all four models. The original P4 positional schema, with 25 per-position
`const` ID constraints, failed before generation. A generic 25-item blocks schema
repaired P4 to 5/5 batches and 20/20 exact-ID requests per model. `--gpu max` did not
improve the focused 12B P2 run.

The later application-shaped closure qualified those concurrency results. Four
concurrent middle/late requests with an approximately 23k full prefix were rejected
before generation, while the same positions completed sequentially. The 12B plain
merge retained all three chunks and 13/13 exact protected numeric values; the block
merge retained 24/24 IDs in exact order. E2B long schema-output failed 2/2 through
reasoning/output-budget exhaustion, while E4B completed one narrow long schema-output
cell. See [the final bounded recommendations](../experiments/lmstudio/results_summaries/2026-07-12_gemma4_final_practical_recommendations.md).

## Final evidence boundary

The historical run executed a complete 64-cell/80-call matrix across 8,192,
16,384, and 28,672 context tiers, loaded sessions, and P1/P2/P4 fan-out. It used a
prompt-embedded schema. Its 0/80 strict acceptance remains valid, but the earlier
interpretation that this implied no JSON, schema, or structure capability is
superseded.

The corrected matrix used 12 LM Studio Responses API calls: one call per model for
M01, M05, and L02-L. Requests bound native `json_schema` with `strict=true`, used
`reasoning.effort=none`, temperature 0, and a 28,672-token context. All 12 calls
reported `reasoning_tokens=0`. M01 and L02-L used 512 output tokens; M05 used 4,096.
Raw JSON, extracted/fenced JSON, exact schema, semantic fidelity, placeholder
fidelity, structural retention, and strict acceptance were scored separately.

| Model | Raw JSON | Extracted JSON | Exact schema | Semantic | Placeholders | L02-L | Strict | Practical role |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| E2B | 2/3 | 3/3 | 3/3 | 0/2 | 0/2 | 318/428 | 0/3 | first schema-following candidate after fidelity repair |
| E4B | 0/3 | 2/3 | 2/3 | 0/2 | 0/2 | 43/428 | 0/3 | blocked for M05 runaway |
| 12B QAT | 0/3 | 3/3 | 2/3 | 0/2 | 0/2 | 428/428 | 0/3 | structural-retention research candidate |
| 26B MoE | 0/3 | 3/3 | 1/3 | 0/2 | 0/2 | 427/428 | 0/3 | not a quality-ceiling choice from this evidence |

E2B is the strongest raw-JSON/exact-schema follower. 12B QAT preserves all 428
L02-L units. 26B MoE preserves 427/428 and follows the exact schema inconsistently.
No model satisfies the semantic and placeholder contracts, so no model passes the
strict operational gate.

## Earlier route-specific model cards (historical)

The table below preserves the L3.31-L3.38 canary record. It is not the final
real-asset admission result; the 2026-07-12 evidence above controls current
recommendations.

| model | load status | max proven context | transcript cleanup | structured simple | structured blocks | structured complex | vision route | cache/session | recommended role |
|---|---|---:|---|---|---|---|---|---|---|
| `google/gemma-4-e2b` | proven in accepted slices | 16384 canary scope | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted narrow for L3.32a E2B/E4B canary | not admitted; no L3.35 eligibility | not run in L3.33a | lightweight baseline |
| `google/gemma-4-e4b` | proven in accepted slices | 16384 canary scope | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | accepted narrow for L3.32a E2B/E4B canary | native plain text accepted for one asset; minimal JSON/broader screening blocked | accepted narrow for `session_loaded` none/warmup_first quality scope; KV reuse not proven | strongest current general candidate |
| `google/gemma-4-12b-qat` | proven in accepted slices | 16384 transcript/simple plus native reasoning-off blocks | accepted at 8192 and L3.31a 16k canary | accepted at 8192 and L3.31a 16k canary | native reasoning-off accepted narrowly at 8192/16384; native reasoning-on and OpenAI strict route blocked | blocked after one bounded 8192 case | not admitted; no L3.35 eligibility | blocked by L3.33a plus invalid repeated-16k research comparison | route-specific candidate; use only where reasoning can be explicitly disabled and locally validated |
| `google/gemma-4-26b-a4b-qat` | controlled only | 8192 controlled / 16k prepared | accepted controlled only | blocked/not run | blocked/not run | blocked/not run | not admitted; no L3.35 eligibility | not run | research/capacity constrained |

## E4B/M05 boundary diagnosis

Under the same native strict-schema contract, E4B/M05 exhausted 4,096/4,096,
8,192/8,192, and 16,384/16,384 output tokens. Every call reported zero reasoning
tokens and `finish_reason=stop`; each larger response preserved the complete prior
prefix and continued malformed non-JSON generation. The 16,384-token call remained
inside the 28,672-token context with 9,065 tokens of calculated headroom. This is a
runaway generation for the tested contract, not reasoning competition or context
choking. E4B/M05 remains blocked.

## Historical admitted scopes

- Default text/structured scope: 8192 context for E2B, E4B, and 12B on `transcript_cleanup/simple`, `structured_json/simple`, and `structured_json/blocks`.
- 16k canary scope: E2B and E4B passed transcript/simple/blocks; 12B passed transcript/simple on the established route and blocks only on the native reasoning-off diagnostic path.
- Complex JSON scope: E2B and E4B passed the 4-cell L3.32a canary at 8192.
- Cache/session scope: E4B passed the narrow L3.33a `session_loaded` none/warmup_first quality canary, but this is not KV reuse proof.
- 12B blocks diagnostic scope: native `/api/v1/chat` with reasoning explicitly `off` produced schema-valid output at the first 1024-token cap for both 8192 and 16384. This is local schema validation, not strict-route admission.

## Historical blocked modes

- 12B `structured_json/blocks` on OpenAI-compatible strict JSON remains blocked. L3.37 native reasoning-off succeeded, but native reasoning-on consumed every cap through 4096 entirely in reasoning and both strict confirmation cells were empty/length-capped at 1024.
- 12B complex JSON: blocked after one bounded adaptive `512 -> 1024` case ended at the truncation ceiling; no broad screening followed.
- 12B cache/session: blocked by two L3.33a finish-length failures and a later repeated-16k comparison with 6/6 invalid length-limited outputs.
- KV reuse/cache benefit: not claimed; timing-only evidence is signal, not proof.
- Vision/image: native E4B plain text is accepted narrowly for one asset, but minimal JSON failed malformed without truncation; L3.35 therefore has zero eligible models and zero attempts.
- 26B structured/cache/vision: not admitted beyond controlled transcript cleanup.
- Qwen: out of Gemma closure scope.

## Practical recommendations

1. Start future normalization repair with E2B, then require semantic and placeholder
   fidelity before operational admission.
2. Use 12B QAT only where structural retention is the research target; fenced JSON
   and normalization fidelity still fail the strict contract.
3. Keep E4B/M05 blocked pending a bounded fix for runaway generation.
4. Do not use 26B MoE as a presumed quality ceiling from this run.
5. Treat timing, loaded-session ratios, and P1/P2/P4 throughput as diagnostic only.
   No physical KV reuse, cache benefit, or production parallelism is claimed.

All model slices and E4B boundary calls ended with cleanup read-back
`loaded_total=0`.

## Earlier narrow gates (historical)

1. Verify an explicit reasoning-off contract on the production structured route, or keep native reasoning-off as an isolated narrow fallback with local schema validation. Do not treat larger output caps as a repair: they did not rescue reasoning-on through 4096.
2. Keep cache/session to `session_loaded`, `parallel=1`, explicit output caps, stable prefixes, and cleanup final zero; do not infer KV reuse from timing.
3. Repair native E4B minimal JSON on the already proven `/api/v1/chat` plain-text route before any L3.35 matrix.

## Canonical reports and provenance

- [Historical 64-cell/80-call synthesis](../experiments/lmstudio/results_summaries/2026-07-12_four_model_real_asset_benchmark_synthesis.md)
- [Historical machine report](../experiments/lmstudio/results_summaries/2026-07-12_four_model_real_asset_benchmark_synthesis.json)
- [Corrected native structured-output report](../experiments/lmstudio/results_summaries/2026-07-12_gemma4_native_structured_output_correction.md)
- [Corrected machine report](../experiments/lmstudio/results_summaries/2026-07-12_gemma4_native_structured_output_correction.json)
- Evidence commits: [`16bede4`](https://github.com/VladimirMonin/lmstudio-labkit/commit/16bede4), [`75565dd`](https://github.com/VladimirMonin/lmstudio-labkit/commit/75565dd), [`a5080dd`](https://github.com/VladimirMonin/lmstudio-labkit/commit/a5080dd), and [`fcfbefd`](https://github.com/VladimirMonin/lmstudio-labkit/commit/fcfbefd).

## Non-claims

This document does not claim production admission, physical KV reuse, cache benefit,
production parallelism, structured or broad image support, broad 12B/26B admission,
or publication of raw artifacts. Timing is not a quality result. The correction
changes capability attribution while preserving the historical evidence and strict
rejection outcome.
