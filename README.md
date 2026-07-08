# LM Studio LabKit

LM Studio LabKit is a Python/uv project for a reusable LM Studio request core and an extensible benchmark harness. The roadmap covers text, image, chat, structured, and non-structured experiments while keeping default checks offline and publication-safe.

Current code includes extracted managed LM Studio backend contracts, lab runners/probes, experiment assets, regression tests, a public `lmstudio_labkit` facade, offline matrix planning/execution, compatibility-filtered axes, safety budgets, hardened structured validators, fake failure modes, privacy-scanned artifacts, report summaries across model/language/complexity/`schema_variant`/retry/skipped cells, and a guarded live bridge interface. Live execution remains explicit opt-in, host-managed, and is not run by default.

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
