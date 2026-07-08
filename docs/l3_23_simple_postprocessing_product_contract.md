# L3.23 — Simple Postprocessing Product Contract

## Status

L3.23 turns the accepted L3.22 LabKit result into an integration-ready contract for a host application.

Accepted evidence:

- L3.22 commit: `98d4c9f feat: publish L3.22 product-like simple postprocessing matrix`
- main run: 80/80 pass, fail_count=0, hard_fail_count=0
- models: `google/gemma-4-e2b`, `google/gemma-4-e4b`
- runtime: context 8192, cold per request, cache none, parallel 1

This document does not promote blocked modes.

## 1. Accepted modes

### Default candidate

```text
transcript_cleanup/simple + strict_no_new_facts
```

Use when the host application needs to clean ASR-like transcript text while preserving meaning and language.

### Controlled optional candidate

```text
term_normalization/simple + term_glossary
```

Use when the host application needs explicit technical-term normalization with a compact glossary.

### Blocked modes

Do not expose yet:

- blocks schema tasks;
- paragraphing hard gate;
- complex schema;
- 12B / 26B / Qwen model families;
- image live;
- throughput / parallel modes;
- session/warmup modes;
- overnight/stress modes.

## 2. Prompt templates

### Transcript cleanup prompt contract

Prompt variant: `strict_no_new_facts`.

Required behavior:

- preserve meaning;
- preserve source language or mixed-language style;
- remove or soften ASR noise when safe;
- do not add facts;
- do not invent names, links, dates, code, or claims;
- return only the requested JSON object.

Recommended operator instruction:

```text
Clean the transcript text for readability.
Preserve the original meaning and language.
Do not add facts, explanations, or external knowledge.
Return valid JSON matching the schema.
```

### Term normalization prompt contract

Prompt variant: `term_glossary`.

Required behavior:

- normalize only glossary-covered technical terms;
- keep natural Russian or mixed RU/EN text;
- do not rewrite unrelated content;
- do not add facts;
- return the normalized terms in the `terms` list when available.

Recommended operator instruction:

```text
Normalize recognized technical terms using the provided glossary.
Keep the text natural and preserve the source language.
Do not add facts or rewrite unrelated content.
Return valid JSON matching the schema.
```

## 3. App-facing API proposal

### Mode enum

```python
from enum import Enum


class SimplePostprocessingMode(str, Enum):
    TRANSCRIPT_CLEANUP = "transcript_cleanup"
    TERM_NORMALIZATION = "term_normalization"
```

### Call shape

```python
result = postprocess_transcript_simple(
    text=raw_transcript,
    mode="transcript_cleanup",
    model="google/gemma-4-e2b",
    context_tier=8192,
)
```

### Function signature proposal

```python
def postprocess_transcript_simple(
    *,
    text: str,
    mode: SimplePostprocessingMode | str,
    model: str = "google/gemma-4-e2b",
    context_tier: int = 8192,
    retry_policy: str = "off",
) -> dict:
    ...
```

Recommended default model: `google/gemma-4-e2b`.

Use `google/gemma-4-e4b` only when a later latency/resource/quality review justifies it. L3.22 validation quality alone does not justify selecting E4B over E2B.

## 4. Input schema

Application-level request:

```json
{
  "text": "string",
  "mode": "transcript_cleanup",
  "model": "google/gemma-4-e2b",
  "context_tier": 8192,
  "retry_policy": "off"
}
```

Constraints:

- `text` must be non-empty after trimming;
- `mode` must be `transcript_cleanup` or `term_normalization`;
- `context_tier` must be `8192` for the accepted L3.22 contract;
- `retry_policy` may be `off` or `retry1`, but retry is not required by L3.22 quality evidence.

## 5. Output JSON schema

### Transcript cleanup output

```json
{
  "language": "same_as_input",
  "clean_text": "string",
  "warnings": ["string"]
}
```

Required fields:

- `language`
- `clean_text`
- `warnings`

### Term normalization output

```json
{
  "language": "same_as_input",
  "clean_text": "string",
  "terms": [
    {
      "source": "джанго",
      "normalized": "Django"
    }
  ],
  "warnings": ["string"]
}
```

Required fields:

- `language`
- `clean_text`
- `terms`
- `warnings`

## 6. Validation policy

### Hard validators

Use as hard failures:

- JSON parse;
- JSON schema;
- non-empty output for non-empty input;
- language compliance;
- privacy and leak checks;
- no placeholder text;
- no reasoning/chain-of-thought leak.

For `term_normalization/simple`, also hard-check expected glossary terms when the source text contains those terms.

### Diagnostic validators

Use as diagnostic or warnings in this product contract:

- punctuation quality;
- filler cleanup quality;
- manual review required;
- no-new-facts review when raw-output human review is not available.

Do not use paragraphing as a hard gate in this contract.

## 7. Retry policy

L3.22 passed with both `off` and `retry1`:

- `off`: 40/40 pass;
- `retry1`: 40/40 pass;
- retry recoveries: 0, because no first-pass failures occurred.

Recommended product default:

```text
retry_policy=off
```

Optional safety-net mode:

```text
retry_policy=retry1
```

Only retry on infrastructure-safe validation failures such as invalid JSON or schema mismatch. Do not use retry to hide semantic or product-quality issues.

## 8. Privacy policy

Do not store or publish:

- raw prompts;
- raw model responses;
- base URLs;
- host names;
- tokens or credentials;
- private local paths;
- private user transcripts.

Allowed public artifacts:

- aggregated metrics;
- sanitized summaries;
- schema and config descriptions;
- model IDs;
- validation taxonomy;
- privacy scan results.

Raw-output review, when needed, must stay local-only and outside the repository.

## 9. User-facing limitations

The feature should be presented as local transcript postprocessing, not as fact checking.

Do not claim:

- production readiness beyond the simple modes;
- support for blocks/paragraphing/complex schemas;
- support for image inputs;
- throughput or parallel performance;
- stronger-model behavior for 12B/26B/Qwen;
- guaranteed semantic perfection.

Suggested user-facing wording:

```text
Clean up transcript text while preserving meaning. The model may make mistakes; review important output before publishing.
```

## 10. Fallback behavior

If validation fails:

1. return the original text unchanged;
2. attach warnings explaining that postprocessing was not applied;
3. do not silently return partially invalid model output;
4. do not expose raw model error details to end users;
5. log sanitized failure category and validator names only.

Example fallback:

```json
{
  "language": "same_as_input",
  "clean_text": "<original input>",
  "warnings": ["postprocessing_failed_validation"]
}
```

## 11. Model recommendation

Default recommendation:

```text
google/gemma-4-e2b
```

Reason:

- L3.22 validation quality tied E2B and E4B;
- E2B is the lighter candidate;
- E4B should not be selected solely on quality from this slice.

Use E4B only if a future latency/resource/local raw-output review shows a practical advantage.

## 12. Next integration gate

Before host-application integration, run a local-only raw-output quality review with realistic transcripts. Commit only sanitized conclusions.

The next gate should answer:

- does `transcript_cleanup/simple` preserve meaning in real transcripts?
- does it remove or soften ASR noise without over-editing?
- does it avoid adding facts?
- are warnings actionable or noisy?
- is E2B still sufficient by human review?
