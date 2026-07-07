# M0.1 Model Availability Probe — LM Studio Lab

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Support commits: `dcefcfd0`, `55d03d5b`
- Evidence level: safe visibility probe, not model screening
- Registry: `experiments/lmstudio/models/candidates.yaml`
- Endpoint: `/v1/models`
- Endpoint class: OpenAI-compatible, localhost loopback
- Native load/unload/download endpoints: not called
- Generation endpoints: not called
- Cache/stateful/vision: not tested
- Raw provider response stored: no
- Raw local paths stored: no

## Goal

M0.1 checks which registry candidates have a confirmed OpenAI-compatible model identifier before starting model screening.

The registry policy remains:

```text
compat_model_id_resolution: safe_v1_models_probe_only
compat_model_id_guessing_from_source_id: forbidden
unresolved_compat_model_id_action: keep_null_until_probe_confirms
```

## Probe result

The safe `/v1/models` probe returned a visible model count of `43`. The raw response was not stored.

| Candidate | Existing `compat_model_id` | Exact compat match | Exact source match | Exact basename match | Result |
| --- | --- | ---: | ---: | ---: | --- |
| `gemma4_e2b_q4km` | `google/gemma-4-e2b` | yes | no | no | visible baseline |
| `qwen35_4b_q4km` | `null` | no | no | no | unresolved |
| `gemma4_e4b_q4km` | `null` | no | no | no | unresolved |
| `qwen35_9b_q4km` | `null` | no | no | no | unresolved |

## Interpretation

Only the current baseline model is confirmed visible through the compatible `/v1/models` plane:

```text
gemma4_e2b_q4km -> google/gemma-4-e2b
```

The other three candidates are not resolved by exact match. This does not prove whether they are not downloaded, not loaded, hidden behind different compatible IDs, or simply not visible in the current LM Studio server state. It only proves that their registry entries do not yet have safe, confirmed compatible IDs.

Because `source_id` is not a compatible model ID, no `compat_model_id` values were guessed or written for unresolved candidates.

## Screening gate

Full M1/M2 four-model screening is blocked until candidates are visible/resolved.

Allowed now:

```text
M2p plain text baseline on google/gemma-4-e2b
safe /v1/models retry after the user makes more models visible
manual registry update only after explicit exact compat_model_id confirmation
```

Not allowed yet:

```text
M1/M2 full four-model matrix
native load/config echo for unresolved native IDs
keepModelInMemory / tryMmap A/B
thinking / temperature / prompt variants
cache/stateful
vision
app_concurrency=4
```

## What this proves

- The registry has one confirmed compatible baseline model.
- The three additional candidates still need safe identity resolution before honest screening.
- The current blocking state is an environment/model-visibility fact, not a Lab code failure.

## What this does not prove yet

- It does not identify the correct compatible IDs for unresolved models.
- It does not prove availability through native `/api/v1/*` endpoints.
- It does not test model loading, unloading, downloading, generation, structured JSON, plain text, cache/stateful behavior, or vision.

## Next gated steps

1. Ask the user to make the unresolved models visible in LM Studio or provide exact compatible IDs shown by LM Studio.
2. Repeat the safe `/v1/models` resolution probe.
3. Update `candidates.yaml` only for IDs confirmed by safe probe or explicit user confirmation.
4. Start M1/M2 multi-model screening only after candidate visibility is resolved.
