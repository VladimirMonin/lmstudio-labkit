# LM Studio LabKit

LM Studio LabKit is a Python/uv project for a reusable LM Studio request core and an extensible benchmark harness. The roadmap covers text, image, chat, structured, and non-structured experiments while keeping default checks offline and publication-safe.

Current code includes extracted managed LM Studio backend contracts, lab runners/probes, experiment assets, regression tests, a public `lmstudio_labkit` facade, offline matrix planning/execution, compatibility-filtered axes, safety budgets, hardened structured validators, fake failure modes, privacy-scanned artifacts, report summaries across model/language/complexity/`schema_variant`/retry/skipped cells, and a guarded live bridge interface. Live execution remains explicit opt-in, host-managed, and is not run by default.

## Docs

- [Agent and instruction workflow](docs/agent-workflow.md)
- [Development plan](docs/development_plan.md)
- [Structured matrix benchmark design](docs/structured_matrix_design.md)
- [Public API design](docs/public_api_design.md)
- [Current state analysis](docs/analysis_current_state.md)

## Live demo snapshots

- [Latest remote text screening snapshot](docs/live_demo/latest_text_remote_e2b_e4b/README.md) — public-safe export target for the latest L3.16 Gemma E2B/E4B remote-link text run. The directory may contain only sanitized summaries and no raw prompts, raw responses, hostnames, tokens, or base URLs.
- [Latest Gemma text quality snapshot](docs/live_demo/latest_text_quality_gemma/README.md) — public-safe export target for the latest L3.17 staged Gemma text-quality run. The directory includes sanitized summaries only: no raw prompts, raw responses, hostnames, tokens, base URLs, or source run paths.

## Quick start

```bash
uv sync --extra dev
uv run pytest -q tests/libs tests/tools tests/architecture
uv run ruff check .
```

Live LM Studio checks, model downloads, large model loads, and overnight runs are opt-in only.
