# MV2.4b-2 — Qwen 4B request-shape reasoning-off probe

Date: 2026-07-05

## Scope

- Track: MV2.4 Qwen recovery.
- Stage: final Qwen 4B request-shape probe for this phase.
- Model: `qwen35_4b_q4km` (`qwen3.5-4b`).
- Dataset: `blocks_json_small` (`sha256:blocks-json-small-v1`).
- Mode: `json_schema_single` / `factual_blocks.v1` validation.
- Load config: `context_length=8192`, `parallel=1`.
- App concurrency: `1`.
- Structured prompt variant: `baseline`.
- Structured reasoning control: `chat_template_kwargs_enable_thinking_false`.
- System metrics: enabled for live generation.
- No medium, no chunked Qwen 4B, no true_parallel, no Qwen 9B, no broad matrix.

## Why this gate existed

Baseline and prompt-level anti-reasoning already reproduced the same symptom:

```text
content_empty=true
reasoning_content_present=true
error_category=empty
```

External evidence suggested that Qwen3.5/LM Studio may expose thinking control through a request-shape or chat-template knob, but recent LM Studio issue reports also describe the same empty-`content`/populated-reasoning failure even when `enable_thinking=false` is attempted. This gate was the one final narrow classifier before closing Qwen 4B structured recovery for the current phase.

## Command sequence

Controlled load:

```powershell
uv run python tools/lmstudio_benchmark.py probe-lifecycle --model-id qwen3.5-4b --scenario controlled_load_echo --context-length 8192 --parallel 1 --execute-lifecycle --run-id mv2_4b_qwen4b_reasoning_control_load_20260705
```

Structured-small request-shape generation:

```powershell
uv run python tools/lmstudio_benchmark.py run experiments/lmstudio/configs/m1_1_structured_small_qwen35_4b.yaml --live --run-id mv2_4b_qwen4b_reasoning_control_20260705 --system-sample-interval-s 1 --structured-reasoning-control chat_template_kwargs_enable_thinking_false
```

Exact cleanup:

```powershell
uv run python tools/lmstudio_benchmark.py probe-lifecycle --model-id qwen3.5-4b --scenario unload_happy_path --execute-lifecycle --run-id mv2_4b_qwen4b_reasoning_control_cleanup_20260705
```

All commands exited successfully.

## Artifact locations

- Load: `experiments/lmstudio/results/run_mv2_4b_qwen4b_reasoning_control_load_20260705_model_lifecycle/`
- Generation: `experiments/lmstudio/results/run_mv2_4b_qwen4b_reasoning_control_20260705_m1_1_structured_small_qwen35_4b/`
- Cleanup: `experiments/lmstudio/results/run_mv2_4b_qwen4b_reasoning_control_cleanup_20260705_model_lifecycle/`

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
| structured_prompt_variant | `baseline` |
| structured_reasoning_control_variant | `chat_template_kwargs_enable_thinking_false` |
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
| total_elapsed_ms | 2187 ms |

## System metrics

- samples: `4`
- RAM peak: `28553.926 MB`
- VRAM before/peak/after: `8563 / 8569 / 8569 MB`
- GPU util peak: `88%`
- GPU memory util peak: `69%`
- GPU power peak: `126.89 W`

## Privacy

- `environment.json` records only finite safe labels:
  - `structured_prompt_variant=baseline`
  - `structured_reasoning_control_variant=chat_template_kwargs_enable_thinking_false`
- Prompt text and response text are not stored.
- Public response content was empty; only hashes/counts/tokens/timing/flags are persisted.
- Native lifecycle artifacts store instance identity as hash only.

## Classification

The request-shape reasoning-off probe did not recover Qwen 4B structured output:

```text
reasoning_routing_unresolved
```

This is the same externally visible failure mode as both prior MV2.4b Qwen 4B probes: the model/server reports a normal stop, reasoning-side output is present, and public assistant `content` remains empty. Since the validation path correctly reads public `content`, JSON/schema/business validation fail honestly as `empty`.

## Decision

Close `qwen35_4b_q4km` as a structured-output candidate for this phase.

Do not spend more time on Qwen 4B structured recovery in MV2.4 unless the LM Studio/Qwen reasoning-content routing bug is fixed upstream or a new documented request shape is provided and can be tested as a separate future gate.

## What this proves

- Qwen 4B still loads and exact-unloads safely at `8192 / parallel=1`.
- The safe request-shape label was delivered to the live run.
- `chat_template_kwargs.enable_thinking=false` does not fix this Qwen 4B structured-output route in the current environment.
- Cleanup returned the live server to zero observed loaded instances.

## What this does not prove

- It does not prove every Qwen 4B format/build is broken.
- It does not test manual LM Studio prompt-template overrides such as ChatML.
- It does not test Qwen 9B.
- It does not authorize reading `reasoning_content` as production structured output.
- It does not touch host application runtime, QueueManager, UI, SQLite, cache/stateful, vision or embeddings.

## Next step

Continue with the already-green Gemma line:

- `gemma4_e2b_q4km` remains the current baseline structured candidate.
- `gemma4_e4b_q4km` remains the heavier candidate.
- Qwen 4B should not move to medium/chunked/true_parallel in this phase.
