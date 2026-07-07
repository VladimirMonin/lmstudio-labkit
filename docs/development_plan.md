# Development Plan

## Goal

Turn LM Studio LabKit into a standalone, publishable Python/uv project for managed LM Studio experiments, reusable backend contracts, structured-output validation, lifecycle probes, cache/context research, and model-policy reporting.

## Phase 0 — Baseline extraction

- Preserve `libs/lmstudio_managed/`, `tools/lmstudio_lab/`, `tools/lmstudio_benchmark.py`, `experiments/lmstudio/`, and targeted tests.
- Keep default tests offline.
- Ensure publication-safety audit passes before docs are committed.

Acceptance gate:

```bash
uv sync --extra dev
uv run pytest -q tests/libs tests/tools tests/architecture
uv run ruff check .
uv run ruff format --check .
python scripts/audit_publication_safety.py
```

## Phase 1 — Packaging boundary

- Decide whether the public package remains `libs.lmstudio_managed` / `tools.lmstudio_lab` for the alpha or gains a `lmstudio_labkit` facade.
- Keep backwards-compatible imports until tests and docs are updated together.
- Add a small import smoke for installed wheel behavior.

## Phase 2 — CLI/report surface

- Stabilize `lmstudio-benchmark` command behavior.
- Add or explicitly defer `summarize` and `compare` commands.
- Ensure monkeypatchable command seams stay lazy so no-live paths do not import live/network modules.

## Phase 3 — Experiment synthesis

- Produce one product-neutral model-policy report from existing result summaries.
- Separate proven facts, lab-only candidates, blocked routes, and future hypotheses.
- Keep raw prompts, private paths, and source-application references out of public artifacts.

## Phase 4 — Optional live gates

- Run live LM Studio gates only with explicit permission.
- Keep downloads, model loads, and long benchmark runs opt-in.
- Record only privacy-safe metrics: hashes, counts, timings, statuses, model IDs, and validation flags.

## Phase 5 — Future vision lane

- Either implement a separate vision/image benchmark lane or mark it out of scope for the first public release.
- Do not mix text-core candidate recommendations with unverified vision capability claims.
