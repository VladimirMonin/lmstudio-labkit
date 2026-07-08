# L3.21.1 — Focused Postprocessing Failure Forensics

## Status

Public-safe forensic over L3.21 sanitized artifacts. Raw prompts, raw responses, raw base URL, host data, and secrets were not used or committed.

Sources inspected:

- `docs/live_demo/latest_postprocessing_screening_live/latest_snapshot.json`
- `docs/live_demo/latest_postprocessing_screening_live/report.md`
- `docs/live_demo/latest_postprocessing_screening_live/model_summary.csv`
- `docs/live_demo/latest_postprocessing_screening_live/failure_summary.csv`
- `docs/live_demo/latest_postprocessing_screening_live/retry_summary.csv`
- `experiments/lmstudio/results_summaries/l3_21_postprocessing_screening_live_decision_record.md`
- local sanitized metrics: `/tmp/labkit-l321-live/matrix_l3_21_postprocessing_screening_live/cell_results.jsonl`

## Summary

L3.21 failed because three independent contracts were red while infrastructure was healthy:

- `blocks` id contract: duplicate/missing id pattern, not mere order-only drift.
- `term_normalization`: model normalized a subset of terms; validator/task expected glossary terms absent from the source.
- `paragraphing`: model returned one paragraph; the fixture and schema made the hard threshold artificial for the first live slice.

## Section A — blocks `id_exact` mismatch

### Safe metadata

| cell_id | model_id | task_id | task_intent | input_profile | prompt_variant | retry_policy | repeat | expected | seen | missing | unexpected | duplicate | first_mismatch | id_order_preserved | json_schema | schema_first_error | finish_reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cell_3de2358030c0 | google/gemma-4-e2b | screen_punctuation_restore_blocks | punctuation_restore | raw_asr_ru_no_punctuation | strict_same_language | off | 0 | 2 | 2 | 1 | 0 | 1 | 0 | False | pass | None | stop |
| cell_8f9f5fbbd483 | google/gemma-4-e2b | screen_punctuation_restore_blocks | punctuation_restore | raw_asr_ru_no_punctuation | strict_same_language | retry1 | 0 | 2 | 2 | 1 | 0 | 1 | 0 | False | pass | None | stop |
| cell_de5e26c5e136 | google/gemma-4-e4b | screen_punctuation_restore_blocks | punctuation_restore | raw_asr_ru_no_punctuation | strict_same_language | off | 0 | 2 | 2 | 1 | 0 | 1 | 0 | False | pass | None | stop |
| cell_980843bba147 | google/gemma-4-e4b | screen_punctuation_restore_blocks | punctuation_restore | raw_asr_ru_no_punctuation | strict_same_language | retry1 | 0 | 2 | 2 | 1 | 0 | 1 | 0 | False | pass | None | stop |
| cell_ce8b36cfc4b9 | google/gemma-4-e4b | screen_paragraphing_blocks | paragraphing | raw_asr_ru_fillers | paragraphing_focused | off | 0 | 2 | 2 | 1 | 0 | 1 | 0 | False | pass | None | stop |
| cell_ab2cb726cd32 | google/gemma-4-e4b | screen_paragraphing_blocks | paragraphing | raw_asr_ru_fillers | paragraphing_focused | retry1 | 0 | 2 | 2 | 1 | 0 | 1 | 0 | False | pass | None | stop |
| cell_6e665462e3dc | google/gemma-4-e4b | screen_term_normalization_blocks | term_normalization | raw_asr_ru_term_noise | term_glossary | off | 0 | 2 | 2 | 1 | 0 | 1 | 0 | False | pass | None | stop |
| cell_70613ff20105 | google/gemma-4-e4b | screen_term_normalization_blocks | term_normalization | raw_asr_ru_term_noise | term_glossary | retry1 | 0 | 2 | 2 | 1 | 0 | 1 | 0 | False | pass | None | stop |
| cell_5992fdd502de | google/gemma-4-e4b | screen_transcript_cleanup_blocks | transcript_cleanup | ru_en_mixed_tech | strict_no_new_facts | off | 0 | 2 | 2 | 1 | 0 | 1 | 0 | False | pass | None | stop |
| cell_898295d768a1 | google/gemma-4-e4b | screen_transcript_cleanup_blocks | transcript_cleanup | ru_en_mixed_tech | strict_no_new_facts | retry1 | 0 | 2 | 2 | 1 | 0 | 1 | 0 | False | pass | None | stop |

### Answers

1. The model did **not** return all ids in a different order. The stable metrics show `seen_count=2`, `missing_count=1`, `duplicate_count=1`, `unexpected_count=0`.
2. The model loses one required id in every id failure.
3. The model duplicates one id in every id failure.
4. It is task-intent dependent in rate, but not exclusive: punctuation, paragraphing, term normalization, and transcript cleanup block cells all show the same duplicate/missing shape.
5. It appears across prompt variants (`strict_same_language`, `paragraphing_focused`, `term_glossary`, `strict_no_new_facts`).
6. It is model dependent in frequency: E4B fails more block cells than E2B, but E2B also fails punctuation blocks.
7. The issue is blocks-only; simple schema cells skip `id_exact` and can pass.

### Selected one-variable fix

Applied **schema hardening**: block schemas now use per-position `prefixItems` with `id.const` instead of an item-level `id.enum`. This does not hide missing/duplicate/reordered ids; it makes invalid positional ids fail at `json_schema` as well as `id_exact`.

## Section B — `term_normalization` failure

### Safe metadata

| model_id | task_id | input_profile | prompt_variant | retry_policy | expected_seen | expected_normalized | forbidden_remaining | term_recall | term_precision | language | schema |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| google/gemma-4-e2b | screen_term_normalization_simple | raw_asr_ru_term_noise | term_glossary | off | 5 | 5 | 0 | 0.7143 | 1.0 | pass | pass |
| google/gemma-4-e2b | screen_term_normalization_simple | raw_asr_ru_term_noise | term_glossary | retry1 | 5 | 5 | 0 | 0.7143 | 1.0 | pass | pass |
| google/gemma-4-e2b | screen_term_normalization_blocks | raw_asr_ru_term_noise | term_glossary | off | 5 | 5 | 0 | 0.7143 | 1.0 | pass | pass |
| google/gemma-4-e2b | screen_term_normalization_blocks | raw_asr_ru_term_noise | term_glossary | retry1 | 5 | 5 | 0 | 0.7143 | 1.0 | pass | pass |
| google/gemma-4-e4b | screen_term_normalization_simple | raw_asr_ru_term_noise | term_glossary | off | 5 | 5 | 0 | 0.7143 | 1.0 | pass | pass |
| google/gemma-4-e4b | screen_term_normalization_simple | raw_asr_ru_term_noise | term_glossary | retry1 | 5 | 5 | 0 | 0.7143 | 1.0 | pass | pass |
| google/gemma-4-e4b | screen_term_normalization_blocks | raw_asr_ru_term_noise | term_glossary | off | 5 | 5 | 5 | 0.7143 | 0.5 | pass | pass |
| google/gemma-4-e4b | screen_term_normalization_blocks | raw_asr_ru_term_noise | term_glossary | retry1 | 5 | 5 | 5 | 0.7143 | 0.5 | pass | pass |

### Answers

1. The model does normalize part of the glossary; it is not a total failure.
2. Every strict term failure normalized 5 terms with recall `0.7143` against a 7-term glossary.
3. Most simple failures had `forbidden_term_variants_remaining=0`; E4B blocks preserved some source variants as well as normalized forms.
4. The prompt variant was `term_glossary`, and the prompt template exists. Artifacts store only `prompt_template_hash`, not the raw rendered prompt.
5. For `transcript_cleanup`, term normalization was diagnostic and passed. Keeping it diagnostic there is correct.
6. For the first product-like run, `term_normalization` can stay hard only after the validator filters expected terms to source-present terms.

### Selected one-variable fix

Applied validator/task fix: term validation now uses user-facing extracted text (`simple`: `clean_text`, `summary`, `title`, `tags[*]`; `blocks`: `blocks[*].text`) and filters expected terms to terms actually present in the source transcript. It does not count JSON keys, metadata, expected/source fields, or schema enum fields.

## Section C — paragraphing failure

### Safe metadata

| model_id | task_id | prompt_variant | retry_policy | paragraph_count | min | max | empty | response_chars | schema | language |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| google/gemma-4-e2b | screen_paragraphing_simple | paragraphing_focused | off | 1 | 2 | None | 1 | 145 | pass | pass |
| google/gemma-4-e2b | screen_paragraphing_simple | paragraphing_focused | retry1 | 1 | 2 | None | 1 | 145 | pass | pass |
| google/gemma-4-e2b | screen_paragraphing_blocks | paragraphing_focused | off | 1 | 2 | None | 0 | 142 | pass | pass |
| google/gemma-4-e2b | screen_paragraphing_blocks | paragraphing_focused | retry1 | 1 | 2 | None | 0 | 142 | pass | pass |
| google/gemma-4-e4b | screen_paragraphing_simple | paragraphing_focused | off | 1 | 2 | None | 0 | 390 | pass | pass |
| google/gemma-4-e4b | screen_paragraphing_simple | paragraphing_focused | retry1 | 1 | 2 | None | 0 | 390 | pass | pass |
| google/gemma-4-e4b | screen_paragraphing_blocks | paragraphing_focused | off | 1 | 2 | None | 0 | 195 | pass | pass |
| google/gemma-4-e4b | screen_paragraphing_blocks | paragraphing_focused | retry1 | 1 | 2 | None | 0 | 195 | pass | pass |

### Answers

1. The model returns one paragraph in all paragraphing failures.
2. There is no evidence that the model used a different paragraph delimiter; metrics show `paragraph_count=1`.
3. `clean_text` with double-newline is a weak schema for paragraphing; `blocks` is also not a paragraph schema.
4. `paragraph_count_min=2` was artificial for the old short `raw_asr_ru_fillers` fixture.
5. Paragraphing should remain blocked or diagnostic-first until a longer fixture and/or paragraph-specific schema is used.

### Selected one-variable fix

Applied fixture adjustment: added a longer `raw_asr_ru_paragraphing` fixture and routed paragraphing tasks to it. Canary still failed paragraphing simple 2/2, so fixture length alone is insufficient; next fix should be schema/policy, not another rerun.

## Offline verification after fixes

Offline fake run over the updated screening config:

- attempt_count: 32
- pass_count: 28
- fail_count: 4
- remaining failure category: `paragraphing_mismatch` only
- postprocessing metrics visible: `term_normalization_status`, `punctuation_metrics`, `paragraphing_metrics`, `filler_cleanup`, `no_new_facts_manual_review`
- raw fixture/prompt/base-url leak check: clean

## Targeted canary evidence

Canary run: `/tmp/labkit-l3211-canary-*/matrix_l3_21_1_postprocessing_canary_live`.

- attempt_count: 6
- pass_count: 2
- fail_count: 4
- term normalization simple: 2/2 pass
- blocks id hardening: 0/2 pass, now fails `json_schema` at `$.blocks[0].id:const` plus `id_exact`, which correctly exposes the duplicate-id behavior
- paragraphing simple: 0/2 pass, still `paragraphing_mismatch`
- final_loaded_instances: 0

## Conclusion

The only fix validated by live canary is term normalization strict-simple. Blocks and paragraphing remain blocked for product-like runs. No broad matrix should run next.
