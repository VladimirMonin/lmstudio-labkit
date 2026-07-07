# MV2.4b — Qwen 4B anti-reasoning structured-small probe

Date: 2026-07-05

## Scope

- Track: MV2.4 Qwen recovery.
- Stage: MV2.4b anti-reasoning prompt-variant probe.
- Model: `qwen35_4b_q4km` (`qwen3.5-4b`).
- Dataset: `blocks_json_small` (`sha256:blocks-json-small-v1`).
- Mode: `json_schema_single` / `factual_blocks.v1` validation.
- Load config: `context_length=8192`, `parallel=1`.
- App concurrency: `1`.
- Structured prompt variant: `anti_reasoning`.
- System metrics: enabled for live generation.
- No true_parallel, no medium run, no broad matrix.

## Command sequence

Controlled load:

```powershell
uv run python tools/lmstudio_benchmark.py probe-lifecycle --model-id qwen3.5-4b --scenario controlled_load_echo --context-length 8192 --parallel 1 --execute-lifecycle --run-id mv2_4b_qwen4b_anti_reasoning_load_20260705
```

Structured-small anti-reasoning generation:

```powershell
uv run python tools/lmstudio_benchmark.py run experiments/lmstudio/configs/m1_1_structured_small_qwen35_4b.yaml --live --run-id mv2_4b_qwen4b_anti_reasoning_20260705 --system-sample-interval-s 1 --structured-prompt-variant anti_reasoning
```

Exact cleanup:

```powershell
uv run python tools/lmstudio_benchmark.py probe-lifecycle --model-id qwen3.5-4b --scenario unload_happy_path --execute-lifecycle --run-id mv2_4b_qwen4b_anti_reasoning_cleanup_20260705
```

All commands exited successfully.

## Artifact locations

- Load: `experiments/lmstudio/results/run_mv2_4b_qwen4b_anti_reasoning_load_20260705_model_lifecycle/`
- Generation: `experiments/lmstudio/results/run_mv2_4b_qwen4b_anti_reasoning_20260705_m1_1_structured_small_qwen35_4b/`
- Cleanup: `experiments/lmstudio/results/run_mv2_4b_qwen4b_anti_reasoning_cleanup_20260705_model_lifecycle/`

These run artifacts remain local/ignored; this summary records the safe evidence.

## Lifecycle evidence

| Phase | Status | Key facts |
|---|---|---|
| controlled load | `ok` | `load_verified=true`, `applied_context_length=8192`, `applied_parallel=1`, observed loaded count `1` |
| cleanup | `ok` | observed loaded count before `1`, after `0`, unload call count `1` |

Raw instance identity was stored only as a hash in artifacts.

## Generation result

| Metric | Value |
|---|---:|
| structured_prompt_variant | `anti_reasoning` |
| finish_reason | `stop` |
| content_empty | `true` |
| reasoning_content_present | `true` |
| response_chars | 0 |
| json_parse_pass | false |
| schema_pass | false |
| business_pass | false |
| error_category | `empty` |
| structured_errors | 1 |
| prompt_tokens | 127 |
| completion_tokens | 153 |
| total_tokens | 280 |
| total_elapsed_ms | 2187 ms |

## System metrics

- samples: `4`
- RAM peak: `26600.125 MB`
- VRAM before/peak/after: `10603 / 10609 / 10609 MB`
- GPU util peak: `89%`
- GPU memory util peak: `71%`
- GPU power peak: `133.54 W`

## Privacy

- `environment.json` records only the finite safe label `structured_prompt_variant=anti_reasoning`.
- Prompt text and response text are not stored.
- Public response content was empty; only hashes/counts/tokens/timing/flags are persisted.
- Native lifecycle artifacts store instance identity as hash only.

## Classification

The anti-reasoning prompt variant did not recover Qwen 4B structured output:

```text
reasoning_routing_unresolved
```

The model again produced reasoning tokens/content according to envelope metadata, while public assistant `content` stayed empty. JSON/schema/business validation therefore fails honestly as `empty`, not as a schema-quality failure.

## What this proves

- Qwen 4B still loads and exact-unloads safely at `8192 / parallel=1`.
- The `anti_reasoning` prompt variant was delivered and recorded as a safe artifact label.
- The baseline failure mode is not fixed by the anti-reasoning system prompt alone:
  - `content_empty=true`
  - `reasoning_content_present=true`
  - `finish_reason=stop`
- Cleanup returned the live server to zero observed loaded instances.

## What this does not prove

- It does not prove that Qwen 4B cannot be recovered with an explicit provider-supported reasoning-off request shape.
- It does not authorize medium Qwen 4B runs or Qwen true_parallel.
- It does not test Qwen 9B.
- It does not touch host application runtime, QueueManager, UI, SQLite, cache/stateful, vision or embeddings.

## Next gate

Do not expand Qwen 4B to medium or true_parallel while small structured output remains unresolved. The only remaining Qwen 4B recovery branch is a narrow request-shape probe if a safe, provider-supported reasoning-off option can be proven and implemented with fake-first tests.
