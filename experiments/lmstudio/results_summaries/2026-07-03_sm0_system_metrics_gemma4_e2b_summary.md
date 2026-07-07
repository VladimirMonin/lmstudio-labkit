# SM0 System Metrics Smoke — LM Studio Lab

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Support commit: `55d03d5b`
- Evidence level: live smoke with telemetry sampling, not a production benchmark
- Model lab key: `gemma4_e2b_q4km`
- Model ID: `google/gemma-4-e2b`
- Output contract: `factual_blocks.v1`
- Dataset ID: `blocks_json_medium_chunked`
- Chunks: `4 x 25 blocks`
- Endpoint: `/v1/chat/completions`
- Response format: `json_schema`
- Base URL class: localhost loopback
- Native load/unload/download endpoints: not called
- Cache/stateful/vision: not tested
- Raw prompt/response/messages/content stored: no

## Goal

SM0 verifies that the new privacy-safe system telemetry scaffold can run during a live LM Studio Lab profile and produce usable RAM/VRAM/GPU/process summaries without storing raw prompts, responses, provider bodies, local paths, or process command lines.

The measured workload uses the current best structured profile from L2d:

```text
warmup_policy: sequential_small_structured
app_concurrency: 2
effective_profile: standard
requested_context_length: 8192
requested_parallel: 1
```

## Validation result

Run ID: `sm0_system_metrics_gemma4_e2b_best_001`

| Metric | Value |
| --- | ---: |
| Planned requests | `13` |
| Warmup requests | `1` |
| Measured batches | `3` |
| Measured chunk requests | `12` |
| `json_parse_pass` | `12/12` |
| `schema_pass` | `12/12` |
| `business_pass` | `12/12` |
| All IDs `0..99` covered | yes |
| Missing IDs | `0` |
| Duplicate IDs | `0` |
| Finish length count | `0` |
| Reasoning leaks | `0` |
| Structured errors | `0` |
| Total prompt tokens | `15306` |
| Total completion tokens | `11110` |
| Total tokens | `26416` |

## Timing result

| Metric | Value |
| --- | ---: |
| Average batch wall time excluding warmup | `23802 ms` |
| Warmup wall time | `8313 ms` |
| Average end-to-end wall time including warmup | `26573 ms` |
| Sequential baseline reference | `33818 ms` |
| Speedup excluding warmup | `1.42x` |
| Effective speedup including warmup | `1.27x` |

This run is primarily a telemetry smoke. Its effective speedup is lower than L2d's `~1.44x` best run because the measured warmup wall time was higher in this session.

## System telemetry summary

| Metric | Value |
| --- | ---: |
| Sample count | `77` |
| RAM before | `16210.902 MB` |
| RAM peak | `20868.984 MB` |
| RAM after | `20868.984 MB` |
| Process RSS before | `233.410 MB` |
| Process RSS peak | `238.359 MB` |
| Process RSS after | `237.449 MB` |
| VRAM before | `1347 MB` |
| VRAM peak | `4509 MB` |
| VRAM after | `4487 MB` |
| GPU util peak | `80%` |
| GPU memory util peak | `62%` |
| GPU power peak | `125.32 W` |

Interpretation:

- `after ~= peak` for RAM/VRAM is expected while the model/runtime remains resident; SM0 did not test unload or lifecycle cleanup.
- On Windows, process RSS does not necessarily reflect all model memory held by the LM Studio runtime, CUDA driver, or GPU allocation path. For screening, RAM/VRAM peak and deltas are the primary memory signals.

## Privacy check

The telemetry artifacts were spot-checked for privacy-sensitive indicators.

| Artifact class | Result |
| --- | --- |
| System samples | no local paths, command lines, cwd, usernames, env, prompts, responses, messages, content, API keys, secrets, or raw provider bodies detected |
| System summary | no local paths, command lines, cwd, usernames, env, prompts, responses, messages, content, API keys, secrets, or raw provider bodies detected |

Committed evidence intentionally records only sanitized counts, timings, validation flags, model identifiers, and aggregate system metrics.

## What this proves

- System telemetry scaffolding works during a live LM Studio Lab run.
- The telemetry files are present and contain the required first-layer metrics: RAM, process RSS, VRAM, GPU util, GPU memory util, and GPU power.
- The current structured profile still validates correctly while telemetry sampling is enabled.
- The telemetry path can support future model screening gates.

## What this does not prove yet

- It does not prove unload/load lifecycle behavior.
- It does not prove memory release after model unload.
- It does not prove the profile generalizes to other models.
- It does not evaluate plain text artifacts, cache/stateful behavior, vision, native load/config, `keepModelInMemory`, or `tryMmap`.

## Next gated steps

1. Keep system metrics enabled for M1/M2 screening.
2. Treat RAM/VRAM peak and deltas as model-screening gates, not cosmetic telemetry.
3. Do not run full multi-model M1/M2 until candidate `compat_model_id` values are visible/resolved.
4. While model availability is blocked, run a baseline-only plain text artifact slice for `google/gemma-4-e2b`.
