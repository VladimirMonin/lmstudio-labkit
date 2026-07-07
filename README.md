# LM Studio LabKit

LM Studio LabKit is a Python/uv laboratory project for managed LM Studio model lifecycle experiments, structured-output probes, cache/context-fit checks, metrics collection, and reusable backend contracts.

The project was split out from a larger desktop application so the LM Studio research and tooling can evolve as a standalone, publishable lab kit.

## Layout

- `libs/lmstudio_managed/` — reusable managed LM Studio backend contracts and clients.
- `tools/lmstudio_lab/` — experiment runners, probes, lifecycle helpers, metrics, and registry bridges.
- `tools/lmstudio_benchmark.py` — standalone benchmark entry tool.
- `experiments/lmstudio/` — experiment configs, datasets, schemas, candidate model metadata, and sanitized result summaries.
- `tests/` — managed-backend, lab-tooling, and architecture-boundary tests.
- `instructions/` — project instructions for agents and contributors.
- `docs/` — sanitized project documentation and source pack.

## Quick start

```bash
uv sync --extra dev
uv run pytest -q tests/libs tests/tools tests/architecture
uv run ruff check .
```

Live LM Studio checks are opt-in only. Do not start model downloads or large model loads from the default test suite.
