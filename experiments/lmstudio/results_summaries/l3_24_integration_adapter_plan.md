# L3.24 — Integration Adapter Plan

## Status

This plan defines how the simple postprocessing lane can move toward a host-application integration prototype after local raw-output review.

It does not approve public user exposure.

## Recommended architecture

```text
Host Application
  Application Layer
    SimplePostprocessingService
      LabKit adapter / LM Studio managed client
        LM Studio local model
```

The host application owns UI, product policy, privacy prompts, and storage rules.

LabKit provides the validated adapter contract, prompt/schema choices, and local LM Studio execution boundary.

## 1. Where the adapter lives in the host app

Recommended placement:

```text
application/services/simple_postprocessing_service.py
infrastructure/lmstudio/simple_postprocessing_adapter.py
```

Responsibilities:

- service layer decides whether postprocessing is enabled;
- adapter layer builds the LM Studio request and validates the response;
- UI layer receives only final `clean_text`, never raw prompt/response internals.

## 2. App-facing function/class

### Mode enum

```python
from enum import Enum


class SimplePostprocessingMode(str, Enum):
    TRANSCRIPT_CLEANUP = "transcript_cleanup"
    TERM_NORMALIZATION = "term_normalization"
```

### Service API

```python
result = postprocess_transcript_simple(
    text=raw_transcript,
    mode="transcript_cleanup",
    model="google/gemma-4-e4b",
    context_tier=8192,
)
```

### Output

Success:

```json
{
  "language": "same_as_input",
  "clean_text": "string",
  "warnings": ["string"]
}
```

Fallback:

```json
{
  "language": "same_as_input",
  "clean_text": "<original input>",
  "warnings": ["postprocessing_failed_validation"]
}
```

## 3. Config fields

Recommended hidden/dev config:

```yaml
simple_postprocessing:
  enabled: false
  exposure: dev_hidden
  default_mode: transcript_cleanup
  default_model: google/gemma-4-e4b
  fallback_model: google/gemma-4-e2b
  context_tier: 8192
  retry_policy: off
  schema: simple
  prompt_variant: strict_no_new_facts
  store_raw_prompt: false
  store_raw_response: false
  log_validation_metadata: true
```

If product policy prioritizes resource use over visible cleanup quality, E2B may be tested as a lightweight candidate, but L3.24 does not confirm it as the quality default.

## 4. Prompt selection

Mode-to-prompt mapping:

```text
transcript_cleanup/simple -> strict_no_new_facts
term_normalization/simple -> term_glossary
```

Transcript-cleanup prompt requirements:

- preserve meaning;
- preserve source language or RU/EN mixed technical style;
- reduce ASR noise conservatively;
- do not add facts;
- return JSON only.

Term-normalization prompt requirements:

- normalize only glossary-covered terms;
- preserve Russian or RU/EN mixed language;
- do not translate the whole sentence;
- return JSON only.

L3.24 finding:

```text
term_normalization needs stronger language-preservation prompting before user exposure.
```

## 5. Model selection

L3.22/L3.23 validation result:

```text
E2B and E4B tied on validation reliability.
```

L3.24 raw-output review result:

```text
E4B is better for visible transcript-cleanup quality.
E2B is faster but often near-identity.
```

Hidden/dev adapter recommendation:

```text
quality default: google/gemma-4-e4b
lightweight fallback: google/gemma-4-e2b
```

Do not expose model family selection to users yet.

## 6. Fallback behavior

Fail closed and preserve the original transcript.

Fallback triggers:

- invalid JSON;
- schema mismatch;
- empty `clean_text`;
- language-policy failure;
- reasoning/chain-of-thought leak;
- placeholder text;
- privacy leak;
- blocked mode/model/axis requested;
- timeout or LM Studio unavailable.

Fallback output:

```json
{
  "language": "same_as_input",
  "clean_text": "<original input>",
  "warnings": ["postprocessing_failed_validation"]
}
```

Do not show raw model errors to users.

## 7. Privacy/logging rules

Never persist in normal app logs:

- raw prompt;
- raw response;
- raw transcript;
- raw base URL;
- host name;
- tokens;
- credentials;
- private local paths.

Allowed telemetry:

- mode;
- model key;
- validation status;
- failure category;
- latency bucket;
- input length;
- output length;
- hashes when needed for deduplication.

Local raw-output review packs are allowed only outside the repository, preferably under `/tmp`, and must never be committed.

## 8. UI exposure level

Current accepted exposure:

```text
dev_hidden only
```

Do not expose in public UI yet:

- model selector;
- term-normalization toggle;
- retry selector;
- validation internals;
- blocked schema modes;
- raw output review controls.

Future minimal UI toggle can be considered only after another tightened prompt/validator review passes.

## 9. Tests required before enabling by default

Before enabling by default in the host application:

1. Unit tests for service fallback behavior.
2. Unit tests for JSON/schema validation failure.
3. Tests that raw prompt/response are not logged.
4. Tests for blocked mode/model rejection.
5. Local integration test with LM Studio unavailable.
6. Local integration test with malformed JSON response.
7. Local raw-output review on realistic snippets after prompt/validator tightening.
8. Latency/resource review in the host-app pipeline.

## Integration direction

Accepted first host-app prototype candidate:

```text
mode: transcript_cleanup/simple
model: google/gemma-4-e4b for quality review path
fallback: google/gemma-4-e2b only as lightweight candidate
context_tier: 8192
retry_policy: off
fallback_behavior: original text
logging: privacy-safe metadata only
```

Term normalization:

```yaml
term_normalization:
  enabled: false
  exposure: advanced_operator_only
```

## Still blocked

Do not run or expose:

- blocks;
- paragraphing;
- complex schema;
- 12B;
- 26B;
- Qwen model family;
- image live;
- throughput;
- parallel;
- session/warmup;
- model family selector;
- raw validator internals.

## Next staged direction

The next step should be prompt/validator tightening before a host-app prototype:

```text
L3.25 — Prompt/Validator Tightening for Simple Postprocessing
```

Reason:

- E2B needs a no-op/identity-output diagnostic;
- term normalization needs stronger language-preservation checks;
- E4B looks better for cleanup quality but should be confirmed after prompt tightening.
