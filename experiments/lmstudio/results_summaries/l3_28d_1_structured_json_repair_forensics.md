# L3.28d.1 Structured JSON Repair Forensics

Status: forensic review of the L3.28 structured JSON canary.

## Source artifacts

- `docs/live_demo/latest_gemma_structured_json_canary/latest_snapshot.json`
- `docs/live_demo/latest_gemma_structured_json_canary/model_summary.csv`
- `docs/live_demo/latest_gemma_structured_json_canary/failure_summary.csv`
- `experiments/lmstudio/results_summaries/l3_28_gemma_family_live_decision_update.md`

## Summary

The L3.28 structured JSON canary failed 0/12, but the evidence points to a broken/under-specified contract rather than a model-family conclusion.

## Failure breakdown

| category | count | affected models |
|---|---:|---|
| language_mismatch | 6 | E2B, E4B, 12B |
| schema_error | 4 | E2B, E4B |
| finish_length | 2 | 12B |

## Answers

1. Which cells failed `language_mismatch`?
   - All simple schema cells failed language validation: E2B/E4B/12B × `ru_ru`/`ru_en_mixed` = 6.
2. Which cells failed `schema_error`?
   - Blocks cells for E2B and E4B failed schema/id contract: E2B/E4B × `ru_ru`/`ru_en_mixed` = 4.
3. Which 12B cells hit `finish_length`?
   - 12B blocks cells for `ru_ru` and `ru_en_mixed` hit finish length.
4. Did JSON parse pass before schema failure?
   - E2B/E4B: JSON parse passed 1.0, so failures were schema/language rather than raw JSON syntax.
   - 12B: JSON parse pass rate was 0.5 due to finish-length blocks cases.
5. Are `language_include_paths` appropriate for schema-only tasks?
   - No. The old canary did not scope structured language validation to schema payload fields. Repair uses `items[*]` for simple and `blocks[*].text` for blocks, avoiding keys/ids/metadata.
6. Are RU fixtures truly Russian?
   - The post-fix L3.28 config used Russian expected payloads, but the prompt did not give the model the actual payload to return.
7. Are mixed fixtures truly mixed?
   - The old mixed simple payload was English-only technical terms. Repair uses mixed Russian/English text such as `Django модель`, `JSON schema`, and `Qwen термин`.
8. Did prompt demand exact schema strongly enough?
   - No. The old prompt said to preserve provided facts, but did not include the concrete facts/output shape in the prompt. Repair prompts include exact JSON shapes and explicit no-markdown/no-extra-fields rules.

## Root cause hypothesis

The canary failed because the task contract was under-specified for generation: `expected_output` existed for the validator, but the live prompt did not provide the model with the exact payload it was expected to emit. Language validation was also too generic for schema-only JSON and mixed-language fixtures were not consistently mixed.

## Repair plan

- Add explicit exact-shape prompts.
- Scope language validation to `items[*]` and `blocks[*].text`.
- Use truly Russian RU fixtures and genuinely mixed RU/EN fixtures.
- Run E2B/E4B first, 8 attempts.
- Run 12B only if E2B/E4B pass.
- Keep 26B structured generation blocked.
