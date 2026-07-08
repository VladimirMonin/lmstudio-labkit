# L3.20.1 — Postprocessing Validator Wiring Report

## Status

Accepted as an offline/code-only wiring slice.

No live inference, model load, model download, 12B rerun, image live, throughput, stress, overnight, `/v1/responses`, or route matrix was run.

## What was wired

The response validation pipeline now carries and uses postprocessing-specific validation metadata:

- `source_text` for before/after diagnostics, stored in artifacts only as hash and character count.
- `expected_terms` for term normalization checks, stored only as hash and count.
- `filler_terms` for filler cleanup checks, stored only as hash and count.
- `punctuation_policy`.
- `paragraphing_policy`.
- `paragraph_count_min` / `paragraph_count_max`.
- `filler_cleanup_policy`.
- `term_normalization_policy`.
- `manual_review_policy`.
- `schema_family` and `response_schema_complexity` for user-facing output extraction.

`validate_response()` now adds postprocessing validation results when the task intent and policies require them:

- `term_normalization_status`.
- `punctuation_metrics`.
- `paragraphing_metrics`.
- `filler_cleanup`.
- `no_new_facts_manual_review`.

## Output extraction

A schema-aware extractor now reads user-facing output values without treating JSON keys or metadata fields as user text:

- `simple`: `clean_text`, `summary`, `title`, `tags[*]`.
- `blocks`: `blocks[*].text`.
- `complex`: `document.title`, `document.sections[*].heading`, `document.sections[*].blocks[*].text`, `document.sections[*].blocks[*].terms[*].normalized`.

Explicit `language_include_paths` still override the defaults.

## Validator severity

Hard validators:

- `term_normalization_status` for `task_intent=term_normalization` unless explicitly configured otherwise.
- `paragraphing_metrics` when `paragraphing_policy=hard` and paragraph limits are configured.
- `filler_cleanup` for `task_intent=filler_cleanup` unless explicitly configured otherwise.

Warning / diagnostic validators:

- `punctuation_metrics` defaults to diagnostic.
- `term_normalization_status` is diagnostic for `transcript_cleanup` / `mixed_postprocess` unless configured as hard.
- `filler_cleanup` is diagnostic for `transcript_cleanup` / `mixed_postprocess` unless configured as hard.
- `no_new_facts_manual_review` is manual-review metadata only, not an automatic hard fail.

`off` remains supported and produces `skip`.

## Prompt templates

The postprocessing prompt templates now contain real task instructions rather than placeholder-only prompts. They include the required common rules:

- Return JSON only.
- Do not use Markdown.
- Follow the provided JSON schema.
- Do not add new facts.
- Preserve input language unless the task explicitly asks for translation.
- Preserve English technical terms when they are technical names.

`term_glossary.md` includes the public-safe glossary for Django, Qwen, embedding, PySide, PySide6, LM Studio, and Lemon Squeezy variants.

## Config and fixture behavior

The L3.20 tiny and screening offline configs now reference source fixtures and prompt templates. The renderer combines:

- prompt template content;
- fixture text;
- task intent;
- response schema complexity;
- optional glossary.

Rendered prompts remain in memory only. Public artifacts store safe metadata only:

- `prompt_template_hash`;
- `source_fixture_id`;
- `fixture_text_hash`;
- `glossary_hash`;
- response `schema_hash`;
- `source_text_hash` and `source_text_char_count`.

## Privacy behavior

The offline run artifacts were checked for raw source and rendered prompt fragments. The checked strings were absent from `cell_results.jsonl`:

- raw fixture text fragments;
- `Return JSON only`;
- `Do not use Markdown`.

## Offline verification

Commands run:

```bash
uv run lmstudio-benchmark plan \
  --config experiments/lmstudio/structured_matrix/configs/matrix.l3_20_postprocessing_tiny.offline.yaml \
  --output-root /tmp/labkit-l3201-plan

uv run lmstudio-benchmark run \
  --config experiments/lmstudio/structured_matrix/configs/matrix.l3_20_postprocessing_tiny.offline.yaml \
  --output-root /tmp/labkit-l3201-fake \
  --profile offline-fake

uv run lmstudio-benchmark summarize \
  --run-dir /tmp/labkit-l3201-fake/matrix_l3_20_postprocessing_tiny_offline

uv run lmstudio-benchmark export-review-pack \
  --run-dir /tmp/labkit-l3201-fake/matrix_l3_20_postprocessing_tiny_offline \
  --output-dir /tmp/labkit-l3201-review-pack
```

Result:

- `attempt_count=4`.
- `pass_count=4`.
- `fail_count=0`.
- `pass_rate=1.0`.
- review pack export passed.
- postprocessing validation metrics are visible in `cell_results.jsonl`.

## Recommended L3.21 live scope

L3.21 can now use the already proposed bounded postprocessing screening scope:

- models: E2B/E4B only;
- task intents: `punctuation_restore`, `term_normalization`, `transcript_cleanup`, `paragraphing`;
- input profiles: `raw_asr_ru_no_punctuation`, `raw_asr_ru_fillers`, `raw_asr_ru_term_noise`, `ru_en_mixed_tech`;
- schemas: `simple`, `blocks`;
- output policies: `preserve_input_language`, `preserve_mixed_language`;
- prompt variants: `strict_same_language`, `term_glossary`;
- retry: `off`, `retry1`;
- context: `8192`;
- execution: `cold_per_request`;
- cache: `none`.

Do not include 12B/26B/Qwen/image/throughput/parallel/overnight in L3.21.

## Non-claims

This slice does not prove live model quality, production readiness, image readiness, throughput, KV reuse, 12B recovery, or host application integration.
