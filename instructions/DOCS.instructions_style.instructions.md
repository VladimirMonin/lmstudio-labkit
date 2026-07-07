---
applyTo: "instructions/*.instructions.md"
name: "DOCS.InstructionsStyle"
description: "Use when creating or updating instruction files: filename pattern, YAML metadata, trigger descriptions, single-responsibility scope, and publication-safe wording."
---

# DOCS — Style for Instructions

## Required format

- File name: `PREFIX.topic.instructions.md`.
- YAML frontmatter is the first content in the file.
- Required frontmatter keys: `applyTo`, `name`, `description`.
- `name` format: `PREFIX.Topic`.
- One primary responsibility per instruction file.
- Rules must match current project code, layout, and verification commands.

## Description rule

`description` is a routing trigger for agents. It must say when the instruction is relevant, including typical files, tasks, and keywords.

Good: "Use when changing LM Studio lifecycle clients, registry identity, loaded-instance ownership, or structured validation."
Bad: "LM Studio notes."

## Canonical prefixes

- `CORE` — repository structure, entry points, module boundaries.
- `INFRA` — LM Studio clients, lifecycle, registry, metrics, validation.
- `TEST` — pytest, fixtures, live/offline gates.
- `DOCS` — instructions, plans, commit messages, documentation hygiene.
- `SEC` — publication safety, privacy, sensitive-data cleanup.

## What to avoid

- Mixing independent subsystems in one file.
- Long release-history narratives.
- Private project names, private support workflows, forum/marketplace names, build-protection details, secrets, or local private paths.
- Rules copied from another project without adapting paths and commands.

## Checklist

- [ ] Filename ends with `.instructions.md`.
- [ ] Frontmatter has `applyTo`, `name`, `description`.
- [ ] `description` contains useful routing triggers.
- [ ] The file has one responsibility.
- [ ] Paths and commands match this repository.
- [ ] Wording is publication-safe.
