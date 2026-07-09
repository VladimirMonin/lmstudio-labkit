# L3.24 — Simple Postprocessing Integration Adapter Plan

## Status

This adapter plan is based on L3.22/L3.23 validation evidence plus L3.24 local raw-output review.

It is not an instruction to expose the feature to end users yet.

## Integration principle

The host application should integrate simple postprocessing only behind a hidden/dev feature flag until raw prose quality is tightened.

Recommended gate:

```text
feature_flag: local_simple_postprocessing_dev
user_visible: false
public_model_picker: false
public_mode_picker: false
```

## Accepted adapter surface

### Modes

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
    mode=SimplePostprocessingMode.TRANSCRIPT_CLEANUP,
    model="google/gemma-4-e4b",
    context_tier=8192,
    retry_policy="off",
)
```

### Output shape

Transcript cleanup:

```json
{
  "language": "same_as_input",
  "clean_text": "string",
  "warnings": ["string"]
}
```

Term normalization:

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

The current LabKit validation schema accepts the simpler shared shape without `terms`. A host adapter can add `terms` as an app-facing enrichment only after the term-normalization contract is tightened.

## Updated model recommendation

L3.22/L3.23 validation quality was tied:

```text
E2B == E4B by validation pass rate
```

L3.24 raw review was not tied:

```text
E4B > E2B for visible transcript-cleanup quality
```

Recommended hidden/dev default:

```text
model: google/gemma-4-e4b
mode: transcript_cleanup
context_tier: 8192
retry_policy: off
```

Keep E2B available only as:

- a lightweight fallback;
- a latency/resource comparison candidate;
- a possible minimal-cleanup mode if identity-preserving output is acceptable.

Do not select E2B as the user-facing quality default solely from L3.22 validation evidence.

## Adapter pipeline

### 1. Input guard

Before calling LM Studio:

- reject empty text after trimming;
- apply a maximum input size based on the 8192 context contract;
- do not send private transcripts unless the user has explicitly invoked local processing;
- never send image inputs through this adapter;
- never switch to blocks, paragraphing, complex schema, 12B/26B/Qwen, throughput, parallel, session/warmup, or `/v1/responses`.

### 2. Request construction

Use only:

```text
endpoint: /v1/chat/completions
response format: json_schema
context_tier: 8192
temperature: 0
parallel: 1
cache: none
execution: cold_per_request
```

Prompt contract:

- `transcript_cleanup`: `strict_no_new_facts_v2` conservative cleanup;
- `term_normalization`: glossary-only normalization;
- no external knowledge;
- return JSON only;
- preserve source language and mixed technical terms.

### 3. Hard validation

Fail closed on:

- invalid JSON;
- schema mismatch;
- empty `clean_text` for non-empty input;
- language-policy violation;
- reasoning/chain-of-thought leak;
- placeholder text;
- privacy leak;
- blocked mode/model/axis request.

### 4. Diagnostic validation

Track but do not show directly to users:

- punctuation improvement;
- filler cleanup;
- no-op/identity output when input contains ASR noise;
- term coverage;
- language drift in term normalization;
- warning usefulness.

New L3.24-required diagnostics:

```text
cleanup_noop_when_noise_present
term_normalization_language_drift
model_warning_empty_or_unhelpful
```

### 5. Fallback behavior

If any hard validator fails:

```json
{
  "status": "fallback",
  "clean_text": "<original input text>",
  "warnings": ["local_postprocessing_failed"]
}
```

Do not show raw model errors to users.

Store only sanitized diagnostic events:

- mode;
- model key;
- failure category;
- validation status;
- latency bucket;
- input/output hashes and lengths;
- no raw prompt;
- no raw response;
- no local base URL;
- no private transcript.

### 6. Retry policy

Default:

```text
retry_policy=off
```

Optional future retry:

```text
retry1 only for invalid JSON or schema mismatch
```

Do not retry semantic quality failures such as:

- language drift;
- no-op cleanup;
- suspicious additions;
- poor readability.

Those should fall back or be routed to a future prompt/validator improvement stage.

## Host-app integration stages

### Stage A — dev-only adapter skeleton

Allowed after L3.24:

- implement adapter interface;
- keep feature hidden;
- use synthetic/local test fixtures;
- no public UI;
- no model picker;
- no persistence of raw prompt/response.

### Stage B — tightened quality gate

Required before real user trials:

- improve transcript-cleanup prompt so E2B/E4B perform visible conservative cleanup;
- measure `cleanup_noop_diagnostics` / `cleanup_noop_when_noise_present`;
- measure `term_normalization_language_drift` as a warning-level drift diagnostic;
- rerun local raw review on 10–20 realistic synthetic/private-safe snippets.

### Stage C — internal dogfood only

Allowed only if Stage B passes:

- explicit local processing toggle;
- clear fallback to original transcript;
- developer-visible diagnostics;
- no raw logging.

### Stage D — user-visible release

Not accepted yet.

Requires:

- stronger raw-output review;
- realistic non-synthetic transcripts reviewed locally;
- clear latency/resource budget;
- UX copy for limitations;
- privacy confirmation in the host application.

## What not to expose yet

Do not expose:

- term normalization as a general user feature;
- model picker;
- retry settings;
- warnings emitted by the model;
- blocks mode;
- paragraphing mode;
- complex schema;
- 12B;
- 26B;
- Qwen model family;
- image live;
- throughput/parallel/session settings;
- overnight/stress modes.

## Adapter decision

L3.24 supports a hidden/dev transcript-cleanup adapter plan, not a user-facing integration.

Recommended next lab step before host-app prototype:

```text
L3.25 — Prompt/Validator Tightening for Simple Postprocessing
```
