# Four-model real-asset benchmark synthesis

> **Correction:** this historical matrix embedded the output schema in the prompt but did not
> bind LM Studio native structured output. Its strict `accepted=0` result remains historical
> evidence, but it must not be interpreted as absence of JSON, exact-schema, or structural
> capability. See `2026-07-12_gemma4_native_structured_output_correction.md` for the focused
> native-schema rerun and corrected admission interpretation. Its E4B/M05 addendum proves that the
> malformed response exhausted 4,096-, 8,192-, and context-safe 16,384-token budgets while the
> runtime reported `finish_reason=stop` and zero reasoning tokens. This is continued runaway
> generation truncated at each configured budget, not a response choked by reasoning or context.

## Decision

None of the four models is operationally admitted under the current prompt, schema, and scoring contract. All 80 calls were independently reviewed and all 80 were rejected. Timing remains useful only as a diagnostic signal.

## Canonical accounting

| Measure | Count |
|---|---:|
| Planned cells | 64 |
| Planned calls | 80 |
| Executed cells | 64 |
| Executed calls | 80 |
| Reviewed outputs | 80 |
| Accepted results | 0 |
| Zero-call rows | 0 |

Every canonical row is present in the machine-readable report. No row was blocked, stop-gated, unsupported, or skipped.

## Asset structure and context

| View | Complexity | Acceptance scope | Calls per model | Context tiers |
|---|---|---|---:|---|
| M01 | Simple normalization | Semantic gold | 3 | 8,192 / 16,384 / 28,672 |
| M05 | Stress normalization | Reference-relative only | 10 | 8,192 / 16,384 / 28,672; loaded/parallel at 16,384 |
| L02-L | Long structural retention | Structural only | 7 | 16,384 |

## Quality and structure

| Model | M01 exact schema | M05 exact schema | L02-L JSON object | Structural retention | Accepted |
|---|---:|---:|---:|---|---:|
| E2B | 3/3 | 7/10 | 0/7 | 318–427 of 428 | 0/20 |
| E4B | 3/3 | 3/10 | 0/7 | 43–427 of 428 | 0/20 |
| 12B QAT | 0/3 | 9/10 | 0/7 | 428–428 of 428 | 0/20 |
| 26B MoE | 0/3 | 7/10 | 0/7 | 387–427 of 428 | 0/20 |

The 12B QAT model retained all 428 structural units in every L02-L call, but fenced output failed the required raw JSON-object contract. The 26B MoE model was coherent but reported 427 units in six calls and 387 in one. E2B and E4B showed weaker and variable retention. These observations do not override the zero accepted results.

## Loaded-session timing signal

| Model | Cold full prefix (s) | Loaded follow-up median (s) | Observed ratio | Operationally admitted |
|---|---:|---:|---:|---|
| E2B | 3.146 | 1.335 | 2.36× | No |
| E4B | 5.606 | 2.759 | 2.03× | No |
| 12B QAT | 9.436 | 3.837 | 2.46× | No |
| 26B MoE | 34.758 | 9.173 | 3.79× | No |

The ratios compare recorded cold-full-prefix latency with the median of six subsequent loaded-session calls. They demonstrate observed loaded-session speedup only. They do not prove physical KV reuse because no server-side cache telemetry was captured.

## P1/P2/P4 timing signal

| Model | Level | Calls | Cell wall (s) | Calls/s | Median call latency (s) | Operationally admitted |
|---|---|---:|---:|---:|---:|---|
| E2B | P1 | 1 | 5.841 | 0.171 | 5.841 | No |
| E2B | P2 | 2 | 6.577 | 0.304 | 6.347 | No |
| E2B | P4 | 4 | 11.575 | 0.346 | 10.979 | No |
| E4B | P1 | 1 | 23.499 | 0.043 | 23.499 | No |
| E4B | P2 | 2 | 10.449 | 0.191 | 9.371 | No |
| E4B | P4 | 4 | 33.769 | 0.118 | 17.033 | No |
| 12B QAT | P1 | 1 | 10.027 | 0.100 | 10.027 | No |
| 12B QAT | P2 | 2 | 45.788 | 0.044 | 28.711 | No |
| 12B QAT | P4 | 4 | 14.586 | 0.274 | 14.578 | No |
| 26B MoE | P1 | 1 | 17.074 | 0.059 | 17.074 | No |
| 26B MoE | P2 | 2 | 28.228 | 0.071 | 27.493 | No |
| 26B MoE | P4 | 4 | 42.278 | 0.095 | 42.215 | No |

These are measured cell-wall throughput signals, not capacity recommendations. Because the corresponding M05 outputs were rejected, no parallelism level can be selected for production from this run.

## Contamination

Each model passed 19 of 20 contamination checks and failed one exact-repeat equality check: the first repeat differed from its predecessor, while the second repeat matched the first repeat. No forbidden cross-call sentinel was observed. This is a reproducibility warning, not evidence of cross-call leakage.

## Per-model recommendation

- **E2B**: reject for current production contract; lowest latency candidate; repair semantic and placeholder fidelity first.
- **E4B**: reject for current production contract; no advantage over E2B on current quality or timing evidence; investigate output-limit behavior before reuse.
- **12B QAT**: reject for current production contract; strongest structural retention candidate; repair fenced JSON and placeholder fidelity first.
- **26B MoE**: reject for current production contract; coherent but slower and not more accurate under current contract; do not select for quality ceiling from this run.

## Non-claims

- No physical KV-cache reuse is claimed.
- No timing result is operationally admitted because all 80 quality verdicts were rejected.
- No model is recommended for production under the current prompt, schema, and scoring contract.
- No semantic truth is claimed for M05 reference-relative scores or L02-L structural-only rows.
- All 64 cells executed; therefore there are no blocked, stop-gated, unsupported, or other zero-call rows in this matrix.
- No new model call, commit, or push was performed for this synthesis.

## Evidence boundary

The synthesis uses the frozen 64-cell plan, four sanitized ledgers, 80 independently recomputed scorecards, and recorded cleanup read-backs. Final loaded model count was zero for every model slice. The report contains no prompts, completions, credentials, private paths, or private raw text.

Machine-readable companion: `2026-07-12_four_model_real_asset_benchmark_synthesis.json`.
