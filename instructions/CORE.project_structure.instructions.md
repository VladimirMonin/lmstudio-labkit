---
applyTo: "lmstudio_labkit/**,libs/**,tools/**,experiments/**,tests/**,docs/**,instructions/**,pyproject.toml,README.md,AGENTS.md"
name: "CORE.ProjectStructure"
description: "Use when changing repository layout, moving LM Studio managed modules, lab tools, experiment assets, docs, tests, or agent instructions."
---

# CORE — Project Structure

## Boundaries

- `libs/lmstudio_managed/` is the reusable backend library. Keep it independent from lab runner CLI concerns.
- `tools/lmstudio_lab/` owns experiment orchestration, probes, metrics files, result writing, and CLI-like lab helpers.
- `tools/lmstudio_benchmark.py` is a standalone entry tool and should remain thin.
- `experiments/lmstudio/` stores declarative configs, schemas, datasets, model candidate metadata, and sanitized result summaries.
- `tests/libs/` tests backend contracts.
- `tests/tools/` tests lab tools and runners.
- `tests/architecture/` protects import boundaries and source-code contracts.
- `docs/` contains publication-safe documentation only.
- `instructions/` contains English agent/contributor instructions only.

## Source split goal

The first milestone is a faithful standalone extraction. Avoid large renames while preserving tests. After the baseline is green, future waves may introduce a cleaner `src/lmstudio_labkit/` public package facade.

## Do not

- Re-introduce host-application imports.
- Hide live LM Studio calls inside default unit tests.
- Store generated result dumps or local runtime logs as source unless they are curated, sanitized summaries.
