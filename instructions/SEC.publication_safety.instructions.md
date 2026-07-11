---
applyTo: "**"
name: "SEC.PublicationSafety"
description: "Use before committing documentation, experiment summaries, instructions, or copied source material: remove private product names, support workflows, marketplace/forum references, build-protection details, credentials, and local private paths while preserving technical substance."
---

# SEC — Publication Safety

## Always scan before committing docs

Run:

```bash
python scripts/audit_publication_safety.py
```

The audit must cover `README.md`, `AGENTS.md`, `instructions/`, `docs/`, `experiments/`, `lmstudio_labkit/`, `libs/`, `tools/`, and `tests/`.

## Remove or generalize

- Source application names and abbreviations.
- Private support workflow names, forum/marketplace references, and customer-case identifiers.
- Build-protection or anti-tamper implementation details.
- Credentials, tokens, account IDs, private local paths, usernames, personal names, and raw private transcripts/prompts.
- Security-sensitive operational instructions not needed to understand the standalone lab kit.

## Preserve

- LM Studio API/lifecycle contracts.
- Benchmark methodology.
- Model capability observations when sanitized.
- Schemas, metrics formats, validation taxonomy, and development plans.
- Public-safe hardware classes when needed for reproducibility.

## Replacement vocabulary

- "source application" or "host application" instead of private product names.
- "private support workflow" instead of specific support/forum/marketplace names.
- "publication safety" instead of detailed protected-build implementation notes.
