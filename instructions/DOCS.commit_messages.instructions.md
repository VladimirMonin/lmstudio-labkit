---
applyTo: "**"
name: "DOCS.CommitMessages"
description: "Use when staging, reviewing, committing, or pushing changes: staged-diff truth, message format, logical grouping, verification gates, authorization, and destructive-operation limits."
---

# DOCS — Commit Messages

## Format

```text
<prefix>: <English summary>

- Detail 1
- Detail 2
- Detail 3
```

## Allowed prefixes

- `feat` — new capability.
- `fix` — bug fix.
- `docs` — documentation or instruction updates.
- `test` — tests and fixtures.
- `refactor` — behavior-preserving restructuring.
- `chore` — repository maintenance, tooling, bootstrap.

## Grouping rule

Group commits by logical change, not by file type. Do not mix unrelated code, documentation, and generated artifacts unless the same acceptance gate requires them together.

## Staged-diff truth

Before writing a commit message, inspect `git status --short --branch`, unstaged changes, untracked files, and `git diff --cached`. The staged diff is the only source of truth for what the commit contains. Do not infer commit contents from a card, working-tree summary, or earlier test report, and do not stage unrelated dirty work.

Commit and push are separate actions. Perform either only when the user explicitly requests it; authorization to commit does not imply authorization to push.

## Required checks before commit

For code changes:

```bash
uv run pytest -q tests/libs tests/tools tests/architecture
uv run ruff check .
uv run ruff format --check .
```

For docs-only changes:

```bash
git diff --check
python scripts/audit_publication_safety.py
```

## Forbidden without explicit user confirmation

- `git reset --hard`, `git reset --mixed`, broad checkout/revert, or force-push.
- Committing `.env`, `.venv`, credentials, caches, local runtime logs, or unsanitized private source notes.
- Claiming a push succeeded without verifying the remote state.
