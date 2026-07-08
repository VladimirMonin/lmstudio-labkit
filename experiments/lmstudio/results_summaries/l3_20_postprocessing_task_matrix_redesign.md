# L3.20 — Postprocessing Task Matrix Redesign + Artifact Analysis

## Status

Accepted as an **offline redesign slice**.

This stage intentionally performed no live inference and made no model-quality acceptance claim.

## Why this slice exists

L3.17/L3.17.1 proved useful structured-output behaviour for E2B/E4B and isolated 12B as a schema/id-contract blocker. L3.19 then showed that continuing to chase a single strict-Russian simple task was not the right next abstraction.

The L3.20 redesign separates the axes that were previously conflated:

1. `task_intent` — what postprocessing operation is requested.
2. `response_schema` / `structure_complexity` — what JSON shape is required.
3. `input_profile` — what kind of transcript input is represented.
4. `output_language_policy` — whether to preserve input language or translate explicitly.
5. `validation_policy` — what can be checked automatically and what remains manual quality review.

## Hard scope

Allowed in this slice:

- sanitized artifact analysis
- offline/fake runs
- synthetic postprocessing fixtures
- prompt variants in config
- validator improvements
- tests
- local-only manual review pack
- public-safe docs and decision record

Forbidden and not performed:

- live inference
- model load
- model download
- image live
- 12B rerun
- 26B
- Qwen
- throughput/parallel live
- overnight/stress
- `/v1/responses`
- route matrix
- raw prompt/response artifacts in git

## New matrix axes

Added planner axes:

```text
task_intent
input_profile
output_language_policy
validation_policy
```

The L3.20 config uses these values:

```text
task_intent:
- punctuate
- remove_fillers_paragraphs
- fix_asr_terms_summary_actions
- translate_summary
- summary_action_items

input_profile:
- asr_noise_ru
- asr_noise_ru_en_mixed
- clean_en

output_language_policy:
- preserve_input_language
- translate_to_ru

validation_policy:
- auto_schema_language_manual_quality
- manual_quality_required
```

## Synthetic postprocessing tasks

The offline config covers representative Whisper postprocessing operations:

```text
ru_punctuation_simple_preserve
ru_fillers_blocks_preserve
mixed_terms_complex_preserve
en_translation_simple_to_ru
ru_action_items_complex_preserve
```

These tasks intentionally decouple semantic task complexity from JSON shape:

- simple JSON can carry non-trivial translation or punctuation work;
- blocks JSON can carry paragraph/filler cleanup;
- complex nested JSON can carry summaries, action items, and term preservation.

## Validator changes

Language validation now supports explicit output policies:

```text
preserve_input_language
translate_to_ru
translate_to_en
```

`preserve_input_language` resolves by input language:

```text
ru_ru        -> allow_code_terms
ru_en_mixed  -> mixed_ru_en
en_ru        -> mixed_ru_en
en_en        -> strict_en
```

`translate_to_ru` resolves to `allow_code_terms`.
`translate_to_en` resolves to `strict_en`.

Language ratio validation now ignores JSON bookkeeping fields that should not dominate language classification:

```text
id
language
schema_version
status
type
task_intent
input_profile
output_language_policy
validation_policy
terms
tags
keywords
```

The `allow_code_terms` threshold was relaxed from 0.25 to 0.15 while still requiring `cyr > 0`, so English-only output still fails for Russian-preserving tasks, but short Russian content with technical terms such as `Django`, `Qwen`, or `Embedding` is not rejected solely by Latin-token ratio.

## Offline run result

Config:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_20_postprocessing_redesign.offline.yaml
```

Run shape:

```text
planned_request_count: 20
live: false
model_loads: false
raw prompt/response artifacts: false
```

Offline/fake result:

```text
attempt_count: 20
pass_count: 20
fail_count: 0
hard_fail_count: 0
pass_rate: 1.0
```

This verifies the redesigned config, schemas, id paths, axes, and validators under fake execution. It does **not** prove live model quality.

## Local-only review pack

A local-only manual review pack was created outside git:

```text
/tmp/labkit-l320-review-pack
```

It contains synthetic task cards for human/agent review of:

- semantic preservation
- punctuation quality
- filler removal
- ASR term correction
- technical term preservation
- action item usefulness

The pack is intentionally not committed.

## Published public-safe artifacts

```text
docs/live_demo/latest_postprocessing_redesign_offline/latest_snapshot.json
experiments/lmstudio/results_summaries/l3_20_postprocessing_task_matrix_redesign.md
```

Privacy status:

```text
status: pass
violation_count: 0
raw_prompt_response_stored: false
```

## Decision

L3.20 establishes the postprocessing matrix design and validator semantics needed before the next live run.

Do not proceed directly to throughput/parallel or broader models from L3.19.

Recommended next live slice:

```text
L3.21 — Postprocessing Live Pilot: E2B/E4B only
```

Suggested scope:

- E2B/E4B only
- text only
- 5 L3.20 tasks
- `cold_per_request`
- `retry_policy`: off + retry1
- repeats: 1 initially
- public-safe latest snapshot
- local-only manual review pack

Keep blocked until explicitly reopened:

- 12B
- 26B
- Qwen
- image live
- throughput/parallel
- overnight/stress
