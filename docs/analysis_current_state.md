# Current State Analysis

## Done in code

- Managed LM Studio backend contracts and clients live in `libs/lmstudio_managed/`.
- Lab runners, probes, lifecycle helpers, cache/context planning, structured-output validation, metrics and reporting live in `tools/lmstudio_lab/`.
- The standalone benchmark entry tool is `tools/lmstudio_benchmark.py`.
- Experiment configs, schemas, candidate metadata, and curated result summaries live in `experiments/lmstudio/`.
- Regression coverage exists in `tests/libs/`, `tests/tools/`, and `tests/architecture/`.

## Planned in docs

- Public package facade and cleaner distribution boundary.
- Final benchmark summary/report commands beyond the current runner/probe paths.
- Product-neutral model recommendation synthesis from the current experiment corpus.
- Optional future vision/image lane.
- Clear distinction between proven cache/context behavior and still-unproven KV reuse telemetry.

## Real next work

1. Decide whether to preserve the current `libs/` plus `tools/` import shape for the first release or introduce a `src/lmstudio_labkit/` facade.
2. Add a final synthesis report that compresses the experiment corpus into model roles, route policies, and explicit non-promotions.
3. Either implement `summarize` / `compare` report commands or adjust the docs to match the implemented CLI.
4. Keep live LM Studio checks opt-in and guarded by explicit user permission.
