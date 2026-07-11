# Four-model benchmark execution overlay

This overlay binds the published 16-view benchmark pack to a bounded 64-cell,
80-call execution plan for E2B, E4B, 12B QAT, and 26B MoE. The tracked
`execution_bundle/` contains the frozen plan, 80 canonical native-chat request
artifacts, per-model load configurations, and current LM Studio SDK token-count
evidence. Every request contains the exact public task prompt, sanitized input,
output schema, task/rubric binding, model/cell/call/request identifiers, context
tier, and output-token limit.

Output limits are frozen by task axis rather than shared globally:

- short semantic normalization (`M01`): 512 tokens;
- long Whisper normalization (`M05`): 2,048 tokens;
- structural retention (`L02-L`): 512 tokens.

The M05 limit covers the complete sanitized reference artifact's 1,926 UTF-8
bytes even under a conservative one-token-per-byte bound. The tracked
`output-budget-fit.json` then combines that limit with the retained real LM Studio
SDK per-model input-token captures, plus a 256-token allowance for the changed
request metadata. All 80 upper bounds fit their loaded context; this is a fit proof,
not a replacement exact capture. The original signed `exact-token-map.json` and the
completed 512-token E2B run remain immutable low-budget evidence.

The executable driver is `tools.lmstudio_lab.four_model_benchmark_driver`. It runs
one model at a time and implements cold one-shot cycles, one compatible loaded
session with stable-prefix/changing-suffix and exact-repeat controls, and P1/P2/P4
concurrent calls against one loaded instance. It writes every raw answer once to
an owner-only directory outside the repository, appends one ledger row per call,
computes deterministic scorecards and contamination evidence, validates complete
closure, unloads the model, and requires a final `loaded_total=0` read-back.

No generation is performed by preparation or token capture. Live generation is
an explicit `run-model` action. Use a new empty private root for every attempt.

## Prepare or refresh the frozen bundle

```bash
uv run python -m tools.lmstudio_lab.four_model_benchmark_driver prepare \
  --bundle experiments/lmstudio/four_model_overlay/v1/execution_bundle
```

## Exact E2B command

```bash
export PRIVATE_BENCHMARK_RUN_ROOT="$HOME/.local/share/lmstudio-labkit/four-model-benchmark/e2b-run-001"
install -d -m 700 "$PRIVATE_BENCHMARK_RUN_ROOT"
uv run python -m tools.lmstudio_lab.four_model_benchmark_driver run-model \
  --model google/gemma-4-e2b \
  --plan experiments/lmstudio/four_model_overlay/v1/execution_bundle/frozen-plan.json \
  --requests experiments/lmstudio/four_model_overlay/v1/execution_bundle/requests \
  --private-root "$PRIVATE_BENCHMARK_RUN_ROOT/raw" \
  --ledger "$PRIVATE_BENCHMARK_RUN_ROOT/call-ledger.jsonl" \
  --scorecards "$PRIVATE_BENCHMARK_RUN_ROOT/scorecards"
```

The command refuses a dirty loaded-model preflight, non-empty output destinations,
unknown model identifiers, and private roots inside the repository. Do not run it
without explicit live-generation authorization.

## Published result

The sanitized synthesis for the completed 64-cell, 80-call run is available in
[`../../results_summaries/2026-07-12_four_model_real_asset_benchmark_synthesis.md`](../../results_summaries/2026-07-12_four_model_real_asset_benchmark_synthesis.md),
with a machine-readable JSON companion. The report publishes measurements and
verdicts only; private prompts, raw responses, local paths, and credentials remain
outside the repository.
