# L4a Model Visibility Probe Evidence — LM Studio Lab

## Scope

- Date: 2026-07-02
- Branch: `next/modular-backend-lab`
- Commit: `08eebfde`
- Evidence level: controlled model visibility probe, not a load/config echo proof
- Model ID requested for target lookup: `google/gemma-4-e2b`
- Endpoint: `/api/v1/models`
- Base URL class: localhost loopback
- Command: `probe-models`
- Prompt/generation/chat endpoint used: no
- Load/unload/download/lifecycle endpoint used: no
- Raw provider response stored: no

## Result

| Metric | Value |
| --- | ---: |
| Command exit code | `0` |
| Probe status | `ok` |
| Error category | `null` |
| Response hash | present |
| Response chars | `27897` |
| Sanitized model records | `43` |
| Loaded model count | `0` |
| Loaded instance total | `0` |
| Target model ID safe | `true` |
| Target model found | `false` |

## Safe model/config observations

- Sanitized model IDs were placeholder records from `model_0001` through `model_0043`.
- No loaded instances were reported by the native model-list response after sanitization.
- No target record for `google/gemma-4-e2b` was found.
- Safe context values observed across sanitized records: `2048`, `32768`, `40960`, `131072`, `202752`, `262144`, `393216`, `1048576`.
- Safe capability keys observed on some records included `vision`, `trained_for_tool_use`, and `reasoning`.
- No `parallel` field was surfaced in sanitized records.

## Privacy and artifact handling

- Probe artifacts were written to a temporary workspace only, not into the repository.
- The repository was not modified by the probe run.
- `environment.json` did not include base URL, current working directory, environment variables, user names, or path fields.
- Safe scan found no raw prompt/message/content/response payloads, no chat endpoint, no localhost URL, no user paths, and no secret/token/password markers.
- The full provider response was represented only by hash and character count.

## Interpretation

L4a proves that the Lab can safely query the native LM Studio model-list endpoint and store sanitized model visibility evidence.

It does **not** prove that the target model is currently loaded with a verified context. The native list probe reported no loaded instances and did not find a safe target record for `google/gemma-4-e2b`. Therefore the L1c medium degradation remains unresolved: the actual loaded context still needs a controlled load/config echo check.

## What this proves

- `GET /api/v1/models` is reachable on localhost and returns a parseable response.
- The Lab model probe stores only sanitized summaries and records.
- No prompt, generation, chat, load, unload, download, or lifecycle endpoint was used.
- The current native visibility snapshot does not show a verified loaded target instance.

## What this does not prove

- It does not prove the actual context length used by the previous `/v1/chat/completions` runs.
- It does not prove that `32768` context is applied.
- It does not prove that `google/gemma-4-e2b` is unavailable or unusable.
- It does not evaluate medium structured JSON again.

## Next gate

Proceed to **L4b controlled load/config echo probe** before retrying medium:

- target model: `google/gemma-4-e2b`;
- requested `context_length=32768`;
- requested `parallel=1`;
- `echo_load_config=true`;
- no wildcard unload;
- no prompt or generation;
- record requested vs sanitized applied config only.
