---
applyTo: "tests/**,libs/**,tools/**,pyproject.toml"
name: "TEST.Testing"
description: "Use before adding or running tests for managed backend contracts, lab tools, architecture boundaries, offline fixtures, and live LM Studio gates."
---

# TEST — Testing

## Default gate

```bash
uv run pytest -q tests/libs tests/tools tests/architecture
uv run ruff check .
uv run ruff format --check .
```

## Test levels

1. Contract/unit tests for `libs/lmstudio_managed/`.
2. Offline lab-tool tests for `tools/lmstudio_lab/`.
3. Architecture boundary tests.
4. Opt-in live LM Studio tests.

## Live-test rule

A live test must make its dependency explicit through config, env, or marker. It must not silently download models, start long benchmark runs, or require private hardware state in the default suite.

## Fixtures

Keep fixtures minimal, deterministic, and publication-safe. Do not embed private prompts, local paths, credentials, or raw private product names.
