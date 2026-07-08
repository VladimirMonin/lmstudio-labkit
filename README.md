# LM Studio LabKit

LM Studio LabKit is a Python/uv project for a reusable LM Studio request core and an extensible benchmark harness. The roadmap covers text, image, chat, structured, and non-structured experiments while keeping default checks offline and publication-safe.

Current code includes extracted managed LM Studio backend contracts, lab runners/probes, experiment assets, and regression tests. Some roadmap items are planned and are not yet implemented.

## Docs

- [Development plan](docs/development_plan.md)
- [Structured matrix benchmark design](docs/structured_matrix_design.md)
- [Public API design](docs/public_api_design.md)
- [Current state analysis](docs/analysis_current_state.md)

## Quick start

```bash
uv sync --extra dev
uv run pytest -q tests/libs tests/tools tests/architecture
uv run ruff check .
```

Live LM Studio checks, model downloads, large model loads, and overnight runs are opt-in only.
