# MV2.4b — Qwen 4B structured-small baseline routing probe

Date: 2026-07-05

## Scope

- Track: MV2.4 Qwen recovery.
- Stage: MV2.4b baseline current-policy probe.
- Model: `qwen35_4b_q4km` (`qwen3.5-4b`).
- Dataset: `blocks_json_small` (`sha256:blocks-json-small-v1`).
- Mode: `json_schema_single` / `factual_blocks.v1` validation.
- Load config: `context_length=8192`, `parallel=1`.
- App concurrency: `1`.
- System metrics: enabled for live generation.
- No true_parallel, no medium run, no broad matrix.

## Command sequence

Controlled load:

```powershell
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py probe-lifecycle --base-url http://127.0.0.1:1234 --model-id qwen3.5-4b --scenario controlled_load_echo --context-length 8192 --parallel 1 --execute-lifecycle --output-root <local-temp-live-results> --run-id mv2_4b_qwen4b_load_20260705
```

Structured-small baseline generation:

```powershell
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py run experiments\lmstudio\configs\m1_1_structured_small_qwen35_4b.yaml --live --output-root <local-temp-live-results> --run-id mv2_4b_qwen4b_structured_small_baseline_20260705 --system-sample-interval-s 1
```

Exact cleanup:

```powershell
.\.venv\Scripts\python.exe tools\lmstudio_benchmark.py probe-lifecycle --base-url http://127.0.0.1:1234 --model-id qwen3.5-4b --scenario unload_happy_path --execute-lifecycle --output-root <local-temp-live-results> --run-id mv2_4b_qwen4b_cleanup_20260705
```

All commands exited successfully.

## Lifecycle evidence

| Phase | Status | Key facts |
|---|---|---|
| controlled load | `ok` | `load_verified=true`, `applied_context_length=8192`, `applied_parallel=1`, observed loaded count `1` |
| cleanup | `ok` | observed loaded count before `1`, after `0`, unload call count `1` |

Raw instance identity was stored only as a hash in artifacts.

## Generation result

| Metric | Value |
|---|---:|
| finish_reason | `stop` |
| content_empty | `true` |
| reasoning_content_present | `true` |
| response_chars | 0 |
| json_parse_pass | false |
| schema_pass | false |
| business_pass | false |
| error_category | `empty` |
| structured_errors | 1 |
| prompt_tokens | 93 |
| completion_tokens | 153 |
| total_tokens | 246 |
| total_elapsed_ms | 2234 ms |

## System metrics

- samples: `4`
- RAM peak: `29186.902 MB`
- VRAM before/peak/after: `8508 / 8514 / 8514 MB`
- GPU util peak: `76%`
- GPU power peak: `124.81 W`

## Classification

The baseline current policy remains unresolved for Qwen 4B structured output:

```text
reasoning_routing_unresolved
```

The model produced reasoning tokens/content according to the envelope metadata, but public `content` was empty. Because the stored public response text is empty, real JSON/schema/business validation fails honestly as `empty`, not as a schema-quality failure.

## What this proves

- Qwen 4B can be loaded and exact-unloaded safely at `8192 / parallel=1`.
- The previous routing symptom is reproducible under the controlled MV2.4b baseline:
  - `content_empty=true`
  - `reasoning_content_present=true`
- The failure mode is a reasoning/public-content routing issue, not timeout or finish-length.

## What this does not prove

- It does not prove that Qwen 4B cannot produce valid structured JSON under another policy.
- It does not test anti-reasoning prompts.
- It does not test an explicit reasoning-off request flag.
- It does not authorize medium Qwen 4B runs or Qwen true_parallel.
- It does not touch host application runtime, QueueManager, UI, SQLite, cache/stateful, vision or embeddings.

## Next gate

Prepare MV2.4b variant support before the next live generation attempt:

1. anti-reasoning system prompt variant;
2. optional reasoning-off request flag only if LM Studio/Qwen exposes a safe request-shape option;
3. preserve safe artifacts: prompt hashes/flags only, no raw prompts/responses.
