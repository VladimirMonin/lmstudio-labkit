# L4a.1 Identity Resolution Probe Evidence — LM Studio Lab

## Scope

- Date: 2026-07-02
- Branch: `next/modular-backend-lab`
- Commit: `017b77b7`
- Evidence level: controlled identity visibility probe, not a load/config echo proof
- Target chat model ID: `google/gemma-4-e2b`
- Compat endpoint: `/v1/models`
- Native endpoint: `/api/v1/models`
- Base URL class: localhost loopback
- Command: `probe-identity`
- Prompt/generation/chat endpoint used: no
- Load/unload/download/lifecycle endpoint used: no
- Raw provider responses stored: no

## Result

| Metric | Value |
| --- | ---: |
| Command exit code | `0` |
| Probe status | `ok` |
| Error category | `null` |
| Target model ID safe | `true` |
| Target found in compat visibility | `true` |
| Target found in native visibility | `false` |
| Target hash match across compat and native | `false` |
| Native load ID resolved | `false` |
| Compat record count | `43` |
| Native record count | `43` |
| Safe record count | `86` |
| Compat response hash | present |
| Native response hash | present |
| Compat response chars | present |
| Native response chars | present |

## Safe model/config observations

- Compat visibility contained the target chat model ID by raw in-memory comparison.
- Native management visibility did not contain a raw candidate matching the target.
- No native load ID was resolved.
- Compat capability keys: none surfaced in the safe summary.
- Native capability keys surfaced in the safe summary: `reasoning`, `trained_for_tool_use`, `vision`.
- Compat context candidates: none surfaced.
- Native context candidates: `2048`, `32768`, `40960`, `131072`, `202752`, `262144`, `393216`, `1048576`.

## Privacy and artifact handling

- Probe artifacts were written to a temporary workspace only, not into the repository.
- The repository was not modified by the probe run.
- `environment.json` did not include base URL, current working directory, environment variables, user names, or path fields.
- Safe scan found no raw prompt/message/content/response payloads, no chat endpoint, no load endpoint, no localhost URL, no user paths, and no token/password markers.
- A benign report privacy sentence mentions stripped secret-like fields; it is not a provider-data leak.
- Full provider responses were represented only by hashes and character counts.

## Interpretation

The identity gate is unresolved:

```text
target_found_compat = true
target_found_native = false
native_load_id_resolved = false
```

This means `google/gemma-4-e2b` is visible as a chat/compat model ID, but the Lab did not resolve a safe native/load ID from the native management visibility response. Therefore L4b controlled load/config echo must not guess a load ID and must stop with `model_identity_unresolved` until a safe native identity is available.

## What this proves

- The Lab can query both visibility planes without prompt, generation, load, or unload.
- The target exists in OpenAI-compatible model visibility.
- The target was not resolved to a native/load identity in the native management visibility snapshot.
- The identity gate correctly blocks blind controlled load.

## What this does not prove

- It does not prove that `google/gemma-4-e2b` cannot be loaded.
- It does not prove that no equivalent native record exists under a different safe identifier.
- It does not prove actual runtime context length.
- It does not evaluate medium structured JSON again.

## Next gate

Do not run L4b `probe-load` until native/load identity is resolved. Safe next steps are offline-only:

1. keep L4b gated with `model_identity_unresolved` on unresolved identity;
2. add context-fit preflight before any medium retry;
3. add token estimate scope metadata (`dataset_only`, `rendered_prompt`, `full_request`) so estimates are not compared across incompatible scopes.
