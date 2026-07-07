# AGENTS — LM Studio LabKit

## Project identity

LM Studio LabKit is a standalone Python/uv project for reusable LM Studio laboratory tooling: managed backend contracts, native/compat REST clients, model lifecycle probes, structured-output validation, cache/context experiments, metrics schemas, and sanitized experiment documentation.

The project is intentionally separated from its source application. Keep public docs and instructions product-neutral: do not reference the source application's name, private support workflows, marketplace/forum monitoring, licensing internals, build-protection internals, credentials, or user/private infrastructure.

## Language policy

- Project documentation, instructions, code comments, commit messages, and plans are written in English.
- User-facing chat with Vladimir is in Russian unless he asks otherwise.

## Repository layout

- `libs/lmstudio_managed/` — reusable managed LM Studio backend library.
- `tools/lmstudio_lab/` — lab runners, probes, cache/context helpers, lifecycle helpers, metrics and reporting.
- `tools/lmstudio_benchmark.py` — standalone benchmark entry tool.
- `experiments/lmstudio/` — configs, datasets, examples, fixtures, schemas, candidate metadata, and sanitized result summaries.
- `tests/libs/` — managed backend tests.
- `tests/tools/` — lab runner/probe tests.
- `tests/architecture/` — import-boundary and architecture tests.
- `docs/` — sanitized documentation pack and development plans.
- `instructions/` — agent/contributor instructions. See the instruction catalog below.

## Instruction catalog

Read the relevant file before changing the matching area:

- `instructions/DOCS.instructions_style.instructions.md` — when creating or updating project instructions.
- `instructions/DOCS.commit_messages.instructions.md` — before every git commit.
- `instructions/CORE.project_structure.instructions.md` — when moving modules, tests, docs, or experiment assets.
- `instructions/INFRA.lmstudio_managed.instructions.md` — when changing LM Studio clients, lifecycle, registry, validation, cache contracts, or metrics.
- `instructions/TEST.testing.instructions.md` — before adding or running tests.
- `instructions/SEC.publication_safety.instructions.md` — before committing docs or publishing the repository.

## uv and verification

Use `uv` only. Do not use Poetry or global pip installs.

Default local gates:

```bash
uv sync --extra dev
uv run pytest -q tests/libs tests/tools tests/architecture
uv run ruff check .
uv run ruff format --check .
```

Live LM Studio gates are opt-in. Do not download models, load large models, start paid/cloud calls, or run long benchmarks without explicit permission.

## Privacy and publication safety

Before committing docs or publishing:

1. Run the publication audit described in `instructions/SEC.publication_safety.instructions.md`.
2. Ensure `docs/`, `instructions/`, `experiments/`, and code comments contain no source-product names, private support references, marketplace/forum names, build-protection details, credentials, account IDs, local private paths, or security-sensitive operational notes.
3. Keep technical substance: model lifecycle contracts, benchmark methodology, schemas, metrics, results, and development plans.
4. Prefer generic terms: "source application", "host application", "private support workflow".

## Commit discipline

- One logical slice per commit.
- Code/bootstrap and documentation/sanitization may be separate commits.
- Do not commit generated caches, `.venv`, secrets, local runtime logs, or unsanitized private notes.
- Push only after local verification and publication-safety audit pass.
