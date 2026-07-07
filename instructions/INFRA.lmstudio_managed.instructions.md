---
applyTo: "libs/lmstudio_managed/**,tools/lmstudio_lab/**,tools/lmstudio_benchmark.py,experiments/lmstudio/**"
name: "INFRA.LMStudioManaged"
description: "Use when changing managed LM Studio clients, endpoint contracts, lifecycle load/unload, registry identity, structured validation, cache contracts, metrics, or lab probes."
---

# INFRA — LM Studio Managed Backend and Lab Tools

## API namespaces

- OpenAI-compatible endpoints and native LM Studio REST endpoints are separate contracts.
- Keep endpoint selection explicit and testable.
- Do not treat a successful root URL request as proof that the required namespace is usable.

## Lifecycle safety

- Duplicate-load prevention is mandatory: check already-loaded instances before load requests.
- Reuse is valid only when runtime shape is compatible with the requested context length, parallelism, and purpose.
- External/preloaded instances must not be unloaded as if the lab created them.
- Load success requires materialization evidence from observed runtime state, not only an HTTP `200`.

## Privacy-safe metrics

- Metrics may include model identifiers, token counts, timings, statuses, endpoint family, and anonymized references.
- Do not store prompts, completions, credentials, local private paths, raw user text, or private product names in result artifacts.

## Default vs live gates

- Default tests are offline and deterministic.
- Live tests must require explicit config/env and must be skipped or guarded by default.
- Model downloads and large model loads require explicit user permission.
