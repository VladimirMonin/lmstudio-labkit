---
applyTo: "AGENTS.md,docs/agent-workflow.md,instructions/AGENT.kanban.instructions.md"
name: "AGENT.Kanban"
description: "Use when creating, dispatching, sleeping, waking, reviewing, or reporting Hermes Kanban work for board lmstudio-labkit: current-front ownership, card scope, evidence, and commit/push boundaries."
---

# AGENT — Kanban workflow

## Board

```text
slug: lmstudio-labkit
default workdir: /home/v/code/lmstudio-labkit
```

The Kanban CLI/database is the source of truth. Dashboards and notifications are reporting layers.

## Current-front boundary

- Inspect the board before creating, dispatching, transitioning, or closing cards.
- Treat running work as the current front. Do not edit, supersede, duplicate, reassign, stop, or close another active card unless the user explicitly asks for that lifecycle change.
- Keep each new card narrow, with the exact workdir, files and instructions to read, measurable done conditions, dependencies, and required offline evidence.
- Creating or editing a card does not authorize dispatch. Dispatch only when the user expects work to start and the card is ready.

## Sleep and review boundaries

- Sleeping, blocked, or deferred cards remain dormant until their stated dependency or user decision is satisfied. Do not wake or dispatch them merely because capacity is available.
- Review is an evidence gate, not a second implementation front. Reviewers inspect the scoped diff and reported checks; they must not absorb unrelated dirty work or silently expand scope.
- Do not mark review or finalization complete when prerequisite cards are still running, sleeping, blocked, or awaiting evidence unless the user explicitly waives the gate.

## Durable-state rule

Keep card IDs, current-front snapshots, transient progress, activity logs, test counts, and wave/report history on the board or in intended result artifacts—not in `AGENTS.md`, instructions, or instruction-governance docs.

Repository edits, commits, pushes, live LM Studio calls, model operations, and network work retain their own authorization boundaries. A card or board transition does not authorize them.
