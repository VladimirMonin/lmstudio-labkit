# M2p Plain Text Artifact Baseline — LM Studio Lab

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: live same-session A/B baseline, not production integration
- Model lab key: `gemma4_e2b_q4km`
- Model ID: `google/gemma-4-e2b`
- Diagnostic kind: `plain_text_artifacts`
- Endpoint: `/v1/chat/completions`
- Response format: none
- Temperature: `0`
- Native load/unload/download endpoints: not called
- Cache/stateful/vision: not tested
- Raw prompt/response/messages/content stored: no

## Goal

M2p checks the plain text artifact workload for the already-visible baseline model while the other M0 candidates remain unresolved through safe `/v1/models`.

The four synthetic artifact tasks are:

```text
summary_short
lecture_notes
mic_command_answer
freeform_rewrite
```

## Lab fix before accepted run

Initial run `m2p_plain_text_gemma4_e2b_seq_001` exposed an artifact-specific cap issue:

| Metric | Value |
| --- | ---: |
| App concurrency | `1` |
| Request count | `4` |
| Max tokens | `128` |
| `business_pass` | `0/4` |
| Finish length count | `4` |
| Structured errors | `4` |

The Lab harness was adjusted so only `plain_text_artifacts` uses an artifact-specific `max_tokens=512`. Existing `plain_text_pair` remains at `128`; structured JSON token sizing was not changed.

## A. Sequential baseline

Run ID: `m2p_plain_text_gemma4_e2b_seq_002`

| Metric | Value |
| --- | ---: |
| App concurrency | `1` |
| Request count | `4` |
| `business_pass` | `4/4` |
| Finish length count | `0` |
| Reasoning leaks | `0` |
| Structured errors | `0` |
| Total prompt tokens | `265` |
| Total completion tokens | `765` |
| Total tokens | `1030` |
| Total wall time | `10813 ms` |
| Average request latency | `2703 ms` |
| Max request latency | `5938 ms` |

System telemetry:

| Metric | Value |
| --- | ---: |
| Sample count | `12` |
| RAM before | `16733.051 MB` |
| RAM peak | `21299.812 MB` |
| RAM after | `21022.508 MB` |
| Process RSS peak | `238.879 MB` |
| VRAM before | `1471 MB` |
| VRAM peak | `4452 MB` |
| VRAM after | `4452 MB` |
| GPU util peak | `80%` |
| GPU memory util peak | `52%` |
| GPU power peak | `111.94 W` |

## B. App concurrency 2 candidate

Run ID: `m2p_plain_text_gemma4_e2b_appconc2_002`

| Metric | Value |
| --- | ---: |
| App concurrency | `2` |
| Request count | `4` |
| `business_pass` | `4/4` |
| Finish length count | `0` |
| Reasoning leaks | `0` |
| Structured errors | `0` |
| Total prompt tokens | `265` |
| Total completion tokens | `493` |
| Total tokens | `758` |
| Total wall time | `3109 ms` |
| Average request latency | `1340 ms` |
| Max request latency | `3109 ms` |
| Speedup vs sequential wall time | `3.48x` |

System telemetry:

| Metric | Value |
| --- | ---: |
| Sample count | `4` |
| RAM before | `21015.855 MB` |
| RAM peak | `21068.434 MB` |
| RAM after | `21033.848 MB` |
| Process RSS peak | `238.914 MB` |
| VRAM before | `4452 MB` |
| VRAM peak | `4452 MB` |
| VRAM after | `4452 MB` |
| GPU util peak | `81%` |
| GPU memory util peak | `53%` |
| GPU power peak | `103.22 W` |

## Acceptance check

| Profile | Business pass | Finish length | Structured errors | Wall time | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| Sequential baseline | `4/4` | `0` | `0` | `10813 ms` | accepted baseline |
| App concurrency `2` | `4/4` | `0` | `0` | `3109 ms` | accepted accelerated candidate |

The `app_concurrency=2` candidate exceeds the `>= 1.2x` threshold in this run. Because total completion tokens differed between the sequential and concurrent runs, treat `3.48x` as live wall-clock evidence for this same-session workload, not as a token-normalized production guarantee.

## Privacy check

The accepted M2p artifacts were spot-checked for raw prompt/response leakage. Sanitized artifacts contain hashes, character counts, token counts, timings, validation flags, and aggregate system metrics. Raw prompts, messages, content, responses, provider bodies, local paths, and command lines were not stored.

## What this proves

- The Lab now has a dedicated plain text artifact diagnostic for the four M2p tasks.
- `google/gemma-4-e2b` can complete these tasks without `response_format` and without finish-length failures when artifact max tokens are `512`.
- `app_concurrency=2` is a promising plain-text artifact acceleration candidate for this model.
- System metrics can be collected for plain-text artifact runs.

## What this does not prove yet

- It does not prove the profile generalizes to unresolved M0 candidates.
- It does not evaluate long text artifacts or real user content.
- It does not evaluate thinking, temperature, prompt variants, cache/stateful behavior, vision, native load/config, `keepModelInMemory`, or `tryMmap`.
- It does not prove memory unload/release behavior; the model remained resident between runs.

## Next gated steps

1. Commit the Lab-only M2p diagnostic and this evidence summary after explicit approval.
2. Make unresolved candidates visible in LM Studio or provide exact compatible IDs.
3. Repeat safe `/v1/models` resolution.
4. Run M1/M2 multi-model screening only after candidate identity is resolved.
