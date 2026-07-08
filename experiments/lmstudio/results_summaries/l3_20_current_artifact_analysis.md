# L3.20 Current Artifact Analysis

## Source files

- present: `docs/live_demo/latest_text_quality_gemma/latest_snapshot.json`
- present: `docs/live_demo/latest_text_quality_gemma/report.md`
- present: `experiments/lmstudio/results_summaries/l3_17_text_quality_wave1_rerun_decision_record.md`
- present: `experiments/lmstudio/results_summaries/l3_17_text_quality_12b_decision_record.md`
- present: `experiments/lmstudio/results_summaries/l3_17_text_quality_gemma_decision_record.md`
- present: `docs/live_demo/latest_text_quality_e2b_e4b_sustained/latest_snapshot.json`
- present: `docs/live_demo/latest_text_quality_e2b_e4b_sustained/report.md`
- present: `experiments/lmstudio/results_summaries/l3_19_e2b_e4b_sustained_text_screening_decision_record.md`

## Current state extracted from sanitized snapshots

### L3.17/L3.17.1 Gemma text quality

- attempt_count: `16`
- pass_count: `16`
- fail_count: `0`
- hard_fail_count: `0`
- length_ratio_warning_count: `4`
- failure_categories: `{}`
- warning_categories: `{'too_long': 4}`

### L3.19 sustained E2B/E4B

- attempt_count: `48`
- pass_count: `40`
- fail_count: `8`
- hard_fail_count: `8`
- failure_categories: `{'language_mismatch': 8}`
- per_language: `{'ru_en_mixed': {'pass': 24, 'warning': 0}, 'ru_ru': {'fail': 8, 'hard_fail': 8, 'pass': 16, 'warning': 0}}`
- per_complexity: `{'complex': {'pass': 16, 'warning': 0}, 'medium': {'pass': 16, 'warning': 0}, 'simple': {'fail': 8, 'hard_fail': 8, 'pass': 8, 'warning': 0}}`

## Failure taxonomy

### Model failures

No accepted E2B/E4B evidence points to a stable model-capability failure. E2B/E4B passed L3.17.1 current text quality and L3.19 failures were concentrated in one artificial strict language task rather than broad schema, JSON, finish reason, or id failure.

12B remains a model-family/blocker candidate for this structured-output family because it repeatedly failed schema/id contract while passing parse/language/business/finish checks. With current committed artifacts, this is best classified as `schema contract failure` / `blocked model issue`, not a Russian-language failure.

### Prompt failures

L3.19 shows that the prompt/task shape for `ru_ru_simple_single` was misleading: it made simple Russian language ratio a hard gate while the model otherwise held schema/id. This is a prompt/task-design problem more than a broad generation problem.

### Validator failures

The old language validator was too global: it could treat JSON metadata, enum-like values, and technical English tokens as output-language evidence. L3.20 addresses this by moving toward value-path language validation and explicit output language policies.

### Task design failures

`ru_ru_simple_single` mixed several concerns: language policy, synthetic simple JSON shape, length ratio, and task realism. It is too artificial to remain a hard production-like gate.

### Schema contract failures

12B failed `json_schema` and `id_exact` in the L3.17 12B decision record. E2B/E4B did not show schema/id regression in accepted L3.17.1 or L3.19.

### Language policy failures

L3.19 hard failures are language policy failures on `ru_ru_simple_single`. They should not be treated as evidence that E2B/E4B cannot do postprocessing.

### Retry failures

Retry did not rescue L3.19 `ru_ru_simple_single`, and 12B retry did not produce an accepted schema/id contract. These failures should not be treated as reasons for repeated live reruns; they indicate task/policy/schema redesign work.

## Required answers

1. **Which failures were real model failures?** 12B schema/id instability is the only strong model/blocker candidate. E2B/E4B failures are not broad model failures.
2. **Which failures were validator/policy issues?** L3.19 `ru_ru_simple_single` language hard failures and earlier simple length-ratio hard treatment were validator/policy issues.
3. **Which tasks are too artificial?** `ru_ru_simple_single` is too artificial as a hard gate. It stresses global Russian ratio more than realistic Whisper cleanup.
4. **Which tasks are closest to real Whisper postprocessing?** Term normalization, transcript cleanup, paragraphing, filler cleanup, mixed RU/EN technical cleanup, and action item extraction.
5. **Should `ru_ru_simple_single` remain in a hard gate?** No. Keep it as diagnostic/regression-only or replace it with production-like postprocessing fixtures.
6. **Which failures should not be treated by repeated live reruns?** 12B schema/id contract failures without new instrumentation, and `ru_ru_simple_single` policy failures. Rerunning live does not fix taxonomy/validator mistakes.
