# Agent instruction workflow

LM Studio LabKit uses `AGENTS.md` as the project router and `instructions/*.instructions.md` as focused, durable contracts.

## Read and scope

1. Read `AGENTS.md` and every instruction whose `applyTo` or description matches the requested work.
2. Inspect `git status --short --branch` before editing and preserve unrelated modified or untracked files.
3. Read current source, tests, configuration, and authoritative docs before treating a plan or historical report as current behavior.
4. For board work, read `instructions/AGENT.kanban.instructions.md` and inspect the `lmstudio-labkit` board before changing card state.

## Maintain instructions

Add a rule only when it is durable, repeatedly useful, and project-wide or attached to a confirmed subsystem boundary. Each instruction file must have YAML frontmatter with `applyTo`, `name`, and a routing-oriented `description`, and must keep one primary responsibility.

Prefer updating an existing instruction over creating overlap. When routing changes, update `AGENTS.md` and the documentation entry point. Do not move L3.x plans, experiment reports, card IDs, current wave state, progress logs, or test-count history into instructions.

## Change and verify

- Keep edits inside the requested scope and leave unrelated dirty work untouched.
- Run the smallest relevant offline checks. Live LM Studio calls, model downloads or loads, paid/cloud calls, network probes, and long benchmarks require explicit permission.
- For instruction-only work, validate frontmatter, routed links, and whitespace with structural checks and `git diff --check` limited to the intended documentation files.
- Report only checks and transitions actually observed.

## Git boundary

Before any requested commit, inspect status, unstaged and untracked changes, and `git diff --cached`. The staged diff alone determines the commit message. Commit and push are separate operations and each requires explicit user authorization; see `instructions/DOCS.commit_messages.instructions.md`.
