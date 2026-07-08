# L3.20 Postprocessing Task Matrix Design

## Axes

- `task_intent`: semantic operation requested from the model.
- `response_schema_complexity`: JSON shape complexity (`simple`, `blocks`, `complex`).
- `input_profile`: transcript input class, including ASR noise and mixed technical language.
- `output_language_policy`: explicit language policy, not a global Russian-output rule.
- `prompt_variant`: prompt framing used for the same task.
- `validation_policy`: automatic vs manual-review checks.
- `manual_review_policy`: local-only sampled review for semantic quality.

## Task intent taxonomy

- `punctuation_restore`: restore punctuation, preserve words, no translation, no shortening, no new facts.
- `paragraphing`: split text into paragraphs, preserve meaning and terms.
- `filler_cleanup`: remove or smooth filler phrases without deleting meaningful content.
- `term_normalization`: normalize ASR-distorted technical terms using fixture metadata.
- `transcript_cleanup`: punctuation + filler cleanup + light paragraphing.
- `translation`: explicit target-language translation only.
- `summary`: concise summary, not zero-drift block rewriting.
- `action_items`: semantic extraction of tasks/actions.
- `mixed_postprocess`: production-like cleanup: punctuation, paragraphs, fillers, terms.

## Response schema complexity

### simple

```json
{ "language": "same_as_input", "clean_text": "string", "warnings": ["string"] }
```

or:

```json
{ "title": "string", "summary": "string", "terms": ["string"], "language": "same_as_input" }
```

### blocks

```json
{ "blocks": [{ "id": 0, "text": "string" }] }
```

`id` exact order is mandatory. Missing, extra, duplicate, or reordered ids are hard failures.

### complex

```json
{
  "document": {
    "language": "same_as_input",
    "sections": [
      {
        "id": 0,
        "heading": "string",
        "blocks": [
          {
            "id": 0,
            "text": "string",
            "terms": [{ "source": "string", "normalized": "string" }],
            "flags": { "unclear": false, "needs_review": false }
          }
        ]
      }
    ]
  }
}
```

## Input profiles

- `clean_ru`
- `raw_asr_ru_no_punctuation`
- `raw_asr_ru_fillers`
- `raw_asr_ru_term_noise`
- `ru_en_mixed_tech`
- `clean_en`
- `noisy_en`

## Output language policy

- `preserve_input_language`
- `preserve_mixed_language`
- `translate_to_ru`
- `translate_to_en`

Do not require Russian output globally. Russian input expects Russian output; mixed technical input expects Russian syntax plus preserved English technical terms; English input expects English; translation uses the explicit target.

## Prompt variants

- `baseline`
- `strict_same_language`
- `strict_no_new_facts`
- `term_glossary`
- `paragraphing_focused`
- `translation_focused`

## Validation taxonomy

- Language: value-path based, ignores JSON keys/metadata/ids and technical token lists.
- Term normalization: checks expected normalized terms and forbidden ASR variants for public-safe synthetic fixtures.
- Punctuation: diagnostic by default; hard only when configured.
- Paragraphing: hard only for paragraphing tasks with min/max paragraphs.
- Filler cleanup: hard only for filler cleanup or mixed postprocess.
- No-new-facts: diagnostic/manual review only.

## Matrix profiles

### tiny

E2B/E4B, two task intents, one input profile/language class, simple/blocks, retry off.

### screening

E2B/E4B, task intents `punctuation_restore`, `term_normalization`, `transcript_cleanup`, `paragraphing`; input profiles `raw_asr_ru_no_punctuation`, `raw_asr_ru_fillers`, `raw_asr_ru_term_noise`, `ru_en_mixed_tech`; schemas `simple`, `blocks`; retry off + retry1.

### focused

Only failing cells from screening.

### overnight

Only accepted configs from screening. Example config only; do not run in L3.20.

## Future matrix columns

`model_key`, `model_id`, `task_intent`, `input_profile`, `output_language_policy`, `prompt_variant`, `response_schema_complexity`, `volume`, `context_tier`, `schema_variant`, `retry_policy`, `execution_mode`, `cache_mode`.
