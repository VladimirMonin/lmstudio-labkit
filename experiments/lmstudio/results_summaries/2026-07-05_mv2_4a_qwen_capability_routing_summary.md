# MV2.4a — Qwen capability/routing GET-only probe

Date: 2026-07-05

## Scope

- Track: MV2.4 Qwen recovery.
- Stage: MV2.4a capability/routing probe.
- Evidence level: live localhost LM Studio GET-only probes.
- No generation, no native load, no native unload, no download.
- No broad matrix, no true_parallel Qwen, no host application runtime integration.

## Commands

```powershell
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py probe-models --base-url http://127.0.0.1:1234 --output-root <local-temp-live-results> --run-id mv2_4a_models_qwen_20260705
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py probe-identity --base-url http://127.0.0.1:1234 --model-id qwen3.5-4b --output-root <local-temp-live-results> --run-id mv2_4a_identity_qwen35_4b_20260705
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py probe-identity --base-url http://127.0.0.1:1234 --model-id qwen/qwen3.5-9b --output-root <local-temp-live-results> --run-id mv2_4a_identity_qwen35_9b_20260705
```

All commands exited successfully.

## GET-only model inventory

| Metric | Value |
|---|---:|
| Status | `ok` |
| Native model count | 43 |
| Loaded model count | 0 |
| Loaded instance total | 0 |
| Response stored | no raw body; only hash/chars/safe records |

## Qwen identity facts

| Candidate | Compat found | Native found | Native format | Bits/weight | Size bytes | Loaded instances | Native capability keys |
|---|---:|---:|---|---:|---:|---:|---|
| `qwen35_4b_q4km` (`qwen3.5-4b`) | true | true | `gguf` | 4 | 3383082464 | 0 | `reasoning`, `trained_for_tool_use`, `vision` |
| `qwen35_9b_q4km` (`qwen/qwen3.5-9b`) | true | true | `gguf` | 4 | 6548927711 | 0 | `reasoning`, `trained_for_tool_use`, `vision` |

Both candidates exposed native context candidates:

```text
2048, 32768, 40960, 131072, 202752, 262144, 393216, 1048576
```

## Reasoning/routing conclusion

- Both Qwen candidates expose a native `reasoning` capability key.
- The GET-only probes did not expose a safe explicit `reasoning_off` / disable-reasoning option.
- Therefore MV2.4b should treat `reasoning_off` as **unknown/not proven** until a dedicated request-shape or config probe proves it.
- The previous Qwen 4B symptom (`content_empty=true`, `reasoning_content_present=true`) remains a routing/reasoning-split recovery hypothesis, not a solved issue.

## Privacy

The probes store safe metadata only:

- endpoint kinds instead of raw endpoint paths;
- response hash/chars instead of raw provider body;
- hashed native load identifiers;
- safe capability key names and counts.

No prompts, responses, generated text, raw provider body, raw URLs, raw paths, API tokens, load calls, unload calls or downloads were used.

## What this proves

- Both Qwen candidates are visible in compat and native LM Studio model lists.
- Both are currently unloaded before recovery generation probes.
- Both expose `reasoning` as a native capability key.
- GET-only tooling is sufficient for MV2.4a and remains privacy-safe.

## What this does not prove

- It does not prove structured generation quality.
- It does not prove that reasoning can be disabled.
- It does not prove that content can be routed from reasoning output into public content.
- It does not prove timeout/chunk policy for Qwen 9B.
- It does not prove plain-text verbosity behavior.
- It does not authorize Qwen true_parallel, broad matrix, vision, embeddings, cache/stateful or host application runtime integration.

## Next gate

MV2.4b should be Qwen 4B structured-small sequential recovery only:

- `qwen35_4b_q4km`
- `blocks_json_small`
- `parallel=1`
- `app_concurrency=1`
- structured `json_schema_single`
- baseline policy first;
- anti-reasoning/reasoning-off variants only after request-shape support is prepared and reviewed.
