# L3.20 Postprocessing Matrix Redesign Report

## 1. Current state

L3.17/L3.17.1 established that E2B/E4B can satisfy the current structured JSON text-quality gate. L3.19 showed that the next useful work is not another raw live rerun, but a redesign toward realistic Whisper postprocessing tasks.

## 2. What L3.17/L3.19 proved

- E2B/E4B can hold JSON/schema/id for the existing structured text family.
- 12B remains blocked on schema/id contract.
- Sustained E2B/E4B failures were concentrated in an artificial language-policy cell, not in broad JSON or id failure.

## 3. Why `ru_ru_simple_single` was misleading

It over-weighted global Russian language ratio and simple JSON shape. It did not represent realistic transcript cleanup, term normalization, paragraphing, or action item extraction.

## 4. Why task_intent must be separate from schema_complexity

A task can be semantically hard while returning simple JSON; a blocks schema can be used for zero-drift cleanup; complex schemas are future document structures. These must be separate axes.

## 5. Proposed task taxonomy

`punctuation_restore`, `paragraphing`, `filler_cleanup`, `term_normalization`, `transcript_cleanup`, `translation`, `summary`, `action_items`, `mixed_postprocess`.

## 6. Proposed validation taxonomy

Language value paths, term normalization metrics, punctuation diagnostics, paragraphing metrics, filler cleanup metrics, and no-new-facts manual review.

## 7. Proposed prompt variants

`baseline`, `strict_same_language`, `strict_no_new_facts`, `term_glossary`, `paragraphing_focused`, `translation_focused`.

## 8. Proposed fixtures

Public-safe synthetic fixtures were added under `experiments/lmstudio/structured_matrix/datasets/text/postprocessing/`.

## 9. 12B forensic result

No live rerun. Current committed metadata proves schema/id blocking at summary level but lacks path-level detail. Keep 12B blocked and improve sanitized instrumentation before any future rerun.

## 10. Recommended next live matrix

Prepare but do not run L3.21: E2B/E4B only, text only, task intents `punctuation_restore`, `term_normalization`, `transcript_cleanup`, `paragraphing`, input profiles `raw_asr_ru_no_punctuation`, `raw_asr_ru_fillers`, `raw_asr_ru_term_noise`, `ru_en_mixed_tech`, schemas `simple` and `blocks`, policies `preserve_input_language` and `preserve_mixed_language`, prompt variants `strict_same_language` and `term_glossary`, retry off + retry1, context 8192, cold_per_request, cache none.

## 11. Recommended overnight matrix

Only after screening acceptance: accepted E2B/E4B cells, no blocked models, no image live, no throughput/parallel until quality gate is clean.

## 12. Non-claims

No L3.20 live inference was run. No model load/download was run. L3.20 does not prove production readiness, 12B readiness, image readiness, throughput, KV reuse, or host-app integration.
