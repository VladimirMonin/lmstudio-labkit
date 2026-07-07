# M2p.1 Plain Text Token-Normalized Repeatability — LM Studio Lab

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: live repeatability A/B, not production integration
- Model lab key: `gemma4_e2b_q4km`
- Model ID: `google/gemma-4-e2b`
- Diagnostic kind: `plain_text_artifacts_normalized`
- Endpoint: `/v1/chat/completions`
- Response format: none
- Temperature: `0`
- App concurrency compared: `1` vs `2`
- Measured batches: `3` per profile
- Artifact tasks per batch: `4`
- Max tokens: `512`
- Native load/unload/download endpoints: not called
- Cache/stateful/vision: not tested
- Raw prompt/response/messages/content stored: no

## Goal

M2p showed a strong wall-clock speedup for plain text artifacts, but completion token counts differed between sequential and concurrent runs. M2p.1 repeats the same four artifact task classes with constrained output length to check whether the acceleration remains after token-normalization.

The constrained synthetic tasks are:

```text
summary_short
lecture_notes
mic_command_answer
freeform_rewrite
```

The normalized prompt asks for a bounded plain-text answer (`120-160` words) with no JSON, markdown, reasoning, or introduction.

## A. App concurrency 1

Run IDs:

```text
m2p1_plain_norm_gemma4_e2b_seq_01
m2p1_plain_norm_gemma4_e2b_seq_02
m2p1_plain_norm_gemma4_e2b_seq_03
```

| Batch | Business pass | Finish length | Errors | Wall time | Completion tokens | Total tokens | ms / completion token |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `01` | `4/4` | `0` | `0` | `15844 ms` | `1466` | `1780` | `10.81` |
| `02` | `4/4` | `0` | `0` | `12015 ms` | `1466` | `1780` | `8.20` |
| `03` | `4/4` | `0` | `0` | `12047 ms` | `1466` | `1780` | `8.22` |

Aggregate:

| Metric | Value |
| --- | ---: |
| Average wall time | `13302 ms` |
| Average completion tokens | `1466` |
| Average total tokens | `1780` |
| Average ms / completion token | `9.07` |
| Average response chars | `2478` |
| Average ms / 1000 response chars | `5368` |
| Average VRAM peak | `4471 MB` |
| Average RAM peak | `21236.837 MB` |
| GPU util peak max | `85%` |
| GPU power peak max | `123.38 W` |

Per-task averages across three sequential batches:

| Task | Completion tokens | Response chars | Latency |
| --- | ---: | ---: | ---: |
| `summary_short` | `362` | `704` | `4437 ms` |
| `lecture_notes` | `388` | `780` | `3099 ms` |
| `mic_command_answer` | `297` | `537` | `2406 ms` |
| `freeform_rewrite` | `419` | `457` | `3360 ms` |

## B. App concurrency 2

Run IDs:

```text
m2p1_plain_norm_gemma4_e2b_appconc2_01
m2p1_plain_norm_gemma4_e2b_appconc2_02
m2p1_plain_norm_gemma4_e2b_appconc2_03
```

| Batch | Business pass | Finish length | Errors | Wall time | Completion tokens | Total tokens | ms / completion token |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `01` | `4/4` | `0` | `0` | `8391 ms` | `1474` | `1788` | `5.69` |
| `02` | `4/4` | `0` | `0` | `8515 ms` | `1509` | `1823` | `5.64` |
| `03` | `4/4` | `0` | `0` | `8235 ms` | `1442` | `1756` | `5.71` |

Aggregate:

| Metric | Value |
| --- | ---: |
| Average wall time | `8380 ms` |
| Average completion tokens | `1475` |
| Average total tokens | `1789` |
| Average ms / completion token | `5.68` |
| Average response chars | `2619` |
| Average ms / 1000 response chars | `3200` |
| Average VRAM peak | `4476 MB` |
| Average RAM peak | `21299.349 MB` |
| GPU util peak max | `85%` |
| GPU power peak max | `123.35 W` |

Per-task averages across three `app_concurrency=2` batches:

| Task | Completion tokens | Response chars | Latency |
| --- | ---: | ---: | ---: |
| `summary_short` | `354` | `726` | `3709 ms` |
| `lecture_notes` | `400` | `833` | `4328 ms` |
| `mic_command_answer` | `315` | `584` | `3583 ms` |
| `freeform_rewrite` | `406` | `476` | `4052 ms` |

## Acceptance check

| Profile | Business pass | Finish length | Errors | Avg wall | Avg ms/completion token | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| App concurrency `1` | `12/12` | `0` | `0` | `13302 ms` | `9.07` | accepted baseline |
| App concurrency `2` | `12/12` | `0` | `0` | `8380 ms` | `5.68` | accepted accelerated candidate |

Speedup summary:

| Metric | Value |
| --- | ---: |
| Wall-clock speedup | `1.59x` |
| Completion-token-normalized speedup | `1.60x` |
| Response-char-normalized speedup | `1.68x` |

The M2p.1 constrained run confirms that the plain text artifact speedup remains above the `>= 1.2x` threshold after token normalization. This is stronger evidence than M2p's `~3.48x` wall-clock signal, but it is still synthetic Lab evidence rather than a production guarantee.

## Privacy check

All accepted M2p.1 artifacts were spot-checked for raw prompt/response leakage. The scan found no local paths, command lines, cwd, usernames, raw messages, raw content, raw synthetic prompts, raw fake responses, API keys, or secrets in `environment.json`, `metrics.jsonl`, `report.md`, `structured_errors.jsonl`, `summary.json`, `system_samples.jsonl`, or `system_summary.json` for the six accepted runs.

## What this proves

- `plain_text_artifacts_normalized` can run the four plain-text artifact classes with stable validation across three batches per profile.
- `app_concurrency=2` remains faster than sequential after completion-token and response-character normalization.
- Completion token totals are close across profiles (`1466` average vs `1475` average), so this is a better throughput signal than the first M2p wall-clock-only run.
- System metrics collection works for repeatability runs.

## What this does not prove yet

- It does not prove behavior on unresolved model candidates.
- It does not evaluate real user content, long text artifacts, cache/stateful behavior, vision, native load/config, `keepModelInMemory`, or `tryMmap`.
- It does not prove production WVM runtime integration; this remains isolated LM Studio Lab evidence.

## Next gated steps

1. Commit the Lab-only M2p.1 diagnostic and this evidence summary after explicit approval.
2. Make unresolved candidates visible in LM Studio or provide exact compatible IDs.
3. Repeat safe `/v1/models` resolution.
4. Start M1/M2 multi-model screening only after candidate identity is resolved.
